#!/usr/bin/env python
"""OD2 Phase 1.5 - FCC-step ATTRIBUTION (the direct test of the domain claim).

The project owner's correction states that FCC re-learns ONLY under two mechanisms
(Type A deep-discharge relearn, Type B charge-side relearn). The sharpest test of that
claim is the REVERSE direction of the response audit:

    For every actual effective FCC step (>= 50 mWh), was it preceded by a Type A or
    Type B opportunity END within the response window [end, end+72h]?

If the domain model is correct, the fraction of FCC steps NOT explained by either
mechanism ("unexplained") should be small. A large unexplained fraction would mean the
gauge also relearns under conditions the two mechanisms do not capture.

Reads the Phase-1 opportunity table; recomputes effective FCC steps from the raw parquet.
Nothing existing is modified. Output: data/processed/fcc_relearn_od2/phase1/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from battery_usage.fcc_learning import _sorted_unique, fcc_step_indicator

REPO = Path(__file__).resolve().parent
PROC = REPO / "data" / "processed"
PARQUET = PROC / "battery_timeseries_all.parquet"
OUT = PROC / "fcc_relearn_od2" / "phase1"
REPORTS = REPO / "data" / "reports"


def effective_steps(df: pd.DataFrame, min_mwh: float) -> pd.DataFrame:
    """Per-user effective FCC-step timestamps (>= min_mwh)."""
    rows = []
    for uid, g in df.groupby("user_id", sort=False):
        g = _sorted_unique(g)
        fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
        ts = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        is_step, _ = fcc_step_indicator(fcc, min_mwh)
        for i in np.flatnonzero(is_step):
            rows.append({"user_id": uid, "step_ts_ns": int(ts[i]),
                         "delta_mwh": float(abs(fcc[i] - fcc[i - 1]))})
    return pd.DataFrame(rows)


def attribute(steps: pd.DataFrame, opps: pd.DataFrame, window_h: int) -> pd.DataFrame:
    """Classify each FCC step by whether a Type A / B END precedes it within window_h."""
    win_ns = int(window_h) * 3600 * 1_000_000_000
    ends = {}
    for uid, g in opps.groupby("user_id", sort=False):
        a = np.sort(g.loc[g["opportunity_type"] == "A", "end_ts"]
                    .to_numpy().astype("datetime64[ns]").astype(np.int64))
        b = np.sort(g.loc[g["opportunity_type"] == "B", "end_ts"]
                    .to_numpy().astype("datetime64[ns]").astype(np.int64))
        ends[uid] = (a, b)

    def _hit(arr, t):
        if arr.size == 0:
            return False
        lo = int(np.searchsorted(arr, t - win_ns, side="left"))
        hi = int(np.searchsorted(arr, t, side="right"))
        return hi > lo

    recs = []
    for r in steps.itertuples(index=False):
        a, b = ends.get(r.user_id, (np.array([], np.int64), np.array([], np.int64)))
        ha, hb = _hit(a, r.step_ts_ns), _hit(b, r.step_ts_ns)
        cls = ("both" if ha and hb else "A_only" if ha else "B_only" if hb else "neither")
        recs.append({"user_id": r.user_id, "step_ts_ns": r.step_ts_ns,
                     "delta_mwh": r.delta_mwh, "by_A": ha, "by_B": hb, "attribution": cls})
    return pd.DataFrame(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-h", type=int, default=72)
    ap.add_argument("--min-mwh", type=float, default=50.0)
    args = ap.parse_args()

    print("loading raw parquet + opportunities...", flush=True)
    raw = pd.read_parquet(PARQUET, columns=["user_id", "timestamp", "fullChargeCapacity"])
    raw["timestamp"] = pd.to_datetime(raw["timestamp"])
    opps = pd.read_parquet(OUT / "od2_opportunities.parquet",
                           columns=["user_id", "opportunity_type", "end_ts"])
    opps["end_ts"] = pd.to_datetime(opps["end_ts"])

    print(f"computing effective FCC steps (>= {args.min_mwh} mWh)...", flush=True)
    steps = effective_steps(raw, args.min_mwh)
    print(f"  {len(steps):,} effective steps across {steps['user_id'].nunique()} users", flush=True)

    att = attribute(steps, opps, args.window_h)
    att.to_parquet(OUT / "od2_fcc_step_attribution.parquet", index=False)

    vc = att["attribution"].value_counts()
    tot = int(len(att))
    explained = int((att["by_A"] | att["by_B"]).sum())
    summary = {
        "window_h": args.window_h, "min_mwh": args.min_mwh, "n_effective_steps": tot,
        "explained_by_either": explained,
        "explained_frac": round(explained / tot, 4) if tot else float("nan"),
        "unexplained": tot - explained,
        "unexplained_frac": round((tot - explained) / tot, 4) if tot else float("nan"),
        "A_only": int(vc.get("A_only", 0)), "B_only": int(vc.get("B_only", 0)),
        "both": int(vc.get("both", 0)), "neither": int(vc.get("neither", 0)),
        "by_A_total": int(att["by_A"].sum()), "by_B_total": int(att["by_B"].sum()),
    }
    pd.DataFrame([summary]).to_csv(OUT / "od2_fcc_step_attribution_summary.csv", index=False)

    # Median unexplained delta vs explained (is the "unexplained" residue just micro-noise?)
    if tot:
        summary["median_delta_explained"] = round(
            float(att.loc[att["by_A"] | att["by_B"], "delta_mwh"].median()), 1)
        un = att.loc[~(att["by_A"] | att["by_B"]), "delta_mwh"]
        summary["median_delta_unexplained"] = round(float(un.median()), 1) if len(un) else float("nan")

    print("\n=== FCC-STEP ATTRIBUTION (does the gauge relearn ONLY under Type A/B?) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nwrote {OUT / 'od2_fcc_step_attribution_summary.csv'}")


if __name__ == "__main__":
    main()
