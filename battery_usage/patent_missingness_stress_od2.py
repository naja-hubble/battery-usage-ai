"""OD2 patent evidence E -- missingness / sleep-gap / censor stress, PER MECHANISM.

ADDITIVE / READ-ONLY fork of ``patent_missingness_stress`` (OD1 E) for the corrected
FCC-relearn opportunity definition (OD2). The technical effect being demonstrated is
unchanged (IC6): under injected gaps and right-censoring the *proposed* detector emits
far fewer FALSE confirmed no-response episodes -- and hence fewer false FW escalations /
Gauge hard-resets -- than the naive detector, while keeping episode recovery. What
changes vs OD1 E:

  * the opportunity ENDs are OD2 relearn ENDs (full-charge attainment), extracted with
    the canonical Type-A / Type-B extractors from ``relearn_od2`` rather than the OD1
    discharge band. Type B REQUIRES ``chargeStatus`` in the timeseries columns;
  * the response audit uses the OD2 PRIMARY window = 168h (not 72h), so end-of-record
    truncation is extended to (168h, 336h) -- a 168h window needs >=7d of look-ahead;
  * the whole stress is run per mechanism (A / B / union) so per-mechanism false counts
    are reported; ``union`` is the headline comparable to the OD1 baseline.

Injection regimes, the four detectors, the clustered bootstrap and the matching logic
are reused verbatim by import from OD1 E; only the (mechanism-coupled) episode
extraction and the 168h-deadline contiguous-gap placement are forked here.

Truth (per user, per mechanism): the ``proposed`` detector on CLEAN (uninjected) data at
the 168h window. A false confirmed no-response is an injected no-response END that has no
clean-truth no-response END within +/-24h; censored / unknown are NEVER counted as
no-response (that is the whole point of ``proposed``).

Technical evidence for patent review -- NOT a legal opinion.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from .fcc_learning import fcc_step_indicator
from .relearn_od2 import (
    DEFAULT_OD2_CONFIG, Od2Config, TypeADef, TypeBDef,
    extract_typeA_episodes, extract_typeB_episodes,
)
# Reuse the anchor/ledger-agnostic OD1 E helpers verbatim (never edited).
from .patent_missingness_stress import (
    DETECTORS,
    _no_response_ends, _match_count,
    _inject_mcar, _inject_truncation, _inject_sleepgaps,
)

EFFECTIVE_STEP_MWH = pc.EFFECTIVE_STEP_MWH        # 50 mWh (abs_ge_50mWh)
PRIMARY_W_H = 168                                  # OD2 PRIMARY window (hours)
HOUR_NS = pc.HOUR_NS

MCAR_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)
GAP_HOURS = (3, 6, 12, 24, 48)
GAP_POSITIONS = ("high_to_low", "around_low", "low_to_high", "after_end", "around_deadline")
TRUNCATE_HOURS = (168, 336)                        # EXTENDED for the 168h window
MECHANISMS = ("A", "B", "union")

_EMPTY = {"end_ns": np.array([], np.int64), "start_ns": np.array([], np.int64),
          "low_ns": np.array([], np.int64), "max_gap_h": np.array([]),
          "status": np.array([], dtype=object)}


# --------------------------------------------------------------------------- #
# Mechanism-coupled OD2 END extraction (the forked part)
# --------------------------------------------------------------------------- #
def extract_union_od2_fast(g: pd.DataFrame, mechanism: str,
                           cfg: Od2Config = DEFAULT_OD2_CONFIG) -> Dict[str, np.ndarray]:
    """Lean OD2 relearn-END extraction for one detector replicate.

    Returns per END -> start_ns / low_ns / end_ns / max_gap_h (over the episode span)
    / status (responded / no_response / censored). Mirrors the production OD2
    END-anchored, censor-aware response semantics (effective >=50 mWh step within
    [END, END+168h]) but is ~10x faster than building full episode records.

    ``mechanism`` in {"A","B","union"}. For "union" the Type-A and Type-B triples are
    de-duplicated on the END position (Type A wins), exactly like
    ``relearn_od2.add_union_flags``.
    """
    if len(g) < 3:
        return dict(_EMPTY)
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    chg = (g["chargeStatus"].to_numpy(dtype=float) if "chargeStatus" in g
           else np.full(len(g), np.nan))
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ns = int(ts_ns[-1])

    triples: List[Tuple[int, int, int, str]] = []
    if mechanism in ("A", "union"):
        triples += [(s, lo, e, "A") for (s, lo, e) in extract_typeA_episodes(rsoc, cfg.type_a)]
    if mechanism in ("B", "union"):
        triples += [(s, lo, e, "B") for (s, lo, e) in extract_typeB_episodes(rsoc, chg, cfg.type_b)]
    if not triples:
        return dict(_EMPTY)
    if mechanism == "union":
        best: Dict[int, Tuple[int, int, int, str]] = {}
        for (s, lo, e, m) in triples:
            cur = best.get(e)
            if cur is None or (cur[3] == "B" and m == "A"):
                best[e] = (s, lo, e, m)
        triples = sorted(best.values(), key=lambda x: x[2])

    is_eff, _ = fcc_step_indicator(fcc, EFFECTIVE_STEP_MWH)
    win = PRIMARY_W_H * HOUR_NS
    starts, lows, ends, gaps, status = [], [], [], [], []
    for (s, lo, e, _m) in triples:
        end_ns = int(ts_ns[e])
        seg = ts_ns[s:e + 1]
        mg = float(np.diff(seg).max() / 3.6e12) if seg.size > 1 else 0.0
        complete = (end_ns + win) <= last_ns
        hi = int(np.searchsorted(ts_ns, end_ns + win, side="right"))
        responded = bool(is_eff[e:hi].any()) if hi > e else False
        st = "responded" if responded else ("no_response" if complete else "censored")
        starts.append(int(ts_ns[s])); lows.append(int(ts_ns[lo])); ends.append(end_ns)
        gaps.append(mg); status.append(st)
    return {"end_ns": np.array(ends, np.int64), "start_ns": np.array(starts, np.int64),
            "low_ns": np.array(lows, np.int64), "max_gap_h": np.array(gaps),
            "status": np.array(status, dtype=object)}


def _inject_contiguous_gap_od2(g: pd.DataFrame, hours: float, position: str,
                               ep_ref: pd.DataFrame, rng_: np.random.Generator) -> pd.DataFrame:
    """Contiguous ``hours`` blackout placed relative to a random reference END.

    Forked from OD1 E only to move the ``around_deadline`` centre to the OD2 168h
    deadline (END + 168h) instead of 72h; every other placement is identical.
    """
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    if ts.size < 5:
        return g
    half = int(hours * HOUR_NS / 2)
    if ep_ref is not None and len(ep_ref):
        r = ep_ref.iloc[rng_.integers(0, len(ep_ref))]
        if position == "high_to_low":
            center = int((r["start_ns"] + r["low_ns"]) / 2)
        elif position == "around_low":
            center = int(r["low_ns"])
        elif position == "low_to_high":
            center = int((r["low_ns"] + r["end_ns"]) / 2)
        elif position == "after_end":
            center = int(r["end_ns"] + 12 * HOUR_NS)
        else:  # around_deadline (168h for OD2)
            center = int(r["end_ns"] + PRIMARY_W_H * HOUR_NS)
    else:
        center = int(ts[rng_.integers(0, ts.size)])
    drop = (ts >= center - half) & (ts <= center + half)
    drop[0] = drop[-1] = False
    return g[~drop]


# --------------------------------------------------------------------------- #
# Driver (per mechanism)
# --------------------------------------------------------------------------- #
def run_od2(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
            design: pd.Series = None, seed: int = 42, n_users: int = 25,
            replicates: int = 40, mechanisms: Tuple[str, ...] = MECHANISMS,
            min_density: int = 500) -> Dict[str, object]:
    """Run the missingness stress for each mechanism and write one combined summary.

    ``steps`` / ``design`` are accepted for signature parity with the other OD2
    pillars but are unused here (E re-extracts ENDs from the raw timeseries)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    # --- dense-user selection (shared across mechanisms): most union-ok OD2 ENDs
    #     among users with dense telemetry. ---
    ep_union_ok = episodes[episodes.get("is_union_primary", False) & episodes["is_ok"]]
    ok_counts = ep_union_ok.groupby("user_id").size().sort_values(ascending=False)
    cols = ["user_id", "timestamp", "remainingCapacityInPercentage",
            "fullChargeCapacity", "chargeStatus"]
    ts_all = pc.load_timeseries(cols)
    dens = ts_all.groupby("user_id").size()
    dense_users = [u for u in ok_counts.index if dens.get(u, 0) >= min_density][:n_users]
    by_user = {u: g.sort_values("timestamp").reset_index(drop=True)
               for u, g in ts_all[ts_all["user_id"].isin(dense_users)].groupby("user_id", sort=False)}

    # --- fleet sleep-gap distribution (hours), capped to a plausible sleep range ---
    samp = ts_all[["user_id", "timestamp"]].copy()
    samp["ts_ns"] = samp["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    fleet_gaps = []
    for _, g in samp.groupby("user_id", sort=False):
        d = np.diff(np.sort(g["ts_ns"].to_numpy())) / HOUR_NS
        fleet_gaps.append(d[(d > 3) & (d < 72)])
    fleet_gaps_h = np.concatenate(fleet_gaps) if fleet_gaps else np.array([6.0])
    if fleet_gaps_h.size:
        fleet_gaps_h = fleet_gaps_h[rng_.integers(0, fleet_gaps_h.size,
                                                  min(fleet_gaps_h.size, 50000))]

    summary_rows: List[dict] = []
    rep_rows: List[dict] = []
    transition_rows: List[dict] = []
    result: Dict[str, dict] = {}

    for mech in mechanisms:
        tm = time.time()
        # clean reference extraction + truth (proposed-on-clean) + gap-placement positions
        ref_ext: Dict[str, dict] = {}
        truth_ends: Dict[str, np.ndarray] = {}
        ref_pos: Dict[str, pd.DataFrame] = {}
        for u in dense_users:
            ext = extract_union_od2_fast(by_user[u], mech)
            ref_ext[u] = ext
            truth_ends[u] = _no_response_ends(ext, "proposed")
            ref_pos[u] = pd.DataFrame({"start_ns": ext["start_ns"], "low_ns": ext["low_ns"],
                                       "end_ns": ext["end_ns"]})

        # regimes
        regimes: List[Tuple[str, callable]] = []
        for f in MCAR_FRACS:
            regimes.append((f"mcar_{int(f*100)}pct", lambda g, u, r, f=f: _inject_mcar(g, f, r)))
        for h in GAP_HOURS:
            regimes.append((f"gap_{h}h_around_low",
                            lambda g, u, r, h=h: _inject_contiguous_gap_od2(g, h, "around_low", ref_pos.get(u), r)))
        for pos in GAP_POSITIONS:
            regimes.append((f"gap_24h_{pos}",
                            lambda g, u, r, pos=pos: _inject_contiguous_gap_od2(g, 24, pos, ref_pos.get(u), r)))
        for h in TRUNCATE_HOURS:
            regimes.append((f"truncate_{h}h", lambda g, u, r, h=h: _inject_truncation(g, h)))
        regimes.append(("sleepgaps_fleet", lambda g, u, r: _inject_sleepgaps(g, fleet_gaps_h, r)))

        for regime_name, inject in regimes:
            false_by_user = {det: {u: [] for u in dense_users} for det in DETECTORS}
            recovery_by_rep: List[float] = []
            det_false_sum = {det: [] for det in DETECTORS}
            det_missed_sum = {det: [] for det in DETECTORS}
            det_count_sum = {det: [] for det in DETECTORS}
            for b in range(replicates):
                det_false = {det: 0 for det in DETECTORS}
                det_missed = {det: 0 for det in DETECTORS}
                det_count = {det: 0 for det in DETECTORS}
                rec_hits = rec_tot = 0
                for u in dense_users:
                    ref_all = ref_ext[u]["end_ns"]
                    if ref_all.size == 0:
                        continue
                    inj_ext = extract_union_od2_fast(inject(by_user[u], u, rng_), mech)
                    rec_tot += ref_all.size
                    rec_hits += _match_count(ref_all, inj_ext["end_ns"])
                    truth = truth_ends[u]
                    for det in DETECTORS:
                        inj_nr = _no_response_ends(inj_ext, det)
                        fb = int(inj_nr.size - _match_count(inj_nr, truth))   # artifact no-response
                        mb = int(truth.size - _match_count(truth, inj_nr))    # missed real no-response
                        det_false[det] += fb
                        det_missed[det] += mb
                        det_count[det] += int(inj_nr.size)
                        false_by_user[det][u].append(fb)
                recovery_by_rep.append(rec_hits / rec_tot if rec_tot else 1.0)
                for det in DETECTORS:
                    det_false_sum[det].append(det_false[det])
                    det_missed_sum[det].append(det_missed[det])
                    det_count_sum[det].append(det_count[det])
                    rep_rows.append({"mechanism": mech, "regime": regime_name, "detector": det,
                                     "replicate": b, "false_no_response": det_false[det],
                                     "missed_no_response": det_missed[det],
                                     "n_no_response": det_count[det]})
            for det in DETECTORS:
                vbu = [np.array(false_by_user[det][u]) for u in dense_users if false_by_user[det][u]]
                ci = pc.user_bootstrap_mean(vbu, 400, rng_) if vbu else {"point": 0, "ci_lo": 0, "ci_hi": 0}
                summary_rows.append({
                    "mechanism": mech, "regime": regime_name, "detector": det,
                    "mean_false_no_response": round(float(np.mean(det_false_sum[det])), 3),
                    "mean_missed_no_response": round(float(np.mean(det_missed_sum[det])), 3),
                    "mean_n_no_response": round(float(np.mean(det_count_sum[det])), 3),
                    "false_per_user_point": round(ci["point"], 4),
                    "false_per_user_ci_lo": round(ci["ci_lo"], 4),
                    "false_per_user_ci_hi": round(ci["ci_hi"], 4),
                    "mean_episode_recovery": round(float(np.mean(recovery_by_rep)), 4),
                    "n_replicates": replicates,
                })

        # per-mechanism aggregate across regimes
        sm = pd.DataFrame([r for r in summary_rows if r["mechanism"] == mech])
        agg = sm.groupby("detector")["mean_false_no_response"].mean()
        naive_false = float(agg.get("naive", np.nan))
        proposed_false = float(agg.get("proposed", np.nan))
        recovery_proposed = float(sm[sm["detector"] == "proposed"]["mean_episode_recovery"].mean())
        for regime_name in sm["regime"].unique():
            sub = sm[sm["regime"] == regime_name]
            nv = float(sub[sub["detector"] == "naive"]["mean_false_no_response"].iloc[0])
            pr = float(sub[sub["detector"] == "proposed"]["mean_false_no_response"].iloc[0])
            transition_rows.append({"mechanism": mech, "regime": regime_name,
                                    "naive_mean_false_no_response": nv,
                                    "proposed_mean_false_no_response": pr,
                                    "false_no_response_reduction": round(nv - pr, 3)})
        n_ends = int(sum(ref_ext[u]["end_ns"].size for u in dense_users))
        result[mech] = {
            "mechanism": mech,
            "naive_mean_false_no_response": round(naive_false, 3),
            "proposed_mean_false_no_response": round(proposed_false, 3),
            "false_no_response_reduction": round(naive_false - proposed_false, 3),
            "proposed_episode_recovery": round(recovery_proposed, 4),
            "ic6_benefit_supported": bool(proposed_false < naive_false),
            "n_dense_users": len(dense_users),
            "n_clean_ends": n_ends,
            "n_regimes": len(regimes),
            "runtime_s": round(time.time() - tm, 2),
        }
        print(f"[E-od2:{mech}] mean false no-response across regimes: naive={naive_false:.2f} "
              f"vs proposed={proposed_false:.2f} (reduction {naive_false-proposed_false:.2f}); "
              f"recovery={recovery_proposed:.3f}; clean_ends={n_ends}; "
              f"IC6 {'SUPPORTED' if proposed_false < naive_false else 'NOT SUPPORTED'} "
              f"({time.time()-tm:.1f}s)", flush=True)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "missingness_stress_summary_od2.csv", index=False)
    pc.save_anon_parquet(pd.DataFrame(rep_rows), out_dir / "missingness_stress_replicates_od2.parquet")
    pd.DataFrame(transition_rows).to_csv(out_dir / "missingness_label_transitions_od2.csv", index=False)

    print(f"[E-od2] done: {len(mechanisms)} mechanisms x {len(dense_users)} users "
          f"({time.time()-t0:.1f}s)", flush=True)
    return {"by_mechanism": result, "n_dense_users": len(dense_users),
            "runtime_s": round(time.time() - t0, 2)}
