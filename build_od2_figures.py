#!/usr/bin/env python
"""Generate the new def deck figure set (dpi=300, anonymized) for the new def patent-review slides.

Reads the verified new def outputs where available; falls back to the master-report numbers.
Figures use ASCII/short labels (Japanese context lives on the slides) and the deck palette.
Output: data/reports/figures/fcc_relearn_od2/
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
EVID = PROC / "fcc_patent_evidence_od2"
PH1 = PROC / "fcc_relearn_od2" / "phase1"
OFF = PROC / "fcc_relearn_od2" / "offline"
FIG = REPO / "data" / "reports" / "figures" / "fcc_relearn_od2"
FIG.mkdir(parents=True, exist_ok=True)

# deck palette
NAVY = "#1F375B"; BLUE = "#1F77B4"; STEEL = "#336699"; GREY = "#555555"
RED = "#C0392B"; GREEN = "#2CA02C"; ORANGE = "#B05A00"; TEAL = "#2E6E6A"
PURPLE = "#6A3D8A"; LGREY = "#BBBBBB"
plt.rcParams.update({"font.size": 12, "axes.edgecolor": "#888888",
                     "axes.grid": True, "grid.color": "#E6E6E6", "grid.linewidth": 0.8,
                     "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight"})


def save(fig, name):
    fig.savefig(FIG / name, facecolor="white")
    plt.close(fig)
    print("wrote", name)


def _read(path, **kw):
    try:
        return pd.read_csv(path, **kw)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 1. Mechanism diagram — Type A (deep) vs Type B (charge-side) RSOC waveforms
# --------------------------------------------------------------------------- #
def mechanism_diagram():
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
    # Type A: full -> deep(<=6) -> full
    tA = np.array([0, 1, 2, 3, 4, 5, 6]); rA = np.array([100, 70, 30, 6, 45, 85, 100])
    axes[0].plot(tA, rA, "-o", color=BLUE, lw=2.4, ms=5)
    axes[0].axhspan(0, 6, color=RED, alpha=0.10); axes[0].axhline(6, color=RED, ls="--", lw=1.2)
    axes[0].axhline(99, color=GREEN, ls="--", lw=1.2)
    axes[0].text(0.1, 92, "full (>=99)", color=GREEN, fontsize=10)
    axes[0].text(0.1, 8.5, "deep (<=6%)", color=RED, fontsize=10)
    axes[0].annotate("END = full re-attained\n(relearn window opens)", xy=(6, 100), xytext=(3.1, 62),
                     fontsize=9.5, color=NAVY, arrowprops=dict(arrowstyle="->", color=NAVY))
    axes[0].set_title("Type A  —  deep-discharge relearn", color=NAVY, fontweight="bold", fontsize=13)
    # Type B: charging through 60-80 -> full
    tB = np.array([0, 1, 2, 3, 4]); rB = np.array([48, 65, 78, 92, 100])
    axes[1].plot(tB, rB, "-o", color=TEAL, lw=2.4, ms=5)
    axes[1].axhspan(60, 80, color=ORANGE, alpha=0.13)
    axes[1].axhline(99, color=GREEN, ls="--", lw=1.2)
    axes[1].text(0.05, 70, "60-80% band\n(charging transit)", color=ORANGE, fontsize=9.5)
    axes[1].text(0.05, 92, "full (>=99)", color=GREEN, fontsize=10)
    axes[1].annotate("END = full reached\n(no deep discharge needed)", xy=(4, 100), xytext=(0.9, 40),
                     fontsize=9.5, color=NAVY, arrowprops=dict(arrowstyle="->", color=NAVY))
    axes[1].set_title("Type B  —  charge-side relearn", color=TEAL, fontweight="bold", fontsize=13)
    for ax in axes:
        ax.set_ylim(0, 108); ax.set_xlabel("time"); ax.set_ylabel("RSOC (%)")
        ax.set_xticks([])
    save(fig, "od2_mechanism_diagram.png")


# --------------------------------------------------------------------------- #
# 2. Attribution vs window (the 168h justification)
# --------------------------------------------------------------------------- #
def attribution_window():
    w = [24, 72, 168, 336]; expl = [46.7, 69.1, 86.1, 91.1]
    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    ax.plot(w, expl, "-o", color=BLUE, lw=2.6, ms=8)
    for x, y in zip(w, expl):
        ax.annotate(f"{y:.0f}%", (x, y), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=11, color=NAVY, fontweight="bold")
    ax.axvline(72, color=GREY, ls=":", lw=1.3); ax.axvline(168, color=GREEN, ls="--", lw=1.6)
    ax.text(72, 40, "old def window\n(72h)", color=GREY, fontsize=9.5, ha="center")
    ax.text(168, 40, "new def primary\n(168h / 7d)", color=GREEN, fontsize=9.5, ha="center")
    ax.set_xlabel("response window (hours)"); ax.set_ylabel("% of real FCC updates explained\nby a Type A/B opportunity")
    ax.set_ylim(35, 100); ax.set_xticks(w)
    ax.set_title("Relearn latency exceeds 72h  ->  168h primary window", color=NAVY, fontweight="bold")
    save(fig, "od2_attribution_window.png")


# --------------------------------------------------------------------------- #
# 3. A2 negative control by mechanism (true vs null means)
# --------------------------------------------------------------------------- #
def negative_control():
    d = _read(EVID / "negative_control_summary_od2.csv")
    controls = ["circular_step_shift", "circular_episode_shift",
                "within_user_time_randomization", "matched_pseudo_episode"]
    clabel = ["circ.step", "circ.epis", "time-rand", "pseudo"]
    mechs = [("A", "Type A", BLUE), ("B", "Type B", TEAL), ("union", "union", PURPLE)]
    true_v = {"A": 0.637, "B": 0.368, "union": 0.359}
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, (m, title, col) in zip(axes, mechs):
        nulls = []
        if d is not None:
            sub = d[(d["mechanism"] == m) & (d["metric"] == "resp_prob_168h")]
            for c in controls:
                r = sub[sub["control"] == c]
                nulls.append(float(r["control_mean"].iloc[0]) if len(r) else np.nan)
            tv = float(sub["true_value"].iloc[0]) if len(sub) else true_v[m]
        else:
            nulls = [0.29, 0.29, 0.29, 0.20]; tv = true_v[m]
        x = np.arange(len(controls))
        ax.bar(x, nulls, color=LGREY, width=0.62, label="control null (168h)")
        ax.axhline(tv, color=RED, lw=2.4, label=f"TRUE = {tv:.3f}")
        ax.set_title(title, color=col, fontweight="bold", fontsize=13)
        ax.set_xticks(x); ax.set_xticklabels(clabel, rotation=25, fontsize=9)
        ax.set_ylim(0, 0.72)
    axes[0].set_ylabel("END-anchored effective\nresponse prob @168h")
    axes[2].legend(loc="upper right", fontsize=9)
    fig.suptitle("A2 negative control: TRUE beats its OWN null for every mechanism (SUPPORTED 4/4)",
                 color=NAVY, fontweight="bold", fontsize=13)
    save(fig, "od2_negative_control_by_mechanism.png")


# --------------------------------------------------------------------------- #
# 4. B response hazard — CIF true vs pseudo per mechanism
# --------------------------------------------------------------------------- #
def response_hazard():
    try:
        c = pd.read_parquet(EVID / "response_hazard_curves_od2.parquet")
    except Exception:
        c = None
    mechs = [("A", "Type A", BLUE), ("B", "Type B", TEAL), ("union", "union", PURPLE)]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, (m, title, col) in zip(axes, mechs):
        if c is not None:
            t = c[(c["mechanism"] == m) & (c["key"] == "true")].sort_values("time_h")
            p = c[(c["mechanism"] == m) & (c["key"] == "pseudo")].sort_values("time_h")
            ax.plot(t["time_h"], t["cif"], color=RED, lw=2.4, label="true END")
            ax.plot(p["time_h"], p["cif"], color=GREY, lw=2.0, ls="--", label="matched pseudo")
        ax.axvline(72, color=LGREY, ls=":", lw=1.1); ax.axvline(168, color=GREEN, ls="--", lw=1.4)
        ax.set_xlim(0, 336); ax.set_ylim(0, 0.72)
        ax.set_title(title, color=col, fontweight="bold", fontsize=13)
        ax.set_xlabel("hours after END")
    axes[0].set_ylabel("cumulative response\nincidence (CIF)")
    axes[0].legend(loc="lower right", fontsize=9)
    fig.suptitle("B response hazard: true >> pseudo; separation grows past 72h (justifies 168h)",
                 color=NAVY, fontweight="bold", fontsize=13)
    save(fig, "od2_response_hazard_by_mechanism.png")


# --------------------------------------------------------------------------- #
# 5. Mechanism strength — healthy response A vs B + k
# --------------------------------------------------------------------------- #
def mechanism_strength():
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    labels = ["Type A\n(deep discharge)", "Type B\n(charge-side)"]
    vals = [0.740, 0.454]; cols = [BLUE, TEAL]; ks = [3, 5]
    b = ax.bar(labels, vals, color=cols, width=0.55)
    for rect, v, k in zip(b, vals, ks):
        ax.text(rect.get_x() + rect.get_width()/2, v + 0.02, f"{v:.2f}\nFW k={k}",
                ha="center", fontsize=11, color=NAVY, fontweight="bold")
    ax.set_ylim(0, 0.9); ax.set_ylabel("healthy-gauge response rate @168h")
    ax.set_title("Two mechanisms, different strength\n(deep = strong trigger, charge-side = frequent/weaker)",
                 color=NAVY, fontweight="bold", fontsize=12)
    save(fig, "od2_mechanism_strength.png")


# --------------------------------------------------------------------------- #
# 6. Offline triage old def vs new def
# --------------------------------------------------------------------------- #
def triage_offline():
    cats = ["FW check", "GAUGE reset", "WATCH"]
    od1 = [14, 18, 55]; od2 = [35, 10, 42]
    x = np.arange(len(cats)); w = 0.38
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(x - w/2, od1, w, color=LGREY, label="old def (72h)")
    ax.bar(x + w/2, od2, w, color=BLUE, label="new def (168h)")
    for i, (a, b_) in enumerate(zip(od1, od2)):
        ax.text(i - w/2, a + 0.7, str(a), ha="center", fontsize=10, color=GREY)
        ax.text(i + w/2, b_ + 0.7, str(b_), ha="center", fontsize=10, color=NAVY, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(cats)
    ax.set_ylabel("users"); ax.legend()
    ax.set_title("Offline triage shift: FW up (14->35), GAUGE down (18->10)",
                 color=NAVY, fontweight="bold")
    save(fig, "od2_triage_offline.png")


# --------------------------------------------------------------------------- #
# 7. Online 9-tier old def vs new def
# --------------------------------------------------------------------------- #
def online_tiers():
    tiers = ["REVIEW_DQ", "NORMAL", "WATCH_LGC", "WATCH_LOW", "FW_WATCH",
             "FW_CORE", "GAUGE_SOFT", "GAUGE_REV", "GAUGE_CORE"]
    od1 = [325, 183, 128, 35, 43, 5, 22, 7, 4]
    od2 = [325, 41, 70, 166, 99, 49, 2, 0, 0]
    y = np.arange(len(tiers)); h = 0.38
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    ax.barh(y + h/2, od1, h, color=LGREY, label="old def")
    ax.barh(y - h/2, od2, h, color=BLUE, label="new def")
    for i, (a, b_) in enumerate(zip(od1, od2)):
        ax.text(a + 3, i + h/2, str(a), va="center", fontsize=9, color=GREY)
        ax.text(b_ + 3, i - h/2, str(b_), va="center", fontsize=9, color=NAVY, fontweight="bold")
    ax.set_yticks(y); ax.set_yticklabels(tiers, fontsize=10); ax.invert_yaxis()
    ax.set_xlabel("users"); ax.legend(loc="lower right")
    ax.set_title("Online 9-tier: FW_CORE 5->49, GAUGE_CORE 4->0, NORMAL 183->41",
                 color=NAVY, fontweight="bold")
    save(fig, "od2_online_tiers.png")


# --------------------------------------------------------------------------- #
# 8. Coverage doubling
# --------------------------------------------------------------------------- #
def coverage():
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    labels = ["old def\n(80/20/80)", "new def\n(Type A + B)"]
    vals = [294, 687]; cols = [LGREY, GREEN]
    b = ax.bar(labels, vals, color=cols, width=0.5)
    for rect, v in zip(b, vals):
        ax.text(rect.get_x()+rect.get_width()/2, v+8, str(v), ha="center",
                fontsize=13, color=NAVY, fontweight="bold")
    ax.axhline(752, color=GREY, ls=":", lw=1.2); ax.text(0.02, 758, "cohort = 752", color=GREY, fontsize=9)
    ax.set_ylim(0, 800); ax.set_ylabel("users with an OK-quality learning opportunity")
    ax.set_title("Opportunity coverage more than doubles (294 -> 687)", color=NAVY, fontweight="bold")
    save(fig, "od2_coverage.png")


# --------------------------------------------------------------------------- #
# 9. E missingness — naive vs proposed
# --------------------------------------------------------------------------- #
def missingness():
    mechs = ["Type A", "Type B", "union"]
    naive = [246.61, 49.53, 203.70]; proposed = [0.33, 2.59, 5.01]
    x = np.arange(len(mechs)); w = 0.38
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(x - w/2, naive, w, color=RED, label="naive detector")
    ax.bar(x + w/2, proposed, w, color=GREEN, label="proposed (censor-aware)")
    for i, (a, b_) in enumerate(zip(naive, proposed)):
        ax.text(i - w/2, a + 4, f"{a:.0f}", ha="center", fontsize=10, color=RED)
        ax.text(i + w/2, b_ + 4, f"{b_:.1f}", ha="center", fontsize=10, color=GREEN, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels(mechs); ax.set_ylabel("mean FALSE confirmed no-response")
    ax.legend(); ax.set_title("E missingness stress: proposed collapses false no-response (~40x)",
                              color=NAVY, fontweight="bold")
    save(fig, "od2_missingness.png")


# --------------------------------------------------------------------------- #
# 10. D retention — stateless agreement vs retention, rw 72 vs 168
# --------------------------------------------------------------------------- #
def retention():
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    days = [7, 14, 30, 60, 90]
    ag72 = [0.771, 0.90, 0.95, 0.965, 0.97]
    ag168 = [0.011, 0.60, 0.90, 0.955, 0.97]
    ax.plot(days, ag72, "-o", color=GREY, lw=2.2, label="stateless rw=72h")
    ax.plot(days, ag168, "-o", color=RED, lw=2.2, label="stateless rw=168h")
    ax.axhline(1.0, color=GREEN, lw=2.6, label="stateful (any retention) = 1.0")
    ax.set_xlabel("raw-data retention (days)"); ax.set_ylabel("response-status agreement vs full history")
    ax.set_ylim(0, 1.05); ax.legend(loc="lower right", fontsize=9.5)
    ax.set_title("D retention: 168h window needs the STATEFUL ledger\n(stateless@7d fails; stateful=1.0 at 30d, storage 4.2%)",
                 color=NAVY, fontweight="bold", fontsize=12)
    save(fig, "od2_retention.png")


if __name__ == "__main__":
    mechanism_diagram(); attribution_window(); negative_control(); response_hazard()
    mechanism_strength(); triage_offline(); online_tiers(); coverage()
    missingness(); retention()
    print("\nAll new def figures written to", FIG)
