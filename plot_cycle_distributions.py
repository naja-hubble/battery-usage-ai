"""Plot battery cycle-count distributions from the per-user master table.

Produces two publication-quality figures (dpi=600) from
``data/processed/user_master.csv`` (one row per user; ``cycle_count_last`` is the
authoritative live cycle count, ``batt_fru`` is the battery FRU / part number):

  1. cycle_distribution_user.png
       Histogram of per-user cycle count across the whole cohort, with the
       maximum value annotated (plus median / mean for context).

  2. cycle_distribution_by_fru.png
       Per-FRU distribution of user cycle counts (horizontal box + jittered
       points), sorted by median, with the per-FRU maximum annotated. FRUs are
       restricted to those with at least ``MIN_USERS_PER_FRU`` users so each box
       represents a real distribution; the excluded long tail is reported in a
       footnote.

A companion ``cycle_distribution_by_fru_summary.csv`` records n / min / median /
mean / max per FRU for traceability.

    python plot_cycle_distributions.py

FRU normalization: control characters (e.g. ``\x0e``), a leading ``LNV-`` prefix,
and trailing junk (``@`` / ``?``) are stripped so that report-format variants
(e.g. ``\x0eLNV-5B10W51877`` and ``5B10W51877``) collapse to the same physical
part number.

Both figures use scale tricks to cope with the heavy right skew (cycle counts
span 1..910): the per-user histogram uses a log-scaled count axis so the long
tail of high-cycle users stays visible, and the per-FRU plot uses a log-scaled
cycle axis so low- and high-cycle FRUs are both legible. Linear-axis variants
(``*_linear.png``) are written alongside each for direct value reading.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ---- config --------------------------------------------------------------
SRC = Path("data/processed/user_master.csv")
OUT_DIR = Path("data/reports/figures/cycle_distribution")
DPI = 600
MIN_USERS_PER_FRU = 5          # a "distribution" needs several points
BIN_WIDTH = 25                 # cycle-count histogram bin width

# Use a Japanese-capable font if present (Windows 11 ships Meiryo / Yu Gothic).
_installed = {f.name for f in font_manager.fontManager.ttflist}
for _f in ("Meiryo", "Yu Gothic", "MS Gothic"):
    if _f in _installed:
        plt.rcParams["font.family"] = _f
        break
else:  # no CJK font -> Japanese labels would render as tofu; warn loudly
    import warnings
    warnings.warn(
        "No Japanese-capable font (Meiryo/Yu Gothic/MS Gothic) found; "
        "CJK labels will render as missing-glyph boxes."
    )
plt.rcParams["axes.unicode_minus"] = False     # keep minus sign with CJK font


def normalize_fru(s: pd.Series) -> pd.Series:
    """Collapse report-format FRU variants to a canonical part number."""
    return (
        s.astype("string")
        .str.replace(r"[\x00-\x1f]", "", regex=True)  # control chars (e.g. \x0e)
        .str.strip()
        .str.replace(r"^LNV-", "", regex=True)         # vendor prefix
        .str.replace(r"[@?]+$", "", regex=True)        # trailing junk (@, ?)
        .str.strip()
    )


def plot_user_distribution(cycles: pd.Series, out: Path, log: bool = True) -> None:
    cmax = float(cycles.max())
    cmed = float(cycles.median())
    cmean = float(cycles.mean())
    n = len(cycles)

    bins = np.arange(0, (np.ceil(cmax / BIN_WIDTH) + 1) * BIN_WIDTH, BIN_WIDTH)

    fig, ax = plt.subplots(figsize=(11, 6.2))
    ax.hist(cycles, bins=bins, color="#3b6ea5", edgecolor="white", linewidth=0.4)
    if log:
        # Log count axis: the bulk sits in the first few bins while the high-cycle
        # tail is only 1-4 users/bin — a linear axis would hide that tail entirely.
        ax.set_yscale("log")
        ax.set_ylim(0.7, None)

    for val, color, label in [
        (cmed, "#2ca02c", f"中央値 = {cmed:.0f}"),
        (cmean, "#ff7f0e", f"平均 = {cmean:.1f}"),
        (cmax, "#d62728", f"最大 = {cmax:.0f}"),
    ]:
        ax.axvline(val, color=color, linestyle="--", linewidth=1.6, label=label)

    # Prominent max annotation (nudged off the right spine). On a log axis the
    # callout sits at the geometric mid-height and anchors on the tail bar; on a
    # linear axis it sits high and anchors at the baseline.
    ymin, ymax = ax.get_ylim()
    y_text = np.sqrt(ymin * ymax) if log else ymax * 0.55
    ax.annotate(
        f"最大値 = {cmax:.0f} cycles",
        xy=(cmax, 1 if log else 0),
        xytext=(cmax * 0.985, y_text),
        ha="right",
        fontsize=11,
        fontweight="bold",
        color="#d62728",
        arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.3),
    )

    scale_tag = "  (y: log scale)" if log else "  (y: linear)"
    ax.set_title(
        f"User cycle 分布  (n = {n} users){scale_tag}",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.set_xlabel("Cycle count (cycle_count_last)", fontsize=12)
    ax.set_ylabel("ユーザー数  (log scale)" if log else "ユーザー数", fontsize=12)
    ax.set_xlim(0, bins[-1])
    ax.grid(axis="y", which="both" if log else "major", alpha=0.3)
    ax.legend(frameon=False, fontsize=11, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}  (n={n}, max={cmax:.0f}, median={cmed:.0f}, mean={cmean:.1f})")


def plot_fru_distribution(df: pd.DataFrame, out: Path, summary_csv: Path,
                          log: bool = True) -> None:
    valid = df.dropna(subset=["batt_fru"])
    n_null_fru = len(df) - len(valid)

    grp = valid.groupby("batt_fru")["cycle_count_last"]
    counts = grp.size()
    keep = counts[counts >= MIN_USERS_PER_FRU].index
    sub = valid[valid["batt_fru"].isin(keep)].copy()

    # Per-FRU summary, sorted by median cycle (ascending so highest is at TOP
    # of a horizontal axis).
    summ = (
        sub.groupby("batt_fru")["cycle_count_last"]
        .agg(n="size", min="min", median="median", mean="mean", max="max")
        .sort_values(["median", "mean"])   # mean breaks median ties deterministically
    )
    summ.to_csv(summary_csv)

    frus = list(summ.index)
    data = [sub.loc[sub["batt_fru"] == f, "cycle_count_last"].values for f in frus]
    positions = np.arange(1, len(frus) + 1)

    fig_h = max(6.0, 0.42 * len(frus) + 1.8)
    fig, ax = plt.subplots(figsize=(12, fig_h))

    bp = ax.boxplot(
        data, positions=positions, vert=False, widths=0.62,
        patch_artist=True, showfliers=False,
        medianprops=dict(color="#08306b", linewidth=1.6),
        whiskerprops=dict(color="#5a5a5a"),
        capprops=dict(color="#5a5a5a"),
        boxprops=dict(edgecolor="#5a5a5a"),
    )
    for patch in bp["boxes"]:
        patch.set_facecolor("#9ecae1")
        patch.set_alpha(0.75)

    # Jittered individual users for transparency on small groups.
    rng = np.random.default_rng(0)
    for pos, vals in zip(positions, data):
        jit = rng.uniform(-0.16, 0.16, size=len(vals))
        ax.scatter(vals, pos + jit, s=10, color="#08519c", alpha=0.45, zorder=3,
                   edgecolors="none")

    # Log cycle axis (default): one FRU reaches 910 while ~half sit below 150 —
    # a linear axis crushes the low-cycle FRUs into a sliver at the left.
    xmax = float(sub["cycle_count_last"].max())
    if log:
        ax.set_xscale("log")
        ax.set_xlim(0.8, xmax * 1.9)        # headroom on the right for max labels
    else:
        ax.set_xlim(0, xmax * 1.13)

    # Per-FRU max annotation, placed just right of that FRU's own max point
    # (multiplicative offset on a log axis, additive on a linear one).
    for pos, f in zip(positions, frus):
        m = int(summ.loc[f, "max"])
        x_lab = m * 1.06 if log else m + xmax * 0.012
        ax.text(x_lab, pos, f"max {m}", va="center", ha="left",
                fontsize=8, color="#d62728", fontweight="bold")

    ax.set_yticks(positions)
    ax.set_yticklabels([f"{f}  (n={int(summ.loc[f, 'n'])})" for f in frus], fontsize=8)
    ax.set_ylim(0.4, len(frus) + 0.6)
    ax.set_xlabel("Cycle count (cycle_count_last, log scale)" if log
                  else "Cycle count (cycle_count_last)", fontsize=12)
    scale_tag = "x: log scale" if log else "x: linear"
    ax.set_title(
        f"FRU 別 User cycle 分布  "
        f"(FRUあたり users ≥ {MIN_USERS_PER_FRU}, {len(frus)} FRUs / {len(sub)} users, {scale_tag})",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.grid(axis="x", which="both" if log else "major", alpha=0.3)

    n_excluded_fru = int((counts < MIN_USERS_PER_FRU).sum())
    n_excluded_users = int(counts[counts < MIN_USERS_PER_FRU].sum())
    foot = (
        f"赤字 = FRU別の最大cycle値。 箱 = 四分位、点 = 個別ユーザー。 "
        f"中央値で昇順ソート。\n"
        f"除外: users < {MIN_USERS_PER_FRU} の {n_excluded_fru} FRUs "
        f"({n_excluded_users} users) と FRU未取得 {n_null_fru} users。"
    )
    fig.text(0.01, 0.005, foot, fontsize=8, color="#444444", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out}  ({len(frus)} FRUs, {len(sub)} users, "
          f"excluded {n_excluded_fru} FRUs/{n_excluded_users} users + {n_null_fru} null-FRU)")
    print(f"  wrote {summary_csv}")


def main() -> None:
    df = pd.read_csv(SRC)
    df = df[["user_id", "batt_fru", "cycle_count_last"]].copy()
    df["cycle_count_last"] = pd.to_numeric(df["cycle_count_last"], errors="coerce")
    df = df.dropna(subset=["cycle_count_last"])
    df["batt_fru"] = normalize_fru(df["batt_fru"]).replace({"": pd.NA})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loaded {len(df)} users from {SRC}")
    summary = OUT_DIR / "cycle_distribution_by_fru_summary.csv"

    # Log-scaled (default) + linear variants of each figure.
    plot_user_distribution(df["cycle_count_last"],
                           OUT_DIR / "cycle_distribution_user.png", log=True)
    plot_user_distribution(df["cycle_count_last"],
                           OUT_DIR / "cycle_distribution_user_linear.png", log=False)
    plot_fru_distribution(df, OUT_DIR / "cycle_distribution_by_fru.png", summary, log=True)
    plot_fru_distribution(df, OUT_DIR / "cycle_distribution_by_fru_linear.png", summary, log=False)


if __name__ == "__main__":
    main()
