"""Patent evidence C2 -- dual-track asymmetric-reset ablation (D0..D5).

ADDITIVE. Replays the SAME chronological event stream (FCC steps + qualified
episode completions + 72h no-response deadlines) under six FCC state semantics
and measures the direct state-machine effects -- not only proxy labels (spec 7.2).

  D0 any-change only        single track; ANY integer step resets the evidence.
  D1 effective-change only  single track; only an effective (>=50 mWh) step resets;
                            micro steps are invisible (cannot label micro-wobble).
  D2 dual, symmetric on any both tracks reset on ANY step -> a micro step ERASES
                            pending/no-response evidence.
  D3 dual, symmetric on eff both tracks reset only on an effective step; micro is
                            ignored and not recorded -> evidence preserved but
                            micro-wobble is indistinguishable from a hard freeze.
  D4 PROPOSED asymmetric    micro step resets the ANY track ONLY and is recorded;
                            effective state / pending episodes / no-response
                            evidence are preserved (== production online_step_state).
  D5 adaptive asymmetric    D4 with a per-user adaptive effective threshold.

Event ordering at equal timestamps is deterministic: completion < reset < deadline
(mirrors ``online_step_state``). Acceptance (spec 7.4): IC2 asymmetric reset is
downgraded unless D4 measurably (a) preserves unresolved no-response/pending
evidence that a symmetric-on-any reset erases, or (b) reduces hard-action
ambiguity (Gauge Core -> Soft via micro-wobble) vs the effective-only / symmetric
alternatives.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc

# event priorities at equal ts (mirror online_step_state)
_PRIO_COMPLETE, _PRIO_RESET, _PRIO_DEADLINE = 0, 1, 2

FW_CONFIRMED_NR_MIN = 3        # recurring opportunity + no-response -> FW escalation
FROZEN_DAYS = 90.0            # effective-track staleness for a gauge call (production gate)
THRESHOLD_SWEEP_MWH = (20.0, 30.0, 50.0, 75.0, 100.0)


@dataclass
class Policy:
    name: str
    erase_evidence_on_micro: bool      # micro step clears pending/no-response evidence
    record_micro: bool                 # micro tracked -> enables soft-calibration label
    adaptive_threshold: bool = False


POLICIES = [
    Policy("D0_any_only", erase_evidence_on_micro=True, record_micro=False),
    Policy("D1_effective_only", erase_evidence_on_micro=False, record_micro=False),
    Policy("D2_dual_symmetric_any", erase_evidence_on_micro=True, record_micro=True),
    Policy("D3_dual_symmetric_effective", erase_evidence_on_micro=False, record_micro=False),
    Policy("D4_dual_asymmetric_proposed", erase_evidence_on_micro=False, record_micro=True),
    Policy("D5_adaptive_asymmetric", erase_evidence_on_micro=False, record_micro=True,
           adaptive_threshold=True),
]


def build_user_events(end_list: List[Tuple[int, str, bool]],
                      step_list: List[Tuple[int, float]],
                      last_ns: int) -> List[Tuple[int, int, str, object]]:
    """Chronological event list for one user.

    end_list: (end_ns, quality_tier, observed_deadline) per capable primary episode.
    step_list: (ts_ns, abs_delta) per any-change FCC step.
    """
    events: List[Tuple[int, int, str, object]] = []
    win = pc.PRIMARY_WINDOW_H * pc.HOUR_NS
    for (end_ns, tier, _obs) in end_list:
        events.append((end_ns, _PRIO_COMPLETE, "complete", tier))
        if tier in pc.NO_RESPONSE_CAPABLE and (end_ns + win) <= last_ns:
            events.append((end_ns + win, _PRIO_DEADLINE, "deadline", tier))
    for (ts, delta) in step_list:
        events.append((ts, _PRIO_RESET, "step", float(delta)))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def replay(events, eff_threshold: float, policy: Policy, last_ns: int,
           first_ns: int) -> Dict[str, object]:
    """Run one user's event stream under one policy. Returns final-state counts +
    erased-evidence events."""
    pending: Dict[int, str] = {}          # use event index as pseudo-eid
    confirmed_nr = 0                      # confirmed high/medium-quality no-response
    opp_capable = 0                      # capable opportunities since last evidence reset
    n_micro = 0
    last_eff_ts = first_ns
    n_eff_resets = 0
    n_micro_resets = 0                   # micro steps that performed an evidence reset
    erased_pending = 0
    erased_nr = 0
    micro_erase_events: List[dict] = []
    eid = 0

    def _reset_evidence():
        nonlocal pending, confirmed_nr, opp_capable, n_micro
        pending = {}
        confirmed_nr = 0
        opp_capable = 0
        n_micro = 0

    for (ts, prio, kind, payload) in events:
        if kind == "complete":
            tier = payload
            if tier in pc.NO_RESPONSE_CAPABLE:
                eid += 1
                pending[eid] = tier
                opp_capable += 1
        elif kind == "deadline":
            # resolve the *oldest still-pending* capable episode as confirmed no-response
            if pending:
                k = next(iter(pending))
                pending.pop(k, None)
                confirmed_nr += 1
        elif kind == "step":
            delta = payload
            is_eff = delta >= eff_threshold
            if is_eff:
                last_eff_ts = ts
                n_eff_resets += 1
                _reset_evidence()
            else:
                if policy.record_micro:
                    n_micro += 1
                if policy.erase_evidence_on_micro:
                    if pending or confirmed_nr > 0:
                        erased_pending += len(pending)
                        erased_nr += confirmed_nr
                        micro_erase_events.append(
                            {"ts_ns": ts, "abs_delta_mWh": delta,
                             "pending_erased": len(pending), "no_response_erased": confirmed_nr})
                    last_eff_ts = ts
                    n_micro_resets += 1
                    _reset_evidence()

    days_since_eff = (last_ns - last_eff_ts) / pc.DAY_NS
    frozen = days_since_eff >= FROZEN_DAYS
    micro_wobble_only = bool(policy.record_micro and n_micro > 0 and frozen)
    # derived action label (mirrors production triage logic, simplified)
    if confirmed_nr >= FW_CONFIRMED_NR_MIN:
        label = "FW_CHECK"
        hard = True
    elif frozen and opp_capable < FW_CONFIRMED_NR_MIN:
        if micro_wobble_only:
            label = "GAUGE_SOFT"; hard = False
        else:
            label = "GAUGE_RESET_CORE"; hard = True
    else:
        label = "NORMAL"; hard = False
    return {
        "pending_at_end": len(pending), "confirmed_no_response": confirmed_nr,
        "opp_capable": opp_capable, "n_micro": n_micro,
        "n_eff_resets": n_eff_resets, "n_micro_resets": n_micro_resets,
        "n_state_transitions": n_eff_resets + n_micro_resets,
        "erased_pending": erased_pending, "erased_no_response": erased_nr,
        "micro_wobble_only": micro_wobble_only, "label": label, "hard_action": hard,
        "frozen": bool(frozen), "_erase_events": micro_erase_events,
    }


def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
        design: pd.Series, seed: int = 42) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # per-user last sample (frozen + deadline-observed)
    ts_meta = pc.load_timeseries(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    span = {uid: (int(g["ts_ns"].min()), int(g["ts_ns"].max()))
            for uid, g in ts_meta.groupby("user_id", sort=False)}

    # capable primary-band episode ends (tier from graded quality_tier)
    ep = episodes[episodes["threshold_name"] == pc.PRIMARY_THRESHOLD]
    ends_by_user: Dict[str, List[Tuple[int, str, bool]]] = {}
    for uid, g in ep.groupby("user_id", sort=False):
        ends_by_user[uid] = [(int(r.end_ns), str(r.quality_tier), bool(r.window_72h_complete))
                             for r in g.itertuples()]
    # any-change steps per user
    steps_by_user: Dict[str, List[Tuple[int, float]]] = {}
    for uid, g in steps.sort_values("ts_ns").groupby("user_id", sort=False):
        steps_by_user[uid] = list(zip(g["ts_ns"].to_numpy(dtype=np.int64).tolist(),
                                      g["abs_step"].to_numpy(dtype=float).tolist()))
    quant = steps.groupby("user_id")["abs_step"].min()
    responders = set(steps.loc[steps["is_effective"], "user_id"].unique())

    all_users = sorted(set(ends_by_user) | set(steps_by_user) | set(span))
    # per-policy aggregates
    agg: Dict[str, Dict[str, float]] = {p.name: {} for p in POLICIES}
    per_user_label: Dict[str, Dict[str, str]] = {p.name: {} for p in POLICIES}
    erase_rows: List[dict] = []

    for p in POLICIES:
        tot = {"pending_at_end": 0, "confirmed_no_response": 0, "erased_pending": 0,
               "erased_no_response": 0, "n_state_transitions": 0, "hard_action": 0,
               "fw_like": 0, "gauge_soft": 0, "gauge_reset_core": 0,
               "false_hard_reset_on_responder": 0, "micro_erase_events": 0,
               "users_evidence_erased": 0}
        for uid in all_users:
            first_ns, last_ns = span.get(uid, (0, 0))
            ends = ends_by_user.get(uid, [])
            stp = steps_by_user.get(uid, [])
            events = build_user_events(ends, stp, last_ns)
            thr = max(2.0 * float(quant.get(uid, 10.0)),
                      0.001 * float(design.get(uid, np.nan)) if np.isfinite(design.get(uid, np.nan)) else 0.0,
                      20.0) if p.adaptive_threshold else pc.EFFECTIVE_STEP_MWH
            r = replay(events, thr, p, last_ns, first_ns)
            tot["pending_at_end"] += r["pending_at_end"]
            tot["confirmed_no_response"] += r["confirmed_no_response"]
            tot["erased_pending"] += r["erased_pending"]
            tot["erased_no_response"] += r["erased_no_response"]
            tot["n_state_transitions"] += r["n_state_transitions"]
            tot["hard_action"] += int(r["hard_action"])
            tot["fw_like"] += int(r["label"] == "FW_CHECK")
            tot["gauge_soft"] += int(r["label"] == "GAUGE_SOFT")
            tot["gauge_reset_core"] += int(r["label"] == "GAUGE_RESET_CORE")
            if r["hard_action"] and uid in responders:
                tot["false_hard_reset_on_responder"] += 1
            if r["_erase_events"]:
                tot["micro_erase_events"] += len(r["_erase_events"])
                tot["users_evidence_erased"] += 1
                for e in r["_erase_events"]:
                    erase_rows.append({"user_id": uid, "policy": p.name, **e})
            per_user_label[p.name][uid] = r["label"]
        agg[p.name] = tot

    abl = pd.DataFrame([{"policy": k, **v} for k, v in agg.items()])
    abl.to_csv(out_dir / "dual_track_reset_ablation.csv", index=False)
    pc.save_anon_parquet(pd.DataFrame(erase_rows) if erase_rows else
                         pd.DataFrame(columns=["user_id", "policy", "ts_ns", "abs_delta_mWh",
                                               "pending_erased", "no_response_erased"]),
                         out_dir / "dual_track_erased_evidence_events.parquet")

    # ---- label transitions: D4 (proposed) vs each alternative ----
    base = per_user_label["D4_dual_asymmetric_proposed"]
    trans_rows: List[dict] = []
    for p in POLICIES:
        if p.name == "D4_dual_asymmetric_proposed":
            continue
        other = per_user_label[p.name]
        fw_to_other = sum(1 for u in base if base[u] == "FW_CHECK" and other.get(u) != "FW_CHECK")
        gaugecore_to_soft = sum(1 for u in base
                                if other.get(u) == "GAUGE_RESET_CORE" and base[u] == "GAUGE_SOFT")
        soft_to_hard = sum(1 for u in base
                           if base[u] == "GAUGE_SOFT" and other.get(u) in ("GAUGE_RESET_CORE", "FW_CHECK"))
        trans_rows.append({
            "from_policy": p.name, "to_policy": "D4_dual_asymmetric_proposed",
            "fw_evidence_lost_under_other": fw_to_other,
            "hardreset_avoided_by_d4_microwobble": gaugecore_to_soft,
            "soft_calls_only_d4_makes": soft_to_hard,
        })
    pd.DataFrame(trans_rows).to_csv(out_dir / "dual_track_label_transitions.csv", index=False)

    # ---- label stability under effective-threshold sweep (D4 policy) ----
    sweep_labels: Dict[float, Dict[str, str]] = {}
    p4 = Policy("sweep", erase_evidence_on_micro=False, record_micro=True)
    for thr in THRESHOLD_SWEEP_MWH:
        lab = {}
        for uid in all_users:
            first_ns, last_ns = span.get(uid, (0, 0))
            events = build_user_events(ends_by_user.get(uid, []), steps_by_user.get(uid, []), last_ns)
            lab[uid] = replay(events, thr, p4, last_ns, first_ns)["label"]
        sweep_labels[thr] = lab
    ref = sweep_labels[50.0]
    actionable = {"FW_CHECK", "GAUGE_RESET_CORE", "GAUGE_SOFT"}
    sweep_rows: List[dict] = []
    for thr in THRESHOLD_SWEEP_MWH:
        lab = sweep_labels[thr]
        a = {u for u in lab if lab[u] in actionable}
        b = {u for u in ref if ref[u] in actionable}
        jac = len(a & b) / len(a | b) if (a | b) else 1.0
        sweep_rows.append({"effective_threshold_mwh": thr, "n_actionable": len(a),
                           "label_jaccard_vs_50mwh": round(jac, 4)})
    pd.DataFrame(sweep_rows).to_csv(out_dir / "dual_track_threshold_stability.csv", index=False)

    d4 = agg["D4_dual_asymmetric_proposed"]; d2 = agg["D2_dual_symmetric_any"]
    d1 = agg["D1_effective_only"]
    evidence_preserved = int(d4["confirmed_no_response"] - d2["confirmed_no_response"])
    hard_reduced = int(d1["hard_action"] - d4["hard_action"])
    accept = bool(evidence_preserved > 0 or hard_reduced > 0)
    print(f"[C2] D2 erases pending={d2['erased_pending']} no_response={d2['erased_no_response']} "
          f"(users={d2['users_evidence_erased']}); D4 preserves +{evidence_preserved} confirmed no-response "
          f"vs D2; hard prompts D1={d1['hard_action']} -> D4={d4['hard_action']} (reduced {hard_reduced}); "
          f"asymmetric-reset {'SUPPORTED' if accept else 'NOT SUPPORTED'} ({time.time()-t0:.1f}s)")
    return {
        "d2_pending_erased": int(d2["erased_pending"]),
        "d2_no_response_erased": int(d2["erased_no_response"]),
        "d2_users_evidence_erased": int(d2["users_evidence_erased"]),
        "d4_confirmed_no_response": int(d4["confirmed_no_response"]),
        "evidence_preserved_vs_symmetric": evidence_preserved,
        "hard_prompts_d1_effective_only": int(d1["hard_action"]),
        "hard_prompts_d4_proposed": int(d4["hard_action"]),
        "hard_prompts_reduced_by_d4": hard_reduced,
        "d4_gauge_soft": int(d4["gauge_soft"]),
        "asymmetric_reset_supported": accept,
        "runtime_s": round(time.time() - t0, 2),
    }
