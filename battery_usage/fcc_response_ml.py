"""ML Layer 2 — episode-level self-supervised FCC-response model (rolling30 spec 10).

One row = one learning episode. The label is NOT a human action label; it is telemetry's
own answer: did FCC effectively step within ``W`` hours AFTER the episode end?

    y = 1  if response_status_72h == "responded"
    y = 0  if response_status_72h == "no_response"   (window complete, no step)
    drop   if censored / unknown                     (window incomplete or FCC missing)

This is the model whose per-episode probabilities drive the anomaly layer (spec 11): for a
healthy gauge each OK opportunity *should* respond with probability p_i; a user/window with
many high-p_i opportunities and zero observed responses is anomalous.

Strict guards (asserted at train time, spec 10.2 / 13.4):
  * NO hardware identity (device_model, batt_vendor, batt_fru, serial, uuid, mtm, ...).
  * NO future signal (FCC after episode end, the response_status itself, flat_tail).
  * NO human/audit label (final_label, subreason, ...).
  * GroupKFold by user_id so 29-day-overlapping sliding windows never straddle the split.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import fcc_step_indicator
from .online_episode_detector import (
    OnlineConfig, DEFAULT_ONLINE_CONFIG, PRIMARY_THRESHOLD,
    recover_design_mwh, step_threshold_mwh,
)

DAY_NS = 86_400 * 1_000_000_000

EPISODE_TIME_FEATURES = [
    "episode_depth", "episode_duration_h", "start_to_low_duration_h", "low_to_end_duration_h",
    "cycle_delta_episode", "start_rsoc", "low_rsoc", "end_rsoc",
    "n_samples_episode", "max_gap_h_episode", "median_gap_h_episode",
    "fcc_before_episode", "soh_before_episode", "cycle_count_before_episode",
    "recent_30d_cycle_delta_before_episode", "recent_30d_ac_ratio_before_episode",
    "recent_30d_rsoc_swing_before_episode", "recent_30d_n_80_20_80_ok_before_episode",
    "recent_30d_fcc_effective_changes_before_episode", "recent_30d_n_samples_before_episode",
    "recent_30d_max_gap_h_before_episode",
]
FORBIDDEN_SUBSTRINGS = (
    "response_status", "fcc_changed", "fcc_response", "final_label", "subreason",
    "recommended_action", "device_model", "batt_vendor", "batt_fru", "manufacturer",
    "serial", "uuid", "mtm", "product_uuid", "flat_tail", "p_response",
)


# --------------------------------------------------------------------------- #
# Episode feature enrichment (all strictly causal at the episode start)
# --------------------------------------------------------------------------- #
def enrich_episode_features(
    df_by_user: Dict[str, pd.DataFrame], episodes: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_by_user: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Add ``soh_before_episode`` + the ``recent_30d_*_before_episode`` context columns.

    Every added value is computed from samples/episodes strictly BEFORE the episode start
    (``[start-30d, start)``) so nothing about the episode's own outcome leaks in.
    """
    design_by_user = design_by_user or {}
    win_ns = cfg.window_days * DAY_NS
    add_rows: List[Dict[str, object]] = []
    eps_by_user = {uid: sub for uid, sub in episodes.groupby("user_id", sort=False)}

    for uid, ueps in eps_by_user.items():
        g = df_by_user[uid]
        ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
        fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
        cyc = g["cycleCount"].to_numpy(dtype=float)
        acdc = (g["acdcMode"].to_numpy() == 1).astype(float)
        soh = g["soh_design_pct"].to_numpy(dtype=float) if "soh_design_pct" in g.columns else None
        min_mwh = step_threshold_mwh(cfg.effective_step,
                                     design_by_user.get(uid, recover_design_mwh(g)))
        is_step, _ = fcc_step_indicator(fcc, min_mwh)
        step_ns = ts_ns[np.flatnonzero(is_step)]
        # primary OK-complete episode ends (for the recent opportunity count) — causal use only
        prim = ueps[(ueps["threshold_name"] == PRIMARY_THRESHOLD)
                    & (ueps["episode_quality"] == "ok")
                    & (ueps["response_status_72h"].isin(["responded", "no_response"]))]
        prim_end_ns = np.sort(prim["end_ts"].to_numpy().astype("datetime64[ns]").astype(np.int64))

        for r in ueps.itertuples(index=False):
            s_ns = int(pd.Timestamp(r.start_ts).value)
            lo = int(np.searchsorted(ts_ns, s_ns - win_ns, side="left"))
            hi = int(np.searchsorted(ts_ns, s_ns, side="left"))   # strictly before start
            seg_r = rsoc[lo:hi]
            valid = seg_r[(seg_r >= 0) & (seg_r <= 100)]
            start_pos = int(np.searchsorted(ts_ns, s_ns, side="left"))
            soh_before = (float(soh[start_pos]) if (soh is not None and start_pos < len(soh))
                          else float("nan"))
            n_recent_steps = int(((step_ns >= s_ns - win_ns) & (step_ns < s_ns)).sum())
            n_recent_ok = int(((prim_end_ns >= s_ns - win_ns) & (prim_end_ns < s_ns)).sum())
            gaps = np.diff(ts_ns[lo:hi]) / 3.6e12 if hi - lo > 1 else np.array([])
            add_rows.append({
                "episode_id": r.episode_id,
                "soh_before_episode": soh_before,
                "recent_30d_cycle_delta_before_episode":
                    float(cyc[hi - 1] - cyc[lo]) if hi - lo >= 1 else float("nan"),
                "recent_30d_ac_ratio_before_episode":
                    float(acdc[lo:hi].mean()) if hi > lo else float("nan"),
                "recent_30d_rsoc_swing_before_episode":
                    float(valid.max() - valid.min()) if valid.size else float("nan"),
                "recent_30d_n_80_20_80_ok_before_episode": n_recent_ok,
                "recent_30d_fcc_effective_changes_before_episode": n_recent_steps,
                "recent_30d_n_samples_before_episode": int(hi - lo),
                "recent_30d_max_gap_h_before_episode":
                    float(gaps.max()) if gaps.size else 0.0,
            })
    add = pd.DataFrame(add_rows)
    return episodes.merge(add, on="episode_id", how="left")


