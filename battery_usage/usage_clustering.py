"""ML Layer 1 — unsupervised clustering of 30-day usage patterns (rolling30 spec 9).

This does NOT detect FW faults directly. It groups user-windows by *usage shape* so the
action layer can lean on a descriptive profile (AC-bound / shallow-topup / mobile deep
cycle responding-or-not / large-gap / sparse) when it explains a Gauge-vs-FW recommendation
(spec 9.1). Hardware identity is never a feature.

HDBSCAN is preferred but not installed in this environment, so we fall back to a
``Pipeline(SimpleImputer, RobustScaler, GaussianMixture|KMeans)`` selected by BIC /
silhouette. Standardisation lives inside the pipeline so fit never leaks across the model
boundary. At cohort scale we fit on a capped random-but-deterministic subsample and then
assign every window.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

CLUSTER_FEATURES = [
    "cycle_delta_30d", "cycle_rate_per_30d", "ac_time_ratio_30d", "charge_time_ratio_30d",
    "discharge_time_ratio_30d", "rsoc_min_30d", "rsoc_max_30d", "rsoc_swing_30d",
    "frac_below_20_30d", "frac_above_80_30d", "frac_above_95_30d", "n_discharge_sessions_30d",
    "n_acdc_switches_30d", "n_80_20_80_ok_complete_30d", "n_80_20_80_large_gap_30d",
    "n_90_10_90_ok_complete_30d", "fcc_effective_changes_30d",
]

PROFILE_NAMES = ("AC_BOUND", "SHALLOW_TOPUP", "LOW_CYCLING_LOW_INFORMATION",
                 "MOBILE_DEEP_CYCLE_RESPONDING", "MOBILE_DEEP_CYCLE_NO_RESPONSE",
                 "LARGE_GAP_AMBIGUOUS", "SPARSE_OR_REVIEW")

_ACTION_HINT = {
    "AC_BOUND": "gauge_reset_hint", "SHALLOW_TOPUP": "gauge_reset_hint",
    "LOW_CYCLING_LOW_INFORMATION": "gauge_reset_hint",
    "MOBILE_DEEP_CYCLE_RESPONDING": "normal_hint",
    "MOBILE_DEEP_CYCLE_NO_RESPONSE": "fw_check_hint",
    "LARGE_GAP_AMBIGUOUS": "watch_hint", "SPARSE_OR_REVIEW": "review_hint",
}


def run_clustering(
    feats: pd.DataFrame, max_fit: int = 40000, random_state: int = 0,
    quality_col: str = "window_data_quality_label",
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]:
    """Cluster usage windows. Returns (assignments, profiles, info).

    ``assignments`` : user_id, window_end_date, cluster_id, cluster_profile_name, action_hint.
    ``profiles``    : one row per cluster with medians/shares + suggested name & hint.
    """
    from sklearn.pipeline import Pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import RobustScaler

    cols = [c for c in CLUSTER_FEATURES if c in feats.columns]
    info: Dict[str, object] = {"features": cols, "algo": None}
    work = feats.copy()
    # cluster only on quality-OK windows; everything else -> SPARSE_OR_REVIEW cluster -1
    ok_mask = (work[quality_col] == "WINDOW_QUALITY_OK") if quality_col in work else np.ones(len(work), bool)
    ok = work[ok_mask]
    if len(ok) < 20:
        work["cluster_id"] = -1
        work["cluster_profile_name"] = "SPARSE_OR_REVIEW"
        work["cluster_action_hint"] = _ACTION_HINT["SPARSE_OR_REVIEW"]
        info["algo"] = "too_few_windows"
        assign = work[["user_id", "window_end_date", "cluster_id",
                       "cluster_profile_name", "cluster_action_hint"]]
        return assign, _profile_frame(work, cols), info

    X_all = ok[cols].replace([np.inf, -np.inf], np.nan)
    # deterministic subsample for fitting
    if len(ok) > max_fit:
        idx = np.linspace(0, len(ok) - 1, max_fit).astype(int)
        fit_X = X_all.iloc[idx]
    else:
        fit_X = X_all

    pre = Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", RobustScaler())])
    Z_fit = pre.fit_transform(fit_X)
    Z_all = pre.transform(X_all)

    labels, algo, k = _fit_predict(Z_fit, Z_all, random_state)
    info["algo"], info["n_clusters"] = algo, int(k)

    work["cluster_id"] = -1
    work.loc[ok.index, "cluster_id"] = labels
    profiles = _profile_frame(work, cols)
    name_map = dict(zip(profiles["cluster_id"], profiles["cluster_profile_name"]))
    work["cluster_profile_name"] = work["cluster_id"].map(name_map).fillna("SPARSE_OR_REVIEW")
    work["cluster_action_hint"] = work["cluster_profile_name"].map(_ACTION_HINT).fillna("review_hint")
    assign = work[["user_id", "window_end_date", "cluster_id",
                   "cluster_profile_name", "cluster_action_hint"]].copy()
    return assign, profiles, info


def _fit_predict(Z_fit: np.ndarray, Z_all: np.ndarray, rs: int
                 ) -> Tuple[np.ndarray, str, int]:
    """Try HDBSCAN, else pick GMM-by-BIC vs KMeans-by-silhouette."""
    try:
        import hdbscan  # noqa: F401
        clusterer = hdbscan.HDBSCAN(min_cluster_size=max(50, len(Z_fit) // 50))
        clusterer.fit(Z_fit)
        if hasattr(clusterer, "approximate_predict"):
            import hdbscan as _h
            labels, _ = _h.approximate_predict(clusterer, Z_all)
            return labels, "hdbscan", int(len(set(labels)) - (1 if -1 in labels else 0))
    except Exception:
        pass

    from sklearn.mixture import GaussianMixture
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    best = None
    for k in range(3, 8):
        try:
            gm = GaussianMixture(n_components=k, covariance_type="full",
                                 random_state=rs, max_iter=200, reg_covar=1e-4).fit(Z_fit)
            bic = gm.bic(Z_fit)
            if best is None or bic < best[0]:
                best = (bic, k, gm)
        except Exception:
            continue
    if best is not None:
        _, k, gm = best
        return gm.predict(Z_all), "gaussian_mixture_bic", k
    # last resort: KMeans by silhouette on a small subsample
    sub = Z_fit[np.linspace(0, len(Z_fit) - 1, min(len(Z_fit), 5000)).astype(int)]
    best_k, best_sil, best_km = 4, -1.0, None
    for k in range(3, 8):
        km = KMeans(n_clusters=k, n_init=10, random_state=rs).fit(sub)
        sil = silhouette_score(sub, km.labels_)
        if sil > best_sil:
            best_k, best_sil, best_km = k, sil, km
    km = KMeans(n_clusters=best_k, n_init=10, random_state=rs).fit(Z_fit)
    return km.predict(Z_all), "kmeans_silhouette", best_k


def _name_cluster(row: pd.Series, fleet_cycle_p25: float) -> str:
    ac = row.get("median_ac_time_ratio", np.nan)
    swing = row.get("median_rsoc_swing", np.nan)
    rmin = row.get("median_rsoc_min", np.nan)
    cyc = row.get("median_cycle_delta", np.nan)
    n_ok = row.get("median_n_80_20_80_ok", 0)
    n_lg = row.get("median_n_80_20_80_large_gap", 0)
    share_nr = row.get("share_no_response", np.nan)
    if pd.notna(ac) and ac >= 0.80:
        return "AC_BOUND"
    if (pd.notna(swing) and swing < 40) and (pd.notna(rmin) and rmin > 30):
        return "SHALLOW_TOPUP"
    if n_lg >= 1 and n_ok < 1:
        return "LARGE_GAP_AMBIGUOUS"
    if pd.notna(cyc) and cyc <= fleet_cycle_p25 and n_ok < 1:
        return "LOW_CYCLING_LOW_INFORMATION"
    if n_ok >= 1:
        if pd.notna(share_nr) and share_nr >= 0.6:
            return "MOBILE_DEEP_CYCLE_NO_RESPONSE"
        return "MOBILE_DEEP_CYCLE_RESPONDING"
    return "SPARSE_OR_REVIEW"


def _profile_frame(work: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    has = work["cluster_id"] >= 0
    if not has.any():
        return pd.DataFrame(columns=["cluster_id", "n_windows", "n_users",
                                     "cluster_profile_name", "suggested_action_hint"])
    fleet_cycle_p25 = float(work.loc[has, "cycle_delta_30d"].quantile(0.25)) \
        if "cycle_delta_30d" in work else 0.0
    rows = []
    for cid, g in work[has].groupby("cluster_id"):
        nr = g.get("n_80_20_80_no_response_30d", pd.Series(0, index=g.index)).sum()
        okc = g.get("n_80_20_80_ok_complete_30d", pd.Series(0, index=g.index)).sum()
        lg = g.get("n_80_20_80_large_gap_30d", pd.Series(0, index=g.index)).sum()
        share_nr = float(nr / okc) if okc > 0 else float("nan")
        prof = {
            "cluster_id": int(cid), "n_windows": int(len(g)), "n_users": int(g["user_id"].nunique()),
            "median_cycle_delta": round(float(g["cycle_delta_30d"].median()), 2) if "cycle_delta_30d" in g else np.nan,
            "median_ac_time_ratio": round(float(g["ac_time_ratio_30d"].median()), 4) if "ac_time_ratio_30d" in g else np.nan,
            "median_rsoc_swing": round(float(g["rsoc_swing_30d"].median()), 2) if "rsoc_swing_30d" in g else np.nan,
            "median_rsoc_min": round(float(g["rsoc_min_30d"].median()), 2) if "rsoc_min_30d" in g else np.nan,
            "median_n_80_20_80_ok": round(float(g.get("n_80_20_80_ok_complete_30d", pd.Series(0)).median()), 2),
            "median_n_80_20_80_large_gap": round(float(g.get("n_80_20_80_large_gap_30d", pd.Series(0)).median()), 2),
            "median_fcc_effective_changes": round(float(g["fcc_effective_changes_30d"].median()), 2) if "fcc_effective_changes_30d" in g else np.nan,
            "share_response_windows": round(float((g.get("n_80_20_80_no_response_30d", pd.Series(0, index=g.index)) == 0).mean()), 4),
            "share_no_response": share_nr,
            "share_large_gap": round(float(lg / max(okc + lg, 1)), 4),
        }
        rows.append(prof)
    pf = pd.DataFrame(rows)
    pf["cluster_profile_name"] = pf.apply(lambda r: _name_cluster(r, fleet_cycle_p25), axis=1)
    pf["suggested_action_hint"] = pf["cluster_profile_name"].map(_ACTION_HINT)
    return pf
