"""Figure functions for the Rolling 30d FCC online detector v2.0 (spec section 16.3).

All figures saved at the requested dpi (default 300). Each figure is wrapped by the driver
in try/except so one missing input never aborts the rest. Reads the v2 output CSV/parquet
files written by ``analyze_fcc_online_sliding30_v2.py``; per-user example plots additionally
read the raw timeseries. Cohort-level usage of hardware fields is only for the post-hoc
enrichment figures (never for classification).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                            # noqa: E402

from . import online_policy_v2 as pol

META_COLS = ["analysis_timestamp", "code_version", "window_days", "stride_days",
             "effective_step_definition"]

TIER_COLORS = {"HIGH_OK": "#2ca02c", "MEDIUM_GAP": "#ff7f0e", "LOW_LARGE_GAP": "#d62728",
               "INVALID": "#999999"}
LABEL_ORDER = [pol.ST_REVIEW_DQ, pol.ST_FW_CORE, pol.ST_GAUGE_CORE, pol.ST_FW_WATCH,
               pol.ST_GAUGE_SOFT, pol.ST_GAUGE_REVIEW, pol.ST_WATCH_LGC, pol.ST_WATCH_LOW,
               pol.ST_NORMAL]
LABEL_SHORT = {l: l.replace("STATEFUL_", "") for l in LABEL_ORDER}


def _save(fig, path: Path, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _safe_id(uid: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(uid))[:60]


class Plotter:
    def __init__(self, in_dir: Path, fig_dir: Path, dpi: int) -> None:
        self.in_dir = Path(in_dir)
        self.fig_dir = Path(fig_dir)
        self.dpi = dpi
        self.n_ok = 0
        self.n_skip = 0
        self._cache: Dict[str, pd.DataFrame] = {}

    def load(self, fname: str) -> pd.DataFrame:
        if fname in self._cache:
            return self._cache[fname]
        p = self.in_dir / fname
        if not p.exists():
            self._cache[fname] = pd.DataFrame()
            return self._cache[fname]
        df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        df = df.drop(columns=[c for c in META_COLS if c in df.columns], errors="ignore")
        self._cache[fname] = df
        return df

    def fig(self, name: str, func) -> None:
        try:
            func(self, self.fig_dir / name)
            self.n_ok += 1
        except Exception as exc:                                           # pragma: no cover
            self.n_skip += 1
            print(f"  [skip] {name}: {type(exc).__name__}: {exc}", flush=True)


# --------------------------------------------------------------------------- #
# Cohort figures
# --------------------------------------------------------------------------- #
def fig_label_counts(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    vc = snap["stateful_label_v2"].value_counts()
    order = [l for l in LABEL_ORDER if l in vc.index]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh([LABEL_SHORT[l] for l in order][::-1], [vc[l] for l in order][::-1], color="#4878a8")
    for i, l in enumerate(order[::-1]):
        ax.text(vc[l], i, f" {vc[l]}", va="center")
    ax.set_xlabel("users"); ax.set_title("v2 latest-snapshot stateful labels")
    _save(fig, out, P.dpi)


def fig_funnel(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    n = len(snap)
    sc = snap["stateful_label_v2"].value_counts().to_dict()
    stages = [("cohort", n),
              ("FW Core", sc.get(pol.ST_FW_CORE, 0)),
              ("FW Watch", sc.get(pol.ST_FW_WATCH, 0)),
              ("Gauge Core", sc.get(pol.ST_GAUGE_CORE, 0)),
              ("Gauge Soft", sc.get(pol.ST_GAUGE_SOFT, 0)),
              ("Review/DQ", sc.get(pol.ST_REVIEW_DQ, 0))]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([s[0] for s in stages], [s[1] for s in stages], color="#6a8caf")
    for i, s in enumerate(stages):
        ax.text(i, s[1], str(s[1]), ha="center", va="bottom")
    ax.set_ylabel("users"); ax.set_title("v2 funnel: cohort -> tiers")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, out, P.dpi)


def fig_days_since_any_vs_eff(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    fig, ax = plt.subplots(figsize=(6.5, 6))
    c = snap["micro_wobble_only_since_effective_change"].astype(bool) \
        if "micro_wobble_only_since_effective_change" in snap else False
    ax.scatter(snap["days_since_any_fcc_change"], snap["days_since_effective_fcc_change"],
               c=np.where(c, "#d62728", "#4878a8"), s=10, alpha=0.5)
    lim = max(snap["days_since_effective_fcc_change"].max(),
              snap["days_since_any_fcc_change"].max())
    ax.plot([0, lim], [0, lim], "k--", lw=0.7)
    ax.axhline(120, color="gray", ls=":", lw=0.7); ax.axvline(120, color="gray", ls=":", lw=0.7)
    ax.set_xlabel("days since any FCC change"); ax.set_ylabel("days since effective FCC change")
    ax.set_title("any-change vs effective-step staleness\n(red = micro-wobble-only)")
    _save(fig, out, P.dpi)


def fig_any_vs_effective_scatter(P: Plotter, out: Path) -> None:
    fig_days_since_any_vs_eff(P, out)


def fig_micro_wobble_dist(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    col = "max_micro_step_mWh_since_effective_change"
    if col not in snap:
        raise KeyError(col)
    v = snap.loc[snap[col] > 0, col]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(v.clip(upper=200), bins=40, color="#9467bd")
    ax.axvline(50, color="red", ls="--", label="50 mWh effective threshold")
    ax.set_xlabel("max micro step since last effective change (mWh)")
    ax.set_ylabel("users"); ax.legend(); ax.set_title("Micro-wobble step magnitude distribution")
    _save(fig, out, P.dpi)


def fig_gap_quality_dist(P: Plotter, out: Path) -> None:
    eps = P.load("rolling_30d_learning_episodes_v2.parquet")
    prim = eps[eps["threshold_name"] == "primary_80_20_80"]
    vc = prim["quality_tier"].value_counts()
    order = [t for t in ("HIGH_OK", "MEDIUM_GAP", "LOW_LARGE_GAP", "INVALID") if t in vc.index]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(order, [vc[t] for t in order], color=[TIER_COLORS[t] for t in order])
    for i, t in enumerate(order):
        ax.text(i, vc[t], str(vc[t]), ha="center", va="bottom")
    ax.set_ylabel("primary-band episodes"); ax.set_title("Graded episode gap-quality tiers")
    _save(fig, out, P.dpi)


def fig_fw_anomaly_dist(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    s = snap.loc[snap["cum_normative_fw_anomaly_score"] > 0, "cum_normative_fw_anomaly_score"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(s, bins=40, color="#e377c2")
    for thr in (1.3, 2.0, 3.0):
        ax.axvline(thr, ls="--", lw=0.7, color="gray")
    ax.set_xlabel("cumulative normative FW anomaly score (-log10 P_all_no_response)")
    ax.set_ylabel("users"); ax.set_title("Normative FW anomaly score distribution")
    _save(fig, out, P.dpi)


def fig_expected_vs_observed(P: Plotter, out: Path) -> None:
    sc = P.load("user_window_anomaly_scores_v2.parquet")
    sub = sc[sc["n_complete_ok_opportunities_30d"] >= 1]
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.scatter(sub["expected_response_30d"], sub["observed_response_30d"], s=6, alpha=0.3,
               color="#4878a8")
    lim = max(sub["expected_response_30d"].max(), sub["observed_response_30d"].max(), 1)
    ax.plot([0, lim], [0, lim], "k--", lw=0.7)
    ax.set_xlabel("expected responses (normative Sum p_i)")
    ax.set_ylabel("observed responses"); ax.set_title("Normative expected vs observed response (per window)")
    _save(fig, out, P.dpi)


def _roc_pr_from_preds(preds: pd.DataFrame):
    from sklearn.metrics import roc_curve, precision_recall_curve
    y = preds["y"].to_numpy()
    p = preds["p_response"].to_numpy() if "p_response" in preds else preds["p_response_raw"].to_numpy()
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    return fpr, tpr, prec, rec


def fig_roc_pr(P: Plotter, out: Path) -> None:
    pn = P.load("episode_response_model_predictions_normative.parquet")
    pp = P.load("episode_response_model_predictions_personalized.parquet")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5))
    for preds, name, col in ((pn, "normative", "#1f77b4"), (pp, "personalized", "#ff7f0e")):
        if preds.empty:
            continue
        fpr, tpr, prec, rec = _roc_pr_from_preds(preds)
        a1.plot(fpr, tpr, label=name, color=col)
        a2.plot(rec, prec, label=name, color=col)
    a1.plot([0, 1], [0, 1], "k--", lw=0.6); a1.set_xlabel("FPR"); a1.set_ylabel("TPR")
    a1.set_title("ROC"); a1.legend()
    a2.set_xlabel("recall"); a2.set_ylabel("precision"); a2.set_title("PR"); a2.legend()
    fig.suptitle("Normative vs personalized episode response model")
    _save(fig, out, P.dpi)


def fig_calibration(P: Plotter, out: Path) -> None:
    from sklearn.calibration import calibration_curve
    pn = P.load("episode_response_model_predictions_normative.parquet")
    pp = P.load("episode_response_model_predictions_personalized.parquet")
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for preds, name, col in ((pn, "normative", "#1f77b4"), (pp, "personalized", "#ff7f0e")):
        if preds.empty:
            continue
        y = preds["y"].to_numpy(); p = preds["p_response"].to_numpy()
        frac, mean = calibration_curve(y, p, n_bins=10, strategy="quantile")
        ax.plot(mean, frac, "o-", label=name, color=col)
    ax.plot([0, 1], [0, 1], "k--", lw=0.6)
    ax.set_xlabel("mean predicted p"); ax.set_ylabel("observed response rate")
    ax.set_title("Calibration (reliability) — normative vs personalized"); ax.legend()
    _save(fig, out, P.dpi)


def _importance_fig(P: Plotter, out: Path, fname: str, title: str) -> None:
    imp = P.load(fname)
    if imp.empty:
        raise ValueError("no importances")
    imp = imp.reindex(imp["weight"].abs().sort_values(ascending=False).index).head(15)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(imp["feature"][::-1], imp["weight"][::-1], color="#5b9bd5")
    ax.set_xlabel(imp["kind"].iloc[0] if "kind" in imp else "weight"); ax.set_title(title)
    _save(fig, out, P.dpi)


def fig_normative_importance(P: Plotter, out: Path) -> None:
    _importance_fig(P, out, "episode_response_model_importances_normative.csv",
                    "Normative model feature importance")


def fig_personalized_importance(P: Plotter, out: Path) -> None:
    _importance_fig(P, out, "episode_response_model_importances_personalized.csv",
                    "Personalized model feature importance")


def fig_false_alert(P: Plotter, out: Path) -> None:
    fa = P.load("active_false_alert_audit_v2.csv")
    if fa.empty:
        raise ValueError("no false alert audit")
    fa = fa.copy()
    fa["short"] = fa["label_v2"].map(lambda l: LABEL_SHORT.get(l, l))
    x = np.arange(len(fa)); w = 0.25
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.bar(x - w, fa["active_false_alert_legacy_any_change"], w, label="legacy any-change")
    ax.bar(x, fa["active_false_alert_online_any_state"], w, label="online any-state")
    ax.bar(x + w, fa["active_false_alert_online_effective_state"], w, label="online effective-state")
    ax.set_xticks(x); ax.set_xticklabels(fa["short"], rotation=30, ha="right")
    ax.set_ylabel("users active"); ax.legend()
    ax.set_title("Active false-alert audit — dual/triple basis by v2 label")
    _save(fig, out, P.dpi)


def fig_stateful_vs_stateless(P: Plotter, out: Path) -> None:
    bt = P.load("backtest_stateful_vs_stateless_v2.csv")
    if bt.empty:
        raise ValueError("no svs")
    r = bt.iloc[0]
    keys = [("stateful", "stateful_detection_n"), ("stateless", "stateless_detection_n"),
            ("overlap", "overlap_detection_n"), ("stateful-only", "stateful_only_detection_n"),
            ("stateless-only", "stateless_only_detection_n")]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    vals = [int(r[k]) for _, k in keys]
    ax.bar([n for n, _ in keys], vals, color="#6a8caf")
    for i, v in enumerate(vals):
        ax.text(i, v, str(v), ha="center", va="bottom")
    ax.set_ylabel("users"); ax.set_title("Stateful vs stateless no-response detection")
    _save(fig, out, P.dpi)


def fig_topn_yield(P: Plotter, out: Path) -> None:
    tn = P.load("topn_yield_v2.csv")
    if tn.empty:
        raise ValueError("no topn")
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for sc, g in tn.groupby("score_col"):
        g = g.sort_values("N")
        ax.plot(g["N"], g["recall_at_N"], "o-", label=f"recall: {sc[:24]}")
        ax.plot(g["N"], g["precision_at_N"], "s--", label=f"prec: {sc[:24]}")
    ax.set_xlabel("top N"); ax.set_ylabel("precision / recall vs proxy"); ax.legend(fontsize=7)
    ax.set_title("Top-N engineering-queue yield vs final proxy")
    _save(fig, out, P.dpi)


def fig_proxy_crosstab(P: Plotter, out: Path) -> None:
    ct = P.load("final_proxy_cross_tab_v2.csv")
    if ct.empty:
        raise ValueError("no crosstab")
    ct = ct.set_index(ct.columns[0])
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(ct.values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(ct.shape[1])); ax.set_xticklabels(ct.columns, rotation=30, ha="right", fontsize=7)
    ax.set_yticks(range(ct.shape[0]))
    ax.set_yticklabels([LABEL_SHORT.get(i, i) for i in ct.index], fontsize=7)
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            ax.text(j, i, ct.values[i, j], ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, fraction=0.04); ax.set_title("v2 label x final proxy cross-tab")
    _save(fig, out, P.dpi)


def fig_policy_matrix(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    if "priority" not in snap or "confidence" not in snap:
        raise KeyError("priority/confidence")
    ct = pd.crosstab(snap["stateful_label_v2"].map(lambda l: LABEL_SHORT.get(l, l)),
                     snap["confidence"])
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(ct.values, cmap="Purples", aspect="auto")
    ax.set_xticks(range(ct.shape[1])); ax.set_xticklabels(ct.columns)
    ax.set_yticks(range(ct.shape[0])); ax.set_yticklabels(ct.index, fontsize=8)
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            ax.text(j, i, ct.values[i, j], ha="center", va="center")
    fig.colorbar(im, ax=ax, fraction=0.04); ax.set_title("Policy matrix: label x confidence")
    _save(fig, out, P.dpi)


def fig_cluster_profiles(P: Plotter, out: Path) -> None:
    prof = P.load("usage_cluster_profiles_v2.csv")
    if prof.empty:
        raise ValueError("no profiles")
    cols = [c for c in ("median_ac_time_ratio", "median_rsoc_swing", "median_cycle_delta",
                        "median_rsoc_min") if c in prof.columns]
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(prof)); w = 0.8 / max(len(cols), 1)
    for i, c in enumerate(cols):
        ax.bar(x + i * w, prof[c], w, label=c.replace("median_", ""))
    ax.set_xticks(x + 0.4)
    ax.set_xticklabels(prof.get("cluster_profile_name", prof["cluster_id"]), rotation=25,
                       ha="right", fontsize=7)
    ax.legend(fontsize=7); ax.set_title("Usage-only cluster profiles (medians)")
    _save(fig, out, P.dpi)


def fig_cluster_outcomes(P: Plotter, out: Path) -> None:
    prof = P.load("usage_cluster_outcome_profile_v2.csv")
    if prof.empty:
        raise ValueError("no outcome profile")
    cols = [c for c in ("share_response", "share_no_response", "share_censored",
                        "share_large_gap") if c in prof.columns]
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(prof)); w = 0.8 / max(len(cols), 1)
    for i, c in enumerate(cols):
        ax.bar(x + i * w, prof[c], w, label=c.replace("share_", ""))
    ax.set_xticks(x + 0.4)
    ax.set_xticklabels(prof.get("cluster_profile_name", prof["cluster_id"]), rotation=25,
                       ha="right", fontsize=7)
    ax.legend(fontsize=7); ax.set_title("POST-HOC cluster outcome profile (interpretation only)")
    _save(fig, out, P.dpi)


def fig_episode_sensitivity(P: Plotter, out: Path) -> None:
    es = P.load("episode_sensitivity_v2.csv")
    if es.empty:
        raise ValueError("no episode sensitivity")
    fig, ax = plt.subplots(figsize=(8, 5))
    for w, g in es.groupby("response_window_h"):
        g = g.set_index("gap_rule").reindex(["6h", "12h", "24h", "graded"])
        ax.plot(g.index, g["response_rate_complete"], "o-", label=f"{w}h window")
    ax.set_xlabel("gap rule"); ax.set_ylabel("response rate (complete)"); ax.legend()
    ax.set_title("Response-rate sensitivity: gap rule x response window")
    _save(fig, out, P.dpi)


def fig_gap_rule_sensitivity(P: Plotter, out: Path) -> None:
    es = P.load("episode_sensitivity_v2.csv")
    if es.empty:
        raise ValueError("no episode sensitivity")
    sub = es[es["response_window_h"] == 72]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    x = np.arange(len(sub)); w = 0.35
    ax.bar(x - w / 2, sub["n_opportunities"], w, label="opportunities")
    ax.bar(x + w / 2, sub["n_no_response"], w, label="no_response")
    ax.set_xticks(x); ax.set_xticklabels(sub["gap_rule"]); ax.legend()
    ax.set_ylabel("episodes (72h window)"); ax.set_title("Gap-rule sensitivity counts")
    _save(fig, out, P.dpi)


def fig_lead_time(P: Plotter, out: Path) -> None:
    lt = P.load("lead_time_v2.csv")
    if lt.empty or "final_label" not in lt:
        raise ValueError("no lead time")
    fig, ax = plt.subplots(figsize=(8, 5))
    data, labels = [], []
    for lab, g in lt.groupby("final_label"):
        if len(g) >= 1:
            data.append(g["lead_time_days"].dropna().values); labels.append(str(lab)[:24])
    if not data:
        raise ValueError("no lead-time groups")
    ax.boxplot(data, labels=labels, vert=True)
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("lead time (days before last obs)"); ax.set_title("Alert lead time by proxy label")
    _save(fig, out, P.dpi)


def fig_hw_enrichment_fw_core(P: Plotter, out: Path) -> None:
    _hw_enrich_fig(P, out, "FW_CORE", "HW enrichment — FW Core")


def fig_hw_enrichment_fw_top50(P: Plotter, out: Path) -> None:
    _hw_enrich_fig(P, out, "FW_ENGINEERING_TOP50", "HW enrichment — FW engineering top50")


def _hw_enrich_fig(P: Plotter, out: Path, population: str, title: str) -> None:
    enr = P.load("hardware_enrichment_v2.csv")
    if enr.empty or "population" not in enr:
        raise ValueError("no enrichment")
    sub = enr[enr["population"] == population].head(12)
    if sub.empty:
        raise ValueError("population empty")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    y = np.arange(len(sub))
    ax.barh(y, sub["shrunk_rate"], color="#4878a8")
    ax.errorbar(sub["shrunk_rate"], y,
                xerr=[sub["shrunk_rate"] - sub["ci_low"], sub["ci_high"] - sub["shrunk_rate"]],
                fmt="none", ecolor="gray", capsize=2)
    ax.axvline(sub["fleet_rate"].iloc[0], color="red", ls="--", label="fleet rate")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.group_axis}={r.group_value}" for r in sub.itertuples()], fontsize=7)
    ax.set_xlabel("shrunk candidate rate"); ax.legend(); ax.set_title(title)
    _save(fig, out, P.dpi)


def fig_transition_v1_to_v2(P: Plotter, out: Path) -> None:
    v2 = P.load("online_latest_snapshot_v2.csv")
    v1p = P.in_dir.parent / "fcc_online" / "online_fcc_current_snapshot.csv"
    if not v1p.exists():
        raise ValueError("no v1 snapshot for transition")
    v1 = pd.read_csv(v1p)[["user_id", "stateful_label"]]
    m = v2[["user_id", "stateful_label_v2"]].merge(v1, on="user_id", how="left")
    ct = pd.crosstab(m["stateful_label"].fillna("NA").map(lambda l: str(l).replace("STATEFUL_", "")),
                     m["stateful_label_v2"].map(lambda l: LABEL_SHORT.get(l, l)))
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(ct.values, cmap="Oranges", aspect="auto")
    ax.set_xticks(range(ct.shape[1])); ax.set_xticklabels(ct.columns, rotation=30, ha="right", fontsize=7)
    ax.set_yticks(range(ct.shape[0])); ax.set_yticklabels(ct.index, fontsize=8)
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            if ct.values[i, j]:
                ax.text(j, i, ct.values[i, j], ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax, fraction=0.04); ax.set_title("v1 label (rows) -> v2 label (cols) transition")
    _save(fig, out, P.dpi)


def fig_stateful_only_examples(P: Plotter, out: Path) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    sl = P.load("backtest_stateless_latest_v2.csv")
    det = ((snap["cum_primary_no_response_since_last_effective_change"] >= 2)
           & (snap["window_data_quality_label"] == "WINDOW_QUALITY_OK")
           & (snap["observed_effective_responses_since_last_effective_change"] == 0))
    st_ids = set(snap.loc[det, "user_id"])
    sl_ids = set(sl.loc[sl["stateless_fw_flag"], "user_id"]) if not sl.empty else set()
    only = list(st_ids - sl_ids)
    sub = snap[snap["user_id"].isin(only)].sort_values(
        "cum_normative_fw_anomaly_score", ascending=False).head(20)
    if sub.empty:
        raise ValueError("no stateful-only users")
    fig, ax = plt.subplots(figsize=(9, 6))
    y = np.arange(len(sub))
    ax.barh(y, sub["cum_primary_no_response_since_last_effective_change"], color="#6a8caf")
    for i, (_, r) in enumerate(sub.iterrows()):
        ax.text(r["cum_primary_no_response_since_last_effective_change"], i,
                f"  {int(r['days_since_effective_fcc_change'])}d", va="center", fontsize=7)
    ax.set_yticks(y); ax.set_yticklabels([f"u{j}" for j in range(len(sub))], fontsize=7)
    ax.set_xlabel("cum no_response since last effective change (annotated: days_eff)")
    ax.set_title("Stateful-only evidence examples (beyond the 30d stateless window)")
    _save(fig, out, P.dpi)


def fig_fru_case_control(P: Plotter, out: Path) -> None:
    enr = P.load("hardware_enrichment_v2.csv")
    if enr.empty or "population" not in enr:
        raise ValueError("no enrichment")
    sub = enr[(enr["population"] == "FW_CORE") & (enr["group_axis"] == "batt_fru")]
    if sub.empty:
        sub = enr[(enr["population"] == "FW_ENGINEERING_TOP50") & (enr["group_axis"] == "batt_fru")]
    if sub.empty:
        raise ValueError("no FRU enrichment available")
    sub = sub.head(12)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    y = np.arange(len(sub))
    ax.barh(y, sub["shrunk_rate"], color="#4878a8", label="shrunk FW rate")
    ax.axvline(sub["fleet_rate"].iloc[0], color="red", ls="--", label="fleet rate")
    ax.set_yticks(y); ax.set_yticklabels(sub["group_value"], fontsize=7)
    ax.set_xlabel("shrunk FW-candidate rate"); ax.legend()
    ax.set_title("FRU case-control (FW candidates by battery FRU, post-classification)")
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Per-user example plots (spec 16.3)
# --------------------------------------------------------------------------- #
def plot_example_users(P: Plotter, ts_path: Path, n_examples: int = 20) -> None:
    snap = P.load("online_latest_snapshot_v2.csv")
    eps = P.load("rolling_30d_learning_episodes_v2.parquet")
    if snap.empty:
        return
    ts = pd.read_parquet(ts_path)
    ts["timestamp"] = pd.to_datetime(ts["timestamp"])
    audit = P.load("online_dual_fcc_change_audit.parquet")
    groups = {
        "example_fw_core_top20": pol.ST_FW_CORE,
        "example_fw_watch_top20": pol.ST_FW_WATCH,
        "example_gauge_core_top20": pol.ST_GAUGE_CORE,
        "example_gauge_soft_top20": pol.ST_GAUGE_SOFT,
        "example_review_top20": pol.ST_REVIEW_DQ,
    }
    for sub_dir, label in groups.items():
        sel = snap[snap["stateful_label_v2"] == label]
        if "cum_normative_fw_anomaly_score" in sel:
            sel = sel.sort_values("cum_normative_fw_anomaly_score", ascending=False)
        sel = sel.head(n_examples)
        for uid in sel["user_id"]:
            try:
                _plot_one_user(P, ts, eps, snap, audit, uid, sub_dir)
                P.n_ok += 1
            except Exception as exc:                                       # pragma: no cover
                P.n_skip += 1
                print(f"  [skip] {sub_dir}/{uid}: {exc}", flush=True)


def _plot_one_user(P, ts, eps, snap, audit, uid, sub_dir) -> None:
    g = ts[ts["user_id"] == uid].sort_values("timestamp")
    if g.empty:
        raise ValueError("no raw")
    srow = snap[snap["user_id"] == uid].iloc[0]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    t = g["timestamp"]
    # RSOC
    axes[0].plot(t, g["remainingCapacityInPercentage"], lw=0.6, color="#1f77b4")
    axes[0].set_ylabel("RSOC %"); axes[0].set_ylim(-3, 105)
    # episodes colored by tier
    ue = eps[eps["user_id"] == uid]
    for r in ue.itertuples(index=False):
        col = TIER_COLORS.get(getattr(r, "quality_tier", "LOW_LARGE_GAP"), "#999")
        axes[0].axvspan(pd.Timestamp(r.start_ts), pd.Timestamp(r.end_ts), color=col, alpha=0.12)
        st = getattr(r, "response_status_72h", "")
        mk = {"responded": "^", "no_response": "v", "censored": "o"}.get(st)
        if mk:
            axes[0].plot(pd.Timestamp(r.end_ts), getattr(r, "end_rsoc", 90), mk, color=col, ms=5)
    # FCC with any/effective markers
    axes[1].plot(t, g["fullChargeCapacity"], lw=0.7, color="#2ca02c")
    axes[1].set_ylabel("FCC (mWh)")
    if not audit.empty:
        ua = audit[audit["user_id"] == uid]
        for r in ua.itertuples(index=False):
            ct = pd.Timestamp(r.change_ts)
            axes[1].axvline(ct, color=("#d62728" if getattr(r, "is_effective", False) else "#bbbbbb"),
                            lw=0.8, ls=("-" if getattr(r, "is_effective", False) else ":"))
    # cycle count
    axes[2].plot(t, g["cycleCount"], lw=0.7, color="#9467bd")
    axes[2].set_ylabel("cycleCount"); axes[2].set_xlabel("time")
    lab = srow["stateful_label_v2"]
    ev = srow.get("evidence_summary", "")
    fig.suptitle(f"{_safe_id(uid)} — {LABEL_SHORT.get(lab, lab)} "
                 f"({srow.get('recommended_action','')})\n{ev}", fontsize=8)
    _save(fig, P.fig_dir / sub_dir / f"{_safe_id(uid)}.png", P.dpi)


# --------------------------------------------------------------------------- #
ALL_FIGS = [
    ("v2_label_counts.png", fig_label_counts),
    ("v2_funnel_counts.png", fig_funnel),
    ("v2_policy_matrix_heatmap.png", fig_policy_matrix),
    ("v2_transition_v1_to_v2_heatmap.png", fig_transition_v1_to_v2),
    ("v2_final_proxy_cross_tab_heatmap.png", fig_proxy_crosstab),
    ("stateful_only_evidence_examples.png", fig_stateful_only_examples),
    ("fru_case_control_if_available.png", fig_fru_case_control),
    ("any_vs_effective_state_scatter.png", fig_any_vs_effective_scatter),
    ("days_since_any_vs_effective_fcc_change.png", fig_days_since_any_vs_eff),
    ("micro_wobble_step_distribution.png", fig_micro_wobble_dist),
    ("active_false_alert_dual_basis.png", fig_false_alert),
    ("personalized_vs_normative_roc_pr.png", fig_roc_pr),
    ("personalized_vs_normative_calibration.png", fig_calibration),
    ("normative_feature_importance.png", fig_normative_importance),
    ("personalized_feature_importance.png", fig_personalized_importance),
    ("expected_vs_observed_response_normative.png", fig_expected_vs_observed),
    ("fw_anomaly_score_distribution.png", fig_fw_anomaly_dist),
    ("fw_topn_yield_curve.png", fig_topn_yield),
    ("large_gap_quality_distribution.png", fig_gap_quality_dist),
    ("gap_rule_sensitivity_counts.png", fig_gap_rule_sensitivity),
    ("response_window_sensitivity_effective.png", fig_episode_sensitivity),
    ("stateful_vs_stateless_counts.png", fig_stateful_vs_stateless),
    ("lead_time_by_proxy_label.png", fig_lead_time),
    ("usage_cluster_profiles.png", fig_cluster_profiles),
    ("usage_cluster_outcome_profile.png", fig_cluster_outcomes),
    ("hardware_enrichment_fw_core.png", fig_hw_enrichment_fw_core),
    ("hardware_enrichment_fw_top50.png", fig_hw_enrichment_fw_top50),
]


def render_all(in_dir, fig_dir, dpi, ts_path=None, n_examples=20) -> Plotter:
    P = Plotter(Path(in_dir), Path(fig_dir), dpi)
    for name, func in ALL_FIGS:
        P.fig(name, func)
    if ts_path is not None and Path(ts_path).exists():
        plot_example_users(P, Path(ts_path), n_examples)
    return P
