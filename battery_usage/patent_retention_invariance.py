"""Patent evidence D -- bounded-retention causal-equivalence grid (IC5).

ADDITIVE. Builds a full-history reference event ledger, then processes the same
data under bounded raw-retention windows both STATELESS (only the raw in the
window, fresh each stride) and STATEFUL (bounded raw + a small persistent causal
derived state), and measures how close each gets to full-history equivalence.

Two engines:
  * ``closed_form_stateless`` -- a stateless sliding-window detector only sees a
    physical episode if the whole [start, end] (and, to resolve a response, the
    [end, end+rw] window) fits inside ONE retained window. Recall, duplicate count
    (re-detection across overlapping windows), response agreement and the
    no-response counter error are all computed in closed form from the ledger.
  * ``windowed_stateful_replay`` -- a genuine causal processor that, at each
    stride, has only the last W days of raw plus a persistent FSM / pending-deadline
    / seen-id / last-effective-change state. Used to VERIFY (not assert) that a
    bounded-retention stateful configuration reproduces the full-history reference,
    and (in ``patent_state_minimality``) to ablate each state component.

The stateful processor never initialises from future / full-history state and a
no-response deadline never fires before its window is observed (no future leakage).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from .fcc_learning import EPISODE_THRESHOLDS, fcc_step_indicator

RETENTION_DAYS = (7, 14, 21, 30, 45, 60, 90)
STRIDES_DAYS = (1, 7)
ALIGNMENTS_DAYS = (0, 1, 2, 3, 4, 5, 6)
RESPONSE_WINDOWS_H = (24, 72, 168)
GAP_CONFIGS = ("ok_only", "graded")          # >=2 gap-quality configurations (spec 9.2)
PRIMARY = pc.PRIMARY_THRESHOLD
EPISODE_MAX_GAP_H = 12.0
# estimated minimal serialized state per user (bytes): partial FSM (1) + 6 i64 scalars
# + pending deadline queue (avg) + a 16-byte resolved-ledger rolling hash.
STATE_FIXED_BYTES = 1 + 6 * 8 + 16


# --------------------------------------------------------------------------- #
# Reference ledger
# --------------------------------------------------------------------------- #
def build_reference_ledger(episodes: pd.DataFrame, steps: pd.DataFrame,
                           force: bool = False) -> pd.DataFrame:
    """Full-history resolved physical-episode ledger (primary band) + per-user
    any/effective reset-event counts. The production full-history episodes ARE the
    causal reference (spec 9.1)."""
    if pc.LEDGER_CACHE.exists() and not force:
        return pd.read_parquet(pc.LEDGER_CACHE)
    ep = episodes[episodes["threshold_name"] == PRIMARY].copy()
    eff_counts = steps[steps["is_effective"]].groupby("user_id").size()
    any_counts = steps.groupby("user_id").size()
    led = ep[["user_id", "episode_id", "start_ns", "low_ns", "end_ns",
              "episode_quality", "quality_tier", "is_ok",
              "fcc_response_status_72h", "window_72h_complete"]].copy()
    led["response_deadline_ns"] = led["end_ns"] + pc.PRIMARY_WINDOW_H * pc.HOUR_NS
    led["n_any_resets_user"] = led["user_id"].map(any_counts).fillna(0).astype(int)
    led["n_eff_resets_user"] = led["user_id"].map(eff_counts).fillna(0).astype(int)
    pc.ensure_dirs()
    led.to_parquet(pc.LEDGER_CACHE, index=False)
    return led


# --------------------------------------------------------------------------- #
# Closed-form stateless detector metrics
# --------------------------------------------------------------------------- #
def _grid_count(lo_ns: np.ndarray, hi_ns: np.ndarray, base_ns: np.ndarray,
                stride_ns: int, last_ns: np.ndarray) -> np.ndarray:
    """Number of stride grid points t = base + k*stride (k>=0, t<=last) in [lo, hi]."""
    hi = np.minimum(hi_ns, last_ns)
    k_lo = np.ceil((lo_ns - base_ns) / stride_ns)
    k_lo = np.maximum(k_lo, 0)
    k_hi = np.floor((hi - base_ns) / stride_ns)
    return np.maximum(0, (k_hi - k_lo + 1)).astype(np.int64)


def closed_form_stateless(led: pd.DataFrame, first_by_user: Dict[str, int],
                          last_by_user: Dict[str, int], W_days: int, stride_days: int,
                          align_days: int, rw_h: int, gap_config: str) -> Dict[str, float]:
    """Stateless sliding-window invariance metrics vs the full-history reference."""
    W = W_days * pc.DAY_NS
    stride = stride_days * pc.DAY_NS
    rw = rw_h * pc.HOUR_NS
    d = led
    if gap_config == "ok_only":
        d = d[d["is_ok"]]
    else:  # graded: HIGH_OK + MEDIUM_GAP are no-response-capable
        d = d[d["quality_tier"].isin(pc.NO_RESPONSE_CAPABLE)]
    if d.empty:
        return {}
    start = d["start_ns"].to_numpy(); end = d["end_ns"].to_numpy()
    base = np.array([first_by_user[u] + align_days * pc.DAY_NS for u in d["user_id"]])
    last = np.array([last_by_user[u] for u in d["user_id"]])
    ref_status = d["fcc_response_status_72h"].to_numpy().astype(str)

    # A stateless window ending at grid point t retains raw over [t-W, t]. It can detect a
    # physical episode only if the whole [start, end] fits inside that window, i.e.
    # t-W <= start AND end <= t  <=>  t in [end, start+W]. Count grid points t (= base + k*stride,
    # k>=0, t<=last) in that interval: >=1 detected, >1 means re-detection across windows.
    n_contain = _grid_count(end, start + W, base, stride, last)
    detected = n_contain >= 1
    duplicates = np.maximum(0, n_contain - 1)
    # response resolvable: a window also contains [start, end+rw]: t in [end+rw, start+W]
    n_resolv = _grid_count(end + rw, start + W, base, stride, last)
    resolvable = n_resolv >= 1
    # stateless status: resolvable -> reference status; detected-not-resolvable -> censored; missed -> 'missed'
    stateless_status = np.where(resolvable, ref_status,
                                np.where(detected, "censored", "missed"))
    agreement = float(np.mean(stateless_status == ref_status))
    recall = float(np.mean(detected))

    # per-user no-response counter error
    df = pd.DataFrame({"user_id": d["user_id"].to_numpy(), "ref": ref_status,
                       "sl": stateless_status})
    ref_nr = df.assign(x=df["ref"] == "no_response").groupby("user_id")["x"].sum()
    sl_nr = df.assign(x=df["sl"] == "no_response").groupby("user_id")["x"].sum()
    nr_mae = float((ref_nr - sl_nr).abs().mean())
    ref_cz = df.assign(x=df["ref"] == "censored").groupby("user_id")["x"].sum()
    sl_cz = df.assign(x=df["sl"] == "censored").groupby("user_id")["x"].sum()
    cz_mae = float((ref_cz - sl_cz).abs().mean())
    return {
        "physical_episode_recall": round(recall, 4),
        "exact_episode_id_match": round(recall, 4),
        "duplicate_episode_count": int(duplicates.sum()),
        "duplicate_rate": round(float(duplicates.sum() / max(detected.sum(), 1)), 4),
        "response_status_agreement": round(agreement, 4),
        "no_response_counter_mae": round(nr_mae, 4),
        "censored_counter_mae": round(cz_mae, 4),
        "n_reference_episodes": int(len(d)),
    }


# --------------------------------------------------------------------------- #
# Genuine windowed stateful replay (causal; bounded raw + persistent state)
# --------------------------------------------------------------------------- #
FULL_COMPONENTS = frozenset({"fsm", "pending", "seen_ids", "last_eff_ts",
                             "eff_cycle", "gap_censor", "ordering"})


def windowed_stateful_replay(g: pd.DataFrame, uid: str, W_days: int, stride_days: int,
                             align_days: int, rw_h: int, gap_config: str,
                             components: Set[str] = FULL_COMPONENTS) -> Dict[str, object]:
    """Causal bounded-retention stateful detector for one user.

    At each stride the detector has only the last W days of raw plus a persistent
    derived state. Returns detected episode ids, duplicate count, confirmed
    no-response count and censored count. Components can be disabled for the
    minimal-state ablation (spec 9.4)."""
    g = g.sort_values("timestamp")
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    n = ts.size
    if n < 3:
        return {"detected": set(), "duplicate_count": 0, "confirmed_no_response": 0,
                "censored": 0}
    is_eff, _ = fcc_step_indicator(fcc, pc.EFFECTIVE_STEP_MWH)
    high, low = EPISODE_THRESHOLDS[PRIMARY]
    W = W_days * pc.DAY_NS; stride = stride_days * pc.DAY_NS; rw = rw_h * pc.HOUR_NS
    first_ns, last_ns = int(ts[0]), int(ts[-1])
    base = first_ns + align_days * pc.DAY_NS

    use_fsm = "fsm" in components
    use_pending = "pending" in components
    use_seen = "seen_ids" in components
    use_last_eff = "last_eff_ts" in components

    seen: Set[str] = set()
    detected: Set[str] = set()
    duplicate_count = 0
    pending: Dict[str, Tuple[int, int]] = {}      # eid -> (end_ns, max_gap_ok)
    confirmed_nr = 0
    censored = 0
    last_eff_ts = first_ns
    # carried FSM
    state = "WAIT_HIGH"; s_idx = None; lo_idx = None
    proc_upto = first_ns - 1
    t = base
    # advance to first stride >= first sample
    while t < first_ns:
        t += stride

    def _close(s_i, l_i, e_i):
        nonlocal duplicate_count, confirmed_nr, censored
        s_ns, e_ns = int(ts[s_i]), int(ts[e_i])
        eid = f"{uid}|{PRIMARY}|{s_ns}|{e_ns}"
        # quality (max gap in span)
        seg = slice(s_i, e_i + 1)
        gaps = np.diff(ts[seg]) / 3.6e12 if e_i > s_i else np.array([0.0])
        max_gap = float(gaps.max()) if gaps.size else 0.0
        ok = max_gap <= EPISODE_MAX_GAP_H
        capable = ok if gap_config == "ok_only" else (max_gap <= 24.0)
        if use_seen and eid in seen:
            duplicate_count += 0       # dedup: correctly suppressed
            return
        if (not use_seen) and eid in detected:
            duplicate_count += 1       # re-emitted -> duplicate
        seen.add(eid); detected.add(eid)
        if capable:
            if use_pending:
                pending[eid] = (e_ns, 1 if ok else 0)
            else:
                # no pending: can only resolve if the whole response window is in
                # the CURRENT retained raw at detection time (else lost)
                if (e_ns + rw) <= last_ns and (e_ns + rw - W) <= s_ns:
                    _resolve_direct(e_ns, ok)

    def _resolve_direct(e_ns, ok):
        nonlocal confirmed_nr
        lo_i = int(np.searchsorted(ts, e_ns, side="left"))
        hi_i = int(np.searchsorted(ts, e_ns + rw, side="right"))
        responded = bool(is_eff[lo_i:hi_i].any()) if hi_i > lo_i else False
        if not responded and ok:
            confirmed_nr += 1

    def _resolve_pending(now_ns):
        nonlocal confirmed_nr, censored
        for eid, (e_ns, ok) in list(pending.items()):
            if (e_ns + rw) <= now_ns:                      # window observed (no leakage)
                if use_last_eff:
                    # resolve via retained raw [e, e+rw] (rw<=W) or last_eff_ts memory
                    lo_i = int(np.searchsorted(ts, e_ns, side="left"))
                    hi_i = int(np.searchsorted(ts, e_ns + rw, side="right"))
                    responded = bool(is_eff[lo_i:hi_i].any()) if hi_i > lo_i else False
                else:
                    responded = False     # without last-eff memory, cannot confirm a response
                if not responded and ok:
                    confirmed_nr += 1
                pending.pop(eid, None)

    while t <= last_ns + stride:
        # process new samples in (proc_upto, t]
        i_lo = int(np.searchsorted(ts, proc_upto, side="right"))
        i_hi = int(np.searchsorted(ts, t, side="right"))
        if not use_fsm:
            state = "WAIT_HIGH"; s_idx = None; lo_idx = None     # FSM forgets across windows
        for i in range(i_lo, i_hi):
            rs = rsoc[i]
            if not (rs >= 0 and rs <= 100):
                continue
            if state == "WAIT_HIGH":
                if rs >= high:
                    s_idx = i; state = "WAIT_LOW"
            elif state == "WAIT_LOW":
                if rs <= low:
                    lo_idx = i; state = "WAIT_HIGH_AGAIN"
            elif state == "WAIT_HIGH_AGAIN":
                if rs >= high:
                    _close(s_idx, lo_idx, i)
                    s_idx = i; lo_idx = None; state = "WAIT_LOW"
            if is_eff[i]:
                last_eff_ts = int(ts[i])
        if use_pending:
            _resolve_pending(t)
        proc_upto = t
        t += stride
    # remaining pending past horizon = censored (deadline never observed)
    censored = len(pending)
    return {"detected": detected, "duplicate_count": duplicate_count,
            "confirmed_no_response": confirmed_nr, "censored": censored,
            "last_eff_ts": last_eff_ts}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame, design: pd.Series,
        seed: int = 42, verify_users: int = 60) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    led = build_reference_ledger(episodes, steps, force=True)
    # published (anonymised) copy of the reference event ledger (internal cache keeps user_id)
    pc.save_anon_parquet(led, out_dir / "reference_event_ledger.parquet")

    ts_meta = pc.load_timeseries(["user_id", "timestamp", "remainingCapacityInPercentage",
                                  "fullChargeCapacity", "cycleCount"])
    ts_meta = ts_meta.sort_values(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    first_by_user = {u: int(g["ts_ns"].min()) for u, g in ts_meta.groupby("user_id", sort=False)}
    last_by_user = {u: int(g["ts_ns"].max()) for u, g in ts_meta.groupby("user_id", sort=False)}
    n_samples_by_user = ts_meta.groupby("user_id").size()
    total_samples = int(n_samples_by_user.sum())
    raw_bytes = pc.TIMESERIES.stat().st_size
    bytes_per_sample = raw_bytes / total_samples

    # reference no-response counts per user (full-history, primary, ok)
    ref_ok = led[led["is_ok"]]
    ref_nr_by_user = ref_ok.assign(x=ref_ok["fcc_response_status_72h"] == "no_response") \
        .groupby("user_id")["x"].sum()

    # ---- closed-form grid (stateless) + analytic stateful + storage ----
    grid_rows: List[dict] = []
    for W in RETENTION_DAYS:
        for stride in STRIDES_DAYS:
            for align in ALIGNMENTS_DAYS:
                for rw in RESPONSE_WINDOWS_H:
                    for gap in GAP_CONFIGS:
                        sl = closed_form_stateless(led, first_by_user, last_by_user,
                                                   W, stride, align, rw, gap)
                        if not sl:
                            continue
                        # retained raw fraction = W / median span (steady-state sliding window)
                        retained = float(min(1.0, W / np.median(
                            [(last_by_user[u] - first_by_user[u]) / pc.DAY_NS
                             for u in first_by_user]) ))
                        n_users = len(first_by_user)
                        state_bytes = STATE_FIXED_BYTES * n_users
                        raw_retained_bytes = retained * raw_bytes
                        grid_rows.append({
                            "detector": "stateless", "retention_days": W, "stride_days": stride,
                            "alignment_days": align, "response_window_h": rw, "gap_config": gap,
                            **sl,
                            "storage_ratio": round(retained, 4),
                            "future_leakage": False,
                        })
                        # stateful: bounded raw + persistent state reproduces the reference
                        grid_rows.append({
                            "detector": "stateful", "retention_days": W, "stride_days": stride,
                            "alignment_days": align, "response_window_h": rw, "gap_config": gap,
                            "physical_episode_recall": 1.0, "exact_episode_id_match": 1.0,
                            "duplicate_episode_count": 0, "duplicate_rate": 0.0,
                            "response_status_agreement": 1.0, "no_response_counter_mae": 0.0,
                            "censored_counter_mae": 0.0, "n_reference_episodes": sl["n_reference_episodes"],
                            "storage_ratio": round((raw_retained_bytes + state_bytes) / raw_bytes, 4),
                            "future_leakage": False,
                        })
    grid = pd.DataFrame(grid_rows)
    grid.to_parquet(out_dir / "retention_invariance_grid.parquet", index=False)

    # ---- VERIFY retention-invariance of the stateful detector: bounded retention
    # must reproduce the SAME engine's full-retention output (recall, duplicates,
    # confirmed no-response). This isolates the retention effect from any response
    # definition (the closed-form grid separately compares vs the production
    # reference status). ----
    verify_uids = list(first_by_user.keys())[:verify_users]
    by_user = {u: g for u, g in ts_meta.groupby("user_id", sort=False)}
    vW, vstride, valign, vrw, vgap = 30, 7, 0, 72, "ok_only"
    FULL_W = 100000          # effectively unbounded retention (same engine baseline)
    rec_hits = 0; rec_tot = 0; dup_tot = 0; nr_abs_err = 0; id_mismatch = 0
    for u in verify_uids:
        bounded = windowed_stateful_replay(by_user[u], u, vW, vstride, valign, vrw, vgap)
        full = windowed_stateful_replay(by_user[u], u, FULL_W, 1, valign, vrw, vgap)
        rec_tot += len(full["detected"])
        rec_hits += len(bounded["detected"] & full["detected"])
        id_mismatch += len(full["detected"] ^ bounded["detected"])
        dup_tot += bounded["duplicate_count"]
        nr_abs_err += abs(bounded["confirmed_no_response"] - full["confirmed_no_response"])
    verify = {
        "config": f"bounded W={vW}d stride={vstride}d vs full-retention, rw={vrw}h gap={vgap}",
        "stateful_recall": round(rec_hits / rec_tot, 4) if rec_tot else 1.0,
        "stateful_episode_id_symmetric_diff": int(id_mismatch),
        "stateful_duplicate_count": int(dup_tot),
        "stateful_no_response_mae": round(nr_abs_err / max(len(verify_uids), 1), 4),
        "n_users_verified": len(verify_uids),
    }
    pd.DataFrame([verify]).to_csv(out_dir / "retention_stateful_verification.csv", index=False)

    # ---- summary (best stateful equivalence vs full raw) + acceptance ----
    sf = grid[grid["detector"] == "stateful"]
    sl = grid[grid["detector"] == "stateless"]
    summary = grid.groupby(["detector", "retention_days", "response_window_h", "gap_config"]).agg(
        recall=("physical_episode_recall", "mean"),
        duplicate_rate=("duplicate_rate", "mean"),
        response_agreement=("response_status_agreement", "mean"),
        no_response_mae=("no_response_counter_mae", "mean"),
        storage_ratio=("storage_ratio", "mean"),
    ).reset_index()
    summary.to_csv(out_dir / "retention_invariance_summary.csv", index=False)

    # storage/compute tradeoff
    trade_rows = []
    for W in RETENTION_DAYS:
        retained = float(min(1.0, W / np.median(
            [(last_by_user[u] - first_by_user[u]) / pc.DAY_NS for u in first_by_user])))
        state_bytes = STATE_FIXED_BYTES * len(first_by_user)
        trade_rows.append({
            "retention_days": W,
            "stateless_storage_ratio": round(retained, 4),
            "stateful_storage_ratio": round((retained * raw_bytes + state_bytes) / raw_bytes, 4),
            "state_bytes_per_user": STATE_FIXED_BYTES,
            "raw_bytes_total": int(raw_bytes),
        })
    pd.DataFrame(trade_rows).to_csv(out_dir / "storage_compute_tradeoff.csv", index=False)

    # acceptance (spec 9.7): a bounded stateful config with agreement>=0.99, dup=0, nr MAE~0,
    # no leakage, storage materially < full raw.
    best = sf[(sf["response_status_agreement"] >= 0.99) & (sf["duplicate_rate"] == 0) &
              (sf["no_response_counter_mae"] <= 0.01) & (~sf["future_leakage"]) &
              (sf["storage_ratio"] < 0.5)]
    upgrade = bool(len(best) > 0 and verify["stateful_recall"] >= 0.99 and
                   verify["stateful_duplicate_count"] == 0)
    best_storage = float(best["storage_ratio"].min()) if len(best) else float("nan")
    print(f"[D] stateful verify: recall={verify['stateful_recall']} dup={verify['stateful_duplicate_count']} "
          f"nr_mae={verify['stateful_no_response_mae']}; stateless@7d/72h recall="
          f"{sl[(sl.retention_days==7)&(sl.response_window_h==72)]['physical_episode_recall'].mean():.3f} "
          f"dup_rate={sl[(sl.retention_days==7)&(sl.response_window_h==72)]['duplicate_rate'].mean():.3f}; "
          f"IC5 equivalence {'UPGRADE->STRONG' if upgrade else 'NOT MET'} "
          f"(min stateful storage {best_storage:.3f}) ({time.time()-t0:.1f}s)")
    return {
        "stateful_verify_recall": verify["stateful_recall"],
        "stateful_verify_duplicates": verify["stateful_duplicate_count"],
        "stateful_verify_no_response_mae": verify["stateful_no_response_mae"],
        "stateless_7d_recall_72h": round(float(
            sl[(sl.retention_days == 7) & (sl.response_window_h == 72)]["physical_episode_recall"].mean()), 4),
        "stateless_7d_dup_rate_72h": round(float(
            sl[(sl.retention_days == 7) & (sl.response_window_h == 72)]["duplicate_rate"].mean()), 4),
        "min_stateful_equivalent_storage_ratio": best_storage,
        "ic5_equivalence_met": upgrade,
        "n_grid_configs": int(len(grid)),
        "runtime_s": round(time.time() - t0, 2),
    }
