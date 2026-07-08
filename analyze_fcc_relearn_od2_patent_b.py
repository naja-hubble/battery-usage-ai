#!/usr/bin/env python
"""OD2 Phase 4 - B response hazard per mechanism (time-resolved corroboration of A2).

Usage: python analyze_fcc_relearn_od2_patent_b.py [--boot 300]
Outputs: data/processed/fcc_patent_evidence_od2/response_hazard_{summary,curves}_od2.*
"""
from __future__ import annotations

import argparse

import pandas as pd

from battery_usage import patent_common_v4 as pc
from battery_usage.patent_negative_controls_od2 import load_od2_episodes
from battery_usage.patent_response_hazard_od2 import run_hazard_od2

OUT = pc.PROC / "fcc_patent_evidence_od2"
REPORTS = pc.REPORTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--mechanisms", type=str, default="A,B,union")
    args = ap.parse_args()
    mechs = tuple(m.strip() for m in args.mechanisms.split(","))

    steps, _ = pc.ensure_shared_inputs()
    ep = load_od2_episodes()
    res = run_hazard_od2(OUT, steps, ep, mechanisms=mechs, boot=args.boot)

    rows = [{"mechanism": m, "n_true": r["n_true"],
             "median_resp_h": r["median_response_h"],
             "true_CIF_72h": r["true_cif_72h"], "pseudo_CIF_72h": r["pseudo_cif_72h"],
             "sep_72h": r["sep_72h"],
             "true_CIF_168h": r["true_cif_168h"], "pseudo_CIF_168h": r["pseudo_cif_168h"],
             "sep_168h": r["sep_168h"]} for m, r in res.items()]
    L = ["# OD2 Phase 4 - B response hazard (CIF) per mechanism\n",
         "_Event = first >=50 mWh FCC step after opportunity END; matched-pseudo excludes "
         "+/-7d of any true union END; user-clustered bootstrap CI._\n",
         "> Reading: `sep_168h` >> `sep_72h` for Type B would confirm the charge-side response "
         "emerges specifically after 72h, justifying the 168h primary window.\n",
         pd.DataFrame(rows).to_markdown(index=False) + "\n"]
    (REPORTS / "fcc_patent_evidence_od2_b_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n=== B-OD2 CIF true vs pseudo ===")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
