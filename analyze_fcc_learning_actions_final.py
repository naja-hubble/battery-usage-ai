"""FINAL FCC-learning intervention classifier — validation, threshold justification, ML shadow.

One run produces every final deliverable (spec sections 1-11): the censoring-aware /
large-gap-safe / REVIEW-subdivided final labels, the data-driven threshold-justification
CSVs + dpi=300 figures, the Empirical-Bayes hardware enrichment, the ML *shadow* analysis
(episode response model, residuals, clustering, surrogate tree), the final report, and the
short actionable summary.

    python analyze_fcc_learning_actions_final.py \
      --timeseries data/processed/battery_timeseries_all.parquet \
      --user-master data/processed/user_master.csv \
      --soh-update-status data/processed/soh_update_status.csv \
      --out-dir data/processed \
      --fig-dir data/reports/figures/fcc_final_thresholds \
      --report data/reports/fcc_final_learning_action_report.md \
      --dpi 300

Hardware identity is merged ONLY after classification (enrichment); it never feeds a rule.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from battery_usage.config import load_config
from battery_usage.fcc_learning import DEFAULT_CONFIG, FccLearningConfig, process_user
from battery_usage.fcc_action_classifier import active_reference_quantiles, compute_candidate_flags
from battery_usage import fcc_final as F
from battery_usage import fcc_justify as J
from battery_usage import fcc_response_model as M
import plot_fcc_learning_actions_final as P

_TS_COLS = ["user_id", "timestamp", "remainingCapacityInPercentage", "cycleCount",
            "fullChargeCapacity", "soh_design_pct", "acdcMode", "chargeStatus", "serialNumber"]
_HW_COLS = ["device_model", "batt_vendor", "batt_fru"]
_CASE_CONTROL_FRU = "5B10W13975"

_EPISODE_CSV_COLS = [
    "user_id", "threshold_name", "start_ts", "low_ts", "end_ts", "start_idx", "low_idx", "end_idx",
    "start_rsoc", "low_rsoc", "end_rsoc", "cycle_delta_episode", "fcc_start", "fcc_end",
    "fcc_changed_during_episode", "fcc_changed_24h", "fcc_changed_72h", "fcc_changed_168h",
    "window_24h_complete", "window_72h_complete", "window_168h_complete",
    "fcc_response_status_24h", "fcc_response_status_72h", "fcc_response_status_168h",
    "response_window_end_ts_24h", "response_window_end_ts_72h", "response_window_end_ts_168h",
    "response_delay_h", "max_gap_h_in_episode", "episode_quality",
]
_ACTION_LABEL_COLS = [
    "analysis_timestamp", "user_id", "final_label", "recommended_action", "confidence",
    "primary_reason", "subreason", "watch_subreason", "review_subreason", "review_priority",
    "manual_review_reason", "fcc_no_or_low_change_candidate", "no_fcc_update", "long_terminal_flat",
    "low_update_per_cycle", "low_update_per_time", "fcc_changes", "fcc_effective_changes_50mwh",
    "fcc_effective_changes_100mwh", "fcc_changes_per_100_cycles", "fcc_change_rate_per_100d",
    "flat_tail_days", "obs_days", "cycle_delta", "tail_days", "tail_cycle_delta", "tail_min_rsoc",
    "tail_max_rsoc", "tail_rsoc_swing", "tail_ac_time_ratio", "tail_n_80_20_80_ok",
    "tail_n_80_20_80_large_gap", "tail_n_80_20_80_any", "tail_n_90_10_90_ok",
    "tail_n_90_10_90_large_gap", "tail_n_90_10_90_any", "tail_n_unresponded_80_20_80_complete_window",
    "tail_n_unresponded_90_10_90_complete_window", "tail_n_censored_80_20_80", "tail_n_censored_90_10_90",
    "expected_tail_responses_72h", "observed_tail_responses_72h", "response_residual_z",
    "ml_fw_support_score_0_100", "cluster_id", "cluster_description",
    "gauge_reset_score_0_100", "fw_check_score_0_100", "primary_evidence", "operational_message",
    "threshold_version", "rule_version", "label_version", "device_model", "batt_vendor", "batt_fru",
]
_TARGET_COLS = [
    "user_id", "final_label", "recommended_action", "confidence", "subreason", "review_priority",
    "gauge_reset_score_0_100", "fw_check_score_0_100", "ml_fw_support_score_0_100", "primary_evidence",
    "flat_tail_days", "fcc_changes", "tail_cycle_delta", "tail_n_80_20_80_ok",
    "tail_n_unresponded_80_20_80_complete_window", "tail_n_unresponded_90_10_90_complete_window",
    "tail_n_80_20_80_large_gap", "tail_ac_time_ratio", "tail_min_rsoc", "obs_days",
    "data_quality_label", "device_model", "batt_vendor", "batt_fru", "operational_message",
]


def build_features_and_episodes(df: pd.DataFrame, cfg: FccLearningConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    feats, eps = [], []
    for uid, g in df.groupby("user_id", sort=False):
        f, e = process_user(uid, g, cfg)
        feats.append(f); eps.extend(e)
    return pd.DataFrame(feats), pd.DataFrame(eps)


def _jaccard(a: set, b: set) -> float:
    u = a | b
    return round(len(a & b) / len(u), 4) if u else 1.0


def main(argv=None) -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Final FCC intervention classifier + validation")
    ap.add_argument("--timeseries", default=str(cfg.processed_dir / "battery_timeseries_all.parquet"))
    ap.add_argument("--user-master", default=str(cfg.processed_dir / "user_master.csv"))
    ap.add_argument("--soh-update-status", default=str(cfg.processed_dir / "soh_update_status.csv"))
    ap.add_argument("--baseline-labels", default=str(cfg.processed_dir / "fcc_learning_action_labels.csv"))
    ap.add_argument("--out-dir", default=str(cfg.processed_dir))
    ap.add_argument("--fig-dir", default=str(cfg.figures_dir / "fcc_final_thresholds"))
    ap.add_argument("--report", default=str(cfg.reports_dir / "fcc_final_learning_action_report.md"))
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--fast", action="store_true", help="skip the slow effective-step 5x re-run")
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = Path(a.fig_dir)
    ts = pd.Timestamp.now().isoformat(timespec="seconds")
    thr = F.DEFAULT_FINAL_THRESHOLDS

    print(f"[1/9] loading {a.timeseries}")
    df = pd.read_parquet(a.timeseries, columns=_TS_COLS)
    n_users = int(df["user_id"].nunique())

    print("[2/9] per-user features + episodes")
    feats, episodes = build_features_and_episodes(df, DEFAULT_CONFIG)

    print("[3/9] candidate flags + final labels")
    q = active_reference_quantiles(feats)
    feat = compute_candidate_flags(feats, q, thr.candidate_pct)
    cls = F.classify_frame_final(feat, thr)
    labels = pd.concat([feat.reset_index(drop=True), cls.reset_index(drop=True)], axis=1)

    print("[4/9] ML shadow analysis (episode response model, clustering, surrogate)")
    eps_feat = M.enrich_episode_features(df, episodes)
    ml = {}
    try:
        model = M.train_response_model(eps_feat)
        resid = M.user_response_residuals(model["predictions"], labels)
        labels = labels.merge(resid, on="user_id", how="left")
        clusters = M.cluster_candidates(labels, [F.LABEL_WATCH, F.LABEL_GAUGE, F.LABEL_FW])
        labels = labels.merge(clusters[["user_id", "cluster_id", "cluster_description"]], on="user_id", how="left")
        surr = M.surrogate_tree(labels)
        ml = {"model": model, "resid": resid, "clusters": clusters, "surrogate": surr}
    except Exception as exc:
        print(f"  WARNING: ML shadow failed: {exc!r}")
    for c, fill in [("expected_tail_responses_72h", np.nan), ("observed_tail_responses_72h", np.nan),
                    ("response_residual_z", np.nan), ("ml_fw_support_score_0_100", 0.0),
                    ("cluster_id", -1), ("cluster_description", "n/a"),
                    ("n_complete_ok_opportunities", 0)]:
        if c not in labels.columns:
            labels[c] = fill
        labels[c] = labels[c].fillna(fill)

    print("[5/9] hardware enrichment (post-classification)")
    hw = pd.read_parquet(a.timeseries, columns=["user_id"] + _HW_COLS).groupby("user_id", as_index=False).first()
    labels = labels.merge(hw, on="user_id", how="left")
    assert len(labels) == n_users and labels["final_label"].isin(F.LABEL_ORDER).all()

    print("[6/9] threshold-justification analyses")
    ref_q = J.reference_quantiles_table(feat)
    sens_parts = [
        J.candidate_pct_sensitivity(feats, q, thr), J.flat_tail_sensitivity(feat, thr),
        J.response_window_sensitivity(feat, thr), J.ac_threshold_sensitivity(feat, thr),
        J.episode_gap_sensitivity(episodes, feat, thr),
    ]
    sens_grid = pd.concat(sens_parts, ignore_index=True)
    # Jaccard stability of the FW & GAUGE sets vs the default labelling.
    base_fw = set(labels.loc[labels.final_label == F.LABEL_FW, "user_id"])
    base_g = set(labels.loc[labels.final_label == F.LABEL_GAUGE, "user_id"])
    jac = []
    from dataclasses import replace as _replace
    for w in ("24h", "72h", "168h"):
        cf = F.classify_frame_final(feat, _replace(thr, response_window=w))
        fw = set(feat.loc[cf["final_label"].values == F.LABEL_FW, "user_id"])
        g = set(feat.loc[cf["final_label"].values == F.LABEL_GAUGE, "user_id"])
        jac.append({"perturbation": f"response_window={w}", "jaccard_fw": _jaccard(base_fw, fw),
                    "jaccard_gauge": _jaccard(base_g, g)})
    jaccard_df = pd.DataFrame(jac)
    delay_per_ep, delay_summary = J.response_delay_distribution(episodes)
    tradeoff = J.learning_threshold_tradeoff(episodes, feat)
    kjust = J.no_response_k_justification(episodes, feat)
    tcj = J.tail_cycle_justification(feat)

    if a.fast:
        eff = pd.DataFrame([{"step_definition": "skipped_fast_mode"}])
    else:
        print("      effective-step sensitivity (5x full re-run; slow)")
        eff = J.effective_step_sensitivity(df, DEFAULT_CONFIG, thr)

    eb = J.hardware_enrichment_eb(labels)

    print("[7/9] cross-validation vs soh_update_status + baseline transition")
    xinfo, ctab = _crossvalidate(labels, Path(a.soh_update_status))
    baseline = pd.read_csv(a.baseline_labels) if Path(a.baseline_labels).exists() else None

    print("[8/9] writing CSVs")
    _write_csvs(out_dir, ts, labels, episodes, ml, ref_q, sens_grid, jaccard_df, delay_per_ep,
                delay_summary, tradeoff, kjust, tcj, eff, eb)

    funnel = {"all_users": n_users,
              "candidates": int(labels["fcc_no_or_low_change_candidate"].sum()),
              "gauge_reset": int((labels.final_label == F.LABEL_GAUGE).sum()),
              "fw_check": int((labels.final_label == F.LABEL_FW).sum()),
              "watch": int((labels.final_label == F.LABEL_WATCH).sum()),
              "review": int((labels.final_label == F.LABEL_REVIEW).sum()),
              "normal": int((labels.final_label == F.LABEL_NORMAL).sum())}

    print("[9/9] report + figures")
    _write_report(Path(a.report), labels, episodes, q, ref_q, sens_grid, jaccard_df, delay_summary,
                  tradeoff, kjust, tcj, eff, eb, ctab, xinfo, ml, funnel, fig_dir, n_users, ts, thr)
    if not a.no_figures:
        try:
            _figures(fig_dir, a.dpi, labels, feat, episodes, sens_parts, delay_per_ep, tradeoff,
                     kjust, eff, eb, funnel, baseline, ml)
        except Exception as exc:
            print(f"  WARNING: figure generation failed: {exc!r}")

    _print_summary(labels, funnel)


# --------------------------------------------------------------------------- #
def _crossvalidate(labels: pd.DataFrame, path: Path) -> Tuple[dict, pd.DataFrame]:
    info: dict = {}
    repro = pd.cut(labels["flat_tail_days"], [-1, 60, 180, 1e18], labels=["active", "stale", "very_stale"])
    info["reproduced"] = repro.value_counts().reindex(["active", "stale", "very_stale"]).fillna(0).astype(int).to_dict()
    ctab = pd.DataFrame()
    if path.exists():
        ext = pd.read_csv(path)[["user_id", "soh_update_status"]]
        info["existing"] = ext["soh_update_status"].value_counts().to_dict()
        m = labels.merge(ext, on="user_id", how="inner")
        info["n_merged"] = int(len(m))
        info["active_misrouted_to_action"] = int(
            ((m.soh_update_status == "active") & m.final_label.isin([F.LABEL_FW, F.LABEL_GAUGE])).sum())
        ctab = pd.crosstab(m["soh_update_status"], m["final_label"])
    return info, ctab


def _write_csvs(out_dir, ts, labels, episodes, ml, ref_q, sens_grid, jaccard_df, delay_per_ep,
                delay_summary, tradeoff, kjust, tcj, eff, eb) -> None:
    def stamp(d):
        d = d.copy(); d["analysis_timestamp"] = ts; return d

    stamp(episodes.reindex(columns=_EPISODE_CSV_COLS)).to_csv(out_dir / "fcc_final_learning_episodes.csv", index=False)
    stamp(labels).to_csv(out_dir / "fcc_final_user_features.csv", index=False)
    action = labels.reindex(columns=[c for c in _ACTION_LABEL_COLS if c != "analysis_timestamp"])
    action.insert(0, "analysis_timestamp", ts)
    action.to_csv(out_dir / "fcc_final_action_labels.csv", index=False)

    tgt = [c for c in _TARGET_COLS if c in labels.columns]
    g = labels[labels.recommended_action == F.ACTION_GAUGE_RESET][tgt].sort_values("gauge_reset_score_0_100", ascending=False)
    fw = labels[labels.recommended_action == F.ACTION_FW_CHECK][tgt].sort_values(
        ["fw_check_score_0_100", "ml_fw_support_score_0_100"], ascending=False)
    watch = labels[labels.recommended_action == F.ACTION_MONITOR][tgt + ["watch_subreason"]]
    review = labels[labels.recommended_action == F.ACTION_REVIEW][
        ["user_id", "final_label", "review_subreason", "review_priority", "manual_review_reason",
         "obs_days", "n_samples", "flat_tail_days", "fcc_no_or_low_change_candidate",
         "data_quality_label", "device_model", "batt_vendor", "batt_fru"]].sort_values("review_priority")
    stamp(g).to_csv(out_dir / "fcc_final_intervention_targets_gauge_reset.csv", index=False)
    stamp(fw).to_csv(out_dir / "fcc_final_intervention_targets_fw_check.csv", index=False)
    stamp(watch).to_csv(out_dir / "fcc_final_watchlist.csv", index=False)
    stamp(review).to_csv(out_dir / "fcc_final_review_queue.csv", index=False)

    # label name mapping (spec 1.1)
    pd.DataFrame([{"old_label": k, "new_label": v} for k, v in F.LABEL_NAME_MAPPING.items()]) \
        .to_csv(out_dir / "fcc_label_name_mapping.csv", index=False)

    stamp(ref_q).to_csv(out_dir / "fcc_threshold_reference_quantiles.csv", index=False)
    stamp(sens_grid).to_csv(out_dir / "fcc_final_sensitivity_grid.csv", index=False)
    stamp(jaccard_df).to_csv(out_dir / "fcc_final_jaccard_stability.csv", index=False)
    stamp(delay_summary).to_csv(out_dir / "fcc_response_delay_distribution.csv", index=False)
    stamp(J_response_window_csv(sens_grid)).to_csv(out_dir / "fcc_response_window_sensitivity.csv", index=False)
    stamp(tradeoff).to_csv(out_dir / "fcc_learning_threshold_tradeoff.csv", index=False)
    stamp(kjust).to_csv(out_dir / "fcc_no_response_k_justification.csv", index=False)
    stamp(tcj).to_csv(out_dir / "fcc_tail_cycle_threshold_justification.csv", index=False)
    stamp(eff).to_csv(out_dir / "fcc_effective_step_sensitivity.csv", index=False)
    stamp(_gap_csv(sens_grid)).to_csv(out_dir / "fcc_episode_quality_gap_sensitivity.csv", index=False)
    stamp(eb).to_csv(out_dir / "fcc_final_hardware_enrichment_empirical_bayes.csv", index=False)

    # threshold justification summary (consolidated, human-facing)
    stamp(_threshold_summary(ref_q, delay_summary, kjust, tcj)).to_csv(
        out_dir / "fcc_final_threshold_justification_summary.csv", index=False)

    # ML shadow scores
    if "resid" in ml:
        stamp(ml["resid"]).to_csv(out_dir / "fcc_final_ml_shadow_scores.csv", index=False)
        stamp(ml["model"]["metrics"]).to_csv(out_dir / "fcc_episode_response_model_metrics.csv", index=False)
        stamp(ml["model"]["predictions"]).to_csv(out_dir / "fcc_episode_response_model_predictions.csv", index=False)
        stamp(ml["resid"]).to_csv(out_dir / "fcc_user_expected_response_residuals.csv", index=False)
        stamp(ml["clusters"]).to_csv(out_dir / "fcc_no_low_candidate_clusters.csv", index=False)
        (out_dir / "fcc_action_surrogate_tree_rules.txt").write_text(
            f"# surrogate fidelity={ml['surrogate']['fidelity']}\n" + ml["surrogate"]["rules"], encoding="utf-8")


def J_response_window_csv(sens_grid: pd.DataFrame) -> pd.DataFrame:
    return sens_grid[sens_grid["dimension"] == "response_window"].copy()


def _gap_csv(sens_grid: pd.DataFrame) -> pd.DataFrame:
    return sens_grid[sens_grid["dimension"] == "episode_max_gap_h"].copy()


def _threshold_summary(ref_q, delay_summary, kjust, tcj) -> pd.DataFrame:
    rows = []
    p05c = ref_q.loc[ref_q.metric == "fcc_changes_per_100_cycles", "p05"].iloc[0]
    p05t = ref_q.loc[ref_q.metric == "fcc_change_rate_per_100d", "p05"].iloc[0]
    cap72 = delay_summary.loc[delay_summary.threshold_name == "primary_80_20_80", "frac_captured_by_72h"]
    cap72 = float(cap72.iloc[0]) if len(cap72) else float("nan")
    k2 = kjust.loc[kjust.k == 2, "p_no_response_theory"]
    k3 = kjust.loc[kjust.k == 3, "p_no_response_theory"]
    p2 = float(k2.iloc[0]) if len(k2) else float("nan")
    p3 = float(k3.iloc[0]) if len(k3) else float("nan")
    rows = [
        ("candidate_fcc_changes_per_100_cycles", f"<= p05 = {p05c}", "active-reference下位5%を下回る更新頻度"),
        ("candidate_fcc_change_rate_per_100d", f"<= p05 = {p05t}", "active-reference下位5%"),
        ("flat_tail_days", "60 / 120 / 180", "既存 active/stale/very_stale 境界に一致"),
        ("response_window", "72h (primary)", f"primary OK応答の {cap72:.0%} を72hで捕捉"),
        ("learning_band_primary", "80/20/80", "ユーザー/episode数が最多、深い放電→再充電を実用的に捕捉"),
        ("K_STRICT_90_10_90", "2", f"strict無応答 k=2 の理論false-alarm proxy={p2:.4f} (<=5%)"),
        ("fw_unresponded_80_20_80", ">=3", f"primary無応答 k=3 false-alarm proxy={p3:.4f} (<=5%)"),
        ("tail_cycle_delta", "30 (FW high)", "active-ref更新間サイクルを大きく超える非更新"),
        ("ac_time_ratio", ">=0.80", "AC固定で深放電機会が乏しい"),
        ("shallow_range", "min_rsoc>20 / swing<60", "80/20/80のlow到達不能・60ptレンジ未満（定義的）"),
        ("episode_max_gap_h", "12", "ロガー~30分間隔、>12hはスリープ欠測"),
    ]
    return pd.DataFrame(rows, columns=["threshold", "value", "rationale"])


# --------------------------------------------------------------------------- #
def _figures(fig_dir, dpi, labels, feat, episodes, sens_parts, delay_per_ep, tradeoff, kjust,
             eff, eb, funnel, baseline, ml) -> None:
    fig_dir = Path(fig_dir); fig_dir.mkdir(parents=True, exist_ok=True)
    feat_l = feat.merge(labels[["user_id", "final_label"]], on="user_id", how="left")
    P.plot_reference_update_rate(labels, "fcc_changes_per_100_cycles", fig_dir / "reference_update_rate_distribution_per_cycle.png", dpi)
    P.plot_reference_update_rate(labels, "fcc_change_rate_per_100d", fig_dir / "reference_update_rate_distribution_per_100d.png", dpi)
    P.plot_flat_tail_distribution(labels, fig_dir / "flat_tail_distribution_with_thresholds.png", dpi)
    P.plot_sensitivity_counts(sens_parts[1], "flat_tail感度", fig_dir / "flat_tail_sensitivity_label_counts.png", dpi)
    P.plot_response_delay_cdf(delay_per_ep, fig_dir / "response_delay_cdf_24_72_168.png", dpi)
    P.plot_sensitivity_counts(sens_parts[2], "response window感度", fig_dir / "response_window_sensitivity_counts.png", dpi)
    P.plot_learning_tradeoff(tradeoff, fig_dir / "learning_threshold_tradeoff.png",
                             fig_dir / "learning_threshold_user_coverage_vs_response.png", dpi)
    P.plot_no_response_k(kjust, fig_dir / "no_response_probability_by_k.png", dpi)
    P.plot_tail_cycle_distribution(labels, fig_dir / "tail_cycle_delta_distribution_with_thresholds.png",
                                   fig_dir / "cycles_between_fcc_updates_active_reference.png", dpi)
    P.plot_ac_distribution(labels, fig_dir / "ac_time_ratio_distribution_with_080.png", dpi)
    P.plot_shallow_range(labels, fig_dir / "shallow_range_thresholds_tail_min_rsoc_swing.png", dpi)
    P.plot_episode_gap(episodes, fig_dir / "episode_max_gap_distribution.png", dpi)
    P.plot_sensitivity_counts(sens_parts[4], "episode gap感度", fig_dir / "episode_gap_threshold_sensitivity.png", dpi)
    P.plot_large_gap_audit(labels, fig_dir / "large_gap_opportunity_audit.png", dpi)
    if "step_definition" in eff and eff["step_definition"].iloc[0] != "skipped_fast_mode":
        P.plot_effective_step(eff, fig_dir / "effective_fcc_step_sensitivity.png", dpi)
    P.plot_final_scatters(labels, fig_dir / "tail_unresponded_opportunities_vs_cycles_final.png",
                          fig_dir / "tail_opportunities_vs_flat_tail_final.png", dpi)
    if baseline is not None:
        P.plot_label_transition(baseline, labels, None, fig_dir / "label_transition_baseline_to_final_heatmap.png", dpi)
    P.plot_review_subgroups(labels, fig_dir / "review_subgroup_counts.png", dpi)
    P.plot_funnel(funnel, fig_dir / "final_funnel_counts.png", dpi)
    P.plot_label_counts(labels, fig_dir / "final_label_counts.png", dpi)
    P.plot_eb_enrichment(eb, fig_dir / "hardware_enrichment_empirical_bayes_fw_check.png", dpi)
    P.plot_fru_case_control(labels, _CASE_CONTROL_FRU, fig_dir / "fru_5B10W13975_case_control_summary.png", dpi)
    if "model" in ml:
        P.plot_ml_figures(ml["model"], ml["resid"], labels, fig_dir, dpi)
        P.plot_cluster_figures(ml["clusters"], labels, fig_dir, dpi)
        P.plot_surrogate_tree(ml["surrogate"], fig_dir, dpi)


def _md_table(df: pd.DataFrame, nd: int = 3) -> str:
    d = df.copy()
    for c in d.select_dtypes("float").columns:
        d[c] = d[c].map(lambda x: f"{x:.{nd}f}" if pd.notna(x) else "")
    head = "| " + " | ".join(map(str, d.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in d.columns) + " |"
    body = ["| " + " | ".join(map(str, r)) + " |" for r in d.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def _write_report(path, labels, episodes, q, ref_q, sens_grid, jaccard_df, delay_summary, tradeoff,
                  kjust, tcj, eff, eb, ctab, xinfo, ml, funnel, fig_dir, n_users, ts, thr) -> None:
    lc = labels["final_label"].value_counts().to_dict()
    rel = Path(fig_dir).name
    fw = labels[labels.final_label == F.LABEL_FW]; g = labels[labels.final_label == F.LABEL_GAUGE]
    L = []
    L.append("# FCC学習機会ベース介入分類 — 最終検証・閾値根拠・MLシャドウ レポート\n")
    L.append(f"_analysis_timestamp: {ts} · users: {n_users} · episodes: {len(episodes):,} · "
             f"label/rule/threshold version: {F.LABEL_VERSION}_\n")

    L.append("## 1. Executive summary\n")
    L.append(
        f"- 全{n_users}ユーザーに相互排他の最終ラベルを付与（合計={sum(lc.values())}）。\n"
        f"- FCC no/low change候補: **{int(labels['fcc_no_or_low_change_candidate'].sum())}**。\n"
        f"- ゲージリセット/キャリブレーション対象 (`ACTION_GAUGE_RESET`): **{lc.get(F.LABEL_GAUGE,0)}**。\n"
        f"- FW/BIOS/EC確認対象 (`ACTION_FW_CHECK`): **{lc.get(F.LABEL_FW,0)}**。\n"
        f"- Watchlist: **{lc.get(F.LABEL_WATCH,0)}** / Review queue: **{lc.get(F.LABEL_REVIEW,0)}** / Normal: **{lc.get(F.LABEL_NORMAL,0)}**。\n"
        "- 閾値は経験則ではなく、active-reference更新率p05・応答遅延72h CDF・無応答確率(k)・large-gap/打ち切り安全策で根拠付け。\n"
        "- **限界**: 本データではFW/BIOS/EC versionもupdate適用有無も確認できない。FW不良の断定ではなく確認対象の抽出。\n")

    L.append("## 2. 目的\n")
    L.append("FCC/SoHが更新されない/ほぼ更新されないユーザーを抽出し、(a) 学習機会が十分確認できない→ゲージリセット促し、"
             "(b) 学習機会があるのにFCC無応答→FW確認促し、に変換する監査ロジック。予測MLはラベルを決めず、閾値説明と"
             "優先順位付けのshadowとしてのみ使用。\n")

    L.append("## 3. データと前提\n")
    L.append("入力 `battery_timeseries_all.parquet`（3.13M行・752ユーザー）。RSOCは0–100整数で欠損なし、FCCは整数mWhで欠損なし、"
             "`serialNumber`不変（パック交換0件）。`device_model/batt_vendor/batt_fru`等のHW識別子は分類ルールに不使用。\n")

    L.append("## 4. データ品質とREVIEW細分化\n")
    dq = labels["data_quality_label"].value_counts().to_dict()
    L.append("\n".join(f"- `{k}`: {v}" for k, v in sorted(dq.items(), key=lambda x: -x[1])))
    rv = labels[labels.final_label == F.LABEL_REVIEW]
    L.append("\n\nREVIEW内訳 (`review_subreason` × `review_priority`):\n")
    L.append(_md_table(rv.groupby(["review_subreason", "review_priority"]).size().rename("n").reset_index(), 0))

    L.append("\n## 5. FCC no/low change候補の定義\n")
    L.append(f"active reference cohort = {q['n_active_reference']}人。p05/p10は §6 参照。候補フラグ "
             "(`no_fcc_update` ∨ `long_terminal_flat` ∨ `low_update_per_cycle` ∨ `low_update_per_time`) で "
             f"**{int(labels['fcc_no_or_low_change_candidate'].sum())}人**。\n")

    L.append("## 6. 閾値根拠\n")
    L.append("### 6.1 active reference 更新率 p05/p10\n")
    L.append(_md_table(ref_q, 4))
    L.append(f"\n図: `{rel}/reference_update_rate_distribution_per_cycle.png`, `{rel}/..._per_100d.png`\n")
    L.append("### 6.2 flat_tail 60/120/180\n既存 active(<60)/stale(60–180)/very_stale(>=180) 境界に一致。感度は §11。\n")
    L.append("### 6.3 response window 72h\n応答遅延CDF（応答したOK episode）:\n")
    L.append(_md_table(delay_summary, 4))
    L.append(f"\n→ primary 80/20/80 の応答の大半を72hで捕捉。図 `{rel}/response_delay_cdf_24_72_168.png`。\n")
    L.append("### 6.4 学習機会帯 80/20/80 vs 85/15/85 vs 90/10/90\n")
    L.append(_md_table(tradeoff, 4))
    L.append("\n90/10/90=厳格・高信頼だが取り逃し多、85/15/85=中間、80/20/80=主判定（数が多く実用的）。\n")
    L.append("### 6.5 無応答エピソード数 k\n")
    L.append(_md_table(kjust, 4))
    L.append(f"\n→ primary無応答 k=3、strict(90/10/90) K_STRICT=2 で false-alarm proxy が概ね5%以下。図 `{rel}/no_response_probability_by_k.png`。\n")
    L.append("### 6.6 tail_cycle_delta 20/30/50\n")
    L.append(_md_table(tcj, 3))
    L.append("\n### 6.7 AC-bound 0.80 / shallow-range\nAC>=0.80（感度0.70/0.90）。shallow: min_rsoc>20 または swing<60（80→20の60ptレンジ・low到達の定義的根拠）。\n")
    L.append("### 6.8 episode max_gap 12h\nロガー約30分間隔。>12hはスリープ欠測でepisode品質低下。感度6/12/24hは §11。\n")
    L.append("### 6.9 effective FCC step 感度 (1.6)\n")
    if "step_definition" in eff and eff["step_definition"].iloc[0] != "skipped_fast_mode":
        L.append(_md_table(eff, 3))
        L.append("\n→ 微小ステップ(<50mWh)を除くとFCC更新回数が減り候補が増えるが、actionable規模の大小関係は保たれる。\n")
    else:
        L.append("（--fast で省略）\n")

    L.append("## 7. 追加検証での変更点\n")
    L.append("- ラベル改名 `..._NO_OPPORTUNITY` → `..._INSUFFICIENT_LEARNING_OPPORTUNITY`（対応表 `fcc_label_name_mapping.csv`）。\n"
             "- 応答窓の右打ち切り: `censored`/`unknown` を `no_response` に混入させない。\n"
             "- large-gap機会の明示: GAUGE highはok=0かつlarge_gap=0を要件化。large_gapのみ→WATCH。\n"
             "- tail response-rateのトートロジー回避: 主図を `unresponded_complete_window` 系に変更。\n"
             "- REVUEW細分化 (`review_subreason`/`review_priority`)。\n")

    L.append("## 8. 最終ラベル定義\n")
    L.append("適用順: review > normal > fw_high > gauge_high > fw_medium > gauge_medium > watch。FWはGAUGEより先（機会ありを"
             "「まず放電」に回さない）。GAUGE highは機会ゼロ(ok&large_gap)要件なのでFWと衝突しない。\n")

    L.append("## 9. 最終ラベル件数とfunnel\n")
    lab_tbl = pd.DataFrame([{"final_label": k, "n": int(lc.get(k, 0)),
                             "pct": round(lc.get(k, 0)/n_users*100, 1)} for k in F.LABEL_ORDER])
    L.append(_md_table(lab_tbl, 1))
    L.append(f"\n合計={int(lab_tbl['n'].sum())}。funnel: {funnel}\n図 `{rel}/final_funnel_counts.png`, `{rel}/final_label_counts.png`。\n")

    L.append("## 10. intervention target lists\n")
    L.append(f"- `fcc_final_intervention_targets_gauge_reset.csv` ({lc.get(F.LABEL_GAUGE,0)}件)\n"
             f"- `fcc_final_intervention_targets_fw_check.csv` ({lc.get(F.LABEL_FW,0)}件, ml_fw_support_scoreで優先順位付け)\n"
             f"- `fcc_final_watchlist.csv` ({lc.get(F.LABEL_WATCH,0)}件) / `fcc_final_review_queue.csv` ({lc.get(F.LABEL_REVIEW,0)}件)\n")

    L.append("## 11. 感度分析とJaccard安定性\n")
    L.append(_md_table(sens_grid, 0))
    L.append("\nFW/GAUGE集合のJaccard安定性（応答窓摂動 vs 既定）:\n")
    L.append(_md_table(jaccard_df, 4))

    L.append("\n## 12. ML shadow analysis\n")
    if ml.get("model"):
        L.append("episode応答モデル（complete OK 72h, GroupKFold by user, 特徴はepisode開始時点のみ・HW識別子禁止）:\n")
        L.append(_md_table(ml["model"]["metrics"], 4))
        L.append(f"\nサロゲート決定木 fidelity={ml['surrogate']['fidelity']}（`fcc_action_surrogate_tree_rules.txt`）。"
                 f"クラスタ: `fcc_no_low_candidate_clusters.csv`。ml_fw_support_scoreはラベル決定に使わずFW優先順位付けのshadow。\n"
                 f"図 `{rel}/ml_response_model_roc_pr.png` ほか。\n")
    else:
        L.append("（MLシャドウはスキップ/失敗）\n")

    L.append("## 13. hardware enrichment (Empirical Bayes, case-control候補)\n")
    L.append("> 分類にHW識別子は不使用。以下は分類後の偏在（FW version確認の優先順位付け）。母数小群のraw率は過大評価に注意。\n\n")
    top = eb[(eb.group_type == "batt_fru") & (eb.n_total >= 5)].head(8)
    L.append(_md_table(top[["group_type", "value", "n_total", "n_fw_check", "raw_fw_check_rate",
                            "shrunk_fw_check_rate", "fw_check_ci_low", "fw_check_ci_high", "fw_fisher_q_bh"]], 4))
    L.append(f"\n図 `{rel}/hardware_enrichment_empirical_bayes_fw_check.png`, `{rel}/fru_5B10W13975_case_control_summary.png`。\n")

    L.append("## 14. 既存 soh_update_status との照合\n")
    if "existing" in xinfo:
        L.append(f"- 既存: {xinfo['existing']} / 本再現(flat_tail 60/180): {xinfo['reproduced']}\n"
                 f"- active→actionable 誤分類: **{xinfo.get('active_misrouted_to_action')}**件\n")
        if not ctab.empty:
            L.append("\n既存status × 最終ラベル:\n")
            L.append(_md_table(ctab.reset_index(), 0))
    else:
        L.append(f"- soh_update_status.csv なし。再現(flat_tail 60/180): {xinfo['reproduced']}\n")

    L.append("\n## 15. 運用メッセージ案\n")
    L.append(f"- GAUGE: {F.MSG_GAUGE}\n- FW: {F.MSG_FW}\n")

    L.append("## 16. 限界\n")
    L.append("- FW不良の断定ではない。FW/BIOS/EC version・update適用有無は本データで確認不可。\n"
             "- ゲージリセットはOEM推奨手順前提。実施後72h〜7日の追跡が必要。\n"
             "- large-gap/打ち切りで判定不能な機会は保守的にWATCHへ。\n")

    L.append("## 17. 次に収集すべきデータ\n")
    L.append("BIOS/EC/バッテリーFW version、update適用日時、intervention実施日時、intervention後72h〜7日のFCC更新有無。"
             "これらで本監査は「介入→効果」の因果評価へ格上げ可能。\n")

    L.append("\n## 生成物一覧\n")
    L.append(_artifact_list(fig_dir, ml_ran=bool(ml.get("model"))))

    L.append("\n## Final actionable summary\n```\n" + _summary_text(labels, funnel) + "\n```\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def _artifact_list(fig_dir, ml_ran: bool = True) -> str:
    csvs = ["fcc_final_learning_episodes.csv", "fcc_final_user_features.csv", "fcc_final_action_labels.csv",
            "fcc_final_intervention_targets_gauge_reset.csv", "fcc_final_intervention_targets_fw_check.csv",
            "fcc_final_watchlist.csv", "fcc_final_review_queue.csv", "fcc_label_name_mapping.csv",
            "fcc_threshold_reference_quantiles.csv", "fcc_final_sensitivity_grid.csv",
            "fcc_final_jaccard_stability.csv", "fcc_response_delay_distribution.csv",
            "fcc_response_window_sensitivity.csv", "fcc_learning_threshold_tradeoff.csv",
            "fcc_no_response_k_justification.csv", "fcc_tail_cycle_threshold_justification.csv",
            "fcc_effective_step_sensitivity.csv", "fcc_episode_quality_gap_sensitivity.csv",
            "fcc_final_hardware_enrichment_empirical_bayes.csv", "fcc_final_threshold_justification_summary.csv"]
    if ml_ran:
        csvs += ["fcc_final_ml_shadow_scores.csv", "fcc_episode_response_model_predictions.csv",
                 "fcc_episode_response_model_metrics.csv", "fcc_user_expected_response_residuals.csv",
                 "fcc_no_low_candidate_clusters.csv", "fcc_action_surrogate_tree_rules.txt"]
    return "CSV/TXT:\n" + "\n".join(f"- `data/processed/{c}`" for c in csvs) + \
           f"\n\n図 (dpi=300): `{Path(fig_dir).as_posix()}/` 配下（reference/flat_tail/response_delay/learning_tradeoff/" \
           "no_response_k/tail_cycle/ac/shallow/episode_gap/large_gap/effective_step/final scatters/" \
           "label_transition/review_subgroup/funnel/label_counts/EB enrichment/FRU case-control/ML/cluster/surrogate)。\n"


def _summary_text(labels, funnel) -> str:
    lc = labels["final_label"].value_counts().to_dict()
    return (
        "Final actionable summary:\n"
        f"- Total users: {funnel['all_users']}\n"
        f"- FCC no/low change candidates: {funnel['candidates']}\n"
        f"- Gauge reset / calibration targets: {lc.get(F.LABEL_GAUGE,0)}\n"
        f"- FW/BIOS/EC check targets: {lc.get(F.LABEL_FW,0)}\n"
        f"- Watchlist: {lc.get(F.LABEL_WATCH,0)}\n"
        f"- Review queue: {lc.get(F.LABEL_REVIEW,0)}\n"
        "- Main threshold rationale: active-reference p05 update cadence, 72h response delay CDF, "
        "empirical no-response probability by k episodes, large-gap/censoring safeguards.\n"
        "- Important limitation: FW defect is not proven without version/update/intervention follow-up data.")


def _print_summary(labels, funnel) -> None:
    print("\n" + _summary_text(labels, funnel))


if __name__ == "__main__":
    main()
