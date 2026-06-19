"""Patent evidence B -- response hazard & cumulative incidence.

ADDITIVE. For each qualified END-anchored learning episode, time zero is the
episode end and the event is the first FCC step after the end, estimated
separately for several effective-step thresholds. Episodes are right-censored at
the user's last observed sample or a maximum follow-up horizon, whichever comes
first.

We estimate a Kaplan-Meier survival curve S(t) = P(no response yet by t) and the
cumulative response incidence CIF(t) = 1 - S(t) (single event, censoring only --
no competing risk). Curves are produced overall, by opportunity threshold band
(80/20/80, 85/15/85, 90/10/90), by gap-quality tier, and for true vs matched
pseudo episodes. Confidence intervals are USER-clustered bootstrap (spec 2.10) --
episodes within a user are NOT treated as independent.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc

# effective-step thresholds for the event definition (mWh); "any" = >=1 mWh
THRESHOLDS_MWH: Tuple[float, ...] = (1.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0)
HORIZON_H = 336.0                               # 14-day max follow-up
GRID_H = np.arange(0.0, HORIZON_H + 1.0, 1.0)   # hourly grid
REPORT_TIMES_H = (24.0, 72.0, 168.0)
BANDS = (pc.PRIMARY_THRESHOLD, pc.SECONDARY_THRESHOLD, pc.STRICT_THRESHOLD)


# --------------------------------------------------------------------------- #
# Kaplan-Meier
# --------------------------------------------------------------------------- #
def km_survival(T: np.ndarray, E: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """KM survival on ``grid`` from event/censor times ``T`` and event flags ``E``."""
    if T.size == 0:
        return np.ones_like(grid)
    et = np.sort(np.unique(T[E == 1]))
    if et.size == 0:
        return np.ones_like(grid)
    surv = 1.0
    s_at = []
    for t in et:
        n_risk = int((T >= t).sum())
        d = int(((T == t) & (E == 1)).sum())
        if n_risk > 0:
            surv *= (1.0 - d / n_risk)
        s_at.append(surv)
    s_at = np.array(s_at)
    # step function: S(grid) = last survival at an event time <= grid point
    idx = np.searchsorted(et, grid, side="right") - 1
    out = np.where(idx >= 0, s_at[np.clip(idx, 0, len(s_at) - 1)], 1.0)
    return out


def _te_for_anchor(anchor_ns: np.ndarray, uid_arr: np.ndarray,
                   sbu_thr: Dict[str, np.ndarray], last_ns: Dict[str, int]
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """(T hours, E event-flag) per anchor: first qualifying step after the anchor,
    right-censored at min(last_sample, horizon)."""
    n = anchor_ns.size
    T = np.empty(n); E = np.zeros(n, dtype=int)
    horizon_ns = int(HORIZON_H * pc.HOUR_NS)
    for i in range(n):
        a = int(anchor_ns[i]); uid = uid_arr[i]
        arr = sbu_thr.get(uid)
        censor_ns = min(last_ns.get(uid, a), a + horizon_ns)
        censor_h = max(0.0, (censor_ns - a) / pc.HOUR_NS)
        nxt = None
        if arr is not None and arr.size:
            j = int(np.searchsorted(arr, a, side="left"))
            if j < arr.size:
                nxt = int(arr[j])
        if nxt is not None and nxt <= censor_ns:
            T[i] = max(0.0, (nxt - a) / pc.HOUR_NS); E[i] = 1
        else:
            T[i] = censor_h; E[i] = 0
    return T, E


def _cif_at(T, E, times) -> Dict[float, float]:
    s = km_survival(T, E, np.array(times))
    return {t: float(1.0 - s[k]) for k, t in enumerate(times)}


def _median_event_time(T, E) -> float:
    ev = T[E == 1]
    return float(np.median(ev)) if ev.size else float("nan")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
        design: pd.Series, seed: int = 42, boot: int = 500) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    # last-sample horizon per user
    ts_meta = pc.load_timeseries(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ns = {uid: int(g["ts_ns"].max()) for uid, g in ts_meta.groupby("user_id", sort=False)}

    # per-threshold step arrays
    sbu_thr: Dict[float, Dict[str, np.ndarray]] = {}
    for thr in THRESHOLDS_MWH:
        sub = steps if thr <= 1.0 else steps[steps["abs_step"] >= thr]
        sbu_thr[thr] = {u: g["ts_ns"].to_numpy(dtype=np.int64)
                        for u, g in sub.sort_values("ts_ns").groupby("user_id", sort=False)}

    curves: List[dict] = []
    summary: List[dict] = []

    def _emit_curve(group: str, key: str, T, E):
        surv = km_survival(T, E, GRID_H)
        for k, t in enumerate(GRID_H):
            curves.append({"group": group, "key": key, "time_h": float(t),
                           "survival": float(surv[k]), "cif": float(1.0 - surv[k])})

    def _boot_cif(anchor_ns, uid_arr, sbu, times) -> Dict[str, Dict[str, float]]:
        """User-clustered bootstrap CI of CIF at ``times``."""
        df = pd.DataFrame({"uid": uid_arr, "anc": anchor_ns})
        pos_by_user = {u: np.asarray(idx) for u, idx in df.groupby("uid").indices.items()}
        users = np.array(list(pos_by_user.keys()))
        nU = users.size
        mat = {t: np.empty(boot) for t in times}
        for b in range(boot):
            s = rng_.integers(0, nU, nU)
            pos = np.concatenate([pos_by_user[users[i]] for i in s])
            Tb, Eb = _te_for_anchor(anchor_ns[pos], uid_arr[pos], sbu, last_ns)
            cif = _cif_at(Tb, Eb, times)
            for t in times:
                mat[t][b] = cif[t]
        return {f"cif_{int(t)}h": {"ci_lo": float(np.nanpercentile(mat[t], 2.5)),
                                   "ci_hi": float(np.nanpercentile(mat[t], 97.5))}
                for t in times}

    # ---- overall + by threshold (primary band, ok-quality) ----
    ep_primary = episodes[(episodes["threshold_name"] == pc.PRIMARY_THRESHOLD) &
                          episodes["is_ok"]].copy()
    anc_p = ep_primary["end_ns"].to_numpy(dtype=np.int64)
    uid_p = ep_primary["user_id"].to_numpy()
    for thr in THRESHOLDS_MWH:
        T, E = _te_for_anchor(anc_p, uid_p, sbu_thr[thr], last_ns)
        label = "any_change" if thr <= 1.0 else f"{int(thr)}mWh"
        _emit_curve("threshold", label, T, E)
        cif = _cif_at(T, E, REPORT_TIMES_H)
        bci = _boot_cif(anc_p, uid_p, sbu_thr[thr], REPORT_TIMES_H)
        row = {"group": "threshold", "key": label, "n_episodes": int(anc_p.size),
               "median_response_h": round(_median_event_time(T, E), 2)}
        for t in REPORT_TIMES_H:
            row[f"cif_{int(t)}h"] = round(cif[t], 4)
            row[f"cif_{int(t)}h_lo"] = round(bci[f"cif_{int(t)}h"]["ci_lo"], 4)
            row[f"cif_{int(t)}h_hi"] = round(bci[f"cif_{int(t)}h"]["ci_hi"], 4)
        summary.append(row)

    # ---- adaptive hybrid threshold (per-user max(2*quant, 0.1% design)) ----
    quant = steps.groupby("user_id")["abs_step"].min()       # per-user quantization
    adapt_thr = {}
    for uid in ep_primary["user_id"].unique():
        q = float(quant.get(uid, 10.0)); d = float(design.get(uid, np.nan))
        adapt_thr[uid] = max(2.0 * q, 0.001 * d if np.isfinite(d) else 0.0, 20.0)
    sbu_adapt: Dict[str, np.ndarray] = {}
    for uid, g in steps.sort_values("ts_ns").groupby("user_id", sort=False):
        thr_u = adapt_thr.get(uid, 50.0)
        m = g["abs_step"].to_numpy() >= thr_u
        sbu_adapt[uid] = g["ts_ns"].to_numpy(dtype=np.int64)[m]
    T, E = _te_for_anchor(anc_p, uid_p, sbu_adapt, last_ns)
    _emit_curve("threshold", "adaptive_hybrid", T, E)
    cif = _cif_at(T, E, REPORT_TIMES_H)
    summary.append({"group": "threshold", "key": "adaptive_hybrid", "n_episodes": int(anc_p.size),
                    "median_response_h": round(_median_event_time(T, E), 2),
                    **{f"cif_{int(t)}h": round(cif[t], 4) for t in REPORT_TIMES_H}})

    # ---- by opportunity threshold band (effective 50 mWh event) ----
    for band in BANDS:
        epb = episodes[(episodes["threshold_name"] == band) & episodes["is_ok"]]
        if epb.empty:
            continue
        anc = epb["end_ns"].to_numpy(dtype=np.int64); uid = epb["user_id"].to_numpy()
        T, E = _te_for_anchor(anc, uid, sbu_thr[50.0], last_ns)
        _emit_curve("band", band, T, E)
        cif = _cif_at(T, E, REPORT_TIMES_H)
        summary.append({"group": "band", "key": band, "n_episodes": int(anc.size),
                        "median_response_h": round(_median_event_time(T, E), 2),
                        **{f"cif_{int(t)}h": round(cif[t], 4) for t in REPORT_TIMES_H}})

    # ---- by gap quality tier (primary band, 50 mWh event) ----
    for tier in (pc.TIER_HIGH, pc.TIER_MEDIUM, pc.TIER_LOW):
        ept = episodes[(episodes["threshold_name"] == pc.PRIMARY_THRESHOLD) &
                       (episodes["quality_tier"] == tier)]
        if ept.empty:
            continue
        anc = ept["end_ns"].to_numpy(dtype=np.int64); uid = ept["user_id"].to_numpy()
        T, E = _te_for_anchor(anc, uid, sbu_thr[50.0], last_ns)
        _emit_curve("quality_tier", tier, T, E)
        cif = _cif_at(T, E, REPORT_TIMES_H)
        summary.append({"group": "quality_tier", "key": tier, "n_episodes": int(anc.size),
                        "median_response_h": round(_median_event_time(T, E), 2),
                        **{f"cif_{int(t)}h": round(cif[t], 4) for t in REPORT_TIMES_H}})

    # ---- true vs matched pseudo episodes (50 mWh event) ----
    samples_by_user = {uid: g["ts_ns"].to_numpy(dtype=np.int64)
                       for uid, g in ts_meta.groupby("user_id", sort=False)}
    pseudo_anc = []; pseudo_uid = []
    excl = int(7 * pc.DAY_NS)
    for uid in ep_primary["user_id"].unique():
        smp = samples_by_user.get(uid)
        ends = anc_p[uid_p == uid]
        if smp is None or smp.size == 0:
            continue
        near = np.min(np.abs(smp[:, None] - ends[None, :]), axis=1) <= excl if ends.size else np.zeros(smp.size, bool)
        allowed = smp[~near]
        if allowed.size == 0:
            allowed = smp
        picks = allowed[rng_.integers(0, allowed.size, ends.size)]
        pseudo_anc.extend(picks.tolist()); pseudo_uid.extend([uid] * ends.size)
    pseudo_anc = np.array(pseudo_anc, dtype=np.int64); pseudo_uid = np.array(pseudo_uid)
    Tt, Et = _te_for_anchor(anc_p, uid_p, sbu_thr[50.0], last_ns)
    Tp, Ep = _te_for_anchor(pseudo_anc, pseudo_uid, sbu_thr[50.0], last_ns)
    _emit_curve("true_vs_pseudo", "true", Tt, Et)
    _emit_curve("true_vs_pseudo", "pseudo", Tp, Ep)
    cif_t = _cif_at(Tt, Et, REPORT_TIMES_H); cif_p = _cif_at(Tp, Ep, REPORT_TIMES_H)
    summary.append({"group": "true_vs_pseudo", "key": "true", "n_episodes": int(anc_p.size),
                    "median_response_h": round(_median_event_time(Tt, Et), 2),
                    **{f"cif_{int(t)}h": round(cif_t[t], 4) for t in REPORT_TIMES_H}})
    summary.append({"group": "true_vs_pseudo", "key": "pseudo", "n_episodes": int(pseudo_anc.size),
                    "median_response_h": round(_median_event_time(Tp, Ep), 2),
                    **{f"cif_{int(t)}h": round(cif_p[t], 4) for t in REPORT_TIMES_H}})

    pd.DataFrame(summary).to_csv(out_dir / "response_hazard_summary.csv", index=False)
    pd.DataFrame(curves).to_parquet(out_dir / "response_hazard_curves.parquet", index=False)

    print(f"[B] true 50mWh CIF 72h={cif_t[72.0]:.3f} vs pseudo {cif_p[72.0]:.3f}; "
          f"any-change CIF 72h={[r for r in summary if r['key']=='any_change'][0]['cif_72h']}; "
          f"median resp(50mWh)={_median_event_time(Tt, Et):.1f}h ({time.time()-t0:.1f}s)")
    return {
        "true_cif_72h_50mwh": float(cif_t[72.0]),
        "pseudo_cif_72h_50mwh": float(cif_p[72.0]),
        "true_minus_pseudo_72h": float(cif_t[72.0] - cif_p[72.0]),
        "median_response_h_50mwh": round(_median_event_time(Tt, Et), 2),
        "n_episodes_primary_ok": int(anc_p.size),
        "runtime_s": round(time.time() - t0, 2),
    }
