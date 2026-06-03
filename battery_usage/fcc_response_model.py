"""ML SHADOW analysis for the FCC classifier (spec section 6) — never decides a label.

Three shadow models, all auxiliary to the rule-based labels:

  6.1 Episode-level response model: P(FCC responds within 72h | learning episode), trained
      ONLY on episode-start/episode-internal features (no leakage, no hardware identity,
      no future signal), grouped by user (GroupKFold). Per user we then compare observed
      vs model-EXPECTED tail responses; a large NEGATIVE residual (far fewer updates than a
      healthy gauge would give) yields an ``ml_fw_support_score`` used to PRIORITISE — not
      decide — FW-check.
  6.2 Unsupervised clustering of the no/low-change + WATCH cohort (KMeans/GMM; hdbscan not
      installed) to describe structure (AC-bound / shallow / high-opportunity-no-response).
  6.3 A shallow surrogate decision tree fit to the rule labels, for external explanation
      of which features the rules effectively branch on (reports fidelity).

Hardware identity is forbidden as a feature throughout.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import _sorted_unique, fcc_step_indicator, _short, EPISODE_THRESHOLDS

# Episode features the model may use (all knowable at/within the episode). Hardware
# identity, future FCC/cycle, and any response_status are FORBIDDEN.
EPISODE_FEATURES = [
    "start_rsoc", "low_rsoc", "end_rsoc", "rsoc_depth",
    "episode_duration_h", "discharge_duration_h", "recharge_duration_h",
    "cycle_delta_episode", "ac_ratio_episode", "charge_ratio_episode", "discharge_ratio_episode",
    "time_since_last_fcc_change_before_episode_h", "fcc_value_before_episode",
    "soh_before_episode", "cycle_count_before_episode", "obs_age_days_at_episode",
    "recent_ac_time_ratio_before_episode", "recent_rsoc_swing_before_episode",
]
FORBIDDEN_SUBSTRINGS = ("fcc_changed", "response_status", "final_label", "subreason",
                        "device_model", "batt_vendor", "batt_fru", "manufacturer",
                        "serial", "uuid", "mtm")

_RECENT_WINDOW_DAYS = 14.0


# --------------------------------------------------------------------------- #
# Episode feature enrichment (re-derives episode-start context from the series)
# --------------------------------------------------------------------------- #
def enrich_episode_features(df_ts: pd.DataFrame, eps: pd.DataFrame,
                            min_mwh: float = 1.0) -> pd.DataFrame:
    """Add the EPISODE_FEATURES columns to ``eps`` using the raw series.

    Episode idx columns are positional within each user's time-sorted, de-duplicated
    frame; we reconstruct that frame per user and read context at the episode start.
    """
    feats_by_key: Dict[Tuple[str, int, int, int], dict] = {}
    need = {"remainingCapacityInPercentage", "fullChargeCapacity", "cycleCount",
            "acdcMode", "timestamp"}
    has_charge = "chargeStatus" in df_ts.columns
    has_soh = "soh_design_pct" in df_ts.columns
    users = set(eps["user_id"].unique())
    for uid, g in df_ts[df_ts["user_id"].isin(users)].groupby("user_id", sort=False):
        g = _sorted_unique(g)
        ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
        fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
        cyc = g["cycleCount"].to_numpy(dtype=float)
        ac = (g["acdcMode"] == 1).to_numpy()
        cs = g["chargeStatus"].to_numpy() if has_charge else None
        soh = g["soh_design_pct"].to_numpy(dtype=float) if has_soh else None
        is_step, _ = fcc_step_indicator(fcc, min_mwh)
        step_ns = ts_ns[np.flatnonzero(is_step)]
        first_ns = int(ts_ns[0])
        sub = eps[eps["user_id"] == uid]
        for s, lo, e in zip(sub["start_idx"], sub["low_idx"], sub["end_idx"]):
            s, lo, e = int(s), int(lo), int(e)
            seg = slice(s, e + 1)
            start_ns = int(ts_ns[s])
            prior = step_ns[step_ns < start_ns]
            since = (start_ns - int(prior[-1])) / 3.6e12 if prior.size else (start_ns - first_ns) / 3.6e12
            rwin = start_ns - int(_RECENT_WINDOW_DAYS * 86400 * 1e9)
            rmask = (ts_ns >= rwin) & (ts_ns <= start_ns)
            rr = rsoc[rmask]
            feats_by_key[(uid, s, lo, e)] = {
                "rsoc_depth": float(rsoc[s] - rsoc[lo]),
                "episode_duration_h": (int(ts_ns[e]) - start_ns) / 3.6e12,
                "discharge_duration_h": (int(ts_ns[lo]) - start_ns) / 3.6e12,
                "recharge_duration_h": (int(ts_ns[e]) - int(ts_ns[lo])) / 3.6e12,
                "ac_ratio_episode": float(ac[seg].mean()),
                "charge_ratio_episode": float((cs[seg] == 1).mean()) if cs is not None else float("nan"),
                "discharge_ratio_episode": float((cs[seg] == 2).mean()) if cs is not None else float("nan"),
                "time_since_last_fcc_change_before_episode_h": float(since),
                "fcc_value_before_episode": float(fcc[s]),
                "soh_before_episode": float(soh[s]) if soh is not None else float("nan"),
                "cycle_count_before_episode": float(cyc[s]),
                "obs_age_days_at_episode": (start_ns - first_ns) / 8.64e13,
                "recent_ac_time_ratio_before_episode": float(ac[rmask].mean()) if rmask.any() else float("nan"),
                "recent_rsoc_swing_before_episode": float(np.nanmax(rr) - np.nanmin(rr)) if rr.size else float("nan"),
            }
    add = pd.DataFrame(
        [feats_by_key.get((r.user_id, int(r.start_idx), int(r.low_idx), int(r.end_idx)), {})
         for r in eps.itertuples(index=False)],
        index=eps.index,
    )
    out = pd.concat([eps, add], axis=1)
    return out


# --------------------------------------------------------------------------- #
# 6.1 episode response model
# --------------------------------------------------------------------------- #
def train_response_model(eps_feat: pd.DataFrame) -> Dict[str, object]:
    """Train P(response in 72h) on complete-window OK episodes, grouped by user."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import GroupKFold, cross_val_predict
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
    from sklearn.calibration import calibration_curve

    train = eps_feat[(eps_feat["episode_quality"] == "ok")
                     & (eps_feat["window_72h_complete"] == True)  # noqa: E712
                     & (eps_feat["fcc_changed_72h"].notna())].copy()
    train["fcc_changed_72h"] = train["fcc_changed_72h"].astype(int)
    th = pd.get_dummies(train["threshold_name"], prefix="band")
    X = pd.concat([train[EPISODE_FEATURES], th], axis=1).astype(float)
    # guard: assert no forbidden feature leaked in
    assert not any(any(s in c.lower() for s in FORBIDDEN_SUBSTRINGS) for c in X.columns), \
        "forbidden feature leaked into the response model"
    # NB: NaN imputation lives INSIDE the CV pipeline (per-fold median), not globally, so the
    # held-out fold never informs the fill — keeps the reported CV metrics honest.
    y = train["fcc_changed_72h"].to_numpy()
    groups = train["user_id"].to_numpy()

    n_splits = int(min(5, max(2, pd.Series(groups).nunique())))
    gkf = GroupKFold(n_splits=n_splits)
    lr = Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler()),
                   ("lr", LogisticRegression(max_iter=2000, class_weight="balanced"))])
    proba = {"logreg": cross_val_predict(lr, X, y, cv=gkf, groups=groups, method="predict_proba")[:, 1]}
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        hgb = HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.08)  # NaN-native
        proba["hgb"] = cross_val_predict(hgb, X, y, cv=gkf, groups=groups, method="predict_proba")[:, 1]
    except Exception:
        pass

    metrics = []
    for name, p in proba.items():
        frac_pos, mean_pred = calibration_curve(y, p, n_bins=10, strategy="quantile")
        metrics.append({
            "model": name, "n_episodes": int(len(y)), "n_users": int(pd.Series(groups).nunique()),
            "positive_rate": round(float(y.mean()), 4),
            "roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4),
            "_calib_pred": list(np.round(mean_pred, 4)), "_calib_obs": list(np.round(frac_pos, 4)),
        })
    # final LR fit on all data for coefficients (standardized).
    lr.fit(X, y)
    coefs = pd.DataFrame({"feature": X.columns,
                          "coef": np.round(lr.named_steps["lr"].coef_[0], 4)}) \
        .sort_values("coef", key=np.abs, ascending=False)

    best = "hgb" if "hgb" in proba else "logreg"
    preds = train[["user_id", "threshold_name", "start_ts", "start_idx", "low_idx", "end_idx",
                   "fcc_changed_72h"]].copy()
    preds["pred_response_prob"] = proba[best]
    preds["model"] = best
    return {"predictions": preds, "metrics": pd.DataFrame(metrics).drop(columns=["_calib_pred", "_calib_obs"]),
            "calibration": {m["model"]: (m["_calib_pred"], m["_calib_obs"]) for m in metrics},
            "coefficients": coefs, "best_model": best, "X_columns": list(X.columns)}


