"""Visualisations for the FCC-learning intervention classifier.

Two layers:
  * cohort-level summaries  (funnel, label counts, opportunity-vs-response,
    flat-tail-vs-tail-cycles, hardware enrichment of the FW-check targets)
  * per-user time-series panels for the top-20 gauge-reset and top-20 FW-check targets,
    so an operator can eyeball each recommendation (RSOC, FCC/SoH, cycleCount, AC/DC,
    learning episodes, FCC change points, last FCC change).

Can be driven by ``analyze_fcc_learning_actions.py`` (``generate_all`` with in-memory
frames) or standalone (reads the CSVs + parquet it needs):

    python plot_fcc_learning_actions.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")                          # headless / no display
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm


def _use_cjk_font() -> None:
    """Pick the first installed CJK-capable font so Japanese labels render (not tofu)."""
    available = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Yu Gothic", "Meiryo", "MS Gothic", "BIZ UDGothic", "Noto Sans CJK JP"):
        if cand in available:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False   # avoid minus-glyph warnings under CJK fonts


_use_cjk_font()

from battery_usage.config import load_config
from battery_usage.fcc_learning import (
    DEFAULT_CONFIG, EPISODE_THRESHOLDS, fcc_step_indicator, _sorted_unique,
)
from battery_usage.fcc_action_classifier import (
    LABEL_ORDER, LABEL_COLORS, LABEL_GAUGE, LABEL_FW,
)

_TS_COLS = ["user_id", "timestamp", "remainingCapacityInPercentage", "cycleCount",
            "fullChargeCapacity", "soh_design_pct", "acdcMode", "serialNumber"]


# --------------------------------------------------------------------------- #
# Cohort-level summaries
# --------------------------------------------------------------------------- #
def plot_funnel(funnel: Dict[str, int], path: Path) -> None:
    stages = [
        ("全ユーザー", funnel["all_users"], "lightgray"),
        ("no/low FCC候補", funnel["candidates"], "tab:blue"),
        ("機会なし→gauge_reset", funnel["no_opportunity"], LABEL_COLORS[LABEL_GAUGE]),
        ("機会あり無応答→fw_check", funnel["has_opportunity"], LABEL_COLORS[LABEL_FW]),
        ("watch(曖昧)", funnel["watch"], "gold"),
    ]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ys = range(len(stages))[::-1]
    for y, (lbl, val, col) in zip(ys, stages):
        ax.barh(y, val, color=col, edgecolor="black", lw=0.5)
        ax.text(val, y, f" {val}", va="center", fontsize=10, fontweight="bold")
    ax.set_yticks(list(ys))
    ax.set_yticklabels([s[0] for s in stages], fontsize=9)
    ax.set_xlabel("ユーザー数")
    ax.set_title("介入分類ファネル: 全 → no/low FCC候補 → 機会なし/あり → アクション")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_label_counts(labels: pd.DataFrame, path: Path) -> None:
    vc = labels["final_label"].value_counts().reindex(LABEL_ORDER).fillna(0).astype(int)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(range(len(vc)), vc.values,
                  color=[LABEL_COLORS[k] for k in vc.index], edgecolor="black", lw=0.5)
    ax.bar_label(bars, fontsize=10, fontweight="bold")
    ax.set_xticks(range(len(vc)))
    ax.set_xticklabels([k.replace("_", "\n") for k in vc.index], fontsize=7)
    ax.set_ylabel("ユーザー数")
    ax.set_title(f"最終ラベル別件数（合計 {int(vc.sum())}・相互排他）")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_opportunity_vs_response(labels: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = labels["tail_n_80_20_80_ok"].to_numpy(dtype=float)
    y = labels["relevant_response_rate_72h"].to_numpy(dtype=float)
    jitter = (np.linspace(-0.18, 0.18, len(x)) if len(x) else 0)
    for lab in LABEL_ORDER:
        m = (labels["final_label"] == lab).to_numpy()
        if m.any():
            ax.scatter(x[m] + jitter[m], y[m], s=22, alpha=0.7, label=lab,
                       color=LABEL_COLORS[lab], edgecolor="none")
    ax.set_xlabel("tail期間中の学習機会数 (tail_n_80_20_80_ok)")
    ax.set_ylabel("FCC応答率 relevant_response_rate_72h")
    ax.set_title("学習機会数 vs FCC応答率（NaN応答=判定不能は非表示）")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=6, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_flat_tail_vs_tail_cycles(labels: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.5))
    x = labels["flat_tail_days"].to_numpy(dtype=float)
    y = labels["tail_cycle_delta"].to_numpy(dtype=float)
    for lab in LABEL_ORDER:
        m = (labels["final_label"] == lab).to_numpy()
        if m.any():
            ax.scatter(x[m], y[m], s=22, alpha=0.7, label=lab,
                       color=LABEL_COLORS[lab], edgecolor="none")
    ax.axhline(20, color="grey", lw=0.5, ls="--")
    ax.axvline(120, color="grey", lw=0.5, ls="--")
    ax.axvline(180, color="grey", lw=0.5, ls=":")
    ax.set_xlabel("flat_tail_days（最後のFCC更新からの日数）")
    ax.set_ylabel("tail_cycle_delta（tail期間のサイクル増分）")
    ax.set_title("flat_tail_days vs tail_cycle_delta（最終ラベルで色分け）")
    ax.legend(fontsize=6, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_hardware_enrichment_fw(enrich: pd.DataFrame, path: Path) -> None:
    attrs = ["device_model", "batt_vendor", "batt_fru"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))
    for ax, attr in zip(axes, attrs):
        sub = enrich[(enrich["attribute"] == attr) & (enrich["n_total"] >= 5)]
        sub = sub.sort_values("fw_check_rate", ascending=False).head(12)
        if sub.empty:
            ax.axis("off"); ax.set_title(f"{attr}: n<5のみ"); continue
        ypos = range(len(sub))[::-1]
        ax.barh(list(ypos), sub["fw_check_rate"].values, color="darkred",
                edgecolor="black", lw=0.4)
        for y, (_, r) in zip(ypos, sub.iterrows()):
            ax.text(r["fw_check_rate"], y, f"  {int(r['n_fw_check'])}/{int(r['n_total'])}",
                    va="center", fontsize=7)
        ax.set_yticks(list(ypos))
        # Strip the shared "ThinkPad " prefix so the distinguishing generation stays visible.
        ax.set_yticklabels([str(v).replace("ThinkPad ", "")[:22] for v in sub["value"]], fontsize=7)
        ax.set_xlabel("fw_check率")
        ax.set_title(f"{attr}（n_total>=5, fw率降順）")
        ax.set_xlim(0, max(0.05, float(sub["fw_check_rate"].max()) * 1.25))
    fig.suptitle("FW確認対象のmodel/vendor/FRU偏在（分類には不使用・母数 fw/total 併記）", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Per-user time-series panels
# --------------------------------------------------------------------------- #
def plot_user_panel(
    g: pd.DataFrame, eps_u: pd.DataFrame, feat_row: pd.Series, path: Path,
    cfg=DEFAULT_CONFIG,
) -> None:
    """One user's RSOC / FCC+SoH / cycleCount panels with episodes + FCC change points."""
    g = _sorted_unique(g)
    ts = g["timestamp"]
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    soh = g["soh_design_pct"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ac = (g["acdcMode"] == 1).to_numpy()
    is_step, _ = fcc_step_indicator(fcc, cfg.fcc_change_min_mwh)
    last_change = pd.to_datetime(feat_row["last_fcc_change_ts"])

    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)

    # --- panel 1: RSOC + AC shading + episode spans ---
    ax = axes[0]
    ax.plot(ts, rsoc, lw=0.6, color="navy")
    ax.fill_between(ts, 0, 100, where=ac, color="khaki", alpha=0.30, step="post",
                    label="AC給電", lw=0)
    # episode spans: primary band (light) overlaid by strict band (green edge), OK only.
    span_colors = {"primary_80_20_80": ("tab:blue", 0.16), "strict_90_10_90": ("green", 0.20)}
    for name, (col, al) in span_colors.items():
        for _, e in eps_u[(eps_u["threshold_name"] == name) & (eps_u["episode_quality"] == "ok")].iterrows():
            ax.axvspan(e["start_ts"], e["end_ts"], color=col, alpha=al, lw=0)
    ax.axhline(20, color="grey", lw=0.4, ls=":")
    ax.axhline(90, color="grey", lw=0.4, ls=":")
    ax.set_ylim(-2, 105)
    ax.set_ylabel("RSOC %")
    ax.legend(fontsize=6, loc="lower left")

    # --- panel 2: FCC + SoH, FCC change points, last-change line ---
    ax = axes[1]
    ax.plot(ts, fcc, lw=0.8, color="darkred", label="FCC(mWh)")
    if is_step.any():
        ax.scatter(ts[is_step], fcc[is_step], s=18, color="black", zorder=5, label="FCC変化点")
    ax.axvline(last_change, color="purple", lw=1.0, ls="--", label="最後のFCC変化")
    ax.set_ylabel("FCC mWh", color="darkred")
    ax2 = ax.twinx()
    ax2.plot(ts, soh, lw=0.5, color="tab:green", alpha=0.7)
    ax2.set_ylabel("SoH %", color="tab:green")
    ax.legend(fontsize=6, loc="lower left")

    # --- panel 3: cycleCount ---
    ax = axes[2]
    ax.plot(ts, cyc, lw=0.9, color="teal")
    ax.set_ylabel("cycleCount")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))

    short = str(feat_row["user_id"]).split("_")[-1][:16]
    title = (f"{short} · {feat_row['final_label']} ({feat_row['confidence']}) · "
             f"flat_tail={feat_row['flat_tail_days']:.0f}d · "
             f"tail_ok[90/80]={int(feat_row['tail_n_90_10_90_ok'])}/{int(feat_row['tail_n_80_20_80_ok'])} · "
             f"resp72h={_fmt(feat_row['relevant_response_rate_72h'])} · "
             f"g={feat_row['gauge_reset_score_0_100']:.0f}/fw={feat_row['fw_check_score_0_100']:.0f}")
    fig.suptitle(title, fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _fmt(x) -> str:
    return f"{x:.2f}" if pd.notna(x) else "NA"


def plot_top_examples(
    df_ts: pd.DataFrame, labels: pd.DataFrame, episodes: pd.DataFrame,
    action_label: str, score_col: str, out_dir: Path, n: int = 20, cfg=DEFAULT_CONFIG,
) -> int:
    sub = labels[labels["final_label"] == action_label].sort_values(score_col, ascending=False).head(n)
    out_dir.mkdir(parents=True, exist_ok=True)
    drawn = 0
    for rank, (_, frow) in enumerate(sub.iterrows(), 1):
        uid = frow["user_id"]
        g = df_ts[df_ts["user_id"] == uid]
        if g.empty:
            continue
        eps_u = episodes[episodes["user_id"] == uid]
        safe = str(uid).replace("/", "_").replace("\\", "_")
        plot_user_panel(g, eps_u, frow, out_dir / f"{rank:02d}_{safe}.png", cfg)
        drawn += 1
    return drawn


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def generate_all(
    df_ts: pd.DataFrame, labels: pd.DataFrame, episodes: pd.DataFrame,
    enrich: pd.DataFrame, funnel: Dict[str, int], fig_dir: Path, cfg=DEFAULT_CONFIG,
) -> None:
    fig_dir = Path(fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    plot_funnel(funnel, fig_dir / "funnel_counts.png")
    plot_label_counts(labels, fig_dir / "label_counts.png")
    plot_opportunity_vs_response(labels, fig_dir / "opportunity_vs_response.png")
    plot_flat_tail_vs_tail_cycles(labels, fig_dir / "flat_tail_vs_tail_cycles.png")
    plot_hardware_enrichment_fw(enrich, fig_dir / "hardware_enrichment_fw_check.png")
    ng = plot_top_examples(df_ts, labels, episodes, LABEL_GAUGE, "gauge_reset_score_0_100",
                           fig_dir / "examples_gauge_reset_top20", 20, cfg)
    nf = plot_top_examples(df_ts, labels, episodes, LABEL_FW, "fw_check_score_0_100",
                           fig_dir / "examples_fw_check_top20", 20, cfg)
    print(f"  figures -> {fig_dir} (gauge examples={ng}, fw examples={nf})")


def main() -> None:
    cfg = load_config()
    pd_dir = cfg.processed_dir
    labels = pd.read_csv(pd_dir / "fcc_learning_user_features.csv")
    episodes = pd.read_csv(pd_dir / "fcc_learning_episodes.csv", parse_dates=[
        "start_ts", "low_ts", "end_ts"])
    enrich = pd.read_csv(pd_dir / "fcc_action_enrichment_by_hardware.csv")
    df_ts = pd.read_parquet(cfg.processed_dir / "battery_timeseries_all.parquet", columns=_TS_COLS)
    funnel = {
        "all_users": int(labels["user_id"].nunique()),
        "candidates": int(labels["fcc_no_or_low_change_candidate"].sum()),
        "no_opportunity": int((labels["final_label"] == LABEL_GAUGE).sum()),
        "has_opportunity": int((labels["final_label"] == LABEL_FW).sum()),
        "watch": int((labels["final_label"] == "WATCH_LOW_UPDATE_RATE_AMBIGUOUS").sum()),
    }
    generate_all(df_ts, labels, episodes, enrich, funnel, cfg.figures_dir / "fcc_action", DEFAULT_CONFIG)


if __name__ == "__main__":
    main()
