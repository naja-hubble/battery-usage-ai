"""Online action policy v2 (rolling30 v2 spec sections 8, 9, 13).

v1 emitted one broad ``STATEFUL_GAUGE_RESET_CANDIDATE`` (45 users — far too coarse) and one
strict ``STATEFUL_FW_CHECK_CANDIDATE`` (3 — high precision, low recall). v2 replaces both
with operational TIERS and assigns each latest-snapshot user EXACTLY ONE label via a fixed
priority ladder (spec 13):

    1 STATEFUL_REVIEW_DATA_QUALITY                 (data quality / history dominates)
    2 STATEFUL_FW_CHECK_CORE                        (high-confidence FW review target)
    3 STATEFUL_GAUGE_RESET_CORE                     (high-confidence gauge reset target)
    4 STATEFUL_FW_WATCH_HIGH_ANOMALY                (FW-like, a core requirement just short)
    5 STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY(micro-wobble, no effective relearn)
    6 STATEFUL_GAUGE_REVIEW                         (gauge-like but large-gap ambiguity)
    7 STATEFUL_WATCH_LARGE_GAP_OR_CENSORED          (ambiguous evidence)
    8 STATEFUL_WATCH_LOW_EVIDENCE                   (weak evidence)
    9 STATEFUL_NORMAL_RESPONDING                    (responding / no concern)

Data-quality review always wins (spec 3.6); for those users we still record diagnostic
``fw_like_evidence_flag`` / ``gauge_like_evidence_flag`` and ``would_have_been_*`` so the
queue is not silently dropped. The policy reads the NORMATIVE anomaly only (spec 10.4); the
personalized anomaly is carried as a diagnostic column elsewhere. Hardware identity is never
read (asserted by the caller).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .usage_clustering import GAUGE_RELEVANT_CLUSTERS

# ---- v2 stateful labels (priority order) ----
ST_REVIEW_DQ = "STATEFUL_REVIEW_DATA_QUALITY"
ST_FW_CORE = "STATEFUL_FW_CHECK_CORE"
ST_GAUGE_CORE = "STATEFUL_GAUGE_RESET_CORE"
ST_FW_WATCH = "STATEFUL_FW_WATCH_HIGH_ANOMALY"
ST_GAUGE_SOFT = "STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY"
ST_GAUGE_REVIEW = "STATEFUL_GAUGE_REVIEW"
ST_WATCH_LGC = "STATEFUL_WATCH_LARGE_GAP_OR_CENSORED"
ST_WATCH_LOW = "STATEFUL_WATCH_LOW_EVIDENCE"
ST_NORMAL = "STATEFUL_NORMAL_RESPONDING"

PRIORITY = {
    ST_REVIEW_DQ: 1, ST_FW_CORE: 2, ST_GAUGE_CORE: 3, ST_FW_WATCH: 4, ST_GAUGE_SOFT: 5,
    ST_GAUGE_REVIEW: 6, ST_WATCH_LGC: 7, ST_WATCH_LOW: 8, ST_NORMAL: 9,
}

# ---- recommended actions (spec 13) ----
ACTION = {
    ST_REVIEW_DQ: "ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW",
    ST_FW_CORE: "ACTION_FW_VERSION_CHECK_CORE",
    ST_GAUGE_CORE: "ACTION_GAUGE_RESET_CORE",
    ST_FW_WATCH: "ACTION_FW_ENGINEERING_REVIEW",
    ST_GAUGE_SOFT: "ACTION_SOFT_CALIBRATION_PROMPT",
    ST_GAUGE_REVIEW: "ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW",
    ST_WATCH_LGC: "ACTION_MONITOR_NEXT_WINDOW",
    ST_WATCH_LOW: "ACTION_MONITOR_NEXT_WINDOW",
    ST_NORMAL: "ACTION_NONE",
}
CONFIDENCE = {
    ST_REVIEW_DQ: "low", ST_FW_CORE: "high", ST_GAUGE_CORE: "high", ST_FW_WATCH: "medium",
    ST_GAUGE_SOFT: "medium", ST_GAUGE_REVIEW: "low", ST_WATCH_LGC: "low",
    ST_WATCH_LOW: "low", ST_NORMAL: "high",
}

# ---- window labels v2 ----
WIN_NORMAL = "WINDOW_NORMAL_RESPONDING"
WIN_NO_RESP = "WINDOW_OPPORTUNITY_NO_RESPONSE"
WIN_MICRO_ONLY = "WINDOW_MICRO_WOBBLE_ONLY"
WIN_INSUFF = "WINDOW_INSUFFICIENT_LEARNING_OPPORTUNITY"
WIN_LARGE_GAP = "WINDOW_LARGE_GAP_AMBIGUOUS"
WIN_CENSORED = "WINDOW_CENSORED_PENDING"
WIN_DQ = "WINDOW_DATA_QUALITY_REVIEW"
WIN_LOW_INFO = "WINDOW_LOW_INFORMATION"


@dataclass(frozen=True)
class PolicyConfigV2:
    """All v2 gate thresholds (no magic numbers; mirrors v1's config-driven style)."""
    # FW Core (spec 9.1)
    fw_core_days: float = 90.0
    fw_core_cycles: float = 30.0
    fw_core_primary_ok_nr: int = 3
    fw_core_strict_ok_nr: int = 2
    fw_core_anomaly: float = 2.0
    fw_core_conformal_p: float = 0.01
    fw_core_high_quality_nr: int = 2
    # FW Watch (spec 9.2) — staleness only "slightly short" of core, so a recently-recovered
    # (effective-active) gauge is never FW-flagged on a stale 30d-window anomaly alone.
    fw_watch_days: float = 60.0
    fw_watch_anomaly: float = 1.3
    fw_watch_conformal_p: float = 0.05
    fw_watch_medium_nr: int = 2
    # Gauge Core (spec 8.1) — long staleness under BOTH definitions
    gauge_core_days: float = 120.0
    # Gauge Soft (spec 8.2) — effective-stale but any-active / micro-wobble
    gauge_soft_eff_days: float = 120.0
    # Watch staleness floor
    watch_days: float = 90.0


DEFAULT_POLICY_V2 = PolicyConfigV2()


# --------------------------------------------------------------------------- #
def _g(r, k, default=0):
    v = getattr(r, k, default)
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return default
    return v


def _evaluate(r, cfg: PolicyConfigV2) -> Dict[str, object]:
    """Evaluate every tier gate for one row. Returns booleans + evidence fields."""
    dq = getattr(r, "window_data_quality_label", "WINDOW_QUALITY_OK")
    dq_ok = (dq == "WINDOW_QUALITY_OK")
    hist_ok = bool(_g(r, "state_history_sufficient", False))
    has_reset = bool(_g(r, "has_counter_reset", False))

    days_eff = _g(r, "days_since_effective_fcc_change", np.nan)
    days_any = _g(r, "days_since_any_fcc_change", np.nan)
    cyc_eff = _g(r, "cycles_since_effective_fcc_change", np.nan)
    days_eff = days_eff if np.isfinite(days_eff) else 0.0
    days_any = days_any if np.isfinite(days_any) else 0.0
    cyc_eff = cyc_eff if np.isfinite(cyc_eff) else 0.0

    # graded opportunity counters since last effective change
    p_ok_opp = _g(r, "cum_primary_ok_opportunities_since_last_effective_change", 0)
    p_med_opp = _g(r, "cum_primary_medium_gap_opportunities_since_last_effective_change", 0)
    p_lg_opp = _g(r, "cum_primary_large_gap_opportunities_since_last_effective_change", 0)
    s_ok_opp = _g(r, "cum_strict_ok_opportunities_since_last_effective_change", 0)
    s_med_opp = _g(r, "cum_strict_medium_gap_opportunities_since_last_effective_change", 0)
    s_lg_opp = _g(r, "cum_strict_large_gap_opportunities_since_last_effective_change", 0)

    p_ok_nr = _g(r, "cum_primary_ok_no_response_since_last_effective_change", 0)
    p_med_nr = _g(r, "cum_primary_medium_gap_no_response_since_last_effective_change", 0)
    p_total_nr = _g(r, "cum_primary_no_response_since_last_effective_change", 0)
    s_ok_nr = _g(r, "cum_strict_ok_no_response_since_last_effective_change", 0)
    s_total_nr = _g(r, "cum_strict_no_response_since_last_effective_change", 0)
    p_cens = _g(r, "cum_primary_censored_since_last_effective_change", 0)

    hq_nr = _g(r, "high_quality_no_response_count", 0)
    cens_ct = _g(r, "censored_count", 0)
    lg_low_ct = _g(r, "large_gap_low_quality_count", 0)
    obs_eff = _g(r, "observed_effective_responses_since_last_effective_change", 0)

    norm_anom = _g(r, "cum_normative_fw_anomaly_score", 0.0)
    win_anom = _g(r, "fw_response_anomaly_score_30d", 0.0)
    conf_p = getattr(r, "conformal_p", np.nan)
    conf_p = conf_p if (conf_p is not None and np.isfinite(conf_p)) else 1.0
    micro_only = bool(_g(r, "micro_wobble_only_since_effective_change", False))
    cluster = getattr(r, "cluster_profile_name", "") or ""
    fcc_eff_recent = _g(r, "fcc_effective_changes_30d", 0)

    total_opp = p_ok_opp + p_med_opp + p_lg_opp + s_ok_opp + s_med_opp + s_lg_opp
    no_real_opportunity = (total_opp == 0)
    not_fw_like_no_resp = (p_total_nr == 0 and s_total_nr == 0)
    gauge_cluster = cluster in GAUGE_RELEVANT_CLUSTERS
    high_quality_dominant = (hq_nr >= cfg.fw_core_high_quality_nr
                             and cens_ct <= hq_nr and lg_low_ct <= hq_nr)

    # ---- FW Core (9.1) ----
    fw_core_evidence = (p_ok_nr >= cfg.fw_core_primary_ok_nr
                        or s_ok_nr >= cfg.fw_core_strict_ok_nr
                        or (norm_anom >= cfg.fw_core_anomaly and conf_p <= cfg.fw_core_conformal_p))
    fw_core = (dq_ok and hist_ok and days_eff >= cfg.fw_core_days
               and cyc_eff >= cfg.fw_core_cycles and obs_eff == 0
               and fw_core_evidence and high_quality_dominant)

    # ---- FW-like evidence (drives Watch + diagnostic flag) ----
    fw_like = (norm_anom >= cfg.fw_watch_anomaly or win_anom >= cfg.fw_watch_anomaly
               or conf_p <= cfg.fw_watch_conformal_p or p_total_nr >= 1 or s_total_nr >= 1
               or p_med_nr >= cfg.fw_watch_medium_nr)
    # FW Watch needs at least "slightly short" effective staleness; a recently-recovered gauge
    # (days_eff < floor) is not FW-like even if its 30d window still carries a pre-recovery anomaly.
    fw_watch = (dq_ok and obs_eff == 0 and fw_like and days_eff >= cfg.fw_watch_days
                and not fw_core)

    # ---- Gauge Core (8.1): long staleness BOTH defs, zero opportunity, not FW-like ----
    gauge_core = (dq_ok and hist_ok and days_eff >= cfg.gauge_core_days
                  and days_any >= cfg.gauge_core_days and no_real_opportunity
                  and gauge_cluster and not_fw_like_no_resp and fcc_eff_recent == 0)

    # ---- Gauge Soft (8.2): effective-stale, any-active/micro-wobble, no clean opp, not FW ----
    no_clean_opp = (p_ok_opp == 0 and p_med_opp == 0 and s_ok_opp == 0 and s_med_opp == 0)
    gauge_soft = (dq_ok and hist_ok and days_eff >= cfg.gauge_soft_eff_days
                  and (days_any < cfg.gauge_core_days or micro_only)
                  and no_clean_opp and gauge_cluster and not_fw_like_no_resp
                  and not gauge_core)

    # ---- Gauge Review (8.3): gauge-like but large-gap ambiguity prevents firm conclusion ----
    gauge_like = (days_eff >= cfg.gauge_core_days and gauge_cluster)
    gauge_review = (dq_ok and gauge_like and not gauge_core and not gauge_soft
                    and not_fw_like_no_resp and p_lg_opp >= 1
                    and p_ok_opp == 0 and p_med_opp == 0)

    # ---- Watch large-gap/censored (ambiguous) ----
    large_gap_dominant = (p_lg_opp >= 1 and p_lg_opp >= (p_ok_opp + p_med_opp))
    censored_dominant = (p_cens >= 1 and p_cens >= (p_ok_opp + p_med_opp))
    watch_lgc = (dq_ok and (large_gap_dominant or censored_dominant) and obs_eff == 0)

    # ---- Watch low evidence (weak) ----
    watch_low = (dq_ok and obs_eff == 0
                 and (norm_anom > 0 or p_total_nr >= 1 or win_anom > 0
                      or (days_eff >= cfg.watch_days and total_opp >= 1)))

    review_dq = (not dq_ok) or (not hist_ok) or has_reset

    return {
        "dq_ok": dq_ok, "hist_ok": hist_ok, "review_dq": review_dq,
        "fw_core": fw_core, "fw_watch": fw_watch, "fw_like": fw_like,
        "gauge_core": gauge_core, "gauge_soft": gauge_soft, "gauge_review": gauge_review,
        "gauge_like": gauge_like, "watch_lgc": watch_lgc, "watch_low": watch_low,
        # evidence carried for messages / flags / would_have_been_*
        "days_eff": days_eff, "days_any": days_any, "cyc_eff": cyc_eff,
        "p_ok_nr": p_ok_nr, "p_total_nr": p_total_nr, "s_ok_nr": s_ok_nr, "hq_nr": hq_nr,
        "p_cens": p_cens, "p_lg_opp": p_lg_opp, "norm_anom": norm_anom, "conf_p": conf_p,
        "micro_only": micro_only, "cluster": cluster, "total_opp": total_opp,
        "large_gap_dominant": large_gap_dominant, "censored_dominant": censored_dominant,
        "no_real_opportunity": no_real_opportunity, "high_quality_dominant": high_quality_dominant,
        "fcc_eff_recent": fcc_eff_recent,
    }


def _label_from_gates(ev: Dict[str, object]) -> str:
    """Priority ladder (spec 13). Highest-priority satisfied gate wins."""
    if ev["review_dq"]:
        return ST_REVIEW_DQ
    if ev["fw_core"]:
        return ST_FW_CORE
    if ev["gauge_core"]:
        return ST_GAUGE_CORE
    if ev["fw_watch"]:
        return ST_FW_WATCH
    if ev["gauge_soft"]:
        return ST_GAUGE_SOFT
    if ev["gauge_review"]:
        return ST_GAUGE_REVIEW
    if ev["watch_lgc"]:
        return ST_WATCH_LGC
    if ev["watch_low"]:
        return ST_WATCH_LOW
    return ST_NORMAL


def _window_label_v2(r) -> str:
    if getattr(r, "window_data_quality_label", "WINDOW_QUALITY_OK") != "WINDOW_QUALITY_OK":
        return WIN_DQ
    n_ok = _g(r, "n_80_20_80_ok_complete_30d", 0)
    n_nr = _g(r, "n_80_20_80_no_response_30d", 0)
    n_lg = _g(r, "n_80_20_80_large_gap_30d", 0)
    n_cs = _g(r, "n_80_20_80_censored_30d", 0)
    fcc_eff = _g(r, "fcc_effective_changes_30d", 0)
    fcc_any = _g(r, "fcc_any_changes_30d", 0)
    if fcc_eff >= 1 or _g(r, "observed_response_30d", 0) >= 1:
        return WIN_NORMAL
    if n_ok >= 1 and n_nr >= 1:
        return WIN_NO_RESP
    if fcc_any >= 1 and fcc_eff == 0:
        return WIN_MICRO_ONLY
    if n_lg >= 1 and n_ok == 0:
        return WIN_LARGE_GAP
    if n_cs >= 1 and n_ok == 0:
        return WIN_CENSORED
    cyc = _g(r, "cycle_delta_30d", 0)
    n_dis = _g(r, "n_discharge_sessions_30d", 0)
    if cyc < 1.0 and n_dis <= 1:
        return WIN_LOW_INFO
    return WIN_INSUFF


def _flags(ev: Dict[str, object]) -> Dict[str, bool]:
    return {
        "fw_like_evidence_flag": bool(ev["fw_like"]),
        "gauge_like_evidence_flag": bool(ev["gauge_like"]),
        "micro_wobble_only_flag": bool(ev["micro_only"]),
        "large_gap_dominant_flag": bool(ev["large_gap_dominant"]),
        "censored_dominant_flag": bool(ev["censored_dominant"]),
        "state_history_insufficient_flag": bool(not ev["hist_ok"]),
        "data_quality_review_flag": bool(not ev["dq_ok"]),
    }


def _would_have_been(ev: Dict[str, object]) -> str:
    """For review/dq users: what tier the evidence resembles (diagnostic, spec 3.6)."""
    if ev["fw_like"] and ev["hq_nr"] >= 2:
        return "FW_CORE_LIKE"
    if ev["fw_like"]:
        return "FW_WATCH_LIKE"
    if ev["gauge_like"] and ev["no_real_opportunity"]:
        return "GAUGE_CORE_LIKE"
    if ev["gauge_like"]:
        return "GAUGE_SOFT_OR_REVIEW_LIKE"
    return "NONE"


def _messages(label: str, ev: Dict[str, object]) -> Dict[str, str]:
    d = int(ev["days_eff"])
    eng = ""
    usr = ""
    if label == ST_FW_CORE:
        # only cite the anomaly/conformal evidence when that gate path actually fired; otherwise
        # cite the deterministic no_response-count path that qualified the user (avoids a
        # self-contradictory "conformal p 0.749" on a count-qualified user — review OPS-6).
        anomaly_path = (ev["norm_anom"] >= 2.0 and ev["conf_p"] <= 0.01)
        why = (f"normative anomaly {ev['norm_anom']:.2f}, conformal p {ev['conf_p']:.3g}"
               if anomaly_path else
               f"{ev['p_ok_nr']} high-quality + {ev['s_ok_nr']} strict-band no_response confirmations")
        eng = (f"Prioritize BIOS/EC/battery-FW version and update review: "
               f"{ev['p_ok_nr']} high-quality discharge+recharge learning opportunities since the "
               f"last effective FCC change ({d}d ago) produced no FCC relearning step ({why}). "
               f"Candidate, not a confirmed FW fault.")
        usr = "No user-facing action; engineering FW review queued."
    elif label == ST_FW_WATCH:
        eng = (f"FW-like no-response signal but a core requirement is short "
               f"(staleness/cycles/quality). Monitor and add to FW engineering queue. "
               f"normative anomaly {ev['norm_anom']:.2f}, {ev['p_total_nr']} no_response since "
               f"last effective change ({d}d ago).")
        usr = "No user-facing action; monitoring."
    elif label == ST_GAUGE_CORE:
        eng = (f"High-confidence gauge reset/calibration target: no learning opportunity for "
               f"{d}d under both any-change and effective definitions, usage cluster "
               f"{ev['cluster']}.")
        usr = "A battery gauge recalibration (full charge/discharge cycle) is recommended."
    elif label == ST_GAUGE_SOFT:
        eng = (f"Soft calibration prompt: micro-wobbles present but no meaningful FCC relearning "
               f"step under the effective threshold for {d}d. Not a hard gauge reset target.")
        usr = "A full charge/discharge cycle may help the gauge recalibrate (low priority)."
    elif label == ST_GAUGE_REVIEW:
        eng = (f"Gauge-like staleness ({d}d) but large-gap opportunities prevent a firm "
               f"no-opportunity conclusion. Manual/engineering review.")
        usr = "No user-facing action; under review."
    elif label == ST_REVIEW_DQ:
        eng = (f"Data-quality/history review outranks action (would_have_been="
               f"{_would_have_been(ev)}). Collect more data or manual review.")
        usr = "No user-facing action; collecting more data."
    elif label in (ST_WATCH_LGC, ST_WATCH_LOW):
        eng = (f"Ambiguous/weak evidence ({d}d since effective change); monitor next window.")
        usr = "No user-facing action; monitoring."
    else:
        eng = "Responding normally; no concern."
        usr = "No action needed."
    return {"engineering_message_template": eng, "user_message_template": usr}


def _primary_reason(label: str, ev: Dict[str, object]) -> str:
    return {
        ST_FW_CORE: "high_quality_no_response_with_long_effective_staleness",
        ST_FW_WATCH: "fw_like_no_response_core_requirement_short",
        ST_GAUGE_CORE: "no_learning_opportunity_both_definitions_long_staleness",
        ST_GAUGE_SOFT: "micro_wobble_only_no_effective_relearn",
        ST_GAUGE_REVIEW: "gauge_like_but_large_gap_ambiguity",
        ST_REVIEW_DQ: "data_quality_or_history_review",
        ST_WATCH_LGC: "large_gap_or_censored_dominant",
        ST_WATCH_LOW: "weak_partial_evidence",
        ST_NORMAL: "responding_or_no_concern",
    }[label]


def _evidence_summary(ev: Dict[str, object]) -> str:
    return (f"days_eff={ev['days_eff']:.0f} days_any={ev['days_any']:.0f} "
            f"cyc_eff={ev['cyc_eff']:.0f} hq_nr={ev['hq_nr']} total_nr={ev['p_total_nr']} "
            f"cens={ev['p_cens']} lg_opp={ev['p_lg_opp']} opp={ev['total_opp']} "
            f"norm_anom={ev['norm_anom']:.2f} conf_p={ev['conf_p']:.3g} "
            f"micro_only={ev['micro_only']} cluster={ev['cluster']}")


def assign_labels_v2(daily: pd.DataFrame, cfg: PolicyConfigV2 = DEFAULT_POLICY_V2) -> pd.DataFrame:
    """Add stateful_label_v2 + window_label_v2 + all v2 policy fields + diagnostic flags."""
    daily = daily.copy()
    labels, windows, actions, confs, prios = [], [], [], [], []
    preasons, sreasons, evids, umsg, emsg, wouldbe = [], [], [], [], [], []
    flagcols: Dict[str, List[bool]] = {k: [] for k in (
        "fw_like_evidence_flag", "gauge_like_evidence_flag", "micro_wobble_only_flag",
        "large_gap_dominant_flag", "censored_dominant_flag",
        "state_history_insufficient_flag", "data_quality_review_flag")}
    for r in daily.itertuples(index=False):
        ev = _evaluate(r, cfg)
        lab = _label_from_gates(ev)
        labels.append(lab)
        windows.append(_window_label_v2(r))
        actions.append(ACTION[lab]); confs.append(CONFIDENCE[lab]); prios.append(PRIORITY[lab])
        preasons.append(_primary_reason(lab, ev))
        # secondary reasons: any other tier the evidence also touches
        sec = []
        for nm, key in (("fw_like", "fw_like"), ("gauge_like", "gauge_like"),
                        ("micro_wobble", "micro_only"), ("large_gap_dominant", "large_gap_dominant"),
                        ("censored_dominant", "censored_dominant")):
            if ev.get(key):
                sec.append(nm)
        sreasons.append(";".join(sec))
        evids.append(_evidence_summary(ev))
        m = _messages(lab, ev)
        umsg.append(m["user_message_template"]); emsg.append(m["engineering_message_template"])
        wouldbe.append(_would_have_been(ev) if lab in (ST_REVIEW_DQ, ST_GAUGE_REVIEW) else "")
        for k, v in _flags(ev).items():
            flagcols[k].append(v)
    daily["stateful_label_v2"] = labels
    daily["window_label_v2"] = windows
    daily["recommended_action"] = actions
    daily["confidence"] = confs
    daily["priority"] = prios
    daily["primary_reason"] = preasons
    daily["secondary_reasons"] = sreasons
    daily["evidence_summary"] = evids
    daily["user_message_template"] = umsg
    daily["engineering_message_template"] = emsg
    daily["would_have_been_label"] = wouldbe
    for k, v in flagcols.items():
        daily[k] = v
    return daily


ACTIONABLE_V2 = (ST_FW_CORE, ST_GAUGE_CORE, ST_FW_WATCH, ST_GAUGE_SOFT)


def apply_alert_cooldown_v2(daily: pd.DataFrame, cooldown_days: int = 30) -> pd.DataFrame:
    """Fire an alert only on a transition into an actionable v2 state, with cooldown.

    The cooldown resets when an effective FCC update happens (days_since drops), so a genuine
    new freeze after a recovery can re-alert (spec 12.6 carried into v2).
    """
    daily = daily.sort_values(["user_id", "window_end_date"], kind="stable").reset_index(drop=True)
    actionable = daily["stateful_label_v2"].isin(ACTIONABLE_V2)
    fired = np.zeros(len(daily), bool)
    consec = np.zeros(len(daily), int)
    for uid, idx in daily.groupby("user_id", sort=False).groups.items():
        idx = list(idx)
        last_alert_day = None
        prev_days_since = None
        run = 0
        for i in idx:
            row = daily.loc[i]
            wd = row["window_end_date"]
            ds = row.get("days_since_effective_fcc_change", np.nan)
            if prev_days_since is not None and np.isfinite(ds) and ds < prev_days_since:
                last_alert_day = None
            prev_days_since = ds
            run = run + 1 if row.get("window_label_v2") == WIN_NO_RESP else 0
            consec[i] = run
            if actionable.loc[i]:
                if last_alert_day is None or (wd - last_alert_day).days >= cooldown_days:
                    fired[i] = True
                    last_alert_day = wd
    daily["alert_fired"] = fired
    daily["consecutive_windows_opportunity_no_response"] = consec
    return daily


# --------------------------------------------------------------------------- #
def latest_snapshot_v2(daily: pd.DataFrame) -> pd.DataFrame:
    idx = daily.groupby("user_id")["window_end_date"].idxmax()
    return daily.loc[idx].copy().reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Engineering FW top-N queue (spec 9.4) — global ranking, independent of strict labels
# --------------------------------------------------------------------------- #
def fw_engineering_queue(snap: pd.DataFrame, ns=(50, 100)) -> Dict[int, pd.DataFrame]:
    """Ranked FW engineering queue. Includes FW Core/Watch + any high-anomaly or
    no_response>=2 (strict gate failed) user, ranked by normative anomaly then no_response.
    """
    s = snap.copy()
    norm_anom = s.get("cum_normative_fw_anomaly_score", pd.Series(0.0, index=s.index)).fillna(0.0)
    pers_anom = s.get("cum_fw_response_anomaly_score_personalized",
                      pd.Series(0.0, index=s.index)).fillna(0.0) \
        if "cum_fw_response_anomaly_score_personalized" in s.columns \
        else pd.Series(0.0, index=s.index)
    p_nr = s.get("cum_primary_no_response_since_last_effective_change",
                 pd.Series(0, index=s.index)).fillna(0)
    s_nr = s.get("cum_strict_no_response_since_last_effective_change",
                 pd.Series(0, index=s.index)).fillna(0)
    in_fw = s["stateful_label_v2"].isin([ST_FW_CORE, ST_FW_WATCH])
    include = (in_fw | (norm_anom >= 1.0) | (pers_anom >= 1.0) | (p_nr >= 2) | (s_nr >= 2)
               | (s["fw_like_evidence_flag"] if "fw_like_evidence_flag" in s else False))
    q = s[include].copy()
    q["queue_norm_anomaly"] = norm_anom[include].values
    q["queue_primary_no_response"] = p_nr[include].values
    q = q.sort_values(["queue_norm_anomaly", "queue_primary_no_response",
                       "days_since_effective_fcc_change"], ascending=False).reset_index(drop=True)
    q["fw_engineering_rank"] = np.arange(1, len(q) + 1)
    out = {}
    for N in ns:
        out[N] = q.head(N).copy()
    return out


def candidate_lists_v2(snap: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Split the snapshot into the per-tier CSV populations (spec 16.1)."""
    out = {
        "fw_core": snap[snap["stateful_label_v2"] == ST_FW_CORE].copy(),
        "fw_watch": snap[snap["stateful_label_v2"] == ST_FW_WATCH].copy(),
        "gauge_core": snap[snap["stateful_label_v2"] == ST_GAUGE_CORE].copy(),
        "gauge_soft": snap[snap["stateful_label_v2"] == ST_GAUGE_SOFT].copy(),
        "gauge_review": snap[snap["stateful_label_v2"] == ST_GAUGE_REVIEW].copy(),
        "review_dq": snap[snap["stateful_label_v2"] == ST_REVIEW_DQ].copy(),
        "watchlist": snap[snap["stateful_label_v2"].isin([ST_WATCH_LGC, ST_WATCH_LOW])].copy(),
    }
    for k in ("fw_core", "fw_watch"):
        if not out[k].empty and "cum_normative_fw_anomaly_score" in out[k].columns:
            out[k] = out[k].sort_values(
                ["cum_normative_fw_anomaly_score",
                 "cum_primary_no_response_since_last_effective_change"], ascending=False)
    if not out["gauge_core"].empty:
        out["gauge_core"] = out["gauge_core"].sort_values(
            "days_since_effective_fcc_change", ascending=False)
    return out
