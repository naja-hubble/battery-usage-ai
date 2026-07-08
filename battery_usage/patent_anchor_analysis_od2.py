"""OD2 patent evidence A3 - response-anchor contamination, PER MECHANISM (Type A / Type B / union).

ADDITIVE / READ-ONLY. Forks the OD1 A3 (``patent_anchor_analysis``) causal convention to the
corrected two-mechanism relearn definition. The OD1 A3 anchored the FCC response window at the
episode END (recharge completion) vs START vs the low-SOC timestamp; here we re-measure the same
causal-leakage quantity for each OD2 mechanism's own anchor set:

  * Type A (deep-discharge relearn):  start (opening full) / low (deep sample) / end (full re-attainment)
  * Type B (charge-side relearn):     arm (= start = low, band-entry while charging) / end (full)
  * union (dedup on coincident ENDs): end

Causal contamination is defined WITHOUT proxy labels, identically to OD1 A3: a counted "response"
FCC step (>= 50 mWh) whose timestamp precedes the physical recharge completion (episode END) is
contamination -- it is part of the charge/discharge that PRODUCED the opportunity, not a response to
the completed opportunity. END anchoring makes this fraction structurally ~0 for BOTH mechanisms;
START (Type A) / ARM (Type B) anchoring counts mid-cycle charge steps as "responses".

For each (mechanism, anchor, window in {24,72,168}h) we report: fraction of counted steps strictly
before completion (contamination), fraction at-or-before, and the DUPLICATE-ATTRIBUTION rate (one
effective FCC step assigned to >= 2 episodes because overlapping windows share it). Because Type B is
dense (~32k ok episodes), overlapping 168h END windows share steps heavily; the union dedup on
coincident ENDs is expected to REDUCE the duplicate-attribution rate vs the pooled A+B episode set --
we quantify that reduction explicitly (``response_anchor_duplicate_od2.csv``).

Reuses the shared v4 FCC-step cache (``pc.ensure_shared_inputs`` / ``pc.steps_by_user``) and the
window-membership primitive (``pc.steps_in_window``) verbatim. Only the driver and the mechanism-anchor
selection are new. Technical evidence for patent review -- no ground truth is fabricated. The
charge-termination anchor remains NOT AVAILABLE (no per-sample charge-current/taper telemetry); END is
its operational proxy, reported as such.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc

WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
PRIMARY_W = 168          # OD2 primary response window
OD1_COMPARE_W = 72       # window at which the OD1 A3 baseline was quoted
CODE_VERSION = "patent_evidence_od2_a3.0"

# per-mechanism anchor set: name -> episode timestamp column (ns)
MECH_ANCHORS: Dict[str, List[Tuple[str, str]]] = {
    "A": [("start", "start_ns"), ("low", "low_ns"), ("end", "end_ns")],
    "B": [("arm", "start_ns"), ("end", "end_ns")],           # arm == start == low for Type B
    "union": [("end", "end_ns")],
}

# OD1 A3 baseline (72h) for side-by-side reporting
OD1_BASELINE_72H = {"end": 0.0, "start": 0.557, "low": 0.270}


def _mech_subset(ep: pd.DataFrame, mech: str) -> pd.DataFrame:
    if mech == "A":
        sub = ep[ep["opportunity_type"] == "A"]
    elif mech == "B":
        sub = ep[ep["opportunity_type"] == "B"]
    elif mech == "union":
        sub = ep[ep["is_union_primary"]]
    else:
        raise ValueError(mech)
    return sub[sub["is_ok"]].copy()


def _contamination_for_anchor(
    ep: pd.DataFrame, anchor_col: str, sbu: Dict[str, Dict[str, np.ndarray]],
    win_ns: int,
) -> dict:
    """Count effective FCC steps in [anchor, anchor+W] and split by completion.

    Returns aggregate counts + per-user contamination num/den (for clustered bootstrap) + the
    per-user counted-step timestamp lists (for the duplicate-attribution rate). Mirrors the OD1
    A3 inner loop but is mechanism-agnostic (the anchor column is passed in)."""
    uids = ep["user_id"].to_numpy()
    anc_all = ep[anchor_col].to_numpy(dtype=np.int64)
    end_all = ep["end_ns"].to_numpy(dtype=np.int64)

    n_counted = n_before = n_at_or_before = 0
    n_eps_counted = 0
    per_user_num: Dict[str, float] = {}
    per_user_den: Dict[str, float] = {}
    counted_ts_by_user: Dict[str, List[int]] = {}

    for i in range(len(ep)):
        uid = uids[i]
        arr = sbu.get(uid)
        if arr is None or arr["ts_ns"].size == 0:
            continue
        a = int(anc_all[i]); e = int(end_all[i])
        idx = pc.steps_in_window(arr, a, a + win_ns, effective_only=True)
        if idx.size == 0:
            continue
        wts = arr["ts_ns"][idx]
        cnt = int(idx.size)
        before = int((wts < e).sum())              # strictly before completion == contamination
        at_or_before = int((wts <= e).sum())
        n_counted += cnt
        n_before += before
        n_at_or_before += at_or_before
        n_eps_counted += 1
        per_user_num[uid] = per_user_num.get(uid, 0.0) + before
        per_user_den[uid] = per_user_den.get(uid, 0.0) + cnt
        counted_ts_by_user.setdefault(uid, []).extend(wts.tolist())

    # duplicate attribution: a step timestamp counted by >= 2 episodes of THIS mechanism (overlapping
    # anchor windows share it). extra attributions beyond the first are duplicates.
    tot_attr = 0
    dup_attr = 0
    for lst in counted_ts_by_user.values():
        a = np.asarray(lst)
        tot_attr += a.size
        _uniq, cnts = np.unique(a, return_counts=True)
        dup_attr += int((cnts[cnts > 1] - 1).sum())
    dup_rate = (dup_attr / tot_attr) if tot_attr else 0.0

    return {
        "n_counted_steps": n_counted,
        "n_before": n_before,
        "n_at_or_before": n_at_or_before,
        "n_episodes_counted": n_eps_counted,
        "frac_before": (n_before / n_counted) if n_counted else 0.0,
        "frac_at_or_before": (n_at_or_before / n_counted) if n_counted else 0.0,
        "duplicate_attribution_rate": dup_rate,
        "n_duplicate_attr": dup_attr,
        "n_total_attr": tot_attr,
        "_num": per_user_num,
        "_den": per_user_den,
    }


def _pooled_end_duplicate(ep_ok: pd.DataFrame, sbu, win_ns: int) -> dict:
    """END-anchor duplicate-attribution over the POOLED A+B episode set (no union dedup).

    Directly quantifies the double counting that the union dedup on coincident ENDs removes:
    when an A and a B episode close on the same full-charge END, a single response step is
    attributed twice in the pooled view but once in the union view."""
    pooled = ep_ok[ep_ok["opportunity_type"].isin(["A", "B"])]
    return _contamination_for_anchor(pooled, "end_ns", sbu, win_ns)


def run_a3_od2(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
               mechanisms=("A", "B", "union"), boot: int = 1000, seed: int = 42) -> Dict[str, dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    eff = steps[steps["is_effective"]]
    sbu = pc.steps_by_user(eff)               # proposed effective (>=50 mWh) step arrays per user
    episodes = episodes.copy()

    comp_rows: List[dict] = []
    boot_rows: List[dict] = []
    result: Dict[str, dict] = {}

    for mech in mechanisms:
        tm = time.time()
        ep = _mech_subset(episodes, mech)
        n_eps = len(ep)
        for anchor_name, anchor_col in MECH_ANCHORS[mech]:
            for w in WINDOWS_H:
                win = int(w) * pc.HOUR_NS
                r = _contamination_for_anchor(ep, anchor_col, sbu, win)
                comp_rows.append({
                    "mechanism": mech, "anchor": anchor_name, "window_h": w,
                    "n_episodes": n_eps, "n_episodes_counted": r["n_episodes_counted"],
                    "n_counted_steps": r["n_counted_steps"],
                    "frac_steps_before_completion": round(r["frac_before"], 5),
                    "frac_steps_at_or_before_completion": round(r["frac_at_or_before"], 5),
                    "duplicate_attribution_rate": round(r["duplicate_attribution_rate"], 5),
                    "n_duplicate_attr": r["n_duplicate_attr"],
                    "n_total_attr": r["n_total_attr"],
                })
                # clustered-bootstrap CI on contamination at the OD2 primary window (168h)
                if w == PRIMARY_W:
                    keys = list(r["_den"].keys())
                    if keys:
                        num = np.array([r["_num"].get(k, 0.0) for k in keys])
                        den = np.array([r["_den"][k] for k in keys])
                        ci = pc.user_bootstrap_ratio(num, den, boot, rng_)
                    else:
                        ci = {"point": 0.0, "ci_lo": 0.0, "ci_hi": 0.0}
                    boot_rows.append({
                        "mechanism": mech, "anchor": anchor_name, "window_h": w,
                        "metric": "contamination_frac",
                        "point": round(ci["point"], 5) if np.isfinite(ci["point"]) else None,
                        "ci_lo": round(ci["ci_lo"], 5) if np.isfinite(ci["ci_lo"]) else None,
                        "ci_hi": round(ci["ci_hi"], 5) if np.isfinite(ci["ci_hi"]) else None,
                    })

        # per-mechanism headline: END contamination + non-END worst + END duplicate rate at 168h
        def _row(anchor, w):
            for rr in comp_rows:
                if rr["mechanism"] == mech and rr["anchor"] == anchor and rr["window_h"] == w:
                    return rr
            return None
        end168 = _row("end", PRIMARY_W)
        non_end = [a for (a, _c) in MECH_ANCHORS[mech] if a != "end"]
        worst_non_end = max((_row(a, PRIMARY_W)["frac_steps_before_completion"] for a in non_end),
                            default=0.0)
        result[mech] = {
            "mechanism": mech, "n_episodes": n_eps,
            "end_contamination_168h": end168["frac_steps_before_completion"],
            "end_contamination_72h": _row("end", OD1_COMPARE_W)["frac_steps_before_completion"],
            "worst_non_end_contamination_168h": round(float(worst_non_end), 5),
            "non_end_anchors": ",".join(non_end),
            "end_duplicate_rate_168h": end168["duplicate_attribution_rate"],
            "end_duplicate_rate_72h": _row("end", OD1_COMPARE_W)["duplicate_attribution_rate"],
        }
        print(f"[A3-od2:{mech}] eps={n_eps} END contam 168h={end168['frac_steps_before_completion']:.4f} "
              f"(72h={result[mech]['end_contamination_72h']:.4f}) worst_non_end 168h={worst_non_end:.4f} "
              f"END dup 168h={end168['duplicate_attribution_rate']:.4f} ({time.time()-tm:.1f}s)", flush=True)

    comp = pd.DataFrame(comp_rows)
    comp.to_csv(out_dir / "response_anchor_comparison_od2.csv", index=False)
    pd.DataFrame(boot_rows).to_csv(out_dir / "response_anchor_contamination_bootstrap_od2.csv", index=False)

    # ---- END-anchor duplicate-attribution: pooled A+B vs union (dedup reduction) ----
    ep_ok = episodes[episodes["is_ok"]]
    dup_rows: List[dict] = []
    for w in WINDOWS_H:
        win = int(w) * pc.HOUR_NS
        pooled = _pooled_end_duplicate(ep_ok, sbu, win)
        uni = _contamination_for_anchor(_mech_subset(episodes, "union"), "end_ns", sbu, win)
        pooled_rate = pooled["duplicate_attribution_rate"]
        uni_rate = uni["duplicate_attribution_rate"]
        dup_rows.append({
            "window_h": w,
            "pooled_AB_duplicate_rate": round(pooled_rate, 5),
            "pooled_AB_n_duplicate": pooled["n_duplicate_attr"],
            "pooled_AB_n_total_attr": pooled["n_total_attr"],
            "union_duplicate_rate": round(uni_rate, 5),
            "union_n_duplicate": uni["n_duplicate_attr"],
            "union_n_total_attr": uni["n_total_attr"],
            "duplicate_attr_removed": pooled["n_duplicate_attr"] - uni["n_duplicate_attr"],
            "rate_reduction": round(pooled_rate - uni_rate, 5),
        })
    dup_df = pd.DataFrame(dup_rows)
    dup_df.to_csv(out_dir / "response_anchor_duplicate_od2.csv", index=False)

    # ---- charge-termination availability (NOT AVAILABLE -> not fabricated) ----
    pd.DataFrame([{
        "anchor": "charge_termination", "status": "NOT AVAILABLE",
        "reason": "no per-sample charge-current/voltage-taper telemetry; END used as proxy",
    }]).to_csv(out_dir / "response_anchor_charge_termination_status_od2.csv", index=False)

    dup168 = dup_df[dup_df["window_h"] == PRIMARY_W].iloc[0]
    summary = {
        "by_mechanism": result,
        "pooled_AB_duplicate_rate_168h": float(dup168["pooled_AB_duplicate_rate"]),
        "union_duplicate_rate_168h": float(dup168["union_duplicate_rate"]),
        "duplicate_attr_removed_by_union_168h": int(dup168["duplicate_attr_removed"]),
        "n_mechanisms": len(mechanisms),
        "runtime_s": round(time.time() - t0, 2),
    }
    print(f"[A3-od2] union END dup 168h={dup168['union_duplicate_rate']:.4f} vs pooled A+B "
          f"{dup168['pooled_AB_duplicate_rate']:.4f} (removed {int(dup168['duplicate_attr_removed'])} attr) "
          f"({time.time()-t0:.1f}s)", flush=True)
    return summary
