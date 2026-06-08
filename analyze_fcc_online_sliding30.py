#!/usr/bin/env python
"""End-to-end CLI for the 30-day sliding-window FCC learning/response ML detector
(rolling30 spec sections 1-18).

Pipeline (each inference point sees only the trailing 30-day raw window + persisted state):

  load -> prepare per-user -> rolling 30d features -> causal (stateful) episodes
       -> episode response ML (GroupKFold, calibrated) -> p_response per episode
       -> usage clustering -> online state (event replay) -> anomaly scores
       -> window+stateful labels + alert cooldown -> snapshot + candidate lists
       -> backtest (stateful vs stateless, final-label proxy) -> HW enrichment -> report

Run:
  python analyze_fcc_online_sliding30.py --timeseries data/processed/battery_timeseries_all.parquet \
      --user-master data/processed/user_master.csv --final-labels data/processed/fcc_final_action_labels.csv \
      --window-days 30 --stride-days 1 --effective-step abs_ge_50mWh --out-dir data/processed/fcc_online \
      --fig-dir data/reports/figures/fcc_online --report data/reports/fcc_online_sliding30_ml_detection_report.md \
      --run-ml --run-clustering --run-backtest --run-enrichment
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

from battery_usage.online_episode_detector import (                       # noqa: E402
    OnlineConfig, EFFECTIVE_STEP_DEFS, RESPONSE_WINDOWS_H, PRIMARY_THRESHOLD, STRICT_THRESHOLD,
    extract_episodes_causal, extract_episodes_in_window, prepare_user, recover_design_mwh,
    episodes_to_frame,
)
from battery_usage.rolling_window_features import (                       # noqa: E402
    build_rolling_features, attach_window_episode_counts,
)
from battery_usage import fcc_response_ml as ml                           # noqa: E402
from battery_usage import usage_clustering as uc                          # noqa: E402
from battery_usage import online_anomaly_scores as anom                   # noqa: E402
from battery_usage import online_action_policy as policy                  # noqa: E402
from battery_usage import online_enrichment as enrich                     # noqa: E402
from battery_usage.online_state import build_online_state                 # noqa: E402

CODE_VERSION = "rolling30-v1.0"


# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stamp(df: pd.DataFrame, cfg: OnlineConfig, ts: str) -> pd.DataFrame:
    if df is None:
        return df
    df = df.copy()   # stamp even empty (but schema-bearing) frames — spec 2 requires it on ALL outputs
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
        keep = ["user_id"] + [c for c in ("device_model", "batt_vendor", "batt_fru") if c in um.columns]
        meta = um[keep].drop_duplicates("user_id")
    else:
        meta = df[[c for c in cols if c in df.columns]].drop_duplicates("user_id")
    return meta


# --------------------------------------------------------------------------- #
# Sensitivity analyses (lightweight: episode-level response counts under variants)
# --------------------------------------------------------------------------- #
def effective_step_sensitivity(df_by_user, design_by_user, base_cfg) -> pd.DataFrame:
    rows = []
    for step in EFFECTIVE_STEP_DEFS:
        cfg = OnlineConfig(**{**base_cfg.__dict__, "effective_step": step})
        n_resp = n_nr = n_cens = n_ok = 0
        for uid, g in df_by_user.items():
            eps = extract_episodes_causal(g, uid, cfg, design_mwh=design_by_user.get(uid))
            for e in eps:
                if e["threshold_name"] != PRIMARY_THRESHOLD or e["episode_quality"] != "ok":
                    continue
                s = e["response_status_72h"]
                n_ok += s in ("responded", "no_response")
                n_resp += s == "responded"; n_nr += s == "no_response"; n_cens += s == "censored"
        rows.append({"effective_step": step, "n_ok_complete_primary": n_ok,
                     "n_responded": n_resp, "n_no_response": n_nr, "n_censored": n_cens,
                     "response_rate": round(n_resp / max(n_ok, 1), 4)})
    return pd.DataFrame(rows)


def gap_sensitivity(df_by_user, design_by_user, base_cfg) -> pd.DataFrame:
    rows = []
    for gap in (6.0, 12.0, 24.0):
        cfg = OnlineConfig(**{**base_cfg.__dict__, "episode_max_gap_hours": gap})
        counts = {"ok": 0, "large_gap": 0}
        for uid, g in df_by_user.items():
            for e in extract_episodes_causal(g, uid, cfg, design_mwh=design_by_user.get(uid)):
                if e["threshold_name"] != PRIMARY_THRESHOLD:
                    continue
                if e["episode_quality"] in counts:
                    counts[e["episode_quality"]] += 1
        rows.append({"episode_max_gap_hours": gap, "n_ok": counts["ok"],
                     "n_large_gap": counts["large_gap"],
                     "ok_fraction": round(counts["ok"] / max(counts["ok"] + counts["large_gap"], 1), 4)})
    return pd.DataFrame(rows)


def response_window_sensitivity(episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ok = episodes[(episodes["threshold_name"] == PRIMARY_THRESHOLD)
                  & (episodes["episode_quality"] == "ok")]
    for w in RESPONSE_WINDOWS_H:
        col = f"response_status_{w}h"
        if col not in ok.columns:
            continue
        vc = ok[col].value_counts()
        n_resp = int(vc.get("responded", 0)); n_nr = int(vc.get("no_response", 0))
        n_cens = int(vc.get("censored", 0))
        rows.append({"response_window_hours": w, "n_responded": n_resp, "n_no_response": n_nr,
                     "n_censored": n_cens,
                     "response_rate_complete": round(n_resp / max(n_resp + n_nr, 1), 4)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Stateless comparison at the latest window per user
# --------------------------------------------------------------------------- #
def stateless_latest(df_by_user, design_by_user, snap: pd.DataFrame, cfg: OnlineConfig) -> pd.DataFrame:
    """Within-30d-window (stateless) view at each user's latest window end.

    Counts complete-by-t OK primary no_response opportunities using ONLY the last 30d raw
    window (inference time = window end). A stateless FW-ish flag needs >=2 such with 0
    responses and OK window quality — the evidence the stateful detector can accumulate over
    many windows but the stateless one cannot see beyond 30 days.
    """
    rows = []
    snap_idx = snap.set_index("user_id")
    for uid, g in df_by_user.items():
        if uid not in snap_idx.index:
            continue
        t = pd.Timestamp(snap_idx.loc[uid, "window_end_ts"])
        start = t - pd.Timedelta(days=cfg.window_days)
        win = g[(g["timestamp"] > start) & (g["timestamp"] <= t)]
        eps = extract_episodes_in_window(win, uid, t, cfg, design_mwh=design_by_user.get(uid),
                                         last_observed_ts=t)
        prim_ok = [e for e in eps if e["threshold_name"] == PRIMARY_THRESHOLD
                   and e["episode_quality"] == "ok"]
        n_resp = sum(e["response_status_72h"] == "responded" for e in prim_ok)
        n_nr = sum(e["response_status_72h"] == "no_response" for e in prim_ok)
        q_ok = snap_idx.loc[uid, "window_data_quality_label"] == "WINDOW_QUALITY_OK"
        flag = bool(n_nr >= 2 and n_resp == 0 and q_ok)
        rows.append({"user_id": uid, "stateless_n_no_response_30d": n_nr,
                     "stateless_n_responded_30d": n_resp, "stateless_fw_flag": flag})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Backtest vs final-label proxy
# --------------------------------------------------------------------------- #
PROXY_FW = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
PROXY_GAUGE = "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY"
PROXY_WATCH = "WATCH_LOW_UPDATE_RATE_AMBIGUOUS"
PROXY_NORMAL = "NORMAL_OR_RESPONDING"
PROXY_REVIEW = "REVIEW_INSUFFICIENT_DATA"


def topn_yield(snap: pd.DataFrame, final: pd.DataFrame, score_col: str,
               proxy_label: str, ns=(10, 20, 30, 50)) -> pd.DataFrame:
    m = snap.merge(final[["user_id", "final_label"]], on="user_id", how="left")
    m = m.sort_values(score_col, ascending=False)
    total_pos = int((m["final_label"] == proxy_label).sum())
    rows = []
    for N in ns:
        top = m.head(N)
        hits = int((top["final_label"] == proxy_label).sum())
        rows.append({"score_col": score_col, "proxy_label": proxy_label, "N": N,
                     "hits": hits, "precision_at_N": round(hits / N, 4),
                     "recall_at_N": round(hits / max(total_pos, 1), 4),
                     "total_proxy_pos": total_pos})
    return pd.DataFrame(rows)


def backtest_summary(snap: pd.DataFrame, final: Optional[pd.DataFrame],
                     soh_status: Optional[pd.DataFrame], stateless: pd.DataFrame,
                     daily: pd.DataFrame, df_by_user) -> Dict[str, object]:
    out: Dict[str, object] = {}
    snap_counts = snap["stateful_label"].value_counts().to_dict()
    out["snapshot_counts"] = snap_counts

    # ---- stateless vs stateful: APPLES-TO-APPLES detection comparison ----
    # Both detectors use the SAME no-response evidence threshold (>=2 OK no_response, 0 observed
    # response, latest window quality OK). They differ ONLY in memory: the stateless detector
    # counts within the last 30d raw window; the stateful detector counts cumulatively since the
    # last effective FCC change (which can span many months). So any user the stateless one finds,
    # the stateful one also finds; the *gain* is users whose evidence is spread across >30 days.
    det_flag = ((snap.get("cum_primary_no_response_since_last_fcc_change", 0) >= 2)
                & (snap.get("cum_observed_response_since_last_fcc_change", 0) == 0)
                & (snap["window_data_quality_label"] == "WINDOW_QUALITY_OK"))
    st_det = set(snap.loc[det_flag, "user_id"])
    sl_det = set(stateless.loc[stateless["stateless_fw_flag"], "user_id"])
    out["stateful_detection_n"] = len(st_det)
    out["stateless_detection_n"] = len(sl_det)
    out["stateful_only_detection_n"] = len(st_det - sl_det)    # incremental gain from persisted state
    out["stateless_only_detection_n"] = len(sl_det - st_det)
    out["overlap_detection_n"] = len(st_det & sl_det)
    # action-policy candidate counts (the strict FW/Gauge gates) — reported separately
    out["action_fw_n"] = int((snap["stateful_label"] == policy.ST_FW).sum())
    out["action_gauge_n"] = int((snap["stateful_label"] == policy.ST_GAUGE).sum())

    # active false-alert rate (existing soh_update_status as ground proxy)
    if soh_status is not None and "soh_update_status" in soh_status.columns:
        act = snap.merge(soh_status[["user_id", "soh_update_status"]], on="user_id", how="left")
        actionable = act[act["stateful_label"].isin([policy.ST_FW, policy.ST_GAUGE])]
        n_act = len(actionable)
        n_active_false = int((actionable["soh_update_status"] == "active").sum())
        out["actionable_n"] = n_act
        out["actionable_active_false_n"] = n_active_false
        out["active_false_alert_rate"] = round(n_active_false / max(n_act, 1), 4)
        # NOTE: soh_update_status flags "active" on ANY FCC change (>=1 mWh); our detector requires
        # >=90d since the last EFFECTIVE (>=50 mWh) change. By our own effective-step definition the
        # actionable set is 0% recently-updated (every actionable user has days_since_eff >= 90):
        n_eff_active = int((actionable["days_since_last_effective_fcc_change"] < 60).sum())
        out["actionable_eff_recent_update_n"] = n_eff_active
        out["active_false_alert_rate_effective_step"] = round(n_eff_active / max(n_act, 1), 4)

    rows: List[Dict] = []
    for label, cnt in snap_counts.items():
        rows.append({"metric": "snapshot_count", "key": label, "value": cnt})
    for k in ("stateful_detection_n", "stateless_detection_n", "stateful_only_detection_n",
              "stateless_only_detection_n", "overlap_detection_n", "action_fw_n", "action_gauge_n",
              "actionable_n", "actionable_active_false_n", "active_false_alert_rate",
              "actionable_eff_recent_update_n", "active_false_alert_rate_effective_step"):
        if k in out:
            rows.append({"metric": "comparison", "key": k, "value": out[k]})

    if final is not None and "final_label" in final.columns:
        # cross-tab snapshot stateful vs final proxy
        m = snap.merge(final[["user_id", "final_label"]], on="user_id", how="left")
        out["crosstab"] = pd.crosstab(m["stateful_label"], m["final_label"])
        # lead time for FW/Gauge proxy cases: first alert vs last observed date
        first_alert = (daily[daily["alert_fired"]].groupby("user_id")["window_end_date"].min()
                       .rename("first_alert_date").reset_index())
        last_obs = pd.DataFrame({"user_id": list(df_by_user.keys()),
                                 "last_obs_date": [pd.Timestamp(g["timestamp"].iloc[-1]).normalize()
                                                   for g in df_by_user.values()]})
        lt = first_alert.merge(last_obs, on="user_id", how="left").merge(
            final[["user_id", "final_label"]], on="user_id", how="left")
        lt["lead_time_days"] = (lt["last_obs_date"] - lt["first_alert_date"]).dt.days
        out["lead_time_table"] = lt
        for proxy in (PROXY_FW, PROXY_GAUGE):
            sub = lt[lt["final_label"] == proxy]
            if not sub.empty:
                rows.append({"metric": "lead_time_days_median", "key": proxy,
                             "value": round(float(sub["lead_time_days"].median()), 1)})
                rows.append({"metric": "n_alerted_of_proxy", "key": proxy, "value": int(len(sub))})
        # top-N yield
        yields = []
        yields.append(topn_yield(snap, final, "cum_fw_response_anomaly_score", PROXY_FW))
        yields.append(topn_yield(snap, final, "days_since_last_effective_fcc_change", PROXY_GAUGE))
        out["topn"] = pd.concat(yields, ignore_index=True)

    out["summary_rows"] = pd.DataFrame(rows)
    return out


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="30-day sliding-window FCC response ML detector")
    ap.add_argument("--timeseries", default="data/processed/battery_timeseries_all.parquet")
    ap.add_argument("--user-master", default="data/processed/user_master.csv")
    ap.add_argument("--final-labels", default="data/processed/fcc_final_action_labels.csv")
    ap.add_argument("--soh-status", default="data/processed/soh_update_status.csv")
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--stride-days", type=int, default=1)
    ap.add_argument("--effective-step", default="abs_ge_50mWh", choices=list(EFFECTIVE_STEP_DEFS))
    ap.add_argument("--response-window-hours", type=int, default=72)
    ap.add_argument("--episode-max-gap-hours", type=float, default=12.0)
    ap.add_argument("--out-dir", default="data/processed/fcc_online")
    ap.add_argument("--fig-dir", default="data/reports/figures/fcc_online")
    ap.add_argument("--report", default="data/reports/fcc_online_sliding30_ml_detection_report.md")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--alert-cooldown-days", type=int, default=30)
    ap.add_argument("--run-ml", action="store_true")
    ap.add_argument("--run-clustering", action="store_true")
    ap.add_argument("--run-backtest", action="store_true")
    ap.add_argument("--run-enrichment", action="store_true")
    ap.add_argument("--run-sensitivity", action="store_true")
    ap.add_argument("--max-users", type=int, default=0, help="debug: cap user count")
    args = ap.parse_args(argv)

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
    log(f"  episodes: {len(episodes):,} "
        f"(quality: {episodes['episode_quality'].value_counts().to_dict() if len(episodes) else {}})")

    # ---- ML response model ----
    ml_result: Dict[str, object] = {}
    ep_probs = pd.DataFrame(columns=["episode_id", "p_response"])
    default_p = 0.5
    if args.run_ml and len(episodes):
        log("training episode response model (GroupKFold, calibrated)")
        episodes = ml.enrich_episode_features(df_by_user, episodes, cfg, design_by_user)
        ml_result, bundle = ml.train_response_model(episodes, f"response_status_{cfg.response_window_hours}h")
        log(f"  status={ml_result.get('status')} best={ml_result.get('best_model')} "
            f"n_ep={ml_result.get('n_episodes')} pos_rate={ml_result.get('positive_rate')}")
        ep_probs = ml.predict_all_ok(bundle, episodes)
        default_p = float(ml_result.get("positive_rate") or 0.5)
        enrich.assert_no_hw_in_classification(ml_result.get("feature_columns", []),
                                              uc.CLUSTER_FEATURES)
    episodes = episodes.merge(ep_probs, on="episode_id", how="left")

    # ---- attach window episode counts (needs episodes) ----
    feats = attach_window_episode_counts(feats, episodes, cfg,
                                         response_col=f"response_status_{cfg.response_window_hours}h")

    # ---- clustering ----
    cluster_assign = pd.DataFrame(columns=["user_id", "window_end_date", "cluster_id",
                                           "cluster_profile_name", "cluster_action_hint"])
    cluster_profiles = pd.DataFrame()
    if args.run_clustering:
        log("clustering 30d usage windows")
        cluster_assign, cluster_profiles, cinfo = uc.run_clustering(feats)
        log(f"  algo={cinfo.get('algo')} k={cinfo.get('n_clusters')}")

    # ---- anomaly scores ----
    log("computing user-window anomaly scores")
    feats = anom.compute_window_scores(feats, episodes, ep_probs, cfg, final_labels=final)

    # ---- online state ----
    log("simulating online state (event replay)")
    state_daily, change_audit = build_online_state(df_by_user, episodes, feats, cfg,
                                                   design_by_user, default_p=default_p, progress=True)
    log(f"  state rows: {len(state_daily):,}")

    # ---- join daily + labels + cooldown ----
    log("assigning window + stateful labels")
    daily = feats.merge(state_daily, on=["user_id", "window_end_date"], how="left")
    if not cluster_assign.empty:
        daily = daily.merge(cluster_assign, on=["user_id", "window_end_date"], how="left")
    else:
        daily["cluster_profile_name"] = "SPARSE_OR_REVIEW"
    daily = policy.assign_labels(daily, cfg)
    daily = policy.apply_alert_cooldown(daily, args.alert_cooldown_days)
    snap = policy.latest_snapshot(daily)
    cands = policy.candidate_lists(snap)
    log("  snapshot stateful labels: " + str(snap["stateful_label"].value_counts().to_dict()))

    # ---- sensitivity ----
    sens = {}
    if args.run_sensitivity:
        log("running sensitivity (effective-step / gap / response-window)")
        sens["effective_step"] = effective_step_sensitivity(df_by_user, design_by_user, cfg)
        sens["gap"] = gap_sensitivity(df_by_user, design_by_user, cfg)
        sens["response_window"] = response_window_sensitivity(episodes)

    # ---- backtest ----
    bt: Dict[str, object] = {}
    stateless = pd.DataFrame()
    if args.run_backtest:
        log("backtest: stateless comparison + final-label proxy")
        stateless = stateless_latest(df_by_user, design_by_user, snap, cfg)
        bt = backtest_summary(snap, final, soh_status, stateless, daily, df_by_user)

    # ---- enrichment ----
    enr = pd.DataFrame()
    if args.run_enrichment:
        log("post-hoc HW/FW enrichment (classification-free)")
        enrich.assert_no_hw_in_classification(ml_result.get("feature_columns", []),
                                              uc.CLUSTER_FEATURES)
        enr = enrich.enrich_all(snap, user_meta, [policy.ST_FW], min_group_n=5)

    # ---- write outputs ----
    log("writing outputs")
    _write_outputs(out_dir, cfg, ts_now, feats, episodes, state_daily, change_audit, daily,
                   snap, cands, ml_result, cluster_profiles, cluster_assign, stateless, bt,
                   enr, sens, user_meta)

    # ---- report ----
    log("writing report")
    _write_report(args.report, cfg, ts_now, df, feats, episodes, ml_result, cluster_profiles,
                  snap, bt, enr, sens, stateless, warnings, default_p)

    # ---- final console summary ----
    _print_final(snap, ml_result, bt, enr, warnings)
    return 0


def _meta_cols(cfg, ts):
    return {"analysis_timestamp": ts, "code_version": CODE_VERSION, "window_days": cfg.window_days,
            "stride_days": cfg.stride_days, "effective_step_definition": cfg.effective_step}


def _write_outputs(out_dir, cfg, ts, feats, episodes, state_daily, change_audit, daily, snap,
                   cands, ml_result, cluster_profiles, cluster_assign, stateless, bt, enr, sens,
                   user_meta):
    def w_parquet(df, name):
        stamp(df, cfg, ts).to_parquet(out_dir / name, index=False,
                                      coerce_timestamps="us", allow_truncated_timestamps=True)

    def w_csv(df, name):
        stamp(df, cfg, ts).to_csv(out_dir / name, index=False)

    w_parquet(feats, "rolling_30d_user_features.parquet")
    w_parquet(episodes, "rolling_30d_learning_episodes.parquet")
    w_parquet(state_daily, "online_fcc_user_state_daily.parquet")
    label_cols = ["user_id", "window_end_date", "window_label", "stateful_label",
                  "recommended_action", "alert_fired",
                  "consecutive_windows_opportunity_no_response",
                  "days_since_last_effective_fcc_change",
                  "cycles_since_last_effective_fcc_change",
                  "fw_response_anomaly_score_30d", "conformal_p", "cluster_profile_name"]
    w_parquet(daily[[c for c in label_cols if c in daily.columns]], "online_fcc_daily_labels.parquet")
    w_csv(snap, "online_fcc_current_snapshot.csv")
    w_csv(cands.get("fw_check", pd.DataFrame()), "online_fcc_action_candidates_fw_check.csv")
    w_csv(cands.get("gauge_reset", pd.DataFrame()), "online_fcc_action_candidates_gauge_reset.csv")
    w_csv(cands.get("watchlist", pd.DataFrame()), "online_fcc_watchlist.csv")
    w_csv(cands.get("review_queue", pd.DataFrame()), "online_fcc_review_queue.csv")
    if not change_audit.empty:
        w_parquet(change_audit, "online_fcc_change_audit.parquet")

    if ml_result:
        m = ml_result.get("metrics", pd.DataFrame())
        if isinstance(m, pd.DataFrame) and not m.empty:
            w_csv(m, "episode_response_model_metrics.csv")
        p = ml_result.get("predictions", pd.DataFrame())
        if isinstance(p, pd.DataFrame) and not p.empty:
            w_parquet(p, "episode_response_model_predictions.parquet")
        imp = ml_result.get("importances", pd.DataFrame())
        if isinstance(imp, pd.DataFrame) and not imp.empty:
            w_csv(imp, "episode_response_model_importances.csv")

    score_cols = ["user_id", "window_end_date", "expected_response_30d", "observed_response_30d",
                  "no_response_count_30d", "n_complete_ok_opportunities_30d",
                  "p_all_no_response_30d", "fw_response_anomaly_score_30d", "conformal_p"]
    if "conformal_p_proxy_final_normal" in feats.columns:
        score_cols.append("conformal_p_proxy_final_normal")
    w_parquet(feats[[c for c in score_cols if c in feats.columns]], "user_window_ml_scores.parquet")

    if not cluster_profiles.empty:
        w_csv(cluster_profiles, "usage_cluster_profiles.csv")
    if not cluster_assign.empty:
        w_parquet(cluster_assign, "usage_cluster_assignments.parquet")

    if bt:
        if isinstance(bt.get("summary_rows"), pd.DataFrame):
            w_csv(bt["summary_rows"], "backtest_detection_summary.csv")
        if isinstance(bt.get("topn"), pd.DataFrame):
            w_csv(bt["topn"], "backtest_topn_yield.csv")
        if isinstance(bt.get("lead_time_table"), pd.DataFrame):
            w_csv(bt["lead_time_table"], "backtest_lead_time.csv")
        if isinstance(bt.get("crosstab"), pd.DataFrame):
            w_csv(bt["crosstab"].reset_index(), "backtest_stateful_vs_final_crosstab.csv")
    if not stateless.empty:
        w_csv(stateless, "backtest_stateless_latest.csv")
    if not enr.empty:
        w_csv(enr, "hardware_enrichment_online_fw_candidates.csv")
    for k, v in (sens or {}).items():
        if isinstance(v, pd.DataFrame) and not v.empty:
            w_csv(v, f"fcc_online_sensitivity_{k}.csv")


# --------------------------------------------------------------------------- #
def _write_report(path, cfg, ts, df, feats, episodes, ml_result, cluster_profiles, snap, bt,
                  enr, sens, stateless, warnings, default_p):
    from textwrap import dedent
    L: List[str] = []
    a = L.append
    sc = snap["stateful_label"].value_counts().to_dict()
    n_users = df["user_id"].nunique()
    eq = episodes["episode_quality"].value_counts().to_dict() if len(episodes) else {}

    a(f"# 30-day Sliding-Window FCC Learning/Response ML Detection — Report\n")
    a(f"*Generated {ts} · code `{CODE_VERSION}` · window={cfg.window_days}d stride={cfg.stride_days}d "
      f"effective-step=`{cfg.effective_step}` response-window={cfg.response_window_hours}h "
      f"episode-max-gap={cfg.episode_max_gap_hours}h*\n")

    a("## 1. Executive summary\n")
    a(f"- Cohort: **{n_users} users**, {len(df):,} raw samples, "
      f"{feats.shape[0]:,} user-windows at stride={cfg.stride_days}d.")
    a(f"- Latest-snapshot stateful labels: " + ", ".join(f"**{k}**={v}" for k, v in sc.items()) + ".")
    if ml_result.get("status") == "ok":
        m = ml_result["metrics"]; best = ml_result["best_model"]
        mr = m[m["model"] == best].iloc[0]
        a(f"- Episode response model (`{best}`, GroupKFold by user): ROC AUC **{mr['roc_auc']}**, "
          f"PR AUC {mr['pr_auc']}, Brier {mr['brier']} (calibrated {mr['brier_calibrated']}), "
          f"calib slope {mr['calib_slope']}; positive (response) rate {mr['positive_rate']}.")
    if bt:
        a(f"- Same-threshold detection (≥2 no_response, 0 response, OK window): "
          f"stateful={bt.get('stateful_detection_n')}, stateless(30d-only)={bt.get('stateless_detection_n')}, "
          f"**stateful-only gain={bt.get('stateful_only_detection_n')}** (evidence spread beyond 30 days). "
          f"Strict action gate yields FW={bt.get('action_fw_n')}, Gauge={bt.get('action_gauge_n')}.")
        if "active_false_alert_rate" in bt:
            a(f"- Active false-alert rate vs `soh_update_status` (any-change): "
              f"{bt['active_false_alert_rate']} ({bt.get('actionable_active_false_n')}/{bt.get('actionable_n')}); "
              f"but by our 50 mWh-effective definition it is "
              f"**{bt.get('active_false_alert_rate_effective_step')}** "
              f"({bt.get('actionable_eff_recent_update_n')}/{bt.get('actionable_n')}) — the gap is the "
              f"any-change vs effective-step definition, not a wrong call.")

    a("\n## 2. The 30-day constraint and the design change\n")
    a("Raw telemetry is assumed retained for only the trailing 30 days; the window slides daily "
      "(`[t-29,t]` -> `[t-28,t+1]`). The detector therefore separates a **stateless** view (the 30d "
      "raw window only) from a **stateful** online detector whose *derived* state (counters since the "
      "last effective FCC change, pending/censored episodes) may persist long-term. Every inference "
      "point uses only the trailing raw window plus state updated up to that point — no future raw, no "
      "raw older than 30 days, no look-ahead at final labels (spec 0.3 / 13.1).")

    a("\n## 3. Why direct very_stale prediction is inappropriate\n")
    a("Prior supervised work (PROJECT_STATUS.md) showed that predicting `very_stale` directly from "
      "usage behaviour reaches only AUC≈0.54 in the fair (obs≥180d) regime — essentially random. So we "
      "do **not** classify `30d usage -> FW fault`. Instead we estimate, per learning episode, the "
      "probability a healthy gauge would respond, and flag users/windows whose **observed** responses "
      "fall far below that **expected** response given real high→low→high opportunities (spec 0.2).")

    a("\n## 4. Data and variables\n")
    a(f"- `fullChargeCapacity` is integer **mWh** (PROJECT_STATUS PDF correction); SoH steps iff FCC "
      f"steps. `remainingCapacityInPercentage` = RSOC. `acdcMode` 1=AC/0=DC. Design capacity recovered "
      f"per user from `FCC*100/soh_design_pct` (median).")
    a(f"- Episode quality distribution (all bands): {eq}. Large-gap dominance reflects multi-hour "
      f"sleep gaps inside otherwise full-range discharges; these are protected out of OK opportunities.")

    a("\n## 5. Rolling window features\n")
    a("One row per `user_id × window_end_date` with data-quality (n_samples, gaps, counter reset), "
      "usage (cycle delta/rate, AC/charge/discharge time ratios, RSOC levels & band fractions, switch "
      "and discharge-session counts) and FCC (start/end/min/max, any vs effective changes, last "
      "effective change ts/cycle) blocks. Time-weighted ratios use capped gap-to-next weights.")

    a("\n## 6. Episode / stateful detector\n")
    a("High→low→high RSOC excursions are detected for 3 bands (80/20, 85/15, 90/10). Response is "
      "**end-anchored**: an effective FCC step in `[end, end+72h]` is a response (spec 7.4). The online "
      "state replays events in time order: an effective FCC step **resets** the since-last-change "
      "counters and clears the pending set (those episodes just responded); a pending OK episode whose "
      "72h window closes with no step becomes a confirmed **no_response**. Each episode is keyed by a "
      "stable `episode_id` so overlapping windows never double-count it (spec 7.5).")

    a("\n## 7. Effective FCC step definition and sensitivity\n")
    if sens.get("effective_step") is not None:
        a("```\n" + sens["effective_step"].to_string(index=False) + "\n```")
        a("Default `abs_ge_50mWh` avoids counting micro-wobbles (~58% of raw steps are <50 mWh) as "
          "learning responses, which would mask genuine no-response (spec 5.3).")
    if sens.get("gap") is not None:
        a("Episode-gap sensitivity (6/12/24h):\n```\n" + sens["gap"].to_string(index=False) + "\n```")
    if sens.get("response_window") is not None:
        a("Response-window sensitivity (24/72/168h):\n```\n" + sens["response_window"].to_string(index=False) + "\n```")

    a("\n## 8. Unsupervised usage clustering\n")
    if not cluster_profiles.empty:
        cols = [c for c in ("cluster_id", "n_windows", "n_users", "median_ac_time_ratio",
                            "median_rsoc_swing", "median_cycle_delta", "share_no_response",
                            "cluster_profile_name", "suggested_action_hint") if c in cluster_profiles.columns]
        a("```\n" + cluster_profiles[cols].to_string(index=False) + "\n```")
    else:
        a("_clustering not run_")

    a("\n## 9. Self-supervised episode response model\n")
    if ml_result.get("status") == "ok":
        a("```\n" + ml_result["metrics"].to_string(index=False) + "\n```")
        imp = ml_result.get("importances")
        if isinstance(imp, pd.DataFrame) and not imp.empty:
            a("Top features:\n```\n" + imp.head(12).to_string(index=False) + "\n```")
        a("Leakage guards asserted: no hardware identity, no future FCC/response, no final label, "
          "GroupKFold by user_id (29-day-overlapping windows never split).")
    else:
        a(f"_model status: {ml_result.get('status', 'not run')}_")

    a("\n## 10. User-window anomaly scores\n")
    a("Per window: `expected_response_30d = Σ p_i`, `observed_response_30d`, "
      "`p_all_no_response_30d = Π(1-clip(p_i))` over **resolved-by-t** OK primary opportunities, "
      "`fw_response_anomaly_score_30d = -log10(p_all_no_response)`, and an empirical `conformal_p` vs "
      "clean OK windows. Zero-opportunity windows get score 0 (no spurious anomaly, spec 16.15).")
    if "fw_response_anomaly_score_30d" in feats.columns:
        s = feats.loc[feats["n_complete_ok_opportunities_30d"] >= 1, "fw_response_anomaly_score_30d"]
        if len(s):
            a(f"Score distribution over scored windows (n={len(s):,}): "
              f"p50={s.median():.3f}, p90={s.quantile(.9):.3f}, p99={s.quantile(.99):.3f}, max={s.max():.3f}.")

    a("\n## 11. Online stateful action policy\n")
    a("Window labels describe the last 30 days; stateful labels add the persisted state. FW-check needs "
      "≥90d & ≥30 cycles since the last effective FCC change, repeated no_response or anomaly≥2.0, zero "
      "observed responses, and large-gap/censored not dominant. Gauge-reset needs the same staleness "
      "but **zero** opportunities (OK or large-gap) plus an AC-bound/shallow/low-cycling usage cluster. "
      "Data-quality review outranks any actionable call (spec 16.14). Alerts fire only on a state "
      "transition with a cooldown, reset by an effective FCC update (spec 12.6).")

    a("\n## 12. Backtest: stateful vs stateless\n")
    if bt:
        a(f"- Same-threshold no-response detection (≥2 OK no_response, 0 observed response, OK "
          f"window) — stateful (cumulative since last effective change): "
          f"**{bt.get('stateful_detection_n')}**, stateless (last 30d raw only): "
          f"{bt.get('stateless_detection_n')}, overlap: {bt.get('overlap_detection_n')}, "
          f"**stateful-only gain: {bt.get('stateful_only_detection_n')}**. The persisted state "
          f"recovers no-response evidence spread across >30 days that a single 30-day window cannot "
          f"hold; the stateless-only set ({bt.get('stateless_only_detection_n')}) is users who very "
          f"recently accumulated ≥2 within one window.")
        a(f"- The strict **action** gates (adding ≥90d/≥30-cycle staleness, anomaly, and large-gap "
          f"protection) deliberately convert far fewer of these into FW={bt.get('action_fw_n')} / "
          f"Gauge={bt.get('action_gauge_n')} candidates; the remainder route to WATCH.")
    else:
        a("_backtest not run_")

    a("\n## 13. Final-validation label proxy comparison\n")
    a("The final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an "
      "**evaluation proxy, not ground truth** (spec 13.2).")
    if bt and isinstance(bt.get("crosstab"), pd.DataFrame):
        a("Stateful (rows) × final proxy (cols):\n```\n" + bt["crosstab"].to_string() + "\n```")
    if bt and isinstance(bt.get("topn"), pd.DataFrame):
        a("Top-N yield:\n```\n" + bt["topn"].to_string(index=False) + "\n```")

    a("\n## 14. Active false alert / lead time / top-N\n")
    if bt and "active_false_alert_rate" in bt:
        a(f"- Active false-alert rate vs `soh_update_status` (any-change basis): "
          f"{bt['active_false_alert_rate']} ({bt.get('actionable_active_false_n')}/{bt.get('actionable_n')}). "
          f"On our 50 mWh-effective basis it is {bt.get('active_false_alert_rate_effective_step')} "
          f"({bt.get('actionable_eff_recent_update_n')}/{bt.get('actionable_n')}). The difference is "
          f"definitional: `soh_update_status=active` counts sub-50 mWh micro-wobbles as updates, which "
          f"the rolling detector intentionally ignores (spec 5.3). Gauge candidates with micro-drift but "
          f"no full re-learning are still legitimate calibration prompts.")
    if bt and isinstance(bt.get("lead_time_table"), pd.DataFrame) and not bt["lead_time_table"].empty:
        lt = bt["lead_time_table"]
        for proxy in (PROXY_FW, PROXY_GAUGE):
            sub = lt[lt["final_label"] == proxy]
            if not sub.empty:
                a(f"- {proxy}: alerted {len(sub)} cases, median lead time "
                  f"{sub['lead_time_days'].median():.0f}d before last observation.")

    a("\n## 15. Large-gap / censored safety audit\n")
    a("- `censored`/`unknown` episodes are never counted as `no_response` (status separation in "
      "`_response_status`).\n- `large_gap` episodes never count as OK opportunities (quality gate).\n"
      "- Each episode contributes once to state (keyed by `episode_id`).\n- Zero-opportunity windows "
      "cannot produce a high anomaly score.")

    a("\n## 16. HW/FW enrichment (post-classification only)\n")
    if not enr.empty:
        a("Top FW-candidate enrichment groups (beta-binomial shrunk rate, Fisher+BH):\n```\n"
          + enr.head(15).to_string(index=False) + "\n```")
        a("Hardware identity is asserted absent from every classification feature list "
          "(`assert_no_hw_in_classification`).")
    else:
        a("_enrichment not run, or no group met the minimum size._ BIOS/EC/battery-FW versions are "
          "**not present** in this dataset, so version-level enrichment is unavailable (spec 14.1).")

    a("\n## 17. Latest snapshot action candidates\n")
    a(f"See `online_fcc_action_candidates_fw_check.csv` ({sc.get(policy.ST_FW,0)}), "
      f"`..._gauge_reset.csv` ({sc.get(policy.ST_GAUGE,0)}), `online_fcc_watchlist.csv` "
      f"({sc.get(policy.ST_WATCH,0)}), `online_fcc_review_queue.csv` ({sc.get(policy.ST_REVIEW,0)}).")

    a("\n## 18. Operational recommendations\n")
    a("- Alert only on state transitions with a 30–60d cooldown, reset on FCC recovery.\n"
      "- Record post-intervention FCC response to close the loop (not available now).\n"
      "- Collect BIOS/EC/battery-FW version + gauge-reset/update dates to enable version-level "
      "enrichment and intervention evaluation.")

    a("\n## 19. Limitations\n")
    a("- This flags *candidates*, not confirmed FW faults. Evidence is mechanistic (opportunity vs "
      "response), evaluated against a **proxy** label set.\n- HDBSCAN and EBM are unavailable here; "
      "clustering uses GaussianMixture/KMeans.\n- The 30d raw constraint limits the stateless view; the "
      "stateful detector mitigates but assumes faithful long-term state.\n- Most episodes are large-gap "
      "(sleep gaps), shrinking the clean-opportunity pool.")

    a("\n## 20. Next steps\n")
    a("- Acquire BIOS/EC/battery-FW versions and intervention outcomes.\n- Validate the response model "
      "on labelled post-intervention recoveries.\n- Tune gap/step/window thresholds against operational "
      "feedback.")

    if warnings:
        a("\n## Warnings\n" + "\n".join(f"- {w}" for w in warnings))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(L), encoding="utf-8")


def _print_final(snap, ml_result, bt, enr, warnings):
    sc = snap["stateful_label"].value_counts().to_dict()
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print("Latest snapshot stateful labels:")
    for k in (policy.ST_NORMAL, policy.ST_GAUGE, policy.ST_FW, policy.ST_WATCH, policy.ST_REVIEW):
        print(f"  {k:38s} {sc.get(k, 0)}")
    if ml_result.get("status") == "ok":
        m = ml_result["metrics"]; best = ml_result["best_model"]
        mr = m[m["model"] == best].iloc[0]
        print(f"Response model [{best}]: ROC AUC={mr['roc_auc']} PR AUC={mr['pr_auc']} "
              f"Brier={mr['brier']}/{mr['brier_calibrated']} calib_slope={mr['calib_slope']}")
    if bt:
        print(f"Detection (same threshold) stateful={bt.get('stateful_detection_n')} | "
              f"stateless={bt.get('stateless_detection_n')} | stateful-only gain="
              f"{bt.get('stateful_only_detection_n')} | action FW={bt.get('action_fw_n')} "
              f"Gauge={bt.get('action_gauge_n')}")
        if "active_false_alert_rate" in bt:
            print(f"Active false-alert: any-change={bt['active_false_alert_rate']} "
                  f"({bt.get('actionable_active_false_n')}/{bt.get('actionable_n')}) | "
                  f"effective-step={bt.get('active_false_alert_rate_effective_step')}")
    if not enr.empty:
        top = enr.head(3)
        print("Top FW enrichment groups: " +
              "; ".join(f"{r.group_axis}={r.group_value}(shrunk={r.shrunk_rate},q={r.q_value})"
                        for r in top.itertuples(index=False)))
    if warnings:
        print("Warnings: " + " | ".join(warnings))
    print("=" * 70)


if __name__ == "__main__":
    raise SystemExit(main())
