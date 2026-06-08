"""Online high->low->high learning-episode detector for the 30-day sliding-window
FCC-response monitor (rolling30 spec sections 5, 7).

This is the rolling/online re-implementation of the audit primitives in
``fcc_learning.py``. The *question* is unchanged — did a full-range discharge+recharge
learning opportunity occur, and did ``fullChargeCapacity`` (FCC) effectively respond
afterwards? — but two things differ from the long-history audit:

  * **Effective FCC step** is configurable (``any_change`` ... ``abs_ge_0p5pct_design``)
    and defaults to ``abs_ge_50mWh``: in 30-day operation a micro 1 mWh wobble must not
    be read as a learning response and mask a genuine no-response (spec 5.3).
  * **Response window is anchored at the episode END** (``[end, end+W]``, spec 7.4), not
    at the episode start as in the audit layer. A change strictly before the recharge
    completes is part of the discharge/recharge, not a response to the completed cycle.

Two detector flavours share this state machine:
  * ``extract_episodes_causal`` — one forward pass over the user's whole series. The
    derived state it feeds (``online_state.py``) is allowed to persist long-term, so this
    is the **stateful** detector and it sees episodes that straddle 30-day boundaries.
  * ``extract_episodes_in_window`` — runs the same machine on ONLY the raw samples inside
    one ``[t-29d, t]`` window. An episode whose opening high predates the window is never
    re-opened, so it is missed (or flagged ``window_left_truncated``). This is the
    **stateless** comparison detector (spec 0.3 / 16.3).

Hardware identity is never read here (spec 0.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import (
    EPISODE_THRESHOLDS,
    PRIMARY_THRESHOLD,
    STRICT_THRESHOLD,
    extract_high_low_high_episodes,
    fcc_step_indicator,
    _sorted_unique,
)

SECONDARY_THRESHOLD = "secondary_85_15_85"

# Response look-ahead windows (hours), measured from episode END. 72h is primary.
RESPONSE_WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
PRIMARY_RESPONSE_WINDOW_H = 72

# --------------------------------------------------------------------------- #
# Effective FCC-step definitions (spec 5.3). Each maps to an absolute mWh threshold,
# resolved per user (the percent-of-design variants need the user's design capacity).
# --------------------------------------------------------------------------- #
EFFECTIVE_STEP_DEFS: Tuple[str, ...] = (
    "any_change",
    "abs_ge_50mWh",
    "abs_ge_100mWh",
    "abs_ge_0p1pct_design",
    "abs_ge_0p5pct_design",
)
DEFAULT_EFFECTIVE_STEP = "abs_ge_50mWh"


def step_threshold_mwh(step_def: str, design_mwh: Optional[float]) -> float:
    """Resolve an effective-step definition to an absolute mWh threshold for one user.

    ``any_change`` -> 1 mWh (FCC is an integer, so >=1 is any change). The percent-design
    variants fall back to 1 mWh when design capacity is unknown (so they degrade to
    any_change rather than silently masking every change).
    """
    if step_def == "any_change":
        return 1.0
    if step_def == "abs_ge_50mWh":
        return 50.0
    if step_def == "abs_ge_100mWh":
        return 100.0
    if step_def in ("abs_ge_0p1pct_design", "abs_ge_0p5pct_design"):
        if design_mwh is None or not np.isfinite(design_mwh) or design_mwh <= 0:
            return 1.0
        pct = 0.001 if step_def.endswith("0p1pct_design") else 0.005
        return max(1.0, float(design_mwh) * pct)
    raise ValueError(f"unknown effective step definition: {step_def!r}")


def recover_design_mwh(g: pd.DataFrame) -> float:
    """Per-user design capacity (mWh) recovered from FCC and soh_design_pct.

    ``soh_design_pct = FCC * 100 / design`` (PROJECT_STATUS 2.1) so
    ``design = median(FCC * 100 / soh_design_pct)``. user_master's
    ``design_capacity_mAh`` is unit-ambiguous, so the in-band recovery is preferred.
    Returns NaN when it cannot be recovered.
    """
    if "soh_design_pct" not in g.columns:
        return float("nan")
    soh = g["soh_design_pct"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    m = (soh > 0) & np.isfinite(soh) & np.isfinite(fcc) & (fcc > 0)
    if not m.any():
        return float("nan")
    return float(np.nanmedian(fcc[m] * 100.0 / soh[m]))


@dataclass(frozen=True)
class OnlineConfig:
    """All tunable thresholds for the rolling30 online detector (no magic numbers)."""

    window_days: int = 30
    stride_days: int = 1
    effective_step: str = DEFAULT_EFFECTIVE_STEP
    response_window_hours: int = PRIMARY_RESPONSE_WINDOW_H
    episode_max_gap_hours: float = 12.0
    # window data-quality gates (spec 6.2)
    window_min_obs_days: float = 7.0       # obs_days_in_window < this -> SHORT_OBS
    window_min_samples: int = 20           # n_samples_30d < this -> SHORT_OBS
    window_sparse_p95_gap_h: float = 24.0  # p95 interval > this -> SPARSE
    gap_small_h: float = 6.0
    gap_mid_h: float = 12.0
    gap_large_h: float = 24.0
    sample_weight_cap_h: float = 2.0
    rsoc_valid_lo: float = 0.0
    rsoc_valid_hi: float = 100.0
    # state / policy horizons (spec 12)
    fw_days_since_change_min: float = 90.0
    gauge_days_since_change_min: float = 90.0
    fw_cycles_since_change_min: float = 30.0


DEFAULT_ONLINE_CONFIG = OnlineConfig()

HOUR_NS = 3600 * 1_000_000_000
DAY_NS = 86_400 * 1_000_000_000


# --------------------------------------------------------------------------- #
# Response judgement (END-anchored; spec 7.4)
# --------------------------------------------------------------------------- #
def _response_status(complete: bool, changed: Optional[bool]) -> str:
    """(window completeness, observed change) -> responded / no_response / censored / unknown.

    A KNOWN change is ``responded`` regardless of completeness. A non-change is
    ``no_response`` only when the whole window was observed (complete); otherwise the
    unobserved tail might still respond -> ``censored``. Missing FCC -> ``unknown``.
    ``censored`` and ``unknown`` are NEVER read as ``no_response`` (spec 0.4, 7.4).
    """
    if changed is None:
        return "unknown"
    if changed:
        return "responded"
    return "no_response" if complete else "censored"


def _changed_after_end(
    ts_ns: np.ndarray, fcc: np.ndarray, is_step: np.ndarray,
    end_idx: int, win_end_ns: int,
) -> Optional[bool]:
    """Did FCC effectively step at any sample in ``[end_ts, win_end_ns]``?

    The lower bound is the episode END sample itself (``side="left"`` lands on end_idx),
    so a step AT the recharge-completion sample (the gauge re-learning at full charge)
    counts; a step strictly before the recharge completed does not (its ts < end_ts).
    Returns None ("unknown") if FCC coverage in the window is incomplete.
    """
    lo = int(np.searchsorted(ts_ns, ts_ns[end_idx], side="left"))   # == end_idx
    hi = int(np.searchsorted(ts_ns, win_end_ns, side="right"))      # exclusive upper
    if hi <= lo:
        return None
    if np.isnan(fcc[lo:hi]).any():
        return None
    if np.isnan(fcc[lo]):              # the end-sample baseline for the first step is missing
        return None
    return bool(is_step[lo:hi].any())


def episode_response(
    ts_ns: np.ndarray, fcc: np.ndarray, is_step: np.ndarray,
    end_idx: int, last_ts_ns: int, windows_h: Tuple[int, ...] = RESPONSE_WINDOWS_H,
) -> Dict[str, object]:
    """Response status for one episode at every look-ahead window, plus the
    timestamp of the first effective step in the primary (72h... actually any) window
    used by the online state machine to resolve 'responded' vs 'no_response'.
    """
    end_ns = int(ts_ns[end_idx])
    out: Dict[str, object] = {}
    for w in windows_h:
        win_end = end_ns + int(w) * HOUR_NS
        complete = win_end <= int(last_ts_ns)
        changed = _changed_after_end(ts_ns, fcc, is_step, end_idx, win_end)
        out[f"response_status_{w}h"] = _response_status(complete, changed)
        out[f"window_{w}h_complete"] = bool(complete)
        out[f"response_window_end_ts_{w}h"] = pd.Timestamp(win_end)
    # First effective step strictly at/after the END sample anywhere in the observation
    # (used to date the 'responded' resolution; capped to the response window by callers).
    post = np.flatnonzero(is_step[end_idx:])
    if post.size:
        first_post_idx = end_idx + int(post[0])
        out["first_post_end_step_ts"] = pd.Timestamp(int(ts_ns[first_post_idx]))
        out["response_delay_h"] = round(float((ts_ns[first_post_idx] - end_ns) / 3.6e12), 3)
    else:
        out["first_post_end_step_ts"] = pd.NaT
        out["response_delay_h"] = float("nan")
    return out


# --------------------------------------------------------------------------- #
# Episode record assembly (quality + geometry; spec 7.3)
# --------------------------------------------------------------------------- #
def _episode_quality(
    ts_ns: np.ndarray, fcc: np.ndarray, rsoc: np.ndarray,
    s: int, lo: int, e: int, max_gap_hours: float,
) -> Tuple[str, float, float]:
    """Quality label + (max gap, median gap) in hours over the episode span [s, e].

    Priority: invalid_order > missing_required_value > large_gap > ok.
    """
    if not (s < lo < e):
        return "invalid_order", float("nan"), float("nan")
    seg = slice(s, e + 1)
    gaps_h = np.diff(ts_ns[seg]) / 3.6e12
    max_gap = float(gaps_h.max()) if gaps_h.size else 0.0
    med_gap = float(np.median(gaps_h)) if gaps_h.size else 0.0
    fcc_missing = bool(np.isnan(fcc[seg]).any())
    rsoc_seg = rsoc[seg]
    rsoc_missing = bool(np.isnan(rsoc_seg).any() or ((rsoc_seg < 0) | (rsoc_seg > 100)).any())
    if fcc_missing or rsoc_missing:
        return "missing_required_value", max_gap, med_gap
    if max_gap > max_gap_hours:
        return "large_gap", max_gap, med_gap
    return "ok", max_gap, med_gap


def _episode_id(uid: str, threshold: str, start_ns: int, end_ns: int) -> str:
    """Stable, location-independent episode id (spec 7.5 double-count prevention).

    Built from (user, band, start_ts, end_ts) so the SAME physical episode gets the SAME
    id whether it is seen by the causal pass or by an overlapping sliding window.
    """
    return f"{uid}|{threshold}|{start_ns}|{end_ns}"


def _build_records(
    uid: str, threshold: str, episodes_idx: List[Tuple[int, int, int]],
    ts_ns: np.ndarray, ts: pd.Series, rsoc: np.ndarray, fcc: np.ndarray,
    cyc: np.ndarray, is_step: np.ndarray, last_ts_ns: int,
    cfg: OnlineConfig, idx_offset: int = 0,
) -> List[Dict[str, object]]:
    """Turn positional (start, low, end) triples into full episode records."""
    rows: List[Dict[str, object]] = []
    for (s, lo, e) in episodes_idx:
        start_ns, low_ns, end_ns = int(ts_ns[s]), int(ts_ns[lo]), int(ts_ns[e])
        qual, max_gap, med_gap = _episode_quality(ts_ns, fcc, rsoc, s, lo, e,
                                                  cfg.episode_max_gap_hours)
        rec: Dict[str, object] = {
            "episode_id": _episode_id(uid, threshold, start_ns, end_ns),
            "user_id": uid,
            "threshold_name": threshold,
            "start_ts": ts.iloc[s], "low_ts": ts.iloc[lo], "end_ts": ts.iloc[e],
            "start_idx": int(s + idx_offset), "low_idx": int(lo + idx_offset),
            "end_idx": int(e + idx_offset),
            "start_rsoc": float(rsoc[s]), "low_rsoc": float(rsoc[lo]), "end_rsoc": float(rsoc[e]),
            "episode_depth": float(rsoc[s] - rsoc[lo]),
            "start_to_low_duration_h": round((low_ns - start_ns) / 3.6e12, 3),
            "low_to_end_duration_h": round((end_ns - low_ns) / 3.6e12, 3),
            "episode_duration_h": round((end_ns - start_ns) / 3.6e12, 3),
            "cycle_delta_episode": round(float(cyc[e] - cyc[s]), 2),
            "fcc_before_episode": float(fcc[s]),
            "cycle_count_before_episode": float(cyc[s]),
            "n_samples_episode": int(e - s + 1),
            "max_gap_h_episode": round(max_gap, 3) if np.isfinite(max_gap) else float("nan"),
            "median_gap_h_episode": round(med_gap, 3) if np.isfinite(med_gap) else float("nan"),
            "episode_quality": qual,
        }
        rec.update(episode_response(ts_ns, fcc, is_step, e, last_ts_ns))
        rows.append(rec)
    return rows


# --------------------------------------------------------------------------- #
# Causal (stateful) detector — one pass over the whole user series
# --------------------------------------------------------------------------- #
def extract_episodes_causal(
    g: pd.DataFrame, uid: str, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_mwh: Optional[float] = None, inference_last_ts: Optional[pd.Timestamp] = None,
) -> List[Dict[str, object]]:
    """All learning episodes (3 bands) for one user over the full series.

    ``g`` must be time-sorted & de-duplicated (use ``prepare_user``). ``inference_last_ts``
    sets the "current time" for censoring; defaults to the user's last sample (final
    backtest resolution). Response status uses the configured effective-step threshold.
    """
    if design_mwh is None:
        design_mwh = recover_design_mwh(g)
    min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ts = g["timestamp"]
    ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ts_ns = int(ts_ns[-1]) if inference_last_ts is None else int(
        pd.Timestamp(inference_last_ts).value)
    is_step, _ = fcc_step_indicator(fcc, min_mwh)

    rows: List[Dict[str, object]] = []
    for name, (high, low) in EPISODE_THRESHOLDS.items():
        idx = extract_high_low_high_episodes(rsoc, high, low)
        rows.extend(_build_records(uid, name, idx, ts_ns, ts, rsoc, fcc, cyc,
                                   is_step, last_ts_ns, cfg))
    return rows


# --------------------------------------------------------------------------- #
# Stateless detector — episodes wholly inside one [t-29d, t] raw window
# --------------------------------------------------------------------------- #
def extract_episodes_in_window(
    g_window: pd.DataFrame, uid: str, window_end: pd.Timestamp,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG, design_mwh: Optional[float] = None,
    last_observed_ts: Optional[pd.Timestamp] = None,
) -> List[Dict[str, object]]:
    """Episodes detectable from ONLY the raw samples in one window (the stateless view).

    The state machine starts fresh at the window's first sample, so an episode whose
    opening high predates the window cannot be re-opened here — exactly the boundary blind
    spot the stateful detector is meant to cover (spec 16.3). ``last_observed_ts`` is the
    inference-time horizon for censoring (defaults to the window end).
    """
    if len(g_window) < 2:
        return []
    g_window = _sorted_unique(g_window)
    if design_mwh is None:
        design_mwh = recover_design_mwh(g_window)
    last_ts = window_end if last_observed_ts is None else last_observed_ts
    eps = extract_episodes_causal(g_window, uid, cfg, design_mwh=design_mwh,
                                  inference_last_ts=last_ts)
    for e in eps:
        e["detector"] = "stateless"
    return eps


# --------------------------------------------------------------------------- #
# Shared prep
# --------------------------------------------------------------------------- #
def prepare_user(g: pd.DataFrame) -> pd.DataFrame:
    """Time-sort, keep the last row per duplicate timestamp (spec 5.1)."""
    return _sorted_unique(g)


def episodes_to_frame(rows: List[Dict[str, object]]) -> pd.DataFrame:
    cols_order = [
        "episode_id", "user_id", "threshold_name", "start_ts", "low_ts", "end_ts",
        "start_rsoc", "low_rsoc", "end_rsoc", "episode_depth",
        "start_to_low_duration_h", "low_to_end_duration_h", "episode_duration_h",
        "cycle_delta_episode", "n_samples_episode", "max_gap_h_episode",
        "median_gap_h_episode", "episode_quality",
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    front = [c for c in cols_order if c in df.columns]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest]
