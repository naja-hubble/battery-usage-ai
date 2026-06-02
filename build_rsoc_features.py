"""Add RSOC / charge-range features to the reason table.

Per the Power Manager PWM decoder, remainingCapacityInPercentage IS RSOC
(remainingCapacity/fullChargeCapacity*100). A smart gauge re-learns FCC mainly on a
"qualified" full-range discharge, so how far / how often a user drives RSOC to its
extremes is mechanistically relevant to whether SoH updates. These features let the
re-analysis test that directly.

  min_rsoc / rsoc_p05 / rsoc_p95     RSOC extremes (depth of discharge reached)
  rsoc_swing                          p95 - p05 (cycle amplitude)
  frac_below_10 / frac_below_5        deep-discharge exposure
  n_deep_dis10                        # deep-discharge events (RSOC crossing below 10%)
  reaches_full / frac_at_full         full-charge (RSOC>=99) ever / time-weighted fraction
  n_full_range_dis                    # discharges spanning >=90% down to <=10% (qualified)

    python build_rsoc_features.py   # merges into data/processed/soh_reason_features.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from battery_usage.config import load_config
from battery_usage.features import sample_weights


def main() -> None:
    cfg = load_config()
    gap = cfg.analysis["max_sample_gap_hours"]
    df = pd.read_parquet(
        cfg.processed_dir / "battery_timeseries_all.parquet",
        columns=["user_id", "timestamp", "remainingCapacityInPercentage", "acdcMode"],
    )
    rows = []
    for uid, g in df.groupby("user_id", sort=False):
        g = g.sort_values("timestamp")
        r = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
        w = sample_weights(g["timestamp"], gap)
        tw = w.sum()
        b10 = r < 10
        n_deep = int((b10[1:] & ~b10[:-1]).sum()) + int(b10[0])
        # qualified full-range discharge: while on battery, RSOC goes from >=90 to <=10
        on_b = (g["acdcMode"] == 0).to_numpy()
        run = np.cumsum(np.concatenate([[True], on_b[1:] != on_b[:-1]]))
        n_full_range = 0
        for _, gg in g.assign(_run=run, _on=on_b)[on_b].groupby("_run"):
            rr = gg["remainingCapacityInPercentage"].to_numpy(dtype=float)
            if rr.size and np.nanmax(rr) >= 90 and np.nanmin(rr) <= 10:
                n_full_range += 1
        rows.append({
            "user_id": uid,
            "min_rsoc": float(np.nanmin(r)),
            "rsoc_p05": float(np.nanpercentile(r, 5)),
            "rsoc_p95": float(np.nanpercentile(r, 95)),
            "rsoc_swing": float(np.nanpercentile(r, 95) - np.nanpercentile(r, 5)),
            "frac_below_10": float(np.nanmean(b10)),
            "frac_below_5": float(np.nanmean(r < 5)),
            "n_deep_dis10": n_deep,
            "reaches_full": int((r >= 99).any()),
            "frac_at_full": float(w[r >= 99].sum() / tw) if tw > 0 else np.nan,
            "n_full_range_dis": n_full_range,
        })
    rs = pd.DataFrame(rows)

    p = cfg.processed_dir / "soh_reason_features.csv"
    t = pd.read_csv(p)
    t = t.drop(columns=[c for c in rs.columns if c != "user_id" and c in t.columns])
    t = t.merge(rs, on="user_id", how="left")
    t.to_csv(p, index=False)
    print(f"merged {rs.shape[1] - 1} RSOC/charge features into {p} -> {t.shape}")
    print("new cols:", [c for c in rs.columns if c != "user_id"])


if __name__ == "__main__":
    main()
