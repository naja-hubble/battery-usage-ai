"""Patent evidence E -- missingness / sleep-gap / censor injection stress (IC6).

ADDITIVE. Starting from dense-telemetry users, inject missingness regimes and
measure how four detectors behave relative to the uninjected dense reference:

  * naive            -- censored / gap episodes counted as no_response;
  * binary_gap_gate  -- exclude max-gap>12h episodes; censored still no_response;
  * graded           -- exclude LOW_LARGE_GAP tier; censored still no_response;
  * proposed         -- graded quality tier + censor-aware (censored/unknown are
                        NEVER no_response).  (= production)

The technical effect (IC6): under injected gaps and right-censoring the proposed
method emits far fewer FALSE confirmed no-response episodes (hence fewer false FW
escalations / Gauge hard-resets) than the naive method, while keeping episode
recovery. USER-clustered bootstrap CI on the false-no-response rate.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from .fcc_learning import EPISODE_THRESHOLDS, fcc_step_indicator, extract_high_low_high_episodes

MATCH_TOL_NS = 24 * pc.HOUR_NS          # episode END proximity for matching (robust to boundary drift)
MCAR_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)
GAP_HOURS = (3, 6, 12, 24, 48)
GAP_POSITIONS = ("high_to_low", "around_low", "low_to_high", "after_end", "around_deadline")
DETECTORS = ("naive", "binary_gap_gate", "graded", "proposed")
PRIMARY = pc.PRIMARY_THRESHOLD


def extract_primary_fast(g: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Lean primary-band END-anchored extraction (only the fields the detectors
    need): per episode -> end_ns, max_gap_h, status (responded/no_response/censored).

    Mirrors ``online_episode_detector`` semantics (END-anchored, effective 50 mWh,
    censor-aware) but ~10x faster than building full episode records per replicate."""
    if len(g) < 3:
        return {"end_ns": np.array([], np.int64), "max_gap_h": np.array([]),
                "status": np.array([], dtype=object)}
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ns = int(ts_ns[-1])
    high, low = EPISODE_THRESHOLDS[PRIMARY]
    idx = extract_high_low_high_episodes(rsoc, high, low)
    is_eff, _ = fcc_step_indicator(fcc, pc.EFFECTIVE_STEP_MWH)
    win = pc.PRIMARY_WINDOW_H * pc.HOUR_NS
    ends = []; gaps = []; status = []
    for (s, lo, e) in idx:
        end_ns = int(ts_ns[e])
        seg = ts_ns[s:e + 1]
        mg = float(np.diff(seg).max() / 3.6e12) if seg.size > 1 else 0.0
        complete = (end_ns + win) <= last_ns
        hi = int(np.searchsorted(ts_ns, end_ns + win, side="right"))
        responded = bool(is_eff[e:hi].any()) if hi > e else False
        st = "responded" if responded else ("no_response" if complete else "censored")
        ends.append(end_ns); gaps.append(mg); status.append(st)
    return {"end_ns": np.array(ends, np.int64), "max_gap_h": np.array(gaps),
            "status": np.array(status, dtype=object)}


def _no_response_ends(ext: Dict[str, np.ndarray], detector: str) -> np.ndarray:
    """END timestamps of episodes counted as confirmed no_response under detector."""
    if ext["end_ns"].size == 0:
        return np.array([], np.int64)
    status = ext["status"]; mg = ext["max_gap_h"]
    not_responded = status != "responded"
    no_resp_only = status == "no_response"
    tier_capable = np.array([pc.graded_tier_from_gap(x) in pc.NO_RESPONSE_CAPABLE for x in mg])
    if detector == "naive":
        mask = not_responded
    elif detector == "binary_gap_gate":
        mask = not_responded & (mg <= pc.EPISODE_MAX_GAP_H)
    elif detector == "graded":
        mask = not_responded & tier_capable
    elif detector == "proposed":
        mask = no_resp_only & tier_capable
    else:
        raise ValueError(detector)
    return np.sort(ext["end_ns"][mask])


