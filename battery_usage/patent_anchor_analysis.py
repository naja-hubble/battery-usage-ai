"""Patent evidence A3 -- response-anchor comparison (start / low / end).

ADDITIVE. Quantifies the causal-leakage advantage of anchoring the FCC response
window at the episode END (recharge completion) rather than at the episode START
or the low-SOC timestamp.

Causal contamination is defined WITHOUT proxy labels: a counted "response" FCC
step whose timestamp precedes the physical recharge completion (episode end) is
contamination -- it is part of the discharge/recharge that produced the learning
opportunity, not a response to the completed opportunity. END anchoring makes
this fraction structurally ~0; START / LOW anchoring counts mid-cycle steps as
"responses".

For each anchor x response window (24/72/168h) we report: fraction of counted
steps before completion, fraction at-or-before completion, duplicate attribution
rate (one step assigned to multiple episodes via overlapping windows), confirmed
no-response count, censored count, agreement with the production END-anchored
response status, downstream label change vs END, and observed-responder
protection. User-clustered bootstrap CI on the contamination fraction.

Charge-termination anchor: the dataset has no per-sample charge-current / taper
telemetry, so a robust charge-termination timestamp is NOT AVAILABLE; it is
reported as such (not fabricated) and END is used as its operational proxy.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import patent_common_v4 as pc

WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
ANCHORS = ("start", "low", "end")
CONFIRMED_NR_USER_MIN = 3


def _anchor_ns(ep: pd.DataFrame, anchor: str) -> np.ndarray:
    return ep[f"{anchor}_ns"].to_numpy(dtype=np.int64)


def run(out_dir: Path, steps: pd.DataFrame, episodes: pd.DataFrame,
        design: pd.Series, seed: int = 42, boot: int = 1000) -> Dict[str, object]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng_ = pc.rng(seed)
    t0 = time.time()

    band = pc.PRIMARY_THRESHOLD
    ep = episodes[episodes["threshold_name"] == band].copy()
    ep = ep[ep["is_ok"]]                                    # qualified opportunities
    eff = steps[steps["is_effective"]]
    sbu = pc.steps_by_user(eff)                             # proposed: effective >=50 mWh
    sbu_any = pc.steps_by_user(steps)                       # production full-history: any change

    # per-user last observed step time horizon for completeness; use the production
    # window-complete flag for END (already computed), recompute completeness for
    # other anchors against the user's last sample.
    last_ns: Dict[str, int] = {}
    ts_meta = pc.load_timeseries(["user_id", "timestamp"])
    ts_meta["ts_ns"] = ts_meta["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    for uid, g in ts_meta.groupby("user_id", sort=False):
        last_ns[uid] = int(g["ts_ns"].max())

    # production END-anchored response (proxy for agreement check)
    prod_resp = ep["fcc_response_status_72h"].astype(str).to_numpy()

    rows: List[dict] = []
    assign_rows: List[dict] = []
    # per (anchor, window) collect per-episode arrays
    per_user_contam_num: Dict[Tuple[str, int], Dict[str, float]] = {}
    per_user_contam_den: Dict[Tuple[str, int], Dict[str, float]] = {}
    # user-level no-response flags vs END (window 72h)
    user_flag: Dict[str, Dict[str, int]] = {}    # uid -> {anchor: confirmed_nr_count}
    responders = set(eff["user_id"].unique())    # observed responders (any effective step)

    uids = ep["user_id"].to_numpy()
    end_ns_all = ep["end_ns"].to_numpy(dtype=np.int64)

    for anchor in ANCHORS:
        anc_all = _anchor_ns(ep, anchor)
        for w in WINDOWS_H:
            win = int(w) * pc.HOUR_NS
            n_counted = 0
            n_before = 0
            n_at_or_before = 0
            responded = np.zeros(len(ep), dtype=bool)
            complete = np.zeros(len(ep), dtype=bool)
            # duplicate attribution: per user collect counted step ts
            counted_ts_by_user: Dict[str, List[int]] = {}
            cu_num: Dict[str, float] = {}
            cu_den: Dict[str, float] = {}
            for i in range(len(ep)):
                uid = uids[i]
                a = int(anc_all[i]); e = int(end_ns_all[i])
                arr = sbu.get(uid)
                comp = (a + win) <= last_ns.get(uid, 0)
                complete[i] = comp
                if arr is None or arr["ts_ns"].size == 0:
                    continue
                ts = arr["ts_ns"]
                lo = int(np.searchsorted(ts, a, side="left"))
                hi = int(np.searchsorted(ts, a + win, side="right"))
                cnt = hi - lo
                if cnt <= 0:
                    continue
                wts = ts[lo:hi]
                responded[i] = True
                n_counted += cnt
                before = int((wts < e).sum())              # strictly before completion
                at_or_before = int((wts <= e).sum())
                n_before += before
                n_at_or_before += at_or_before
                cu_num[uid] = cu_num.get(uid, 0.0) + before
                cu_den[uid] = cu_den.get(uid, 0.0) + cnt
                counted_ts_by_user.setdefault(uid, []).extend(wts.tolist())
                if w == pc.PRIMARY_WINDOW_H:
                    assign_rows.append({
                        "user_id": uid, "anchor": anchor, "episode_id": ep["episode_id"].iat[i],
                        "n_counted_steps": cnt, "n_steps_before_completion": before,
                        "contaminated": bool(before > 0),
                    })
            # duplicate attribution rate (window-overlap double counting)
            tot_attr = 0; dup_attr = 0
            for uid, lst in counted_ts_by_user.items():
                arrl = np.array(lst)
                tot_attr += arrl.size
                uniq, cnts = np.unique(arrl, return_counts=True)
                dup_attr += int((cnts[cnts > 1] - 1).sum())   # extra attributions beyond first
            dup_rate = (dup_attr / tot_attr) if tot_attr else 0.0
            # confirmed no-response (complete window, no counted step) and censored
            confirmed_nr = int((complete & ~responded).sum())
            censored = int((~complete).sum())
            # agreement with production END status. Production full-history counts ANY
            # FCC change, so the fidelity check uses any-change window membership; the
            # contamination/no-response metrics above use the proposed effective step.
            if w == pc.PRIMARY_WINDOW_H:
                responded_any = np.zeros(len(ep), dtype=bool)
                for i in range(len(ep)):
                    arr = sbu_any.get(uids[i])
                    if arr is None or arr["ts_ns"].size == 0:
                        continue
                    ts = arr["ts_ns"]; a = int(anc_all[i])
                    loi = int(np.searchsorted(ts, a, side="left"))
                    hii = int(np.searchsorted(ts, a + win, side="right"))
                    responded_any[i] = hii > loi
                mine = np.where(responded_any, "responded",
                                np.where(complete, "no_response", "censored"))
                agree = float(np.mean(mine == prod_resp))
                # user-level confirmed-nr count for transition vs END
                for uid in ep["user_id"].unique():
                    mask = (uids == uid)
                    nr = int((complete[mask] & ~responded[mask]).sum())
                    user_flag.setdefault(uid, {})[anchor] = nr
            else:
                agree = float("nan")
            contam_frac = (n_before / n_counted) if n_counted else 0.0
            rows.append({
                "anchor": anchor, "window_h": w,
                "n_counted_steps": n_counted,
                "frac_steps_before_completion": round(contam_frac, 5),
                "frac_steps_at_or_before_completion":
                    round(n_at_or_before / n_counted, 5) if n_counted else 0.0,
                "duplicate_attribution_rate": round(dup_rate, 5),
                "confirmed_no_response": confirmed_nr,
                "censored": censored,
                "n_responded_episodes": int(responded.sum()),
                "agreement_with_production_end_72h": round(agree, 5) if np.isfinite(agree) else None,
            })
            per_user_contam_num[(anchor, w)] = cu_num
            per_user_contam_den[(anchor, w)] = cu_den

    comp = pd.DataFrame(rows)
    comp.to_csv(out_dir / "response_anchor_comparison.csv", index=False)
    pc.save_anon_parquet(pd.DataFrame(assign_rows),
                         out_dir / "response_anchor_episode_assignments.parquet")

    # ---- user-clustered bootstrap CI of contamination fraction (72h) ----
    boot_rows: List[dict] = []
    for anchor in ANCHORS:
        num_map = per_user_contam_num[(anchor, pc.PRIMARY_WINDOW_H)]
        den_map = per_user_contam_den[(anchor, pc.PRIMARY_WINDOW_H)]
        keys = list(den_map.keys())
        if keys:
            num = np.array([num_map.get(k, 0.0) for k in keys])
            den = np.array([den_map[k] for k in keys])
            ci = pc.user_bootstrap_ratio(num, den, boot, rng_)
        else:
            ci = {"point": 0.0, "ci_lo": 0.0, "ci_hi": 0.0}
        boot_rows.append({"anchor": anchor, "metric": "contamination_frac_72h", **ci})
    pd.DataFrame(boot_rows).to_csv(out_dir / "response_anchor_contamination_bootstrap.csv", index=False)

    # ---- label transition vs END (user-level confirmed-no-response flag) ----
    trans_rows: List[dict] = []
    end_flag = {u: f.get("end", 0) for u, f in user_flag.items()}
    for anchor in ("start", "low"):
        moved_into_nr = 0; moved_out_nr = 0; responder_flagged = 0
        for uid, f in user_flag.items():
            a_nr = f.get(anchor, 0) >= CONFIRMED_NR_USER_MIN
            e_nr = end_flag.get(uid, 0) >= CONFIRMED_NR_USER_MIN
            if a_nr and not e_nr:
                moved_into_nr += 1
                if uid in responders:
                    responder_flagged += 1
            if e_nr and not a_nr:
                moved_out_nr += 1
        trans_rows.append({
            "anchor": anchor, "vs": "end",
            "users_newly_flagged_no_response": moved_into_nr,
            "users_no_longer_flagged": moved_out_nr,
            "observed_responders_newly_flagged": responder_flagged,
        })
    pd.DataFrame(trans_rows).to_csv(out_dir / "response_anchor_label_transition.csv", index=False)

    # ---- delay CDF data (responders only, 168h horizon) per anchor ----
    delay_rows: List[dict] = []
    for anchor in ANCHORS:
        anc_all = _anchor_ns(ep, anchor)
        for i in range(len(ep)):
            uid = uids[i]; a = int(anc_all[i])
            arr = sbu.get(uid)
            if arr is None or arr["ts_ns"].size == 0:
                continue
            nxt = pc.first_step_after(arr, a, effective_only=True,
                                      horizon_ns=168 * pc.HOUR_NS)
            if nxt is not None:
                delay_rows.append({"anchor": anchor,
                                   "delay_h": (nxt - a) / pc.HOUR_NS})
    pd.DataFrame(delay_rows).to_csv(out_dir / "response_anchor_delay_cdf_data.csv", index=False)

    # ---- charge-termination availability (NOT AVAILABLE -> not fabricated) ----
    pd.DataFrame([{
        "anchor": "charge_termination",
        "status": "NOT AVAILABLE",
        "reason": "no per-sample charge-current/voltage-taper telemetry; END used as proxy",
    }]).to_csv(out_dir / "response_anchor_charge_termination_status.csv", index=False)

    # ---- acceptance: END measurable advantage? ----
    end72 = comp.query("anchor=='end' and window_h==72").iloc[0]
    start72 = comp.query("anchor=='start' and window_h==72").iloc[0]
    low72 = comp.query("anchor=='low' and window_h==72").iloc[0]
    end_contam = float(end72["frac_steps_before_completion"])
    worst_contam = float(max(start72["frac_steps_before_completion"],
                             low72["frac_steps_before_completion"]))
    end_dup = float(end72["duplicate_attribution_rate"])
    worst_dup = float(max(start72["duplicate_attribution_rate"],
                          low72["duplicate_attribution_rate"]))
    advantage = bool(end_contam + 1e-9 < worst_contam or end_dup + 1e-9 < worst_dup)
    print(f"[A3] contamination 72h: end={end_contam:.3f} start={start72['frac_steps_before_completion']:.3f} "
          f"low={low72['frac_steps_before_completion']:.3f}; dup end={end_dup:.3f} worst={worst_dup:.3f}; "
          f"END advantage={'YES' if advantage else 'NO'} ({time.time()-t0:.1f}s)")
    return {
        "end_contamination_frac_72h": end_contam,
        "start_contamination_frac_72h": float(start72["frac_steps_before_completion"]),
        "low_contamination_frac_72h": float(low72["frac_steps_before_completion"]),
        "worst_non_end_contamination_72h": worst_contam,
        "end_duplicate_rate_72h": end_dup,
        "worst_non_end_duplicate_rate_72h": worst_dup,
        "end_agreement_with_production": float(end72["agreement_with_production_end_72h"]),
        "end_anchor_measurable_advantage": advantage,
        "n_episodes": int(len(ep)),
        "runtime_s": round(time.time() - t0, 2),
    }
