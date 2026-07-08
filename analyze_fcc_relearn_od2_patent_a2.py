#!/usr/bin/env python
"""OD2 Phase 4 (MVP) - A2 negative controls per mechanism (Type A / Type B / union).

The decisive falsification test of the corrected relearn definition. See
battery_usage/patent_negative_controls_od2.py. Reuses the v4 FCC-step cache and the
verbatim A2 control generators; only the driver (per-mechanism, 168h acceptance) is new.

Usage: python analyze_fcc_relearn_od2_patent_a2.py [--n-cheap 300] [--mechanisms A,B,union]
Outputs: data/processed/fcc_patent_evidence_od2/
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from battery_usage import patent_common_v4 as pc
from battery_usage.patent_negative_controls_od2 import (
    load_od2_episodes, run_a2_od2, CODE_VERSION,
)

OUT = pc.PROC / "fcc_patent_evidence_od2"
REPORTS = pc.REPORTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cheap", type=int, default=300)
    ap.add_argument("--mechanisms", type=str, default="A,B,union")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    mechs = tuple(m.strip() for m in args.mechanisms.split(","))

    print("[0] ensure shared FCC-step cache (v4)...", flush=True)
    steps, _design = pc.ensure_shared_inputs()
    print(f"    steps: {len(steps):,} rows ({int(steps['is_effective'].sum()):,} effective)", flush=True)

    print("[1] load OD2 opportunities...", flush=True)
    ep = load_od2_episodes()
    print(f"    {len(ep):,} episodes ({(ep['opportunity_type']=='A').sum():,} A / "
          f"{(ep['opportunity_type']=='B').sum():,} B / {ep['is_union_primary'].sum():,} union-primary)",
          flush=True)

    print(f"[2] A2 negative controls per mechanism {mechs}, n_cheap={args.n_cheap}...", flush=True)
    result = run_a2_od2(OUT, steps, ep, mechanisms=mechs, n_cheap=args.n_cheap, seed=args.seed)

    # concise report
    L = ["# OD2 Phase 4 (MVP) - A2 negative controls per mechanism\n",
         f"_Code {CODE_VERSION}. Primary window 168h. Acceptance: TRUE resp_prob_168h outside "
         f"the 95% null (greater) for >=2 of 4 cheap controls AND directionally supported "
         f"(user-bootstrap lower CI > control null mean) for >=2._\n",
         "> The decisive test: does each mechanism's true END-anchored effective-response "
         "probability beat its OWN mechanism-specific negative-control null? Type A is expected "
         "strong; Type B (charge-side) is the crux - its pooled 72h response sits near the OD1 null.\n",
         "## Acceptance by mechanism\n"]
    rows = []
    for m, r in result.items():
        rows.append({
            "mechanism": m, "n_anchors": r["n_anchors"], "n_users": r["n_users"],
            "true_resp_168h": r["true_resp_prob_168h"], "true_resp_72h": r["true_resp_prob_72h"],
            "boot_lo_168h": r["boot_lo_168h"],
            "null_mean_168h": f"{r['null_mean_168h_range'][0]}..{r['null_mean_168h_range'][1]}",
            "outside_null": f"{r['n_controls_outside_null']}/4",
            "directional": f"{r['n_controls_directionally_supported']}/4",
            "SUPPORTED": r["stimulus_response_supported"],
        })
    L.append(pd.DataFrame(rows).to_markdown(index=False) + "\n")
    L.append("## Interpretation\n")
    L.append("- **SUPPORTED** = the mechanism is a real learning stimulus (effect specific to the "
             "true opportunity END, not elapsed time / step density).\n")
    L.append("- If **Type B is NOT SUPPORTED**, the charge-side band traversal adds no stimulus and "
             "the invention reduces to Type A + full-charge END anchoring; the OD2 offline FW labels "
             "(which lean on Type B counts) would then need a Type-A-only variant.\n")
    L.append("- Full detail per control in `negative_control_summary_od2.csv`.\n")
    (REPORTS / "fcc_patent_evidence_od2_a2_report.md").write_text("\n".join(L), encoding="utf-8")

    print("\n=== A2-OD2 ACCEPTANCE ===")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nDONE. Report: {REPORTS / 'fcc_patent_evidence_od2_a2_report.md'}")


if __name__ == "__main__":
    main()
