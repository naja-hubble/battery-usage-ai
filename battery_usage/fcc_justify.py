"""Threshold-justification & hardware-enrichment analyses for the final FCC classifier.

Every numeric cut in :mod:`battery_usage.fcc_final` is backed here by a data-driven
rationale + a sensitivity sweep, so the thresholds can be defended to a third party as
"this is where the data sits / this is how the conclusion moves when we perturb it",
rather than as bare heuristics (spec section 2). Also computes the effective-FCC-step
sensitivity (spec 1.6) and the post-classification hardware enrichment with
beta-binomial / Empirical-Bayes shrinkage + Fisher/BH (spec section 5).

Hardware identity enters ONLY in :func:`hardware_enrichment_eb` (post-classification,
descriptive). Nothing here feeds the classifier.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import beta as _beta, fisher_exact

try:
    from statsmodels.stats.multitest import multipletests
except Exception:  # pragma: no cover
    multipletests = None

from .fcc_learning import (
    DEFAULT_CONFIG, EPISODE_THRESHOLDS, RESPONSE_WINDOWS_H, FccLearningConfig, process_user, _short,
)
from .fcc_action_classifier import active_reference_mask, active_reference_quantiles, compute_candidate_flags
from .fcc_final import (
    DEFAULT_FINAL_THRESHOLDS, FinalThresholds, LABEL_ORDER, LABEL_FW, LABEL_GAUGE,
    LABEL_WATCH, LABEL_REVIEW, LABEL_NORMAL, classify_frame_final,
)

LABEL_SHORT = {LABEL_REVIEW: "review", LABEL_NORMAL: "normal", LABEL_FW: "fw_check",
               LABEL_GAUGE: "gauge_reset", LABEL_WATCH: "watch"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _label_counts(feat: pd.DataFrame, thr: FinalThresholds) -> Dict[str, int]:
    vc = classify_frame_final(feat, thr)["final_label"].value_counts()
    return {f"n_{LABEL_SHORT[lab]}": int(vc.get(lab, 0)) for lab in LABEL_ORDER}


def _features_only(df: pd.DataFrame, cfg: FccLearningConfig) -> pd.DataFrame:
    rows = [process_user(uid, g, cfg)[0] for uid, g in df.groupby("user_id", sort=False)]
    return pd.DataFrame(rows)


def _wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# --------------------------------------------------------------------------- #
# 2.1 active-reference update-rate quantiles
# --------------------------------------------------------------------------- #
def reference_quantiles_table(feat: pd.DataFrame) -> pd.DataFrame:
    ref = feat[active_reference_mask(feat)]
    rows = []
    for col in ("fcc_changes_per_100_cycles", "fcc_change_rate_per_100d"):
        v = ref[col].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        rows.append({
            "metric": col, "n_active_reference": int(len(ref)),
            "p05": round(float(np.percentile(v, 5)), 4) if v.size else float("nan"),
            "p10": round(float(np.percentile(v, 10)), 4) if v.size else float("nan"),
            "p25": round(float(np.percentile(v, 25)), 4) if v.size else float("nan"),
            "p50": round(float(np.percentile(v, 50)), 4) if v.size else float("nan"),
            "default_used": "p05",
        })
    return pd.DataFrame(rows)


def candidate_pct_sensitivity(feat_raw: pd.DataFrame, q: Dict[str, float],
                              base: FinalThresholds) -> pd.DataFrame:
    rows = []
    for pct in ("p05", "p10"):
        feat = compute_candidate_flags(feat_raw, q, pct)
        row = {"dimension": "candidate_pct", "variant": pct,
               "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum())}
        row.update(_label_counts(feat, replace(base, candidate_pct=pct)))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.2 flat_tail 60/120/180 sensitivity
# --------------------------------------------------------------------------- #
def flat_tail_sensitivity(feat: pd.DataFrame, base: FinalThresholds) -> pd.DataFrame:
    rows = []
    for v in (60, 120, 180):
        thr = replace(base, gauge_hi_flat_tail_days=v, fw_hi_flat_tail_days=max(v, 120),
                      gauge_med_flat_tail_days=min(v, 60))
        row = {"dimension": "flat_tail_days[gauge_hi]", "variant": v,
               "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum())}
        row.update(_label_counts(feat, thr))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.3 response-delay distribution + response-window sensitivity
# --------------------------------------------------------------------------- #
def response_delay_distribution(eps: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Delay (episode end -> first FCC step) for responded complete OK episodes."""
    ok = eps[eps["episode_quality"] == "ok"].copy()
    rows = []
    per = []
    for name in EPISODE_THRESHOLDS:
        s = _short(name)
        sub = ok[(ok["threshold_name"] == name)
                 & (ok["fcc_response_status_72h"].isin(["responded", "no_response"]))]
        # "responded" episodes have a finite delay within observation; use those for the CDF.
        resp = sub[sub["response_delay_h"].notna() & (sub["fcc_changed_168h"] == True)]  # noqa: E712
        d = resp["response_delay_h"].clip(lower=0).to_numpy(dtype=float)
        per.append(pd.DataFrame({"threshold_name": name, "response_delay_h": d}))
        row = {"threshold_name": name, "n_responded_ok": int(d.size)}
        for w in RESPONSE_WINDOWS_H:
            row[f"frac_captured_by_{w}h"] = round(float((d <= w).mean()), 4) if d.size else float("nan")
        rows.append(row)
    return pd.concat(per, ignore_index=True) if per else pd.DataFrame(), pd.DataFrame(rows)


