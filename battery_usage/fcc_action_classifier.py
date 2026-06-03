"""Final intervention labelling on top of the FCC-learning audit features.

Given the per-user feature table from :mod:`battery_usage.fcc_learning`, assign each
user ONE mutually-exclusive label and a recommended operational action:

    REVIEW_INSUFFICIENT_DATA                 -> ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW
    NORMAL_OR_RESPONDING                     -> ACTION_NONE
    ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY    -> ACTION_GAUGE_RESET
    ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE -> ACTION_FW_CHECK
    WATCH_LOW_UPDATE_RATE_AMBIGUOUS          -> ACTION_MONITOR_OR_MANUAL_REVIEW

This is an AUDIT rule, not a predictive model: every decision is a transparent
threshold on interpretable features, and hardware identity (device_model / batt_vendor
/ batt_fru) is never read. Thresholds live in :class:`ClassifierThresholds`.

Resolution order note
---------------------
Spec section 8 lists GAUGE_RESET (8.3) before FW_CHECK (8.4), but the *defining*
discriminator in the prose is whether a genuine learning OPPORTUNITY exists: gauge =
"lacks the opportunity to re-learn", FW = "had opportunities yet FCC did not respond".
A user can satisfy gauge-MEDIUM (<=1 primary OK episode) while ALSO satisfying an FW
rule (e.g. one strict 90-10-90 full-range opportunity with zero response). In that
overlap the firmware check is the correct, higher-value action, so within a confidence
tier FW is resolved first. High-confidence gauge requires ZERO opportunities and so
never overlaps any FW rule. The applied order is therefore:

    review > normal > fw_high > gauge_high > fw_medium > gauge_medium > watch
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ---- labels & actions -------------------------------------------------------
LABEL_REVIEW = "REVIEW_INSUFFICIENT_DATA"
LABEL_NORMAL = "NORMAL_OR_RESPONDING"
LABEL_GAUGE = "ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY"
LABEL_FW = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
LABEL_WATCH = "WATCH_LOW_UPDATE_RATE_AMBIGUOUS"
LABEL_ORDER = [LABEL_REVIEW, LABEL_NORMAL, LABEL_GAUGE, LABEL_FW, LABEL_WATCH]

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
    "FCC/SoHが長期間更新されていませんが、ログ上は深い放電→再充電の学習機会が不足しています。"
    "安全な環境でOEM推奨のバッテリーゲージリセット/キャリブレーションを実施し、その後72h〜7日間の"
    "テレメトリでFCC更新有無を確認してください。"
)
MSG_FW = (
    "FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会が複数回確認されています。"
    "通常のキャリブレーション機会があったにもかかわらずFCC応答がないため、BIOS/EC/バッテリー関連FWの"
    "Version確認とアップデート有無確認を優先してください。アップデート後、次回の学習機会後72h〜7日間で"
    "FCC更新有無を確認してください。"
)
MSG_WATCH = (
    "FCC更新率は低いものの完全凍結ではない/学習機会が少ない/データ品質が中程度のため、"
    "FW確認に回す前にモニタリングまたは手動レビューを推奨します。"
)
MSG_REVIEW = (
    "観測期間・サンプル数・カウンタ整合性のいずれかが不足しており、信頼できる介入判定ができません。"
    "追加データ収集または手動レビューが必要です。"
)


@dataclass(frozen=True)
class ClassifierThresholds:
    """Every numeric cut from spec section 8 (no magic numbers in the logic)."""

    # ---- REVIEW gate (8.1) ----
    review_min_obs_days: float = 120.0
    review_min_samples: int = 200

    # ---- candidate quantiles (section 5): which active-reference percentile to use ----
    candidate_pct: str = "p05"  # "p05" or "p10"
    # ---- which FCC-response look-ahead window defines "no response" (sensitivity knob) ----
    response_window: str = "72h"  # one of "24h" / "72h" / "168h"

    # ---- GAUGE high confidence (8.3) ----
    gauge_hi_flat_tail_days: float = 120.0
    gauge_hi_tail_cycle_lt: float = 20.0
    gauge_hi_tail_min_rsoc_gt: float = 20.0
    gauge_hi_tail_swing_lt: float = 60.0
    gauge_hi_ac_ratio_ge: float = 0.80
    # ---- GAUGE medium confidence (8.3) ----
    gauge_med_flat_tail_days: float = 60.0
    gauge_med_tail_n_le: int = 1
    gauge_med_tail_cycle_lt: float = 30.0
    gauge_med_tail_min_rsoc_gt: float = 25.0
    gauge_med_tail_swing_lt: float = 50.0
    gauge_med_ac_ratio_ge: float = 0.75

    # ---- sub-reason cuts (gauge) ----
    sub_ac_bound_ge: float = 0.80
    sub_low_cycle_lt: float = 20.0
    sub_shallow_min_rsoc_gt: float = 20.0
    sub_shallow_swing_lt: float = 60.0

    # ---- FW high confidence (8.4) ----
    fw_hi_flat_tail_days: float = 180.0
    fw_hi_tail_cycle_ge: float = 30.0
    fw_hi_tail_n_8020_ge: int = 3
    fw_hi_tail_n_9010_ge: int = 1
    # ---- FW "stronger" zero-update sub-condition (8.4) ----
    fw_zero_total_n_8020_ge: int = 5
    # ---- FW medium confidence (8.4) ----
    fw_med_flat_tail_days: float = 120.0
    fw_med_tail_cycle_ge: float = 20.0
    fw_med_tail_n_8020_ge: int = 2
    fw_med_deep_min_rsoc_le: float = 10.0
    fw_med_deep_max_rsoc_ge: float = 90.0
    fw_med_resp_rate_le: float = 0.10
    # ---- sub-reason cuts (fw) ----
    fw_terminal_flat_days: float = 180.0
    fw_terminal_tail_n_8020_ge: int = 3


DEFAULT_THRESHOLDS = ClassifierThresholds()


# --------------------------------------------------------------------------- #
# Active-reference quantiles & candidate flags (section 5)
# --------------------------------------------------------------------------- #
def active_reference_mask(df: pd.DataFrame) -> pd.Series:
    """Healthy, well-observed, actively-updating users — the reference cohort."""
    return (
        (df["obs_days"] >= 180)
        & (df["cycle_delta"] >= 20)
        & (df["flat_tail_days"] < 60)
        & (df["data_quality_label"] == "QUALITY_OK")
    )


def active_reference_quantiles(df: pd.DataFrame) -> Dict[str, float]:
    """p05/p10 of the FCC-update RATES within the active-reference cohort."""
    ref = df[active_reference_mask(df)]
    out: Dict[str, float] = {"n_active_reference": int(len(ref))}
    for col in ("fcc_changes_per_100_cycles", "fcc_change_rate_per_100d"):
        vals = ref[col].to_numpy(dtype=float)
        vals = vals[np.isfinite(vals)]
        out[f"p05_{col}_active"] = float(np.percentile(vals, 5)) if vals.size else float("nan")
        out[f"p10_{col}_active"] = float(np.percentile(vals, 10)) if vals.size else float("nan")
    return out


def compute_candidate_flags(
    df: pd.DataFrame, q: Dict[str, float], pct: str = "p05",
) -> pd.DataFrame:
    """Add the FCC no/low-change candidate flags (section 5). Pure FCC-based audit
    flags — the gauge-vs-FW *branch* (section 8) instead leans on usage history + the
    post-opportunity FCC response, not on the FCC outcome alone."""
    cyc_thr = q[f"{pct}_fcc_changes_per_100_cycles_active"]
    time_thr = q[f"{pct}_fcc_change_rate_per_100d_active"]
    out = df.copy()
    out["no_fcc_update"] = (out["fcc_changes"] == 0) & (out["obs_days"] >= 120)
    out["long_terminal_flat"] = out["flat_tail_days"] >= 180
    out["low_update_per_cycle"] = (out["cycle_delta"] >= 50) & (out["fcc_changes_per_100_cycles"] <= cyc_thr)
    out["low_update_per_time"] = (out["obs_days"] >= 180) & (out["fcc_change_rate_per_100d"] <= time_thr)
    out["fcc_no_or_low_change_candidate"] = (
        out["no_fcc_update"] | out["long_terminal_flat"]
        | out["low_update_per_cycle"] | out["low_update_per_time"]
    )
    return out


# --------------------------------------------------------------------------- #
# Small predicate helpers (NaN-safe)
# --------------------------------------------------------------------------- #
def _is_zero(x) -> bool:
    """True only for a KNOWN exact-zero response rate (NaN/unknown is NOT zero)."""
    return bool(pd.notna(x) and x == 0)


def _le(x, thr) -> bool:
    return bool(pd.notna(x) and x <= thr)


def _ge(x, thr) -> bool:
    return bool(pd.notna(x) and x >= thr)


def _lt(x, thr) -> bool:
    return bool(pd.notna(x) and x < thr)


def _gt(x, thr) -> bool:
    return bool(pd.notna(x) and x > thr)


def _clip01(x: float) -> float:
    if not np.isfinite(x):
        return 0.0
    return float(min(1.0, max(0.0, x)))


# --------------------------------------------------------------------------- #
# Rule predicates
# --------------------------------------------------------------------------- #
def _gauge_high(r, t: ClassifierThresholds) -> bool:
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.gauge_hi_flat_tail_days)
        and r["tail_n_80_20_80_ok"] == 0
        and r["tail_n_90_10_90_ok"] == 0
        and (
            _lt(r["tail_cycle_delta"], t.gauge_hi_tail_cycle_lt)
            or _gt(r["tail_min_rsoc"], t.gauge_hi_tail_min_rsoc_gt)
            or _lt(r["tail_rsoc_swing"], t.gauge_hi_tail_swing_lt)
            or _ge(r["tail_ac_time_ratio"], t.gauge_hi_ac_ratio_ge)
        )
        and r["data_quality_label"] == "QUALITY_OK"
    )


def _gauge_medium(r, t: ClassifierThresholds) -> bool:
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.gauge_med_flat_tail_days)
        and r["tail_n_80_20_80_ok"] <= t.gauge_med_tail_n_le
        and (
            _lt(r["tail_cycle_delta"], t.gauge_med_tail_cycle_lt)
            or _gt(r["tail_min_rsoc"], t.gauge_med_tail_min_rsoc_gt)
            or _lt(r["tail_rsoc_swing"], t.gauge_med_tail_swing_lt)
            or _ge(r["tail_ac_time_ratio"], t.gauge_med_ac_ratio_ge)
        )
    )


def _fw_high(r, t: ClassifierThresholds) -> bool:
    w = t.response_window
    standard = (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.fw_hi_flat_tail_days)
        and _ge(r["tail_cycle_delta"], t.fw_hi_tail_cycle_ge)
        and (
            r["tail_n_80_20_80_ok"] >= t.fw_hi_tail_n_8020_ge
            or r["tail_n_90_10_90_ok"] >= t.fw_hi_tail_n_9010_ge
        )
        and (
            _is_zero(r[f"tail_response_rate_80_20_80_{w}"])
            or _is_zero(r[f"tail_response_rate_90_10_90_{w}"])
        )
        and r["data_quality_label"] == "QUALITY_OK"
    )
    stronger = (
        r["fcc_changes"] == 0
        and r["total_n_80_20_80_ok"] >= t.fw_zero_total_n_8020_ge
        and _is_zero(r[f"total_response_rate_80_20_80_{w}"])
    )
    return bool(standard or stronger)


def _fw_medium(r, t: ClassifierThresholds) -> bool:
    return (
        bool(r["fcc_no_or_low_change_candidate"])
        and _ge(r["flat_tail_days"], t.fw_med_flat_tail_days)
        and _ge(r["tail_cycle_delta"], t.fw_med_tail_cycle_ge)
        and (
            r["tail_n_80_20_80_ok"] >= t.fw_med_tail_n_8020_ge
            or (_le(r["tail_min_rsoc"], t.fw_med_deep_min_rsoc_le)
                and _ge(r["tail_max_rsoc"], t.fw_med_deep_max_rsoc_ge))
        )
        and _le(r[f"relevant_response_rate_{t.response_window}"], t.fw_med_resp_rate_le)
    )


# --------------------------------------------------------------------------- #
# Sub-reasons & evidence
# --------------------------------------------------------------------------- #
def _gauge_sub_reasons(r, t: ClassifierThresholds) -> str:
    reasons: List[str] = []
    if _ge(r["tail_ac_time_ratio"], t.sub_ac_bound_ge):
        reasons.append("NO_OPPORTUNITY_AC_BOUND")
    if _lt(r["tail_cycle_delta"], t.sub_low_cycle_lt):
        reasons.append("NO_OPPORTUNITY_LOW_CYCLING")
    if _gt(r["tail_min_rsoc"], t.sub_shallow_min_rsoc_gt) or _lt(r["tail_rsoc_swing"], t.sub_shallow_swing_lt):
        reasons.append("NO_OPPORTUNITY_SHALLOW_RANGE")
    return ";".join(reasons) if reasons else "NO_OPPORTUNITY_UNSPECIFIED"


def _fw_sub_reasons(r, t: ClassifierThresholds) -> str:
    w = t.response_window
    if (r["fcc_changes"] == 0 and r["total_n_80_20_80_ok"] >= t.fw_zero_total_n_8020_ge
            and _is_zero(r[f"total_response_rate_80_20_80_{w}"])):
        return "ZERO_UPDATE_AFTER_OPPORTUNITIES"
    if (r["fcc_changes"] > 0 and _ge(r["flat_tail_days"], t.fw_terminal_flat_days)
            and r["tail_n_80_20_80_ok"] >= t.fw_terminal_tail_n_8020_ge
            and _is_zero(r[f"tail_response_rate_80_20_80_{w}"])):
        return "TERMINAL_FREEZE_AFTER_OPPORTUNITIES"
    return "LOW_UPDATE_RATE_WITH_OPPORTUNITIES"


# --------------------------------------------------------------------------- #
# Scoring (section 9) — components normalised to [0, 1], score in [0, 100]
# --------------------------------------------------------------------------- #
def _dq_component(label: str) -> float:
    if label == "QUALITY_OK":
        return 1.0
    if label in ("QUALITY_SHORT_OBS", "QUALITY_SPARSE"):
        return 0.5
    return 0.0  # counter reset / pack change


def gauge_reset_score(r, t: ClassifierThresholds) -> float:
    long_flat = _clip01(r["flat_tail_days"] / t.fw_hi_flat_tail_days)
    n_opp = (r["tail_n_80_20_80_ok"] or 0) + (r["tail_n_90_10_90_ok"] or 0)
    no_opp = 1.0 if n_opp == 0 else _clip01(1.0 / (1.0 + n_opp))
    shallow_ac = _clip01(max(
        r["tail_ac_time_ratio"] if pd.notna(r["tail_ac_time_ratio"]) else 0.0,
        (t.gauge_hi_tail_swing_lt - r["tail_rsoc_swing"]) / t.gauge_hi_tail_swing_lt
        if pd.notna(r["tail_rsoc_swing"]) else 0.0,
    ))
    low_cycle = _clip01((t.gauge_med_tail_cycle_lt - (r["tail_cycle_delta"] or 0.0))
                        / t.gauge_med_tail_cycle_lt) if pd.notna(r["tail_cycle_delta"]) else 0.0
    dq = _dq_component(r["data_quality_label"])
    return round(30 * long_flat + 25 * no_opp + 20 * shallow_ac + 15 * low_cycle + 10 * dq, 1)


def fw_check_score(r, t: ClassifierThresholds) -> float:
    long_flat = _clip01(r["flat_tail_days"] / t.fw_hi_flat_tail_days)
    opp = _clip01(max((r["tail_n_80_20_80_ok"] or 0) / t.fw_zero_total_n_8020_ge,
                      (r["tail_n_90_10_90_ok"] or 0) / 2.0))
    rel = r[f"relevant_response_rate_{t.response_window}"]
    zero_resp = (1.0 - rel) if pd.notna(rel) else 0.0
    tail_cycle = _clip01((r["tail_cycle_delta"] or 0.0) / 50.0) if pd.notna(r["tail_cycle_delta"]) else 0.0
    dq = _dq_component(r["data_quality_label"])
    return round(30 * long_flat + 30 * opp + 20 * zero_resp + 10 * tail_cycle + 10 * dq, 1)


# --------------------------------------------------------------------------- #
# Main per-user classifier
# --------------------------------------------------------------------------- #
def classify_user(r, t: ClassifierThresholds = DEFAULT_THRESHOLDS) -> Dict[str, object]:
    """Assign ONE label + action + confidence + sub-reason + scores + evidence."""
    g_score = gauge_reset_score(r, t)
    f_score = fw_check_score(r, t)

    label: str
    confidence: str
    sub_reason = ""

    if (_lt(r["obs_days"], t.review_min_obs_days)
            or _lt(r["n_samples"], t.review_min_samples)
            or r["data_quality_label"] in ("QUALITY_COUNTER_RESET", "QUALITY_PACK_CHANGE_OR_ID_CHANGE")):
        label, confidence = LABEL_REVIEW, "review"
    elif not bool(r["fcc_no_or_low_change_candidate"]):
        label, confidence = LABEL_NORMAL, "high"
    elif _fw_high(r, t):
        label, confidence, sub_reason = LABEL_FW, "high", _fw_sub_reasons(r, t)
    elif _gauge_high(r, t):
        label, confidence, sub_reason = LABEL_GAUGE, "high", _gauge_sub_reasons(r, t)
    elif _fw_medium(r, t):
        label, confidence, sub_reason = LABEL_FW, "medium", _fw_sub_reasons(r, t)
    elif _gauge_medium(r, t):
        label, confidence, sub_reason = LABEL_GAUGE, "medium", _gauge_sub_reasons(r, t)
    else:
        label, confidence = LABEL_WATCH, "low"

    return {
        "final_label": label,
        "recommended_action": LABEL_ACTION[label],
        "confidence": confidence,
        "sub_reason": sub_reason,
        "gauge_reset_score_0_100": g_score,
        "fw_check_score_0_100": f_score,
        "primary_evidence": _evidence(r, label),
        "operational_message": _message(label),
    }


def _message(label: str) -> str:
    return {LABEL_GAUGE: MSG_GAUGE, LABEL_FW: MSG_FW, LABEL_WATCH: MSG_WATCH,
            LABEL_REVIEW: MSG_REVIEW, LABEL_NORMAL: ""}[label]


def _fmt(x, nd=1) -> str:
    return f"{x:.{nd}f}" if pd.notna(x) else "NA"


def _evidence(r, label: str) -> str:
    base = (f"flat_tail={_fmt(r['flat_tail_days'])}d, fcc_changes={int(r['fcc_changes'])}, "
            f"tail_cyc={_fmt(r['tail_cycle_delta'])}, "
            f"tail_ok[90/80/85]={int(r['tail_n_90_10_90_ok'])}/{int(r['tail_n_80_20_80_ok'])}/"
            f"{int(r['tail_n_85_15_85_ok'])}")
    if label == LABEL_GAUGE:
        return (base + f", ac={_fmt(r['tail_ac_time_ratio'],2)}, min_rsoc={_fmt(r['tail_min_rsoc'])}, "
                f"swing={_fmt(r['tail_rsoc_swing'])} -> no learning opportunity in flat tail")
    if label == LABEL_FW:
        return (base + f", resp72h(rel)={_fmt(r['relevant_response_rate_72h'],3)} "
                f"-> opportunities present but FCC did not respond")
    if label == LABEL_NORMAL:
        return base + " -> FCC still updating / not a no-low-change candidate"
    if label == LABEL_REVIEW:
        return (f"obs_days={_fmt(r['obs_days'])}, n_samples={int(r['n_samples'])}, "
                f"quality={r['data_quality_label']} -> insufficient/uncertain data")
    return base + f", resp72h(rel)={_fmt(r['relevant_response_rate_72h'],3)} -> ambiguous low-update"


def classify_frame(df: pd.DataFrame, t: ClassifierThresholds = DEFAULT_THRESHOLDS) -> pd.DataFrame:
    """Apply :func:`classify_user` to every row; returns the classification columns."""
    res = df.apply(lambda r: classify_user(r, t), axis=1, result_type="expand")
    return res
