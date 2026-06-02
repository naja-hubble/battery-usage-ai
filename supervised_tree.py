"""Supervised, interpretable tree predicting very_stale from the LEARNING features
(device_model / batt_vendor / manufacturer / design_capacity already excluded).

very_stale is span-gated by construction (needs >=180 flat trailing days), so a naive
tree latches onto cumulative counters that merely scale with observation length
(total_awake_hrs_last, cycle_count_last, n_*_dis ...). We therefore split the learning
features into:
  EXTENSIVE  cumulative counters (grow with observation span) -> span-confounded
  INTENSIVE  rates / ratios / levels (span-robust)            -> the honest predictors

and report the honest tree on the INTENSIVE set (impurity + held-out permutation
importance, interpretable rules, and a tree plot).

    python supervised_tree.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text, plot_tree
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.inspection import permutation_importance
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from battery_usage.config import load_config
from classify_reason import learning_features

# Cumulative counters that scale with observation length (span-confounded).
EXTENSIVE = {
    "cycle_count_last", "cycles_in_window", "hours_at_full_charge_last",
    "hours_high_temp_last", "total_charged_capacity_last", "total_awake_hrs_last",
    "n_discharge_sessions", "sleep_events", "sleep_total_hours", "n_deep_dis10",
    "n_full_range_dis",
}


def _cv_auc(X, y, feats, depth=4, seeds=range(5)) -> float:
    aucs = []
    for s in seeds:
        clf = DecisionTreeClassifier(max_depth=depth, class_weight="balanced", random_state=s)
        sk = StratifiedKFold(5, shuffle=True, random_state=s)
        aucs.append(cross_val_score(clf, X[feats], y, cv=sk, scoring="roc_auc").mean())
    return float(np.mean(aucs))


def main() -> None:
    cfg = load_config()
    t = pd.read_csv(cfg.processed_dir / "soh_reason_features.csv")
    y = (t["soh_update_status"] == "very_stale").astype(int)

    feats_all = learning_features(t)
    intensive = [f for f in feats_all if f not in EXTENSIVE]
    X = t[feats_all].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median())

    print(f"target very_stale: {int(y.sum())}/{len(y)} positives")
    print(f"learning features: {len(feats_all)} (intensive {len(intensive)} / extensive {len(EXTENSIVE)})")
    print("\n=== CV ROC-AUC predicting very_stale (depth-4 tree, mean of 5 seeds) ===")
    print(f"  all {len(feats_all)} features         : {_cv_auc(X, y, feats_all):.3f}")
    print(f"  INTENSIVE {len(intensive)} (span-robust) : {_cv_auc(X, y, intensive):.3f}")
    # fair region: very_stale can only occur at obs>=180d
    fair = t["observation_days"] >= 180
    print(f"  INTENSIVE on obs>=180d (n={int(fair.sum())}, fair): "
          f"{_cv_auc(X[fair], y[fair], intensive):.3f}")

    # Naive tree importances (demonstrate the span trap).
    clf_all = DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=0).fit(X[feats_all], y)
    imp_all = pd.Series(clf_all.feature_importances_, index=feats_all).sort_values(ascending=False)
    print("\n=== NAIVE tree (all features) top splits - span-confounded counters dominate ===")
    print(imp_all[imp_all > 0].head(8).to_string())

    # Honest intensive tree.
    Xi = X[intensive]
    clf = DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=0).fit(Xi, y)
    imp = pd.Series(clf.feature_importances_, index=intensive).sort_values(ascending=False)
    Xtr, Xte, ytr, yte = train_test_split(Xi, y, test_size=0.3, stratify=y, random_state=0)
    clf2 = DecisionTreeClassifier(max_depth=4, class_weight="balanced", random_state=0).fit(Xtr, ytr)
    perm = permutation_importance(clf2, Xte, yte, n_repeats=40, random_state=0, scoring="roc_auc")
    perms = pd.Series(perm.importances_mean, index=intensive).sort_values(ascending=False)

    print("\n=== HONEST INTENSIVE tree - impurity importance (top) ===")
    print(imp[imp > 0].head(10).to_string())
    print("\n=== permutation importance on 30% hold-out (AUC drop, top) ===")
    print(perms.head(8).to_string())

    rules = export_text(clf, feature_names=list(intensive), max_depth=4)
    (cfg.processed_dir / "very_stale_tree_rules.txt").write_text(rules, encoding="utf-8")

    out = pd.DataFrame({"feature": intensive})
    out["impurity_imp"] = out.feature.map(imp).round(4)
    out["perm_imp_auc_drop"] = out.feature.map(perms).round(4)
    out = out.sort_values("impurity_imp", ascending=False)
    out.to_csv(cfg.processed_dir / "very_stale_tree_importances.csv", index=False)

    fig, ax = plt.subplots(figsize=(22, 11))
    plot_tree(clf, feature_names=[f[:20] for f in intensive], class_names=["not_vs", "very_stale"],
              filled=True, impurity=False, proportion=True, rounded=True, fontsize=7, ax=ax, max_depth=3)
    ax.set_title("Decision tree: predict very_stale from span-robust (intensive) features\n"
                 "(device_model / batt_vendor / design_capacity excluded)", fontsize=12)
    fig.savefig(cfg.figures_dir / "very_stale_tree.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print("\nsaved: very_stale_tree.png, very_stale_tree_rules.txt, very_stale_tree_importances.csv")


if __name__ == "__main__":
    main()
