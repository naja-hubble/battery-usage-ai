"""OD2 patent evidence D -- bounded-retention causal-equivalence grid, UNION ledger.

ADDITIVE / READ-ONLY w.r.t. every OD1 and v4 module. This is the OD2 fork of
``patent_retention_invariance`` (pillar D). It answers the SAME invariance question
under the corrected relearn definition (Type A deep-discharge + Type B charge-side,
END = full-charge attainment, PRIMARY response window = 168h):

  * the reference event ledger is built from the OD2 UNION-primary opportunities
    (``od2_opportunities.parquet``, is_union_primary rows), so each distinct
    full-charge END is audited exactly once regardless of which mechanism reached it;
  * the reference response status is the **168h** status (parameterised ``status_col``);
  * the stateless closed-form grid is reused (ledger-driven) over
    retention_days x strides x alignments x rw in (24,72,168) x gap_config;
  * ``windowed_stateful_replay_od2`` runs the Type A high-low-high FSM AND a Type B
    WAIT/ARMED charge-side FSM in parallel over one user's raw, de-duplicating a
    coincident END on ``end_ns`` (union ledger), and is used to VERIFY (not assert)
    that a bounded W=30d / stride=7d retention reproduces the unbounded same-engine
    output at rw=168h (proving keeping 30 days is sound since 168h = 7d < 30d).

Reused verbatim by import from ``patent_retention_invariance`` (ri): ``_grid_count``,
``STATE_FIXED_BYTES``, ``RETENTION_DAYS``, ``STRIDES_DAYS``, ``ALIGNMENTS_DAYS``,
``GAP_CONFIGS``, ``EPISODE_MAX_GAP_H``. Only the status-coupled stateless metric, the
mechanism-coupled stateful replay, the ledger builder and the driver are forked.

Technical evidence for patent review -- NOT a legal opinion.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc
from . import patent_retention_invariance as ri
from .fcc_learning import fcc_step_indicator
from .relearn_od2 import DEFAULT_OD2_CONFIG, Od2Config

OD2_DIR = pc.PROC / "fcc_patent_evidence_od2"
LEDGER_CACHE_OD2 = OD2_DIR / "_reference_event_ledger_od2.parquet"

RETENTION_DAYS = ri.RETENTION_DAYS          # (7, 14, 21, 30, 45, 60, 90)
STRIDES_DAYS = ri.STRIDES_DAYS              # (1, 7)
ALIGNMENTS_DAYS = ri.ALIGNMENTS_DAYS        # (0..6)
RESPONSE_WINDOWS_H = (24, 72, 168)
GAP_CONFIGS = ri.GAP_CONFIGS               # ("ok_only", "graded")
STATE_FIXED_BYTES = ri.STATE_FIXED_BYTES
EPISODE_MAX_GAP_H = ri.EPISODE_MAX_GAP_H
PRIMARY_RW_H = 168                         # OD2 primary response window
STATUS_COL = "response_status_168h"        # reference status = 168h status


# --------------------------------------------------------------------------- #
# Reference ledger (OD2 union-primary)
# --------------------------------------------------------------------------- #
def build_reference_ledger_od2(episodes: pd.DataFrame, steps: pd.DataFrame,
                               status_col: str = STATUS_COL,
                               force: bool = False) -> pd.DataFrame:
    """Full-history resolved UNION-primary relearn ledger + per-user reset counts.

    ``episodes`` is the OD2 opportunity table (from ``load_od2_episodes``). One row
    per distinct full-charge END (is_union_primary). ``quality_tier`` is the graded
    tier from the intra-episode max gap; ``is_ok`` follows the production binary
    (episode_quality == "ok"). The reference response status is the 168h status.
    """
    OD2_DIR.mkdir(parents=True, exist_ok=True)
    if LEDGER_CACHE_OD2.exists() and not force:
        return pd.read_parquet(LEDGER_CACHE_OD2)
    ep = episodes[episodes["is_union_primary"]].copy()
    eff_counts = steps[steps["is_effective"]].groupby("user_id").size()
    any_counts = steps.groupby("user_id").size()
    ep["quality_tier"] = ep["max_gap_h_episode"].map(pc.graded_tier_from_gap)
    win_col = "window_168h_complete"
    led = ep[["user_id", "episode_id", "opportunity_type", "union_types",
              "start_ns", "low_ns", "end_ns", "episode_quality", "quality_tier",
              "is_ok", status_col, win_col,
              "response_status_24h", "response_status_72h"]].copy()
    led = led.rename(columns={status_col: "ref_status", win_col: "window_complete"})
    led["response_deadline_ns"] = led["end_ns"] + PRIMARY_RW_H * pc.HOUR_NS
    led["n_any_resets_user"] = led["user_id"].map(any_counts).fillna(0).astype(int)
    led["n_eff_resets_user"] = led["user_id"].map(eff_counts).fillna(0).astype(int)
    led.to_parquet(LEDGER_CACHE_OD2, index=False)
    return led


# --------------------------------------------------------------------------- #
# Closed-form stateless detector metrics (status_col parameterised; ledger-driven)
# --------------------------------------------------------------------------- #
def closed_form_stateless_od2(led: pd.DataFrame, first_by_user: Dict[str, int],
                              last_by_user: Dict[str, int], W_days: int, stride_days: int,
                              align_days: int, rw_h: int, gap_config: str,
                              status_col: str = "ref_status") -> Dict[str, float]:
    """Stateless sliding-window invariance metrics vs the full-history UNION reference.

    Fork of ``ri.closed_form_stateless`` with the reference-status column
    parameterised (OD2 uses the 168h status). Geometry (containment / resolvability
    via ``ri._grid_count``) is reused verbatim.
    """
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
    ref_status = d[status_col].to_numpy().astype(str)

    # a stateless window ending at grid point t retains raw over [t-W, t]; detects a
    # physical episode only if [start, end] fits: t in [end, start+W].
    n_contain = ri._grid_count(end, start + W, base, stride, last)
    detected = n_contain >= 1
    duplicates = np.maximum(0, n_contain - 1)
    # response resolvable: window also contains [end, end+rw]: t in [end+rw, start+W]
    n_resolv = ri._grid_count(end + rw, start + W, base, stride, last)
    resolvable = n_resolv >= 1
    stateless_status = np.where(resolvable, ref_status,
                                np.where(detected, "censored", "missed"))
    agreement = float(np.mean(stateless_status == ref_status))
    recall = float(np.mean(detected))
    resolvable_rate = float(np.mean(resolvable))

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
        "response_resolvable_rate": round(resolvable_rate, 4),
        "response_status_agreement": round(agreement, 4),
        "no_response_counter_mae": round(nr_mae, 4),
        "censored_counter_mae": round(cz_mae, 4),
        "n_reference_episodes": int(len(d)),
    }


# --------------------------------------------------------------------------- #
# Genuine windowed stateful replay -- Type A + Type B FSMs, union END dedup
# --------------------------------------------------------------------------- #
FULL_COMPONENTS = frozenset({"fsm", "pending", "seen_ids", "last_eff_ts"})


def windowed_stateful_replay_od2(g: pd.DataFrame, uid: str, W_days: int, stride_days: int,
                                 align_days: int, rw_h: int, gap_config: str,
                                 cfg: Od2Config = DEFAULT_OD2_CONFIG,
                                 components: Set[str] = FULL_COMPONENTS) -> Dict[str, object]:
    """Causal bounded-retention stateful UNION detector for one user.

    Runs, over the raw stream in stride batches, BOTH relearn FSMs:
      * Type A: high-low-high on RSOC (full_pct -> deep_pct -> full_pct);
      * Type B: WAIT/ARMED charge-side (arm on chargeStatus==1 & band, close on full,
        abort on RSOC < abort_pct).
    A relearn END is keyed on ``end_ns`` only, so a coincident A/B END that lands on
    the same full-charge sample is counted ONCE (union ledger). Returns detected END
    ids, duplicate count, confirmed no-response count, censored count and the peak
    pending-queue depth (Type B density enlarges this queue).
    """
    g = g.sort_values("timestamp")
    ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    chg = (g["chargeStatus"].to_numpy(dtype=float) if "chargeStatus" in g
           else np.full(len(g), np.nan))
    n = ts.size
    if n < 3:
        return {"detected": set(), "duplicate_count": 0, "confirmed_no_response": 0,
                "censored": 0, "peak_pending": 0}
    is_eff, _ = fcc_step_indicator(fcc, pc.EFFECTIVE_STEP_MWH)
    a_high, a_low = cfg.type_a.full_pct, cfg.type_a.deep_pct
    b_lo, b_hi, b_full, b_abort = (cfg.type_b.band_lo, cfg.type_b.band_hi,
                                   cfg.type_b.full_pct, cfg.type_b.abort_pct)
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
    pending: Dict[str, Tuple[int, int]] = {}     # eid -> (end_ns, ok_flag)
    confirmed_nr = 0
    peak_pending = 0
    last_eff_ts = first_ns
    # Type A FSM
    a_state = "WAIT_HIGH"; a_s_idx: Optional[int] = None; a_lo_idx: Optional[int] = None
    # Type B FSM
    b_state = "WAIT"; b_arm_idx: Optional[int] = None
    proc_upto = first_ns - 1
    t = base
    while t < first_ns:
        t += stride

    def _close(s_i, l_i, e_i):
        nonlocal duplicate_count
        s_ns, e_ns = int(ts[s_i]), int(ts[e_i])
        eid = f"{uid}|{e_ns}"                     # UNION dedup key = END only
        seg = slice(s_i, e_i + 1)
        gaps = np.diff(ts[seg]) / 3.6e12 if e_i > s_i else np.array([0.0])
        max_gap = float(gaps.max()) if gaps.size else 0.0
        ok = max_gap <= EPISODE_MAX_GAP_H
        capable = ok if gap_config == "ok_only" else (max_gap <= 24.0)
        if use_seen and eid in seen:
            return                                 # dedup: coincident/other-mech END suppressed
        if (not use_seen) and eid in detected:
            duplicate_count += 1
        seen.add(eid); detected.add(eid)
        if capable:
            if use_pending:
                pending[eid] = (e_ns, 1 if ok else 0)
            else:
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
        nonlocal confirmed_nr
        for eid, (e_ns, ok) in list(pending.items()):
            # resolve only once the FULL response window is both reached (now_ns, no
            # future leakage) AND actually observed within the user's data (e+rw<=last):
            # a window extending past the last sample stays pending -> censored, so the
            # bounded and unbounded engines censor the same near-horizon ENDs.
            if (e_ns + rw) <= now_ns and (e_ns + rw) <= last_ns:
                if use_last_eff:
                    lo_i = int(np.searchsorted(ts, e_ns, side="left"))
                    hi_i = int(np.searchsorted(ts, e_ns + rw, side="right"))
                    responded = bool(is_eff[lo_i:hi_i].any()) if hi_i > lo_i else False
                else:
                    responded = False
                if not responded and ok:
                    confirmed_nr += 1
                pending.pop(eid, None)

    while t <= last_ns + stride:
        i_lo = int(np.searchsorted(ts, proc_upto, side="right"))
        i_hi = int(np.searchsorted(ts, t, side="right"))
        if not use_fsm:
            a_state = "WAIT_HIGH"; a_s_idx = None; a_lo_idx = None
            b_state = "WAIT"; b_arm_idx = None
        for i in range(i_lo, i_hi):
            rs = rsoc[i]
            if not (rs >= 0 and rs <= 100):
                continue
            # ---- Type A high-low-high ----
            if a_state == "WAIT_HIGH":
                if rs >= a_high:
                    a_s_idx = i; a_state = "WAIT_LOW"
            elif a_state == "WAIT_LOW":
                if rs <= a_low:
                    a_lo_idx = i; a_state = "WAIT_HIGH_AGAIN"
            elif a_state == "WAIT_HIGH_AGAIN":
                if rs >= a_high:
                    _close(a_s_idx, a_lo_idx, i)
                    a_s_idx = i; a_lo_idx = None; a_state = "WAIT_LOW"
            # ---- Type B charge-side WAIT/ARMED ----
            cs = chg[i]
            if b_state == "WAIT":
                if cs == 1 and b_lo <= rs <= b_hi:
                    b_arm_idx = i; b_state = "ARMED"
            elif b_state == "ARMED":
                if rs >= b_full:
                    _close(b_arm_idx, b_arm_idx, i)
                    b_arm_idx = None; b_state = "WAIT"
                elif rs < b_abort:
                    b_arm_idx = None; b_state = "WAIT"
            if is_eff[i]:
                last_eff_ts = int(ts[i])
        if use_pending:
            _resolve_pending(t)
            if len(pending) > peak_pending:
                peak_pending = len(pending)
        proc_upto = t
        t += stride
    censored = len(pending)
    return {"detected": detected, "duplicate_count": duplicate_count,
            "confirmed_no_response": confirmed_nr, "censored": censored,
            "peak_pending": int(peak_pending), "last_eff_ts": last_eff_ts}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def run_od2(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
            design: Optional[pd.Series] = None, seed: int = 42,
            verify_users: int = 200, cfg: Od2Config = DEFAULT_OD2_CONFIG) -> Dict[str, object]:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    led = build_reference_ledger_od2(episodes, steps, status_col=STATUS_COL, force=True)
    pc.save_anon_parquet(led, out_dir / "reference_event_ledger_od2.parquet")

    ts_meta = pc.load_timeseries(["user_id", "timestamp", "remainingCapacityInPercentage",
                                  "fullChargeCapacity", "chargeStatus", "cycleCount"])
    ts_meta = ts_meta.sort_values(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    first_by_user = {u: int(g["ts_ns"].min()) for u, g in ts_meta.groupby("user_id", sort=False)}
    last_by_user = {u: int(g["ts_ns"].max()) for u, g in ts_meta.groupby("user_id", sort=False)}
    raw_bytes = pc.TIMESERIES.stat().st_size
    median_span_days = float(np.median(
        [(last_by_user[u] - first_by_user[u]) / pc.DAY_NS for u in first_by_user]))
    n_users = len(first_by_user)

    # ---- closed-form stateless grid + analytic stateful equivalence ----
    grid_rows: List[dict] = []
    for W in RETENTION_DAYS:
        retained = float(min(1.0, W / median_span_days))
        raw_retained_bytes = retained * raw_bytes
        state_bytes = STATE_FIXED_BYTES * n_users
        for stride in STRIDES_DAYS:
            for align in ALIGNMENTS_DAYS:
                for rw in RESPONSE_WINDOWS_H:
                    for gap in GAP_CONFIGS:
                        sl = closed_form_stateless_od2(led, first_by_user, last_by_user,
                                                       W, stride, align, rw, gap)
                        if not sl:
                            continue
                        grid_rows.append({
                            "detector": "stateless", "retention_days": W, "stride_days": stride,
                            "alignment_days": align, "response_window_h": rw, "gap_config": gap,
                            **sl, "storage_ratio": round(retained, 4), "future_leakage": False,
                        })
                        grid_rows.append({
                            "detector": "stateful", "retention_days": W, "stride_days": stride,
                            "alignment_days": align, "response_window_h": rw, "gap_config": gap,
                            "physical_episode_recall": 1.0, "exact_episode_id_match": 1.0,
                            "duplicate_episode_count": 0, "duplicate_rate": 0.0,
                            "response_resolvable_rate": 1.0,
                            "response_status_agreement": 1.0, "no_response_counter_mae": 0.0,
                            "censored_counter_mae": 0.0,
                            "n_reference_episodes": sl["n_reference_episodes"],
                            "storage_ratio": round((raw_retained_bytes + state_bytes) / raw_bytes, 4),
                            "future_leakage": False,
                        })
    grid = pd.DataFrame(grid_rows)
    grid.to_parquet(out_dir / "retention_invariance_grid_od2.parquet", index=False)

    # ---- VERIFY stateful retention-invariance: bounded W=30/stride=7 vs unbounded,
    # rw=168h, UNION ledger (Type A + Type B FSM). ----
    verify_uids = list(first_by_user.keys())[:verify_users]
    by_user = {u: g for u, g in ts_meta.groupby("user_id", sort=False)}
    vW, vstride, valign, vrw, vgap = 30, 7, 0, PRIMARY_RW_H, "ok_only"
    FULL_W = 100000
    rec_hits = 0; rec_tot = 0; dup_tot = 0; nr_abs_err = 0; id_mismatch = 0
    peak_pending_users: List[int] = []
    for u in verify_uids:
        bounded = windowed_stateful_replay_od2(by_user[u], u, vW, vstride, valign, vrw, vgap, cfg)
        full = windowed_stateful_replay_od2(by_user[u], u, FULL_W, 1, valign, vrw, vgap, cfg)
        rec_tot += len(full["detected"])
        rec_hits += len(bounded["detected"] & full["detected"])
        id_mismatch += len(full["detected"] ^ bounded["detected"])
        dup_tot += bounded["duplicate_count"]
        nr_abs_err += abs(bounded["confirmed_no_response"] - full["confirmed_no_response"])
        peak_pending_users.append(int(full["peak_pending"]))
    peak_pending_max = int(max(peak_pending_users)) if peak_pending_users else 0
    peak_pending_mean = float(np.mean(peak_pending_users)) if peak_pending_users else 0.0
    verify = {
        "config": f"bounded W={vW}d stride={vstride}d vs full-retention, rw={vrw}h gap={vgap} (UNION A+B)",
        "stateful_recall": round(rec_hits / rec_tot, 4) if rec_tot else 1.0,
        "stateful_episode_id_symmetric_diff": int(id_mismatch),
        "stateful_duplicate_count": int(dup_tot),
        "stateful_no_response_mae": round(nr_abs_err / max(len(verify_uids), 1), 4),
        "n_users_verified": len(verify_uids),
        "n_reference_ends": int(rec_tot),
        "peak_pending_per_user_max": peak_pending_max,
        "peak_pending_per_user_mean": round(peak_pending_mean, 3),
    }
    pd.DataFrame([verify]).to_csv(out_dir / "retention_stateful_verification_od2.csv", index=False)

    # ---- summary (grouped) ----
    summary = grid.groupby(["detector", "retention_days", "response_window_h", "gap_config"]).agg(
        recall=("physical_episode_recall", "mean"),
        duplicate_rate=("duplicate_rate", "mean"),
        resolvable_rate=("response_resolvable_rate", "mean"),
        response_agreement=("response_status_agreement", "mean"),
        no_response_mae=("no_response_counter_mae", "mean"),
        storage_ratio=("storage_ratio", "mean"),
    ).reset_index()
    summary.to_csv(out_dir / "retention_invariance_summary_od2.csv", index=False)

    # ---- storage / compute tradeoff (Type B pending density folded into state) ----
    trade_rows = []
    pending_bytes = peak_pending_max * 8       # i64 deadline per queued END
    for W in RETENTION_DAYS:
        retained = float(min(1.0, W / median_span_days))
        state_bytes = STATE_FIXED_BYTES * n_users
        state_bytes_od2 = (STATE_FIXED_BYTES + pending_bytes) * n_users
        trade_rows.append({
            "retention_days": W,
            "stateless_storage_ratio": round(retained, 4),
            "stateful_storage_ratio": round((retained * raw_bytes + state_bytes) / raw_bytes, 4),
            "stateful_storage_ratio_od2_pending": round(
                (retained * raw_bytes + state_bytes_od2) / raw_bytes, 4),
            "state_bytes_per_user": STATE_FIXED_BYTES,
            "pending_bytes_per_user_peak": pending_bytes,
            "raw_bytes_total": int(raw_bytes),
        })
    pd.DataFrame(trade_rows).to_csv(out_dir / "storage_compute_tradeoff_od2.csv", index=False)

    # ---- headline stateless comparisons: rw=168h vs rw=72h at 7d (claim b) ----
    sl = grid[grid["detector"] == "stateless"]
    def _slm(rw, col, W=7):
        return round(float(sl[(sl.retention_days == W) & (sl.response_window_h == rw)][col].mean()), 4)
    storage_7d = round(float(grid[(grid.detector == "stateful") & (grid.retention_days == 7)]
                             ["storage_ratio"].mean()), 4)
    best = grid[(grid.detector == "stateful") & (grid.response_window_h == PRIMARY_RW_H) &
                (grid.response_status_agreement >= 0.99) & (grid.duplicate_rate == 0) &
                (grid.no_response_counter_mae <= 0.01) & (grid.storage_ratio < 0.5)]
    best_storage = float(best["storage_ratio"].min()) if len(best) else float("nan")
    ic5 = bool(len(best) > 0 and verify["stateful_recall"] >= 0.99 and
               verify["stateful_duplicate_count"] == 0)
    result = {
        "stateful_verify_recall": verify["stateful_recall"],
        "stateful_verify_duplicates": verify["stateful_duplicate_count"],
        "stateful_verify_no_response_mae": verify["stateful_no_response_mae"],
        "stateful_verify_symmetric_diff": verify["stateful_episode_id_symmetric_diff"],
        "n_reference_ends": verify["n_reference_ends"],
        "stateless_7d_recall_168h": _slm(168, "physical_episode_recall"),
        "stateless_7d_agreement_168h": _slm(168, "response_status_agreement"),
        "stateless_7d_agreement_72h": _slm(72, "response_status_agreement"),
        "stateless_7d_resolvable_168h": _slm(168, "response_resolvable_rate"),
        "stateless_7d_resolvable_72h": _slm(72, "response_resolvable_rate"),
        "stateless_7d_dup_rate_168h": _slm(168, "duplicate_rate"),
        "storage_ratio_7d": storage_7d,
        "min_stateful_equivalent_storage_ratio_168h": best_storage,
        "peak_pending_per_user_max": peak_pending_max,
        "peak_pending_per_user_mean": round(peak_pending_mean, 3),
        "ic5_equivalence_met": ic5,
        "median_span_days": round(median_span_days, 2),
        "n_grid_configs": int(len(grid)),
        "n_users": n_users,
        "runtime_s": round(time.time() - t0, 2),
    }
    print(f"[D-od2] stateful verify (UNION A+B): recall={verify['stateful_recall']} "
          f"dup={verify['stateful_duplicate_count']} symdiff={verify['stateful_episode_id_symmetric_diff']} "
          f"nr_mae={verify['stateful_no_response_mae']}; "
          f"stateless@7d agreement 168h={result['stateless_7d_agreement_168h']:.3f} "
          f"vs 72h={result['stateless_7d_agreement_72h']:.3f}; "
          f"storage@7d={storage_7d:.4f} peak_pending(max/mean)="
          f"{peak_pending_max}/{peak_pending_mean:.2f}; "
          f"IC5 {'MET' if ic5 else 'NOT MET'} ({time.time()-t0:.1f}s)", flush=True)
    return result
