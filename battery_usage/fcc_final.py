"""Final intervention labelling (v2) — censoring-aware, large-gap-safe, REVIEW-subdivided.

This supersedes :mod:`battery_usage.fcc_action_classifier` for the *final validation*
deliverable (the original stays intact for the baseline). Differences vs the baseline:

  * GAUGE label renamed ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY ->
    ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY (it means "insufficient deep
    discharge->recharge opportunity to re-learn FCC", not "literally zero").
  * FW non-response evidence uses RIGHT-CENSORING-aware counts
    (``tail_n_unresponded_*_complete_window``): an opportunity whose 72h window runs past
    last_ts is ``censored`` and is NOT counted as a no-response (spec 1.2 / 1.4).
  * GAUGE high confidence additionally requires ZERO large-gap opportunities, so a
    gappy full-range discharge can't be mistaken for "no opportunity" (spec 1.3); such
    users fall to WATCH with watch_subreason POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS.
  * REVIEW and WATCH carry sub-reasons + a review priority (spec 1.5 / 3.5).

Hardware identity (device_model/batt_vendor/batt_fru/manufacturer/design_capacity/MTM/
UUID/serial) is NEVER read here — classification is a transparent rule on usage + FCC
response only. K_STRICT (strict-band unresponded count for FW-high) is justified
empirically in fcc_justify (active-reference no-response probability by k).

Applied order (spec 3.2): review > normal > fw_high > gauge_high > fw_medium >
gauge_medium > watch. FW resolves before GAUGE within a tier so an opportunity-bearing
user is never told to "go discharge first"; GAUGE-high requires zero opportunities
(ok AND large_gap) so it never collides with any FW rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

# Reuse the baseline candidate-flag machinery (FCC no/low-change audit, spec section 5).
from .fcc_action_classifier import (
    active_reference_mask, active_reference_quantiles, compute_candidate_flags,
    _is_zero, _le, _ge, _lt, _gt, _clip01, _dq_component,
)

THRESHOLD_VERSION = "v2.0-final"
RULE_VERSION = "v2.0-final"
LABEL_VERSION = "v2.0-final"

# ---- final labels (spec 3.1) -----------------------------------------------
LABEL_REVIEW = "REVIEW_INSUFFICIENT_DATA"
LABEL_NORMAL = "NORMAL_OR_RESPONDING"
LABEL_FW = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
LABEL_GAUGE = "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY"
LABEL_WATCH = "WATCH_LOW_UPDATE_RATE_AMBIGUOUS"
LABEL_ORDER = [LABEL_REVIEW, LABEL_NORMAL, LABEL_FW, LABEL_GAUGE, LABEL_WATCH]

# Baseline -> final label rename map (spec 1.1, written to fcc_label_name_mapping.csv).
LABEL_NAME_MAPPING = {
    "ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY": LABEL_GAUGE,
    "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE": LABEL_FW,
    "REVIEW_INSUFFICIENT_DATA": LABEL_REVIEW,
    "NORMAL_OR_RESPONDING": LABEL_NORMAL,
    "WATCH_LOW_UPDATE_RATE_AMBIGUOUS": LABEL_WATCH,
}

ACTION_REVIEW = "ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW"
ACTION_NONE = "ACTION_NONE"
ACTION_GAUGE_RESET = "ACTION_GAUGE_RESET"
ACTION_FW_CHECK = "ACTION_FW_CHECK"
ACTION_MONITOR = "ACTION_MONITOR_OR_MANUAL_REVIEW"
LABEL_ACTION = {
    LABEL_REVIEW: ACTION_REVIEW, LABEL_NORMAL: ACTION_NONE, LABEL_GAUGE: ACTION_GAUGE_RESET,
    LABEL_FW: ACTION_FW_CHECK, LABEL_WATCH: ACTION_MONITOR,
}
LABEL_COLORS = {
    LABEL_REVIEW: "lightgray", LABEL_NORMAL: "steelblue", LABEL_GAUGE: "darkorange",
    LABEL_FW: "darkred", LABEL_WATCH: "gold",
}

MSG_GAUGE = (
    "FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会が十分に確認できません"
    "（OK品質の機会が無く、large-gapを含めても判定可能な機会がない）。安全な環境でOEM推奨のバッテリー"
    "ゲージリセット/キャリブレーションを実施し、その後72h〜7日間のテレメトリでFCC更新有無を確認してください。"
)
MSG_FW = (
    "FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会（完全窓・OK品質）が複数回確認"
    "されるのにFCCが応答していません。BIOS/EC/バッテリー関連FWのVersion確認とアップデート有無確認を優先"
    "してください。アップデート後、次回の学習機会後72h〜7日間でFCC更新有無を確認してください。"
)
MSG_WATCH = (
    "FCC更新率は低いが完全凍結ではない/学習機会がlarge-gapまたは打ち切りで確証が弱い/境界的のため、"
    "FW確認に回す前にモニタリングまたは手動レビューを推奨します。"
)
MSG_REVIEW = (
    "観測期間・サンプル数・カウンタ整合性のいずれかが不足しており信頼できる判定ができません。"
    "review_priorityに従い追加データ収集または手動レビューを行ってください。"
)


@dataclass(frozen=True)
class FinalThresholds:
    """All cuts for the final classifier (no magic numbers in the logic)."""

    # REVIEW gate
    review_min_obs_days: float = 120.0
    review_min_samples: int = 200
    # candidate quantile percentile (active-reference); response window for completeness
    candidate_pct: str = "p05"
    response_window: str = "72h"

    # FW high confidence (spec 3.3); K_STRICT justified empirically in fcc_justify
    fw_hi_flat_tail_days: float = 180.0
    fw_hi_tail_cycle_ge: float = 30.0
    fw_hi_unresponded_8020_ge: int = 3
    fw_hi_unresponded_9010_ge: int = 2          # K_STRICT (active-ref no-resp proxy ~5%)
    # FW medium confidence (extension: weaker thresholds, still complete-window evidence)
    fw_med_flat_tail_days: float = 120.0
    fw_med_tail_cycle_ge: float = 20.0
    fw_med_unresponded_8020_ge: int = 2         # primary k=2 -> false-alarm proxy ~10%

    # GAUGE high confidence (spec 3.4) — requires ZERO ok AND zero large-gap opportunities
    gauge_hi_flat_tail_days: float = 120.0
    gauge_med_flat_tail_days: float = 60.0
    gauge_hi_tail_cycle_lt: float = 20.0
    gauge_hi_tail_min_rsoc_gt: float = 20.0
    gauge_hi_tail_swing_lt: float = 60.0
    gauge_hi_ac_ratio_ge: float = 0.80
    gauge_med_tail_cycle_lt: float = 30.0
    gauge_med_tail_min_rsoc_gt: float = 25.0
    gauge_med_tail_swing_lt: float = 50.0
    gauge_med_ac_ratio_ge: float = 0.75

    # sub-reason cuts (gauge)
    sub_ac_bound_ge: float = 0.80
    sub_low_cycle_lt: float = 20.0
    sub_shallow_min_rsoc_gt: float = 20.0
    sub_shallow_swing_lt: float = 60.0
    # WATCH borderline window
    watch_flat_tail_lo: float = 60.0


DEFAULT_FINAL_THRESHOLDS = FinalThresholds()


# --------------------------------------------------------------------------- #
# Rule predicates (all NaN-safe; complete-window / large-gap aware)
# --------------------------------------------------------------------------- #
def _u8020(r, w: str = "72h") -> int:
    """Tail OK + complete-window + no-response 80/20/80 count at window ``w``."""
    v = r.get(f"tail_n_unresponded_80_20_80_complete_window_{w}",
              r.get("tail_n_unresponded_80_20_80_complete_window", 0))
    return int(v or 0)


def _u9010(r, w: str = "72h") -> int:
    v = r.get(f"tail_n_unresponded_90_10_90_complete_window_{w}",
              r.get("tail_n_unresponded_90_10_90_complete_window", 0))
    return int(v or 0)


def _fw_high(r, t: FinalThresholds) -> bool:
    w = t.response_window
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.fw_hi_flat_tail_days)
        and _ge(r["tail_cycle_delta"], t.fw_hi_tail_cycle_ge)
        and r["data_quality_label"] == "QUALITY_OK"
        and (_u8020(r, w) >= t.fw_hi_unresponded_8020_ge or _u9010(r, w) >= t.fw_hi_unresponded_9010_ge)
    )


def _fw_medium(r, t: FinalThresholds) -> bool:
    w = t.response_window
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.fw_med_flat_tail_days)
        and _ge(r["tail_cycle_delta"], t.fw_med_tail_cycle_ge)
        and _u8020(r, w) >= t.fw_med_unresponded_8020_ge
    )


def _no_opportunity(r) -> bool:
    """No judgeable learning opportunity at all in the tail — ok AND large-gap both zero
    (spec 1.3: a large-gap full-range discharge is a POSSIBLE opportunity, so its presence
    forbids the 'no opportunity' conclusion)."""
    return (r["tail_n_80_20_80_ok"] == 0 and r["tail_n_90_10_90_ok"] == 0
            and r.get("tail_n_80_20_80_large_gap", 0) == 0
            and r.get("tail_n_90_10_90_large_gap", 0) == 0)


def _gauge_usage(r, t: FinalThresholds, medium: bool) -> bool:
    cyc = t.gauge_med_tail_cycle_lt if medium else t.gauge_hi_tail_cycle_lt
    mr = t.gauge_med_tail_min_rsoc_gt if medium else t.gauge_hi_tail_min_rsoc_gt
    sw = t.gauge_med_tail_swing_lt if medium else t.gauge_hi_tail_swing_lt
    ac = t.gauge_med_ac_ratio_ge if medium else t.gauge_hi_ac_ratio_ge
    return (_lt(r["tail_cycle_delta"], cyc) or _gt(r["tail_min_rsoc"], mr)
            or _lt(r["tail_rsoc_swing"], sw) or _ge(r["tail_ac_time_ratio"], ac))


def _gauge_high(r, t: FinalThresholds) -> bool:
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.gauge_hi_flat_tail_days)
        and _no_opportunity(r)
        and _gauge_usage(r, t, medium=False)
        and r["data_quality_label"] == "QUALITY_OK"
    )


def _gauge_medium(r, t: FinalThresholds) -> bool:
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.gauge_med_flat_tail_days)
        and _no_opportunity(r)
        and _gauge_usage(r, t, medium=True)
    )


# --------------------------------------------------------------------------- #
# Sub-reasons
# --------------------------------------------------------------------------- #
def _fw_subreason(r, t: FinalThresholds) -> str:
    w = t.response_window
    if r["fcc_changes"] == 0 and _u8020(r, w) >= t.fw_hi_unresponded_8020_ge:
        return "ZERO_UPDATE_AFTER_OPPORTUNITIES"
    if r["fcc_changes"] > 0 and _ge(r["flat_tail_days"], t.fw_hi_flat_tail_days) and _u8020(r, w) >= t.fw_hi_unresponded_8020_ge:
        return "TERMINAL_FREEZE_AFTER_OPPORTUNITIES"
    return "LOW_UPDATE_RATE_WITH_OPPORTUNITIES"


def _gauge_subreason(r, t: FinalThresholds) -> str:
    reasons: List[str] = []
    if _ge(r["tail_ac_time_ratio"], t.sub_ac_bound_ge):
        reasons.append("NO_OPPORTUNITY_AC_BOUND")
    if _lt(r["tail_cycle_delta"], t.sub_low_cycle_lt):
        reasons.append("NO_OPPORTUNITY_LOW_CYCLING")
    if _gt(r["tail_min_rsoc"], t.sub_shallow_min_rsoc_gt) or _lt(r["tail_rsoc_swing"], t.sub_shallow_swing_lt):
        reasons.append("NO_OPPORTUNITY_SHALLOW_RANGE")
    return ";".join(reasons) if reasons else "NO_OPPORTUNITY_UNSPECIFIED"


def _watch_subreason(r, t: FinalThresholds) -> str:
    """Why a candidate is parked in WATCH rather than actioned (spec 3.5)."""
    w = t.response_window
    ok = r["tail_n_80_20_80_ok"] + r["tail_n_90_10_90_ok"]
    lg = r.get("tail_n_80_20_80_large_gap", 0) + r.get("tail_n_90_10_90_large_gap", 0)
    cens = r.get(f"tail_n_censored_80_20_80_{w}", r.get("tail_n_censored_80_20_80", 0)) \
        + r.get(f"tail_n_censored_90_10_90_{w}", r.get("tail_n_censored_90_10_90", 0))
    unresp = _u8020(r, w) + _u9010(r, w)
    rel = r.get(f"relevant_response_rate_{w}", r.get("relevant_response_rate_72h", float("nan")))

    if ok == 0 and lg > 0:
        return "WATCH_POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS"
    if ok > 0 and unresp == 0 and cens > 0:
        return "WATCH_INSUFFICIENT_COMPLETE_WINDOWS"
    if pd.notna(rel) and rel > 0:
        return "WATCH_LOW_UPDATE_RATE_BUT_SOME_RESPONSE"
    if _lt(r["flat_tail_days"], t.gauge_med_flat_tail_days) or _lt(r["tail_cycle_delta"], t.fw_med_tail_cycle_ge):
        # candidate but flat tail short or barely cycled -> active-ish low cadence
        if _lt(r["flat_tail_days"], t.gauge_med_flat_tail_days):
            return "WATCH_ACTIVE_LOW_CADENCE"
        return "WATCH_BORDERLINE_FLAT_TAIL_OR_CYCLES"
    if _ge(r["flat_tail_days"], t.gauge_med_flat_tail_days) and _lt(r["flat_tail_days"], t.fw_hi_flat_tail_days):
        return "WATCH_BORDERLINE_FLAT_TAIL_OR_CYCLES"
    return "WATCH_OTHER_AMBIGUOUS"


def _review_subreason_priority(r, t: FinalThresholds) -> tuple:
    """(review_subreason, review_priority, manual_review_reason) per spec 1.5."""
    dq = r["data_quality_label"]
    cand = bool(r["fcc_no_or_low_change_candidate"])
    stale_like = _ge(r["flat_tail_days"], 60.0)
    if dq == "QUALITY_COUNTER_RESET":
        return ("REVIEW_COUNTER_RESET", "high",
                "cycleCountが減少（カウンタリセット/パック異常疑い）。生ログ確認が必要。")
    if dq == "QUALITY_PACK_CHANGE_OR_ID_CHANGE":
        return ("REVIEW_COUNTER_RESET", "high",
                "serialNumber変化（パック交換/ID変化疑い）。生ログ確認が必要。")
    if dq == "QUALITY_SPARSE":
        return ("REVIEW_SPARSE_LOG", "medium",
                "ログが疎（p95サンプル間隔>24hまたはサンプル少）。episode判定の信頼度が低い。")
    if _lt(r["obs_days"], t.review_min_obs_days):
        if cand:
            return ("REVIEW_NO_LOW_CHANGE_BUT_INSUFFICIENT_DATA", "high",
                    "no/low-change候補だが観測期間<120日。優先的に追加観測。")
        if stale_like:
            return ("REVIEW_SHORT_OBS_STALE_OR_VERY_STALE", "high",
                    "観測期間<120日だがflat_tail>=60日（stale様）。優先的に追加観測。")
        return ("REVIEW_SHORT_OBS_ACTIVE_LIKE", "low",
                "観測期間<120日でactive様（flat_tail<60）。経過観察で十分なことが多い。")
    if _lt(r["n_samples"], t.review_min_samples):
        return ("REVIEW_OTHER_INSUFFICIENT_DATA", "medium", "サンプル数<200。追加観測が必要。")
    return ("REVIEW_OTHER_INSUFFICIENT_DATA", "medium", "データ不足によりレビュー対象。")


# --------------------------------------------------------------------------- #
# Scoring (continuity with baseline; complete-window aware for FW)
# --------------------------------------------------------------------------- #
def gauge_reset_score(r, t: FinalThresholds) -> float:
    long_flat = _clip01(r["flat_tail_days"] / t.fw_hi_flat_tail_days)
    n_opp = (r["tail_n_80_20_80_ok"] or 0) + (r["tail_n_90_10_90_ok"] or 0) \
        + (r.get("tail_n_80_20_80_large_gap", 0) or 0)
    no_opp = 1.0 if n_opp == 0 else _clip01(1.0 / (1.0 + n_opp))
    shallow_ac = _clip01(max(
        r["tail_ac_time_ratio"] if pd.notna(r["tail_ac_time_ratio"]) else 0.0,
        (t.gauge_hi_tail_swing_lt - r["tail_rsoc_swing"]) / t.gauge_hi_tail_swing_lt
        if pd.notna(r["tail_rsoc_swing"]) else 0.0))
    low_cycle = _clip01((t.gauge_med_tail_cycle_lt - (r["tail_cycle_delta"] or 0.0))
                        / t.gauge_med_tail_cycle_lt) if pd.notna(r["tail_cycle_delta"]) else 0.0
    dq = _dq_component(r["data_quality_label"])
    return round(30 * long_flat + 25 * no_opp + 20 * shallow_ac + 15 * low_cycle + 10 * dq, 1)


def fw_check_score(r, t: FinalThresholds) -> float:
    long_flat = _clip01(r["flat_tail_days"] / t.fw_hi_flat_tail_days)
    opp = _clip01(max(_u8020(r) / 5.0, _u9010(r) / 2.0))
    rel = r.get("relevant_response_rate_72h", float("nan"))
    zero_resp = (1.0 - rel) if pd.notna(rel) else (1.0 if (_u8020(r) + _u9010(r)) > 0 else 0.0)
    tail_cycle = _clip01((r["tail_cycle_delta"] or 0.0) / 50.0) if pd.notna(r["tail_cycle_delta"]) else 0.0
    dq = _dq_component(r["data_quality_label"])
    return round(30 * long_flat + 30 * opp + 20 * zero_resp + 10 * tail_cycle + 10 * dq, 1)


# --------------------------------------------------------------------------- #
# Main per-user classifier
# --------------------------------------------------------------------------- #
def classify_user_final(r, t: FinalThresholds = DEFAULT_FINAL_THRESHOLDS) -> Dict[str, object]:
    g_score = gauge_reset_score(r, t)
    f_score = fw_check_score(r, t)
    label = confidence = primary_reason = ""
    subreason = watch_subreason = review_subreason = review_priority = manual_review_reason = ""

    is_review = (_lt(r["obs_days"], t.review_min_obs_days)
                 or _lt(r["n_samples"], t.review_min_samples)
                 or r["data_quality_label"] in ("QUALITY_COUNTER_RESET", "QUALITY_PACK_CHANGE_OR_ID_CHANGE"))

    if is_review:
        label, confidence = LABEL_REVIEW, "review"
        review_subreason, review_priority, manual_review_reason = _review_subreason_priority(r, t)
        primary_reason = review_subreason
    elif not bool(r["fcc_no_or_low_change_candidate"]):
        label, confidence, primary_reason = LABEL_NORMAL, "high", "NOT_NO_LOW_CHANGE_CANDIDATE"
    elif _fw_high(r, t):
        label, confidence, subreason = LABEL_FW, "high", _fw_subreason(r, t)
        primary_reason = "FW_HIGH_UNRESPONDED_COMPLETE_WINDOWS"
    elif _gauge_high(r, t):
        label, confidence, subreason = LABEL_GAUGE, "high", _gauge_subreason(r, t)
        primary_reason = "GAUGE_HIGH_NO_OPPORTUNITY"
    elif _fw_medium(r, t):
        label, confidence, subreason = LABEL_FW, "medium", _fw_subreason(r, t)
        primary_reason = "FW_MEDIUM_UNRESPONDED_COMPLETE_WINDOWS"
    elif _gauge_medium(r, t):
        label, confidence, subreason = LABEL_GAUGE, "medium", _gauge_subreason(r, t)
        primary_reason = "GAUGE_MEDIUM_NO_OPPORTUNITY"
    else:
        label, confidence = LABEL_WATCH, "low"
        watch_subreason = _watch_subreason(r, t)
        primary_reason = watch_subreason

    return {
        "final_label": label,
        "recommended_action": LABEL_ACTION[label],
        "confidence": confidence,
        "primary_reason": primary_reason,
        "subreason": subreason,
        "watch_subreason": watch_subreason,
        "review_subreason": review_subreason,
        "review_priority": review_priority,
        "manual_review_reason": manual_review_reason,
        "gauge_reset_score_0_100": g_score,
        "fw_check_score_0_100": f_score,
        "primary_evidence": _evidence(r, label),
        "operational_message": {LABEL_GAUGE: MSG_GAUGE, LABEL_FW: MSG_FW, LABEL_WATCH: MSG_WATCH,
                                LABEL_REVIEW: MSG_REVIEW, LABEL_NORMAL: ""}[label],
        "threshold_version": THRESHOLD_VERSION,
        "rule_version": RULE_VERSION,
        "label_version": LABEL_VERSION,
    }


def _fmt(x, nd=1) -> str:
    return f"{x:.{nd}f}" if pd.notna(x) else "NA"


def _evidence(r, label: str) -> str:
    base = (f"flat_tail={_fmt(r['flat_tail_days'])}d, fcc_changes={int(r['fcc_changes'])}, "
            f"tail_cyc={_fmt(r['tail_cycle_delta'])}, "
            f"tail_ok[90/80]={int(r['tail_n_90_10_90_ok'])}/{int(r['tail_n_80_20_80_ok'])}, "
            f"unresp_complete[90/80]={_u9010(r)}/{_u8020(r)}, "
            f"large_gap[90/80]={int(r.get('tail_n_90_10_90_large_gap', 0))}/"
            f"{int(r.get('tail_n_80_20_80_large_gap', 0))}")
    if label == LABEL_GAUGE:
        return base + f", ac={_fmt(r['tail_ac_time_ratio'],2)}, min_rsoc={_fmt(r['tail_min_rsoc'])} -> insufficient learning opportunity"
    if label == LABEL_FW:
        return base + " -> complete-window opportunities present but FCC did not respond"
    if label == LABEL_NORMAL:
        return base + " -> FCC still updating / not a no-low-change candidate"
    if label == LABEL_REVIEW:
        return (f"obs_days={_fmt(r['obs_days'])}, n_samples={int(r['n_samples'])}, "
                f"quality={r['data_quality_label']} -> insufficient/uncertain data")
    return base + " -> ambiguous (watch)"


def classify_frame_final(df: pd.DataFrame, t: FinalThresholds = DEFAULT_FINAL_THRESHOLDS) -> pd.DataFrame:
    return df.apply(lambda r: classify_user_final(r, t), axis=1, result_type="expand")
