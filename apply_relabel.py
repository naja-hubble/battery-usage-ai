"""One-shot migration: propagate vendor-alias merges + the new active threshold to
existing data/processed artifacts.

Both changes are pure relabel / reclassify (vendor name remap; status re-bucketed from
the already-computed soh_flat_tail_days), so no feature or FCC recompute is needed —
this is exactly equivalent to a full rebuild, just far cheaper. Source of truth
(vendor_normalize.ALIAS_MAP, soh_update_status thresholds) is already updated.

    python apply_relabel.py
"""
from __future__ import annotations

import pandas as pd

from battery_usage.config import load_config
from vendor_normalize import ALIAS_MAP
from soh_update_status import _classify, STALE_DAYS, VERY_STALE_DAYS


def _amap(v):
    return ALIAS_MAP.get(v, v) if isinstance(v, str) else v


def main() -> None:
    cfg = load_config()
    pdir = cfg.processed_dir

    # 1) parquet: remap batt_vendor
    pq = pdir / "battery_timeseries_all.parquet"
    df = pd.read_parquet(pq)
    df["batt_vendor"] = df["batt_vendor"].map(_amap)
    df.to_parquet(pq, index=False)
    print("parquet vendors ->", sorted(df["batt_vendor"].dropna().unique()))

    # 2) user_master.csv: remap batt_vendor
    p = pdir / "user_master.csv"
    m = pd.read_csv(p)
    m["batt_vendor"] = m["batt_vendor"].map(_amap)
    m.to_csv(p, index=False)

    # 3) soh_reason_features.csv: remap vendor + reclassify status (new threshold)
    p = pdir / "soh_reason_features.csv"
    t = pd.read_csv(p)
    t["batt_vendor"] = t["batt_vendor"].map(_amap)
    t["soh_update_status"] = t["soh_flat_tail_days"].map(_classify)
    t.to_csv(p, index=False)

    # 4) soh_update_status.csv: reclassify status
    p = pdir / "soh_update_status.csv"
    s = pd.read_csv(p)
    s["soh_update_status"] = s["soh_flat_tail_days"].map(_classify)
    s.to_csv(p, index=False)

    print(f"thresholds: stale>={STALE_DAYS}d, very_stale>={VERY_STALE_DAYS}d")
    print("status counts:", t["soh_update_status"].value_counts().to_dict())


if __name__ == "__main__":
    main()
