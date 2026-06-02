"""Plotting: cohort-level distributions and per-user detail figures.

All figures are written as PNGs under ``data/reports/figures/`` and the saved
paths returned so the report layer can embed them. Uses a non-interactive
matplotlib backend so it runs headless.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import seaborn as sns
    sns.set_theme(style="whitegrid")
except Exception:  # pragma: no cover
    sns = None

from .anon import display_id
from .config import Config
from .features import discharge_sessions, soh_timeseries
from .parse import UserData


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Cohort-level figures
# ---------------------------------------------------------------------------
def plot_cohort(cohort: pd.DataFrame, cfg: Config) -> Dict[str, Path]:
    figdir = cfg.figures_dir
    out: Dict[str, Path] = {}

    def hist(col: str, title: str, xlabel: str, fname: str, bins: int = 20):
        if col not in cohort or cohort[col].dropna().empty:
            return
        fig, ax = plt.subplots(figsize=(6, 4))
        data = pd.to_numeric(cohort[col], errors="coerce").dropna()
        ax.hist(data, bins=min(bins, max(5, len(data))), color="#4C72B0", edgecolor="white")
        ax.axvline(data.median(), color="#C44E52", ls="--", lw=1.5,
                   label=f"median {data.median():.1f}")
        ax.set_title(title); ax.set_xlabel(xlabel); ax.set_ylabel("users"); ax.legend()
        out[fname] = _save(fig, figdir / fname)

    hist("soh_peak_pct", "State of Health (vs peak capacity)", "SOH %", "cohort_soh.png")
    hist("capacity_fade_pct", "Capacity fade from peak", "fade %", "cohort_fade.png")
    hist("ac_time_ratio", "AC (plugged-in) time ratio", "fraction of time on AC", "cohort_ac_ratio.png")
    hist("cycles_per_year", "Charge cycles per year", "cycles / year", "cohort_cycles_per_year.png")
    hist("mean_dod_pct", "Mean depth of discharge per session", "DoD %", "cohort_dod.png")

    # SOH vs cycle count scatter, coloured by persona if present.
    if {"cycle_count_last", "soh_peak_pct"}.issubset(cohort.columns):
        d = cohort.dropna(subset=["cycle_count_last", "soh_peak_pct"])
        if not d.empty:
            fig, ax = plt.subplots(figsize=(6.5, 4.5))
            if "persona_label" in d:
                for lbl, g in d.groupby("persona_label"):
                    ax.scatter(g["cycle_count_last"], g["soh_peak_pct"], s=45, alpha=0.8, label=str(lbl))
                ax.legend(fontsize=8, title="persona")
            else:
                ax.scatter(d["cycle_count_last"], d["soh_peak_pct"], s=45, alpha=0.8)
            ax.set_xlabel("cycle count"); ax.set_ylabel("SOH % (vs peak)")
            ax.set_title("Battery health vs cycle count")
            out["cohort_soh_vs_cycles.png"] = _save(fig, figdir / "cohort_soh_vs_cycles.png")

    # Usage-mode landscape: AC ratio vs mean % remaining.
    if {"ac_time_ratio", "mean_pct_remaining"}.issubset(cohort.columns):
        d = cohort.dropna(subset=["ac_time_ratio", "mean_pct_remaining"])
        if not d.empty:
            fig, ax = plt.subplots(figsize=(6.5, 4.5))
            sizes = pd.to_numeric(d.get("cycles_per_year", 20), errors="coerce").fillna(20)
            sc = ax.scatter(d["ac_time_ratio"], d["mean_pct_remaining"],
                            s=30 + 4 * sizes.clip(0, 60), alpha=0.7, c="#55A868", edgecolor="k", lw=0.4)
            ax.set_xlabel("AC time ratio (0=always battery, 1=always plugged)")
            ax.set_ylabel("mean % remaining")
            ax.set_title("Usage landscape (marker size ~ cycles/yr)")
            out["cohort_usage_landscape.png"] = _save(fig, figdir / "cohort_usage_landscape.png")

    return out


# ---------------------------------------------------------------------------
# Per-user figures
# ---------------------------------------------------------------------------
def plot_user(ud: UserData, cfg: Config) -> Dict[str, Path]:
    df = ud.battery
    if df.empty:
        return {}
    figdir = cfg.figures_dir / "users"
    out: Dict[str, Path] = {}
    # Pseudonym for titles + filenames so PNGs carry no username/serial.
    sid = display_id(ud.safe_id, cfg.analysis.get("anonymize", True))

    # (1) % remaining timeline, shaded by AC/battery.
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(df["timestamp"], df["remainingCapacityInPercentage"], lw=0.7, color="#333")
    on_batt = df["acdcMode"] == 0
    ax.fill_between(df["timestamp"], 0, 100, where=on_batt, color="#C44E52", alpha=0.12, step="post",
                    label="on battery")
    ax.set_ylim(0, 105); ax.set_ylabel("% remaining"); ax.set_title(f"{sid} — charge timeline")
    ax.legend(loc="lower left", fontsize=8)
    out[f"{sid}_timeline.png"] = _save(fig, figdir / f"{sid}_timeline.png")

    # (2) SOH / capacity trend vs time (twin axis with cycle count).
    soh = soh_timeseries(df, ud.design_capacity)
    if not soh.empty:
        fig, ax = plt.subplots(figsize=(7, 3.4))
        ax.plot(soh["date"], soh["soh_peak"], color="#4C72B0", label="SOH (vs peak)")
        if soh["soh_design"].notna().any():
            ax.plot(soh["date"], soh["soh_design"], color="#8172B3", ls="--", label="SOH (vs design)")
        ax.set_ylabel("SOH %"); ax.set_title(f"{sid} — state of health")
        ax2 = ax.twinx()
        ax2.plot(soh["date"], soh["cycleCount"], color="#CCB974", alpha=0.7, label="cycles")
        ax2.set_ylabel("cycle count")
        ax.legend(loc="lower left", fontsize=8)
        out[f"{sid}_soh.png"] = _save(fig, figdir / f"{sid}_soh.png")

    return out


def plot_top_users(uds: List[UserData], cfg: Config, k: int = 3) -> Dict[str, Path]:
    """Detail figures for the first ``k`` users that have a usable time-series."""
    out: Dict[str, Path] = {}
    made = 0
    for ud in uds:
        if ud.battery.empty:
            continue
        out.update(plot_user(ud, cfg))
        made += 1
        if made >= k:
            break
    return out
