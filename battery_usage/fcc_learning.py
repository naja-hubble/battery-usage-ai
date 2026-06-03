"""FCC re-learning audit primitives: high->low->high learning episodes, FCC response
judgment, per-user data-quality gates, FCC-freeze features, and trailing-tail features.

This module is the data layer for the *intervention* classifier (see
``fcc_action_classifier.py``). The question it answers is NOT "predict who freezes"
(the supervised work showed usage behaviour predicts the freeze at AUC~=0.54, i.e.
barely better than chance — see PROJECT_STATUS.md). Instead it AUDITS, per user, the
mechanistic relationship:

    Did the smart gauge get a *learning opportunity* (a deep full-range discharge +
    recharge), and if so, did fullChargeCapacity (FCC) actually *respond* (step) within
    a 24h / 72h / 168h window afterwards?

A user who never gets the opportunity is a candidate for a GAUGE RESET / calibration
prompt; a user who gets repeated opportunities yet whose FCC never responds is a
candidate for a FW/BIOS/EC version check. Hardware identity (device_model, batt_vendor,
batt_fru) is DELIBERATELY NOT used anywhere in this module — it is for post-hoc
enrichment only (a directive carried over from classify_reason.py).

Telemetry semantics (verified, see PROJECT_STATUS.md):
  * ``remainingCapacityInPercentage`` IS RSOC (0-100, integer in this cohort).
  * ``fullChargeCapacity`` (FCC, mWh integer) drives SoH; SoH steps iff FCC steps.
  * ``acdcMode`` 1=AC, 0=on battery. Duplicate timestamps: keep the LAST row.

All numeric thresholds live in :class:`FccLearningConfig` / the module constants below
so there are no magic numbers scattered through the logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .features import sample_weights

# --------------------------------------------------------------------------- #
# Episode definitions (high -> low -> high RSOC excursions = learning chances)
# --------------------------------------------------------------------------- #
# name -> (high_threshold, low_threshold). A full-range discharge+recharge is the
# canonical event on which a smart gauge re-learns FCC.
EPISODE_THRESHOLDS: Dict[str, Tuple[int, int]] = {
    "strict_90_10_90": (90, 10),
    "primary_80_20_80": (80, 20),
    "secondary_85_15_85": (85, 15),
}
PRIMARY_THRESHOLD = "primary_80_20_80"
STRICT_THRESHOLD = "strict_90_10_90"

# FCC-response look-ahead windows, measured from episode END.
RESPONSE_WINDOWS_H: Tuple[int, ...] = (24, 72, 168)

EPISODE_QUALITY_ORDER = ["ok", "large_gap", "missing_fcc", "invalid_order"]


@dataclass(frozen=True)
class FccLearningConfig:
    """All tunable thresholds for the audit layer (no magic numbers downstream)."""

    # ---- FCC change detection ----
    fcc_change_min_mwh: float = 1.0      # |delta FCC| >= this (mWh) counts as a step
    fcc_change_pct_design: float = 0.0   # if >0, per-user step threshold = design_mWh * this
                                         # (effective-step sensitivity, spec 1.6); 0 = absolute
    # ---- episode quality ----
    episode_max_gap_h: float = 12.0      # max intra-episode sample gap for quality "ok"
    # ---- data-quality gates (per user) ----
    short_obs_days: float = 120.0        # obs_days < this -> QUALITY_SHORT_OBS
    sparse_p95_gap_h: float = 24.0       # p95 inter-sample gap > this -> QUALITY_SPARSE
    sparse_min_samples: int = 200        # fewer samples than this -> QUALITY_SPARSE
    gap_small_h: float = 6.0             # threshold for gaps_gt6h
    gap_large_h: float = 24.0            # threshold for gaps_gt24h
    # ---- time-weighting / level thresholds ----
    sample_weight_cap_h: float = 2.0     # cap for time-weighted ratios (matches pipeline)
    rsoc_full_pct: float = 99.0          # RSOC >= this == "at full charge"
    rsoc_low_pct: float = 20.0           # RSOC < this == "low"
    rsoc_valid_lo: float = 0.0           # RSOC outside [lo, hi] treated as missing
    rsoc_valid_hi: float = 100.0


DEFAULT_CONFIG = FccLearningConfig()


# --------------------------------------------------------------------------- #
# Episode state machine
# --------------------------------------------------------------------------- #
def extract_high_low_high_episodes(rsoc, high: float, low: float) -> List[Tuple[int, int, int]]:
    """Extract (start, low, end) POSITIONAL indices of every high->low->high excursion.

    Generic in (high, low): pass (80, 20) for the primary band, (70, 30), etc. After an
    episode closes, its closing high is reused as the next episode's opening high (so a
    long sawtooth yields back-to-back episodes). RSOC that is NaN or outside [0, 100] is
    treated as missing and skipped (it neither opens nor closes a state) — abnormal RSOC
    is a data-quality concern, never a learning event.

    Returns indices into the SAME positional order as ``rsoc`` (caller must pass a
    time-sorted, de-duplicated sequence).
    """
    state = "WAIT_HIGH"
    start_idx: Optional[int] = None
    low_idx: Optional[int] = None
    episodes: List[Tuple[int, int, int]] = []

    # Iterating a Python list of scalars is markedly faster than indexing an ndarray
    # element-by-element (this runs over ~3M samples x 3 bands).
    seq = rsoc.tolist() if hasattr(rsoc, "tolist") else list(rsoc)
    for idx, rs in enumerate(seq):
        if rs is None or (isinstance(rs, float) and np.isnan(rs)) or rs < 0 or rs > 100:
            continue  # missing / abnormal RSOC: not a valid state observation

        if state == "WAIT_HIGH":
            if rs >= high:
                start_idx = idx
                state = "WAIT_LOW"
        elif state == "WAIT_LOW":
            if rs <= low:
                low_idx = idx
                state = "WAIT_HIGH_AGAIN"
        elif state == "WAIT_HIGH_AGAIN":
            if rs >= high:
                episodes.append((start_idx, low_idx, idx))
                start_idx = idx          # reuse this high as the next episode's start
                low_idx = None
                state = "WAIT_LOW"
    return episodes


# --------------------------------------------------------------------------- #
# FCC step detection & response judgment
# --------------------------------------------------------------------------- #
def fcc_step_indicator(fcc: np.ndarray, min_mwh: float) -> Tuple[np.ndarray, np.ndarray]:
    """Per-sample (is_step, is_unknown) booleans.

    ``is_step[i]``    True  -> FCC stepped AT sample i vs i-1 (|delta| >= min_mwh, both known)
    ``is_unknown[i]`` True  -> can't tell (sample i or i-1 has a missing FCC)

    The unknown flag is what stops a missing-FCC gap from being silently read as
    "no response" (spec section 11).
    """
    n = len(fcc)
    is_step = np.zeros(n, dtype=bool)
    is_unknown = np.zeros(n, dtype=bool)
    if n < 2:
        return is_step, is_unknown
    prev = fcc[:-1]
    cur = fcc[1:]
    nan_pair = np.isnan(prev) | np.isnan(cur)
    is_unknown[1:] = nan_pair
    delta = np.where(nan_pair, 0.0, np.abs(cur - prev))
    is_step[1:] = (~nan_pair) & (delta >= min_mwh)
    return is_step, is_unknown


def _changed_in_window(
    ts_ns: np.ndarray, fcc: np.ndarray, is_step: np.ndarray,
    t0_ns: int, t1_ns: int,
) -> Optional[bool]:
    """Did FCC step at any sample STRICTLY AFTER t0, up to and including t1?

    Callers always pass t0 = the episode START timestamp. We use ``side="right"`` for the
    lower bound so a step that lands exactly ON the start sample is EXCLUDED: such a step
    (``is_step[start_idx]`` = a change between start_idx-1 and start_idx) completed as the
    episode opened, i.e. BEFORE its discharge/recharge learning event, and must not be
    misattributed to the episode (spec section 6: "changed BETWEEN episode start and end").
    Counting it would spuriously raise the response rate and mask a genuine non-response,
    suppressing legitimate FW-check candidacy.

    Returns True/False, or None ("unknown") when the window's FCC coverage is incomplete
    (missing FCC inside, or the start-sample baseline that the first step is measured
    against is missing) — so callers never count an unknown as a zero response.
    """
    lo = int(np.searchsorted(ts_ns, t0_ns, side="right"))  # first sample strictly after t0
    hi = int(np.searchsorted(ts_ns, t1_ns, side="right"))  # exclusive upper
    if hi <= lo:
        return None  # no samples strictly after the start within the window -> can't judge
    if np.isnan(fcc[lo:hi]).any():
        return None
    if lo == 0 or np.isnan(fcc[lo - 1]):
        return None  # the start-sample baseline for the first eligible step is missing
    return bool(is_step[lo:hi].any())


def _response_status(complete: bool, changed: Optional[bool]) -> str:
    """Map (window completeness, observed change) -> responded / no_response / censored / unknown.

    A KNOWN change is ``responded`` regardless of completeness (we already saw the
    response). A non-change is ``no_response`` ONLY if the full window was observed; if the
    window runs past last_ts it is ``censored`` (the unobserved tail might still respond).
    Missing FCC -> ``unknown``. ``censored`` and ``unknown`` must NEVER be read as
    no_response (spec section 1.2).
    """
    if changed is None:
        return "unknown"
    if changed:
        return "responded"
    return "no_response" if complete else "censored"


def episode_fcc_response(
    ts_ns: np.ndarray, fcc: np.ndarray, is_step: np.ndarray,
    start_idx: int, end_idx: int, last_ts_ns: int,
    windows_h: Tuple[int, ...] = RESPONSE_WINDOWS_H,
) -> Dict[str, object]:
    """FCC response of one episode: during the episode and within end+{24,72,168}h.

    The look-ahead window starts at the episode START (so a mid-episode step counts) and
    ends at episode_end + W. ``window_{w}h_complete`` records whether that window finished
    on or before the user's last sample; if not, a non-response is ``censored`` rather than
    ``no_response`` (spec sections 1.2 / 6).
    """
    start_ns = int(ts_ns[start_idx])
    end_ns = int(ts_ns[end_idx])
    out: Dict[str, object] = {
        "fcc_changed_during_episode": _changed_in_window(ts_ns, fcc, is_step, start_ns, end_ns),
    }
    hour_ns = int(3600 * 1_000_000_000)
    for w in windows_h:
        win_end = end_ns + int(w) * hour_ns
        complete = win_end <= int(last_ts_ns)
        changed = _changed_in_window(ts_ns, fcc, is_step, start_ns, win_end)
        out[f"fcc_changed_{w}h"] = changed
        out[f"response_window_end_ts_{w}h"] = pd.Timestamp(win_end)
        out[f"window_{w}h_complete"] = bool(complete)
        out[f"fcc_response_status_{w}h"] = _response_status(complete, changed)
    return out


def episode_quality(
    ts_ns: np.ndarray, fcc: np.ndarray, rsoc: np.ndarray,
    start_idx: int, low_idx: int, end_idx: int,
    window_end_ns: int, cfg: FccLearningConfig = DEFAULT_CONFIG,
) -> Tuple[str, float]:
    """Episode quality label + max intra-episode gap (hours).

    Priority: invalid_order > missing_fcc > large_gap > ok. RSOC missingness is also
    folded into missing_fcc (abnormal/NaN RSOC inside the episode). The FCC check spans
    the episode AND the response look-ahead window (window_end_ns), since a missing FCC
    in the look-ahead would corrupt the response judgment too.
    """
    if not (start_idx < low_idx < end_idx):
        return "invalid_order", float("nan")

    seg = slice(start_idx, end_idx + 1)
    gaps_h = np.diff(ts_ns[seg]) / 3.6e12  # ns -> hours
    max_gap_h = float(gaps_h.max()) if gaps_h.size else 0.0

    # FCC coverage over episode + look-ahead window.
    win_hi = int(np.searchsorted(ts_ns, window_end_ns, side="right"))
    fcc_missing = bool(np.isnan(fcc[start_idx:max(win_hi, end_idx + 1)]).any())
    rsoc_seg = rsoc[seg]
    rsoc_missing = bool(np.isnan(rsoc_seg).any() or ((rsoc_seg < 0) | (rsoc_seg > 100)).any())

    if fcc_missing or rsoc_missing:
        return "missing_fcc", max_gap_h
    if max_gap_h > cfg.episode_max_gap_h:
        return "large_gap", max_gap_h
    return "ok", max_gap_h


# --------------------------------------------------------------------------- #
# Per-user processing (one pass over the user's sorted, de-duplicated samples)
# --------------------------------------------------------------------------- #
def _sorted_unique(g: pd.DataFrame) -> pd.DataFrame:
    """Time-sort and keep the LAST row per duplicate timestamp (spec section 6).

    ``kind="stable"`` (mergesort) preserves input order among equal timestamps, so
    ``keep="last"`` deterministically retains the truly last-arriving source row rather
    than whatever an unstable sort happened to place last. (This cohort has 0 duplicate
    timestamps, so the dedup branch never fires today; the stable sort makes the intent
    correct should a future ingest ever introduce same-timestamp rows.)
    """
    g = g.sort_values("timestamp", kind="stable")
    dup = g["timestamp"].duplicated(keep="last")
    return g.loc[~dup] if dup.any() else g


def _quality_metrics(g: pd.DataFrame, n_dupes: int, cfg: FccLearningConfig) -> Dict[str, object]:
    ts = g["timestamp"]
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    n = len(g)
    first_ts, last_ts = ts.iloc[0], ts.iloc[-1]
    obs_days = (last_ts - first_ts).total_seconds() / 86400.0
    diffs_h = ts.diff().dt.total_seconds().to_numpy()[1:] / 3600.0
    sn_distinct = int(g["serialNumber"].nunique()) if "serialNumber" in g else 1
    cyc_dec = int((np.diff(cyc) < 0).sum()) if n > 1 else 0

    q: Dict[str, object] = {
        "n_samples": int(n),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "obs_days": round(float(obs_days), 2),
        "median_interval_h": round(float(np.nanmedian(diffs_h)), 3) if diffs_h.size else float("nan"),
        "p95_interval_h": round(float(np.nanpercentile(diffs_h, 95)), 3) if diffs_h.size else float("nan"),
        "gaps_gt6h": int((diffs_h > cfg.gap_small_h).sum()) if diffs_h.size else 0,
        "gaps_gt24h": int((diffs_h > cfg.gap_large_h).sum()) if diffs_h.size else 0,
        "duplicate_timestamp_count": int(n_dupes),
        "cycle_decrease_count": cyc_dec,
        "fcc_missing_count": int(np.isnan(fcc).sum() + (fcc <= 0).sum()),
        "rsoc_missing_count": int(np.isnan(rsoc).sum() + ((rsoc < 0) | (rsoc > 100)).sum()),
        "serial_number_distinct": sn_distinct,
    }
    q["data_quality_label"] = _quality_label(q, cfg)
    return q


def _quality_label(q: Dict[str, object], cfg: FccLearningConfig) -> str:
    """Single descriptive quality bucket (most severe data-integrity issue first)."""
    if q["serial_number_distinct"] > 1:
        return "QUALITY_PACK_CHANGE_OR_ID_CHANGE"
    if q["cycle_decrease_count"] > 0:
        return "QUALITY_COUNTER_RESET"
    p95 = q["p95_interval_h"]
    if (pd.notna(p95) and p95 > cfg.sparse_p95_gap_h) or q["n_samples"] < cfg.sparse_min_samples:
        return "QUALITY_SPARSE"
    if q["obs_days"] < cfg.short_obs_days:
        return "QUALITY_SHORT_OBS"
    return "QUALITY_OK"


def _user_min_mwh(g: pd.DataFrame, cfg: FccLearningConfig) -> float:
    """Per-user FCC step threshold (mWh). Absolute by default; if ``fcc_change_pct_design``
    is set, scale by the user's design capacity (recovered from FCC and soh_design_pct)."""
    if cfg.fcc_change_pct_design <= 0:
        return cfg.fcc_change_min_mwh
    if "soh_design_pct" not in g:
        return cfg.fcc_change_min_mwh
    soh = g["soh_design_pct"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    m = (soh > 0) & np.isfinite(soh) & np.isfinite(fcc)
    if not m.any():
        return cfg.fcc_change_min_mwh
    design = float(np.nanmedian(fcc[m] * 100.0 / soh[m]))
    return max(1.0, design * cfg.fcc_change_pct_design) if np.isfinite(design) else cfg.fcc_change_min_mwh


def _fcc_features(g: pd.DataFrame, obs_days: float, cfg: FccLearningConfig) -> Dict[str, object]:
    """FCC-freeze features + the trailing flat-tail anchor (last_fcc_change_ts)."""
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    ts = g["timestamp"].to_numpy()
    cyc = g["cycleCount"].to_numpy(dtype=float)
    soh = g["soh_design_pct"].to_numpy(dtype=float) if "soh_design_pct" in g else None

    min_mwh = _user_min_mwh(g, cfg)
    is_step, _ = fcc_step_indicator(fcc, min_mwh)
    delta = np.diff(fcc)
    valid = ~(np.isnan(fcc[1:]) | np.isnan(fcc[:-1]))
    pos = int(((delta >= min_mwh) & valid).sum())
    neg = int(((delta <= -min_mwh) & valid).sum())
    n_changes = int(is_step.sum())

    # Last FCC change anchors the flat tail. If FCC never changed, the *entire*
    # observation is the tail (spec section 7) -> anchor at first_ts.
    step_pos = np.flatnonzero(is_step)
    if step_pos.size:
        last_change_ts = pd.Timestamp(ts[step_pos[-1]])
    else:
        last_change_ts = pd.Timestamp(ts[0])
    last_ts = pd.Timestamp(ts[-1])
    flat_tail_days = (last_ts - last_change_ts) / np.timedelta64(1, "D")

    cyc_delta = float(np.nanmax(cyc) - np.nanmin(cyc)) if np.isfinite(cyc).any() else float("nan")
    years = obs_days / 365.25 if obs_days > 0 else None
    f: Dict[str, object] = {
        "fcc_start": float(fcc[0]),
        "fcc_end": float(fcc[-1]),
        "fcc_min": float(np.nanmin(fcc)),
        "fcc_max": float(np.nanmax(fcc)),
        "fcc_distinct": int(pd.Series(fcc).nunique()),
        "fcc_changes": n_changes,
        "fcc_pos_changes": pos,
        "fcc_neg_changes": neg,
        "last_fcc_change_ts": last_change_ts,
        "flat_tail_days": round(float(flat_tail_days), 1),
        "fcc_change_rate_per_100d": round(n_changes / obs_days * 100, 3) if obs_days > 0 else float("nan"),
        "cycle_start": float(np.nanmin(cyc)) if np.isfinite(cyc).any() else float("nan"),
        "cycle_end": float(np.nanmax(cyc)) if np.isfinite(cyc).any() else float("nan"),
        "cycle_delta": round(cyc_delta, 1),
        "cycles_per_year": round(cyc_delta / years, 2) if years else float("nan"),
        "fcc_changes_per_100_cycles": round(n_changes / max(cyc_delta, 1e-9) * 100, 3),
        # Effective-step counts (spec 1.6): many FCC steps are tiny (~58% < 50 mWh), so an
        # |delta|>=50/100 mWh view of "real" updates is reported alongside any-change.
        "fcc_effective_changes_50mwh": int(fcc_step_indicator(fcc, 50.0)[0].sum()),
        "fcc_effective_changes_100mwh": int(fcc_step_indicator(fcc, 100.0)[0].sum()),
    }
    if soh is not None and np.isfinite(soh).any():
        soh_end = float(soh[~np.isnan(soh)][-1])
        f["soh_span_pct"] = round(float(np.nanmax(soh) - np.nanmin(soh)), 3)
        f["soh_end_pct"] = round(soh_end, 3)
        f["near_design_plateau"] = bool(abs(soh_end - 100) <= 2 and n_changes == 0)
        f["near_101_plateau"] = bool(100.8 <= soh_end <= 101.2 and n_changes == 0)
    else:
        f["soh_span_pct"] = float("nan")
        f["soh_end_pct"] = float("nan")
        f["near_design_plateau"] = False
        f["near_101_plateau"] = False
    return f


def extract_user_episodes(
    g: pd.DataFrame, uid: str, cfg: FccLearningConfig = DEFAULT_CONFIG,
) -> List[Dict[str, object]]:
    """All learning episodes (3 thresholds) for one user, with FCC response + quality.

    ``g`` must be time-sorted & de-duplicated. Indices reported are POSITIONAL within
    ``g`` (start_idx/low_idx/end_idx), matching the audited ordering.
    """
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ts = g["timestamp"]
    ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ts_ns = int(ts_ns[-1])
    is_step, _ = fcc_step_indicator(fcc, _user_min_mwh(g, cfg))

    rows: List[Dict[str, object]] = []
    for name, (high, low) in EPISODE_THRESHOLDS.items():
        for (s, lo, e) in extract_high_low_high_episodes(rsoc, high, low):
            resp = episode_fcc_response(ts_ns, fcc, is_step, s, e, last_ts_ns)
            win_end_ns = int(ts_ns[e]) + max(RESPONSE_WINDOWS_H) * 3600 * 1_000_000_000
            qual, max_gap = episode_quality(ts_ns, fcc, rsoc, s, lo, e, win_end_ns, cfg)
            row: Dict[str, object] = {
                "user_id": uid,
                "threshold_name": name,
                "start_ts": ts.iloc[s], "low_ts": ts.iloc[lo], "end_ts": ts.iloc[e],
                "start_idx": int(s), "low_idx": int(lo), "end_idx": int(e),
                "start_rsoc": float(rsoc[s]), "low_rsoc": float(rsoc[lo]), "end_rsoc": float(rsoc[e]),
                "cycle_delta_episode": round(float(cyc[e] - cyc[s]), 1),
                "fcc_start": float(fcc[s]), "fcc_end": float(fcc[e]),
                "max_gap_h_in_episode": round(max_gap, 3) if pd.notna(max_gap) else float("nan"),
                "episode_quality": qual,
            }
            # Delay (h) from episode END to the first FCC step strictly AFTER episode start
            # (the responded change). Used for the response-delay CDF (spec 2.3). NaN if no
            # step ever follows within the observation.
            post = np.flatnonzero(is_step[s + 1:])
            if post.size:
                fs = s + 1 + int(post[0])
                row["response_delay_h"] = round(float((ts_ns[fs] - ts_ns[e]) / 3.6e12), 3)
            else:
                row["response_delay_h"] = float("nan")
            row.update(resp)
            rows.append(row)
    return rows


def _tail_features(
    g: pd.DataFrame, episodes: List[Dict[str, object]],
    last_fcc_change_ts: pd.Timestamp, cfg: FccLearningConfig,
) -> Dict[str, object]:
    """Features over the trailing window since the LAST FCC change (the flat tail).

    An episode "belongs to the tail" when it STARTS at/after last_fcc_change_ts (its
    learning chance occurred during the flat run, so a non-response there is a genuinely
    missed update). Response rates are computed only over OK-quality tail episodes whose
    response is KNOWN (None/unknown responses are excluded from both numerator and
    denominator, never counted as zero).
    """
    ts = g["timestamp"]
    tail_mask = (ts >= last_fcc_change_ts).to_numpy()
    tg = g.loc[tail_mask]
    rsoc = tg["remainingCapacityInPercentage"].to_numpy(dtype=float)
    cyc = tg["cycleCount"].to_numpy(dtype=float)
    out: Dict[str, object] = {}

    if len(tg) >= 1:
        tail_days = (tg["timestamp"].iloc[-1] - tg["timestamp"].iloc[0]).total_seconds() / 86400.0
        out["tail_days"] = round(float(tail_days), 1)
        cyc_delta = float(np.nanmax(cyc) - np.nanmin(cyc)) if np.isfinite(cyc).any() else float("nan")
        out["tail_cycle_delta"] = round(cyc_delta, 1)
        years = tail_days / 365.25 if tail_days > 0 else None
        out["tail_cycles_per_year"] = round(cyc_delta / years, 2) if years else float("nan")
        valid_r = rsoc[(rsoc >= 0) & (rsoc <= 100)]
        out["tail_min_rsoc"] = float(np.nanmin(valid_r)) if valid_r.size else float("nan")
        out["tail_max_rsoc"] = float(np.nanmax(valid_r)) if valid_r.size else float("nan")
        out["tail_rsoc_swing"] = (out["tail_max_rsoc"] - out["tail_min_rsoc"]
                                  if valid_r.size else float("nan"))
        w = sample_weights(tg["timestamp"], cfg.sample_weight_cap_h)
        tw = w.sum()
        ac = (tg["acdcMode"] == 1).to_numpy()
        out["tail_ac_time_ratio"] = round(float(w[ac].sum() / tw), 4) if tw > 0 else float("nan")
        out["tail_full_time_ratio"] = (round(float(w[rsoc >= cfg.rsoc_full_pct].sum() / tw), 4)
                                       if tw > 0 else float("nan"))
        out["tail_below20_time_ratio"] = (round(float(w[rsoc < cfg.rsoc_low_pct].sum() / tw), 4)
                                          if tw > 0 else float("nan"))
    else:
        for k in ("tail_days", "tail_cycle_delta", "tail_cycles_per_year", "tail_min_rsoc",
                  "tail_max_rsoc", "tail_rsoc_swing", "tail_ac_time_ratio",
                  "tail_full_time_ratio", "tail_below20_time_ratio"):
            out[k] = float("nan")

    # Episode counts & response rates, tail-scoped and total-scoped. ok / large_gap / any
    # are reported separately (spec 1.3) so a GAUGE "no opportunity" gate can require zero
    # large-gap opportunities too (else a gappy full-range discharge is wrongly ignored).
    # Response rates are computed at every look-ahead window for the window sensitivity.
    for name in EPISODE_THRESHOLDS:
        s = _short(name)
        eps = [e for e in episodes if e["threshold_name"] == name]
        tail_eps = [e for e in eps if e["start_ts"] >= last_fcc_change_ts]
        tail_ok = [e for e in tail_eps if e["episode_quality"] == "ok"]
        tail_lg = [e for e in tail_eps if e["episode_quality"] == "large_gap"]
        total_ok = [e for e in eps if e["episode_quality"] == "ok"]
        total_lg = [e for e in eps if e["episode_quality"] == "large_gap"]
        out[f"tail_n_{s}_ok"] = len(tail_ok)
        out[f"tail_n_{s}_large_gap"] = len(tail_lg)
        out[f"tail_n_{s}_any"] = len(tail_eps)
        out[f"tail_n_{s}_any_quality"] = len(tail_eps)   # backward-compat alias
        out[f"total_n_{s}_ok"] = len(total_ok)
        out[f"total_n_{s}_large_gap"] = len(total_lg)
        out[f"total_n_{s}_any"] = len(eps)
        # Right-censoring aware tail counts (spec 1.4) at every window: unresponded == OK +
        # complete window + observed no FCC change; censored == OK but the window ran past
        # last_ts. Computed per window so the response-window sensitivity can swap horizons.
        for w in RESPONSE_WINDOWS_H:
            out[f"tail_n_unresponded_{s}_complete_window_{w}h"] = sum(
                1 for e in tail_ok if e[f"fcc_response_status_{w}h"] == "no_response")
            out[f"tail_n_censored_{s}_{w}h"] = sum(
                1 for e in tail_ok if e[f"fcc_response_status_{w}h"] == "censored")
            out[f"tail_response_rate_{s}_{w}h"] = _response_rate(tail_ok, f"fcc_changed_{w}h")
            out[f"total_response_rate_{s}_{w}h"] = _response_rate(total_ok, f"fcc_changed_{w}h")
        # Canonical 72h aliases (the spec-named columns used by the default classifier/CSV).
        out[f"tail_n_unresponded_{s}_complete_window"] = out[f"tail_n_unresponded_{s}_complete_window_72h"]
        out[f"tail_n_censored_{s}"] = out[f"tail_n_censored_{s}_72h"]

    # "Relevant" response rate for the medium FW rule: prefer the primary band, fall
    # back to the strict band when the primary has no judgeable tail episodes.
    for w in RESPONSE_WINDOWS_H:
        rel = out[f"tail_response_rate_80_20_80_{w}h"]
        if pd.isna(rel):
            rel = out[f"tail_response_rate_90_10_90_{w}h"]
        out[f"relevant_response_rate_{w}h"] = rel
    return out


def _short(name: str) -> str:
    """strict_90_10_90 -> 90_10_90, primary_80_20_80 -> 80_20_80 (column-name friendly)."""
    return name.split("_", 1)[1]


def _response_rate(ok_episodes: List[Dict[str, object]], key: str) -> float:
    """Fraction of OK episodes with a KNOWN True response. NaN if none are judgeable."""
    known = [e for e in ok_episodes if e[key] is not None]
    if not known:
        return float("nan")
    return round(sum(1 for e in known if e[key]) / len(known), 4)


def process_user(
    uid: str, g: pd.DataFrame, cfg: FccLearningConfig = DEFAULT_CONFIG,
) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    """One pass over a user's samples -> (feature row, list of episode rows).

    Composes quality gates + FCC-freeze features + episodes + tail features. The caller
    (analyze_fcc_learning_actions.py) groups the cohort by user_id and calls this once
    per user, so the multi-million-row frame is traversed a single time.
    """
    n_before = len(g)
    g = _sorted_unique(g)
    n_dupes = n_before - len(g)

    quality = _quality_metrics(g, n_dupes, cfg)
    fcc = _fcc_features(g, float(quality["obs_days"]), cfg)
    episodes = extract_user_episodes(g, uid, cfg)
    tail = _tail_features(g, episodes, fcc["last_fcc_change_ts"], cfg)

    feat: Dict[str, object] = {"user_id": uid}
    feat.update(quality)
    feat.update(fcc)
    feat.update(tail)
    return feat, episodes
