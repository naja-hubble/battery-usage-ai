"""Per-user date-vs-SoH small-multiples for a subset of the cohort.

Reads the consolidated parquet, picks the N longest-observed users (clearest time
trend), and draws one date-vs-SoH panel each: daily-median ``soh_design_pct`` over
time, y-axis fixed to 0-110%, with a dashed 100% (design-capacity) reference.

    python plot_soh_by_user.py [N]      # default N = 100

Saves data/reports/figures/soh_by_user_<N>.png
"""
from __future__ import annotations

import math
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")                       # headless / no display
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

from battery_usage.config import load_config
from soh_update_status import (
    compute_update_status, STATUS_COLORS, STATUS_ORDER, STALE_DAYS, VERY_STALE_DAYS,
)

SOH_YLIM = (0, 110)                          # requested display range
NCOL = 10                                    # panels per row


def main(n: int = 100) -> None:
    cfg = load_config()
    pq = cfg.processed_dir / "battery_timeseries_all.parquet"
    if not pq.exists():
        print("Missing", pq, "- run build_timeseries.py first.")
        return

    df = pd.read_parquet(
        pq, columns=["user_id", "batt_vendor", "timestamp",
                     "soh_design_pct", "fullChargeCapacity"],
    )

    # Pick the N users with the longest observation span (best date-vs-SoH signal).
    span = df.groupby("user_id")["timestamp"].agg(["min", "max"])
    span["days"] = (span["max"] - span["min"]).dt.total_seconds() / 86400.0
    users = span.sort_values("days", ascending=False).head(n).index.tolist()

    # Daily-median SoH per selected user (denoise the per-sample jitter + thin out).
    sub = df[df["user_id"].isin(users)].copy()
    sub["date"] = sub["timestamp"].dt.floor("D")
    daily = sub.groupby(["user_id", "date"])["soh_design_pct"].median()
    vendor = sub.groupby("user_id")["batt_vendor"].first()

    # Classify how long each user's SoH has gone without an update (red = very_stale).
    status = compute_update_status(sub).set_index("user_id")

    nrow = math.ceil(len(users) / NCOL)
    fig, axes = plt.subplots(nrow, NCOL, figsize=(NCOL * 2.6, nrow * 2.0), squeeze=False)

    for i, uid in enumerate(users):
        ax = axes[i // NCOL][i % NCOL]
        g = daily.loc[uid]
        st = status.loc[uid, "soh_update_status"]
        ft = status.loc[uid, "soh_flat_tail_days"]
        color = STATUS_COLORS[st]
        lw = 1.4 if st == "very_stale" else (1.0 if st == "stale" else 0.8)
        ax.plot(g.index, g.values, lw=lw, color=color)
        # Mark where SoH last changed (start of the flat tail) for flagged users.
        if st != "active":
            ax.axvline(status.loc[uid, "soh_last_change_ts"], color=color, lw=0.5, ls=":")
        ax.axhline(100, color="grey", lw=0.4, ls="--")     # design-capacity reference
        ax.set_ylim(*SOH_YLIM)
        v = vendor.get(uid) or "?"
        short = uid.split("_")[-1][:12]                     # win_user, truncated
        title_color = "red" if st == "very_stale" else "black"
        ax.set_title(f"{short} · {v} [{ft:.0f}d]", fontsize=6, color=title_color)
        ax.tick_params(labelsize=4)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_ha("right")

    # Blank any unused panels in the last row.
    for j in range(len(users), nrow * NCOL):
        axes[j // NCOL][j % NCOL].axis("off")

    # Status counts among the plotted users, for the legend.
    plotted = status.loc[users, "soh_update_status"]
    cnt = {k: int((plotted == k).sum()) for k in STATUS_ORDER}
    legend_lbl = {
        "active": f"active (<{STALE_DAYS}d)  n={cnt['active']}",
        "stale": f"stale ({STALE_DAYS}-{VERY_STALE_DAYS}d)  n={cnt['stale']}",
        "very_stale": f"very stale (>={VERY_STALE_DAYS}d, RED)  n={cnt['very_stale']}",
    }
    handles = [Line2D([0], [0], color=STATUS_COLORS[k], lw=2, label=legend_lbl[k])
               for k in STATUS_ORDER]
    fig.legend(handles=handles, loc="upper right", fontsize=8, ncol=3,
               frameon=False, bbox_to_anchor=(0.995, 0.997))
    fig.suptitle(
        f"Date vs SoH (vs design) — {len(users)} longest-observed users · daily median · "
        f"y=0-110% · title [Nd]=days since SoH last changed",
        fontsize=12, x=0.30,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.975])

    cfg.ensure_dirs()
    out = cfg.figures_dir / f"soh_by_user_{len(users)}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"wrote {out}  ({len(users)} users, {nrow}x{NCOL} grid)")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    main(n)
