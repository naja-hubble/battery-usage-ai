"""XGBoost (gradient-boosted trees) predicting very_stale from the LEARNING features
(device_model / batt_vendor / manufacturer / design_capacity excluded).

Same span-confound handling as supervised_tree.py: report the naive all-feature model
(inflated by cumulative span-proxy counters) AND the honest INTENSIVE (rate/ratio/level,
span-robust) model. Interpretation via XGBoost gain importance + SHAP + held-out
permutation importance. A more powerful nonlinear learner is a fair test of whether ANY
behavioural signal predicts the freeze once hardware identity and span are removed.

    python supervised_xgb.py
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.metrics import roc_auc_score
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from battery_usage.config import load_config
from classify_reason import learning_features
from supervised_tree import EXTENSIVE     # reuse the extensive(span-confounded)/intensive split

warnings.filterwarnings("ignore")


def make_xgb(y, seed=0) -> XGBClassifier:
    pos = int(y.sum()); neg = len(y) - pos
    return XGBClassifier(
        n_estimators=300, max_depth=3, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=3, reg_lambda=2.0,
        scale_pos_weight=neg / max(pos, 1), eval_metric="auc",
        use_label_encoder=False, random_state=seed, n_jobs=4,
    )


def cv_auc(X, y, feats, seeds=range(5)) -> float:
    """Manual stratified CV AUC (xgboost 1.6 + this sklearn don't integrate via scorer)."""
    X, y = X[feats].reset_index(drop=True), pd.Series(y).reset_index(drop=True)
    aucs = []
    for s in seeds:
        sk = StratifiedKFold(5, shuffle=True, random_state=s)
        fold = []
        for tr, te in sk.split(X, y):
            m = make_xgb(y.iloc[tr], s).fit(X.iloc[tr], y.iloc[tr])
            fold.append(roc_auc_score(y.iloc[te], m.predict_proba(X.iloc[te])[:, 1]))
        aucs.append(np.mean(fold))
    return float(np.mean(aucs))


def perm_imp(model, X, y, feats, n=40, seed=0) -> pd.Series:
    """Manual permutation importance = mean AUC drop when each feature is shuffled."""
    rng = np.random.RandomState(seed)
    base = roc_auc_score(y, model.predict_proba(X)[:, 1])
    out = {}
    for f in feats:
        drops = []
        for _ in range(n):
            Xp = X.copy(); Xp[f] = rng.permutation(Xp[f].to_numpy())
            drops.append(base - roc_auc_score(y, model.predict_proba(Xp)[:, 1]))
        out[f] = float(np.mean(drops))
    return pd.Series(out).sort_values(ascending=False)


def main() -> None:
    cfg = load_config()
    t = pd.read_csv(cfg.processed_dir / "soh_reason_features.csv")
    y = (t["soh_update_status"] == "very_stale").astype(int)

    feats_all = learning_features(t)
    intensive = [f for f in feats_all if f not in EXTENSIVE]
    X = t[feats_all].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median())

    print(f"target very_stale: {int(y.sum())}/{len(y)} | features: {len(feats_all)} "
          f"(intensive {len(intensive)} / extensive {len(EXTENSIVE)})")
    print("\n=== XGBoost CV ROC-AUC predicting very_stale (mean of 5 seeds x 5-fold) ===")
    auc_all = cv_auc(X, y, feats_all)
    auc_int = cv_auc(X, y, intensive)
    fair = t["observation_days"] >= 180
    auc_fair = cv_auc(X[fair].reset_index(drop=True), y[fair].reset_index(drop=True), intensive)
    print(f"  all {len(feats_all)} features            : {auc_all:.3f}")
    print(f"  INTENSIVE {len(intensive)} (span-robust)    : {auc_int:.3f}")
    print(f"  INTENSIVE on obs>=180d (n={int(fair.sum())}, fair): {auc_fair:.3f}")
    print("  (decision-tree baseline was 0.737 / 0.585 / 0.535)")

    # Naive gain importance (span trap).
    m_all = make_xgb(y).fit(X[feats_all], y)
    gain_all = pd.Series(m_all.get_booster().get_score(importance_type="gain")).sort_values(ascending=False)
    print("\n=== NAIVE XGB gain importance (span-confounded counters dominate) ===")
    print(gain_all.head(8).round(2).to_string())

    # Honest intensive model: gain + SHAP + held-out permutation.
    Xi = X[intensive]
    m = make_xgb(y).fit(Xi, y)
    gain = pd.Series(m.get_booster().get_score(importance_type="gain")).reindex(intensive).fillna(0)

    expl = shap.TreeExplainer(m)
    sv = expl.shap_values(Xi)
    shap_imp = pd.Series(np.abs(sv).mean(0), index=intensive).sort_values(ascending=False)

    Xtr, Xte, ytr, yte = train_test_split(Xi, y, test_size=0.3, stratify=y, random_state=0)
    mp = make_xgb(ytr).fit(Xtr, ytr)
    perms = perm_imp(mp, Xte, yte, intensive, n=40, seed=0)

    print("\n=== HONEST INTENSIVE XGB - mean|SHAP| (top) ===")
    print(shap_imp.head(10).round(4).to_string())
    print("\n=== held-out permutation importance (AUC drop, top) ===")
    print(perms.head(8).round(4).to_string())

    out = pd.DataFrame({"feature": intensive})
    out["xgb_gain"] = out.feature.map(gain).round(3)
    out["mean_abs_shap"] = out.feature.map(shap_imp).round(4)
    out["perm_imp_auc_drop"] = out.feature.map(perms).round(4)
    out = out.sort_values("mean_abs_shap", ascending=False)
    out.to_csv(cfg.processed_dir / "very_stale_xgb_importances.csv", index=False)

    plt.figure()
    shap.summary_plot(sv, Xi, max_display=14, show=False)
    plt.title("XGBoost SHAP - very_stale from span-robust features "
              "(model/vendor/design_capacity excluded)", fontsize=10)
    plt.tight_layout()
    plt.savefig(cfg.figures_dir / "very_stale_xgb_shap.png", dpi=130, bbox_inches="tight")
    plt.close()
    print("\nsaved: very_stale_xgb_shap.png, very_stale_xgb_importances.csv")


if __name__ == "__main__":
    main()