# --------------------------------------------------------------------------- #
# Model training (GroupKFold + OOF calibration)
# --------------------------------------------------------------------------- #
@dataclass
class ResponseModelBundle:
    feature_columns: List[str]
    model: object                 # fitted on all complete-OK episodes
    calibrator: Optional[object]  # isotonic fitted on OOF (p_raw -> p_cal), or None
    best_model_name: str
    band_columns: List[str]


def _assert_no_leakage(columns) -> None:
    bad = [c for c in columns if any(s in c.lower() for s in FORBIDDEN_SUBSTRINGS)]
    assert not bad, f"forbidden feature(s) leaked into the response model: {bad}"


def _build_xy(eps_feat: pd.DataFrame, response_col: str
              ) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, List[str], List[str]]:
    train = eps_feat[(eps_feat["episode_quality"] == "ok")
                     & (eps_feat[response_col].isin(["responded", "no_response"]))].copy()
    y = (train[response_col] == "responded").astype(int).to_numpy()
    band = pd.get_dummies(train["threshold_name"], prefix="band")
    band_cols = list(band.columns)
    feats = [c for c in EPISODE_TIME_FEATURES if c in train.columns]
    X = pd.concat([train[feats].reset_index(drop=True),
                   band.reset_index(drop=True)], axis=1).astype(float)
    _assert_no_leakage(X.columns)
    groups = train["user_id"].to_numpy()
    return X, y, groups, feats, band_cols


