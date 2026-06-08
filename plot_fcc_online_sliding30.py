"""Matplotlib figures for the rolling/online 30-day-sliding FCC analysis.

Reads the analysis outputs written under ``--in-dir`` (parquet/csv) and writes a
fixed set of PNG figures under ``--fig-dir``. Every figure is saved at the
configured DPI (default 300) with title / axis labels / threshold reference
lines / an n-count annotation. Uses ONLY matplotlib (no seaborn).

Each figure is wrapped in its own try/except: a failure prints
``[skip] <name>: <reason>`` and never aborts the rest. Missing input files or
columns are treated as a skip, not a crash.

Style follows ``plot_fcc_learning_actions_final.py`` (tight_layout / _save with
bbox_inches="tight" / plt.close).

Verified debug command::

    python plot_fcc_online_sliding30.py \
      --in-dir data/processed/fcc_online_debug \
      --fig-dir data/reports/figures/fcc_online_debug --dpi 150 --n-examples 6
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# trailing metadata columns present on every output file -- ignored everywhere.
META_COLS = ("analysis_timestamp", "code_version", "window_days", "stride_days",
             "effective_step_definition")

STATEFUL_ORDER = ["STATEFUL_NORMAL", "STATEFUL_WATCH", "STATEFUL_GAUGE_RESET_CANDIDATE",
                  "STATEFUL_FW_CHECK_CANDIDATE", "STATEFUL_REVIEW"]
STATEFUL_COLORS = {
    "STATEFUL_NORMAL": "steelblue",
    "STATEFUL_WATCH": "gold",
    "STATEFUL_GAUGE_RESET_CANDIDATE": "darkorange",
    "STATEFUL_FW_CHECK_CANDIDATE": "darkred",
    "STATEFUL_REVIEW": "lightgray",
}
THRESHOLD_COLORS = {
    "primary_80_20_80": "darkred",
    "secondary_85_15_85": "orange",
    "strict_90_10_90": "green",
}
FW_PROXY = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
GAUGE_PROXY = "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY"


# --------------------------------------------------------------------------- #
# small infra
# --------------------------------------------------------------------------- #
def _use_cjk_font() -> None:
    avail = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Yu Gothic", "Meiryo", "MS Gothic", "BIZ UDGothic", "Noto Sans CJK JP"):
        if cand in avail:
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams["axes.unicode_minus"] = False


class FigCounter:
    def __init__(self) -> None:
        self.written = 0
        self.skipped = 0


def _save(fig, path: Path, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _annot_n(ax, n: int, loc: str = "upper right") -> None:
    xy = (0.98, 0.97) if "right" in loc else (0.02, 0.97)
    ha = "right" if "right" in loc else "left"
    ax.annotate(f"n={n:,}", xy=xy, xycoords="axes fraction", ha=ha, va="top",
                fontsize=9, color="black",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.7))


def _read(path: Path, drop_meta: bool = True) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if drop_meta:
        df = df.drop(columns=[c for c in META_COLS if c in df.columns], errors="ignore")
    return df


def _need(df: pd.DataFrame, cols) -> None:
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise KeyError(f"missing columns {miss}")


def _safe_id(uid: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", str(uid))


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


class Plotter:
    """Wraps each figure call so one bad figure never aborts the rest."""

    def __init__(self, in_dir: Path, fig_dir: Path, dpi: int, counter: FigCounter) -> None:
        self.in_dir = in_dir
        self.fig_dir = fig_dir
        self.dpi = dpi
        self.c = counter
        self._cache: dict[str, pd.DataFrame] = {}

    def load(self, fname: str, drop_meta: bool = True) -> pd.DataFrame:
        if fname in self._cache:
            return self._cache[fname]
        path = self.in_dir / fname
        if not path.exists():
            raise FileNotFoundError(f"input file not found: {fname}")
        df = _read(path, drop_meta=drop_meta)
        self._cache[fname] = df
        return df

    def fig(self, name: str, func) -> None:
        """Run ``func(ax-or-self)`` building a figure saved to fig_dir/name."""
        out = self.fig_dir / name
        try:
            func(out)
            self.c.written += 1
            print(f"[ok]   {name}")
        except Exception as exc:  # noqa: BLE001 -- robustness is required
            self.c.skipped += 1
            print(f"[skip] {name}: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Dataset / coverage
# --------------------------------------------------------------------------- #
def fig_user_coverage(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["user_id", "window_end_date"])
    per_user = feat.groupby("user_id").size()
    dates = _as_date(feat["window_end_date"])
    cov = feat.assign(_d=dates).dropna(subset=["_d"]).groupby("_d").size().sort_index()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8))
    a1.hist(per_user.values, bins=min(40, max(5, per_user.nunique())), color="steelblue",
            alpha=0.8, edgecolor="black", lw=0.3)
    a1.set_xlabel("windows per user")
    a1.set_ylabel("users")
    a1.set_title(f"Per-user rolling window count (median={int(per_user.median())})")
    _annot_n(a1, int(per_user.shape[0]))
    a2.plot(cov.index, cov.values, color="darkred", lw=1.2)
    a2.set_xlabel("window_end_date")
    a2.set_ylabel("windows")
    a2.set_title("Window coverage over time")
    a2.tick_params(axis="x", rotation=30)
    _annot_n(a2, int(feat.shape[0]), loc="upper left")
    fig.suptitle("Rolling 30d window user coverage", fontsize=12)
    _save(fig, out, P.dpi)


def fig_quality_counts(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["window_data_quality_label"])
    vc = feat["window_data_quality_label"].value_counts()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    b = ax.bar(range(len(vc)), vc.values, color="teal", edgecolor="black", lw=0.4)
    ax.bar_label(b, fontweight="bold", fontsize=8)
    ax.set_xticks(range(len(vc)))
    ax.set_xticklabels([str(k).replace("WINDOW_QUALITY_", "") for k in vc.index],
                       rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("windows")
    ax.set_title("Window data-quality label counts")
    _annot_n(ax, int(vc.sum()))
    _save(fig, out, P.dpi)


def fig_interval_dist(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    cols = [c for c in ("median_interval_h", "p95_interval_h") if c in feat.columns]
    if not cols:
        raise KeyError("no median_interval_h / p95_interval_h")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    allvals = pd.concat([feat[c] for c in cols]).replace([np.inf, -np.inf], np.nan).dropna()
    hi = float(np.nanpercentile(allvals, 99)) if len(allvals) else 1.0
    bins = np.linspace(0, max(hi, 1.0), 50)
    colors = {"median_interval_h": "steelblue", "p95_interval_h": "darkred"}
    n = 0
    for c in cols:
        d = feat[c].replace([np.inf, -np.inf], np.nan).dropna()
        n = max(n, len(d))
        ax.hist(d.clip(upper=bins[-1]), bins=bins, alpha=0.5, label=c, color=colors.get(c))
    ax.axvline(1.0, color="black", ls="--", lw=1)
    ax.text(1.0, ax.get_ylim()[1] * 0.9, "1h", fontsize=8, rotation=90)
    ax.set_xlabel("sample interval (h)")
    ax.set_ylabel("windows")
    ax.legend(fontsize=8)
    ax.set_title("Window sample-interval distribution")
    _annot_n(ax, n)
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Episode / response
# --------------------------------------------------------------------------- #
def fig_episode_counts(P: Plotter, out: Path) -> None:
    ep = P.load("rolling_30d_learning_episodes.parquet")
    _need(ep, ["threshold_name", "episode_quality"])
    ct = pd.crosstab(ep["threshold_name"], ep["episode_quality"])
    order = [t for t in THRESHOLD_COLORS if t in ct.index] + \
            [t for t in ct.index if t not in THRESHOLD_COLORS]
    ct = ct.reindex(order)
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(ct))
    width = 0.8 / max(1, len(ct.columns))
    qcolors = {"ok": "green", "large_gap": "lightgray", "missing_required_value": "orange",
               "invalid_order": "darkred"}
    for i, q in enumerate(ct.columns):
        ax.bar(x + i * width, ct[q].values, width, label=q, color=qcolors.get(q))
    ax.set_xticks(x + width * (len(ct.columns) - 1) / 2)
    ax.set_xticklabels(ct.index, fontsize=8)
    ax.set_ylabel("episodes")
    ax.legend(fontsize=8, title="quality")
    ax.set_title("Learning-episode counts by threshold x quality")
    _annot_n(ax, int(ct.values.sum()))
    _save(fig, out, P.dpi)


def fig_response_delay_cdf(P: Plotter, out: Path) -> None:
    ep = P.load("rolling_30d_learning_episodes.parquet")
    _need(ep, ["threshold_name", "response_status_72h", "response_delay_h"])
    fig, ax = plt.subplots(figsize=(8, 5))
    total = 0
    for name in [t for t in THRESHOLD_COLORS if t in set(ep["threshold_name"])]:
        sub = ep[(ep["threshold_name"] == name) &
                 (ep["response_status_72h"] == "responded")]
        d = sub["response_delay_h"].replace([np.inf, -np.inf], np.nan).dropna()
        d = d[d >= 0]
        if len(d):
            xs = np.sort(d.values)
            ys = np.arange(1, len(xs) + 1) / len(xs)
            ax.plot(xs, ys, label=f"{name} (n={len(xs)})", color=THRESHOLD_COLORS[name])
            total += len(xs)
    if total == 0:
        raise ValueError("no responded primary episodes with response_delay_h")
    for x in (24, 72, 168):
        ax.axvline(x, color="black", ls="--", lw=1)
        ax.text(x, 0.05, f"{x}h", fontsize=8, rotation=90)
    ax.set_xscale("symlog")
    ax.set_xlabel("response delay after episode end (h)")
    ax.set_ylabel("CDF")
    ax.legend(fontsize=8)
    ax.set_title("FCC response-delay CDF (responded episodes)")
    _annot_n(ax, total, loc="lower right")
    _save(fig, out, P.dpi)


def fig_gap_sensitivity(P: Plotter, out: Path) -> None:
    g = P.load("fcc_online_sensitivity_gap.csv")
    _need(g, ["episode_max_gap_hours", "n_ok", "n_large_gap"])
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    x = np.arange(len(g))
    ax.bar(x - 0.2, g["n_ok"], 0.4, label="n_ok", color="green")
    ax.bar(x + 0.2, g["n_large_gap"], 0.4, label="n_large_gap", color="lightgray")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(v)}h" for v in g["episode_max_gap_hours"]])
    ax.set_xlabel("episode max-gap threshold")
    ax.set_ylabel("episodes")
    ax.legend(loc="upper left", fontsize=8)
    if "ok_fraction" in g.columns:
        ax2 = ax.twinx()
        ax2.plot(x, g["ok_fraction"], "o-", color="darkred", label="ok_fraction")
        ax2.set_ylabel("ok_fraction", color="darkred")
        ax2.set_ylim(0, 1)
        ax2.legend(loc="upper right", fontsize=8)
    ax.set_title("Episode-quality gap sensitivity (ok vs large_gap)")
    _annot_n(ax, int(g[["n_ok", "n_large_gap"]].sum().sum()), loc="upper center")
    _save(fig, out, P.dpi)


def fig_censored_over_time(P: Plotter, out: Path) -> None:
    # Prefer state-daily cumulative censored; fall back to daily_labels window_label.
    series = {}
    n = 0
    try:
        st = P.load("online_fcc_user_state_daily.parquet")
        if {"window_end_date", "cum_primary_censored_since_last_fcc_change"}.issubset(st.columns):
            st = st.assign(_d=_as_date(st["window_end_date"]))
            agg = st.dropna(subset=["_d"]).groupby("_d")[
                "cum_primary_censored_since_last_fcc_change"].sum().sort_index()
            series["primary censored (cum)"] = agg
            n = int(st.shape[0])
    except Exception:
        pass
    try:
        dl = P.load("online_fcc_daily_labels.parquet")
        if {"window_end_date", "window_label"}.issubset(dl.columns):
            dl = dl.assign(_d=_as_date(dl["window_end_date"]))
            pend = dl[dl["window_label"].isin(["WINDOW_OPPORTUNITY_NO_RESPONSE",
                                               "WINDOW_LARGE_GAP_AMBIGUOUS"])]
            agg = pend.dropna(subset=["_d"]).groupby("_d").size().sort_index()
            series["pending/ambiguous windows"] = agg
            n = max(n, int(dl.shape[0]))
    except Exception:
        pass
    if not series:
        raise KeyError("no censored/pending source columns available")
    fig, ax = plt.subplots(figsize=(11, 4.8))
    for lab, s in series.items():
        ax.plot(s.index, s.values, lw=1.2, label=lab)
    ax.set_xlabel("window_end_date")
    ax.set_ylabel("count")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=30)
    ax.set_title("Censored / pending counts over time")
    _annot_n(ax, n, loc="upper left")
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# ML model
# --------------------------------------------------------------------------- #
def fig_model_roc_pr(P: Plotter, out: Path) -> None:
    from sklearn.metrics import roc_curve, precision_recall_curve, roc_auc_score, \
        average_precision_score
    pred = P.load("episode_response_model_predictions.parquet")
    _need(pred, ["y", "p_response"])
    d = pred[["y", "p_response"]].replace([np.inf, -np.inf], np.nan).dropna()
    y = d["y"].to_numpy().astype(int)
    p = d["p_response"].to_numpy(dtype=float)
    if len(np.unique(y)) < 2:
        raise ValueError("y has a single class; ROC/PR undefined")
    fpr, tpr, _ = roc_curve(y, p)
    prec, rec, _ = precision_recall_curve(y, p)
    auc = roc_auc_score(y, p)
    ap = average_precision_score(y, p)
    # annotate AUCs from metrics.csv if available
    msg = ""
    try:
        m = P.load("episode_response_model_metrics.csv")
        if {"roc_auc", "pr_auc"}.issubset(m.columns) and len(m):
            r0 = m.iloc[0]
            msg = f"  metrics.csv: roc_auc={r0['roc_auc']} pr_auc={r0['pr_auc']}"
    except Exception:
        pass
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.8))
    a1.plot(fpr, tpr, color="darkred", label=f"AUC={auc:.3f}")
    a1.plot([0, 1], [0, 1], "k--", lw=0.7)
    a1.set_xlabel("FPR")
    a1.set_ylabel("TPR")
    a1.set_title("ROC")
    a1.legend(fontsize=9)
    a2.plot(rec, prec, color="steelblue", label=f"AP={ap:.3f}")
    a2.axhline(y.mean(), color="gray", ls=":", lw=1, label=f"base={y.mean():.3f}")
    a2.set_xlabel("recall")
    a2.set_ylabel("precision")
    a2.set_title("Precision-Recall")
    a2.legend(fontsize=9)
    _annot_n(a1, len(y), loc="lower right")
    fig.suptitle(f"Episode response model ROC/PR (n={len(y):,}){msg}", fontsize=11)
    _save(fig, out, P.dpi)


def fig_model_calibration(P: Plotter, out: Path) -> None:
    pred = P.load("episode_response_model_predictions.parquet")
    _need(pred, ["y", "p_response"])
    d = pred[["y", "p_response"]].replace([np.inf, -np.inf], np.nan).dropna()
    y = d["y"].to_numpy().astype(float)
    p = d["p_response"].to_numpy(dtype=float)
    if len(d) < 10:
        raise ValueError("too few predictions for a reliability diagram")
    brier = float(np.mean((p - y) ** 2))
    nb = 10
    qs = np.unique(np.quantile(p, np.linspace(0, 1, nb + 1)))
    if len(qs) < 3:
        qs = np.linspace(p.min(), p.max() + 1e-9, 4)
    bins = pd.cut(pd.Series(p), bins=qs, include_lowest=True, duplicates="drop")
    grp = pd.DataFrame({"p": p, "y": y, "b": bins}).groupby("b", observed=True)
    mp = grp["p"].mean().values
    ob = grp["y"].mean().values
    fig, ax = plt.subplots(figsize=(6.2, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=0.8, label="perfect")
    ax.plot(mp, ob, "o-", color="darkred", label="model")
    ax.set_xlabel("mean predicted p_response")
    ax.set_ylabel("observed response rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=9)
    ax.set_title(f"Reliability diagram (Brier={brier:.3f})")
    _annot_n(ax, len(y), loc="upper left")
    _save(fig, out, P.dpi)


def fig_model_importance(P: Plotter, out: Path) -> None:
    imp = P.load("episode_response_model_importances.csv")
    _need(imp, ["feature", "weight"])
    sub = imp.copy()
    sub["weight"] = pd.to_numeric(sub["weight"], errors="coerce")
    sub = sub.dropna(subset=["weight"])
    if sub.empty:
        raise ValueError("all importance weights are NaN")
    sub["abs"] = sub["weight"].abs()
    sub = sub.sort_values("abs", ascending=False).head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 6))
    y = np.arange(len(sub))
    ax.barh(y, sub["weight"].values,
            color=["darkred" if w < 0 else "steelblue" for w in sub["weight"]])
    ax.axvline(0, color="black", lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(sub["feature"], fontsize=8)
    ax.set_xlabel("weight")
    ax.set_title("Episode response model feature importance (top 15 by |weight|)")
    _annot_n(ax, int(imp.shape[0]), loc="lower right")
    _save(fig, out, P.dpi)


def fig_p_response_by_status(P: Plotter, out: Path) -> None:
    pred = P.load("episode_response_model_predictions.parquet")
    _need(pred, ["p_response", "response_status_72h"])
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bins = np.linspace(0, 1, 26)
    n = 0
    for status, color in [("responded", "green"), ("no_response", "darkred")]:
        d = pred.loc[pred["response_status_72h"] == status, "p_response"]
        d = d.replace([np.inf, -np.inf], np.nan).dropna()
        if len(d):
            ax.hist(d, bins=bins, alpha=0.5, label=f"{status} (n={len(d)})", color=color)
            n += len(d)
    if n == 0:
        raise ValueError("no responded/no_response predictions")
    ax.axvline(0.5, color="black", ls="--", lw=1)
    ax.set_xlabel("p_response")
    ax.set_ylabel("episodes")
    ax.legend(fontsize=8)
    ax.set_title("p_response distribution by observed 72h status")
    _annot_n(ax, n)
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Anomaly / scoring
# --------------------------------------------------------------------------- #
def fig_fw_anomaly_dist(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["fw_response_anomaly_score_30d", "n_complete_ok_opportunities_30d"])
    sub = feat[feat["n_complete_ok_opportunities_30d"] >= 1]
    d = sub["fw_response_anomaly_score_30d"].replace([np.inf, -np.inf], np.nan).dropna()
    if d.empty:
        raise ValueError("no windows with >=1 complete OK opportunity")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    hi = max(3.5, float(np.nanpercentile(d, 99)))
    ax.hist(d.clip(upper=hi), bins=50, color="purple", alpha=0.75)
    for x in (1.0, 2.0, 3.0):
        ax.axvline(x, color="black", ls="--", lw=1)
        ax.text(x, ax.get_ylim()[1] * 0.9, f"{x:.0f}", fontsize=8)
    ax.set_xlabel("fw_response_anomaly_score_30d")
    ax.set_ylabel("windows (>=1 complete OK opp)")
    ax.set_title("FW response anomaly score distribution")
    _annot_n(ax, int(len(d)))
    _save(fig, out, P.dpi)


def fig_p_all_no_response(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["p_all_no_response_30d"])
    d = feat["p_all_no_response_30d"].replace([np.inf, -np.inf], np.nan).dropna()
    d = d[(d > 0) & (d <= 1)]
    if d.empty:
        raise ValueError("no valid p_all_no_response_30d in (0,1]")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    logd = np.log10(d)
    bins = np.linspace(logd.min(), 0, 50)
    ax.hist(logd, bins=bins, color="darkorange", alpha=0.8)
    for x in (0.05, 0.01, 0.001):
        lx = np.log10(x)
        ax.axvline(lx, color="black", ls="--", lw=1)
        ax.text(lx, ax.get_ylim()[1] * 0.9, f"{x}", fontsize=8, rotation=90)
    ax.set_xlabel("log10 p_all_no_response_30d")
    ax.set_ylabel("windows")
    ax.set_title("P(all no-response) distribution (log10)")
    _annot_n(ax, int(len(d)), loc="upper left")
    _save(fig, out, P.dpi)


def fig_expected_vs_observed(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["expected_response_30d", "observed_response_30d"])
    d = feat[["expected_response_30d", "observed_response_30d"]].replace(
        [np.inf, -np.inf], np.nan).dropna()
    if d.empty:
        raise ValueError("no expected/observed pairs")
    if len(d) > 5000:
        d = d.iloc[np.linspace(0, len(d) - 1, 5000).astype(int)]
    fig, ax = plt.subplots(figsize=(6.8, 6.5))
    ax.scatter(d["expected_response_30d"], d["observed_response_30d"], s=14, alpha=0.4,
               color="steelblue", edgecolors="none")
    lim = max(1.0, float(d.max().max()) * 1.05)
    ax.plot([0, lim], [0, lim], "k--", lw=0.8, label="y=x")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("expected_response_30d (model)")
    ax.set_ylabel("observed_response_30d")
    ax.legend(fontsize=9)
    ax.set_title("Expected vs observed responses per window")
    _annot_n(ax, int(len(d)), loc="upper left")
    _save(fig, out, P.dpi)


def fig_score_vs_opportunities(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["n_complete_ok_opportunities_30d", "fw_response_anomaly_score_30d"])
    d = feat[["n_complete_ok_opportunities_30d", "fw_response_anomaly_score_30d"]].replace(
        [np.inf, -np.inf], np.nan).dropna()
    if d.empty:
        raise ValueError("no opportunity/score pairs")
    if len(d) > 5000:
        d = d.iloc[np.linspace(0, len(d) - 1, 5000).astype(int)]
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    ax.scatter(d["n_complete_ok_opportunities_30d"], d["fw_response_anomaly_score_30d"],
               s=16, alpha=0.4, color="darkred", edgecolors="none")
    for yv in (1.0, 2.0, 3.0):
        ax.axhline(yv, color="black", ls="--", lw=0.8)
    ax.set_xlabel("n_complete_ok_opportunities_30d")
    ax.set_ylabel("fw_response_anomaly_score_30d")
    ax.set_title("Anomaly score vs complete OK opportunities")
    _annot_n(ax, int(len(d)))
    _save(fig, out, P.dpi)


def fig_conformal_dist(P: Plotter, out: Path) -> None:
    feat = P.load("rolling_30d_user_features.parquet")
    _need(feat, ["conformal_p"])
    d = feat["conformal_p"].replace([np.inf, -np.inf], np.nan).dropna()
    d = d[(d >= 0) & (d <= 1)]
    if d.empty:
        raise ValueError("no valid conformal_p in [0,1]")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.hist(d, bins=np.linspace(0, 1, 41), color="seagreen", alpha=0.8)
    for x in (0.05, 0.01):
        ax.axvline(x, color="black", ls="--", lw=1)
        ax.text(x, ax.get_ylim()[1] * 0.9, f"{x}", fontsize=8, rotation=90)
    ax.set_xlabel("conformal_p")
    ax.set_ylabel("windows")
    ax.set_title("Conformal p-value distribution")
    _annot_n(ax, int(len(d)))
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
def fig_cluster_heatmap(P: Plotter, out: Path) -> None:
    prof = P.load("usage_cluster_profiles.csv")
    _need(prof, ["cluster_profile_name"])
    med = [c for c in prof.columns if c.startswith("median_")]
    if not med:
        raise KeyError("no median_* columns")
    grp = prof.groupby("cluster_profile_name")[med].mean()
    z = (grp - grp.mean()) / grp.std(ddof=0).replace(0, 1)
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(med)), max(4, 0.7 * len(grp) + 2)))
    im = ax.imshow(z.values, cmap="coolwarm", aspect="auto", vmin=-2, vmax=2)
    ax.set_xticks(range(len(med)))
    ax.set_xticklabels([c.replace("median_", "") for c in med], rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(len(grp)))
    ax.set_yticklabels([str(i)[:28] for i in grp.index], fontsize=8)
    for i in range(len(grp)):
        for j in range(len(med)):
            ax.text(j, i, f"{grp.values[i, j]:.2g}", ha="center", va="center",
                    fontsize=6, color="black")
    fig.colorbar(im, ax=ax, fraction=0.03, label="z(median)")
    ax.set_title("Usage cluster profile heatmap (median_* features, z-scored)")
    _annot_n(ax, int(len(grp)), loc="upper left")
    _save(fig, out, P.dpi)


def fig_cluster_counts(P: Plotter, out: Path) -> None:
    asg = P.load("usage_cluster_assignments.parquet")
    _need(asg, ["cluster_profile_name"])
    vc = asg["cluster_profile_name"].value_counts()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    b = ax.bar(range(len(vc)), vc.values, color="steelblue", edgecolor="black", lw=0.4)
    ax.bar_label(b, fontweight="bold", fontsize=8)
    ax.set_xticks(range(len(vc)))
    ax.set_xticklabels([str(k) for k in vc.index], rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("windows")
    ax.set_title("Windows per usage cluster profile")
    _annot_n(ax, int(vc.sum()))
    _save(fig, out, P.dpi)


def fig_cluster_pca(P: Plotter, out: Path) -> None:
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    feat = P.load("rolling_30d_user_features.parquet")
    asg = P.load("usage_cluster_assignments.parquet")
    cols = ["cycle_delta_30d", "ac_time_ratio_30d", "rsoc_swing_30d", "rsoc_min_30d",
            "n_80_20_80_ok_complete_30d", "fcc_effective_changes_30d"]
    cols = [c for c in cols if c in feat.columns]
    if len(cols) < 2:
        raise KeyError("not enough cluster feature columns for PCA")
    df = feat.merge(asg[["user_id", "window_end_date", "cluster_id"]],
                    on=["user_id", "window_end_date"], how="inner")
    df = df[pd.to_numeric(df["cluster_id"], errors="coerce").fillna(-99) >= 0]
    if df.empty or df["cluster_id"].nunique() < 2:
        raise ValueError("fewer than 2 real clusters after filtering noise")
    if len(df) > 5000:
        df = df.iloc[np.linspace(0, len(df) - 1, 5000).astype(int)]
    X = df[cols].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True))
    pc = PCA(n_components=2).fit_transform(StandardScaler().fit_transform(X))
    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    cids = sorted(df["cluster_id"].unique())
    cmap = plt.get_cmap("tab10")
    for k, cid in enumerate(cids):
        m = (df["cluster_id"] == cid).values
        ax.scatter(pc[m, 0], pc[m, 1], s=16, alpha=0.5, color=cmap(k % 10),
                   label=f"cluster {cid}", edgecolors="none")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.legend(fontsize=7, ncol=2)
    ax.set_title("Usage clusters (PCA 2-D of window features)")
    _annot_n(ax, int(len(df)), loc="upper left")
    _save(fig, out, P.dpi)


def fig_action_hint_dist(P: Plotter, out: Path) -> None:
    asg = P.load("usage_cluster_assignments.parquet")
    _need(asg, ["cluster_action_hint"])
    vc = asg["cluster_action_hint"].value_counts()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    b = ax.bar(range(len(vc)), vc.values, color="darkorange", edgecolor="black", lw=0.4)
    ax.bar_label(b, fontweight="bold", fontsize=8)
    ax.set_xticks(range(len(vc)))
    ax.set_xticklabels([str(k) for k in vc.index], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("windows")
    ax.set_title("Cluster action-hint distribution")
    _annot_n(ax, int(vc.sum()))
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Online / backtest
# --------------------------------------------------------------------------- #
def fig_latest_funnel(P: Plotter, out: Path) -> None:
    snap = P.load("online_fcc_current_snapshot.csv")
    _need(snap, ["stateful_label"])
    vc = snap["stateful_label"].value_counts()
    order = [s for s in STATEFUL_ORDER if s in vc.index] + \
            [s for s in vc.index if s not in STATEFUL_ORDER]
    vc = vc.reindex(order)
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ys = list(range(len(vc)))[::-1]
    for y, lab in zip(ys, vc.index):
        v = int(vc[lab])
        ax.barh(y, v, color=STATEFUL_COLORS.get(lab, "gray"), edgecolor="black", lw=0.5)
        ax.text(v, y, f" {v}", va="center", fontweight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([str(s).replace("STATEFUL_", "") for s in vc.index], fontsize=8)
    ax.set_xlabel("users (snapshot)")
    ax.set_title("Latest snapshot stateful-label funnel")
    _annot_n(ax, int(vc.sum()), loc="lower right")
    _save(fig, out, P.dpi)


def fig_window_label_counts(P: Plotter, out: Path) -> None:
    dl = P.load("online_fcc_daily_labels.parquet")
    _need(dl, ["window_label"])
    vc = dl["window_label"].value_counts()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    b = ax.bar(range(len(vc)), vc.values, color="teal", edgecolor="black", lw=0.4)
    ax.bar_label(b, fontweight="bold", fontsize=8)
    ax.set_xticks(range(len(vc)))
    ax.set_xticklabels([str(k).replace("WINDOW_", "") for k in vc.index],
                       rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("windows")
    ax.set_title("Window-label counts (daily labels)")
    _annot_n(ax, int(vc.sum()))
    _save(fig, out, P.dpi)


def fig_stateful_vs_stateless(P: Plotter, out: Path) -> None:
    bs = P.load("backtest_detection_summary.csv")
    _need(bs, ["metric", "key", "value"])
    comp = bs[bs["metric"] == "comparison"].set_index("key")["value"]
    # same-threshold detection comparison (state vs single 30d window) + strict action gates
    keys = ["stateful_detection_n", "stateless_detection_n", "overlap_detection_n",
            "stateful_only_detection_n", "stateless_only_detection_n", "action_fw_n", "action_gauge_n"]
    present = [k for k in keys if k in comp.index]
    if not present:
        raise KeyError("no comparison keys in backtest_detection_summary")
    vals = [float(comp[k]) for k in present]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    colors = {"stateful_detection_n": "darkred", "stateless_detection_n": "steelblue",
              "overlap_detection_n": "purple", "stateful_only_detection_n": "darkorange",
              "stateless_only_detection_n": "gray", "action_fw_n": "firebrick",
              "action_gauge_n": "seagreen"}
    b = ax.bar(range(len(present)), vals, color=[colors.get(k, "slategray") for k in present],
               edgecolor="black", lw=0.4)
    ax.bar_label(b, fmt="%.0f", fontweight="bold", fontsize=9)
    ax.set_xticks(range(len(present)))
    ax.set_xticklabels([k.replace("_n", "").replace("_", "\n") for k in present],
                       rotation=0, ha="center", fontsize=7.5)
    ax.set_ylabel("users")
    ax.set_title("Same-threshold no-response detection: stateful vs stateless (+ strict action gates)")
    _annot_n(ax, int(sum(vals)))
    _save(fig, out, P.dpi)


def _lead_time_fig(P: Plotter, out: Path, label: str, title: str) -> None:
    lt = P.load("backtest_lead_time.csv")
    _need(lt, ["final_label", "lead_time_days"])
    d = lt.loc[lt["final_label"] == label, "lead_time_days"].dropna()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    if len(d):
        ax.hist(d, bins=min(20, max(4, len(d))), color="darkred", alpha=0.8,
                edgecolor="black", lw=0.4)
        ax.axvline(float(d.median()), color="black", ls="--", lw=1,
                   label=f"median={d.median():.0f}d")
        ax.legend(fontsize=9)
        ax.set_ylabel("users")
    else:
        ax.text(0.5, 0.5, "no users for this proxy label", ha="center", va="center",
                transform=ax.transAxes, fontsize=11, color="gray")
        ax.set_ylim(0, 1)
    ax.set_xlabel("lead time (days) first alert -> last obs")
    ax.set_title(title)
    _annot_n(ax, int(len(d)))
    _save(fig, out, P.dpi)


def fig_lead_time_fw(P: Plotter, out: Path) -> None:
    _lead_time_fig(P, out, FW_PROXY, "Time-to-first-alert (FW-check proxy)")


def fig_lead_time_gauge(P: Plotter, out: Path) -> None:
    _lead_time_fig(P, out, GAUGE_PROXY, "Time-to-first-alert (gauge-reset proxy)")


def _topn_fig(P: Plotter, out: Path, score_col: str, proxy: str, title: str) -> None:
    ty = P.load("backtest_topn_yield.csv")
    _need(ty, ["score_col", "proxy_label", "N", "precision_at_N", "recall_at_N"])
    sub = ty[(ty["score_col"] == score_col) & (ty["proxy_label"] == proxy)].sort_values("N")
    if sub.empty:
        raise ValueError(f"no rows for score_col={score_col} proxy={proxy}")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(sub["N"], sub["precision_at_N"], "o-", color="darkred", label="precision@N")
    ax.plot(sub["N"], sub["recall_at_N"], "s-", color="steelblue", label="recall@N")
    ax.set_xlabel("N (top-ranked users)")
    ax.set_ylabel("rate")
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=9)
    tp = int(sub["total_proxy_pos"].iloc[0]) if "total_proxy_pos" in sub.columns else 0
    ax.set_title(f"{title} (total proxy positives={tp})")
    _annot_n(ax, int(len(sub)), loc="upper right")
    _save(fig, out, P.dpi)


def fig_topn_fw(P: Plotter, out: Path) -> None:
    _topn_fig(P, out, "cum_fw_response_anomaly_score", FW_PROXY,
              "Top-N yield (FW proxy)")


def fig_topn_gauge(P: Plotter, out: Path) -> None:
    _topn_fig(P, out, "days_since_last_effective_fcc_change", GAUGE_PROXY,
              "Top-N yield (gauge-reset proxy)")


def fig_active_false_alert(P: Plotter, out: Path) -> None:
    dl = P.load("online_fcc_daily_labels.parquet")
    _need(dl, ["window_end_date", "stateful_label"])
    actionable = {"STATEFUL_FW_CHECK_CANDIDATE", "STATEFUL_GAUGE_RESET_CANDIDATE"}
    dl = dl.assign(_d=_as_date(dl["window_end_date"]))
    dl = dl.dropna(subset=["_d"])
    grp = dl.groupby("_d")
    n_act = grp.apply(lambda g: g["stateful_label"].isin(actionable).sum())
    n_tot = grp.size()
    rate = (n_act / n_tot).sort_index()
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(rate.index, rate.values, color="darkred", lw=1.2, label="actionable fraction")
    ax.set_xlabel("window_end_date")
    ax.set_ylabel("fraction of users in actionable label")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(fontsize=8)
    ax.set_title("Actionable stateful-label fraction over time (false-alert proxy; no SoH ground truth)")
    _annot_n(ax, int(n_act.sum()), loc="upper left")
    _save(fig, out, P.dpi)


def fig_transition_matrix(P: Plotter, out: Path) -> None:
    dl = P.load("online_fcc_daily_labels.parquet")
    _need(dl, ["user_id", "window_end_date", "stateful_label"])
    df = dl.assign(_d=_as_date(dl["window_end_date"])).sort_values(["user_id", "_d"])
    df["prev"] = df.groupby("user_id")["stateful_label"].shift(1)
    tr = df.dropna(subset=["prev"])
    if tr.empty:
        raise ValueError("no consecutive label pairs")
    ct = pd.crosstab(tr["prev"], tr["stateful_label"])
    labs = [s for s in STATEFUL_ORDER if s in ct.index or s in ct.columns]
    labs += [s for s in set(ct.index) | set(ct.columns) if s not in labs]
    ct = ct.reindex(index=labs, columns=labs, fill_value=0)
    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = ax.imshow(ct.values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(labs)))
    ax.set_xticklabels([s.replace("STATEFUL_", "") for s in labs], rotation=35, ha="right", fontsize=7)
    ax.set_yticks(range(len(labs)))
    ax.set_yticklabels([s.replace("STATEFUL_", "") for s in labs], fontsize=7)
    mx = ct.values.max() if ct.values.size else 1
    for i in range(len(labs)):
        for j in range(len(labs)):
            v = ct.values[i, j]
            if v:
                ax.text(j, i, int(v), ha="center", va="center", fontsize=7,
                        color="white" if v > mx / 2 else "black")
    fig.colorbar(im, ax=ax, fraction=0.04, label="transitions")
    ax.set_xlabel("to")
    ax.set_ylabel("from")
    ax.set_title("Stateful-label transition matrix (consecutive windows)")
    _annot_n(ax, int(ct.values.sum()), loc="upper left")
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Enrichment
# --------------------------------------------------------------------------- #
def fig_hw_enrichment(P: Plotter, out: Path) -> None:
    en = P.load("hardware_enrichment_online_fw_candidates.csv")
    _need(en, ["group_value", "shrunk_rate", "ci_low", "ci_high"])
    sub = en.copy().sort_values("shrunk_rate", ascending=False).head(15)
    if sub.empty:
        raise ValueError("no enrichment groups")
    sub = sub.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.45 * len(sub) + 2)))
    y = np.arange(len(sub))
    xerr = np.vstack([
        (sub["shrunk_rate"] - sub["ci_low"]).clip(lower=0).values,
        (sub["ci_high"] - sub["shrunk_rate"]).clip(lower=0).values,
    ])
    ax.barh(y, sub["shrunk_rate"].values, color="darkred", alpha=0.6)
    ax.errorbar(sub["shrunk_rate"].values, y, xerr=xerr, fmt="none", ecolor="black",
                elinewidth=0.8, capsize=2)
    if "raw_rate" in sub.columns:
        ax.scatter(sub["raw_rate"].values, y, color="black", s=14, zorder=5, label="raw_rate")
    if "fleet_rate" in en.columns and en["fleet_rate"].notna().any():
        fr = float(en["fleet_rate"].dropna().iloc[0])
        ax.axvline(fr, color="blue", ls="--", lw=1, label=f"fleet_rate={fr:.3g}")
    for yi, (_, r) in zip(y, sub.iterrows()):
        nt = int(r["n_total"]) if "n_total" in sub.columns else 0
        nc = int(r["n_candidate"]) if "n_candidate" in sub.columns else 0
        ax.text(0, yi, f" {nc}/{nt}", fontsize=6, va="center")
    ax.set_yticks(y)
    ax.set_yticklabels([str(v)[:24] for v in sub["group_value"]], fontsize=7)
    ax.set_xlabel("shrunk FW-candidate rate")
    ax.legend(fontsize=8)
    ax.set_title("Hardware enrichment: FW candidate rate (EB shrink + CI)")
    _annot_n(ax, int(len(sub)), loc="lower right")
    _save(fig, out, P.dpi)


def fig_top_fru(P: Plotter, out: Path) -> None:
    en = P.load("hardware_enrichment_online_fw_candidates.csv")
    _need(en, ["group_axis", "group_value", "n_total", "n_candidate"])
    sub = en[en["group_axis"] == "batt_fru"].copy()
    if sub.empty:
        raise ValueError("no batt_fru rows in enrichment file")
    sub = sub.sort_values("shrunk_rate" if "shrunk_rate" in sub.columns else "n_candidate",
                          ascending=False).head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, max(4, 0.45 * len(sub) + 2)))
    y = np.arange(len(sub))
    ax.barh(y, sub["n_total"].values, color="lightgray", label="n_total")
    ax.barh(y, sub["n_candidate"].values, color="darkred", label="n_candidate")
    ax.set_yticks(y)
    ax.set_yticklabels([str(v)[:24] for v in sub["group_value"]], fontsize=7)
    ax.set_xlabel("count")
    ax.legend(fontsize=8)
    ax.set_title("Top FRU case-control (FW candidates)")
    _annot_n(ax, int(sub["n_total"].sum()), loc="lower right")
    _save(fig, out, P.dpi)


# --------------------------------------------------------------------------- #
# Example users (section 15.8)
# --------------------------------------------------------------------------- #
def _episode_ts_col(df: pd.DataFrame) -> Optional[str]:
    for c in ("start_ts", "end_ts"):
        if c in df.columns:
            return c
    return None


def plot_example_users(P: Plotter, ts_path: Path, n_examples: int) -> None:
    if not ts_path.exists():
        print(f"[skip] example-users: timeseries not found at {ts_path}")
        P.c.skipped += 1
        return
    # column detection on the raw timeseries (read schema only, not the 3M rows)
    cols_needed = {"user_id", "timestamp"}
    rsoc_col = None
    fcc_col = None
    cyc_col = None
    import pyarrow.parquet as pq  # available with pandas parquet engine
    all_cols = set(pq.ParquetFile(str(ts_path)).schema.names)
    for cand in ("remainingCapacityInPercentage", "rsoc", "remaining_capacity_pct"):
        if cand in all_cols:
            rsoc_col = cand
            break
    for cand in ("fullChargeCapacity", "fcc", "full_charge_capacity"):
        if cand in all_cols:
            fcc_col = cand
            break
    for cand in ("cycleCount", "cycle_count", "cyclecount"):
        if cand in all_cols:
            cyc_col = cand
            break
    if not cols_needed.issubset(all_cols):
        print(f"[skip] example-users: timeseries missing {cols_needed - all_cols}")
        P.c.skipped += 1
        return
    read_cols = [c for c in ["user_id", "timestamp", rsoc_col, fcc_col, cyc_col] if c]
    ts = pd.read_parquet(ts_path, columns=read_cols)
    ts["timestamp"] = pd.to_datetime(ts["timestamp"], errors="coerce")

    # episodes + snapshot for overlays/annotations
    try:
        ep = P.load("rolling_30d_learning_episodes.parquet")
    except Exception:
        ep = pd.DataFrame()
    try:
        snap = P.load("online_fcc_current_snapshot.csv").set_index("user_id")
    except Exception:
        snap = pd.DataFrame()

    groups = [
        ("examples_fw_check_candidates", "online_fcc_action_candidates_fw_check.csv", None),
        ("examples_gauge_reset_candidates", "online_fcc_action_candidates_gauge_reset.csv", None),
        ("examples_watch_large_gap", "online_fcc_watchlist.csv", None),
        ("examples_normal_responding", None, "STATEFUL_NORMAL"),
    ]
    for folder, fname, normal_label in groups:
        sub = P.fig_dir / folder
        sub.mkdir(parents=True, exist_ok=True)
        # build the user list
        try:
            if normal_label is not None:
                if snap.empty or "stateful_label" not in snap.columns:
                    raise ValueError("snapshot lacks stateful_label")
                uids = snap.index[snap["stateful_label"] == normal_label].tolist()
            else:
                cand = P.load(fname)
                uids = cand["user_id"].dropna().tolist() if "user_id" in cand.columns else []
        except Exception as exc:
            print(f"[skip] {folder}: {type(exc).__name__}: {exc}")
            P.c.skipped += 1
            continue
        if not uids:
            print(f"[skip] {folder}: no users in source list")
            continue
        made = 0
        for uid in uids[:n_examples]:
            try:
                _plot_one_user(P, ts, ep, snap, uid, rsoc_col, fcc_col, cyc_col, sub)
                made += 1
                P.c.written += 1
            except Exception as exc:  # noqa: BLE001
                P.c.skipped += 1
                print(f"[skip] {folder}/{_safe_id(uid)}: {type(exc).__name__}: {exc}")
        print(f"[ok]   {folder}: {made} example figure(s)")


def _plot_one_user(P, ts, ep, snap, uid, rsoc_col, fcc_col, cyc_col, sub_dir) -> None:
    u = ts[ts["user_id"] == uid].dropna(subset=["timestamp"]).sort_values("timestamp")
    if u.empty:
        raise ValueError("no timeseries rows for user")
    panels = [("RSOC", rsoc_col), ("fullChargeCapacity", fcc_col), ("cycleCount", cyc_col)]
    panels = [(t, c) for t, c in panels if c is not None and c in u.columns]
    if not panels:
        raise ValueError("no plottable channels (rsoc/fcc/cycle) in timeseries")
    fig, axes = plt.subplots(len(panels), 1, figsize=(12, 2.6 * len(panels) + 0.6),
                             sharex=True)
    if len(panels) == 1:
        axes = [axes]
    # episode spans for this user
    eu = ep[ep["user_id"] == uid] if not ep.empty and "user_id" in ep.columns else pd.DataFrame()
    resp_color = {"responded": "green", "no_response": "darkred", "censored": "gray",
                  "unknown": "lightgray"}
    for ax, (title, col) in zip(axes, panels):
        ax.plot(u["timestamp"], u[col], color="steelblue", lw=0.8)
        ax.set_ylabel(title, fontsize=8)
        # shade learning-episode spans
        if not eu.empty and {"start_ts", "end_ts"}.issubset(eu.columns):
            for _, r in eu.iterrows():
                s, e = r["start_ts"], r["end_ts"]
                if pd.isna(s) or pd.isna(e):
                    continue
                rc = resp_color.get(str(r.get("response_status_72h", "unknown")), "lightgray")
                ax.axvspan(s, e, color=rc, alpha=0.12)
        # mark effective-change points on the FCC panel
        if title == "fullChargeCapacity":
            d = u[col].astype(float)
            chg = u["timestamp"][d.diff().abs() >= 50]
            for x in chg:
                ax.axvline(x, color="black", ls=":", lw=0.5, alpha=0.5)
    axes[-1].set_xlabel("timestamp")
    # title annotation from snapshot
    meta = ""
    if not snap.empty and uid in snap.index:
        r = snap.loc[uid]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        sl = r.get("stateful_label", "?")
        wl = r.get("window_label", "?")
        an = r.get("fw_response_anomaly_score_30d", float("nan"))
        ds = r.get("days_since_last_effective_fcc_change", float("nan"))
        try:
            meta = f"  [{sl} / {wl}  anomaly={float(an):.2f}  days_since_fcc={float(ds):.0f}]"
        except Exception:
            meta = f"  [{sl} / {wl}]"
    fig.suptitle(f"User {uid}{meta}\n(episode spans shaded by 72h response status)",
                 fontsize=10)
    _save(fig, sub_dir / f"{_safe_id(uid)}.png", P.dpi)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="Plot rolling/online 30d-sliding FCC figures")
    p.add_argument("--in-dir", default="data/processed/fcc_online")
    p.add_argument("--fig-dir", default="data/reports/figures/fcc_online")
    p.add_argument("--timeseries", default="data/processed/battery_timeseries_all.parquet")
    p.add_argument("--final-labels", default="data/processed/fcc_final_action_labels.csv")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--n-examples", type=int, default=12)
    a = p.parse_args()

    _use_cjk_font()
    in_dir = Path(a.in_dir)
    fig_dir = Path(a.fig_dir)
    fig_dir.mkdir(parents=True, exist_ok=True)
    counter = FigCounter()
    P = Plotter(in_dir, fig_dir, a.dpi, counter)

    print(f"in-dir : {in_dir}  (exists={in_dir.exists()})")
    print(f"fig-dir: {fig_dir}")

    figures = [
        # dataset / coverage
        ("rolling_window_user_coverage.png", fig_user_coverage),
        ("window_data_quality_counts.png", fig_quality_counts),
        ("window_sample_interval_distribution.png", fig_interval_dist),
        # episode / response
        ("rolling_episode_counts_by_threshold.png", fig_episode_counts),
        ("response_delay_cdf_online.png", fig_response_delay_cdf),
        ("episode_quality_gap_sensitivity_online.png", fig_gap_sensitivity),
        ("censored_pending_counts_over_time.png", fig_censored_over_time),
        # ml model
        ("episode_response_model_roc_pr.png", fig_model_roc_pr),
        ("episode_response_model_calibration.png", fig_model_calibration),
        ("episode_response_model_feature_importance.png", fig_model_importance),
        ("p_response_distribution_by_observed_status.png", fig_p_response_by_status),
        # anomaly
        ("fw_response_anomaly_score_distribution.png", fig_fw_anomaly_dist),
        ("p_all_no_response_distribution.png", fig_p_all_no_response),
        ("expected_vs_observed_response_by_window.png", fig_expected_vs_observed),
        ("score_vs_complete_opportunities.png", fig_score_vs_opportunities),
        ("conformal_pvalue_distribution.png", fig_conformal_dist),
        # clustering
        ("usage_cluster_profile_heatmap.png", fig_cluster_heatmap),
        ("usage_cluster_counts.png", fig_cluster_counts),
        ("usage_cluster_umap_or_pca.png", fig_cluster_pca),
        ("cluster_action_hint_distribution.png", fig_action_hint_dist),
        # online / backtest
        ("online_latest_funnel_counts.png", fig_latest_funnel),
        ("online_label_counts.png", fig_window_label_counts),
        ("stateful_vs_stateless_counts.png", fig_stateful_vs_stateless),
        ("time_to_first_alert_fw_proxy.png", fig_lead_time_fw),
        ("time_to_first_alert_gauge_proxy.png", fig_lead_time_gauge),
        ("topn_yield_curve_fw_proxy.png", fig_topn_fw),
        ("topn_yield_curve_gauge_proxy.png", fig_topn_gauge),
        ("active_false_alert_rate_over_time.png", fig_active_false_alert),
        ("watch_to_action_transition_matrix.png", fig_transition_matrix),
        # enrichment
        ("online_hardware_enrichment_fw_candidates.png", fig_hw_enrichment),
        ("top_fru_case_control_online.png", fig_top_fru),
    ]
    for name, func in figures:
        P.fig(name, lambda out, f=func: f(P, out))

    # example users
    try:
        plot_example_users(P, Path(a.timeseries), a.n_examples)
    except Exception as exc:  # noqa: BLE001
        counter.skipped += 1
        print(f"[skip] example-users: {type(exc).__name__}: {exc}")

    print("=" * 60)
    print(f"figures written : {counter.written}")
    print(f"figures skipped : {counter.skipped}")
    print(f"output dir      : {fig_dir}")


if __name__ == "__main__":
    main()
