"""Patent evidence A2 -- negative controls & temporal falsification.

ADDITIVE. Tests whether an effective FCC step is *specifically* associated with a
true qualified learning opportunity and its causal END time, rather than with
elapsed time, activity, cycle accumulation, user identity, or the marginal
distribution of episode times.

Method: the technical statistic is the END-anchored effective-FCC response
probability over qualified (production ``ok``) complete-window episodes,
recomputed from the raw FCC-step event stream (NOT from proxy labels). For each
negative control we destroy the true end<->step alignment while preserving the
per-user marginal structure, and re-measure the same statistic. If the response
is merely a function of elapsed time / marginal step density, the control
statistic equals the true statistic; if it is specifically tied to the true
qualified end, the control collapses toward a baseline.

Controls (per-user marginal structure preserved):
  1. circular_step_shift     -- roll effective FCC steps by delta within the user's
                                observation span (>=7d, <= span-7d); keep true ends.
  2. circular_episode_shift  -- roll episode ENDs by delta; keep true steps.
  3. within_user_permutation -- re-pair each end with another eligible end of the
                                same user (permute anchor<->window assignment).
  4. matched_pseudo_episode  -- random pseudo ends per user, matched on calendar
                                month + observation availability, excluded within a
                                radius of any true qualified end; keep true steps.
  5. rsoc_phase_shift        -- circularly shift RSOC vs FCC/cycle within user and
                                re-extract episodes (expensive raw re-extraction).

USER-clustered bootstrap throughout (spec 2.10); empirical randomization p-value
from the replicate distribution. censored/unknown are never counted as
no_response (spec 2.3).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from .fcc_learning import EPISODE_THRESHOLDS, extract_high_low_high_episodes, fcc_step_indicator

WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
PRIMARY_W = 72
MIN_SHIFT_DAYS = 7.0
PSEUDO_EXCLUSION_DAYS = 7.0
CONFIRMED_NR_USER_MIN = 3       # >=3 confirmed no-response -> FW-like flagged user


# --------------------------------------------------------------------------- #
# Eligible-anchor construction (qualified, complete-window, END-anchored)
# --------------------------------------------------------------------------- #
def build_anchors(episodes: pd.DataFrame, band: str = pc.PRIMARY_THRESHOLD,
                  ok_only: bool = True) -> pd.DataFrame:
    """One row per qualified END-anchored episode for the chosen band.

    Eligibility mirrors production: an ``ok``-quality episode whose 72h response
    window is observable (``window_72h_complete``). These are the slots over
    which a confirmed responded / no_response is decidable."""
    ep = episodes[episodes["threshold_name"] == band].copy()
    if ok_only:
        ep = ep[ep["is_ok"]]
    ep = ep[ep["window_72h_complete"].fillna(False).astype(bool)]
    return ep[["user_id", "end_ns", "start_ns", "low_ns",
               "fcc_response_status_72h"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Statistic: END-anchored effective response over a set of anchors
# --------------------------------------------------------------------------- #
def _response_for_anchors(anchor_ns: np.ndarray, sbu: Dict[str, np.ndarray],
                          last_ns: int) -> Dict[str, np.ndarray]:
    """For one user's anchor timestamps + step arrays, return per-anchor:
    complete[w], responded[w], n_eff[w], delay (first eff-step lag, h).

    An anchor is *eligible* at window w iff anchor+w <= last_ns (the window is
    observed); otherwise it is censored and excluded from the rate."""
    out: Dict[str, np.ndarray] = {}
    ts = sbu["ts_ns"] if sbu is not None else np.array([], dtype=np.int64)
    eff = sbu["is_effective"] if sbu is not None else np.array([], dtype=bool)
    n = anchor_ns.size
    delay = np.full(n, np.nan)
    for w in WINDOWS_H:
        win = int(w) * pc.HOUR_NS
        complete = anchor_ns + win <= last_ns
        responded = np.zeros(n, dtype=bool)
        neff = np.zeros(n, dtype=float)
        for i in range(n):
            a = int(np.searchsorted(ts, anchor_ns[i], side="left"))
            b = int(np.searchsorted(ts, anchor_ns[i] + win, side="right"))
            if b > a:
                m = eff[a:b]
                cnt = int(m.sum())
                neff[i] = cnt
                if cnt > 0:
                    responded[i] = True
                    if w == PRIMARY_W and not np.isfinite(delay[i]):
                        first = a + int(np.flatnonzero(m)[0])
                        delay[i] = (ts[first] - anchor_ns[i]) / pc.HOUR_NS
        out[f"complete_{w}"] = complete
        out[f"responded_{w}"] = responded & complete
        out[f"neff_{w}"] = neff
    out["delay"] = delay
    return out


def statistic(anchors_by_user: Dict[str, np.ndarray], sbu: Dict[str, Dict[str, np.ndarray]],
              last_by_user: Dict[str, int]) -> Dict[str, object]:
    """Pooled response statistics + per-user numerator/denominator arrays for the
    clustered bootstrap, computed over every user's anchors."""
    users = list(anchors_by_user.keys())
    per_user_num = {w: [] for w in WINDOWS_H}
    per_user_den = {w: [] for w in WINDOWS_H}
    per_user_neff = {w: [] for w in WINDOWS_H}
    delays_by_user: List[np.ndarray] = []
    nr72_by_user: List[int] = []           # confirmed no-response episode count per user
    for uid in users:
        anc = anchors_by_user[uid]
        if anc.size == 0:
            continue
        res = _response_for_anchors(anc, sbu.get(uid), last_by_user.get(uid, 0))
        for w in WINDOWS_H:
            den = int(res[f"complete_{w}"].sum())
            num = int(res[f"responded_{w}"].sum())
            per_user_num[w].append(num)
            per_user_den[w].append(den)
            per_user_neff[w].append(float(res[f"neff_{w}"][res[f"complete_{w}"]].sum()))
        d = res["delay"]
        delays_by_user.append(d[np.isfinite(d)])
        comp72 = res["complete_72"]
        resp72 = res["responded_72"]
        nr = int((comp72 & ~resp72).sum())
        nr72_by_user.append(nr)
    out: Dict[str, object] = {}
    for w in WINDOWS_H:
        num = np.array(per_user_num[w], dtype=float)
        den = np.array(per_user_den[w], dtype=float)
        out[f"resp_prob_{w}h"] = float(num.sum() / den.sum()) if den.sum() else float("nan")
        out[f"eff_step_rate_{w}h"] = (float(np.array(per_user_neff[w]).sum() / den.sum())
                                      if den.sum() else float("nan"))
        out[f"_num_{w}"] = num
        out[f"_den_{w}"] = den
    alld = np.concatenate(delays_by_user) if delays_by_user else np.array([])
    out["median_delay_h"] = float(np.median(alld)) if alld.size else float("nan")
    out["_delays_by_user"] = delays_by_user
    nr = np.array(nr72_by_user, dtype=float)
    out["confirmed_no_response_episodes"] = float(nr.sum())
    out["fw_like_flagged_users"] = int((nr >= CONFIRMED_NR_USER_MIN).sum())
    out["_nr_by_user"] = nr
    return out


