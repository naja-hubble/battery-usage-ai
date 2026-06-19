#!/usr/bin/env python
"""FCC learning-response -- patent-evidence v4 completion driver (ADDITIVE).

Completes the v3 PENDING raw-trace analyses and adds the dual-track reset
ablation and data-driven effective threshold:

  A2  negative controls / temporal falsification   (patent_negative_controls)
  A3  response-anchor comparison (start/low/end)    (patent_anchor_analysis)
  B   response hazard / cumulative incidence        (patent_response_hazard)
  C2  dual-track asymmetric-reset ablation          (patent_dual_track_ablation)
  C3  data-driven effective threshold               (patent_effective_threshold)
  D   bounded-retention invariance + minimal state  (patent_retention_invariance,
                                                      patent_state_minimality)
  E   missingness / sleep-gap / censor stress       (patent_missingness_stress)

Then aggregates evidence (baseline gate, technical effects, evidence strength,
claim-support / prior-art / scope matrices, manifest) and writes the v4 reports +
dpi=300 anonymous figures. NOTHING is fabricated; intervention/version data stay
NOT AVAILABLE unless real columns are found.

Technical evidence for patent review -- NOT a legal opinion.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:  # robust UTF-8 stdout on CP932 consoles
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from battery_usage import patent_common_v4 as pc
from battery_usage import patent_negative_controls as nc
from battery_usage import patent_anchor_analysis as aa
from battery_usage import patent_response_hazard as rh
from battery_usage import patent_dual_track_ablation as dta
from battery_usage import patent_effective_threshold as et
from battery_usage import patent_retention_invariance as ri
from battery_usage import patent_state_minimality as sm
from battery_usage import patent_missingness_stress as ms
from battery_usage import patent_evidence_v4 as ev
from battery_usage import patent_reporting_v4 as rep
from battery_usage import patent_plotting_v4 as plot


def build_manifest(out_dir: Path) -> None:
    import pyarrow.parquet as pq
    inputs = [pc.TIMESERIES, pc.FULL_EPISODES, pc.ACTION_LABELS, pc.ONLINE_SNAPSHOT,
              pc.ONLINE_STATEFUL]
    rows = []
    for p in inputs:
        if not p.exists():
            rows.append({"path": str(p.relative_to(pc.REPO)), "exists": False}); continue
        try:
            if p.suffix == ".parquet":
                cols = [f.name for f in pq.read_schema(p)]
                n = pq.read_metadata(p).num_rows
            else:
                d = pd.read_csv(p, nrows=5); cols = d.columns.tolist()
                n = sum(1 for _ in open(p, encoding="utf-8")) - 1
            rows.append({"path": str(p.relative_to(pc.REPO)), "exists": True,
                         "sha256": pc.sha256(p), "bytes": p.stat().st_size,
                         "n_rows": int(n), "n_cols": len(cols)})
        except Exception as e:
            rows.append({"path": str(p.relative_to(pc.REPO)), "exists": True,
                         "error": f"{type(e).__name__}"})
    pd.DataFrame(rows).to_csv(out_dir / "input_manifest_patent_v4.csv", index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FCC patent evidence v4 (additive)")
    ap.add_argument("--timeseries", default=str(pc.TIMESERIES))
    ap.add_argument("--full-history-dir", default=str(pc.PROC))
    ap.add_argument("--online-v2-dir", default=str(pc.PROC / "fcc_online_v2"))
    ap.add_argument("--v3-dir", default=str(pc.V3_DIR))
    ap.add_argument("--out-dir", default=str(pc.V4_DIR))
    ap.add_argument("--fig-dir", default=str(pc.FIG_DIR))
    ap.add_argument("--report", default=str(pc.REPORTS / "fcc_patent_evidence_v4_report.md"))
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--random-seed", type=int, default=42)
    ap.add_argument("--quick", action="store_true",
                    help="reduced replicate/user counts for a fast smoke run")
    ap.add_argument("--skip", default="", help="comma-separated analyses to skip (A2,A3,B,C2,C3,D,E)")
    ap.add_argument("--no-figures", action="store_true")
    args = ap.parse_args(argv)

    np.random.seed(args.random_seed)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = Path(args.fig_dir); fig_dir.mkdir(parents=True, exist_ok=True)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    Q = args.quick
    t0 = time.time()

    print("=" * 74)
    print("FCC PATENT EVIDENCE v4 -- technical evidence for patent review (NOT legal advice)")
    print("=" * 74)

    pc.ensure_dirs()
    print("[setup] building/loading shared inputs (FCC step events, design capacity)...")
    steps, design = pc.ensure_shared_inputs()
    episodes = pc.load_full_episodes()
    build_manifest(out_dir)

    gate, status = ev.baseline_gate(out_dir)
    print(f"[gate] baseline reproduction = {status} ({int(gate['match'].sum())}/{len(gate)} match)")
    avail = ev.availability_probe(out_dir)
    print(f"[probe] intervention/BIOS/EC/FW-version data = {avail['intervention_version_data']}")
    if status != "PASS":
        print("\n[STOP] BASELINE_MISMATCH -- no patent-evidence conclusions emitted. "
              "See patent_baseline_gate_v4.csv.")
        return 1

    results: dict = {}
    seed = args.random_seed

    if "A2" not in skip:
        results["A2"] = nc.run(out_dir, steps, episodes, design, seed=seed,
                               n_cheap=200 if Q else 1000, n_raw=50 if Q else 200,
                               rsoc_user_cap=150 if Q else None)
    if "A3" not in skip:
        results["A3"] = aa.run(out_dir, steps, episodes, design, seed=seed,
                               boot=300 if Q else 1000)
    if "B" not in skip:
        results["B"] = rh.run(out_dir, steps, episodes, design, seed=seed,
                              boot=200 if Q else 500)
    if "C2" not in skip:
        results["C2"] = dta.run(out_dir, steps, episodes, design, seed=seed)
    if "C3" not in skip:
        results["C3"] = et.run(out_dir, steps, episodes, design, seed=seed,
                               boot=80 if Q else 300)
    if "D" not in skip:
        results["D"] = ri.run(out_dir, steps, episodes, design, seed=seed,
                              verify_users=80 if Q else 200)
        results["Dmin"] = sm.run(out_dir, steps, episodes, design, seed=seed,
                                 n_users=100 if Q else 200)
    if "E" not in skip:
        results["E"] = ms.run(out_dir, steps, episodes, design, seed=seed,
                              n_users=20 if Q else 35, replicates=15 if Q else 60)

    # aggregation + reports + figures
    ev.build_all(results, out_dir, status, avail["intervention_version_data"])
    rep.build_all(results, status, avail["intervention_version_data"])
    if not args.no_figures:
        plot.build_all(out_dir, fig_dir)
    ev.results_manifest(out_dir)

    (out_dir / "_v4_results_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    _console_summary(results, status, avail["intervention_version_data"], time.time() - t0)
    return 0


def _console_summary(results, status, availability, runtime):
    a2, a3, b = results.get("A2", {}), results.get("A3", {}), results.get("B", {})
    c2, c3, d = results.get("C2", {}), results.get("C3", {}), results.get("D", {})
    dmin, e = results.get("Dmin", {}), results.get("E", {})
    es = pd.read_csv(pc.V4_DIR / "patent_evidence_strength_v4.csv")
    strength = {r["family"]: r["evidence_strength_v4"] for _, r in es.iterrows()}
    print("\n" + "=" * 74)
    print("FCC PATENT EVIDENCE v4 -- FINAL SUMMARY")
    print("=" * 74)
    print(f"baseline gate: {status} | intervention/version: {availability} | runtime {runtime/60:.1f} min")
    print("\nTop independently-supported technical effects:")
    print(f"  1. END-anchored stimulus-response specificity (A2): resp72={a2.get('true_resp_prob_72h')}, "
          f"{a2.get('n_controls_outside_null')}/{a2.get('n_controls_total')} controls outside null "
          f"-> {'SUPPORTED' if a2.get('stimulus_response_supported') else 'NOT'}")
    print(f"  2. bounded-retention causal equivalence (D, IC5): stateful recall="
          f"{d.get('stateful_verify_recall')}, dup={d.get('stateful_verify_duplicates')} at storage ratio "
          f"{d.get('min_stateful_equivalent_storage_ratio')}")
    print(f"  3. censor/gap false-escalation robustness (E, IC6): false no-response naive="
          f"{e.get('naive_mean_false_no_response')} -> proposed={e.get('proposed_mean_false_no_response')}")
    print(f"\nnegative controls: 5 controls, {a2.get('n_controls_directionally_supported')} directionally "
          f"supported under user-bootstrap")
    print(f"anchor: END contamination 72h={a3.get('end_contamination_frac_72h')} vs worst non-END="
          f"{a3.get('worst_non_end_contamination_72h')} (advantage={a3.get('end_anchor_measurable_advantage')})")
    print(f"retention equivalence: IC5 met={d.get('ic5_equivalence_met')}; minimal state="
          f"{dmin.get('necessary_components')}")
    print(f"missingness stress: IC6 supported={e.get('ic6_benefit_supported')}, "
          f"recovery={e.get('proposed_episode_recovery')}")
    print(f"dual-track asymmetric reset: supported={c2.get('asymmetric_reset_supported')}, "
          f"evidence preserved +{c2.get('evidence_preserved_vs_symmetric')}, hard prompts reduced "
          f"{c2.get('hard_prompts_reduced_by_d4')}")
    print(f"adaptive threshold: quantization={c3.get('quantization_unit_mwh')}mWh, GMM valley="
          f"{c3.get('gmm_valley_mwh')}mWh; recommend narrow=50mWh / medium=>quant+noise / broad=adaptive")
    print("\nevidence strength v4:")
    for fam in ("IC1", "IC2", "IC5", "IC6", "IC7", "IC8"):
        print(f"  {fam}: {strength.get(fam, 'n/a')}")
    print("\nremaining limitations: proxy labels not ground truth; intervention/version NOT AVAILABLE; "
          "matched-pseudo/RSOC controls conservative; MCAR-50% recovery degrades; prior-art UNVERIFIED.")
    print("\nrerun: python analyze_fcc_patent_evidence_v4.py --out-dir data/processed/fcc_patent_evidence_v4 \\")
    print("       --fig-dir data/reports/figures/fcc_patent_evidence_v4 --dpi 300 --random-seed 42")
    print("       (add --quick for a fast smoke run; --skip A2,E to skip stages)")
    print("NOTE: technical evidence supports/does not support; NO legal novelty/inventive-step/"
          "infringement/grant claim is made.")


if __name__ == "__main__":
    raise SystemExit(main())