def response_window_sensitivity(feat: pd.DataFrame, base: FinalThresholds) -> pd.DataFrame:
    rows = []
    for w in ("24h", "72h", "168h"):
        row = {"dimension": "response_window", "variant": w,
               "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum())}
        row.update(_label_counts(feat, replace(base, response_window=w)))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.4 learning-band (90/85/80) trade-off
# --------------------------------------------------------------------------- #
def learning_threshold_tradeoff(eps: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name in EPISODE_THRESHOLDS:
        s = _short(name)
        sub = eps[eps["threshold_name"] == name]
        ok = sub[sub["episode_quality"] == "ok"]
        # Response rate over COMPLETE-window OK episodes only (responded / no_response);
        # censored & unknown are excluded — never counted as no_response (spec 1.2).
        judg = ok[ok["fcc_response_status_72h"].isin(["responded", "no_response"])]
        resp = float((judg["fcc_response_status_72h"] == "responded").mean()) if len(judg) else float("nan")
        tail_ok_col = f"tail_n_{s}_ok"
        unresp_col = f"tail_n_unresponded_{s}_complete_window"
        rows.append({
            "threshold_name": name,
            "n_episodes": int(len(sub)),
            "n_ok": int(len(ok)),
            "n_large_gap": int((sub["episode_quality"] == "large_gap").sum()),
            "n_users_with_ok": int(ok["user_id"].nunique()),
            "ok_response_rate_72h": round(resp, 4) if resp == resp else float("nan"),
            "n_users_with_tail_opportunities": int((feat[tail_ok_col] > 0).sum()),
            "n_fw_check_if_used_as_primary": int((feat[unresp_col] >= 3).sum()),
            "n_gauge_reset_if_used_as_no_opportunity_gate": int(
                (feat["fcc_no_or_low_change_candidate"] & (feat[tail_ok_col] == 0)
                 & (feat[f"tail_n_{s}_large_gap"] == 0) & (feat["flat_tail_days"] >= 120)).sum()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.5 no-response probability by k
# --------------------------------------------------------------------------- #
def no_response_k_justification(eps: pd.DataFrame, feat: pd.DataFrame, band: str = "primary_80_20_80",
                                seed: int = 0, n_boot: int = 500, n_tuples: int = 1500) -> pd.DataFrame:
    """P(k complete-OK episodes all show no response) for the reference population.

    Reference = users NOT flagged as no/low-change candidates (healthy/responding),
    restricted to complete-window OK episodes of ``band``. Reports the simple theory line
    (1-p)^k and a USER-LEVEL (cluster) bootstrap: each iteration resamples USERS with
    replacement, pools their episodes, then draws k-episode tuples — so the CI reflects the
    finite number of users (and within-user correlation), not the Monte-Carlo budget. The CI
    is the 2.5/97.5 percentile across bootstrap iterations.
    """
    healthy = set(feat.loc[~feat["fcc_no_or_low_change_candidate"], "user_id"])
    ok = eps[(eps["threshold_name"] == band) & (eps["episode_quality"] == "ok")
             & (eps["fcc_response_status_72h"].isin(["responded", "no_response"]))
             & (eps["user_id"].isin(healthy))].copy()
    ok["responded"] = (ok["fcc_response_status_72h"] == "responded").astype(int)
    p = float(ok["responded"].mean()) if len(ok) else float("nan")
    pools = [grp.to_numpy() for _, grp in ok.groupby("user_id")["responded"]]
    n_users = len(pools)
    rng = np.random.default_rng(seed)
    rows = []
    for k in (1, 2, 3, 4, 5):
        p_theory = (1 - p) ** k if p == p else float("nan")
        if n_users >= 2 and len(ok) >= k:
            ests = np.empty(n_boot)
            for b in range(n_boot):
                idx = rng.integers(0, n_users, n_users)            # resample users w/ replacement
                pooled = np.concatenate([pools[i] for i in idx])
                draws = rng.choice(pooled, size=(n_tuples, k), replace=True)
                ests[b] = (draws.sum(axis=1) == 0).mean()
            p_boot = float(ests.mean()); lo, hi = (float(x) for x in np.percentile(ests, [2.5, 97.5]))
        else:
            p_boot = lo = hi = float("nan")
        rows.append({
            "band": band, "k": k, "n_users": n_users, "n_episodes": int(len(ok)),
            "response_rate_p": round(p, 4) if p == p else float("nan"),
            "p_no_response_theory": round(p_theory, 4) if p_theory == p_theory else float("nan"),
            "p_no_response_bootstrap": round(p_boot, 4) if p_boot == p_boot else float("nan"),
            "boot_ci_lo": round(lo, 4) if lo == lo else float("nan"),
            "boot_ci_hi": round(hi, 4) if hi == hi else float("nan"),
            "false_alarm_proxy_le_5pct": bool(p_theory <= 0.05) if p_theory == p_theory else False,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.6 tail_cycle_delta justification
# --------------------------------------------------------------------------- #
def tail_cycle_justification(feat: pd.DataFrame) -> pd.DataFrame:
    ref = feat[active_reference_mask(feat)]
    # cycles between FCC updates (active ref) ~ cycle_delta / fcc_changes (avg gap proxy)
    cu = ref["cycle_delta"] / ref["fcc_changes"].replace(0, np.nan)
    cu = cu[np.isfinite(cu)]
    cand = feat[feat["fcc_no_or_low_change_candidate"]]
    tc = cand["tail_cycle_delta"]
    tc = tc[np.isfinite(tc)]
    rows = [{
        "metric": "cycles_between_fcc_updates_active_reference",
        "n": int(cu.size),
        "p50": round(float(np.percentile(cu, 50)), 2) if cu.size else float("nan"),
        "p75": round(float(np.percentile(cu, 75)), 2) if cu.size else float("nan"),
        "p90": round(float(np.percentile(cu, 90)), 2) if cu.size else float("nan"),
        "p95": round(float(np.percentile(cu, 95)), 2) if cu.size else float("nan"),
        "note": "FW-high requires tail_cycle_delta >= 30 so a non-update spans well beyond the typical active-reference update gap.",
    }]
    for thr in (20, 30, 50):
        rows.append({
            "metric": f"candidate_tail_cycle_ge_{thr}", "n": int(tc.size),
            "p50": round(float((tc >= thr).mean()), 4) if tc.size else float("nan"),
            "p75": float("nan"), "p90": float("nan"), "p95": float("nan"),
            "note": f"share of no/low-change candidates with tail_cycle_delta >= {thr}",
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.7 AC-bound threshold sensitivity
# --------------------------------------------------------------------------- #
def ac_threshold_sensitivity(feat: pd.DataFrame, base: FinalThresholds) -> pd.DataFrame:
    rows = []
    for v in (0.70, 0.80, 0.90):
        thr = replace(base, gauge_hi_ac_ratio_ge=v, sub_ac_bound_ge=v)
        row = {"dimension": "ac_time_ratio[gauge_hi]", "variant": v,
               "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum())}
        row.update(_label_counts(feat, thr))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 2.8 episode max-gap sensitivity (recomputes tail counts from the episode table)
# --------------------------------------------------------------------------- #
def recompute_tail_counts(eps: pd.DataFrame, feat: pd.DataFrame, gap_h: float) -> pd.DataFrame:
    """Return a copy of ``feat`` with tail ok/large_gap/unresponded counts recomputed under
    a different OK max-gap threshold (derived from the episode table, no re-scan)."""
    m = feat[["user_id", "last_fcc_change_ts"]].copy()
    e = eps.merge(m, on="user_id", how="left")
    e = e[e["start_ts"] >= e["last_fcc_change_ts"]]            # tail episodes
    qualifies = e["episode_quality"].isin(["ok", "large_gap"])
    e = e[qualifies].copy()
    e["new_ok"] = e["max_gap_h_in_episode"] <= gap_h
    out = feat.copy()
    for name in EPISODE_THRESHOLDS:
        s = _short(name)
        sub = e[e["threshold_name"] == name]
        ok_cnt = sub[sub["new_ok"]].groupby("user_id").size()
        lg_cnt = sub[~sub["new_ok"]].groupby("user_id").size()
        unresp = sub[sub["new_ok"] & (sub["fcc_response_status_72h"] == "no_response")].groupby("user_id").size()
        out[f"tail_n_{s}_ok"] = out["user_id"].map(ok_cnt).fillna(0).astype(int)
        out[f"tail_n_{s}_large_gap"] = out["user_id"].map(lg_cnt).fillna(0).astype(int)
        out[f"tail_n_unresponded_{s}_complete_window"] = out["user_id"].map(unresp).fillna(0).astype(int)
        out[f"tail_n_unresponded_{s}_complete_window_72h"] = out[f"tail_n_unresponded_{s}_complete_window"]
    return out


def episode_gap_sensitivity(eps: pd.DataFrame, feat: pd.DataFrame, base: FinalThresholds) -> pd.DataFrame:
    rows = []
    n_users_with_ok_total = eps["user_id"].nunique()
    for gap in (6, 12, 24):
        ok = eps[eps["episode_quality"].isin(["ok", "large_gap"]) & (eps["max_gap_h_in_episode"] <= gap)]
        judg = ok[ok["fcc_response_status_72h"].isin(["responded", "no_response"])]  # complete-window only
        resp = float((judg["fcc_response_status_72h"] == "responded").mean()) if len(judg) else float("nan")
        feat_g = recompute_tail_counts(eps, feat, gap)
        row = {"dimension": "episode_max_gap_h", "variant": gap,
               "n_ok_episodes": int(len(ok)),
               "n_users_with_ok": int(ok["user_id"].nunique()),
               "ok_response_rate_72h": round(resp, 4) if resp == resp else float("nan")}
        row.update(_label_counts(feat_g, base))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 1.6 effective-FCC-step sensitivity (full re-run per definition)
# --------------------------------------------------------------------------- #
EFFECTIVE_STEP_DEFS = {
    "any_change": dict(fcc_change_min_mwh=1.0),
    "abs_ge_50mWh": dict(fcc_change_min_mwh=50.0),
    "abs_ge_100mWh": dict(fcc_change_min_mwh=100.0),
    "abs_ge_0p1pct_design": dict(fcc_change_pct_design=0.001),
    "abs_ge_0p5pct_design": dict(fcc_change_pct_design=0.005),
}


def effective_step_sensitivity(df: pd.DataFrame, base_cfg: FccLearningConfig,
                               base_thr: FinalThresholds) -> pd.DataFrame:
    rows = []
    for name, kw in EFFECTIVE_STEP_DEFS.items():
        cfg = replace(base_cfg, **kw)
        feat = _features_only(df, cfg)
        q = active_reference_quantiles(feat)
        feat = compute_candidate_flags(feat, q, base_thr.candidate_pct)
        row = {
            "step_definition": name,
            "median_fcc_changes": round(float(feat["fcc_changes"].median()), 2),
            "median_fcc_changes_per_100_cycles": round(float(feat["fcc_changes_per_100_cycles"].median()), 3),
            "median_fcc_change_rate_per_100d": round(float(feat["fcc_change_rate_per_100d"].median()), 3),
            "median_flat_tail_days": round(float(feat["flat_tail_days"].median()), 1),
            "n_candidates": int(feat["fcc_no_or_low_change_candidate"].sum()),
        }
        row.update(_label_counts(feat, base_thr))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 5.1 / 5.2 hardware enrichment: Empirical-Bayes shrinkage + Fisher/BH
# --------------------------------------------------------------------------- #
def _eb_prior(x: np.ndarray, n: np.ndarray) -> Tuple[float, float]:
    """Method-of-moments Beta prior (alpha0, beta0) for per-group binomial rates.

    Observed-rate variance = between-group (prior) variance + within-group binomial
    sampling variance. The MoM concentration must invert the PRIOR variance, so the
    expected within-group component E[p(1-p)/n] is subtracted before inverting (else the
    prior variance is overstated, k0 under-estimated and shrinkage too weak).
    """
    if n.sum() <= 0:
        return 25.0, 25.0
    m = float(x.sum() / n.sum())
    p = x / np.maximum(n, 1)
    v_obs = float(np.average((p - m) ** 2, weights=n))
    within = float(np.average(np.maximum(p * (1 - p), 1e-9) / np.maximum(n, 1), weights=n))
    v_prior = v_obs - within
    if v_prior <= 1e-9 or m <= 0 or m >= 1:
        k0 = 50.0
    else:
        k0 = max(1.0, min(500.0, m * (1 - m) / v_prior - 1.0))
    return m * k0, (1 - m) * k0


def hardware_enrichment_eb(labels: pd.DataFrame, group_types=("device_model", "batt_vendor", "batt_fru"),
                           min_n: int = 5) -> pd.DataFrame:
    is_fw = (labels["final_label"] == LABEL_FW).astype(int)
    is_gauge = (labels["final_label"] == LABEL_GAUGE).astype(int)
    N = len(labels)
    X_fw, X_gauge = int(is_fw.sum()), int(is_gauge.sum())
    out_rows: List[dict] = []
    for gt in group_types:
        v = labels[gt].fillna("(none)")
        agg = pd.DataFrame({"value": v, "fw": is_fw.values, "gauge": is_gauge.values}) \
            .groupby("value").agg(n_total=("fw", "size"), n_fw_check=("fw", "sum"),
                                  n_gauge_reset=("gauge", "sum")).reset_index()
        n = agg["n_total"].to_numpy(dtype=float)
        a_fw, b_fw = _eb_prior(agg["n_fw_check"].to_numpy(dtype=float), n)
        a_g, b_g = _eb_prior(agg["n_gauge_reset"].to_numpy(dtype=float), n)
        # Fisher exact (FW vs rest) per group + BH FDR over groups with n>=min_n.
        pvals, idx = [], []
        for i, r in agg.iterrows():
            x, ni = int(r["n_fw_check"]), int(r["n_total"])
            if ni >= min_n:
                table = [[x, ni - x], [X_fw - x, (N - ni) - (X_fw - x)]]
                _, pv = fisher_exact(table, alternative="greater")
                pvals.append(pv); idx.append(i)
        qmap = {}
        if pvals and multipletests is not None:
            q = multipletests(pvals, method="fdr_bh")[1]
            qmap = {i: qq for i, qq in zip(idx, q)}
        pmap = {i: pv for i, pv in zip(idx, pvals)}
        for i, r in agg.iterrows():
            x, ni, xg = int(r["n_fw_check"]), int(r["n_total"]), int(r["n_gauge_reset"])
            af, bf = a_fw + x, b_fw + (ni - x)
            ag, bg = a_g + xg, b_g + (ni - xg)
            out_rows.append({
                "group_type": gt, "value": r["value"], "n_total": ni,
                "n_fw_check": x, "raw_fw_check_rate": round(x / ni, 4),
                "shrunk_fw_check_rate": round(af / (af + bf), 4),
                "fw_check_ci_low": round(float(_beta.ppf(0.025, af, bf)), 4),
                "fw_check_ci_high": round(float(_beta.ppf(0.975, af, bf)), 4),
                "n_gauge_reset": xg, "raw_gauge_reset_rate": round(xg / ni, 4),
                "shrunk_gauge_reset_rate": round(ag / (ag + bg), 4),
                "gauge_reset_ci_low": round(float(_beta.ppf(0.025, ag, bg)), 4),
                "gauge_reset_ci_high": round(float(_beta.ppf(0.975, ag, bg)), 4),
                "fw_fisher_p": round(float(pmap[i]), 5) if i in pmap else float("nan"),
                "fw_fisher_q_bh": round(float(qmap[i]), 5) if i in qmap else float("nan"),
            })
    out = pd.DataFrame(out_rows)
    out["rank_fw_check_shrunk"] = out.groupby("group_type")["shrunk_fw_check_rate"] \
        .rank(ascending=False, method="min").astype(int)
    out["rank_gauge_reset_shrunk"] = out.groupby("group_type")["shrunk_gauge_reset_rate"] \
        .rank(ascending=False, method="min").astype(int)
    return out.sort_values(["group_type", "shrunk_fw_check_rate"], ascending=[True, False]).reset_index(drop=True)
