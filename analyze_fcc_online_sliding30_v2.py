#!/usr/bin/env python
"""End-to-end CLI for the Rolling 30-day FCC Learning/Response Online Detector v2.0
(rolling30 v2 spec sections 1-21).

v2 DAG (each inference point sees only the trailing 30d raw window + persisted state):

  load -> prepare per-user -> rolling 30d features -> causal episodes
       -> graded gap quality -> episode-context enrichment
       -> dual response models (personalized + NORMATIVE) -> per-episode p_response_*
       -> causal window episode counts -> dual window anomaly (normative=policy)
       -> usage-ONLY clustering v2 -> dual-track online state (any + effective)
       -> v2 policy (9-level priority ladder, Gauge/FW tiers) + alert cooldown
       -> snapshot + FW engineering top-N queue + per-tier candidate lists
       -> backtest (stateful/stateless, proxy cross-tab, top-N, lead time, dual-basis
          false-alert, sensitivity) -> multi-population HW enrichment -> report

Run (full):
  python analyze_fcc_online_sliding30_v2.py \
    --timeseries data/processed/battery_timeseries_all.parquet \
    --user-master data/processed/user_master.csv \
    --final-labels data/processed/fcc_final_action_labels.csv \
    --soh-update-status data/processed/soh_update_status.csv \
    --window-days 30 --stride-days 1 --response-window-hours 72 \
    --episode-max-gap-hours 12 --effective-step abs_ge_50mWh \
    --run-any-change-track --run-normative-model --run-personalized-model \
    --run-clustering --run-backtest --run-enrichment \
    --out-dir data/processed/fcc_online_v2 --fig-dir data/reports/figures/fcc_online_v2 \
    --report data/reports/fcc_online_sliding30_v2_report.md --dpi 300 --random-seed 42
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from battery_usage.online_episode_detector import (                         # noqa: E402
    OnlineConfig, EFFECTIVE_STEP_DEFS, extract_episodes_causal, prepare_user,
    recover_design_mwh, episodes_to_frame,
)
from battery_usage.rolling_window_features import (                         # noqa: E402
    build_rolling_features, attach_window_episode_counts,
)
from battery_usage import online_gap_quality as gq                          # noqa: E402
from battery_usage import fcc_response_ml as ml                             # noqa: E402
from battery_usage import fcc_response_normative as nrm                     # noqa: E402
from battery_usage import usage_clustering as uc                           # noqa: E402
from battery_usage import online_policy_v2 as pol                           # noqa: E402
from battery_usage import online_evaluation_v2 as ev                        # noqa: E402
from battery_usage import online_enrichment as enrich                       # noqa: E402
from battery_usage.online_step_state import build_dual_online_state         # noqa: E402
from battery_usage import online_reporting_v2 as report_v2                  # noqa: E402

CODE_VERSION = "rolling30-v2.0"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stamp(df: pd.DataFrame, cfg: OnlineConfig, ts: str) -> pd.DataFrame:
    if df is None:
        return df
    df = df.copy()
    df["analysis_timestamp"] = ts
    df["code_version"] = CODE_VERSION
    df["window_days"] = cfg.window_days
    df["stride_days"] = cfg.stride_days
    df["effective_step_definition"] = cfg.effective_step
    return df


def load_user_meta(args, df: pd.DataFrame) -> pd.DataFrame:
    cols = ["user_id", "device_model", "batt_vendor", "batt_fru"]
    if args.user_master and Path(args.user_master).exists():
        um = pd.read_csv(args.user_master)
        keep = ["user_id"] + [c for c in ("device_model", "batt_vendor", "batt_fru")
                              if c in um.columns]
        return um[keep].drop_duplicates("user_id")
    return df[[c for c in cols if c in df.columns]].drop_duplicates("user_id")


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Rolling 30d FCC online detector v2.0")
    ap.add_argument("--timeseries", default="data/processed/battery_timeseries_all.parquet")
    ap.add_argument("--user-master", default="data/processed/user_master.csv")
    ap.add_argument("--final-labels", default="data/processed/fcc_final_action_labels.csv")
    ap.add_argument("--soh-update-status", dest="soh_status",
                    default="data/processed/soh_update_status.csv")
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--stride-days", type=int, default=1)
    ap.add_argument("--response-window-hours", type=int, default=72)
    ap.add_argument("--delayed-response-window-hours", type=int, default=168)
    ap.add_argument("--episode-max-gap-hours", type=float, default=12.0)
    ap.add_argument("--episode-medium-gap-hours", type=float, default=24.0)
    ap.add_argument("--effective-step", default="abs_ge_50mWh", choices=list(EFFECTIVE_STEP_DEFS))
    ap.add_argument("--run-any-change-track", action="store_true")
    ap.add_argument("--run-normative-model", action="store_true")
    ap.add_argument("--run-personalized-model", action="store_true")
    ap.add_argument("--run-clustering", action="store_true")
    ap.add_argument("--run-backtest", action="store_true")
    ap.add_argument("--run-enrichment", action="store_true")
    ap.add_argument("--out-dir", default="data/processed/fcc_online_v2")
    ap.add_argument("--fig-dir", default="data/reports/figures/fcc_online_v2")
    ap.add_argument("--report", default="data/reports/fcc_online_sliding30_v2_report.md")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--alert-cooldown-days", type=int, default=30)
    ap.add_argument("--random-seed", type=int, default=42)
    ap.add_argument("--max-users", type=int, default=0, help="debug: cap user count")
    args = ap.parse_args(argv)

    np.random.seed(args.random_seed)
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = OnlineConfig(window_days=args.window_days, stride_days=args.stride_days,
                       effective_step=args.effective_step,
                       response_window_hours=args.response_window_hours,
                       episode_max_gap_hours=args.episode_max_gap_hours)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    warnings: List[str] = []

    # ---- load ----
    log(f"loading {args.timeseries}")
    if not Path(args.timeseries).exists():
        log(f"FATAL: timeseries not found: {args.timeseries}"); return 2
    df = pd.read_parquet(args.timeseries)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if args.max_users:
        keep = df["user_id"].drop_duplicates().head(args.max_users)
        df = df[df["user_id"].isin(keep)]
    log(f"  {len(df):,} rows, {df['user_id'].nunique()} users")
    user_meta = load_user_meta(args, df)
    final = pd.read_csv(args.final_labels) if Path(args.final_labels).exists() else None
    if final is None:
        warnings.append(f"final-labels not found ({args.final_labels}); proxy backtest skipped")
    soh_status = pd.read_csv(args.soh_status) if Path(args.soh_status).exists() else None

    # ---- prepare per-user frames + design recovery ----
    log("preparing per-user frames")
    df_by_user: Dict[str, pd.DataFrame] = {}
    design_by_user: Dict[str, float] = {}
    for uid, g in df.groupby("user_id", sort=False):
        gp = prepare_user(g)
        df_by_user[uid] = gp
        design_by_user[uid] = recover_design_mwh(gp)

    # ---- rolling features ----
    log("building 30d rolling window features")
    feats, design_by_user = build_rolling_features(df, cfg, design_by_user, progress=True)
    log(f"  features: {feats.shape[0]:,} user-windows")

    # ---- causal (stateful) episodes ----
    log("extracting causal learning episodes")
    ep_rows: List[dict] = []
    for uid, g in df_by_user.items():
        ep_rows.extend(extract_episodes_causal(g, uid, cfg, design_mwh=design_by_user.get(uid)))
    episodes = episodes_to_frame(ep_rows)
    log(f"  episodes: {len(episodes):,}")

    # ---- graded gap quality (spec 11) ----
    log("attaching graded gap quality")
    episodes = gq.attach_gap_quality(episodes, df_by_user, cfg)
    if len(episodes):
        log("  tier dist (primary): " +
            str(gq.tier_distribution(episodes, "primary_80_20_80").to_dict()))

    # ---- episode-context features + dual response models ----
    rcol = f"response_status_{cfg.response_window_hours}h"
    norm_res = pers_res = {"status": "not_run"}
    ep_probs = pd.DataFrame(columns=["episode_id", "p_response_normative",
                                     "p_response_personalized"])
    default_p = 0.5
    if args.run_normative_model or args.run_personalized_model:
        log("enriching episode features + training dual response models (GroupKFold, calibrated)")
        episodes = ml.enrich_episode_features(df_by_user, episodes, cfg, design_by_user)
        models = nrm.train_dual_models(episodes, rcol, random_state=args.random_seed)
        pers_res = models["personalized_result"]; norm_res = models["normative_result"]
        log(f"  personalized: status={pers_res.get('status')} best={pers_res.get('best_model')} "
            f"n_ep={pers_res.get('n_episodes')}")
        log(f"  normative:    status={norm_res.get('status')} best={norm_res.get('best_model')} "
            f"n_ep={norm_res.get('n_episodes')}")
        ep_probs = nrm.score_dual_models(models, episodes)
        default_p = float(norm_res.get("positive_rate") or 0.5)
        # leakage guards (spec 10.2 / 12.1 / 0.4.2)
        enrich.assert_no_hw_in_classification(norm_res.get("feature_columns", []),
                                              pers_res.get("feature_columns", []),
                                              uc.USAGE_ONLY_CLUSTER_FEATURES)
        nrm.assert_normative_excludes_history(
            [c for c in norm_res.get("feature_columns", []) if not str(c).startswith("band_")])
    episodes = episodes.merge(ep_probs, on="episode_id", how="left")

    # ---- causal window episode counts (for window labels / cluster profiling) ----
    feats = attach_window_episode_counts(feats, episodes, cfg, response_col=rcol)

    # ---- dual window anomaly (normative = policy names; personalized = *_personalized) ----
    log("computing dual window anomaly scores (normative drives policy)")
    feats = nrm.compute_dual_window_scores(feats, episodes, ep_probs, cfg, final_labels=final)

    # ---- usage-only clustering v2 ----
    cluster_assign = pd.DataFrame(columns=["user_id", "window_end_date", "cluster_id",
                                           "cluster_profile_name"])
    cluster_profiles = pd.DataFrame()
    if args.run_clustering:
        log("usage-only clustering v2")
        cluster_assign, cluster_profiles, cinfo = uc.run_usage_clustering_v2(
            feats, random_state=args.random_seed)
        log(f"  algo={cinfo.get('algo')} k={cinfo.get('n_clusters')}")
        uc._assert_usage_only(cinfo.get("features", []))

    # ---- dual-track online state ----
    log("simulating dual-track online state (any + effective)")
    state_daily, change_audit = build_dual_online_state(
        df_by_user, episodes, feats, cfg, design_by_user, default_p=default_p,
        prob_col="p_response_normative", progress=True)
    log(f"  state rows: {len(state_daily):,}")

    # ---- join daily + v2 labels + cooldown ----
    log("assigning v2 stateful labels (9-level priority ladder)")
    daily = feats.merge(state_daily, on=["user_id", "window_end_date"], how="left")
    if not cluster_assign.empty:
        daily = daily.merge(cluster_assign, on=["user_id", "window_end_date"], how="left")
    else:
        daily["cluster_profile_name"] = "SPARSE_OR_GAPPY"
    daily = pol.assign_labels_v2(daily, pol.DEFAULT_POLICY_V2)
    daily = pol.apply_alert_cooldown_v2(daily, args.alert_cooldown_days)
    snap = pol.latest_snapshot_v2(daily)
    log("  snapshot v2 labels: " + str(snap["stateful_label_v2"].value_counts().to_dict()))

    # ---- engineering queue + candidate lists ----
    fw_queue = pol.fw_engineering_queue(snap, ns=(50, 100))
    cands = pol.candidate_lists_v2(snap)

    # ---- cluster outcome profiling (post-hoc) ----
    cluster_outcomes = pd.DataFrame()
    if args.run_clustering and not cluster_assign.empty:
        cluster_outcomes = uc.profile_cluster_outcomes_v2(cluster_assign, daily)

    # ---- backtest / evaluation ----
    bt: Dict[str, object] = {}
    stateless = pd.DataFrame()
    if args.run_backtest:
        log("backtest: stateful/stateless, proxy cross-tab, top-N, lead time, false-alert, sensitivity")
        stateless = ev.stateless_latest_v2(df_by_user, design_by_user, snap, cfg)
        bt["svs"] = ev.stateful_vs_stateless(snap, stateless)
        bt["false_alert"] = ev.active_false_alert_audit(snap, soh_status)
        bt["gauge_core_exceptions"] = ev.gauge_core_active_exceptions(snap, soh_status)
        bt["episode_sensitivity"] = ev.episode_sensitivity_grid(episodes)
        bt["policy_sensitivity"] = ev.policy_sensitivity_grid(snap)
        bt["lead_time"] = ev.lead_time_v2(daily, df_by_user, final)
        if final is not None and "final_label" in final.columns:
            bt["crosstab"] = ev.final_proxy_crosstab(snap, final)
            bt["proxy_pr"] = ev.proxy_precision_recall(snap, final, fw_queue)
            bt["misroute"] = ev.proxy_misroute_table(snap, final)
            yields = [ev.topn_yield_v2(snap, final, "cum_normative_fw_anomaly_score", ev.PROXY_FW),
                      ev.topn_yield_v2(snap, final, "days_since_effective_fcc_change",
                                       ev.PROXY_GAUGE)]
            bt["topn"] = pd.concat([y for y in yields if not y.empty], ignore_index=True) \
                if any(not y.empty for y in yields) else pd.DataFrame()

    # ---- multi-population HW enrichment (post-classification only) ----
    enr = pd.DataFrame()
    if args.run_enrichment:
        log("multi-population HW enrichment (classification-free)")
        enrich.assert_no_hw_in_classification(norm_res.get("feature_columns", []),
                                              uc.USAGE_ONLY_CLUSTER_FEATURES)
        populations = {
            "FW_CORE": set(cands["fw_core"]["user_id"]),
            "FW_CORE+FW_WATCH": set(cands["fw_core"]["user_id"]) | set(cands["fw_watch"]["user_id"]),
            "FW_ENGINEERING_TOP50": set(fw_queue[50]["user_id"]),
            "FW_ENGINEERING_TOP100": set(fw_queue[100]["user_id"]),
            "no_response_ge2_queue": set(snap.loc[
                snap.get("cum_primary_no_response_since_last_effective_change", 0) >= 2, "user_id"]),
            "GAUGE_CORE": set(cands["gauge_core"]["user_id"]),
            "GAUGE_SOFT_CALIBRATION": set(cands["gauge_soft"]["user_id"]),
        }
        populations = {k: v for k, v in populations.items() if len(v) > 0}
        enr = enrich.enrich_multi_population(snap, user_meta, populations, min_group_n=5)

    # ---- write outputs ----
    log("writing outputs")
    _write_outputs(out_dir, cfg, ts_now, feats, episodes, state_daily, change_audit, daily,
                   snap, cands, fw_queue, pers_res, norm_res, cluster_profiles, cluster_assign,
                   cluster_outcomes, stateless, bt, enr)

    # ---- report ----
    log("writing report")
    report_v2.write_report(args.report, cfg, ts_now, CODE_VERSION, df, feats, episodes,
                           pers_res, norm_res, cluster_profiles, cluster_outcomes, snap, daily,
                           fw_queue, bt, enr, warnings)

    _print_final(snap, pers_res, norm_res, bt)
    return 0


# --------------------------------------------------------------------------- #
def _write_outputs(out_dir, cfg, ts, feats, episodes, state_daily, change_audit, daily, snap,
                   cands, fw_queue, pers_res, norm_res, cluster_profiles, cluster_assign,
                   cluster_outcomes, stateless, bt, enr):
    def wp(df, name):
        if df is None:
            return
        stamp(df, cfg, ts).to_parquet(out_dir / name, index=False,
                                      coerce_timestamps="us", allow_truncated_timestamps=True)

    def wc(df, name):
        if df is None:
            return
        stamp(df, cfg, ts).to_csv(out_dir / name, index=False)

    wp(feats, "rolling_30d_user_features_v2.parquet")
    wp(episodes, "rolling_30d_learning_episodes_v2.parquet")
    wp(state_daily, "online_dual_step_state_daily.parquet")
    label_cols = ["user_id", "window_end_date", "window_label_v2", "stateful_label_v2",
                  "recommended_action", "confidence", "priority", "primary_reason",
                  "alert_fired", "consecutive_windows_opportunity_no_response",
                  "days_since_effective_fcc_change", "days_since_any_fcc_change",
                  "cum_normative_fw_anomaly_score", "conformal_p", "cluster_profile_name",
                  # gate-input columns so the daily artifact is self-contained for re-derivation
                  # (review OPS-7)
                  "window_data_quality_label", "state_history_sufficient", "has_counter_reset",
                  "cum_primary_no_response_since_last_effective_change",
                  "high_quality_no_response_count",
                  "micro_wobble_only_since_effective_change"]
    wp(daily[[c for c in label_cols if c in daily.columns]], "online_stateful_labels_v2.parquet")
    wc(snap, "online_latest_snapshot_v2.csv")

    wc(cands.get("fw_core"), "online_fcc_fw_core.csv")
    wc(cands.get("fw_watch"), "online_fcc_fw_watch_high_anomaly.csv")
    wc(fw_queue.get(50), "online_fcc_fw_engineering_queue_top50.csv")
    wc(fw_queue.get(100), "online_fcc_fw_engineering_queue_top100.csv")
    wc(cands.get("gauge_core"), "online_fcc_gauge_core.csv")
    wc(cands.get("gauge_soft"), "online_fcc_gauge_soft_calibration_effective_only.csv")
    wc(cands.get("gauge_review"), "online_fcc_gauge_review.csv")
    wc(cands.get("watchlist"), "online_fcc_watchlist_v2.csv")
    wc(cands.get("review_dq"), "online_fcc_review_queue_v2.csv")

    if change_audit is not None and not change_audit.empty:
        wp(change_audit, "online_dual_fcc_change_audit.parquet")

    for tag, res in (("personalized", pers_res), ("normative", norm_res)):
        m = res.get("metrics") if isinstance(res, dict) else None
        if isinstance(m, pd.DataFrame) and not m.empty:
            wc(m, f"episode_response_model_metrics_{tag}.csv")
        p = res.get("predictions") if isinstance(res, dict) else None
        if isinstance(p, pd.DataFrame) and not p.empty:
            wp(p, f"episode_response_model_predictions_{tag}.parquet")
        imp = res.get("importances") if isinstance(res, dict) else None
        if isinstance(imp, pd.DataFrame) and not imp.empty:
            wc(imp, f"episode_response_model_importances_{tag}.csv")

    score_cols = ["user_id", "window_end_date", "expected_response_30d", "observed_response_30d",
                  "no_response_count_30d", "n_complete_ok_opportunities_30d",
                  "p_all_no_response_30d", "fw_response_anomaly_score_30d", "conformal_p",
                  "fw_response_anomaly_score_30d_personalized", "conformal_p_proxy_final_normal"]
    wp(feats[[c for c in score_cols if c in feats.columns]], "user_window_anomaly_scores_v2.parquet")

    if not cluster_profiles.empty:
        wc(cluster_profiles, "usage_cluster_profiles_v2.csv")
    if not cluster_assign.empty:
        wp(cluster_assign, "usage_cluster_assignments_v2.parquet")
    if cluster_outcomes is not None and not cluster_outcomes.empty:
        wc(cluster_outcomes, "usage_cluster_outcome_profile_v2.csv")

    if bt:
        svs = bt.get("svs")
        if isinstance(svs, dict):
            wc(pd.DataFrame([svs]), "backtest_stateful_vs_stateless_v2.csv")
        for key, name in (("crosstab", "final_proxy_cross_tab_v2.csv"),
                          ("topn", "topn_yield_v2.csv"),
                          ("proxy_pr", "proxy_precision_recall_v2.csv"),
                          ("misroute", "proxy_misroute_v2.csv"),
                          ("false_alert", "active_false_alert_audit_v2.csv"),
                          ("gauge_core_exceptions", "gauge_core_active_exceptions_v2.csv"),
                          ("lead_time", "lead_time_v2.csv"),
                          ("policy_sensitivity", "sensitivity_grid_v2.csv"),
                          ("episode_sensitivity", "episode_sensitivity_v2.csv")):
            v = bt.get(key)
            if isinstance(v, pd.DataFrame) and not v.empty:
                if key == "crosstab":
                    wc(v.reset_index(), name)
                else:
                    wc(v, name)
    if not stateless.empty:
        wc(stateless, "backtest_stateless_latest_v2.csv")
    if enr is not None and not enr.empty:
        wc(enr, "hardware_enrichment_v2.csv")


def _print_final(snap, pers_res, norm_res, bt):
    sc = snap["stateful_label_v2"].value_counts().to_dict()
    print("\n" + "=" * 72)
    print("V2 FINAL SUMMARY")
    print("=" * 72)
    for k in (pol.ST_FW_CORE, pol.ST_FW_WATCH, pol.ST_GAUGE_CORE, pol.ST_GAUGE_SOFT,
              pol.ST_GAUGE_REVIEW, pol.ST_REVIEW_DQ, pol.ST_WATCH_LGC, pol.ST_WATCH_LOW,
              pol.ST_NORMAL):
        print(f"  {k:48s} {sc.get(k, 0)}")
    for tag, res in (("personalized", pers_res), ("normative", norm_res)):
        if isinstance(res, dict) and res.get("status") == "ok":
            m = res["metrics"]; best = res["best_model"]
            mr = m[m["model"] == best].iloc[0]
            print(f"{tag:13s} [{best}]: ROC AUC={mr['roc_auc']} PR AUC={mr['pr_auc']} "
                  f"Brier={mr['brier']}/{mr['brier_calibrated']} slope={mr['calib_slope']}")
    if bt and isinstance(bt.get("svs"), dict):
        s = bt["svs"]
        print(f"Detection: stateful={s['stateful_detection_n']} stateless={s['stateless_detection_n']} "
              f"gain={s['stateful_only_detection_n']} | FW_core={s['fw_core_n']} "
              f"FW_watch={s['fw_watch_n']} Gauge_core={s['gauge_core_n']} Gauge_soft={s['gauge_soft_n']}")
    print("=" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
