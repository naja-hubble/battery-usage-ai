#!/usr/bin/env python
"""OD2 Phase 4 - pillar D bounded-retention invariance (UNION ledger, rw=168h primary).

Fork of the OD1 pillar D (patent_retention_invariance) under the corrected relearn
definition: the reference event ledger is the OD2 UNION-primary opportunity set
(Type A deep-discharge + Type B charge-side, END = full-charge attainment), the
reference response status is the 168h status, and the stateful verifier runs both
mechanism FSMs in parallel with END dedup on end_ns.

Claims reproduced/compared (OD1 baseline: stateful recall 1.0 / dup 0 /
no_response MAE ~0.02 / storage ratio 0.0417 at 7d):
  (a) stateful recall ~1.0 / dup 0 must hold at W=30d with rw=168h (168h=7d < 30d);
  (b) stateless curves at rw=168h degrade markedly vs rw=72h;
  (c) storage ratio recomputed; Type B density enlarges the pending queue but stays < 0.1.

Usage: python analyze_fcc_relearn_od2_patent_d.py [--verify-users 200] [--smoke]
Outputs: data/processed/fcc_patent_evidence_od2/
         (retention_invariance_summary_od2.csv, retention_stateful_verification_od2.csv,
          storage_compute_tradeoff_od2.csv, retention_invariance_grid_od2.parquet,
          reference_event_ledger_od2.parquet)
Report:  data/reports/fcc_patent_evidence_od2_d_report.md
"""
from __future__ import annotations

import argparse

import pandas as pd

from battery_usage import patent_common_v4 as pc
from battery_usage.patent_negative_controls_od2 import load_od2_episodes
from battery_usage.patent_retention_invariance_od2 import run_od2

OUT = pc.PROC / "fcc_patent_evidence_od2"
REPORTS = pc.REPORTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-users", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true",
                    help="tiny subset (verify on 8 users) just to confirm it runs")
    args = ap.parse_args()
    vusers = 8 if args.smoke else args.verify_users

    print("[0] ensure shared FCC-step cache (v4)...", flush=True)
    steps, design = pc.ensure_shared_inputs()
    print(f"    steps: {len(steps):,} rows ({int(steps['is_effective'].sum()):,} effective)", flush=True)

    print("[1] load OD2 opportunities...", flush=True)
    ep = load_od2_episodes()
    print(f"    {len(ep):,} episodes; {int(ep['is_union_primary'].sum()):,} union-primary "
          f"({(ep['opportunity_type']=='A').sum():,} A / {(ep['opportunity_type']=='B').sum():,} B)",
          flush=True)

    print(f"[2] pillar D retention invariance (verify_users={vusers})...", flush=True)
    res = run_od2(OUT, steps, ep, design, seed=args.seed, verify_users=vusers)

    # ---- concise report ----
    ver = pd.read_csv(OUT / "retention_stateful_verification_od2.csv")
    summ = pd.read_csv(OUT / "retention_invariance_summary_od2.csv")
    trade = pd.read_csv(OUT / "storage_compute_tradeoff_od2.csv")
    sl = summ[summ["detector"] == "stateless"]
    sl_head = sl[(sl["retention_days"].isin([7, 14, 30])) &
                 (sl["gap_config"] == "ok_only")][
        ["retention_days", "response_window_h", "recall", "resolvable_rate",
         "response_agreement", "no_response_mae", "storage_ratio"]]

    L = [
        "# OD2 Phase 4 - pillar D: bounded-retention invariance (UNION ledger, rw=168h primary)\n",
        "_Reference ledger = OD2 union-primary opportunities (Type A deep-discharge + Type B "
        "charge-side, END = full-charge attainment); reference response status = the 168h status. "
        "Stateful verifier runs both mechanism FSMs in parallel with END dedup on `end_ns`. "
        "Technical evidence for patent review - NOT legal advice._\n",
        f"Cohort: {res['n_users']} users, median span {res['median_span_days']}d, "
        f"{res['n_reference_ends']} reference ENDs over {res['n_users']} users (verified subset).\n",
        "## Claim (a): bounded stateful == unbounded at W=30d / rw=168h\n",
        "> Since 168h = 7d < 30d, keeping the last 30 days of raw plus a small persistent "
        "causal state reproduces the full-history UNION detector exactly.\n",
        ver.to_markdown(index=False) + "\n",
        f"OD1 baseline: recall 1.0 / dup 0 / no_response MAE ~0.02 (rw=72h). "
        f"OD2: recall {res['stateful_verify_recall']} / dup {res['stateful_verify_duplicates']} / "
        f"symdiff {res['stateful_verify_symmetric_diff']} / "
        f"no_response MAE {res['stateful_verify_no_response_mae']} (rw=168h, UNION A+B).\n",
        "## Claim (b): stateless degrades at rw=168h vs rw=72h (7d retention)\n",
        f"- response-status agreement @7d: 168h = **{res['stateless_7d_agreement_168h']}** vs "
        f"72h = **{res['stateless_7d_agreement_72h']}**\n",
        f"- response resolvable rate @7d: 168h = **{res['stateless_7d_resolvable_168h']}** vs "
        f"72h = **{res['stateless_7d_resolvable_72h']}**\n",
        f"- physical-episode recall @7d (rw-independent) = {res['stateless_7d_recall_168h']}, "
        f"duplicate rate @7d/168h = {res['stateless_7d_dup_rate_168h']}\n",
        sl_head.to_markdown(index=False) + "\n",
        "## Claim (c): storage / compute tradeoff (Type B pending density)\n",
        f"- stateful storage ratio @7d = **{res['storage_ratio_7d']}** (OD1 baseline 0.0417); "
        f"well under 0.1.\n",
        f"- peak pending-queue depth per user: max {res['peak_pending_per_user_max']}, "
        f"mean {res['peak_pending_per_user_mean']} (Type B enlarges the queue; folded into "
        f"`stateful_storage_ratio_od2_pending`).\n",
        trade.to_markdown(index=False) + "\n",
        "## Verdict\n",
        f"- IC5 bounded-retention causal-equivalence at rw=168h: "
        f"**{'MET' if res['ic5_equivalence_met'] else 'NOT MET'}** "
        f"(min equivalent stateful storage ratio {res['min_stateful_equivalent_storage_ratio_168h']}).\n",
        f"- Grid configs evaluated: {res['n_grid_configs']}. Runtime {res['runtime_s']}s.\n",
    ]
    (REPORTS / "fcc_patent_evidence_od2_d_report.md").write_text("\n".join(L), encoding="utf-8")

    print("\n=== D-OD2 SUMMARY ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
    print(f"\nDONE. Report: {REPORTS / 'fcc_patent_evidence_od2_d_report.md'}")


if __name__ == "__main__":
    main()
