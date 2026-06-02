"""Classify users by how long their SoH (FCC) has gone WITHOUT an update.

SoH = FCC * 100 / DesignCapacity and DesignCapacity is a per-user constant, so SoH
changes iff the integer ``fullChargeCapacity`` steps. Some packs' gauges stop
re-learning FCC: it stays pinned at one value for hundreds of days even while the
logger keeps sampling -> the date-vs-SoH curve flat-lines.

For each user we measure the trailing flat run: the time from the LAST FCC change
to the last sample (``soh_flat_tail_days``), and bucket it:

    active     : flat tail <  STALE_DAYS      (SoH still updating)
    stale      : STALE_DAYS <= flat tail < VERY_STALE_DAYS
    very_stale : flat tail >= VERY_STALE_DAYS (plotted in RED)

    python soh_update_status.py            # writes data/processed/soh_update_status.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from battery_usage.config import load_config

STALE_DAYS = 60            # SoH not updated >= this -> "stale" (active = flat tail < 60d)
VERY_STALE_DAYS = 180      # >= this -> "very_stale" (red)
NOW = pd.Timestamp("2026-06-02")   # reference "today" for staleness (no wall-clock dep)

STATUS_ORDER = ["active", "stale", "very_stale"]
STATUS_COLORS = {"active": "tab:blue", "stale": "tab:orange", "very_stale": "red"}


def _classify(flat_tail_days: float) -> str:
    if flat_tail_days >= VERY_STALE_DAYS:
        return "very_stale"
    if flat_tail_days >= STALE_DAYS:
        return "stale"
    return "active"


def compute_update_status(df: pd.DataFrame, now: pd.Timestamp = NOW) -> pd.DataFrame:
    """One row per user: trailing-flat-run length of FCC/SoH + status bucket.

    ``df`` must have columns user_id, timestamp, fullChargeCapacity.
    """
    rows = []
    for uid, g in df.groupby("user_id", sort=False):
        g = g.sort_values("timestamp")
        fcc = g["fullChargeCapacity"].to_numpy()
        ts = g["timestamp"].to_numpy()
        last = fcc[-1]
        # Walk back over the trailing run where FCC == its final value.
        s = len(fcc) - 1
        while s > 0 and fcc[s - 1] == last:
            s -= 1
        last_change_ts = ts[s]
        flat_tail_days = (ts[-1] - last_change_ts) / np.timedelta64(1, "D")
        stale_days = (now - pd.Timestamp(ts[-1])) / np.timedelta64(1, "D")
        rows.append((
            uid,
            pd.Timestamp(last_change_ts),
            pd.Timestamp(ts[-1]),
            round(float(flat_tail_days), 1),
            int(pd.Series(fcc).nunique()),
            round(float(stale_days), 1),
        ))
    m = pd.DataFrame(rows, columns=[
        "user_id", "soh_last_change_ts", "last_ts",
        "soh_flat_tail_days", "fcc_distinct", "stale_days",
    ])
    m["soh_update_status"] = m["soh_flat_tail_days"].map(_classify)
    return m.sort_values("soh_flat_tail_days", ascending=False).reset_index(drop=True)


def main() -> None:
    cfg = load_config()
    pq = cfg.processed_dir / "battery_timeseries_all.parquet"
    df = pd.read_parquet(pq, columns=["user_id", "timestamp", "fullChargeCapacity"])
    m = compute_update_status(df)

    out = cfg.processed_dir / "soh_update_status.csv"
    m.to_csv(out, index=False)

    counts = m["soh_update_status"].value_counts().reindex(STATUS_ORDER).fillna(0).astype(int)
    print(f"wrote {out}  ({len(m)} users)")
    print(f"thresholds: stale >= {STALE_DAYS}d, very_stale >= {VERY_STALE_DAYS}d")
    print("classification:")
    for k in STATUS_ORDER:
        print(f"  {k:<11} {counts[k]:>4}")
    print("\ntop 8 longest-stale SoH:")
    print(m.head(8)[["user_id", "soh_flat_tail_days", "fcc_distinct",
                     "soh_last_change_ts", "soh_update_status"]].to_string(index=False))


if __name__ == "__main__":
    main()