def user_response_residuals(preds: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    """Per user: expected vs observed TAIL responses + FW support score (shadow only).

    Tail = complete-window OK episodes that start at/after the user's last FCC change (the
    judgeable opportunities during the flat run). Expected = sum of model response
    probabilities; a large negative residual_z (far fewer updates than a healthy gauge
    would give over the same opportunities) raises ml_fw_support_score.
    """
    p = preds.merge(feat[["user_id", "last_fcc_change_ts"]], on="user_id", how="left")
    p["start_ts"] = pd.to_datetime(p["start_ts"])
    p["last_fcc_change_ts"] = pd.to_datetime(p["last_fcc_change_ts"])
    p = p[p["start_ts"] >= p["last_fcc_change_ts"]]            # tail opportunities only
    rows = []
    for uid, g in p.groupby("user_id"):
        exp = float(g["pred_response_prob"].sum())
        obs = float(g["fcc_changed_72h"].sum())
        var = float((g["pred_response_prob"] * (1 - g["pred_response_prob"])).sum())
        z = (obs - exp) / np.sqrt(var) if var > 1e-9 else 0.0
        n_opp = int(len(g))
        # FW support: high when observed << expected (gauge under-responds) AND opportunities exist.
        sig = 1.0 / (1.0 + np.exp(z))            # z<<0 -> ~1
        opp_factor = min(n_opp / 3.0, 1.0)
        rows.append({
            "user_id": uid, "n_complete_ok_opportunities": n_opp,
            "expected_tail_responses_72h": round(exp, 3),
            "observed_tail_responses_72h": round(obs, 3),
            "response_residual": round(obs - exp, 3),
            "response_residual_z": round(float(z), 3),
            "ml_fw_support_score_0_100": round(float(100 * sig * opp_factor), 1),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 6.2 clustering
# --------------------------------------------------------------------------- #
CLUSTER_FEATURES = [
    "flat_tail_days", "tail_cycle_delta", "tail_ac_time_ratio", "tail_min_rsoc",
    "tail_rsoc_swing", "tail_n_80_20_80_ok", "tail_n_80_20_80_large_gap",
    "tail_n_unresponded_80_20_80_complete_window", "fcc_changes_per_100_cycles",
    "fcc_change_rate_per_100d",
]


def cluster_candidates(feat_labeled: pd.DataFrame, target_labels) -> pd.DataFrame:
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    sub = feat_labeled[feat_labeled["final_label"].isin(target_labels)].copy()
    if len(sub) < 8:
        sub["cluster_id"] = -1
        sub["cluster_description"] = "too_few_for_clustering"
        return sub[["user_id", "final_label", "cluster_id", "cluster_description"]]
    X = sub[CLUSTER_FEATURES].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True)).to_numpy(dtype=float)
    Xs = StandardScaler().fit_transform(X)
    best_k, best_sil, best_lab = 2, -1.0, None
    for k in range(2, 7):
        if len(sub) <= k:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
        sil = silhouette_score(Xs, km.labels_)
        if sil > best_sil:
            best_k, best_sil, best_lab = k, sil, km.labels_
    sub["cluster_id"] = best_lab
    # describe each cluster from standardized feature means -> a short rule-of-thumb label.
    desc = {}
    means = sub.groupby("cluster_id")[CLUSTER_FEATURES].mean()
    for cid, row in means.iterrows():
        tags = []
        if row["tail_ac_time_ratio"] >= 0.80:
            tags.append("AC_BOUND")
        if row["tail_min_rsoc"] > 20 or row["tail_rsoc_swing"] < 60:
            tags.append("SHALLOW_RANGE")
        if row["tail_n_unresponded_80_20_80_complete_window"] >= 2:
            tags.append("HIGH_OPP_NO_RESPONSE")
        if row["tail_n_80_20_80_large_gap"] >= 2 and row["tail_n_80_20_80_ok"] < 1:
            tags.append("LARGE_GAP_OPP")
        if row["tail_cycle_delta"] < 20:
            tags.append("LOW_CYCLING")
        desc[cid] = "+".join(tags) if tags else "MIXED"
    sub["cluster_description"] = sub["cluster_id"].map(desc)
    sub.attrs["best_k"] = best_k
    sub.attrs["silhouette"] = round(float(best_sil), 4)
    return sub[["user_id", "final_label", "cluster_id", "cluster_description"]]


# --------------------------------------------------------------------------- #
# 6.3 surrogate decision tree
# --------------------------------------------------------------------------- #
SURROGATE_FEATURES = [
    "flat_tail_days", "obs_days", "cycle_delta", "tail_cycle_delta", "tail_min_rsoc",
    "tail_max_rsoc", "tail_rsoc_swing", "tail_ac_time_ratio", "tail_n_80_20_80_ok",
    "tail_n_80_20_80_large_gap", "tail_n_unresponded_80_20_80_complete_window",
    "tail_n_90_10_90_ok", "tail_n_unresponded_90_10_90_complete_window",
    "fcc_changes", "fcc_changes_per_100_cycles", "fcc_change_rate_per_100d",
    "fcc_no_or_low_change_candidate",
]


def surrogate_tree(feat_labeled: pd.DataFrame, max_depth: int = 3) -> Dict[str, object]:
    from sklearn.tree import DecisionTreeClassifier, export_text
    from sklearn.metrics import accuracy_score

    cols = [c for c in SURROGATE_FEATURES if c in feat_labeled.columns]
    assert not any(any(s in c.lower() for s in ("device", "vendor", "batt_fru", "manufacturer"))
                   for c in cols), "hardware identity must not be a surrogate feature"
    X = feat_labeled[cols].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True)).astype(float)
    y = feat_labeled["final_label"].to_numpy()
    tree = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=10, random_state=0).fit(X, y)
    fidelity = float(accuracy_score(y, tree.predict(X)))
    rules = export_text(tree, feature_names=list(cols))
    return {"tree": tree, "feature_names": cols, "fidelity": round(fidelity, 4), "rules": rules}
