"""30-day sliding-window feature generation (rolling30 spec section 6).

One row per ``user_id x window_end_date``. The window covers ``(window_end - 30d,
window_end]`` (window_end inclusive, taken at end-of-day). Features are computed from
ONLY the raw samples inside that window (the 30-day raw-retention constraint, spec 0.3)
— no future samples, no samples older than 30 days. Episode-derived counts (which need
the episode table) are attached separately by :func:`attach_window_episode_counts`.

Performance: per user we build prefix sums of the time-weighted quantities once, so each
window's AC/charge/discharge ratios and SOC-band fractions are O(1); per-window slicing
is used only for percentiles / min / max / switch counts. At stride=1 the cohort yields
~135k windows and this runs in a couple of minutes.

Hardware identity is never read here (spec 0.4 / 9.2).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .features import sample_weights
from .fcc_learning import fcc_step_indicator
from .online_episode_detector import (
    OnlineConfig, DEFAULT_ONLINE_CONFIG, recover_design_mwh, step_threshold_mwh,
)

WINDOW_QUALITY_OK = "WINDOW_QUALITY_OK"
WINDOW_QUALITY_SHORT_OBS = "WINDOW_QUALITY_SHORT_OBS"
WINDOW_QUALITY_SPARSE = "WINDOW_QUALITY_SPARSE"
WINDOW_QUALITY_COUNTER_RESET = "WINDOW_QUALITY_COUNTER_RESET"
WINDOW_QUALITY_DUPLICATE_CONFLICT = "WINDOW_QUALITY_DUPLICATE_CONFLICT"

DAY_NS = 86_400 * 1_000_000_000
HOUR_NS = 3600 * 1_000_000_000


def window_end_grid(first_ts: pd.Timestamp, last_ts: pd.Timestamp,
                    stride_days: int) -> pd.DatetimeIndex:
    """End-of-day window-end timestamps from the first to the last observed day.

    Each entry ``d`` is normalised to 23:59:59.999999999 so the window ``(d-30d, d]``
    includes everything logged on calendar day ``d``.
    """
    first_day = pd.Timestamp(first_ts).normalize()
    last_day = pd.Timestamp(last_ts).normalize()
    days = pd.date_range(first_day, last_day, freq=f"{int(stride_days)}D")
    # push each day to its last nanosecond
    return days + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)


def _quality_label(n_samples: int, obs_days: float, p95_gap_h: float,
                   has_reset: bool, dup_conflict: bool, cfg: OnlineConfig) -> str:
    if has_reset:
        return WINDOW_QUALITY_COUNTER_RESET
    if dup_conflict:
        return WINDOW_QUALITY_DUPLICATE_CONFLICT
    if n_samples < cfg.window_min_samples or obs_days < cfg.window_min_obs_days:
        return WINDOW_QUALITY_SHORT_OBS
    if np.isfinite(p95_gap_h) and p95_gap_h > cfg.window_sparse_p95_gap_h:
        return WINDOW_QUALITY_SPARSE
    return WINDOW_QUALITY_OK


def dup_conflict_timestamps(g_raw: pd.DataFrame) -> np.ndarray:
    """Timestamps (int64 ns) that appear more than once with DISAGREEING FCC (spec 5.1).

    These are kept as a data-quality flag even though ``prepare_user`` de-duplicates to the
    last row. The cohort currently has 0 duplicate timestamps, so this returns empty here, but
    a future ingest with conflicting same-timestamp FCC would surface WINDOW_QUALITY_DUPLICATE_CONFLICT.
    """
    if g_raw.empty or g_raw["timestamp"].duplicated().sum() == 0:
        return np.array([], dtype=np.int64)
    nun = g_raw.groupby("timestamp")["fullChargeCapacity"].nunique()
    bad = nun[nun > 1].index
    if len(bad) == 0:
        return np.array([], dtype=np.int64)
    return np.sort(pd.DatetimeIndex(bad).asi8)


def compute_user_windows(
    g: pd.DataFrame, uid: str, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_mwh: Optional[float] = None, dup_conflict_ns: Optional[np.ndarray] = None,
) -> List[Dict[str, object]]:
    """All 30-day window feature rows for one (sorted, de-duplicated) user frame."""
    n = len(g)
    if n == 0:
        return []
    if design_mwh is None:
        design_mwh = recover_design_mwh(g)
    min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)

    ts = g["timestamp"]
    ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    acdc = (g["acdcMode"].to_numpy() == 1)
    cs = g["chargeStatus"].to_numpy() if "chargeStatus" in g.columns else None
    soh = g["soh_design_pct"].to_numpy(dtype=float) if "soh_design_pct" in g.columns else None

    is_step, _ = fcc_step_indicator(fcc, min_mwh)
    step_pos = np.flatnonzero(is_step)            # positions of effective steps
    abs_delta = np.abs(np.diff(fcc, prepend=fcc[0]))  # |delta| at each sample (0 at i=0)
    any_step, _ = fcc_step_indicator(fcc, 1.0)

    # ---- prefix sums for O(1) time-weighted window aggregates ----
    w = sample_weights(ts, cfg.sample_weight_cap_h)         # hours each sample represents
    def _pre(mask_or_vals: np.ndarray) -> np.ndarray:
        return np.concatenate([[0.0], np.cumsum(w * mask_or_vals)])
    P_w = np.concatenate([[0.0], np.cumsum(w)])
    P_ac = _pre(acdc.astype(float))
    P_chg = _pre((cs == 1).astype(float)) if cs is not None else None
    P_dis = _pre((cs == 2).astype(float)) if cs is not None else None
    P_b10 = _pre((rsoc < 10).astype(float))
    P_b20 = _pre((rsoc < 20).astype(float))
    P_a80 = _pre((rsoc > 80).astype(float))
    P_a90 = _pre((rsoc > 90).astype(float))
    P_a95 = _pre((rsoc > 95).astype(float))

    grid = window_end_grid(ts.iloc[0], ts.iloc[-1], cfg.stride_days)
    win_len_ns = cfg.window_days * DAY_NS
    rows: List[Dict[str, object]] = []
    for end_ts in grid:
        end_ns = int(end_ts.value)
        start_ns = end_ns - win_len_ns
        lo = int(np.searchsorted(ts_ns, start_ns, side="left"))
        hi = int(np.searchsorted(ts_ns, end_ns, side="right"))
        ns = hi - lo
        if ns < 1:
            continue
        sl = slice(lo, hi)
        wts = ts_ns[sl]
        wrsoc = rsoc[sl]
        wfcc = fcc[sl]
        wcyc = cyc[sl]
        tw = P_w[hi] - P_w[lo]

        gaps_h = np.diff(wts) / 3.6e12 if ns > 1 else np.array([])
        obs_days = float((wts[-1] - wts[0]) / 8.64e13)
        p95_gap = float(np.percentile(gaps_h, 95)) if gaps_h.size else float("nan")
        cyc_dec = int((np.diff(wcyc) < 0).sum()) if ns > 1 else 0
        has_reset = cyc_dec > 0
        n_dup_conflict = 0
        if dup_conflict_ns is not None and dup_conflict_ns.size:
            n_dup_conflict = int(np.searchsorted(dup_conflict_ns, end_ns, side="right")
                                 - np.searchsorted(dup_conflict_ns, start_ns, side="left"))

        # effective FCC steps whose change-sample lands inside the window (idx in (lo, hi))
        in_win_steps = step_pos[(step_pos > lo) & (step_pos < hi)]
        n_eff = int(in_win_steps.size)
        in_win_any = np.flatnonzero(any_step[lo:hi]) + lo
        in_win_any = in_win_any[in_win_any > lo]
        eff_abs_max = float(abs_delta[in_win_steps].max()) if n_eff else 0.0
        if n_eff:
            last_step_idx = int(in_win_steps[-1])
            last_eff_ts = pd.Timestamp(int(ts_ns[last_step_idx]))
            last_eff_cyc = float(cyc[last_step_idx])
        else:
            last_eff_ts, last_eff_cyc = pd.NaT, float("nan")

        n_acdc_sw = int((np.diff(acdc[sl].astype(int)) != 0).sum()) if ns > 1 else 0
        if cs is not None and ns > 1:
            n_cs_sw = int((np.diff(cs[sl]) != 0).sum())
            # discharge sessions: contiguous chargeStatus==2 runs
            disc = (cs[sl] == 2).astype(int)
            n_disc = int(((np.diff(disc) == 1).sum()) + (1 if disc.size and disc[0] == 1 else 0))
        else:
            n_cs_sw, n_disc = 0, 0

        valid_r = wrsoc[(wrsoc >= 0) & (wrsoc <= 100)]
        rmin = float(valid_r.min()) if valid_r.size else float("nan")
        rmax = float(valid_r.max()) if valid_r.size else float("nan")

        ql = _quality_label(ns, obs_days, p95_gap, has_reset, n_dup_conflict > 0, cfg)
        row: Dict[str, object] = {
            "user_id": uid,
            "window_end_date": end_ts.normalize(),
            "window_start_ts": pd.Timestamp(start_ns),
            "window_end_ts": end_ts,
            # ---- data quality (6.2) ----
            "n_samples_30d": int(ns),
            "obs_days_in_window": round(obs_days, 3),
            "median_interval_h": round(float(np.median(gaps_h)), 3) if gaps_h.size else float("nan"),
            "p95_interval_h": round(p95_gap, 3) if np.isfinite(p95_gap) else float("nan"),
            "max_gap_h": round(float(gaps_h.max()), 3) if gaps_h.size else 0.0,
            "gaps_gt_6h_count": int((gaps_h > cfg.gap_small_h).sum()) if gaps_h.size else 0,
            "gaps_gt_12h_count": int((gaps_h > cfg.gap_mid_h).sum()) if gaps_h.size else 0,
            "gaps_gt_24h_count": int((gaps_h > cfg.gap_large_h).sum()) if gaps_h.size else 0,
            "duplicate_timestamp_count": int(n_dup_conflict),   # conflicting same-ts FCC (spec 5.1)
            "cycle_decrease_count": cyc_dec,
            "fcc_missing_count": int(np.isnan(wfcc).sum() + (wfcc <= 0).sum()),
            "rsoc_missing_count": int(np.isnan(wrsoc).sum() + ((wrsoc < 0) | (wrsoc > 100)).sum()),
            "has_counter_reset": bool(has_reset),
            "window_data_quality_label": ql,
            # ---- usage (6.3) ----
            "cycle_start_30d": float(wcyc[0]),
            "cycle_end_30d": float(wcyc[-1]),
            "cycle_delta_30d": round(float(wcyc[-1] - wcyc[0]), 2),
            "cycle_rate_per_30d": round(float((wcyc[-1] - wcyc[0]) / max(obs_days, 1e-6) * cfg.window_days), 3),
            "ac_time_ratio_30d": round(float((P_ac[hi] - P_ac[lo]) / tw), 4) if tw > 0 else float("nan"),
            "charge_time_ratio_30d": (round(float((P_chg[hi] - P_chg[lo]) / tw), 4)
                                      if (P_chg is not None and tw > 0) else float("nan")),
            "discharge_time_ratio_30d": (round(float((P_dis[hi] - P_dis[lo]) / tw), 4)
                                         if (P_dis is not None and tw > 0) else float("nan")),
            "rsoc_min_30d": rmin,
            "rsoc_max_30d": rmax,
            "rsoc_swing_30d": round(rmax - rmin, 2) if valid_r.size else float("nan"),
            "rsoc_p05_30d": round(float(np.percentile(valid_r, 5)), 2) if valid_r.size else float("nan"),
            "rsoc_p50_30d": round(float(np.percentile(valid_r, 50)), 2) if valid_r.size else float("nan"),
            "rsoc_p95_30d": round(float(np.percentile(valid_r, 95)), 2) if valid_r.size else float("nan"),
            "frac_below_10_30d": round(float((P_b10[hi] - P_b10[lo]) / tw), 4) if tw > 0 else float("nan"),
            "frac_below_20_30d": round(float((P_b20[hi] - P_b20[lo]) / tw), 4) if tw > 0 else float("nan"),
            "frac_above_80_30d": round(float((P_a80[hi] - P_a80[lo]) / tw), 4) if tw > 0 else float("nan"),
            "frac_above_90_30d": round(float((P_a90[hi] - P_a90[lo]) / tw), 4) if tw > 0 else float("nan"),
            "frac_above_95_30d": round(float((P_a95[hi] - P_a95[lo]) / tw), 4) if tw > 0 else float("nan"),
            "n_acdc_switches_30d": n_acdc_sw,
            "n_charge_status_switches_30d": n_cs_sw,
            "n_discharge_sessions_30d": n_disc,
            # ---- FCC (6.4) ----
            "fcc_start_30d": float(wfcc[0]),
            "fcc_end_30d": float(wfcc[-1]),
            "fcc_min_30d": float(np.nanmin(wfcc)),
            "fcc_max_30d": float(np.nanmax(wfcc)),
            "fcc_abs_delta_30d": round(float(np.nanmax(wfcc) - np.nanmin(wfcc)), 2),
            "fcc_any_changes_30d": int(in_win_any.size),
            "fcc_effective_changes_30d": n_eff,
            "fcc_effective_step_abs_max_30d": round(eff_abs_max, 2),
            "last_effective_fcc_change_ts_in_window": last_eff_ts,
            "last_effective_fcc_change_cycle_in_window": last_eff_cyc,
            "soh_start_30d": round(float(soh[lo]), 3) if soh is not None else float("nan"),
            "soh_end_30d": round(float(soh[hi - 1]), 3) if soh is not None else float("nan"),
        }
        rows.append(row)
    return rows


def build_rolling_features(
    df: pd.DataFrame, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_by_user: Optional[Dict[str, float]] = None,
    progress: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Cohort-wide rolling features. Returns (features_df, recovered design_by_user)."""
    from .online_episode_detector import prepare_user
    out: List[Dict[str, object]] = []
    design_out: Dict[str, float] = {}
    users = df["user_id"].unique()
    for i, (uid, g_raw) in enumerate(df.groupby("user_id", sort=False)):
        dup_ns = dup_conflict_timestamps(g_raw)        # detect conflicts BEFORE de-duplication
        g = prepare_user(g_raw)
        d = (design_by_user or {}).get(uid)
        if d is None:
            d = recover_design_mwh(g)
        design_out[uid] = d
        out.extend(compute_user_windows(g, uid, cfg, design_mwh=d, dup_conflict_ns=dup_ns))
        if progress and (i + 1) % 100 == 0:
            print(f"  rolling features: {i + 1}/{len(users)} users", flush=True)
    feats = pd.DataFrame(out)
    return feats, design_out