# --------------------------------------------------------------------------- #
# Control generators (each returns anchors_by_user OR steps_by_user)
# --------------------------------------------------------------------------- #
def _draw_shift(span_ns: int, rng_: np.random.Generator) -> int:
    """delta in [7d, span-7d] (so neither identity nor near-identity)."""
    lo = int(MIN_SHIFT_DAYS * pc.DAY_NS)
    hi = int(span_ns - MIN_SHIFT_DAYS * pc.DAY_NS)
    if hi <= lo:
        return lo if span_ns > lo else int(span_ns // 2)
    return int(rng_.integers(lo, hi))


def _circular_shift(values_ns: np.ndarray, first_ns: int, span_ns: int,
                    delta: int) -> np.ndarray:
    if span_ns <= 0:
        return values_ns
    return first_ns + ((values_ns - first_ns + delta) % span_ns)


def control_circular_step_shift(anchors_by_user, sbu, last_by_user, span, first,
                                rng_) -> Dict[str, object]:
    new_sbu: Dict[str, Dict[str, np.ndarray]] = {}
    for uid, arr in sbu.items():
        d = _draw_shift(span.get(uid, 0), rng_)
        shifted = _circular_shift(arr["ts_ns"], first[uid], span[uid], d)
        order = np.argsort(shifted)
        new_sbu[uid] = {"ts_ns": shifted[order], "is_effective": arr["is_effective"][order],
                        "abs_step": arr["abs_step"][order], "step": arr["step"][order]}
    return statistic(anchors_by_user, new_sbu, last_by_user)


def control_circular_episode_shift(anchors_by_user, sbu, last_by_user, span, first,
                                   rng_) -> Dict[str, object]:
    new_anch: Dict[str, np.ndarray] = {}
    for uid, anc in anchors_by_user.items():
        d = _draw_shift(span.get(uid, 0), rng_)
        new_anch[uid] = _circular_shift(anc, first[uid], span[uid], d)
    return statistic(new_anch, sbu, last_by_user)


def control_within_user_time_randomization(anchors_by_user, sbu, last_by_user, span,
                                           first, last, rng_) -> Dict[str, object]:
    """Re-draw each anchor uniformly within the user's [first+7d, last-7d] span.

    Preserves per-user anchor COUNT and user identity (so it controls for marginal
    per-user step density and identity) while destroying the specific end times.
    A pure label permutation among a user's own ends leaves the pooled rate
    invariant by construction; re-drawing the anchor times is the operative
    within-user falsification (and we note the invariance property in the report)."""
    new_anch: Dict[str, np.ndarray] = {}
    pad = int(MIN_SHIFT_DAYS * pc.DAY_NS)
    for uid, anc in anchors_by_user.items():
        lo = first.get(uid, 0) + pad
        hi = last.get(uid, 0) - pad
        if hi <= lo or anc.size == 0:
            new_anch[uid] = anc
            continue
        new_anch[uid] = np.sort(rng_.integers(lo, hi, anc.size).astype(np.int64))
    return statistic(new_anch, sbu, last_by_user)


def build_pseudo_pool(anchors_by_user, samples_by_user, months_by_user
                      ) -> Dict[str, dict]:
    """Precompute, per user, the calendar-month -> allowed-sample-times pool used
    by the matched-pseudo control (allowed = observed samples not within +/-7d of
    any true qualified end). Done once so each replicate is a cheap draw."""
    excl = int(PSEUDO_EXCLUSION_DAYS * pc.DAY_NS)
    pool: Dict[str, dict] = {}
    for uid, anc in anchors_by_user.items():
        smp = samples_by_user.get(uid)
        if smp is None or smp.size == 0 or anc.size == 0:
            pool[uid] = {"months": np.array([], dtype=np.int64), "by_month": {},
                         "fallback": np.array([], dtype=np.int64)}
            continue
        near = np.min(np.abs(smp[:, None] - anc[None, :]), axis=1) <= excl
        allowed = smp[~near]
        if allowed.size == 0:
            allowed = smp
        amonths = (allowed.astype("datetime64[ns]").astype("datetime64[M]")).astype(np.int64)
        by_month = {int(m): allowed[amonths == m] for m in np.unique(amonths)}
        pool[uid] = {"months": months_by_user[uid], "by_month": by_month, "fallback": allowed}
    return pool


def control_matched_pseudo(anchors_by_user, sbu, last_by_user, pseudo_pool,
                           rng_) -> Dict[str, object]:
    """Pseudo ends matched on user + calendar month + observation availability,
    excluded within +/-7d of any true qualified end (pool precomputed)."""
    new_anch: Dict[str, np.ndarray] = {}
    for uid, anc in anchors_by_user.items():
        p = pseudo_pool.get(uid)
        if p is None or p["months"].size == 0:
            new_anch[uid] = np.array([], dtype=np.int64)
            continue
        picks: List[int] = []
        for m in p["months"]:
            cand = p["by_month"].get(int(m), p["fallback"])
            if cand.size == 0:
                cand = p["fallback"]
            picks.append(int(cand[rng_.integers(0, cand.size)]))
        new_anch[uid] = np.sort(np.array(picks, dtype=np.int64))
    return statistic(new_anch, sbu, last_by_user)


def control_rsoc_phase_shift(users, df_by_user, design_by_user, last_by_user,
                             span, first, rng_) -> Dict[str, object]:
    """Circularly shift RSOC vs FCC/cycle within user, re-extract primary-band
    episodes, then measure effective response after the (now misaligned) ends."""
    anchors: Dict[str, np.ndarray] = {}
    sbu: Dict[str, Dict[str, np.ndarray]] = {}
    high, low = EPISODE_THRESHOLDS[pc.PRIMARY_THRESHOLD]
    for uid in users:
        g = df_by_user.get(uid)
        if g is None or len(g) < 5:
            continue
        rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
        fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
        ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        n = rsoc.size
        roll = int(rng_.integers(int(n * 0.1), int(n * 0.9))) if n > 10 else 1
        rsoc_shift = np.roll(rsoc, roll)
        idx = extract_high_low_high_episodes(rsoc_shift, high, low)
        ends = np.array([ts_ns[e] for (_, _, e) in idx], dtype=np.int64)
        anchors[uid] = ends
        is_step, _ = fcc_step_indicator(fcc, pc.EFFECTIVE_STEP_MWH)
        pos = np.flatnonzero(is_step)
        sbu[uid] = {"ts_ns": ts_ns[pos], "is_effective": np.ones(pos.size, dtype=bool),
                    "abs_step": np.abs(np.diff(fcc, prepend=fcc[0]))[pos] if pos.size else np.array([]),
                    "step": np.zeros(pos.size)}
    return statistic(anchors, sbu, last_by_user)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
        design: pd.Series, seed: int = 42, n_cheap: int = 1000, n_raw: int = 200,
        rsoc_user_cap: Optional[int] = None) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    anchors_df = build_anchors(episodes, pc.PRIMARY_THRESHOLD, ok_only=True)
    anchors_by_user = {uid: g["end_ns"].to_numpy(dtype=np.int64)
                       for uid, g in anchors_df.groupby("user_id", sort=False)}
    # effective-only step arrays per user
    eff_steps = steps[steps["is_effective"]]
    sbu = pc.steps_by_user(eff_steps)
    for uid in anchors_by_user:
        sbu.setdefault(uid, {"ts_ns": np.array([], dtype=np.int64),
                             "is_effective": np.array([], dtype=bool),
                             "abs_step": np.array([]), "step": np.array([])})

    # per-user observation span + month/sample availability (from raw timeseries)
    ts_meta = pc.load_timeseries(["user_id", "timestamp",
                                  "remainingCapacityInPercentage", "fullChargeCapacity",
                                  "cycleCount"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    span: Dict[str, int] = {}
    first: Dict[str, int] = {}
    last_by_user: Dict[str, int] = {}
    samples_by_user: Dict[str, np.ndarray] = {}
    months_by_user: Dict[str, np.ndarray] = {}
    df_by_user: Dict[str, pd.DataFrame] = {}
    for uid, g in ts_meta.groupby("user_id", sort=False):
        g = g.sort_values("ts_ns")
        arr = g["ts_ns"].to_numpy(dtype=np.int64)
        first[uid] = int(arr[0]); last_by_user[uid] = int(arr[-1])
        span[uid] = int(arr[-1] - arr[0])
        samples_by_user[uid] = arr
        df_by_user[uid] = g
    for uid, anc in anchors_by_user.items():
        months_by_user[uid] = (anc.astype("datetime64[ns]").astype("datetime64[M]")).astype(np.int64)

    # ---- TRUE statistic ----
    true_stat = statistic(anchors_by_user, sbu, last_by_user)
    print(f"[A2] true resp_prob_72h={true_stat['resp_prob_72h']:.3f} "
          f"confirmed_no_response={int(true_stat['confirmed_no_response_episodes'])} "
          f"({time.time()-t0:.1f}s)")

    # ---- user-bootstrap CI of the true statistic ----
    boot_rows: List[dict] = []
    for w in WINDOWS_H:
        ci = pc.user_bootstrap_ratio(true_stat[f"_num_{w}"], true_stat[f"_den_{w}"], 1000, rng_)
        boot_rows.append({"statistic": f"resp_prob_{w}h", **ci})
    delay_ci = pc.user_bootstrap_mean(true_stat["_delays_by_user"], 1000, rng_)
    boot_rows.append({"statistic": "median_delay_h_mean", **delay_ci})
    nr_ci = pc.user_bootstrap_mean([np.array([x]) for x in true_stat["_nr_by_user"]], 1000, rng_)
    boot_rows.append({"statistic": "confirmed_no_response_per_user", **nr_ci})
    pd.DataFrame(boot_rows).to_csv(out_dir / "negative_control_user_bootstrap.csv", index=False)

    # ---- run controls ----
    metrics = ["resp_prob_24h", "resp_prob_72h", "resp_prob_168h",
               "eff_step_rate_72h", "median_delay_h", "confirmed_no_response_episodes",
               "fw_like_flagged_users"]
    cheap_controls = {
        "circular_step_shift": lambda r: control_circular_step_shift(
            anchors_by_user, sbu, last_by_user, span, first, r),
        "circular_episode_shift": lambda r: control_circular_episode_shift(
            anchors_by_user, sbu, last_by_user, span, first, r),
        "within_user_time_randomization": lambda r: control_within_user_time_randomization(
            anchors_by_user, sbu, last_by_user, span, first, last_by_user, r),
        "matched_pseudo_episode": lambda r: control_matched_pseudo(
            anchors_by_user, sbu, last_by_user, pseudo_pool, r),
    }
    pseudo_pool = build_pseudo_pool(anchors_by_user, samples_by_user, months_by_user)
    rsoc_users = list(anchors_by_user.keys())
    if rsoc_user_cap:
        rsoc_users = rsoc_users[:rsoc_user_cap]

    boot_lo72 = float([r for r in boot_rows if r["statistic"] == "resp_prob_72h"][0]["ci_lo"])

    rep_rows: List[dict] = []
    summary_rows: List[dict] = []
    detector_rows: List[dict] = []

    def _summarise(name: str, reps: List[Dict[str, object]], runtime: float):
        for m in metrics:
            null = np.array([float(r[m]) for r in reps if np.isfinite(r.get(m, np.nan))])
            true_v = float(true_stat[m])
            lo = float(np.nanpercentile(null, 2.5)) if null.size else float("nan")
            hi = float(np.nanpercentile(null, 97.5)) if null.size else float("nan")
            mean = float(np.nanmean(null)) if null.size else float("nan")
            alt = "greater" if "resp" in m or "fw_like" in m or "no_response" in m else "two-sided"
            p = pc.randomization_pvalue(true_v, null, alt)
            outside = bool(np.isfinite(lo) and (true_v < lo or true_v > hi))
            # directional consistency under user bootstrap: for the response-probability
            # metric, the TRUE bootstrap-lower-CI must exceed this control's null mean.
            dir_ok = (bool(boot_lo72 > mean) if m == "resp_prob_72h" and np.isfinite(mean)
                      else None)
            summary_rows.append({
                "control": name, "metric": m, "true_value": round(true_v, 5),
                "control_mean": round(mean, 5), "control_ci_lo": round(lo, 5),
                "control_ci_hi": round(hi, 5),
                "true_minus_control": round(true_v - mean, 5) if np.isfinite(mean) else None,
                "true_over_control": round(true_v / mean, 4) if mean else None,
                "true_outside_null_95ci": outside,
                "true_bootlo_exceeds_control_mean": dir_ok,
                "directionally_supported": bool(outside and dir_ok) if dir_ok is not None else None,
                "randomization_p": round(p, 5), "n_replicates": int(null.size),
                "runtime_s": round(runtime, 2),
            })
        detector_rows.append({
            "control": name,
            "true_confirmed_no_response": int(true_stat["confirmed_no_response_episodes"]),
            "control_mean_confirmed_no_response":
                round(float(np.mean([r["confirmed_no_response_episodes"] for r in reps])), 2),
            "true_fw_like_flagged_users": int(true_stat["fw_like_flagged_users"]),
            "control_mean_fw_like_flagged_users":
                round(float(np.mean([r["fw_like_flagged_users"] for r in reps])), 2),
        })

    for name, fn in cheap_controls.items():
        tc = time.time()
        reps = []
        for b in range(n_cheap):
            s = fn(rng_)
            row = {k: float(s[k]) for k in metrics}
            row.update({"control": name, "replicate": b})
            reps.append(s)
            rep_rows.append(row)
        _summarise(name, reps, time.time() - tc)
        print(f"[A2] control {name}: mean resp72="
              f"{np.mean([r['resp_prob_72h'] for r in reps]):.3f} ({time.time()-tc:.1f}s)")

    # RSOC phase-shift (expensive raw re-extraction)
    tc = time.time()
    reps = []
    for b in range(n_raw):
        s = control_rsoc_phase_shift(rsoc_users, df_by_user, design, last_by_user,
                                     span, first, rng_)
        row = {k: float(s[k]) for k in metrics}
        row.update({"control": "rsoc_phase_shift", "replicate": b})
        reps.append(s)
        rep_rows.append(row)
    _summarise("rsoc_phase_shift", reps, time.time() - tc)
    print(f"[A2] control rsoc_phase_shift: mean resp72="
          f"{np.mean([r['resp_prob_72h'] for r in reps]):.3f} ({time.time()-tc:.1f}s)")

    pd.DataFrame(rep_rows).to_parquet(out_dir / "negative_control_replicates.parquet", index=False)
    summ = pd.DataFrame(summary_rows)
    summ.to_csv(out_dir / "negative_control_summary.csv", index=False)
    pd.DataFrame(detector_rows).to_csv(out_dir / "negative_control_detector_impact.csv", index=False)

    # ---- acceptance criterion (spec 4.5) ----
    # claim a stimulus-response effect only if the TRUE response statistic is outside
    # the 95% null interval for >=2 controls AND remains directionally consistent under
    # user bootstrap (TRUE bootstrap-lower-CI exceeds the control null mean) for >=2 of them.
    resp72 = summ[summ["metric"] == "resp_prob_72h"]
    n_outside = int(resp72["true_outside_null_95ci"].sum())
    n_directional = int((resp72["directionally_supported"] == True).sum())  # noqa: E712
    directionally_consistent = bool(n_directional >= 2)
    accept = bool(n_outside >= 2 and directionally_consistent)

    print(f"[A2] acceptance: true resp72 outside null-95CI for {n_outside}/{len(resp72)} controls; "
          f"directionally supported under user-bootstrap for {n_directional}/{len(resp72)} -> "
          f"{'SUPPORTED' if accept else 'NOT SUPPORTED'}")
    return {
        "true_resp_prob_72h": float(true_stat["resp_prob_72h"]),
        "true_confirmed_no_response": int(true_stat["confirmed_no_response_episodes"]),
        "n_controls_outside_null": n_outside,
        "n_controls_directionally_supported": n_directional,
        "n_controls_total": int(resp72.shape[0]),
        "directionally_consistent_bootstrap": directionally_consistent,
        "stimulus_response_supported": accept,
        "n_anchors": int(sum(a.size for a in anchors_by_user.values())),
        "n_users_with_anchors": len(anchors_by_user),
        "runtime_s": round(time.time() - t0, 2),
    }
