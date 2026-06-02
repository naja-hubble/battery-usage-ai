"""Join per-user features + SoH-update dynamics into one analysis table.

To investigate WHY some users' SoH (FCC) stops updating, pair the full feature set
(``extract_features`` via ``aggregate.build_cohort_table``) with FCC-update dynamics:

  fcc_distinct              distinct FCC values seen
  fcc_changes               number of FCC steps (updates)
  fcc_change_rate_per_100d  span-normalized update rate (robust to span length)
  soh_flat_tail_days        trailing days with no FCC change (the threshold metric)
  flat_pct_of_span          flat tail as % of the observed window (span-robust)
  soh_update_status         active / stale / very_stale (same thresholds as the plot)

One row per user -> data/processed/soh_reason_features.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from battery_usage.config import load_config
from battery_usage.aggregate import build_cohort_table
from soh_update_status import _classify, NOW
from vendor_normalize import normalize_vendor


def fcc_dynamics(cfg) -> pd.DataFrame:
    df = pd.read_parquet(
        cfg.processed_dir / "battery_timeseries_all.parquet",
        columns=["user_id", "timestamp", "fullChargeCapacity"],
    )
    rows = []
    for uid, g in df.groupby("user_id", sort=False):
        g = g.sort_values("timestamp")
        fcc = g["fullChargeCapacity"].to_numpy()
        ts = g["timestamp"].to_numpy()
        span = (ts[-1] - ts[0]) / np.timedelta64(1, "D")
        changes = int((fcc[1:] != fcc[:-1]).sum())
        last = fcc[-1]
        s = len(fcc) - 1
        while s > 0 and fcc[s - 1] == last:
            s -= 1
        flat_tail = (ts[-1] - ts[s]) / np.timedelta64(1, "D")
        rows.append({
            "user_id": uid,
            "fcc_distinct": int(pd.Series(fcc).nunique()),
            "fcc_changes": changes,
            "fcc_change_rate_per_100d": round(changes / span * 100, 3) if span > 0 else np.nan,
            "soh_flat_tail_days": round(float(flat_tail), 1),
            "flat_pct_of_span": round(float(flat_tail / span * 100), 1) if span > 0 else np.nan,
            "soh_last_change_ts": pd.Timestamp(ts[s]),
            "stale_days": round(float((NOW - pd.Timestamp(ts[-1])) / np.timedelta64(1, "D")), 1),
        })
    m = pd.DataFrame(rows)
    m["soh_update_status"] = m["soh_flat_tail_days"].map(_classify)
    return m


def main() -> None:
    cfg = load_config()
    feats = build_cohort_table(cfg)                 # full extract_features per user
    feats["batt_vendor"] = feats["manufacturer"].map(normalize_vendor)
    dyn = fcc_dynamics(cfg)
    t = feats.merge(dyn, on="user_id", how="inner")

    out = cfg.processed_dir / "soh_reason_features.csv"
    t.to_csv(out, index=False)
    print("wrote", out, t.shape)
    print("status counts:", t["soh_update_status"].value_counts().to_dict())
    print("n cols:", t.shape[1])


if __name__ == "__main__":
    main()
