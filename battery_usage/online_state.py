"""Stateful online detector: per-user derived state that may persist long-term even
though raw telemetry is only retained for 30 days (rolling30 spec section 8).

The simulation is an event replay over each user's whole series, but it only ever
*reads* the derived state plus the events as they occur in time order — never future raw
samples — so it is a faithful backtest of an online system whose only long-term memory is
this state object (spec 13.1).

Events (sorted by ``(timestamp, priority)``):
  * ``complete``  — a learning episode finished (its recharge reached high). An OK-quality
                    episode enters the *pending* set; a large_gap one is tallied but
                    enters no pending set (it can never become a clean no_response).
  * ``reset``     — an EFFECTIVE FCC step. Zeroes every ``*_since_last_fcc_change`` counter
                    and CLEARS the pending set: any episode still pending at a reset has
                    ``end <= reset_ts <= end+W``, i.e. it just *responded* (spec 7.4), so it
                    must not later be counted as a no_response.
  * ``deadline``  — ``end + response_window`` for a pending OK episode. If it is still
                    pending (no reset intervened) the window completed with no response ->
                    a confirmed ``no_response`` (and its model probability is folded into
                    the cumulative Poisson-binomial anomaly, spec 11.2).

Each physical episode appears exactly once (keyed by ``episode_id``), so the same episode
seen by many overlapping 30-day windows is never double-counted in state (spec 7.5 / 16.6).

Counters are tracked for the PRIMARY (80/20/80) and STRICT (90/10/90) bands; the cumulative
anomaly uses the primary band only (the strict band is nested inside it, so mixing them
would double-count the same physical excursion — spec 11.2).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import fcc_step_indicator
from .online_episode_detector import (
    OnlineConfig, DEFAULT_ONLINE_CONFIG, PRIMARY_THRESHOLD, STRICT_THRESHOLD,
    recover_design_mwh, step_threshold_mwh, prepare_user,
)

HOUR_NS = 3600 * 1_000_000_000
DAY_NS = 86_400 * 1_000_000_000
P_CLIP = (0.001, 0.999)

# event priorities at equal timestamps: a completion is recorded before a reset that lands
# on the same instant (so the episode enters then is cleared = responded); a reset is
# applied before a deadline on the same instant (the reset's change responded to it).
_PRIO_COMPLETE, _PRIO_RESET, _PRIO_DEADLINE = 0, 1, 2


def _effective_change_events(g: pd.DataFrame, min_mwh: float) -> List[Tuple[int, float, float]]:
    """(ts_ns, fcc_value, cycle) for every effective FCC step in the user's series."""
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    is_step, _ = fcc_step_indicator(fcc, min_mwh)
    pos = np.flatnonzero(is_step)
    return [(int(ts_ns[i]), float(fcc[i]), float(cyc[i])) for i in pos]


class _BandState:
    __slots__ = ("cum_no_response", "pending", "cum_large_gap",
                 "cum_expected", "cum_log_p")

    def __init__(self):
        self.cum_no_response = 0
        self.cum_large_gap = 0
        self.pending: Dict[str, float] = {}   # episode_id -> p_i (model prob, primary only used)
        self.cum_expected = 0.0
        self.cum_log_p = 0.0                  # sum log(1 - clip(p_i)) over resolved no_response

    def reset(self):
        self.cum_no_response = 0
        self.cum_large_gap = 0
        self.pending = {}
        self.cum_expected = 0.0
        self.cum_log_p = 0.0


