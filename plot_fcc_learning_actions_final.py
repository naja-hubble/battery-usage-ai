"""All threshold-justification / label / enrichment / ML figures for the FINAL classifier.

Every figure is saved at dpi=300, bbox_inches="tight" (spec section 4), under
``data/reports/figures/fcc_final_thresholds/``. CJK fonts are configured so the Japanese
captions render. Can be driven by the orchestrator (``generate_all`` / ``generate_ml``
with in-memory frames) or standalone from the written CSVs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from battery_usage.config import load_config
from battery_usage.fcc_final import LABEL_ORDER, LABEL_COLORS, LABEL_FW, LABEL_GAUGE
from battery_usage.fcc_action_classifier import active_reference_mask


def _use_cjk_font() -> None:
    avail = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Yu Gothic", "Meiryo", "MS Gothic", "BIZ UDGothic", "Noto Sans CJK JP"):
        if cand in avail:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False


_use_cjk_font()
DPI = 300


def _save(fig, path: Path, dpi: int = DPI) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# threshold-justification figures
# --------------------------------------------------------------------------- #
def plot_reference_update_rate(feat: pd.DataFrame, col: str, path: Path, dpi=DPI) -> None:
    ref = feat[active_reference_mask(feat)][col].replace([np.inf, -np.inf], np.nan).dropna()
    cand = feat[feat["fcc_no_or_low_change_candidate"]][col].replace([np.inf, -np.inf], np.nan).dropna()
    norm = feat[~feat["fcc_no_or_low_change_candidate"]][col].replace([np.inf, -np.inf], np.nan).dropna()
    p05, p10 = np.percentile(ref, 5), np.percentile(ref, 10)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    hi = float(np.nanpercentile(np.concatenate([ref.values, norm.values]), 98)) if len(ref) else 1.0
    bins = np.linspace(0, max(hi, p10 * 2 + 1), 40)
    for d, lab, c in [(ref, "active reference", "steelblue"), (norm, "normal/responding", "green"),
                      (cand, "no/low候補", "darkred")]:
        if len(d):
            a1.hist(d.clip(upper=bins[-1]), bins=bins, alpha=0.45, label=lab, color=c, density=True)
    for x, lb in [(p05, f"p05={p05:.2f}"), (p10, f"p10={p10:.2f}")]:
        a1.axvline(x, color="black", ls="--", lw=1); a1.text(x, a1.get_ylim()[1]*0.9, lb, fontsize=7, rotation=90)
    a1.set_title(f"{col} 分布 (active ref基準)"); a1.set_xlabel(col); a1.legend(fontsize=7)
    for d, lab, c in [(ref, "active reference", "steelblue"), (cand, "no/low候補", "darkred")]:
        if len(d):
            xs = np.sort(d.values); ys = np.arange(1, len(xs)+1)/len(xs)
            a2.plot(xs, ys, label=lab, color=c)
    a2.axvline(p05, color="black", ls="--", lw=1); a2.axvline(p10, color="gray", ls=":", lw=1)
    a2.set_xlim(0, bins[-1]); a2.set_title("ECDF"); a2.set_xlabel(col); a2.set_ylabel("ECDF"); a2.legend(fontsize=7)
    fig.suptitle(f"参照群の更新率分布と候補閾値 p05/p10 — {col}", fontsize=12)
    _save(fig, path, dpi)


def plot_flat_tail_distribution(feat: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8))
    bins = np.linspace(0, float(np.nanpercentile(feat["flat_tail_days"], 99)) + 1, 50)
    for lab in LABEL_ORDER:
        d = feat.loc[feat["final_label"] == lab, "flat_tail_days"].dropna()
        if len(d):
            ax.hist(d.clip(upper=bins[-1]), bins=bins, alpha=0.55, label=lab.split("_")[0], color=LABEL_COLORS[lab])
    for x in (60, 120, 180):
        ax.axvline(x, color="black", ls="--", lw=1); ax.text(x, ax.get_ylim()[1]*0.92, f"{x}d", fontsize=8)
    ax.set_xlabel("flat_tail_days"); ax.set_ylabel("users"); ax.legend(fontsize=7)
    ax.set_title("flat_tail_days 分布（最終ラベル別）と 60/120/180日閾値")
    _save(fig, path, dpi)


def plot_sensitivity_counts(df: pd.DataFrame, title: str, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.6))
    labs = [c for c in df.columns if c.startswith("n_") and c != "n_candidates"]
    x = np.arange(len(df)); width = 0.8/len(labs)
    colmap = {"n_review": "lightgray", "n_normal": "steelblue", "n_fw_check": "darkred",
              "n_gauge_reset": "darkorange", "n_watch": "gold"}
    for i, c in enumerate(labs):
        ax.bar(x + i*width, df[c].values, width, label=c.replace("n_", ""), color=colmap.get(c, None))
    ax.set_xticks(x + width*len(labs)/2)
    ax.set_xticklabels([str(v) for v in df["variant"]], fontsize=8)
    ax.set_xlabel(df["dimension"].iloc[0] if "dimension" in df else "variant")
    ax.set_ylabel("users"); ax.legend(fontsize=7); ax.set_title(title)
    _save(fig, path, dpi)


def plot_response_delay_cdf(per_ep: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    for name, c in [("strict_90_10_90", "green"), ("primary_80_20_80", "darkred"),
                    ("secondary_85_15_85", "orange")]:
        d = per_ep.loc[per_ep["threshold_name"] == name, "response_delay_h"].dropna()
        d = d[d >= 0]
        if len(d):
            xs = np.sort(d.values); ys = np.arange(1, len(xs)+1)/len(xs)
            ax.plot(xs, ys, label=f"{name} (n={len(xs)})", color=c)
    for x in (24, 72, 168):
        ax.axvline(x, color="black", ls="--", lw=1); ax.text(x, 0.05, f"{x}h", fontsize=8, rotation=90)
    ax.set_xscale("symlog"); ax.set_xlabel("episode end からの応答遅延 (h)"); ax.set_ylabel("CDF")
    ax.set_title("FCC応答遅延CDF（応答したOK episode）と 24/72/168h"); ax.legend(fontsize=8)
    _save(fig, path, dpi)


def plot_learning_tradeoff(tr: pd.DataFrame, path1: Path, path2: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.6))
    x = np.arange(len(tr))
    ax.bar(x-0.2, tr["n_ok"], 0.4, label="n_ok", color="steelblue")
    ax.bar(x+0.2, tr["n_large_gap"], 0.4, label="n_large_gap", color="lightgray")
    ax2 = ax.twinx(); ax2.plot(x, tr["ok_response_rate_72h"], "o-", color="darkred", label="ok_response_rate_72h")
    ax.set_xticks(x); ax.set_xticklabels(tr["threshold_name"], fontsize=8)
    ax.set_ylabel("episodes"); ax2.set_ylabel("ok_response_rate_72h", color="darkred"); ax2.set_ylim(0, 1)
    ax.legend(loc="upper left", fontsize=7); ax2.legend(loc="upper right", fontsize=7)
    ax.set_title("学習機会閾値トレードオフ（episode数 / 応答率）")
    _save(fig, path1, dpi)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.bar(x-0.2, tr["n_users_with_tail_opportunities"], 0.4, label="users_with_tail_opp", color="teal")
    ax.bar(x+0.2, tr["n_fw_check_if_used_as_primary"], 0.4, label="fw_if_primary", color="darkred")
    ax.set_xticks(x); ax.set_xticklabels(tr["threshold_name"], fontsize=8)
    ax.set_ylabel("users"); ax.legend(fontsize=7)
    ax.set_title("学習機会閾値: ユーザーcoverage vs FW該当数")
    _save(fig, path2, dpi)


def plot_no_response_k(kdf: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(kdf["k"], kdf["p_no_response_theory"], "s--", label="理論 (1-p)^k", color="gray")
    ax.plot(kdf["k"], kdf["p_no_response_bootstrap"], "o-", label="user-level bootstrap", color="darkred")
    if "boot_ci_lo" in kdf:
        ax.fill_between(kdf["k"], kdf["boot_ci_lo"], kdf["boot_ci_hi"], color="darkred", alpha=0.15, label="bootstrap 95%CI")
    ax.axhline(0.05, color="black", ls=":", lw=1); ax.text(kdf["k"].max(), 0.06, "5% proxy", fontsize=8, ha="right")
    ax.set_xlabel("k 連続無応答 (complete OK episodes)"); ax.set_ylabel("P(全て無応答)")
    ax.set_title("無応答エピソード数 k の経験確率（FW閾値根拠）"); ax.legend(fontsize=8)
    _save(fig, path, dpi)


def plot_tail_cycle_distribution(feat: pd.DataFrame, path: Path, path2: Path, dpi=DPI) -> None:
    cand = feat[feat["fcc_no_or_low_change_candidate"]]["tail_cycle_delta"].replace([np.inf,-np.inf],np.nan).dropna()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    if len(cand):
        ax.hist(cand.clip(upper=float(np.nanpercentile(cand,99))+1), bins=40, color="darkorange", alpha=0.7)
    for x in (20, 30, 50):
        ax.axvline(x, color="black", ls="--", lw=1); ax.text(x, ax.get_ylim()[1]*0.9, f"{x}", fontsize=8)
    ax.set_xlabel("tail_cycle_delta (候補)"); ax.set_ylabel("users")
    ax.set_title("候補ユーザーの tail_cycle_delta 分布と 20/30/50閾値")
    _save(fig, path, dpi)
    ref = feat[active_reference_mask(feat)]
    cu = (ref["cycle_delta"]/ref["fcc_changes"].replace(0,np.nan)).replace([np.inf,-np.inf],np.nan).dropna()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    if len(cu):
        ax.hist(cu.clip(upper=float(np.nanpercentile(cu,95))+1), bins=40, color="steelblue", alpha=0.7)
        ax.axvline(np.median(cu), color="black", ls="--", lw=1)
        ax.text(np.median(cu), ax.get_ylim()[1]*0.9, f"median={np.median(cu):.1f}", fontsize=8)
    ax.set_xlabel("cycles per FCC update (active ref)"); ax.set_ylabel("users")
    ax.set_title("active reference: FCC更新間のサイクル数")
    _save(fig, path2, dpi)


def plot_ac_distribution(feat: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.6))
    cand = feat[feat["fcc_no_or_low_change_candidate"]]["tail_ac_time_ratio"].dropna()
    ref = feat[active_reference_mask(feat)]["tail_ac_time_ratio"].dropna()
    bins = np.linspace(0, 1, 40)
    if len(ref): ax.hist(ref, bins=bins, alpha=0.5, label="active ref", color="steelblue", density=True)
    if len(cand): ax.hist(cand, bins=bins, alpha=0.5, label="no/low候補", color="darkred", density=True)
    for x in (0.70, 0.80, 0.90):
        ax.axvline(x, color="black", ls="--", lw=1); ax.text(x, ax.get_ylim()[1]*0.9, f"{x}", fontsize=7)
    ax.set_xlabel("tail_ac_time_ratio"); ax.set_ylabel("density"); ax.legend(fontsize=8)
    ax.set_title("AC-bound 閾値 0.80（感度 0.70/0.90）")
    _save(fig, path, dpi)


def plot_shallow_range(feat: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 6))
    for lab in LABEL_ORDER:
        m = feat["final_label"] == lab
        if m.any():
            ax.scatter(feat.loc[m, "tail_min_rsoc"], feat.loc[m, "tail_rsoc_swing"], s=18, alpha=0.6,
                       color=LABEL_COLORS[lab], label=lab.split("_")[0])
    ax.axvline(20, color="black", ls="--", lw=1); ax.axhline(60, color="black", ls="--", lw=1)
    ax.set_xlabel("tail_min_rsoc (>20=浅い)"); ax.set_ylabel("tail_rsoc_swing (<60=浅い)")
    ax.set_title("shallow-range 定義 (min_rsoc>20 / swing<60)"); ax.legend(fontsize=7)
    _save(fig, path, dpi)


def plot_episode_gap(eps: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.6))
    g = eps["max_gap_h_in_episode"].replace([np.inf,-np.inf],np.nan).dropna()
    g = g[g <= float(np.nanpercentile(g, 99))]
    ax.hist(g, bins=60, color="purple", alpha=0.7)
    for x in (6, 12, 24):
        ax.axvline(x, color="black", ls="--", lw=1); ax.text(x, ax.get_ylim()[1]*0.9, f"{x}h", fontsize=8)
    ax.set_xlabel("max_gap_h_in_episode"); ax.set_ylabel("episodes")
    ax.set_title("episode内最大サンプル間隔の分布と 6/12/24h")
    _save(fig, path, dpi)


def plot_large_gap_audit(feat: pd.DataFrame, path: Path, dpi=DPI) -> None:
    cand = feat[feat["fcc_no_or_low_change_candidate"]]
    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.scatter(cand["tail_n_80_20_80_ok"], cand["tail_n_80_20_80_large_gap"], s=22, alpha=0.6,
               c=[LABEL_COLORS[l] for l in cand["final_label"]])
    ax.set_xlabel("tail_n_80_20_80_ok"); ax.set_ylabel("tail_n_80_20_80_large_gap")
    ax.set_title("large-gap機会の監査（候補ユーザー・最終ラベル色）")
    _save(fig, path, dpi)


def plot_effective_step(ed: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8))
    x = np.arange(len(ed))
    a1.bar(x, ed["median_fcc_changes"], color="steelblue")
    a1.set_xticks(x); a1.set_xticklabels(ed["step_definition"], rotation=30, ha="right", fontsize=7)
    a1.set_ylabel("median fcc_changes"); a1.set_title("有効ステップ定義 vs 中央FCC更新回数")
    for c, col in [("n_candidates","black"),("n_fw_check","darkred"),("n_gauge_reset","darkorange"),("n_watch","gold")]:
        if c in ed: a2.plot(x, ed[c], "o-", label=c.replace("n_",""), color=col)
    a2.set_xticks(x); a2.set_xticklabels(ed["step_definition"], rotation=30, ha="right", fontsize=7)
    a2.set_ylabel("users"); a2.legend(fontsize=7); a2.set_title("有効ステップ定義 vs ラベル件数")
    fig.suptitle("effective FCC step 感度分析 (spec 1.6)", fontsize=12)
    _save(fig, path, dpi)


def plot_final_scatters(labels: pd.DataFrame, path1: Path, path2: Path, dpi=DPI) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    s = (labels["flat_tail_days"].fillna(0)/180*40+8).clip(8, 80)
    for lab in LABEL_ORDER:
        m = labels["final_label"] == lab
        if m.any():
            ax.scatter(labels.loc[m, "tail_n_unresponded_80_20_80_complete_window"], labels.loc[m, "tail_cycle_delta"],
                       s=s[m], alpha=0.6, color=LABEL_COLORS[lab], label=lab.split("_")[0])
    ax.set_xlabel("tail_n_unresponded_80_20_80_complete_window"); ax.set_ylabel("tail_cycle_delta")
    ax.set_title("無応答(完全窓)機会数 vs tail_cycle（size=flat_tail）"); ax.legend(fontsize=7)
    _save(fig, path1, dpi)
    fig, ax = plt.subplots(figsize=(8, 6))
    s = (labels["tail_cycle_delta"].fillna(0)/50*40+8).clip(8, 80)
    for lab in LABEL_ORDER:
        m = labels["final_label"] == lab
        if m.any():
            ax.scatter(labels.loc[m, "tail_n_80_20_80_ok"], labels.loc[m, "flat_tail_days"],
                       s=s[m], alpha=0.6, color=LABEL_COLORS[lab], label=lab.split("_")[0])
    ax.set_xlabel("tail_n_80_20_80_ok"); ax.set_ylabel("flat_tail_days")
    ax.set_title("OK機会数 vs flat_tail（size=tail_cycle）"); ax.legend(fontsize=7)
    _save(fig, path2, dpi)


def plot_label_transition(baseline: pd.DataFrame, final: pd.DataFrame, mapping: pd.DataFrame,
                          path: Path, dpi=DPI) -> None:
    m = baseline[["user_id", "final_label"]].rename(columns={"final_label": "baseline"}) \
        .merge(final[["user_id", "final_label"]].rename(columns={"final_label": "final"}), on="user_id")
    ct = pd.crosstab(m["baseline"], m["final"])
    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(ct.values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels([c[:18] for c in ct.columns], rotation=30, ha="right", fontsize=7)
    ax.set_yticks(range(len(ct.index))); ax.set_yticklabels([c[:22] for c in ct.index], fontsize=7)
    for i in range(len(ct.index)):
        for j in range(len(ct.columns)):
            ax.text(j, i, ct.values[i, j], ha="center", va="center", fontsize=8,
                    color="white" if ct.values[i, j] > ct.values.max()/2 else "black")
    ax.set_title("ラベル遷移: baseline → final"); fig.colorbar(im, ax=ax, fraction=0.04)
    _save(fig, path, dpi)


def plot_review_subgroups(labels: pd.DataFrame, path: Path, dpi=DPI) -> None:
    rv = labels[labels["final_label"].str.startswith("REVIEW")]
    vc = rv.groupby(["review_subreason", "review_priority"]).size().unstack(fill_value=0)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    vc.plot(kind="barh", stacked=True, ax=ax, color={"high":"darkred","medium":"orange","low":"gold"})
    ax.set_xlabel("users"); ax.set_title("REVIEW サブグループ × 優先度"); ax.legend(title="priority", fontsize=7)
    _save(fig, path, dpi)


def plot_funnel(funnel: Dict[str, int], path: Path, dpi=DPI) -> None:
    stages = [("全ユーザー", funnel["all_users"], "lightgray"), ("no/low候補", funnel["candidates"], "tab:blue"),
              ("gauge_reset", funnel["gauge_reset"], LABEL_COLORS[LABEL_GAUGE]),
              ("fw_check", funnel["fw_check"], LABEL_COLORS[LABEL_FW]), ("watch", funnel["watch"], "gold")]
    fig, ax = plt.subplots(figsize=(8, 4.2)); ys = list(range(len(stages)))[::-1]
    for y, (lb, v, c) in zip(ys, stages):
        ax.barh(y, v, color=c, edgecolor="black", lw=0.5); ax.text(v, y, f" {v}", va="center", fontweight="bold")
    ax.set_yticks(ys); ax.set_yticklabels([s[0] for s in stages]); ax.set_xlabel("users")
    ax.set_title("最終介入ファネル")
    _save(fig, path, dpi)


def plot_label_counts(labels: pd.DataFrame, path: Path, dpi=DPI) -> None:
    vc = labels["final_label"].value_counts().reindex(LABEL_ORDER).fillna(0).astype(int)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    b = ax.bar(range(len(vc)), vc.values, color=[LABEL_COLORS[k] for k in vc.index], edgecolor="black", lw=0.5)
    ax.bar_label(b, fontweight="bold")
    ax.set_xticks(range(len(vc))); ax.set_xticklabels([k.replace("_","\n") for k in vc.index], fontsize=6)
    ax.set_ylabel("users"); ax.set_title(f"最終ラベル件数（合計 {int(vc.sum())}・相互排他）")
    _save(fig, path, dpi)


def plot_eb_enrichment(eb: pd.DataFrame, path: Path, dpi=DPI) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax, gt in zip(axes, ["device_model", "batt_vendor", "batt_fru"]):
        sub = eb[(eb["group_type"] == gt) & (eb["n_total"] >= 5)].sort_values("shrunk_fw_check_rate", ascending=False).head(12)
        if sub.empty:
            ax.axis("off"); ax.set_title(f"{gt}: n<5"); continue
        y = list(range(len(sub)))[::-1]
        ax.barh(y, sub["shrunk_fw_check_rate"], color="darkred", alpha=0.6, label="shrunk")
        ax.errorbar(sub["shrunk_fw_check_rate"], y,
                    xerr=[sub["shrunk_fw_check_rate"]-sub["fw_check_ci_low"], sub["fw_check_ci_high"]-sub["shrunk_fw_check_rate"]],
                    fmt="none", ecolor="black", elinewidth=0.8, capsize=2)
        ax.scatter(sub["raw_fw_check_rate"], y, color="black", s=14, label="raw", zorder=5)
        for yi, (_, r) in zip(y, sub.iterrows()):
            ax.text(0, yi, f" {int(r['n_fw_check'])}/{int(r['n_total'])}", fontsize=6, va="center")
        ax.set_yticks(y); ax.set_yticklabels([str(v).replace("ThinkPad ","")[:20] for v in sub["value"]], fontsize=7)
        ax.set_xlabel("fw_check率"); ax.set_title(f"{gt} (EB shrink + 95%CI)"); ax.legend(fontsize=6)
    fig.suptitle("FW確認対象のHW偏在（Empirical Bayes shrinkage・分類には不使用）", fontsize=13)
    _save(fig, path, dpi)


def plot_fru_case_control(labels: pd.DataFrame, fru: str, path: Path, dpi=DPI) -> bool:
    if "batt_fru" not in labels or fru not in set(labels["batt_fru"].dropna()):
        return False
    ing = labels[labels["batt_fru"] == fru]; out = labels[labels["batt_fru"] != fru]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    rows = []
    for lab in LABEL_ORDER:
        rows.append((lab.split("_")[0], (ing["final_label"] == lab).mean(), (out["final_label"] == lab).mean()))
    r = pd.DataFrame(rows, columns=["label", "in_fru", "rest"]); x = np.arange(len(r))
    ax.bar(x-0.2, r["in_fru"], 0.4, label=f"{fru} (n={len(ing)})", color="darkred")
    ax.bar(x+0.2, r["rest"], 0.4, label=f"その他 (n={len(out)})", color="gray")
    ax.set_xticks(x); ax.set_xticklabels(r["label"], fontsize=7); ax.set_ylabel("share"); ax.legend(fontsize=8)
    ax.set_title(f"FRU {fru} case-control（分類には不使用）")
    _save(fig, path, dpi); return True


# --------------------------------------------------------------------------- #
# ML figures (need model artifacts in memory)
# --------------------------------------------------------------------------- #
def plot_ml_figures(model: dict, residuals: pd.DataFrame, labels: pd.DataFrame, fig_dir: Path, dpi=DPI) -> None:
    from sklearn.metrics import roc_curve, precision_recall_curve
    preds = model["predictions"]; y = preds["fcc_changed_72h"].to_numpy(); p = preds["pred_response_prob"].to_numpy()
    fpr, tpr, _ = roc_curve(y, p); prec, rec, _ = precision_recall_curve(y, p)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.8))
    a1.plot(fpr, tpr); a1.plot([0,1],[0,1],"k--",lw=0.7); a1.set_xlabel("FPR"); a1.set_ylabel("TPR"); a1.set_title("ROC")
    a2.plot(rec, prec); a2.set_xlabel("recall"); a2.set_ylabel("precision"); a2.set_title("PR")
    m = model["metrics"].iloc[0]
    fig.suptitle(f"episode応答モデル ({model['best_model']}) AUC={m['roc_auc']} PR={m['pr_auc']} Brier={m['brier']}")
    _save(fig, fig_dir / "ml_response_model_roc_pr.png", dpi)
    # calibration
    fig, ax = plt.subplots(figsize=(6, 6))
    for name, (mp, ob) in model["calibration"].items():
        ax.plot(mp, ob, "o-", label=name)
    ax.plot([0,1],[0,1],"k--",lw=0.7); ax.set_xlabel("predicted"); ax.set_ylabel("observed"); ax.legend(fontsize=8)
    ax.set_title("calibration / reliability"); _save(fig, fig_dir / "ml_response_model_calibration.png", dpi)
    # coefficients
    co = model["coefficients"].head(15)
    fig, ax = plt.subplots(figsize=(8, 5.5)); yy = range(len(co))[::-1]
    ax.barh(list(yy), co["coef"], color=["darkred" if c<0 else "steelblue" for c in co["coef"]])
    ax.set_yticks(list(yy)); ax.set_yticklabels(co["feature"], fontsize=7); ax.axvline(0, color="black", lw=0.6)
    ax.set_title("LR係数 (標準化, |coef|上位15)"); _save(fig, fig_dir / "ml_response_model_coefficients.png", dpi)
    # expected vs observed
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    rr = residuals.merge(labels[["user_id","final_label"]], on="user_id", how="left")
    for lab in LABEL_ORDER:
        mm = rr["final_label"] == lab
        if mm.any():
            ax.scatter(rr.loc[mm,"expected_tail_responses_72h"], rr.loc[mm,"observed_tail_responses_72h"],
                       s=22, alpha=0.6, color=LABEL_COLORS[lab], label=lab.split("_")[0])
    lim = max(1, float(rr["expected_tail_responses_72h"].max())*1.05)
    ax.plot([0,lim],[0,lim],"k--",lw=0.7); ax.set_xlim(0,lim); ax.set_ylim(0,lim)
    ax.set_xlabel("expected tail responses (model)"); ax.set_ylabel("observed"); ax.legend(fontsize=7)
    ax.set_title("期待 vs 実測 tail応答（下回る=FW寄り）"); _save(fig, fig_dir / "ml_expected_vs_observed_tail_response.png", dpi)
    # residual by label
    fig, ax = plt.subplots(figsize=(8, 4.8))
    data = [rr.loc[rr["final_label"]==lab,"response_residual_z"].dropna().values for lab in LABEL_ORDER]
    ax.boxplot([d for d in data if len(d)], labels=[l.split("_")[0] for l,d in zip(LABEL_ORDER,data) if len(d)])
    ax.axhline(0, color="black", lw=0.6); ax.set_ylabel("response_residual_z")
    ax.set_title("応答残差z（最終ラベル別・shadow）"); _save(fig, fig_dir / "ml_residual_by_final_label.png", dpi)


def plot_cluster_figures(clusters: pd.DataFrame, feat: pd.DataFrame, fig_dir: Path, dpi=DPI) -> None:
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    from battery_usage.fcc_response_model import CLUSTER_FEATURES
    # feat may already carry cluster_id (orchestrator passes labels) or not (standalone CLI
    # passes user-features); merge only when needed to avoid _x/_y column collisions.
    if "cluster_id" in feat.columns:
        sub = feat.copy()
    else:
        sub = feat.merge(clusters[["user_id", "cluster_id", "cluster_description"]], on="user_id", how="inner")
    sub = sub[pd.to_numeric(sub["cluster_id"], errors="coerce").fillna(-1) >= 0].copy()
    if sub.empty or sub["cluster_id"].nunique() < 2:
        return
    X = sub[CLUSTER_FEATURES].replace([np.inf,-np.inf],np.nan)
    X = X.fillna(X.median(numeric_only=True))
    Xs = StandardScaler().fit_transform(X)
    pc = PCA(n_components=2).fit_transform(Xs)
    fig, ax = plt.subplots(figsize=(8, 6))
    for cid in sorted(sub["cluster_id"].unique()):
        m = sub["cluster_id"] == cid; desc = sub.loc[m,"cluster_description"].iloc[0]
        ax.scatter(pc[m.values,0], pc[m.values,1], s=22, alpha=0.6, label=f"{cid}:{desc}")
    ax.set_xlabel("PC1"); ax.set_ylabel("PC2"); ax.legend(fontsize=6); ax.set_title("WATCH/候補クラスタ (PCA)")
    _save(fig, fig_dir / "watch_candidate_cluster_pca.png", dpi)
    means = sub.groupby("cluster_id")[CLUSTER_FEATURES].mean()
    means_z = (means - X.mean()) / X.std(ddof=0).replace(0,1)
    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(means_z.values, cmap="coolwarm", aspect="auto", vmin=-2, vmax=2)
    ax.set_xticks(range(len(CLUSTER_FEATURES))); ax.set_xticklabels(CLUSTER_FEATURES, rotation=40, ha="right", fontsize=6)
    ax.set_yticks(range(len(means_z))); ax.set_yticklabels([f"{i}" for i in means_z.index])
    fig.colorbar(im, ax=ax, fraction=0.03); ax.set_title("クラスタ別 特徴量平均 (z)")
    _save(fig, fig_dir / "watch_candidate_cluster_feature_means.png", dpi)


def plot_surrogate_tree(surr: dict, fig_dir: Path, dpi=DPI) -> None:
    from sklearn.tree import plot_tree
    fig, ax = plt.subplots(figsize=(20, 9))
    plot_tree(surr["tree"], feature_names=surr["feature_names"], class_names=surr["tree"].classes_,
              filled=True, fontsize=7, ax=ax, impurity=False, proportion=True)
    ax.set_title(f"説明用サロゲート決定木 (depth=3, fidelity={surr['fidelity']})")
    _save(fig, fig_dir / "surrogate_decision_tree.png", dpi)


# --------------------------------------------------------------------------- #
# standalone CLI (re-plot from CSVs)
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="Re-plot final FCC threshold figures from CSVs")
    cfg = load_config()
    p.add_argument("--labels", default=str(cfg.processed_dir / "fcc_final_action_labels.csv"))
    p.add_argument("--user-features", default=str(cfg.processed_dir / "fcc_final_user_features.csv"))
    p.add_argument("--episodes", default=str(cfg.processed_dir / "fcc_final_learning_episodes.csv"))
    p.add_argument("--out-dir", default=str(cfg.figures_dir / "fcc_final_thresholds"))
    p.add_argument("--dpi", type=int, default=300)
    a = p.parse_args()
    fig_dir = Path(a.out_dir); fig_dir.mkdir(parents=True, exist_ok=True)
    feat = pd.read_csv(a.user_features)
    labels = pd.read_csv(a.labels)
    # the user-features file carries the candidate flag + final_label needed by the plots
    for c in ("final_label",):
        if c not in feat.columns and c in labels.columns:
            feat = feat.merge(labels[["user_id", c]], on="user_id", how="left")
    plot_label_counts(labels, fig_dir / "final_label_counts.png", a.dpi)
    plot_flat_tail_distribution(feat, fig_dir / "flat_tail_distribution_with_thresholds.png", a.dpi)
    plot_final_scatters(labels, fig_dir / "tail_unresponded_opportunities_vs_cycles_final.png",
                        fig_dir / "tail_opportunities_vs_flat_tail_final.png", a.dpi)
    print(f"re-plotted core figures to {fig_dir}")


if __name__ == "__main__":
    main()
