"""Dual-track online FCC state (rolling30 v2 spec sections 7, 8, 10.4).

v1 (`online_state.py`) tracked a SINGLE notion of "the last FCC change": the effective
(>= 50 mWh) step. v2 keeps two parallel tracks so the policy can separate a genuine hard
gauge freeze from harmless micro-wobbles (spec 7):

  * **any-change track**  — resets on ANY integer FCC step (>= 1 mWh). Drives
    ``days_since_any_fcc_change`` and the legacy-any active-false-alert basis.
  * **effective track**   — resets on an effective step (>= the configured threshold).
    Drives ``days_since_effective_fcc_change``, the since-last-effective opportunity
    counters, the pending/censored set, and the normative Poisson-binomial anomaly.

An effective step is also an any step, so it resets BOTH tracks; a sub-threshold step
resets only the any track and is tallied as a *micro* step (spec 17.3).

Opportunity counters are **graded by ``quality_tier``** (spec 11): HIGH_OK / MEDIUM_GAP
contribute no_response-capable opportunities (and feed the anomaly when they resolve as
no_response); LOW_LARGE_GAP is ambiguity only and never becomes a no_response. The anomaly
accumulator uses the **normative** per-episode probability ``p_response_normative`` and the
PRIMARY band only (the strict band is nested inside it — mixing double-counts; spec 10.4).

All causal guards from v1 are preserved verbatim in spirit:
  * a no_response deadline is scheduled only if its 72h window is actually observed
    (``end + W <= last_sample``) — a censored episode must never flip to no_response just
    because the end-of-day grid walked past ``end+W`` in wall-clock time (regression #16);
  * each physical episode is counted once (``seen_ids`` keyed on ``episode_id``, spec 7.5);
  * censored/unknown are never counted as no_response.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import fcc_step_indicator
from .online_episode_detector import (
    OnlineConfig, DEFAULT_ONLINE_CONFIG, PRIMARY_THRESHOLD, STRICT_THRESHOLD,
    recover_design_mwh, step_threshold_mwh,
)
from .online_gap_quality import (
    TIER_HIGH, TIER_MEDIUM, TIER_LOW, NO_RESPONSE_CAPABLE_TIERS,
)

HOUR_NS = 3600 * 1_000_000_000
DAY_NS = 86_400 * 1_000_000_000
P_CLIP = (0.001, 0.999)

# Active-flag horizon: a track is "active" if its last change is within this many days.
ACTIVE_FLAG_DAYS = 60.0
# Minimum derived-state span (days) before a long-staleness call is trustworthy (spec 8/9).
STATE_HISTORY_MIN_DAYS = 60.0

# event priorities at equal timestamps (mirror v1): completion before reset before deadline
_PRIO_COMPLETE, _PRIO_RESET, _PRIO_DEADLINE = 0, 1, 2


def _fcc_step_events(g: pd.DataFrame, eff_min_mwh: float
                     ) -> List[Tuple[int, float, float, float, bool]]:
    """(ts_ns, abs_delta_mWh, fcc_value, cycle, is_effective) for every any-change FCC step."""
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    any_step, _ = fcc_step_indicator(fcc, 1.0)
    pos = np.flatnonzero(any_step)
    out = []
    for i in pos:
        delta = abs(float(fcc[i] - fcc[i - 1]))
        out.append((int(ts_ns[i]), delta, float(fcc[i]), float(cyc[i]), delta >= eff_min_mwh))
    return out


class _BandStateV2:
    """Graded since-last-effective-change counters for one RSOC band."""
    __slots__ = ("ok_opp", "medium_opp", "large_opp",
                 "ok_nr", "medium_nr", "pending",
                 "cum_expected", "cum_log_p")

    def __init__(self):
        self.reset()

    def reset(self):
        self.ok_opp = 0          # HIGH_OK opportunities (completed)
        self.medium_opp = 0      # MEDIUM_GAP opportunities
        self.large_opp = 0       # LOW_LARGE_GAP opportunities (ambiguity)
        self.ok_nr = 0           # HIGH_OK confirmed no_response
        self.medium_nr = 0       # MEDIUM_GAP confirmed no_response
        self.pending: Dict[str, Tuple[str, float]] = {}   # eid -> (tier, p_norm)
        self.cum_expected = 0.0
        self.cum_log_p = 0.0     # sum log(1 - clip(p_norm)) over resolved no_response

    @property
    def censored(self) -> int:
        return len(self.pending)

    @property
    def total_nr(self) -> int:
        return self.ok_nr + self.medium_nr


def build_user_dual_state_daily(
    g: pd.DataFrame, uid: str, grid_ends: np.ndarray, episodes: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG, design_mwh: Optional[float] = None,
    default_p: float = 0.5, prob_col: str = "p_response_normative",
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Daily dual-track state rows + any/effective FCC-change audit rows for one user."""
    if design_mwh is None:
        design_mwh = recover_design_mwh(g)
    eff_min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    first_ns, last_ns = int(ts_ns[0]), int(ts_ns[-1])
    win_ns = int(cfg.response_window_hours) * HOUR_NS

    # ---- event list ----
    events: List[Tuple[int, int, str, object]] = []
    for (ts, delta, val, cy, is_eff) in _fcc_step_events(g, eff_min_mwh):
        events.append((ts, _PRIO_RESET, "step", (delta, val, cy, is_eff)))

    seen_ids = set()
    ep = episodes[episodes["threshold_name"].isin([PRIMARY_THRESHOLD, STRICT_THRESHOLD])]
    for r in ep.itertuples(index=False):
        eid = r.episode_id
        if eid in seen_ids:                      # double-count guard (spec 7.5)
            continue
        seen_ids.add(eid)
        band = "primary" if r.threshold_name == PRIMARY_THRESHOLD else "strict"
        end_ns = int(pd.Timestamp(r.end_ts).value)
        tier = getattr(r, "quality_tier", TIER_LOW)
        p_i = getattr(r, prob_col, np.nan)
        if not np.isfinite(p_i):
            p_i = default_p
        events.append((end_ns, _PRIO_COMPLETE, "complete", (band, tier, eid, float(p_i))))
        # schedule a no_response deadline only for no_response-capable tiers AND only if the
        # 72h window is actually observed (else it stays pending == censored; regression #16).
        if tier in NO_RESPONSE_CAPABLE_TIERS and (end_ns + win_ns) <= last_ns:
            events.append((end_ns + win_ns, _PRIO_DEADLINE, "deadline", (band, eid)))
    events.sort(key=lambda e: (e[0], e[1]))

    # ---- running state ----
    bands = {"primary": _BandStateV2(), "strict": _BandStateV2()}
    # effective track
    eff_ts, eff_val, eff_cyc = first_ns, float(fcc[0]), float(cyc[0])
    # any track
    any_ts, any_val, any_cyc = first_ns, float(fcc[0]), float(cyc[0])
    # micro tracking since last effective change
    n_micro = 0
    max_micro = 0.0
    audit: List[Dict[str, object]] = []

    def _apply(ev):
        nonlocal eff_ts, eff_val, eff_cyc, any_ts, any_val, any_cyc, n_micro, max_micro
        _, _, kind, payload = ev
        ts0 = ev[0]
        if kind == "step":
            delta, val, cy, is_eff = payload
            # any track always resets
            any_ts, any_val, any_cyc = ts0, val, cy
            audit.append({"user_id": uid, "change_ts": pd.Timestamp(ts0), "fcc_value": val,
                          "cycle": cy, "abs_delta_mWh": delta, "is_effective": bool(is_eff)})
            if is_eff:
                for b in bands.values():
                    b.reset()
                n_micro = 0
                max_micro = 0.0
                eff_ts, eff_val, eff_cyc = ts0, val, cy
            else:
                n_micro += 1
                max_micro = max(max_micro, delta)
        elif kind == "complete":
            band, tier, eid, p_i = payload
            bs = bands[band]
            if tier == TIER_HIGH:
                bs.ok_opp += 1
                bs.pending[eid] = (tier, p_i)
            elif tier == TIER_MEDIUM:
                bs.medium_opp += 1
                bs.pending[eid] = (tier, p_i)
            elif tier == TIER_LOW:
                bs.large_opp += 1
            # INVALID / unknown: ignored
        elif kind == "deadline":
            band, eid = payload
            bs = bands[band]
            item = bs.pending.pop(eid, None)
            if item is not None:                 # still pending -> confirmed no_response
                tier, p_i = item
                if tier == TIER_HIGH:
                    bs.ok_nr += 1
                else:
                    bs.medium_nr += 1
                if band == "primary":            # anomaly accrues on the primary band only
                    bs.cum_expected += p_i
                    bs.cum_log_p += math.log(1.0 - min(max(p_i, P_CLIP[0]), P_CLIP[1]))

    rows: List[Dict[str, object]] = []
    ei, ne = 0, len(events)
    for end_ns in grid_ends:
        end_ns = int(end_ns)
        while ei < ne and events[ei][0] <= end_ns:
            _apply(events[ei]); ei += 1
        cur_idx = int(np.searchsorted(ts_ns, end_ns, side="right")) - 1
        cur_cyc = float(cyc[cur_idx]) if cur_idx >= 0 else float("nan")
        cur_seen_ts = int(ts_ns[cur_idx]) if cur_idx >= 0 else first_ns
        bp, bsr = bands["primary"], bands["strict"]
        cum_log_p = bp.cum_log_p
        days_since_eff = round((end_ns - eff_ts) / 8.64e13, 3)
        days_since_any = round((end_ns - any_ts) / 8.64e13, 3)
        state_hist_days = round((end_ns - first_ns) / 8.64e13, 3)
        hist_ok = state_hist_days >= STATE_HISTORY_MIN_DAYS
        anomaly = round(-cum_log_p / math.log(10), 4)

        row = {
            "user_id": uid,
            "window_end_date": pd.Timestamp(end_ns).normalize(),
            "state_as_of_ts": pd.Timestamp(end_ns),
            "first_seen_ts": pd.Timestamp(first_ns),
            "last_seen_ts": pd.Timestamp(cur_seen_ts),
            "state_history_days": state_hist_days,
            "state_history_sufficient": bool(hist_ok),
            # ---- effective track ----
            "last_effective_fcc_value": eff_val,
            "last_effective_fcc_change_ts": pd.Timestamp(eff_ts),
            "last_effective_fcc_change_cycle": eff_cyc,
            "days_since_effective_fcc_change": days_since_eff,
            "cycles_since_effective_fcc_change": round(cur_cyc - eff_cyc, 2)
                if np.isfinite(cur_cyc) else float("nan"),
            "effective_active_flag": bool(days_since_eff < ACTIVE_FLAG_DAYS and hist_ok),
            # ---- any-change track ----
            "last_any_fcc_value": any_val,
            "last_any_fcc_change_ts": pd.Timestamp(any_ts),
            "last_any_fcc_change_cycle": any_cyc,
            "days_since_any_fcc_change": days_since_any,
            "cycles_since_any_fcc_change": round(cur_cyc - any_cyc, 2)
                if np.isfinite(cur_cyc) else float("nan"),
            "legacy_any_active_flag": bool(days_since_any < ACTIVE_FLAG_DAYS and hist_ok),
            # ---- micro-step tracking since last effective change ----
            "n_micro_steps_since_effective_change": int(n_micro),
            "max_micro_step_mWh_since_effective_change": round(float(max_micro), 2),
            "micro_wobble_only_since_effective_change": bool(n_micro > 0),
            # ---- graded opportunity counters (primary) ----
            "cum_primary_ok_opportunities_since_last_effective_change": bp.ok_opp,
            "cum_primary_medium_gap_opportunities_since_last_effective_change": bp.medium_opp,
            "cum_primary_large_gap_opportunities_since_last_effective_change": bp.large_opp,
            "cum_primary_ok_no_response_since_last_effective_change": bp.ok_nr,
            "cum_primary_medium_gap_no_response_since_last_effective_change": bp.medium_nr,
            "cum_primary_no_response_since_last_effective_change": bp.total_nr,
            "cum_primary_censored_since_last_effective_change": bp.censored,
            # ---- graded opportunity counters (strict) ----
            "cum_strict_ok_opportunities_since_last_effective_change": bsr.ok_opp,
            "cum_strict_medium_gap_opportunities_since_last_effective_change": bsr.medium_opp,
            "cum_strict_large_gap_opportunities_since_last_effective_change": bsr.large_opp,
            "cum_strict_ok_no_response_since_last_effective_change": bsr.ok_nr,
            "cum_strict_medium_gap_no_response_since_last_effective_change": bsr.medium_nr,
            "cum_strict_no_response_since_last_effective_change": bsr.total_nr,
            "cum_strict_censored_since_last_effective_change": bsr.censored,
            # ---- FW-gate convenience aggregates ----
            "high_quality_no_response_count": bp.ok_nr,
            "censored_count": bp.censored,
            "large_gap_low_quality_count": bp.large_opp,
            "observed_effective_responses_since_last_effective_change": 0,
            # ---- normative cumulative anomaly (primary) ----
            "cum_expected_normative_response": round(bp.cum_expected, 4),
            "cum_observed_effective_response": 0,
            "cum_log_p_all_no_response_since_last_effective_change": round(cum_log_p, 5),
            "cum_normative_fw_anomaly_score": anomaly,
            "cumulative_normative_fw_anomaly_score": anomaly,
            # ---- v1-compatible aliases (so v1 backtest/eval helpers still read the frame) ----
            "days_since_last_effective_fcc_change": days_since_eff,
            "cycles_since_last_effective_fcc_change": round(cur_cyc - eff_cyc, 2)
                if np.isfinite(cur_cyc) else float("nan"),
            "cum_primary_no_response_since_last_fcc_change": bp.total_nr,
            "cum_strict_no_response_since_last_fcc_change": bsr.total_nr,
            "cum_observed_response_since_last_fcc_change": 0,
            "cum_fw_response_anomaly_score": anomaly,
        }
        rows.append(row)
    return rows, audit


