#!/usr/bin/env python
"""Compare FCC logs: gauge-reset targets vs non-targets (OD2 final labels).

Top row: FCC trajectories (as % of each user's first FCC) — GAUGE-RESET targets (flat)
vs NORMAL/responding users (stepping down as the gauge relearns).
Bottom row: per-user summary boxplots (FCC update rate, flat-tail days) by group.

Output: data/reports/figures/fcc_relearn_od2/od2_gauge_vs_nongauge_fcc.png
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Japanese font if available (fallback = default)
for _f in ["Meiryo", "Yu Gothic", "MS Gothic", "MS PGothic"]:
    if any(_f.lower() in n.name.lower() for n in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break
plt.rcParams.update({"axes.unicode_minus": False, "font.size": 12,
                     "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
                     "axes.grid": True, "grid.color": "#E6E6E6"})

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
LAB = PROC / "fcc_relearn_od2" / "offline" / "od2_final_action_labels.csv"
PARQ = PROC / "battery_timeseries_all.parquet"
FIG = REPO / "data" / "reports" / "figures" / "fcc_relearn_od2"
ORANGE = "#B05A00"; BLUE = "#1F77B4"; NAVY = "#1F375B"; RED = "#C0392B"; GREY = "#888888"
GREEN = "#2CA02C"

lab = pd.read_csv(LAB)
col = "final_label_od2_rejk"
gauge_ids = lab.loc[lab[col].str.contains("GAUGE_RESET"), "user_id"].tolist()
normal = lab[lab[col].str.contains("NORMAL")].copy()
cand = normal[normal["obs_days"] >= 180].copy() if "obs_days" in normal else normal.copy()

# Load FCC for gauge + NORMAL candidates, then keep ONLY clearly-updating NORMAL users
# (visible total decline, updating right up to the end) so none look "flat" / misleading.
ts_all = pd.read_parquet(PARQ, columns=["user_id", "timestamp", "fullChargeCapacity"])
ts_all = ts_all[ts_all["user_id"].isin(set(gauge_ids) | set(cand["user_id"]))].copy()
ts_all["timestamp"] = pd.to_datetime(ts_all["timestamp"])


def _decline_pct(g):
    f = g.sort_values("timestamp")["fullChargeCapacity"].to_numpy(float)
    f = f[np.isfinite(f) & (f > 0)]
    return (f[0] - f[-1]) / f[0] * 100.0 if f.size >= 2 else 0.0


dec = (ts_all[ts_all["user_id"].isin(cand["user_id"])]
       .groupby("user_id").apply(_decline_pct).rename("decline_pct").reset_index())
cand = cand.merge(dec, on="user_id", how="left")
upd = cand[(cand["decline_pct"] >= 5.0) & (cand["flat_tail_days"] <= 25) &
           (cand["fcc_change_rate_per_100d"] >= 10)]
rng = np.random.default_rng(42)
n_show = min(14, len(upd))
normal_ids = (list(upd["user_id"].iloc[rng.choice(len(upd), n_show, replace=False)])
              if len(upd) else [])
print(f"clearly-updating NORMAL available={len(upd)} (of {len(cand)} obs>=180d); plotting {n_show}")
ts = ts_all[ts_all["user_id"].isin(gauge_ids + normal_ids)].copy()


def traj(ax, ids, color, title, mean_color):
    curves = []
    for uid, g in ts[ts["user_id"].isin(ids)].groupby("user_id"):
        g = g.sort_values("timestamp")
        fcc = g["fullChargeCapacity"].to_numpy(float)
        fcc = fcc[np.isfinite(fcc) & (fcc > 0)]
        if fcc.size < 2:
            continue
        t = g["timestamp"].to_numpy()
        t = t[np.isfinite(g["fullChargeCapacity"].to_numpy(float)) & (g["fullChargeCapacity"].to_numpy(float) > 0)]
        days = (t - t[0]) / np.timedelta64(1, "D")
        pct = fcc / fcc[0] * 100.0
        ax.plot(days, pct, color=color, lw=1.1, alpha=0.55)
        curves.append((days, pct))
    ax.axhline(100, color=GREY, ls=":", lw=1)
    ax.set_xlabel("経過日数 (days)"); ax.set_ylabel("FCC（初期値=100%）")
    ax.set_title(title, color=NAVY, fontweight="bold", fontsize=12)
    ax.set_ylim(60, 108)
    return curves


fig = plt.figure(figsize=(13.2, 8.6))
gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1.0], hspace=0.42, wspace=0.22)
axA = fig.add_subplot(gs[0, 0]); axB = fig.add_subplot(gs[0, 1], sharey=axA)
traj(axA, gauge_ids, ORANGE, f"ゲージリセット対象 (n={len(gauge_ids)}) — FCCが凍結（ほぼ平坦）", ORANGE)
traj(axB, normal_ids, BLUE, f"非対象：NORMAL/応答あり・更新が明確な例 (n={len(normal_ids)}) — FCCが階段状に低下", BLUE)

# bottom: summary boxplots by group (all users in each label)
g_rate = lab.loc[lab[col].str.contains("GAUGE_RESET"), "fcc_change_rate_per_100d"].dropna()
n_rate = lab.loc[lab[col].str.contains("NORMAL"), "fcc_change_rate_per_100d"].dropna()
f_rate = lab.loc[lab[col].str.contains("FW_CHECK"), "fcc_change_rate_per_100d"].dropna()
g_ft = lab.loc[lab[col].str.contains("GAUGE_RESET"), "flat_tail_days"].dropna()
n_ft = lab.loc[lab[col].str.contains("NORMAL"), "flat_tail_days"].dropna()
f_ft = lab.loc[lab[col].str.contains("FW_CHECK"), "flat_tail_days"].dropna()

axC = fig.add_subplot(gs[1, 0]); axD = fig.add_subplot(gs[1, 1])
box_cols = [ORANGE, BLUE, RED]
labels3 = ["ゲージ\n(n=%d)" % len(g_rate), "NORMAL\n(n=%d)" % len(n_rate), "FW確認\n(n=%d)" % len(f_rate)]
for ax, data, title, ylab in [
    (axC, [g_rate, n_rate, f_rate], "FCC更新率（回/100日）— ゲージ対象はほぼ0", "fcc_change_rate_per_100d"),
    (axD, [g_ft, n_ft, f_ft], "凍結日数（末尾でFCC不変の日数）— ゲージ対象は長い", "flat_tail_days")]:
    bp = ax.boxplot(data, patch_artist=True, widths=0.6, showfliers=False,
                    medianprops=dict(color="black", lw=1.6))
    for patch, c in zip(bp["boxes"], box_cols):
        patch.set_facecolor(c); patch.set_alpha(0.55)
    ax.set_xticklabels(labels3); ax.set_ylabel(ylab)
    ax.set_title(title, color=NAVY, fontweight="bold", fontsize=11.5)

fig.suptitle("ゲージリセット対象 vs 非対象：FCCログ比較（OD2最終ラベル）",
             color=NAVY, fontweight="bold", fontsize=15)
out = FIG / "od2_gauge_vs_nongauge_fcc.png"
fig.savefig(out, facecolor="white")
plt.close(fig)
print("wrote", out)
print(f"GAUGE median: rate={g_rate.median():.2f}/100d, flat_tail={g_ft.median():.0f}d")
print(f"NORMAL median: rate={n_rate.median():.2f}/100d, flat_tail={n_ft.median():.0f}d")
print(f"font: {plt.rcParams['font.family']}")
