"""Standalone re-run of the ML SHADOW analysis (spec section 6 / CLI section 9).

Reads the final episode/feature/label CSVs (+ the parquet for episode-context features),
re-trains the episode response model, recomputes per-user residuals + FW support scores,
re-clusters the candidate cohort, refits the surrogate tree, and regenerates the ML
figures. Never changes the rule-based labels.

    python analyze_fcc_response_model.py \
      --episodes data/processed/fcc_final_learning_episodes.csv \
      --user-features data/processed/fcc_final_user_features.csv \
      --labels data/processed/fcc_final_action_labels.csv \
      --out-dir data/processed \
      --fig-dir data/reports/figures/fcc_final_thresholds \
      --dpi 300
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from battery_usage.config import load_config
from battery_usage import fcc_response_model as M
from battery_usage import fcc_final as F
import plot_fcc_learning_actions_final as P


def main(argv=None) -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="ML shadow analysis for the FCC classifier")
    ap.add_argument("--timeseries", default=str(cfg.processed_dir / "battery_timeseries_all.parquet"))
    ap.add_argument("--episodes", default=str(cfg.processed_dir / "fcc_final_learning_episodes.csv"))
    ap.add_argument("--user-features", default=str(cfg.processed_dir / "fcc_final_user_features.csv"))
    ap.add_argument("--labels", default=str(cfg.processed_dir / "fcc_final_action_labels.csv"))
    ap.add_argument("--out-dir", default=str(cfg.processed_dir))
    ap.add_argument("--fig-dir", default=str(cfg.figures_dir / "fcc_final_thresholds"))
    ap.add_argument("--dpi", type=int, default=300)
    a = ap.parse_args(argv)
    out_dir = Path(a.out_dir); fig_dir = Path(a.fig_dir); fig_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().isoformat(timespec="seconds")

    print("loading episodes / features / labels / timeseries")
    eps = pd.read_csv(a.episodes, parse_dates=["start_ts", "low_ts", "end_ts"])
    feat = pd.read_csv(a.user_features, parse_dates=["last_fcc_change_ts"])
    labels = pd.read_csv(a.labels)
    df = pd.read_parquet(a.timeseries, columns=[
        "user_id", "timestamp", "remainingCapacityInPercentage", "fullChargeCapacity",
        "cycleCount", "acdcMode", "chargeStatus", "soh_design_pct"])
    if "final_label" not in feat.columns:
        feat = feat.merge(labels[["user_id", "final_label"]], on="user_id", how="left")

    print("enrich episode features + train response model")
    eps_feat = M.enrich_episode_features(df, eps)
    model = M.train_response_model(eps_feat)
    resid = M.user_response_residuals(model["predictions"], feat)
    clusters = M.cluster_candidates(feat, [F.LABEL_WATCH, F.LABEL_GAUGE, F.LABEL_FW])
    surr = M.surrogate_tree(feat)

    def stamp(d):
        d = d.copy(); d["analysis_timestamp"] = ts; return d
    stamp(model["predictions"]).to_csv(out_dir / "fcc_episode_response_model_predictions.csv", index=False)
    stamp(model["metrics"]).to_csv(out_dir / "fcc_episode_response_model_metrics.csv", index=False)
    stamp(resid).to_csv(out_dir / "fcc_user_expected_response_residuals.csv", index=False)
    stamp(resid).to_csv(out_dir / "fcc_final_ml_shadow_scores.csv", index=False)
    stamp(clusters).to_csv(out_dir / "fcc_no_low_candidate_clusters.csv", index=False)
    (out_dir / "fcc_action_surrogate_tree_rules.txt").write_text(
        f"# surrogate fidelity={surr['fidelity']}\n" + surr["rules"], encoding="utf-8")

    print("figures")
    P.plot_ml_figures(model, resid, labels, fig_dir, a.dpi)
    P.plot_cluster_figures(clusters, feat, fig_dir, a.dpi)
    P.plot_surrogate_tree(surr, fig_dir, a.dpi)

    m = model["metrics"].iloc[0]
    print(f"\nepisode response model ({model['best_model']}): ROC AUC={m['roc_auc']}, PR AUC={m['pr_auc']}, "
          f"Brier={m['brier']} | surrogate fidelity={surr['fidelity']}")
    print(f"wrote ML shadow CSVs to {out_dir} and figures to {fig_dir}")


if __name__ == "__main__":
    main()
