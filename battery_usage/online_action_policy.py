"""Online action policy (rolling30 spec 12): window labels, stateful labels, the
FW-check / Gauge-reset / Watch gates, alert cooldown, and the latest-snapshot action lists.

Two label families are kept strictly separate:
  * **window label**   — what the last 30 days alone say (spec 12.1).
  * **stateful label**  — the long-horizon action candidate built from the persisted state
                          (``*_since_last_fcc_change`` counters), the usage cluster, and the
                          anomaly score (spec 12.2-12.5).

Data-quality review always outranks an actionable call (spec 16.14): a window that is not
clean cannot drive a Gauge/FW recommendation. Hardware identity is never read.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .online_episode_detector import OnlineConfig, DEFAULT_ONLINE_CONFIG

# ---- window labels (12.1) ----
WIN_NORMAL = "WINDOW_NORMAL_RESPONDING"
WIN_NO_RESP = "WINDOW_OPPORTUNITY_NO_RESPONSE"
WIN_INSUFF = "WINDOW_INSUFFICIENT_LEARNING_OPPORTUNITY"
WIN_LARGE_GAP = "WINDOW_LARGE_GAP_AMBIGUOUS"
WIN_CENSORED = "WINDOW_CENSORED_PENDING"
WIN_DQ = "WINDOW_DATA_QUALITY_REVIEW"
WIN_LOW_INFO = "WINDOW_LOW_INFORMATION"

# ---- stateful labels (12.2) ----
ST_NORMAL = "STATEFUL_NORMAL"
ST_GAUGE = "STATEFUL_GAUGE_RESET_CANDIDATE"
ST_FW = "STATEFUL_FW_CHECK_CANDIDATE"
ST_WATCH = "STATEFUL_WATCH"
ST_REVIEW = "STATEFUL_REVIEW"

_ACTION = {
    ST_NORMAL: "ACTION_NONE", ST_GAUGE: "ACTION_GAUGE_RESET_CALIBRATION",
    ST_FW: "ACTION_FW_BIOS_EC_CHECK", ST_WATCH: "ACTION_WATCH",
    ST_REVIEW: "ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW",
}

_GAUGE_CLUSTERS = {"AC_BOUND", "SHALLOW_TOPUP", "LOW_CYCLING_LOW_INFORMATION"}


def _window_label(r) -> str:
    if r.window_data_quality_label != "WINDOW_QUALITY_OK":
        return WIN_DQ
    if (getattr(r, "fcc_effective_changes_30d", 0) or 0) >= 1 or (getattr(r, "observed_response_30d", 0) or 0) >= 1:
        return WIN_NORMAL
    n_ok = getattr(r, "n_complete_ok_opportunities_30d", 0) or 0
    n_nr = getattr(r, "no_response_count_30d", 0) or 0
    n_lg = getattr(r, "n_80_20_80_large_gap_30d", 0) or 0
    n_cs = getattr(r, "n_80_20_80_censored_30d", 0) or 0
    if n_ok >= 1 and n_nr >= 1:
        return WIN_NO_RESP
    if n_lg >= 1 and n_ok == 0:
        return WIN_LARGE_GAP
    if n_cs >= 1 and n_ok == 0:
        return WIN_CENSORED
    cyc = getattr(r, "cycle_delta_30d", 0) or 0
    n_dis = getattr(r, "n_discharge_sessions_30d", 0) or 0
    if cyc < 1.0 and n_dis <= 1:
        return WIN_LOW_INFO
    return WIN_INSUFF


def _stateful_label(r, cfg: OnlineConfig, fleet_cycle_p25: float) -> str:
    # review guard first (data quality dominates an actionable call)
    if r.window_data_quality_label != "WINDOW_QUALITY_OK":
        return ST_REVIEW

    days_since = getattr(r, "days_since_last_effective_fcc_change", np.nan)
    cyc_since = getattr(r, "cycles_since_last_effective_fcc_change", np.nan)
    cum_p_nr = getattr(r, "cum_primary_no_response_since_last_fcc_change", 0) or 0
    cum_s_nr = getattr(r, "cum_strict_no_response_since_last_fcc_change", 0) or 0
    cum_p_ok = getattr(r, "cum_primary_ok_since_last_fcc_change", 0) or 0
    cum_p_lg = getattr(r, "cum_primary_large_gap_since_last_fcc_change", 0) or 0
    cum_p_cens = getattr(r, "cum_primary_censored_since_last_fcc_change", 0) or 0
    cum_s_ok = getattr(r, "cum_strict_ok_since_last_fcc_change", 0) or 0
    cum_s_lg = getattr(r, "cum_strict_large_gap_since_last_fcc_change", 0) or 0
    cum_obs = getattr(r, "cum_observed_response_since_last_fcc_change", 0) or 0
    cum_anom = getattr(r, "cum_fw_response_anomaly_score", 0.0) or 0.0
    win_anom = getattr(r, "fw_response_anomaly_score_30d", 0.0) or 0.0
    conf_p = getattr(r, "conformal_p", np.nan)
    cluster = getattr(r, "cluster_profile_name", "") or ""
    fcc_eff_recent = getattr(r, "fcc_effective_changes_30d", 0) or 0

    large_gap_or_censored_dominant = (cum_p_lg + cum_p_cens) > max(cum_p_nr, 1)

    # ---- FW_CHECK (12.3) ----
    fw_evidence = (cum_p_nr >= 3 or cum_s_nr >= 2 or cum_anom >= 2.0 or win_anom >= 2.0)
    if (np.isfinite(days_since) and days_since >= cfg.fw_days_since_change_min
            and np.isfinite(cyc_since) and cyc_since >= cfg.fw_cycles_since_change_min
            and fw_evidence and cum_obs == 0 and not large_gap_or_censored_dominant):
        return ST_FW

    # ---- GAUGE_RESET (12.4) ----
    gauge_usage = (getattr(r, "ac_time_ratio_30d", 0) or 0) >= 0.80 \
        or (getattr(r, "rsoc_swing_30d", 99) or 99) < 60 \
        or (getattr(r, "rsoc_min_30d", 0) or 0) > 20 \
        or ((getattr(r, "cycle_delta_30d", 0) or 0) <= fleet_cycle_p25)
    if (np.isfinite(days_since) and days_since >= cfg.gauge_days_since_change_min
            and fcc_eff_recent == 0
            and cum_p_ok == 0 and cum_p_lg == 0 and cum_s_ok == 0 and cum_s_lg == 0
            and cluster in _GAUGE_CLUSTERS and gauge_usage):
        return ST_GAUGE

    # ---- WATCH (12.5): partial / ambiguous evidence ----
    watch_evidence = (
        (cum_p_nr >= 1) or (cum_s_nr >= 1) or (win_anom >= 1.0) or (cum_anom >= 1.0)
        or (np.isfinite(conf_p) and conf_p <= 0.05)
        or (large_gap_or_censored_dominant and np.isfinite(days_since)
            and days_since >= cfg.gauge_days_since_change_min)
    )
    if watch_evidence and cum_obs == 0:
        return ST_WATCH
    return ST_NORMAL


def assign_labels(
    daily: pd.DataFrame, cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
) -> pd.DataFrame:
    """Add ``window_label``, ``stateful_label``, ``recommended_action`` to the joined daily frame."""
    daily = daily.copy()
    ok = daily["window_data_quality_label"] == "WINDOW_QUALITY_OK"
    fleet_cycle_p25 = float(daily.loc[ok, "cycle_delta_30d"].quantile(0.25)) if ok.any() else 0.0
    daily["window_label"] = [_window_label(r) for r in daily.itertuples(index=False)]
    daily["stateful_label"] = [_stateful_label(r, cfg, fleet_cycle_p25)
                               for r in daily.itertuples(index=False)]
    daily["recommended_action"] = daily["stateful_label"].map(_ACTION)
    return daily


# --------------------------------------------------------------------------- #
# Alert cooldown (12.6) + consecutive-window counters
# --------------------------------------------------------------------------- #
def apply_alert_cooldown(daily: pd.DataFrame, cooldown_days: int = 30) -> pd.DataFrame:
    """Fire an alert only on a transition into an actionable state, respecting a cooldown.

    The cooldown resets when an effective FCC update happens (``days_since_...`` drops),
    so a genuinely new freeze after a recovery can re-alert (spec 12.6).
    """
    daily = daily.sort_values(["user_id", "window_end_date"], kind="stable").reset_index(drop=True)
    actionable = daily["stateful_label"].isin([ST_FW, ST_GAUGE])
    fired = np.zeros(len(daily), bool)
    consec_no_resp = np.zeros(len(daily), int)
    for uid, idx in daily.groupby("user_id", sort=False).groups.items():
        idx = list(idx)
        last_alert_day = None
        prev_days_since = None
        run = 0
        for i in idx:
            row = daily.loc[i]
            wd = row["window_end_date"]
            ds = row.get("days_since_last_effective_fcc_change", np.nan)
            # reset cooldown if an effective FCC update occurred (days_since dropped)
            if prev_days_since is not None and np.isfinite(ds) and ds < prev_days_since:
                last_alert_day = None
            prev_days_since = ds
            run = run + 1 if row["window_label"] == WIN_NO_RESP else 0
            consec_no_resp[i] = run
            if actionable.loc[i]:
                if last_alert_day is None or (wd - last_alert_day).days >= cooldown_days:
                    fired[i] = True
                    last_alert_day = wd
    daily["alert_fired"] = fired
    daily["consecutive_windows_opportunity_no_response"] = consec_no_resp
    return daily


# --------------------------------------------------------------------------- #
# Latest snapshot + action candidate lists
# --------------------------------------------------------------------------- #
def latest_snapshot(daily: pd.DataFrame) -> pd.DataFrame:
    idx = daily.groupby("user_id")["window_end_date"].idxmax()
    snap = daily.loc[idx].copy().reset_index(drop=True)
    snap["primary_evidence"] = [_evidence_string(r) for r in snap.itertuples(index=False)]
    return snap


def _evidence_string(r) -> str:
    return (f"days_since_fcc={_g(r,'days_since_last_effective_fcc_change')}, "
            f"cyc_since={_g(r,'cycles_since_last_effective_fcc_change')}, "
            f"cum_primary_no_response={_g(r,'cum_primary_no_response_since_last_fcc_change')}, "
            f"cum_strict_no_response={_g(r,'cum_strict_no_response_since_last_fcc_change')}, "
            f"cum_anom={_g(r,'cum_fw_response_anomaly_score')}, "
            f"win_anom={_g(r,'fw_response_anomaly_score_30d')}, "
            f"expected={_g(r,'expected_response_30d')}, observed={_g(r,'observed_response_30d')}, "
            f"n_ok_opp={_g(r,'n_complete_ok_opportunities_30d')}, "
            f"cluster={_g(r,'cluster_profile_name')}, quality={_g(r,'window_data_quality_label')}")


def _g(r, k):
    v = getattr(r, k, None)
    if isinstance(v, float):
        return round(v, 3)
    return v


def candidate_lists(snap: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    out = {}
    out["fw_check"] = snap[snap["stateful_label"] == ST_FW].copy()
    out["gauge_reset"] = snap[snap["stateful_label"] == ST_GAUGE].copy()
    out["watchlist"] = snap[snap["stateful_label"] == ST_WATCH].copy()
    out["review_queue"] = snap[snap["stateful_label"] == ST_REVIEW].copy()
    # sort actionable lists by strength of evidence
    if not out["fw_check"].empty:
        out["fw_check"] = out["fw_check"].sort_values(
            ["cum_fw_response_anomaly_score", "cum_primary_no_response_since_last_fcc_change"],
            ascending=False)
    if not out["gauge_reset"].empty:
        out["gauge_reset"] = out["gauge_reset"].sort_values(
            "days_since_last_effective_fcc_change", ascending=False)
    return out
