"""OD2 patent evidence B - response hazard / CIF, PER MECHANISM (Type A / Type B / union).

Time-resolved corroboration of A2. Time zero = opportunity END (full-charge attainment);
event = first effective (>=50 mWh) FCC step after END; right-censored at min(last sample,
336h). We estimate CIF(t)=1-S(t) for each mechanism's TRUE ok-quality ENDs vs matched-pseudo
ends (random per-user times excluded within +/-7d of ANY true UNION end), reporting CIF at
24/72/168h so the SHAPE is visible: the crux is whether Type B's true-vs-pseudo separation
emerges specifically AFTER 72h (justifying the 168h primary window) or is absent (which would
corroborate a Type B negative-control failure).

Reuses km_survival / _te_for_anchor / _cif_at / _median_event_time verbatim from
patent_response_hazard. ADDITIVE / READ-ONLY. Outputs: data/processed/fcc_patent_evidence_od2/.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from . import patent_response_hazard as rh

REPORT_TIMES_H = (24.0, 72.0, 168.0, 336.0)
EVENT_MWH = 50.0


def _mech_ends(ep: pd.DataFrame, mech: str) -> pd.DataFrame:
    if mech == "A":
        sub = ep[(ep["opportunity_type"] == "A") & ep["is_ok"]]
    elif mech == "B":
        sub = ep[(ep["opportunity_type"] == "B") & ep["is_ok"]]
    elif mech == "union":
        sub = ep[ep["is_union_primary"] & ep["is_ok"]]
    else:
        raise ValueError(mech)
    return sub


def run_hazard_od2(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
                   mechanisms=("A", "B", "union"), boot: int = 400, seed: int = 42):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    ts_meta = pc.load_timeseries(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ns = {uid: int(g["ts_ns"].max()) for uid, g in ts_meta.groupby("user_id", sort=False)}
    samples_by_user = {uid: np.sort(g["ts_ns"].to_numpy(dtype=np.int64))
                       for uid, g in ts_meta.groupby("user_id", sort=False)}

    # effective (>=50 mWh) step times per user
    sub = steps[steps["abs_step"] >= EVENT_MWH]
    sbu = {u: g["ts_ns"].to_numpy(dtype=np.int64)
           for u, g in sub.sort_values("ts_ns").groupby("user_id", sort=False)}

    # exclusion set for pseudo = ALL true union ok ENDs per user (avoid pseudo landing on a real END)
    union_ends = _mech_ends(episodes, "union")
    excl_by_user = {uid: np.sort(g["end_ns"].to_numpy(dtype=np.int64))
                    for uid, g in union_ends.groupby("user_id", sort=False)}
    excl_ns = int(7 * pc.DAY_NS)

    curves: List[dict] = []
    summary: List[dict] = []
    result: Dict[str, dict] = {}

    def _boot_cif(anchor_ns, uid_arr, times):
        df = pd.DataFrame({"uid": uid_arr, "anc": anchor_ns})
        pos_by_user = {u: np.asarray(idx) for u, idx in df.groupby("uid").indices.items()}
        users = np.array(list(pos_by_user.keys())); nU = users.size
        mat = {t: np.empty(boot) for t in times}
        for b in range(boot):
            s = rng_.integers(0, nU, nU)
            pos = np.concatenate([pos_by_user[users[i]] for i in s])
            Tb, Eb = rh._te_for_anchor(anchor_ns[pos], uid_arr[pos], sbu, last_ns)
            cif = rh._cif_at(Tb, Eb, times)
            for t in times:
                mat[t][b] = cif[t]
        return {t: (float(np.nanpercentile(mat[t], 2.5)), float(np.nanpercentile(mat[t], 97.5)))
                for t in times}

    for mech in mechanisms:
        tm = time.time()
        epm = _mech_ends(episodes, mech)
        anc = epm["end_ns"].to_numpy(dtype=np.int64)
        uid = epm["user_id"].to_numpy()

        Tt, Et = rh._te_for_anchor(anc, uid, sbu, last_ns)
        cif_t = rh._cif_at(Tt, Et, REPORT_TIMES_H)
        bci = _boot_cif(anc, uid, REPORT_TIMES_H)
        surv = rh.km_survival(Tt, Et, rh.GRID_H)
        for k, t in enumerate(rh.GRID_H):
            curves.append({"mechanism": mech, "key": "true", "time_h": float(t),
                           "cif": float(1.0 - surv[k])})

        # matched pseudo
        p_anc, p_uid = [], []
        for u in np.unique(uid):
            smp = samples_by_user.get(u)
            ends = excl_by_user.get(u, np.array([], np.int64))
            k = int((uid == u).sum())
            if smp is None or smp.size == 0:
                continue
            near = (np.min(np.abs(smp[:, None] - ends[None, :]), axis=1) <= excl_ns
                    if ends.size else np.zeros(smp.size, bool))
            allowed = smp[~near]
            if allowed.size == 0:
                allowed = smp
            p_anc.extend(allowed[rng_.integers(0, allowed.size, k)].tolist())
            p_uid.extend([u] * k)
        p_anc = np.array(p_anc, dtype=np.int64); p_uid = np.array(p_uid)
        Tp, Ep = rh._te_for_anchor(p_anc, p_uid, sbu, last_ns)
        cif_p = rh._cif_at(Tp, Ep, REPORT_TIMES_H)
        survp = rh.km_survival(Tp, Ep, rh.GRID_H)
        for k, t in enumerate(rh.GRID_H):
            curves.append({"mechanism": mech, "key": "pseudo", "time_h": float(t),
                           "cif": float(1.0 - survp[k])})

        row = {"mechanism": mech, "n_true": int(anc.size), "n_pseudo": int(p_anc.size),
               "median_response_h": round(rh._median_event_time(Tt, Et), 2)}
        for t in REPORT_TIMES_H:
            row[f"true_cif_{int(t)}h"] = round(cif_t[t], 4)
            row[f"true_cif_{int(t)}h_lo"] = round(bci[t][0], 4)
            row[f"true_cif_{int(t)}h_hi"] = round(bci[t][1], 4)
            row[f"pseudo_cif_{int(t)}h"] = round(cif_p[t], 4)
            row[f"sep_{int(t)}h"] = round(cif_t[t] - cif_p[t], 4)
        summary.append(row)
        result[mech] = {"mechanism": mech, "n_true": int(anc.size),
                        "true_cif_72h": round(cif_t[72.0], 4), "pseudo_cif_72h": round(cif_p[72.0], 4),
                        "true_cif_168h": round(cif_t[168.0], 4), "pseudo_cif_168h": round(cif_p[168.0], 4),
                        "sep_72h": round(cif_t[72.0] - cif_p[72.0], 4),
                        "sep_168h": round(cif_t[168.0] - cif_p[168.0], 4),
                        "median_response_h": round(rh._median_event_time(Tt, Et), 2)}
        print(f"[B-od2:{mech}] true CIF 72h={cif_t[72.0]:.3f}/168h={cif_t[168.0]:.3f} "
              f"vs pseudo {cif_p[72.0]:.3f}/{cif_p[168.0]:.3f} "
              f"sep72={cif_t[72.0]-cif_p[72.0]:+.3f} sep168={cif_t[168.0]-cif_p[168.0]:+.3f} "
              f"median={rh._median_event_time(Tt, Et):.1f}h ({time.time()-tm:.1f}s)", flush=True)

    pd.DataFrame(summary).to_csv(out_dir / "response_hazard_summary_od2.csv", index=False)
    pd.DataFrame(curves).to_parquet(out_dir / "response_hazard_curves_od2.parquet", index=False)
    print(f"[B-od2] done ({time.time()-t0:.1f}s)", flush=True)
    return result