def _match_count(a: np.ndarray, b: np.ndarray, tol: int = MATCH_TOL_NS) -> int:
    """Number of elements of ``a`` with at least one element of ``b`` within ``tol``."""
    if a.size == 0 or b.size == 0:
        return 0
    b = np.sort(b)
    pos = np.searchsorted(b, a)
    hit = 0
    for k, x in enumerate(a):
        p = pos[k]
        near = False
        if p < b.size and abs(b[p] - x) <= tol:
            near = True
        if p > 0 and abs(b[p - 1] - x) <= tol:
            near = True
        hit += int(near)
    return hit


def _inject_mcar(g: pd.DataFrame, frac: float, rng_: np.random.Generator) -> pd.DataFrame:
    if frac <= 0 or len(g) < 5:
        return g
    keep = rng_.random(len(g)) >= frac
    keep[0] = keep[-1] = True
    return g[keep]


def _inject_contiguous_gap(g: pd.DataFrame, hours: float, position: str,
                           ep_ref: pd.DataFrame, rng_: np.random.Generator) -> pd.DataFrame:
    """Remove all samples within a contiguous ``hours`` window placed relative to a
    randomly chosen reference episode (or randomly if none)."""
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    if ts.size < 5:
        return g
    half = int(hours * pc.HOUR_NS / 2)
    if ep_ref is not None and len(ep_ref):
        r = ep_ref.iloc[rng_.integers(0, len(ep_ref))]
        if position == "high_to_low":
            center = int((r["start_ns"] + r["low_ns"]) / 2)
        elif position == "around_low":
            center = int(r["low_ns"])
        elif position == "low_to_high":
            center = int((r["low_ns"] + r["end_ns"]) / 2)
        elif position == "after_end":
            center = int(r["end_ns"] + 12 * pc.HOUR_NS)
        else:  # around_deadline
            center = int(r["end_ns"] + pc.PRIMARY_WINDOW_H * pc.HOUR_NS)
    else:
        center = int(ts[rng_.integers(0, ts.size)])
    drop = (ts >= center - half) & (ts <= center + half)
    drop[0] = drop[-1] = False
    return g[~drop]


def _inject_truncation(g: pd.DataFrame, hours: float) -> pd.DataFrame:
    """End-of-record truncation -> right censoring of the final episode(s)."""
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    if ts.size < 5:
        return g
    cutoff = ts[-1] - int(hours * pc.HOUR_NS)
    return g[ts <= cutoff]


def _inject_sleepgaps(g: pd.DataFrame, fleet_gaps_h: np.ndarray,
                      rng_: np.random.Generator) -> pd.DataFrame:
    """Sample realistic sleep-gap durations from the fleet and drop samples to
    realise a few gaps of those durations."""
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    if ts.size < 8 or fleet_gaps_h.size == 0:
        return g
    n_gaps = max(1, int(len(g) * 0.02))
    drop = np.zeros(ts.size, dtype=bool)
    for _ in range(n_gaps):
        dur = float(fleet_gaps_h[rng_.integers(0, fleet_gaps_h.size)])
        c = int(ts[rng_.integers(0, ts.size)])
        half = int(dur * pc.HOUR_NS / 2)
        drop |= (ts >= c - half) & (ts <= c + half)
    drop[0] = drop[-1] = False
    return g[~drop]


def _counts(ep: pd.DataFrame) -> Dict[str, int]:
    return {det: int(_classify_no_response(ep, det).sum()) for det in DETECTORS}