def build_dual_online_state(
    df_by_user: Dict[str, pd.DataFrame], episodes: pd.DataFrame, feats: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_by_user: Optional[Dict[str, float]] = None, default_p: float = 0.5,
    prob_col: str = "p_response_normative", progress: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cohort daily dual-track online-state trajectory + FCC-change audit log.

    ``feats`` supplies the per-user grid of window-end timestamps so state joins 1:1 with
    the feature table. ``episodes`` must carry ``quality_tier`` and ``prob_col`` (normative
    per-episode probability) for graded counting and the cumulative anomaly.
    """
    design_by_user = design_by_user or {}
    grid_by_user: Dict[str, np.ndarray] = {}
    for uid, sub in feats.groupby("user_id", sort=False):
        grid_by_user[uid] = sub["window_end_ts"].to_numpy().astype(
            "datetime64[ns]").astype(np.int64)

    eps_by_user = {uid: sub for uid, sub in episodes.groupby("user_id", sort=False)} \
        if not episodes.empty else {}
    state_rows: List[Dict[str, object]] = []
    audit_rows: List[Dict[str, object]] = []
    keys = list(grid_by_user.keys())
    for i, uid in enumerate(keys):
        g = df_by_user[uid]
        grid = grid_by_user[uid]
        ueps = eps_by_user.get(uid, episodes.iloc[0:0])
        sr, ar = build_user_dual_state_daily(
            g, uid, grid, ueps, cfg, design_mwh=design_by_user.get(uid),
            default_p=default_p, prob_col=prob_col)
        state_rows.extend(sr)
        audit_rows.extend(ar)
        if progress and (i + 1) % 100 == 0:
            print(f"  dual online state: {i + 1}/{len(keys)} users", flush=True)
    return pd.DataFrame(state_rows), pd.DataFrame(audit_rows)