# --------------------------------------------------------------------------- #
# Episode-count attachment (cluster / policy inputs that need the episode table)
# --------------------------------------------------------------------------- #
_BAND_SHORT = {"primary_80_20_80": "80_20_80", "secondary_85_15_85": "85_15_85",
               "strict_90_10_90": "90_10_90"}


def attach_window_episode_counts(
    feats: pd.DataFrame, episodes: pd.DataFrame, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    response_col: str = "response_status_72h",
) -> pd.DataFrame:
    """Add per-window episode counts (OK-complete / large_gap / no_response / censored) by band.

    Assignment is CAUSAL (mirrors :func:`online_anomaly_scores.compute_window_scores`): an
    episode ending at ``e`` is contained in windows ending at ``t`` for ``t in [e, e+30d)``,
    but its 72h response is only KNOWN once ``t >= e+W``. So for a window ending at ``t`` with
    ``e <= t < e+W`` the opportunity is still ``censored`` (it must NOT count as ok_complete /
    no_response); only at ``t >= e+W`` does the resolved status apply. An episode whose response
    window never closes within the observation (final status ``censored``) is censored in every
    window. large_gap / "any" counts do not depend on the response window, so they use the full
    ``[e, e+30d)`` membership. This keeps future-resolved status out of the cluster features
    (spec 9.2 / 13.4) and matches the anomaly path.
    """
    bands = list(_BAND_SHORT.items())
    new_cols = {}
    for _, short in bands:
        for suff in ("ok_complete", "large_gap", "no_response", "censored", "any"):
            new_cols[f"n_{short}_{suff}_30d"] = np.zeros(len(feats), dtype=int)
    feats = feats.reset_index(drop=True)
    win_idx: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for uid, sub in feats.groupby("user_id", sort=False):
        ends = sub["window_end_ts"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        win_idx[uid] = (sub.index.to_numpy(), ends)
    win_len_ns = cfg.window_days * DAY_NS
    win_resp_ns = int(cfg.response_window_hours) * HOUR_NS

    if not episodes.empty:
        for r in episodes.itertuples(index=False):
            uid = r.user_id
            if uid not in win_idx:
                continue
            rows_idx, ends = win_idx[uid]
            e_ns = int(pd.Timestamp(r.end_ts).value)
            j0 = int(np.searchsorted(ends, e_ns, side="left"))                 # first window with t>=e
            j1 = int(np.searchsorted(ends, e_ns + win_len_ns, side="left"))    # window no longer contains e
            jr = int(np.searchsorted(ends, e_ns + win_resp_ns, side="left"))   # first window with t>=e+W
            sel_any = rows_idx[j0:j1]
            if sel_any.size == 0:
                continue
            short = _BAND_SHORT.get(r.threshold_name)
            if short is None:
                continue
            q = r.episode_quality
            status = getattr(r, response_col, None)
            new_cols[f"n_{short}_any_30d"][sel_any] += 1
            if q == "large_gap":
                new_cols[f"n_{short}_large_gap_30d"][sel_any] += 1
            elif q == "ok":
                if status == "censored":
                    new_cols[f"n_{short}_censored_30d"][sel_any] += 1     # never resolves -> censored everywhere
                else:                                                     # responded / no_response (final)
                    sel_cens = rows_idx[j0:max(min(jr, j1), j0)]          # e <= t < e+W : not yet resolved
                    sel_res = rows_idx[max(jr, j0):j1]                    # t >= e+W     : resolved
                    new_cols[f"n_{short}_censored_30d"][sel_cens] += 1
                    new_cols[f"n_{short}_ok_complete_30d"][sel_res] += 1
                    if status == "no_response":
                        new_cols[f"n_{short}_no_response_30d"][sel_res] += 1
    for k, v in new_cols.items():
        feats[k] = v
    return feats