def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame, design: pd.Series,
        seed: int = 42, n_users: int = 50, replicates: int = 100) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    # dense user selection: most ok-quality primary episodes + high sample density
    ep_all = episodes[episodes["threshold_name"] == PRIMARY]
    ok_counts = ep_all[ep_all["is_ok"]].groupby("user_id").size().sort_values(ascending=False)
    cols = ["user_id", "timestamp", "remainingCapacityInPercentage", "fullChargeCapacity",
            "cycleCount", "soh_design_pct"]
    ts_all = pc.load_timeseries(cols)
    dens = ts_all.groupby("user_id").size()
    candidates = [u for u in ok_counts.index if dens.get(u, 0) >= 500]
    dense_users = candidates[:n_users]
    by_user = {u: g.sort_values("timestamp").reset_index(drop=True)
               for u, g in ts_all[ts_all["user_id"].isin(dense_users)].groupby("user_id", sort=False)}

    # fleet sleep-gap distribution (hours), capped to plausible sleep range
    samp = ts_all[["user_id", "timestamp"]].copy()
    samp["ts_ns"] = samp["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    fleet_gaps = []
    for _, g in samp.groupby("user_id", sort=False):
        d = np.diff(np.sort(g["ts_ns"].to_numpy())) / pc.HOUR_NS
        fleet_gaps.append(d[(d > 3) & (d < 72)])
    fleet_gaps_h = np.concatenate(fleet_gaps) if fleet_gaps else np.array([6.0])
    fleet_gaps_h = fleet_gaps_h[rng_.integers(0, fleet_gaps_h.size, min(fleet_gaps_h.size, 50000))]

    # reference: production primary-band episode positions (for gap placement) +
    # fast uninjected extraction (the clean baseline); truth no-response = proposed-on-clean.
    ep_prim = episodes[episodes["threshold_name"] == PRIMARY]
    ref_pos: Dict[str, pd.DataFrame] = {u: g for u, g in ep_prim.groupby("user_id", sort=False)}
    ref_ext: Dict[str, dict] = {}
    truth_ends: Dict[str, np.ndarray] = {}
    for u in dense_users:
        ref_ext[u] = extract_primary_fast(by_user[u])
        truth_ends[u] = _no_response_ends(ref_ext[u], "proposed")

    # regimes
    regimes: List[Tuple[str, callable]] = []
    for f in MCAR_FRACS:
        regimes.append((f"mcar_{int(f*100)}pct", lambda g, u, r, f=f: _inject_mcar(g, f, r)))
    for h in GAP_HOURS:
        regimes.append((f"gap_{h}h_around_low",
                        lambda g, u, r, h=h: _inject_contiguous_gap(g, h, "around_low", ref_pos.get(u), r)))
    for pos in GAP_POSITIONS:
        regimes.append((f"gap_24h_{pos}",
                        lambda g, u, r, pos=pos: _inject_contiguous_gap(g, 24, pos, ref_pos.get(u), r)))
    for h in (72, 168):
        regimes.append((f"truncate_{h}h", lambda g, u, r, h=h: _inject_truncation(g, h)))
    regimes.append(("sleepgaps_fleet", lambda g, u, r: _inject_sleepgaps(g, fleet_gaps_h, r)))

    rep_rows: List[dict] = []
    summary_rows: List[dict] = []
    transitions: List[dict] = []

    for regime_name, inject in regimes:
        false_by_user = {det: {u: [] for u in dense_users} for det in DETECTORS}
        recovery_by_rep: List[float] = []
        for b in range(replicates):
            det_false = {det: 0 for det in DETECTORS}
            det_missed = {det: 0 for det in DETECTORS}
            det_count = {det: 0 for det in DETECTORS}
            rec_hits = rec_tot = 0
            for u in dense_users:
                ref_all = ref_ext[u]["end_ns"]
                if ref_all.size == 0:
                    continue
                inj_ext = extract_primary_fast(inject(by_user[u], u, rng_))
                rec_tot += ref_all.size
                rec_hits += _match_count(ref_all, inj_ext["end_ns"])
                for det in DETECTORS:
                    inj_nr = _no_response_ends(inj_ext, det)
                    truth = truth_ends[u]
                    fb = int(inj_nr.size - _match_count(inj_nr, truth))   # artifact no-response
                    mb = int(truth.size - _match_count(truth, inj_nr))    # missed real no-response
                    det_false[det] += fb
                    det_missed[det] += mb
                    det_count[det] += int(inj_nr.size)
                    false_by_user[det][u].append(fb)
            recovery_by_rep.append(rec_hits / rec_tot if rec_tot else 1.0)
            for det in DETECTORS:
                rep_rows.append({"regime": regime_name, "detector": det, "replicate": b,
                                 "false_no_response": det_false[det],
                                 "missed_no_response": det_missed[det],
                                 "n_no_response": det_count[det]})
        rr = pd.DataFrame([r for r in rep_rows if r["regime"] == regime_name])
        for det in DETECTORS:
            sub = rr[rr["detector"] == det]
            vbu = [np.array(false_by_user[det][u]) for u in dense_users if false_by_user[det][u]]
            ci = pc.user_bootstrap_mean(vbu, 400, rng_) if vbu else {"point": 0, "ci_lo": 0, "ci_hi": 0}
            summary_rows.append({
                "regime": regime_name, "detector": det,
                "mean_false_no_response": round(float(sub["false_no_response"].mean()), 3),
                "mean_missed_no_response": round(float(sub["missed_no_response"].mean()), 3),
                "false_per_user_point": round(ci["point"], 4),
                "false_per_user_ci_lo": round(ci["ci_lo"], 4),
                "false_per_user_ci_hi": round(ci["ci_hi"], 4),
                "mean_episode_recovery": round(float(np.mean(recovery_by_rep)), 4),
                "n_replicates": replicates,
            })

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "missingness_stress_summary.csv", index=False)
    pc.save_anon_parquet(pd.DataFrame(rep_rows), out_dir / "missingness_stress_replicates.parquet")

    # label-transition: false FW-escalation users (>=3 false confirmed no-response) naive vs proposed
    for regime_name, _ in regimes:
        sub = summary[summary["regime"] == regime_name]
        naive = float(sub[sub["detector"] == "naive"]["mean_false_no_response"].iloc[0])
        prop = float(sub[sub["detector"] == "proposed"]["mean_false_no_response"].iloc[0])
        transitions.append({"regime": regime_name, "naive_mean_false_no_response": naive,
                            "proposed_mean_false_no_response": prop,
                            "false_no_response_reduction": round(naive - prop, 3)})
    pd.DataFrame(transitions).to_csv(out_dir / "missingness_label_transitions.csv", index=False)

    # aggregate effect: proposed vs naive false-no-response across regimes
    agg = summary.groupby("detector")["mean_false_no_response"].mean()
    naive_false = float(agg.get("naive", np.nan))
    proposed_false = float(agg.get("proposed", np.nan))
    recovery_proposed = float(summary[summary["detector"] == "proposed"]["mean_episode_recovery"].mean())
    benefit = bool(proposed_false < naive_false)
    print(f"[E] mean false confirmed no-response across regimes: naive={naive_false:.2f} "
          f"vs proposed={proposed_false:.2f} (reduction {naive_false-proposed_false:.2f}); "
          f"proposed episode recovery={recovery_proposed:.3f}; "
          f"IC6 censor/gap benefit {'SUPPORTED' if benefit else 'NOT SUPPORTED'} "
          f"({time.time()-t0:.1f}s)")
    return {
        "naive_mean_false_no_response": round(naive_false, 3),
        "proposed_mean_false_no_response": round(proposed_false, 3),
        "false_no_response_reduction": round(naive_false - proposed_false, 3),
        "proposed_episode_recovery": round(recovery_proposed, 4),
        "ic6_benefit_supported": benefit,
        "n_dense_users": len(dense_users),
        "n_regimes": len(regimes),
        "runtime_s": round(time.time() - t0, 2),
    }
