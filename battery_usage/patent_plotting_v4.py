"""Patent evidence v4 -- figures (all dpi=300, anonymous; no user_id/serial/UUID).

Each figure is rendered from the produced v4 aggregate CSV/parquet files. Robust:
a missing input is skipped with a notice rather than crashing the pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import patent_common_v4 as pc

DPI = 300


def _save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def _read(p: Path, parquet=False):
    if not p.exists():
        return None
    return pd.read_parquet(p) if parquet else pd.read_csv(p)


def fig_negative_control(in_dir: Path, fig_dir: Path):
    s = _read(in_dir / "negative_control_summary.csv")
    rep = _read(in_dir / "negative_control_replicates.parquet", parquet=True)
    if s is None:
        return
    d = s[s["metric"] == "resp_prob_72h"]
    fig, ax = plt.subplots(figsize=(7, 4))
    x = np.arange(len(d))
    ax.bar(x, d["control_mean"], yerr=[d["control_mean"] - d["control_ci_lo"],
                                       d["control_ci_hi"] - d["control_mean"]],
           color="#9ecae1", capsize=4, label="control null (95% CI)")
    ax.axhline(d["true_value"].iloc[0], color="#d62728", lw=2, label="true (observed)")
    ax.set_xticks(x); ax.set_xticklabels(d["control"], rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("response prob 72h"); ax.set_title("A2: true vs negative-control response (END-anchored)")
    ax.legend(fontsize=8)
    _save(fig, fig_dir / "negative_control_true_vs_null.png")

    if rep is not None:
        fig, ax = plt.subplots(figsize=(7, 4))
        for ctrl in rep["control"].unique():
            v = rep[rep["control"] == ctrl]["resp_prob_72h"]
            ax.hist(v, bins=30, alpha=0.45, label=ctrl)
        ax.axvline(d["true_value"].iloc[0], color="#d62728", lw=2, label="true")
        ax.set_xlabel("response prob 72h (control replicate)"); ax.set_ylabel("count")
        ax.set_title("A2: randomization distribution"); ax.legend(fontsize=7)
        _save(fig, fig_dir / "negative_control_randomization_distribution.png")


def fig_anchor(in_dir: Path, fig_dir: Path):
    c = _read(in_dir / "response_anchor_comparison.csv")
    if c is not None:
        d = c[c["window_h"] == 72]
        fig, ax = plt.subplots(figsize=(6.5, 4))
        x = np.arange(len(d))
        ax.bar(x - 0.2, d["frac_steps_before_completion"], 0.4, label="contamination (pre-completion)", color="#d62728")
        ax.bar(x + 0.2, d["duplicate_attribution_rate"], 0.4, label="duplicate attribution", color="#9467bd")
        ax.set_xticks(x); ax.set_xticklabels(d["anchor"])
        ax.set_ylabel("fraction"); ax.set_title("A3: causal contamination by response anchor (72h)")
        ax.legend(fontsize=8)
        _save(fig, fig_dir / "response_anchor_contamination.png")
    dd = _read(in_dir / "response_anchor_delay_cdf_data.csv")
    if dd is not None and len(dd):
        fig, ax = plt.subplots(figsize=(6.5, 4))
        for anc in dd["anchor"].unique():
            v = np.sort(dd[dd["anchor"] == anc]["delay_h"].to_numpy())
            ax.plot(v, np.linspace(0, 1, len(v)), label=anc)
        ax.set_xlabel("time to first effective step (h)"); ax.set_ylabel("CDF")
        ax.set_xlim(0, 168); ax.set_title("A3: response-delay CDF by anchor"); ax.legend(fontsize=8)
        _save(fig, fig_dir / "response_anchor_delay_cdf.png")


def fig_hazard(in_dir: Path, fig_dir: Path):
    cur = _read(in_dir / "response_hazard_curves.parquet", parquet=True)
    if cur is None:
        return
    for group, fname, title in [
        ("true_vs_pseudo", "response_hazard_true_vs_pseudo.png", "B: response CIF true vs matched pseudo"),
        ("quality_tier", "response_hazard_by_quality.png", "B: response CIF by gap quality tier"),
        ("threshold", "response_hazard_by_threshold.png", "B: response CIF by effective-step threshold"),
    ]:
        g = cur[cur["group"] == group]
        if g.empty:
            continue
        fig, ax = plt.subplots(figsize=(6.5, 4))
        for key in g["key"].unique():
            k = g[g["key"] == key]
            ax.plot(k["time_h"], k["cif"], label=str(key), lw=1.5)
        ax.set_xlabel("hours since episode end"); ax.set_ylabel("cumulative response incidence")
        ax.set_xlim(0, 168); ax.set_title(title); ax.legend(fontsize=7)
        _save(fig, fig_dir / fname)


def fig_dual_track(in_dir: Path, fig_dir: Path):
    a = _read(in_dir / "dual_track_reset_ablation.csv")
    if a is None:
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(a))
    ax.bar(x - 0.2, a["confirmed_no_response"], 0.4, label="confirmed no-response retained", color="#2ca02c")
    ax.bar(x + 0.2, a["hard_action"], 0.4, label="hard-action prompts", color="#d62728")
    ax.set_xticks(x); ax.set_xticklabels(a["policy"], rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("count"); ax.set_title("C2: reset-semantics ablation (D0..D5)"); ax.legend(fontsize=8)
    _save(fig, fig_dir / "dual_track_reset_semantics.png")

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x, a["erased_no_response"], color="#ff7f0e", label="no-response evidence erased by micro step")
    ax.bar(x, a["erased_pending"], bottom=a["erased_no_response"], color="#8c564b",
           label="pending opportunities erased")
    ax.set_xticks(x); ax.set_xticklabels(a["policy"], rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("count erased"); ax.set_title("C2: evidence erased by symmetric vs asymmetric reset")
    ax.legend(fontsize=8)
    _save(fig, fig_dir / "dual_track_erased_evidence.png")


def fig_threshold(in_dir: Path, fig_dir: Path):
    steps = _read(pc.STEPS_CACHE, parquet=True)
    ms = _read(in_dir / "effective_threshold_model_selection.csv")
    if steps is not None:
        a = steps["abs_step"].to_numpy(); a = a[a > 0]
        fig, ax = plt.subplots(figsize=(6.5, 4))
        ax.hist(np.log10(a), bins=60, color="#9ecae1", density=True)
        if ms is not None:
            for _, r in ms.iterrows():
                if np.isfinite(r["threshold_mwh"]) and r["threshold_mwh"] > 0:
                    ax.axvline(np.log10(r["threshold_mwh"]), lw=1, ls="--",
                               label=f"{r['method']}={r['threshold_mwh']:.0f}mWh")
        ax.axvline(np.log10(50), color="k", lw=2, label="50 mWh (narrow)")
        ax.set_xlabel("log10 |FCC step| (mWh)"); ax.set_ylabel("density")
        ax.set_title("C3: FCC step magnitude distribution + candidate thresholds")
        ax.legend(fontsize=6)
        _save(fig, fig_dir / "effective_threshold_mixture_fit.png")
    sens = _read(in_dir / "effective_threshold_label_sensitivity.csv")
    if sens is not None:
        d = sens[sens["threshold_kind"] == "fixed_mwh"]
        fig, ax = plt.subplots(figsize=(6.5, 4))
        ax.plot(d["threshold"], d["frac_steps_micro"], "-o", label="frac steps micro", color="#1f77b4")
        ax.plot(d["threshold"], d["frac_users_no_effective_step"], "-s",
                label="frac users w/ no effective step", color="#d62728")
        ax.axvline(50, color="k", ls="--", lw=1)
        ax.set_xlabel("effective threshold (mWh)"); ax.set_ylabel("fraction")
        ax.set_title("C3: technical-effect curve vs threshold"); ax.legend(fontsize=8)
        _save(fig, fig_dir / "effective_threshold_technical_effect_curve.png")


def fig_retention(in_dir: Path, fig_dir: Path):
    grid = _read(in_dir / "retention_invariance_grid.parquet", parquet=True)
    if grid is not None:
        d = grid[(grid["response_window_h"] == 72) & (grid["gap_config"] == "ok_only")]
        piv = d.pivot_table(index="detector", columns="retention_days",
                            values="response_status_agreement", aggfunc="mean")
        fig, ax = plt.subplots(figsize=(7, 2.8))
        im = ax.imshow(piv.values, aspect="auto", cmap="RdYlGn", vmin=0.5, vmax=1.0)
        ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns)
        ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index)
        ax.set_xlabel("retention (days)"); ax.set_title("D: response-status agreement vs full history")
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                ax.text(j, i, f"{piv.values[i,j]:.2f}", ha="center", va="center", fontsize=7)
        fig.colorbar(im, ax=ax, fraction=0.05)
        _save(fig, fig_dir / "retention_invariance_heatmap.png")
        # storage vs equivalence
        fig, ax = plt.subplots(figsize=(6.5, 4))
        for det in d["detector"].unique():
            dd = d[d["detector"] == det].groupby("retention_days").agg(
                stor=("storage_ratio", "mean"), agr=("response_status_agreement", "mean")).reset_index()
            ax.plot(dd["stor"], dd["agr"], "-o", label=det)
        ax.set_xlabel("storage ratio (vs full raw)"); ax.set_ylabel("response agreement")
        ax.set_title("D: storage vs full-history equivalence"); ax.legend(fontsize=8)
        _save(fig, fig_dir / "storage_vs_equivalence.png")
    abl = _read(in_dir / "minimal_state_ablation.csv")
    if abl is not None:
        d = abl[abl["physical_episode_recall"].notna() & (abl["component_removed"] != "none")]
        if len(d):
            d = d.groupby("component_removed").agg(rec=("physical_episode_recall", "min"),
                                                   nrm=("no_response_mae", "max")).reset_index()
            fig, ax = plt.subplots(figsize=(6.5, 4))
            x = np.arange(len(d))
            ax.bar(x - 0.2, 1 - d["rec"], 0.4, label="recall loss", color="#d62728")
            ax.bar(x + 0.2, d["nrm"], 0.4, label="no-response MAE", color="#ff7f0e")
            ax.set_xticks(x); ax.set_xticklabels(d["component_removed"], rotation=20, ha="right", fontsize=8)
            ax.set_ylabel("invariant breakage"); ax.set_title("D: minimal-state necessity (component removed)")
            ax.legend(fontsize=8)
            _save(fig, fig_dir / "minimal_state_necessity.png")


def fig_missingness(in_dir: Path, fig_dir: Path):
    s = _read(in_dir / "missingness_stress_summary.csv")
    if s is None:
        return
    piv = s.pivot_table(index="regime", columns="detector", values="mean_false_no_response", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(8, 6))
    piv.plot(kind="barh", ax=ax, width=0.8)
    ax.set_xlabel("mean false confirmed no-response"); ax.set_title("E: false escalation by detector x regime")
    ax.legend(fontsize=7); ax.tick_params(axis="y", labelsize=6)
    _save(fig, fig_dir / "missingness_false_escalation.png")

    # quality-tier benefit: naive vs graded vs proposed (mean over regimes)
    agg = s.groupby("detector").agg(false=("mean_false_no_response", "mean"),
                                    missed=("mean_missed_no_response", "mean")).reset_index()
    fig, ax = plt.subplots(figsize=(6.5, 4))
    x = np.arange(len(agg))
    ax.bar(x - 0.2, agg["false"], 0.4, label="false no-response", color="#d62728")
    ax.bar(x + 0.2, agg["missed"], 0.4, label="missed no-response", color="#1f77b4")
    ax.set_xticks(x); ax.set_xticklabels(agg["detector"], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("mean count"); ax.set_title("E: quality-tier + censor-aware benefit"); ax.legend(fontsize=8)
    _save(fig, fig_dir / "missingness_quality_tier_benefit.png")

    # censor injection safety: truncation regimes
    tr = s[s["regime"].str.startswith("truncate")]
    if len(tr):
        piv2 = tr.pivot_table(index="regime", columns="detector", values="mean_false_no_response")
        fig, ax = plt.subplots(figsize=(6.5, 4))
        piv2.plot(kind="bar", ax=ax)
        ax.set_ylabel("false no-response under truncation/censoring")
        ax.set_title("E: censor-injection safety"); ax.legend(fontsize=7)
        _save(fig, fig_dir / "censor_injection_safety.png")


def fig_summary(in_dir: Path, fig_dir: Path):
    te = _read(in_dir / "patent_technical_effects_v4.csv")
    if te is not None:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        colors = ["#2ca02c" if x else "#d62728" for x in te["supported"]]
        y = np.arange(len(te))
        ax.barh(y, [1] * len(te), color=colors)
        ax.set_yticks(y); ax.set_yticklabels(te["endpoint"], fontsize=7)
        ax.set_xticks([]); ax.set_title("v4 independent technical-effect endpoints (green=supported)")
        _save(fig, fig_dir / "technical_effect_waterfall.png")
    es = _read(in_dir / "patent_evidence_strength_v4.csv")
    if es is not None:
        rank = {"STRONG": 3, "MEDIUM": 2, "WEAK": 1, "PROSPECTIVE": 1}
        es = es[es["family"].isin(["IC1", "IC2", "IC5", "IC6", "IC7", "IC8"])].copy()
        es["score"] = es["evidence_strength_v4"].map(lambda s: next(
            (v for k, v in rank.items() if k in str(s)), 1))
        fig, ax = plt.subplots(figsize=(6.5, 4))
        ax.bar(es["family"], es["score"], color="#1f77b4")
        ax.set_yticks([1, 2, 3]); ax.set_yticklabels(["WEAK/PROSP", "MEDIUM", "STRONG"])
        ax.set_title("v4 evidence strength by claim family")
        _save(fig, fig_dir / "evidence_strength_table.png")


def build_all(in_dir: Path, fig_dir: Path):
    in_dir = Path(in_dir); fig_dir = Path(fig_dir); fig_dir.mkdir(parents=True, exist_ok=True)
    for fn in (fig_negative_control, fig_anchor, fig_hazard, fig_dual_track, fig_threshold,
               fig_retention, fig_missingness, fig_summary):
        try:
            fn(in_dir, fig_dir)
        except Exception as ex:  # pragma: no cover
            print(f"[plot] {fn.__name__} skipped: {type(ex).__name__}: {ex}")
    print(f"[plot] figures -> {fig_dir} (dpi={DPI})")