def build_user_state_daily(
    g: pd.DataFrame, uid: str, grid_ends: np.ndarray, episodes: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG, design_mwh: Optional[float] = None,
    default_p: float = 0.5,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Daily state rows + FCC-change audit rows for one user.

    ``grid_ends`` are the window-end timestamps (int64 ns) to emit a row for — aligned to
    the rolling-feature table so state joins 1:1 with features. ``episodes`` is this user's
    causal episode table (must carry ``p_response`` for the anomaly accrual).
    """
    if design_mwh is None:
        design_mwh = recover_design_mwh(g)
    min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    first_ns, last_ns = int(ts_ns[0]), int(ts_ns[-1])

    win_ns = int(cfg.response_window_hours) * HOUR_NS

    # ---- build the event list ----
    events: List[Tuple[int, int, str, object]] = []
    for (ts, val, cy) in _effective_change_events(g, min_mwh):
        events.append((ts, _PRIO_RESET, "reset", (val, cy)))

    seen_ids = set()
    ep = episodes[episodes["threshold_name"].isin([PRIMARY_THRESHOLD, STRICT_THRESHOLD])]
    for r in ep.itertuples(index=False):
        eid = r.episode_id
        if eid in seen_ids:      # double-count guard (spec 7.5)
            continue
        seen_ids.add(eid)
        band = "primary" if r.threshold_name == PRIMARY_THRESHOLD else "strict"
        end_ns = int(pd.Timestamp(r.end_ts).value)
        q = r.episode_quality
        p_i = getattr(r, "p_response", np.nan)
        if not np.isfinite(p_i):
            p_i = default_p
        events.append((end_ns, _PRIO_COMPLETE, "complete", (band, q, eid, float(p_i))))
        # Only schedule a no_response deadline if the 72h response window is actually OBSERVED
        # (a sample exists at/after end+W). Otherwise the episode stays pending == censored and
        # must NEVER flip to no_response just because the window-end grid (which runs to end-of-day)
        # walked past end+W in wall-clock time (review finding: censored != no_response, spec 7.4).
        if q == "ok" and (end_ns + win_ns) <= last_ns:
            events.append((end_ns + win_ns, _PRIO_DEADLINE, "deadline", (band, eid)))
    events.sort(key=lambda e: (e[0], e[1]))

    # ---- running state ----
    bands = {"primary": _BandState(), "strict": _BandState()}
    last_change_ts = first_ns
    last_change_val = float(fcc[0])
    last_change_cyc = float(cyc[0])
    audit: List[Dict[str, object]] = []

    def _apply(ev):
        nonlocal last_change_ts, last_change_val, last_change_cyc
        _, _, kind, payload = ev
        if kind == "reset":
            val, cy = payload
            for b in bands.values():
                b.reset()
            audit.append({"user_id": uid, "change_ts": pd.Timestamp(ev[0]),
                          "fcc_value": val, "cycle": cy,
                          "prev_fcc_value": last_change_val})
            last_change_ts, last_change_val, last_change_cyc = ev[0], val, cy
        elif kind == "complete":
            band, q, eid, p_i = payload
            bs = bands[band]
            if q == "large_gap":
                bs.cum_large_gap += 1
            elif q == "ok":
                bs.pending[eid] = p_i
            # unknown / missing / invalid_order: ignored (never a clean opportunity)
        elif kind == "deadline":
            band, eid = payload
            bs = bands[band]
            p_i = bs.pending.pop(eid, None)
            if p_i is not None:                # still pending -> confirmed no_response
                bs.cum_no_response += 1
                bs.cum_expected += p_i
                bs.cum_log_p += math.log(1.0 - min(max(p_i, P_CLIP[0]), P_CLIP[1]))

    # ---- sweep grid days, applying events up to end-of-day ----
    rows: List[Dict[str, object]] = []
    ei, ne = 0, len(events)
    for end_ns in grid_ends:
        end_ns = int(end_ns)
        while ei < ne and events[ei][0] <= end_ns:
            _apply(events[ei]); ei += 1
        cur_cyc_idx = int(np.searchsorted(ts_ns, end_ns, side="right")) - 1
        cur_cyc = float(cyc[cur_cyc_idx]) if cur_cyc_idx >= 0 else float("nan")
        cur_seen_ts = int(ts_ns[cur_cyc_idx]) if cur_cyc_idx >= 0 else first_ns
        bp, bsr = bands["primary"], bands["strict"]
        cum_log_p = bp.cum_log_p
        rows.append({
            "user_id": uid,
            "window_end_date": pd.Timestamp(end_ns).normalize(),
            "state_as_of_ts": pd.Timestamp(end_ns),
            "first_seen_ts": pd.Timestamp(first_ns),
            "last_seen_ts": pd.Timestamp(cur_seen_ts),
            "last_effective_fcc_value": last_change_val,
            "last_effective_fcc_change_ts": pd.Timestamp(last_change_ts),
            "last_effective_fcc_change_cycle": last_change_cyc,
            "days_since_last_effective_fcc_change": round((end_ns - last_change_ts) / 8.64e13, 3),
            "cycles_since_last_effective_fcc_change": round(cur_cyc - last_change_cyc, 2)
                if np.isfinite(cur_cyc) else float("nan"),
            # primary band cumulative since last effective FCC change
            "cum_primary_no_response_since_last_fcc_change": bp.cum_no_response,
            "cum_primary_censored_since_last_fcc_change": len(bp.pending),
            "cum_primary_ok_since_last_fcc_change": bp.cum_no_response + len(bp.pending),
            "cum_primary_large_gap_since_last_fcc_change": bp.cum_large_gap,
            "cum_primary_response_since_last_fcc_change": 0,
            # strict band cumulative
            "cum_strict_no_response_since_last_fcc_change": bsr.cum_no_response,
            "cum_strict_censored_since_last_fcc_change": len(bsr.pending),
            "cum_strict_ok_since_last_fcc_change": bsr.cum_no_response + len(bsr.pending),
            "cum_strict_large_gap_since_last_fcc_change": bsr.cum_large_gap,
            "cum_strict_response_since_last_fcc_change": 0,
            # expected/observed response + cumulative Poisson-binomial anomaly (primary)
            "cum_expected_response_since_last_fcc_change": round(bp.cum_expected, 4),
            "cum_observed_response_since_last_fcc_change": 0,
            "cum_log_p_all_no_response_since_last_fcc_change": round(cum_log_p, 5),
            "cum_fw_response_anomaly_score": round(-cum_log_p / math.log(10), 4),
        })
    return rows, audit


def build_online_state(
    df_by_user: Dict[str, pd.DataFrame], episodes: pd.DataFrame,
    feats: pd.DataFrame, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_by_user: Optional[Dict[str, float]] = None, default_p: float = 0.5,
    progress: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Cohort daily online-state trajectory + FCC-change audit log.

    ``df_by_user`` maps user_id -> prepared (sorted, de-duplicated) frame. ``feats`` supplies
    the per-user grid of window-end timestamps so state aligns 1:1 with the feature table.
    """
    design_by_user = design_by_user or {}
    grid_by_user: Dict[str, np.ndarray] = {}
    for uid, sub in feats.groupby("user_id", sort=False):
        grid_by_user[uid] = sub["window_end_ts"].to_numpy().astype("datetime64[ns]").astype(np.int64)

    eps_by_user = {uid: sub for uid, sub in episodes.groupby("user_id", sort=False)} \
        if not episodes.empty else {}
    state_rows: List[Dict[str, object]] = []
    audit_rows: List[Dict[str, object]] = []
    keys = list(grid_by_user.keys())
    for i, uid in enumerate(keys):
        g = df_by_user[uid]
        grid = grid_by_user[uid]
        ueps = eps_by_user.get(uid, episodes.iloc[0:0])
        sr, ar = build_user_state_daily(g, uid, grid, ueps, cfg,
                                        design_mwh=design_by_user.get(uid), default_p=default_p)
        state_rows.extend(sr)
        audit_rows.extend(ar)
        if progress and (i + 1) % 100 == 0:
            print(f"  online state: {i + 1}/{len(keys)} users", flush=True)
    return pd.DataFrame(state_rows), pd.DataFrame(audit_rows)
