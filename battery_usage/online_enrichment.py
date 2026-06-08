"""Fleet-level hardware/FW enrichment — applied ONLY AFTER classification (rolling30 spec 14).

Hardware identity (FRU / vendor / device_model / BIOS / EC / battery-FW version) is forbidden
as a classification feature (spec 0.4). This module looks at the *resulting* candidate sets
and asks the descriptive question "are FW-check (or Gauge) candidates over-represented in any
hardware group?" using:

  * beta-binomial empirical-Bayes shrinkage (stabilises small-group rates), and
  * Fisher's exact test with Benjamini-Hochberg FDR correction.

:func:`assert_no_hw_in_classification` is called by the pipeline to *prove* (raise if not)
that no hardware token reached the model / cluster / policy feature lists.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

HW_TOKENS = ("device_model", "batt_vendor", "batt_fru", "manufacturer", "serial",
             "uuid", "mtm", "product_uuid")
DEFAULT_GROUP_AXES = ("batt_fru", "batt_vendor", "device_model")


def assert_no_hw_in_classification(*feature_lists: Sequence[str]) -> None:
    """Raise if any hardware identity token appears in a classification feature list."""
    for fl in feature_lists:
        bad = [c for c in fl if any(t in str(c).lower() for t in HW_TOKENS)]
        assert not bad, f"hardware identity leaked into a classification feature list: {bad}"


def _beta_prior(k: np.ndarray, n: np.ndarray) -> tuple:
    """Method-of-moments beta prior (alpha, beta) for the candidate rate across groups."""
    n = n.astype(float); k = k.astype(float)
    if n.sum() <= 0:
        return 1.0, 1.0
    phat = float(k.sum() / n.sum())
    w = n
    r = k / np.maximum(n, 1.0)
    msp = float(np.sum(w * (r - phat) ** 2))
    denom = phat * (1 - phat) * (w.sum() - np.sum(w ** 2) / w.sum()) if w.sum() > 0 else 0.0
    if denom <= 0 or phat <= 0 or phat >= 1:
        kappa = max(float(np.median(n)), 1.0)
    else:
        rho = min(max(msp / denom, 1e-3), 0.99)
        kappa = (1 - rho) / rho
    alpha = max(phat * kappa, 1e-3)
    beta = max((1 - phat) * kappa, 1e-3)
    return alpha, beta


def _bh(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR q-values."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    if m == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * m / (np.arange(m) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(q, 0, 1)
    return out


def enrich_axis(
    snap: pd.DataFrame, user_meta: pd.DataFrame, axis: str,
    candidate_labels: Sequence[str], min_group_n: int = 5,
) -> pd.DataFrame:
    """One enrichment table for one grouping ``axis`` (e.g. batt_fru)."""
    from scipy.stats import beta as beta_dist, fisher_exact

    if axis not in user_meta.columns:
        return pd.DataFrame()
    df = snap[["user_id", "stateful_label"]].merge(
        user_meta[["user_id", axis]].drop_duplicates("user_id"), on="user_id", how="left")
    df["is_cand"] = df["stateful_label"].isin(candidate_labels).astype(int)
    df = df[df[axis].notna()]
    total_cand = int(df["is_cand"].sum())
    total_n = int(len(df))

    grp = df.groupby(axis)["is_cand"].agg(["sum", "count"]).rename(
        columns={"sum": "n_candidate", "count": "n_total"})
    grp = grp[grp["n_total"] >= min_group_n]
    if grp.empty:
        return pd.DataFrame()
    k = grp["n_candidate"].to_numpy(); n = grp["n_total"].to_numpy()
    alpha0, beta0 = _beta_prior(k, n)
    shrunk = (k + alpha0) / (n + alpha0 + beta0)
    ci_low = beta_dist.ppf(0.025, k + alpha0, n - k + beta0)
    ci_high = beta_dist.ppf(0.975, k + alpha0, n - k + beta0)

    pvals = []
    for kk, nn in zip(k, n):
        a, b = kk, nn - kk
        c, d = total_cand - kk, (total_n - nn) - (total_cand - kk)
        try:
            _, p = fisher_exact([[a, b], [c, d]], alternative="greater")
        except Exception:
            p = 1.0
        pvals.append(p)
    qvals = _bh(np.array(pvals))

    out = pd.DataFrame({
        "group_axis": axis, "group_value": grp.index.astype(str),
        "n_total": n, "n_candidate": k,
        "raw_rate": np.round(k / n, 4),
        "shrunk_rate": np.round(shrunk, 4),
        "ci_low": np.round(ci_low, 4), "ci_high": np.round(ci_high, 4),
        "fisher_p": np.round(pvals, 5), "q_value": np.round(qvals, 5),
        "fleet_rate": round(total_cand / max(total_n, 1), 4),
    }).sort_values("shrunk_rate", ascending=False).reset_index(drop=True)
    return out


def enrich_all(
    snap: pd.DataFrame, user_meta: pd.DataFrame,
    candidate_labels: Sequence[str], group_axes: Sequence[str] = DEFAULT_GROUP_AXES,
    min_group_n: int = 5,
) -> pd.DataFrame:
    frames = [enrich_axis(snap, user_meta, ax, candidate_labels, min_group_n)
              for ax in group_axes]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
