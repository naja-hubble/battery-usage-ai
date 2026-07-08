"""OD2 patent evidence A2 - negative controls, PER MECHANISM (Type A / Type B / union).

The decisive test of the corrected relearn definition: is an effective FCC step
specifically associated with a TRUE Type-A (deep-discharge) or Type-B (charge-side)
learning-opportunity END, rather than with elapsed time / marginal step density?

For each mechanism we build END-anchored qualified (ok, complete-window) anchors from
data/processed/fcc_relearn_od2/phase1/od2_opportunities.parquet and re-measure the pooled
END-anchored effective-response probability at the OD2 PRIMARY window (168h), against the
four cheap negative controls (import-reused verbatim from patent_negative_controls):
circular_step_shift / circular_episode_shift / within_user_time_randomization /
matched_pseudo_episode. Acceptance mirrors A2: the TRUE statistic must sit outside the 95%
null interval (greater) for >=2 controls AND be directionally supported under a user
bootstrap for >=2.

Crux (Phase-1): Type B pooled response @72h (0.27) sits at the OD1 null (~0.25); the
question is whether Type B beats ITS OWN mechanism-specific null at 168h. If it does not,
the charge-side band traversal is not a real stimulus and the invention reduces to Type A.

ADDITIVE / READ-ONLY. No OD1 or v4 file is modified. Runs on 168h; 24/72h kept as columns.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from . import patent_negative_controls as nc

WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
PRIMARY_W = 168
PHASE1_EPISODES = pc.PROC / "fcc_relearn_od2" / "phase1" / "od2_opportunities.parquet"
CODE_VERSION = "patent_evidence_od2.0"


def load_od2_episodes(path: Path = PHASE1_EPISODES) -> pd.DataFrame:
    ep = pd.read_parquet(path)
    for c in ("start_ts", "low_ts", "end_ts"):
        ep[c] = pd.to_datetime(ep[c])
    ep["end_ns"] = ep["end_ts"].astype("datetime64[ns]").astype("int64")
    ep["start_ns"] = ep["start_ts"].astype("datetime64[ns]").astype("int64")
    ep["low_ns"] = ep["low_ts"].astype("datetime64[ns]").astype("int64")
    ep["is_ok"] = ep["episode_quality"].astype(str).eq("ok")
    return ep


def build_anchors_od2(ep: pd.DataFrame, mechanism: str, window_h: int = PRIMARY_W,
                      ok_only: bool = True) -> Dict[str, np.ndarray]:
    if mechanism == "A":
        sub = ep[ep["opportunity_type"] == "A"]
    elif mechanism == "B":
        sub = ep[ep["opportunity_type"] == "B"]
    elif mechanism == "union":
        sub = ep[ep["is_union_primary"]]
    else:
        raise ValueError(mechanism)
    sub = sub.copy()
    if ok_only:
        sub = sub[sub["is_ok"]]
    wc = f"window_{window_h}h_complete"
    sub = sub[sub[wc].fillna(False).astype(bool)]
    return {uid: g["end_ns"].to_numpy(dtype=np.int64)
            for uid, g in sub.groupby("user_id", sort=False)}


def _prep_common(steps: pd.DataFrame):
    """Effective-step arrays per user + per-user observation meta (shared across mechanisms)."""
    eff = steps[steps["is_effective"]]
    sbu = pc.steps_by_user(eff)
    ts_meta = pc.load_timeseries(["user_id", "timestamp",
                                  "remainingCapacityInPercentage", "fullChargeCapacity",
                                  "cycleCount"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    span, first, last_by_user, samples_by_user, df_by_user = {}, {}, {}, {}, {}
    for uid, g in ts_meta.groupby("user_id", sort=False):
        g = g.sort_values("ts_ns")
        arr = g["ts_ns"].to_numpy(dtype=np.int64)
        first[uid] = int(arr[0]); last_by_user[uid] = int(arr[-1])
        span[uid] = int(arr[-1] - arr[0]); samples_by_user[uid] = arr
        df_by_user[uid] = g
    return sbu, span, first, last_by_user, samples_by_user, df_by_user


def _summarise(true_stat, reps, controls_order, boot_lo_168):
    rows = []
    metrics = ["resp_prob_24h", "resp_prob_72h", "resp_prob_168h",
               "confirmed_no_response_episodes", "fw_like_flagged_users"]
    for name in controls_order:
        rr = reps[name]
        for m in metrics:
            null = np.array([float(r[m]) for r in rr if np.isfinite(r.get(m, np.nan))])
            true_v = float(true_stat[m])
            lo = float(np.nanpercentile(null, 2.5)) if null.size else float("nan")
            hi = float(np.nanpercentile(null, 97.5)) if null.size else float("nan")
            mean = float(np.nanmean(null)) if null.size else float("nan")
            p = pc.randomization_pvalue(true_v, null, "greater")
            outside = bool(np.isfinite(lo) and true_v > hi)   # greater-tail separation
            dir_ok = (bool(boot_lo_168 > mean) if m == "resp_prob_168h" and np.isfinite(mean)
                      else None)
            rows.append({
                "control": name, "metric": m, "true_value": round(true_v, 5),
                "control_mean": round(mean, 5), "control_ci_lo": round(lo, 5),
                "control_ci_hi": round(hi, 5),
                "true_minus_control": round(true_v - mean, 5) if np.isfinite(mean) else None,
                "true_over_control": round(true_v / mean, 4) if mean else None,
                "true_outside_null_95ci": outside,
                "true_bootlo_exceeds_control_mean": dir_ok,
                "directionally_supported": bool(outside and dir_ok) if dir_ok is not None else None,
                "randomization_p": round(p, 5), "n_replicates": int(null.size),
            })
    return rows


def run_a2_od2(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
               mechanisms=("A", "B", "union"), n_cheap: int = 300, seed: int = 42):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    sbu, span, first, last_by_user, samples_by_user, df_by_user = _prep_common(steps)

    all_summary: List[dict] = []
    result: Dict[str, dict] = {}
    controls_order = ["circular_step_shift", "circular_episode_shift",
                      "within_user_time_randomization", "matched_pseudo_episode"]

    for mech in mechanisms:
        t0 = time.time()
        anchors = build_anchors_od2(episodes, mech, PRIMARY_W)
        for uid in anchors:
            sbu.setdefault(uid, {"ts_ns": np.array([], np.int64),
                                 "is_effective": np.array([], bool),
                                 "abs_step": np.array([]), "step": np.array([])})
        months = {uid: (a.astype("datetime64[ns]").astype("datetime64[M]")).astype(np.int64)
                  for uid, a in anchors.items()}
        true_stat = nc.statistic(anchors, sbu, last_by_user)
        boot168 = pc.user_bootstrap_ratio(true_stat["_num_168"], true_stat["_den_168"], 1000, rng_)
        boot_lo_168 = float(boot168["ci_lo"])
        n_anchors = int(sum(a.size for a in anchors.values()))
        print(f"[A2-od2:{mech}] n_anchors={n_anchors} users={len(anchors)} "
              f"true resp168={true_stat['resp_prob_168h']:.4f} "
              f"(72h={true_stat['resp_prob_72h']:.4f}) bootlo168={boot_lo_168:.4f}", flush=True)

        pseudo_pool = nc.build_pseudo_pool(anchors, samples_by_user, months)
        cheap = {
            "circular_step_shift": lambda r: nc.control_circular_step_shift(
                anchors, sbu, last_by_user, span, first, r),
            "circular_episode_shift": lambda r: nc.control_circular_episode_shift(
                anchors, sbu, last_by_user, span, first, r),
            "within_user_time_randomization": lambda r: nc.control_within_user_time_randomization(
                anchors, sbu, last_by_user, span, first, last_by_user, r),
            "matched_pseudo_episode": lambda r: nc.control_matched_pseudo(
                anchors, sbu, last_by_user, pseudo_pool, r),
        }
        reps = {name: [] for name in controls_order}
        for name in controls_order:
            tc = time.time()
            for _ in range(n_cheap):
                reps[name].append(cheap[name](rng_))
            print(f"    {name}: null resp168="
                  f"{np.mean([r['resp_prob_168h'] for r in reps[name]]):.4f} "
                  f"({time.time()-tc:.1f}s)", flush=True)
        rows = _summarise(true_stat, reps, controls_order, boot_lo_168)
        for row in rows:
            row["mechanism"] = mech
        all_summary.extend(rows)

        r168 = [r for r in rows if r["metric"] == "resp_prob_168h"]
        n_outside = sum(1 for r in r168 if r["true_outside_null_95ci"])
        n_dir = sum(1 for r in r168 if r["directionally_supported"])
        accept = bool(n_outside >= 2 and n_dir >= 2)
        result[mech] = {
            "mechanism": mech, "n_anchors": n_anchors, "n_users": len(anchors),
            "true_resp_prob_168h": round(float(true_stat["resp_prob_168h"]), 5),
            "true_resp_prob_72h": round(float(true_stat["resp_prob_72h"]), 5),
            "boot_lo_168h": round(boot_lo_168, 5),
            "null_mean_168h_range": [round(min(r["control_mean"] for r in r168), 5),
                                     round(max(r["control_mean"] for r in r168), 5)],
            "n_controls_outside_null": n_outside,
            "n_controls_directionally_supported": n_dir,
            "stimulus_response_supported": accept,
            "runtime_s": round(time.time() - t0, 2),
        }
        print(f"[A2-od2:{mech}] outside_null={n_outside}/4 directional={n_dir}/4 -> "
              f"{'SUPPORTED' if accept else 'NOT SUPPORTED'}", flush=True)

    pd.DataFrame(all_summary).to_csv(out_dir / "negative_control_summary_od2.csv", index=False)
    pd.DataFrame(list(result.values())).to_csv(out_dir / "a2_od2_acceptance_by_mechanism.csv", index=False)
    return result