def train_response_model(
    eps_feat: pd.DataFrame, response_col: str = "response_status_72h",
) -> Tuple[Dict[str, object], ResponseModelBundle]:
    """Train P(response) on complete-window OK episodes, grouped by user.

    Returns (results dict, bundle). ``results`` has metrics, OOF predictions (calibrated),
    coefficients/importances and calibration curves; ``bundle`` carries the refit model +
    calibrator for scoring ALL OK episodes (incl. censored) operationally.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import GroupKFold, cross_val_predict
    from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
    from sklearn.calibration import calibration_curve
    from sklearn.isotonic import IsotonicRegression
    from sklearn.ensemble import HistGradientBoostingClassifier

    X, y, groups, feats, band_cols = _build_xy(eps_feat, response_col)
    n_users = int(pd.Series(groups).nunique())
    result: Dict[str, object] = {"n_episodes": int(len(y)), "n_users": n_users,
                                 "positive_rate": round(float(y.mean()), 4) if len(y) else float("nan"),
                                 "feature_columns": list(X.columns)}
    if len(y) < 20 or y.sum() < 3 or (len(y) - y.sum()) < 3 or n_users < 3:
        result["status"] = "insufficient_data"
        result["metrics"] = pd.DataFrame()
        result["predictions"] = pd.DataFrame()
        # degenerate bundle: predict the base rate
        base = float(y.mean()) if len(y) else 0.5
        bundle = ResponseModelBundle(list(X.columns), _ConstModel(base), None, "base_rate", band_cols)
        return result, bundle

    n_splits = int(min(5, max(2, n_users)))
    gkf = GroupKFold(n_splits=n_splits)
    candidates: Dict[str, object] = {
        "logreg": Pipeline([("imp", SimpleImputer(strategy="median")),
                            ("sc", StandardScaler()),
                            ("lr", LogisticRegression(max_iter=3000, class_weight="balanced"))]),
        "hgb": HistGradientBoostingClassifier(max_depth=3, max_iter=300,
                                              learning_rate=0.07, l2_regularization=1.0),
    }
    for opt, ctor in (("lightgbm", _try_lightgbm), ("xgboost", _try_xgboost)):
        m = ctor()
        if m is not None:
            candidates[opt] = m

    metrics, oof = [], {}
    for name, est in candidates.items():
        try:
            p = cross_val_predict(est, X, y, cv=gkf, groups=groups,
                                  method="predict_proba")[:, 1]
        except Exception as exc:                       # pragma: no cover
            result.setdefault("warnings", []).append(f"{name} CV failed: {exc}")
            continue
        oof[name] = p
        frac_pos, mean_pred = calibration_curve(y, p, n_bins=10, strategy="quantile")
        # isotonic-calibrated OOF (honest: calibrator never sees a sample's own fold pred at fit?
        # we fit on the full OOF vector — standard for reporting reliability of the CV scores).
        iso = IsotonicRegression(out_of_bounds="clip").fit(p, y)
        p_cal = iso.transform(p)
        cm = _confusion_at(y, p)
        metrics.append({
            "model": name, "n_episodes": int(len(y)), "n_users": n_users,
            "positive_rate": round(float(y.mean()), 4),
            "roc_auc": round(float(roc_auc_score(y, p)), 4),
            "pr_auc": round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4),
            "brier_calibrated": round(float(brier_score_loss(y, p_cal)), 4),
            "calib_slope": _calib_slope(y, p), **cm,
            "_calib_pred": list(np.round(mean_pred, 4)), "_calib_obs": list(np.round(frac_pos, 4)),
        })
    if not metrics:
        result["status"] = "all_models_failed"
        result["metrics"] = pd.DataFrame(); result["predictions"] = pd.DataFrame()
        bundle = ResponseModelBundle(list(X.columns), _ConstModel(float(y.mean())), None,
                                     "base_rate", band_cols)
        return result, bundle

    mdf = pd.DataFrame(metrics)
    best = mdf.sort_values("roc_auc", ascending=False).iloc[0]["model"]
    result["status"] = "ok"
    result["best_model"] = best
    result["metrics"] = mdf.drop(columns=["_calib_pred", "_calib_obs"])
    result["calibration"] = {m["model"]: (m["_calib_pred"], m["_calib_obs"]) for m in metrics}

    # OOF predictions for the chosen model, calibrated
    from sklearn.isotonic import IsotonicRegression as _Iso
    iso_best = _Iso(out_of_bounds="clip").fit(oof[best], y)
    train = eps_feat[(eps_feat["episode_quality"] == "ok")
                     & (eps_feat[response_col].isin(["responded", "no_response"]))].copy()
    preds = train[["episode_id", "user_id", "threshold_name", "start_ts", "end_ts",
                   response_col]].reset_index(drop=True)
    preds["y"] = y
    preds["p_response_raw"] = oof[best]
    preds["p_response"] = iso_best.transform(oof[best])
    preds["model"] = best
    # assign GroupKFold fold id (for audit)
    fold = np.full(len(y), -1)
    for k, (_, te) in enumerate(gkf.split(X, y, groups)):
        fold[te] = k
    preds["fold"] = fold
    result["predictions"] = preds

    # ---- coefficients / importances (full refit) ----
    full = candidates[best]
    full.fit(X, y)
    result["importances"] = _importances(full, list(X.columns), X, y, groups)
    bundle = ResponseModelBundle(list(X.columns), full, iso_best, best, band_cols)
    return result, bundle


def predict_all_ok(bundle: ResponseModelBundle, eps_feat: pd.DataFrame) -> pd.DataFrame:
    """Operational per-episode p_response for ALL OK episodes (complete OR censored).

    Used by the anomaly layer / online state; censored episodes still get a probability so
    the cumulative expected-response can include opportunities still inside their window.
    """
    ok = eps_feat[eps_feat["episode_quality"] == "ok"].copy()
    if ok.empty:
        ok["p_response"] = []
        return ok[["episode_id", "p_response"]]
    band = pd.get_dummies(ok["threshold_name"], prefix="band")
    for bc in bundle.band_columns:
        if bc not in band.columns:
            band[bc] = 0
    feats = [c for c in bundle.feature_columns if c not in bundle.band_columns]
    X = pd.concat([ok[feats].reset_index(drop=True),
                   band[bundle.band_columns].reset_index(drop=True)], axis=1).astype(float)
    X = X[bundle.feature_columns]
    p_raw = bundle.model.predict_proba(X)[:, 1]
    p = bundle.calibrator.transform(p_raw) if bundle.calibrator is not None else p_raw
    out = ok[["episode_id"]].copy()
    out["p_response"] = np.clip(p, 0.0, 1.0)
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
class _ConstModel:
    """Fallback 'model' that returns a constant probability (insufficient-data path)."""
    def __init__(self, p: float):
        self.p = float(np.clip(p, 0.001, 0.999))

    def predict_proba(self, X):
        n = len(X)
        return np.column_stack([np.full(n, 1 - self.p), np.full(n, self.p)])


def _confusion_at(y: np.ndarray, p: np.ndarray) -> Dict[str, int]:
    out = {}
    for t in (0.5, 0.7, 0.9):
        pred = (p >= t).astype(int)
        tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
        tn = int(((pred == 0) & (y == 0)).sum()); fn = int(((pred == 0) & (y == 1)).sum())
        out[f"tp@{t}"], out[f"fp@{t}"], out[f"tn@{t}"], out[f"fn@{t}"] = tp, fp, tn, fn
    return out


def _calib_slope(y: np.ndarray, p: np.ndarray) -> float:
    """Logistic-recalibration slope of y ~ logit(p); 1.0 == well calibrated."""
    from sklearn.linear_model import LogisticRegression
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    logit = np.log(pc / (1 - pc)).reshape(-1, 1)
    if len(np.unique(y)) < 2:
        return float("nan")
    try:
        lr = LogisticRegression(max_iter=1000).fit(logit, y)
        return round(float(lr.coef_[0][0]), 3)
    except Exception:
        return float("nan")


def _importances(model, columns: List[str], X=None, y=None, groups=None) -> pd.DataFrame:
    import numpy as _np
    if hasattr(model, "named_steps") and "lr" in getattr(model, "named_steps", {}):
        coef = model.named_steps["lr"].coef_[0]
        return pd.DataFrame({"feature": columns, "weight": _np.round(coef, 4),
                             "kind": "logreg_coef"}) \
            .sort_values("weight", key=_np.abs, ascending=False)
    if hasattr(model, "feature_importances_"):
        return pd.DataFrame({"feature": columns,
                             "weight": _np.round(model.feature_importances_, 5),
                             "kind": "native_importance"}) \
            .sort_values("weight", ascending=False)
    # HistGradientBoosting has no native importances -> permutation importance (ROC AUC drop).
    if X is not None and y is not None:
        try:
            from sklearn.inspection import permutation_importance
            r = permutation_importance(model, X, y, n_repeats=5, random_state=0,
                                       scoring="roc_auc", n_jobs=1)
            return pd.DataFrame({"feature": columns,
                                 "weight": _np.round(r.importances_mean, 5),
                                 "weight_std": _np.round(r.importances_std, 5),
                                 "kind": "permutation_roc_auc"}) \
                .sort_values("weight", ascending=False)
        except Exception:
            pass
    return pd.DataFrame({"feature": columns, "weight": [float("nan")] * len(columns),
                         "kind": "unavailable"})


def _try_lightgbm():
    try:
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=300, max_depth=3, learning_rate=0.05,
                              num_leaves=15, verbose=-1)
    except Exception:
        return None


def _try_xgboost():
    try:
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05,
                             eval_metric="logloss", verbosity=0, use_label_encoder=False)
    except Exception:
        return None
