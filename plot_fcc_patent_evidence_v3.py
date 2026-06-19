#!/usr/bin/env python
"""Patent evidence v3 figures (dpi=300, anonymized aggregates only).

Each figure caption records invention_family / technical_problem /
technical_effect. No user ids, serials or device names appear in any figure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent
EVID = REPO / "data" / "processed" / "fcc_patent_evidence_v3"
FIG = REPO / "data" / "reports" / "figures" / "fcc_patent_evidence_v3"
DPI = 300


def _save(fig, name, caption):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.text(0.5, 0.005, caption, ha="center", va="bottom", fontsize=6, wrap=True, color="#444")
    fig.savefig(FIG / name, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print("[fig]", name)


def fig_ablation():
    d = pd.read_csv(EVID / "patent_ablation_comparison.csv")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    x = np.arange(len(d))
    ax1.bar(x, d["n_flagged"], color="#4C78A8")
    ax1.set_xticks(x); ax1.set_xticklabels(d["variant"])
    ax1.set_ylabel("n flagged actionable"); ax1.set_title("Flagged count by ablation variant")
    for i, v in enumerate(d["n_flagged"]):
        ax1.text(i, v + 0.5, str(int(v)), ha="center", fontsize=8)
    p = d["proxy_precision"].fillna(0)
    ax2.plot(x, p, "o-", color="#B01F1F", label="proxy precision")
    ax2.plot(x, d["proxy_recall"].fillna(0), "s--", color="#1F77B4", label="proxy recall")
    ax2.set_xticks(x); ax2.set_xticklabels(d["variant"]); ax2.set_ylim(0, 1.05)
    ax2.set_title("Proxy precision/recall vs production"); ax2.legend(fontsize=8); ax2.grid(alpha=.3)
    fig.suptitle("Analysis A — opportunity/response comparator ablation (A0→A6)", fontsize=12)
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    _save(fig, "ablation_technical_effect.png",
          "invention_family: IC1(opportunity-conditioned no-response)+IC6(gap tier)+IC2(dual-track)+branch | "
          "technical_problem: static FCC-stale flags non-actionable & cannot bifurcate | "
          "technical_effect: gap-quality tier raises proxy precision 0.33(A0)->0.89(A5); bifurcation+dual-track (A6) "
          "recovers full FW(14)+Gauge(18) recall. A6 == production reference (precision/recall 1.0 tautological).")


def fig_dual_track():
    s = pd.read_csv(EVID / "_dual_track_abs_steps_sample.csv")["abs_step"].to_numpy()
    summ = pd.read_csv(EVID / "dual_track_step_magnitude_summary.csv").iloc[0]
    thr = pd.read_csv(EVID / "dual_track_threshold_analysis.csv")
    thr_mwh = thr[thr["threshold_kind"] == "fixed_mwh"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    bins = np.logspace(0, np.log10(max(s.max(), 100)), 60)
    ax1.hist(s, bins=bins, color="#4C78A8", alpha=.85)
    ax1.set_xscale("log"); ax1.axvline(50, color="#B01F1F", ls="--", lw=2, label="50 mWh (effective)")
    ax1.axvline(summ["quantization_unit_mwh"], color="#2CA02C", ls=":", lw=2,
                label=f"quantization {summ['quantization_unit_mwh']:.0f} mWh")
    ax1.set_xlabel("|FCC step| (mWh, log)"); ax1.set_ylabel("count")
    ax1.set_title(f"FCC step magnitudes (micro<50mWh: {summ['frac_micro_lt_50mwh']*100:.1f}%)")
    ax1.legend(fontsize=8)
    ax2.plot(thr_mwh["threshold"], thr_mwh["users_all_steps_below_thr_frac"], "o-", color="#B01F1F")
    ax2.axvline(50, color="#888", ls="--")
    ax2.set_xlabel("effective-step threshold (mWh)")
    ax2.set_ylabel("frac users with ALL steps below thr (would be 'frozen')")
    ax2.set_title("Threshold sweep (elbow near 50 mWh)"); ax2.grid(alpha=.3)
    fig.suptitle("Analysis C — any/effective dual-track step-magnitude evidence", fontsize=12)
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    _save(fig, "dual_track_threshold_evidence.png",
          "invention_family: IC2(any/effective dual-track + asymmetric reset) | "
          "technical_problem: integer gauge emits micro-wobble (quantization 10 mWh) indistinguishable from re-learning | "
          f"technical_effect: 58.1% of steps are micro(<50mWh); 'frozen-user' fraction plateaus beyond ~50 mWh "
          "(0.20@50->0.22@100), supporting 50 mWh effective-step definition; smaller thr over-counts noise.")


def fig_technical_effects():
    d = pd.read_csv(EVID / "patent_technical_effects.csv")
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(d)); w = 0.38
    ax.bar(x - w/2, d["n_flagged_actionable"], w, label="flagged actionable", color="#4C78A8")
    ax.bar(x + w/2, d["production_normal_falsely_flagged"], w, label="production-NORMAL falsely flagged", color="#B01F1F")
    ax.set_xticks(x); ax.set_xticklabels(d["detector"], rotation=20, ha="right", fontsize=8)
    for i, v in enumerate(d["n_flagged_actionable"]):
        ax.text(i - w/2, v + 0.3, str(int(v)), ha="center", fontsize=8)
    ax.set_ylabel("device count"); ax.legend(fontsize=8)
    ax.set_title("Analysis H — technical effect: actionable flags & false NORMAL flags by detector")
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    _save(fig, "technical_effect_detectors.png",
          "invention_family: IC1+IC6+IC2+branch vs static baseline | "
          "technical_problem: avoid wrong battery maintenance actions & protect responders | "
          "technical_effect: static FCC-stale flags 55 (cannot bifurcate); full-history proposed flags 32 with 0 "
          "production-NORMAL; rolling stateful-v2 core flags 9 with 0 NORMAL vs stateless 15 with 3 NORMAL.")


def main():
    fig_ablation()
    fig_dual_track()
    fig_technical_effects()
    print("[done] figures ->", FIG)


if __name__ == "__main__":
    main()
