#!/usr/bin/env python
"""OD2 Phase 4 - pillar E: missingness / sleep-gap / censor stress, per mechanism.

Starting from dense-telemetry users, inject missingness regimes (MCAR fractions,
contiguous gaps, sleep-gaps, end-of-record truncation extended to 168h/336h for the
168h primary window) and measure how four detectors (naive / binary_gap_gate / graded /
proposed) behave vs the uninjected clean reference. Truth no-response = the proposed
detector on clean OD2 relearn ENDs at the 168h window. Run per mechanism (A / B / union).

Usage:  python analyze_fcc_relearn_od2_patent_e.py [--n-users 25] [--replicates 40]
                                                    [--mechanisms A,B,union] [--smoke]
Outputs: data/processed/fcc_patent_evidence_od2/missingness_stress_summary_od2.csv
         data/reports/fcc_patent_evidence_od2_e_report.md
"""
from __future__ import annotations

import argparse

import pandas as pd

from battery_usage import patent_common_v4 as pc
from battery_usage.patent_negative_controls_od2 import load_od2_episodes
from battery_usage.patent_missingness_stress_od2 import run_od2

OUT = pc.PROC / "fcc_patent_evidence_od2"
REPORTS = pc.REPORTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-users", type=int, default=25)
    ap.add_argument("--replicates", type=int, default=40)
    ap.add_argument("--mechanisms", type=str, default="A,B,union")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true",
                    help="tiny run (4 users x 3 replicates) to confirm it executes")
    args = ap.parse_args()
    n_users = 4 if args.smoke else args.n_users
    replicates = 3 if args.smoke else args.replicates
    mechs = tuple(m.strip() for m in args.mechanisms.split(","))

    steps, design = pc.ensure_shared_inputs()
    ep = load_od2_episodes()
    res = run_od2(OUT, steps, ep, design, seed=args.seed, n_users=n_users,
                  replicates=replicates, mechanisms=mechs)

    by_mech = res["by_mechanism"]
    rows = [{"mechanism": m, "n_clean_ends": r["n_clean_ends"],
             "naive_false_no_response": r["naive_mean_false_no_response"],
             "proposed_false_no_response": r["proposed_mean_false_no_response"],
             "reduction": r["false_no_response_reduction"],
             "proposed_recovery": r["proposed_episode_recovery"],
             "IC6_supported": r["ic6_benefit_supported"]}
            for m, r in by_mech.items()]
    df = pd.DataFrame(rows)

    if not args.smoke:
        L = ["# OD2 Phase 4 - E missingness / censor stress (per mechanism)\n",
             "_Dense users; inject MCAR / contiguous-gap / sleep-gap / truncation regimes; "
             "compare four detectors' FALSE confirmed no-response vs the clean reference. "
             "Truth = `proposed` on clean OD2 relearn ENDs at the **168h** primary window; "
             "truncation extended to (168h, 336h). Censored/unknown are NEVER no-response._\n",
             "> IC6: the `proposed` detector should emit far fewer FALSE confirmed "
             "no-response episodes than `naive` under injection, while keeping recovery. "
             "`union` is the headline (OD1 baseline: naive ~643 -> proposed ~4.1).\n",
             "## Headline per mechanism (mean false no-response across regimes)\n",
             df.to_markdown(index=False) + "\n",
             "\n## Per-detector per-regime (union)\n",
             _detector_table("union") + "\n"]
        (REPORTS / "fcc_patent_evidence_od2_e_report.md").write_text("\n".join(L), encoding="utf-8")

    print("\n=== E-OD2 headline (mean false confirmed no-response across regimes) ===")
    print(df.to_string(index=False))


def _detector_table(mech: str) -> str:
    s = pd.read_csv(OUT / "missingness_stress_summary_od2.csv")
    s = s[s["mechanism"] == mech]
    piv = s.pivot_table(index="regime", columns="detector",
                        values="mean_false_no_response", aggfunc="first")
    order = [d for d in ("naive", "binary_gap_gate", "graded", "proposed") if d in piv.columns]
    return piv[order].round(2).to_markdown()


if __name__ == "__main__":
    main()
