#!/usr/bin/env python
"""OD2 Phase 4 - A3 response-anchor contamination per mechanism (Type A / Type B / union).

Forks the OD1 A3 (patent_anchor_analysis) causal-leakage quantity to the corrected
two-mechanism relearn definition. For each mechanism and each response window (24/72/168h)
it counts effective (>=50 mWh) FCC steps in [anchor, anchor+W] and reports the fraction that
fall BEFORE the physical recharge completion (episode END) -- causal contamination -- plus the
END-anchor duplicate-attribution rate. Anchors: Type A = start/low/end; Type B = arm/end;
union = end. Reuses the v4 FCC-step cache + pc.steps_in_window verbatim.

Usage: python analyze_fcc_relearn_od2_patent_a3.py [--boot 1000] [--mechanisms A,B,union]
Outputs: data/processed/fcc_patent_evidence_od2/response_anchor_*_od2.csv
Report:  data/reports/fcc_patent_evidence_od2_a3_report.md
"""
from __future__ import annotations

import argparse

import pandas as pd

from battery_usage import patent_common_v4 as pc
from battery_usage.patent_negative_controls_od2 import load_od2_episodes
from battery_usage.patent_anchor_analysis_od2 import (
    run_a3_od2, OD1_BASELINE_72H, PRIMARY_W, OD1_COMPARE_W, CODE_VERSION,
)

OUT = pc.PROC / "fcc_patent_evidence_od2"
REPORTS = pc.REPORTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--mechanisms", type=str, default="A,B,union")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-users", type=int, default=0,
                    help="if >0, smoke-test on this many users only")
    args = ap.parse_args()
    mechs = tuple(m.strip() for m in args.mechanisms.split(","))

    print("[0] ensure shared FCC-step cache (v4)...", flush=True)
    steps, _design = pc.ensure_shared_inputs()
    print(f"    steps: {len(steps):,} rows ({int(steps['is_effective'].sum()):,} effective)", flush=True)

    print("[1] load OD2 opportunities...", flush=True)
    ep = load_od2_episodes()
    if args.sample_users > 0:
        keep = ep["user_id"].drop_duplicates().head(args.sample_users)
        ep = ep[ep["user_id"].isin(keep)].copy()
        print(f"    SMOKE subset: {ep['user_id'].nunique()} users, {len(ep):,} episodes", flush=True)
    print(f"    {len(ep):,} episodes ({(ep['opportunity_type']=='A').sum():,} A / "
          f"{(ep['opportunity_type']=='B').sum():,} B / {ep['is_union_primary'].sum():,} union-primary)",
          flush=True)

    print(f"[2] A3 anchor contamination per mechanism {mechs}, boot={args.boot}...", flush=True)
    res = run_a3_od2(OUT, steps, ep, mechanisms=mechs, boot=args.boot, seed=args.seed)

    # ---- concise report ----
    by = res["by_mechanism"]
    mech_rows = []
    for m in mechs:
        r = by[m]
        mech_rows.append({
            "mechanism": m, "n_ok_episodes": r["n_episodes"],
            "non_end_anchor(s)": r["non_end_anchors"] or "-",
            "worst_non_end_contam_168h": r["worst_non_end_contamination_168h"],
            "END_contam_168h": r["end_contamination_168h"],
            "END_contam_72h": r["end_contamination_72h"],
            "END_dup_rate_168h": r["end_duplicate_rate_168h"],
        })

    comp = pd.read_csv(OUT / "response_anchor_comparison_od2.csv")
    dup = pd.read_csv(OUT / "response_anchor_duplicate_od2.csv")

    L = ["# OD2 Phase 4 - A3 response-anchor contamination per mechanism\n",
         f"_Code {CODE_VERSION}. Contamination = fraction of counted effective (>=50 mWh) FCC "
         f"response steps in [anchor, anchor+W] whose timestamp is STRICTLY BEFORE the episode END "
         f"(recharge completion) -- a step during the charge/discharge that produced the opportunity, "
         f"not a response to it. OD2 primary window = {PRIMARY_W}h; {OD1_COMPARE_W}h shown for direct "
         f"OD1 A3 comparison._\n",
         "> Anchors per mechanism: **Type A** = start (opening full) / low (deep sample) / end "
         "(full re-attainment); **Type B** = arm (= start = low, band entry while charging) / end; "
         "**union** = end (dedup on coincident ENDs).\n",
         "## Headline: END anchoring removes contamination for both mechanisms\n",
         pd.DataFrame(mech_rows).to_markdown(index=False) + "\n",
         f"OD1 A3 baseline (72h): END={OD1_BASELINE_72H['end']:.3f}, START={OD1_BASELINE_72H['start']:.3f}, "
         f"LOW={OD1_BASELINE_72H['low']:.3f}. In OD2, END contamination is structurally ~0 for both "
         "mechanisms (an END-anchored window starts AT completion, so no counted step can precede it); "
         "the non-END anchors (Type A start/low, Type B arm) recover the same mid-cycle contamination "
         "seen in OD1.\n",
         "## END-anchor duplicate attribution: union dedup vs pooled A+B\n",
         "_One effective FCC step attributed to >= 2 episodes because their END windows overlap. Union "
         "dedup on coincident ENDs removes the cross-mechanism double counting (an A and a B episode "
         "closing on the same full-charge END)._\n",
         dup.to_markdown(index=False) + "\n",
         "## Full anchor x window grid\n",
         comp.to_markdown(index=False) + "\n",
         "## Notes\n",
         "- Charge-termination anchor is **NOT AVAILABLE** (no per-sample charge-current / voltage-taper "
         "telemetry); END is its operational proxy. Reported, not fabricated.\n",
         "- Type B arm-anchor contamination quantifies the leakage that a band-entry-anchored response "
         "audit would suffer: charge-side steps between band entry and full charge would be miscounted "
         "as responses. END anchoring is required for Type B specifically.\n",
         "- CSVs: `response_anchor_comparison_od2.csv`, `response_anchor_contamination_bootstrap_od2.csv`, "
         "`response_anchor_duplicate_od2.csv`, `response_anchor_charge_termination_status_od2.csv`.\n"]
    (REPORTS / "fcc_patent_evidence_od2_a3_report.md").write_text("\n".join(L), encoding="utf-8")

    print("\n=== A3-OD2 CONTAMINATION (primary 168h) ===")
    print(pd.DataFrame(mech_rows).to_string(index=False))
    print("\n=== END-anchor duplicate attribution (union vs pooled A+B) ===")
    print(dup.to_string(index=False))
    print(f"\nDONE. Report: {REPORTS / 'fcc_patent_evidence_od2_a3_report.md'}")


if __name__ == "__main__":
    main()
