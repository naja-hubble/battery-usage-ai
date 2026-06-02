"""All-user SoH views (every analyzable user, not a subset).

Reads daily-median soh_design_pct per user from the parquet + root-cause labels
from soh_reason_labeled.csv, and renders two figures (y fixed 0-110%):

  soh_overlay_by_class.png  curves overlaid, one facet per root-cause class, aligned
                            on elapsed days since each user's first sample + class
                            median trend — best for reading population trends.
  soh_by_user_all.png       every user as a small panel, coloured + grouped by root
                            cause (complete, all users visible).

    python plot_soh_all.py
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from battery_usage.config import load_config
from classify_reason import CLASS_ORDER as _RC_ORDER, CLASS_COLORS

SOH_YLIM = (0, 110)
# Flagged root-cause classes first, then the active majority.
CLASS_ORDER = list(_RC_ORDER) + ["active"]


def _prep(cfg):
    df = pd.read_parquet(
        cfg.processed_dir / "battery_timeseries_all.parquet",
        columns=["user_id", "timestamp", "soh_design_pct"],
    )
    df["date"] = df["timestamp"].dt.floor("D")
    daily = df.groupby(["user_id", "date"])["soh_design_pct"].median().reset_index()
    first = daily.groupby("user_id")["date"].transform("min")
    daily["elapsed"] = (daily["date"] - first).dt.days

    lab = pd.read_csv(cfg.processed_dir / "soh_reason_labeled.csv",
                      usecols=["user_id", "soh_reason_class", "soh_flat_tail_days"])
    cls = lab.set_index("user_id")["soh_reason_class"]
    ft = lab.set_index("user_id")["soh_flat_tail_days"]
    return daily, cls, ft


def overlay_by_class(cfg, daily, cls):
    classes = CLASS_ORDER
    fig, axes = plt.subplots(2, 3, figsize=(18, 10), squeeze=False)
    for k, cname in enumerate(classes):
        ax = axes[k // 3][k % 3]
        uids = cls.index[cls == cname]
        for uid in uids:
            g = daily[daily["user_id"] == uid]
            ax.plot(g["elapsed"], g["soh_design_pct"], lw=0.5, alpha=0.25,
                    color=CLASS_COLORS[cname])
        # class median trend by 30-day elapsed bin
        sub = daily[daily["user_id"].isin(uids)].copy()
        if not sub.empty:
            sub["bin"] = (sub["elapsed"] // 30) * 30
            med = sub.groupby("bin")["soh_design_pct"].median()
            ax.plot(med.index, med.values, lw=2.4, color="black",
                    label="class median (30d bins)")
        ax.set_ylim(*SOH_YLIM)
        ax.axhline(100, color="grey", lw=0.5, ls="--")
        ax.set_title(f"{cname}  (n={len(uids)})", fontsize=11, color=CLASS_COLORS[cname])
        ax.set_xlabel("days since first sample"); ax.set_ylabel("SoH (vs design) %")
        ax.legend(fontsize=8, loc="lower left")
    for k in range(len(classes), axes.size):       # blank unused facets
        axes[k // 3][k % 3].axis("off")
    fig.suptitle("SoH trajectories by root-cause class — all 752 users, elapsed-aligned, "
                 "y=0-110%", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = cfg.figures_dir / "soh_overlay_by_class.png"
    fig.savefig(out, dpi=130); plt.close(fig)
    print("wrote", out)


def grid_all(cfg, daily, cls, ft, ncol=24):
    # Order: flagged users first grouped by root cause, then active; flat tail desc within.
    order_key = {c: i for i, c in enumerate(CLASS_ORDER)}
    users = sorted(cls.index, key=lambda u: (order_key.get(cls[u], 99), -ft.get(u, 0)))
    nrow = math.ceil(len(users) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(ncol * 1.35, nrow * 1.0), squeeze=False)
    by_user = {u: g for u, g in daily.groupby("user_id")}
    for i, uid in enumerate(users):
        ax = axes[i // ncol][i % ncol]
        g = by_user[uid]
        ax.plot(g["date"], g["soh_design_pct"], lw=0.7, color=CLASS_COLORS[cls[uid]])
        ax.axhline(100, color="grey", lw=0.3, ls="--")
        ax.set_ylim(*SOH_YLIM)
        ax.set_xticks([]); ax.set_yticks([])
    for j in range(len(users), nrow * ncol):
        axes[j // ncol][j % ncol].axis("off")
    handles = [Line2D([0], [0], color=CLASS_COLORS[c], lw=3,
                      label=f"{c} (n={int((cls == c).sum())})") for c in CLASS_ORDER]
    fig.legend(handles=handles, loc="upper center", ncol=6, fontsize=10, frameon=False,
               bbox_to_anchor=(0.5, 0.998))
    fig.suptitle("Date vs SoH — ALL 752 users, coloured + grouped by root cause · y=0-110%",
                 fontsize=14, y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    out = cfg.figures_dir / "soh_by_user_all.png"
    fig.savefig(out, dpi=110); plt.close(fig)
    print("wrote", out, f"({len(users)} users, {nrow}x{ncol})")


def main():
    cfg = load_config()
    cfg.ensure_dirs()
    daily, cls, ft = _prep(cfg)
    print(f"prepared daily SoH for {daily['user_id'].nunique()} users, {len(daily):,} day-rows")
    overlay_by_class(cfg, daily, cls)
    grid_all(cfg, daily, cls, ft)


if __name__ == "__main__":
    main()
