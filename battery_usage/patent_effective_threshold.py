"""Patent evidence C3 -- data-driven effective-step threshold.

ADDITIVE. Characterises the FCC step-magnitude distribution and asks whether a
small step is physically/temporally consistent with micro-wobble rather than
meaningful re-learning, then evaluates the technical effect of every candidate
effective-step threshold. Output distinguishes (spec 8.5):

  * narrow fallback   : fixed 50 mWh;
  * medium scope      : a threshold above the gauge quantization / noise band;
  * broad preferred   : adaptive max(k*quantization, alpha*DesignCapacity, noise pct).

Sub-threshold steps are NOT called "noise" unless the persistence/reversal
analysis supports it (spec 8.2); otherwise "micro-step".
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc

FIXED_MWH = (10, 20, 30, 40, 50, 75, 100, 150)
PCT_DESIGN = (0.05, 0.1, 0.2, 0.5)
K_QUANT = tuple(range(2, 11))
PERSIST_H = (6, 24, 72)
DESIGN_BANDS = [(0, 45000), (45000, 60000), (60000, 1e9)]


def _gmm_2(logx: np.ndarray, seed: int):
    """2-component 1-D Gaussian mixture on log-magnitude (micro vs effective)."""
    try:
        from sklearn.mixture import GaussianMixture
    except Exception:
        return None
    gm = GaussianMixture(n_components=2, random_state=seed, n_init=3)
    gm.fit(logx.reshape(-1, 1))
    order = np.argsort(gm.means_.ravel())
    means = gm.means_.ravel()[order]
    sds = np.sqrt(gm.covariances_.ravel())[order]
    weights = gm.weights_.ravel()[order]
    # valley = crossing point of the two weighted component densities between the means
    grid = np.linspace(means[0], means[1], 2000)
    from scipy.stats import norm
    d0 = weights[0] * norm.pdf(grid, means[0], sds[0])
    d1 = weights[1] * norm.pdf(grid, means[1], sds[1])
    diff = d0 - d1
    sign = np.sign(diff)
    cross = np.where(np.diff(sign) != 0)[0]
    valley_log = float(grid[cross[0]]) if cross.size else float((means[0] + means[1]) / 2)
    return {"means_log10": means.tolist(), "sds_log10": sds.tolist(),
            "weights": weights.tolist(), "valley_log10": valley_log,
            "valley_mwh": float(10 ** valley_log),
            "micro_mode_mwh": float(10 ** means[0]),
            "effective_mode_mwh": float(10 ** means[1]),
            "bic": float(gm.bic(logx.reshape(-1, 1)))}


def _valley_histogram(logx: np.ndarray) -> float:
    """Density valley between the two modes via a smoothed histogram (model-free)."""
    hist, edges = np.histogram(logx, bins=60)
    centers = 0.5 * (edges[:-1] + edges[1:])
    # smooth
    k = np.ones(5) / 5
    sm = np.convolve(hist, k, mode="same")
    # find the two largest peaks, then the min between them
    if sm.size < 5:
        return float(10 ** np.median(logx))
    peak1 = int(np.argmax(sm))
    # search opposite side for a second peak
    left = sm[:peak1]; right = sm[peak1 + 1:]
    if right.size and right.max() >= (left.max() if left.size else 0):
        peak2 = peak1 + 1 + int(np.argmax(right))
    else:
        peak2 = int(np.argmax(left)) if left.size else peak1
    a, b = sorted((peak1, peak2))
    if b - a < 2:
        return float(10 ** np.median(logx))
    valley = a + int(np.argmin(sm[a:b + 1]))
    return float(10 ** centers[valley])


def persistence_reversal(steps: pd.DataFrame, ep_ends_by_user: Dict[str, np.ndarray]
                         ) -> pd.DataFrame:
    """Per-step persistence / reversal / opportunity-association, split by
    micro (<50 mWh) vs effective (>=50 mWh)."""
    rows: List[dict] = []
    win72 = 72 * pc.HOUR_NS
    for uid, g in steps.sort_values("ts_ns").groupby("user_id", sort=False):
        ts = g["ts_ns"].to_numpy(dtype=np.int64)
        sgn = np.sign(g["step"].to_numpy(dtype=float))
        mag = g["abs_step"].to_numpy(dtype=float)
        n = ts.size
        ends = ep_ends_by_user.get(uid)
        for i in range(n):
            nxt_dt = (ts[i + 1] - ts[i]) if i + 1 < n else np.inf
            reversed_next = bool(i + 1 < n and sgn[i + 1] == -sgn[i])
            # full reversal: next step returns ~to previous value (|next mag - this mag| small)
            full_rev = bool(reversed_next and abs(mag[i + 1] - mag[i]) <= 0.5 * mag[i])
            opp_assoc = False
            if ends is not None and ends.size:
                j = int(np.searchsorted(ends, ts[i], side="right")) - 1
                if j >= 0 and (ts[i] - ends[j]) <= win72:
                    opp_assoc = True
            row = {"is_micro": bool(mag[i] < pc.EFFECTIVE_STEP_MWH), "abs_step": float(mag[i])}
            for h in PERSIST_H:
                row[f"persist_{h}h"] = bool(nxt_dt >= h * pc.HOUR_NS)
                row[f"reversed_{h}h"] = bool(reversed_next and nxt_dt <= h * pc.HOUR_NS)
                row[f"full_reversed_{h}h"] = bool(full_rev and nxt_dt <= h * pc.HOUR_NS)
            row["opportunity_associated_72h"] = opp_assoc
            rows.append(row)
    df = pd.DataFrame(rows)
    agg_rows = []
    for label, sub in [("micro", df[df["is_micro"]]), ("effective", df[~df["is_micro"]])]:
        if sub.empty:
            continue
        rec = {"step_class": label, "n_steps": int(len(sub))}
        for h in PERSIST_H:
            rec[f"frac_persist_{h}h"] = round(float(sub[f"persist_{h}h"].mean()), 4)
            rec[f"frac_reversed_{h}h"] = round(float(sub[f"reversed_{h}h"].mean()), 4)
            rec[f"frac_full_reversed_{h}h"] = round(float(sub[f"full_reversed_{h}h"].mean()), 4)
        rec["frac_opportunity_associated_72h"] = round(float(sub["opportunity_associated_72h"].mean()), 4)
        agg_rows.append(rec)
    return pd.DataFrame(agg_rows)


def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
        design: pd.Series, seed: int = 42, boot: int = 500) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    abs_step = steps["abs_step"].to_numpy(dtype=float)
    abs_step = abs_step[abs_step > 0]
    logx = np.log10(abs_step)
    quant_global = float(abs_step.min())
    quant_by_user = steps.groupby("user_id")["abs_step"].min()
    noise_pct_by_user = steps.groupby("user_id")["abs_step"].quantile(0.5)   # per-user median as noise scale

    # ---- distribution model selection ----
    gmm = _gmm_2(logx, seed)
    valley_hist = _valley_histogram(logx)
    model_rows = [
        {"method": "quantization_unit", "threshold_mwh": round(quant_global, 2),
         "note": "smallest observed positive |step| (integer gauge unit)"},
        {"method": "empirical_p50", "threshold_mwh": round(float(np.percentile(abs_step, 50)), 2),
         "note": "median step magnitude"},
        {"method": "empirical_p75", "threshold_mwh": round(float(np.percentile(abs_step, 75)), 2),
         "note": "75th percentile"},
        {"method": "valley_histogram", "threshold_mwh": round(valley_hist, 2),
         "note": "density valley between micro and macro modes (model-free)"},
    ]
    if gmm:
        model_rows.append({"method": "gmm2_valley", "threshold_mwh": round(gmm["valley_mwh"], 2),
                           "note": f"2-comp GMM valley; modes {gmm['micro_mode_mwh']:.0f}/"
                                   f"{gmm['effective_mode_mwh']:.0f} mWh; BIC={gmm['bic']:.0f}"})
    pd.DataFrame(model_rows).to_csv(out_dir / "effective_threshold_model_selection.csv", index=False)

    # ---- bootstrap CI of the data-driven threshold by USER (GMM valley is the
    # meaningful micro/effective separator; histogram valley just tracks the
    # quantization spike and is reported for transparency) ----
    users = steps["user_id"].unique()
    abs_all = steps["abs_step"].to_numpy()
    pos_by_user = {u: np.asarray(idx) for u, idx in steps.reset_index(drop=True).groupby("user_id").indices.items()}
    boot_hist = np.empty(boot); boot_gmm = np.full(boot, np.nan)
    for b in range(boot):
        s = rng_.integers(0, users.size, users.size)
        pos = np.concatenate([pos_by_user[users[i]] for i in s])
        a = abs_all[pos]; a = a[a > 0]
        lg = np.log10(a)
        boot_hist[b] = _valley_histogram(lg)
        gm = _gmm_2(lg, seed + b)
        if gm:
            boot_gmm[b] = gm["valley_mwh"]
    bdf = [{"method": "valley_histogram", "point_mwh": round(valley_hist, 2),
            "ci_lo_mwh": round(float(np.percentile(boot_hist, 2.5)), 2),
            "ci_hi_mwh": round(float(np.percentile(boot_hist, 97.5)), 2)}]
    if gmm:
        bdf.append({"method": "gmm2_valley", "point_mwh": round(gmm["valley_mwh"], 2),
                    "ci_lo_mwh": round(float(np.nanpercentile(boot_gmm, 2.5)), 2),
                    "ci_hi_mwh": round(float(np.nanpercentile(boot_gmm, 97.5)), 2)})
    pd.DataFrame(bdf).to_csv(out_dir / "effective_threshold_bootstrap.csv", index=False)

    # ---- persistence / reversal (micro-step vs effective) ----
    ep = episodes[episodes["threshold_name"] == pc.PRIMARY_THRESHOLD]
    ends_by_user = {uid: np.sort(g["end_ns"].to_numpy(dtype=np.int64))
                    for uid, g in ep.groupby("user_id", sort=False)}
    pr = persistence_reversal(steps, ends_by_user)
    pr.to_csv(out_dir / "effective_threshold_persistence_reversal.csv", index=False)

    # ---- technical-effect curves over candidate thresholds ----
    grp_max = steps.groupby("user_id")["abs_step"].max()
    n_users = int(steps["user_id"].nunique())
    design_band_label = {}
    for uid in grp_max.index:
        d = float(design.get(uid, np.nan))
        for k, (lo, hi) in enumerate(DESIGN_BANDS):
            if np.isfinite(d) and lo <= d < hi:
                design_band_label[uid] = k
                break
        else:
            design_band_label[uid] = -1

    def _curve_row(kind, thr_value, thr_by_user_or_scalar):
        if np.isscalar(thr_by_user_or_scalar):
            eff_mask = steps["abs_step"].to_numpy() >= thr_by_user_or_scalar
            users_no_eff = int((grp_max < thr_by_user_or_scalar).sum())
            # by design band
            sens = {}
            for k in range(len(DESIGN_BANDS)):
                band_users = [u for u in grp_max.index if design_band_label.get(u) == k]
                if band_users:
                    sens[f"frac_no_eff_band{k}"] = round(
                        float(np.mean([grp_max[u] < thr_by_user_or_scalar for u in band_users])), 4)
            return {"threshold_kind": kind, "threshold": thr_value,
                    "frac_steps_micro": round(float((~eff_mask).mean()), 4),
                    "n_effective_steps": int(eff_mask.sum()),
                    "users_no_effective_step": users_no_eff,
                    "frac_users_no_effective_step": round(users_no_eff / n_users, 4), **sens}
        else:
            thr_u = steps["user_id"].map(thr_by_user_or_scalar).to_numpy()
            eff_mask = steps["abs_step"].to_numpy() >= thr_u
            no_eff = sum(1 for u in grp_max.index if grp_max[u] < thr_by_user_or_scalar.get(u, np.inf))
            return {"threshold_kind": kind, "threshold": thr_value,
                    "frac_steps_micro": round(float((~eff_mask).mean()), 4),
                    "n_effective_steps": int(eff_mask.sum()),
                    "users_no_effective_step": no_eff,
                    "frac_users_no_effective_step": round(no_eff / n_users, 4)}

    rows: List[dict] = []
    for t in FIXED_MWH:
        rows.append(_curve_row("fixed_mwh", float(t), float(t)))
    for p in PCT_DESIGN:
        thr_u = {u: float(design.get(u, np.nan)) * p / 100.0 for u in grp_max.index}
        thr_u = {u: v for u, v in thr_u.items() if np.isfinite(v)}
        rows.append(_curve_row("pct_design", float(p), thr_u))
    for k in K_QUANT:
        thr_u = {u: float(quant_by_user.get(u, 10.0)) * k for u in grp_max.index}
        rows.append(_curve_row("k_quant", float(k), thr_u))
    # per-user noise percentile
    thr_u = {u: float(noise_pct_by_user.get(u, 10.0)) for u in grp_max.index}
    rows.append(_curve_row("user_noise_p50", 0.5, thr_u))
    # hybrid broad
    thr_u = {u: max(2.0 * float(quant_by_user.get(u, 10.0)),
                    0.001 * float(design.get(u, np.nan)) if np.isfinite(design.get(u, np.nan)) else 0.0,
                    float(noise_pct_by_user.get(u, 10.0))) for u in grp_max.index}
    rows.append(_curve_row("hybrid_adaptive", 0.0, thr_u))
    sens = pd.DataFrame(rows)
    sens.to_csv(out_dir / "effective_threshold_label_sensitivity.csv", index=False)

    # ---- machine-readable scope recommendation (spec 8.5) ----
    micro_frac_50 = float((abs_step < 50).mean())
    rec = {
        "narrow_fallback": {"definition": "fixed_50mWh", "threshold_mwh": 50.0,
                            "evidence": f"micro(<50mWh) fraction={micro_frac_50:.3f}; "
                                        f"label-Jaccard stable plateau near 50 mWh (see C2 sweep)"},
        "medium_scope": {"definition": "above_quantization_and_noise_band",
                         "threshold_mwh_floor": round(max(2 * quant_global,
                                                          float(np.percentile(abs_step, 50))), 2),
                         "evidence": f"quantization={quant_global:.0f}mWh; median noise scale="
                                     f"{float(np.percentile(abs_step,50)):.0f}mWh; "
                                     f"valley={valley_hist:.0f}mWh (hist)"},
        "broad_preferred": {"definition": "max(k*quantization, alpha*DesignCapacity, noise_percentile)",
                            "k": 2, "alpha_pct_design": 0.1, "noise_percentile": 50,
                            "evidence": "adaptive to per-device quantization, design capacity and "
                                        "observed noise; bootstrap valley CI in effective_threshold_bootstrap.csv"},
        "data_driven_valley_mwh": round(valley_hist, 2),
        "gmm_valley_mwh": round(gmm["valley_mwh"], 2) if gmm else None,
    }
    (out_dir / "effective_threshold_recommendation.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    micro_pr = pr[pr["step_class"] == "micro"]
    eff_pr = pr[pr["step_class"] == "effective"]
    print(f"[C3] quantization={quant_global:.0f}mWh valley(hist)={valley_hist:.0f}mWh "
          f"gmm_valley={gmm['valley_mwh']:.0f}mWh; micro frac<50={micro_frac_50:.3f}; "
          f"micro reversal24h={float(micro_pr['frac_reversed_24h'].iloc[0]) if not micro_pr.empty else float('nan'):.3f} "
          f"vs eff {float(eff_pr['frac_reversed_24h'].iloc[0]) if not eff_pr.empty else float('nan'):.3f}; "
          f"micro opp-assoc={float(micro_pr['frac_opportunity_associated_72h'].iloc[0]) if not micro_pr.empty else float('nan'):.3f} "
          f"vs eff {float(eff_pr['frac_opportunity_associated_72h'].iloc[0]) if not eff_pr.empty else float('nan'):.3f} "
          f"({time.time()-t0:.1f}s)")
    return {
        "quantization_unit_mwh": quant_global,
        "valley_histogram_mwh": round(valley_hist, 2),
        "gmm_valley_mwh": round(gmm["valley_mwh"], 2) if gmm else None,
        "gmm_micro_mode_mwh": round(gmm["micro_mode_mwh"], 2) if gmm else None,
        "gmm_effective_mode_mwh": round(gmm["effective_mode_mwh"], 2) if gmm else None,
        "frac_micro_lt_50mwh": round(micro_frac_50, 4),
        "micro_reversal_24h": float(micro_pr["frac_reversed_24h"].iloc[0]) if not micro_pr.empty else None,
        "effective_reversal_24h": float(eff_pr["frac_reversed_24h"].iloc[0]) if not eff_pr.empty else None,
        "micro_opportunity_assoc_72h": float(micro_pr["frac_opportunity_associated_72h"].iloc[0]) if not micro_pr.empty else None,
        "effective_opportunity_assoc_72h": float(eff_pr["frac_opportunity_associated_72h"].iloc[0]) if not eff_pr.empty else None,
        "runtime_s": round(time.time() - t0, 2),
    }
