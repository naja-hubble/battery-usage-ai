#!/usr/bin/env python
"""OD2 re-analysis - Phase 2: offline triage labels on the corrected relearn opportunities.

Re-runs the final gauge-vs-FW triage (fcc_final.classify_user_final) on the OD2 feature
table (Type A -> strict slot, Type B -> primary slot; union == no-opportunity gate) with
the 168h primary response window, and compares the resulting labels to the production
baseline (NORMAL 327 / REVIEW 338 / WATCH 55 / GAUGE 18 / FW 14).

Because Type B fires ~3x more often than the old primary band and the window is now 168h,
the FW k-thresholds are RE-JUSTIFIED empirically from the healthy (active-reference) users'
per-opportunity response rate. Both the old-k and re-justified-k label sets are produced.

Nothing in the OD1 pipeline is modified. The classifier is reused by import with an OD2
FinalThresholds config. Outputs: data/processed/fcc_relearn_od2/offline/.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from battery_usage.relearn_od2_features import build_od2_cohort_features
from battery_usage.fcc_action_classifier import (
    active_reference_mask, active_reference_quantiles, compute_candidate_flags,
)
from battery_usage import fcc_final
from battery_usage.fcc_final import (
    FinalThresholds, classify_frame_final, LABEL_ORDER,
)

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
PARQUET = PROC / "battery_timeseries_all.parquet"
PHASE1 = PROC / "fcc_relearn_od2" / "phase1" / "od2_opportunities.parquet"
OUT = PROC / "fcc_relearn_od2" / "offline"
REPORTS = REPO / "data" / "reports"
BASELINE = PROC / "fcc_final_action_labels.csv"
PRIMARY_W = 168


def load_cohort(limit):
    cols = ["user_id", "timestamp", "chargeStatus", "acdcMode",
            "remainingCapacityInPercentage", "cycleCount", "fullChargeCapacity",
            "soh_design_pct", "serialNumber"]
    df = pd.read_parquet(PARQUET, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if limit:
        keep = df["user_id"].drop_duplicates().head(limit)
        df = df[df["user_id"].isin(keep)]
    return df


def k_for_false_alarm(p_response: float, target: float) -> int:
    """Smallest k with P(k independent no-responses) = (1-p)^k <= target."""
    if not np.isfinite(p_response) or p_response <= 0:
        return 99
    q = 1.0 - p_response
    if q <= 0:
        return 1
    return max(1, int(math.ceil(math.log(target) / math.log(q))))


def justify_k(feat: pd.DataFrame) -> dict:
    """Healthy per-opportunity response rate at 168h -> re-justified FW k-thresholds.

    Uses the Phase-1 episode table restricted to active-reference (healthy) users' OK
    episodes: Type B -> primary(80/20/80) slot, Type A -> strict(90/10/90) slot.
    """
    ref_users = set(feat.loc[active_reference_mask(feat), "user_id"])
    eps = pd.read_parquet(PHASE1, columns=["user_id", "opportunity_type",
                                           "episode_quality", f"response_status_{PRIMARY_W}h"])
    eps = eps[(eps["user_id"].isin(ref_users)) & (eps["episode_quality"] == "ok")]
    out = {"n_active_reference": int(len(ref_users))}
    for opp, band in (("B", "80_20_80"), ("A", "90_10_90")):
        sub = eps[eps["opportunity_type"] == opp]
        known = sub[sub[f"response_status_{PRIMARY_W}h"].isin(["responded", "no_response"])]
        resp = int((known[f"response_status_{PRIMARY_W}h"] == "responded").sum())
        p = round(resp / len(known), 4) if len(known) else float("nan")
        out[f"p_response_{band}_168h"] = p
        out[f"n_known_{band}"] = int(len(known))
        out[f"k_fa05_{band}"] = k_for_false_alarm(p, 0.05)
        out[f"k_fa10_{band}"] = k_for_false_alarm(p, 0.10)
    return out


def label_counts(series: pd.Series) -> dict:
    vc = series.value_counts()
    return {lab: int(vc.get(lab, 0)) for lab in LABEL_ORDER}


def classify_with(feat: pd.DataFrame, thr: FinalThresholds) -> pd.Series:
    res = classify_frame_final(feat, thr)
    return res["final_label"]


def load_baseline():
    for enc in ("cp932", "utf-8", "latin-1"):
        try:
            b = pd.read_csv(BASELINE, usecols=["user_id", "final_label"], encoding=enc)
            return b
        except (UnicodeDecodeError, ValueError):
            continue
    return pd.read_csv(BASELINE, usecols=["user_id", "final_label"], encoding_errors="replace")


def transition_matrix(baseline: pd.DataFrame, od2_labels: pd.Series, feat: pd.DataFrame) -> pd.DataFrame:
    m = feat[["user_id"]].copy()
    m["od2_label"] = od2_labels.to_numpy()
    j = m.merge(baseline.rename(columns={"final_label": "baseline_label"}), on="user_id", how="left")
    ct = pd.crosstab(j["baseline_label"], j["od2_label"])
    ct = ct.reindex(index=[l for l in LABEL_ORDER if l in ct.index],
                    columns=[l for l in LABEL_ORDER if l in ct.columns], fill_value=0)
    return ct, j


SHORT = {
    "REVIEW_INSUFFICIENT_DATA": "REVIEW", "NORMAL_OR_RESPONDING": "NORMAL",
    "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE": "FW",
    "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY": "GAUGE",
    "WATCH_LOW_UPDATE_RATE_AMBIGUOUS": "WATCH",
}


def _short_counts(d: dict) -> dict:
    return {SHORT.get(k, k): v for k, v in d.items()}


def write_report(kj, base_counts, oldk_counts, rej_counts, thr_rej, ct_oldk, ct_rej, n_users):
    L = []
    L.append("# OD2 re-analysis - Phase 2: offline triage labels on corrected relearn opportunities\n")
    L.append(f"_Cohort {n_users} users. Classifier = fcc_final.classify_user_final (reused by "
             f"import), response window **168h**, Type A->strict slot / Type B->primary slot. "
             f"OD1 files untouched._\n")
    L.append("## 1. k-threshold re-justification (healthy per-opportunity response @168h)\n")
    L.append("\n".join(f"- **{k}**: {v}" for k, v in kj.items()) + "\n")
    L.append(f"Re-justified FW thresholds used: primary(Type B) k={thr_rej.fw_hi_unresponded_8020_ge} "
             f"(medium k={thr_rej.fw_med_unresponded_8020_ge}), strict(Type A) "
             f"k={thr_rej.fw_hi_unresponded_9010_ge}.\n")
    L.append("## 2. Label distributions (baseline vs OD2)\n")
    dist = pd.DataFrame({
        "label": list(_short_counts(base_counts).keys()),
        "baseline(OD1,72h)": list(_short_counts(base_counts).values()),
        "OD2 old-k(168h)": list(_short_counts(oldk_counts).values()),
        "OD2 rejustified-k(168h)": list(_short_counts(rej_counts).values()),
    })
    L.append(dist.to_markdown(index=False) + "\n")
    L.append("## 3. Transition matrix - baseline (rows) -> OD2 rejustified-k (cols)\n")
    ct = ct_rej.rename(index=SHORT, columns=SHORT)
    L.append(ct.to_markdown() + "\n")
    L.append("## 4. Transition matrix - baseline (rows) -> OD2 old-k (cols)\n")
    L.append(ct_oldk.rename(index=SHORT, columns=SHORT).to_markdown() + "\n")
    L.append("## Notes\n")
    L.append("- Candidate flags (fcc_no_or_low_change_candidate) and REVIEW/NORMAL gates are "
             "opportunity-INDEPENDENT, so the re-triage moves users only among FW/GAUGE/WATCH "
             "(and REVIEW where data-quality dominates).\n")
    L.append("- 'GAUGE = insufficient learning opportunity' now means no Type A AND no Type B "
             "(union empty). Type B's high frequency shrinks the no-opportunity pool.\n")
    (REPORTS / "fcc_relearn_od2_offline_report.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    print("[1/5] loading cohort + building OD2 feature table...", flush=True)
    df = load_cohort(args.limit)
    n_users = df["user_id"].nunique()
    feat = build_od2_cohort_features(df)
    print(f"      {len(feat)} user rows", flush=True)

    print("[2/5] active-reference quantiles + candidate flags...", flush=True)
    q = active_reference_quantiles(feat)
    feat = compute_candidate_flags(feat, q, pct="p05")
    print(f"      active reference n={q['n_active_reference']}, "
          f"candidates={int(feat['fcc_no_or_low_change_candidate'].sum())}", flush=True)

    print("[3/5] k re-justification @168h...", flush=True)
    kj = justify_k(feat)
    print("      " + str(kj), flush=True)

    # old-k (OD1 defaults 3/2/2) vs re-justified-k, both at 168h
    thr_oldk = FinalThresholds(response_window="168h")
    kB = kj.get("k_fa05_80_20_80", 3)
    kA = kj.get("k_fa05_90_10_90", 2)
    kB_med = kj.get("k_fa10_80_20_80", 2)
    thr_rej = replace(thr_oldk,
                      fw_hi_unresponded_8020_ge=int(kB),
                      fw_hi_unresponded_9010_ge=int(kA),
                      fw_med_unresponded_8020_ge=int(kB_med))

    print("[4/5] classifying (old-k and rejustified-k)...", flush=True)
    lab_oldk = classify_with(feat, thr_oldk)
    lab_rej = classify_with(feat, thr_rej)
    feat["final_label_od2_oldk"] = lab_oldk.to_numpy()
    feat["final_label_od2_rejk"] = lab_rej.to_numpy()

    print("[5/5] comparison vs baseline + write...", flush=True)
    baseline = load_baseline()
    base_counts = label_counts(baseline["final_label"].map(
        lambda x: x if x in LABEL_ORDER else x))
    oldk_counts = label_counts(lab_oldk)
    rej_counts = label_counts(lab_rej)
    ct_oldk, _ = transition_matrix(baseline, lab_oldk, feat)
    ct_rej, joined = transition_matrix(baseline, lab_rej, feat)

    feat.to_csv(OUT / "od2_final_action_labels.csv", index=False, encoding="utf-8")
    joined.to_csv(OUT / "od2_label_join_baseline.csv", index=False, encoding="utf-8")
    ct_rej.to_csv(OUT / "od2_transition_rejk.csv")
    ct_oldk.to_csv(OUT / "od2_transition_oldk.csv")
    pd.DataFrame([kj]).to_csv(OUT / "od2_k_justification.csv", index=False)

    print("\n=== LABEL DISTRIBUTIONS ===")
    print("baseline (OD1/72h):", _short_counts(base_counts))
    print("OD2 old-k (168h)  :", _short_counts(oldk_counts))
    print("OD2 rej-k (168h)  :", _short_counts(rej_counts))
    print("\n=== TRANSITION baseline(rows) -> OD2 rej-k(cols) ===")
    print(ct_rej.rename(index=SHORT, columns=SHORT).to_string())

    write_report(kj, base_counts, oldk_counts, rej_counts, thr_rej, ct_oldk, ct_rej, n_users)
    print(f"\nDONE. Report: {REPORTS / 'fcc_relearn_od2_offline_report.md'}")


if __name__ == "__main__":
    main()
