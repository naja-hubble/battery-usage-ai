"""Consolidate every user's battery time-series into ONE long dataframe.

Each downloaded user's cleaned ``battery.csv`` (typed, de-duplicated, time-sorted by
``parse.load_battery``) is stacked vertically, with the user's unique id attached to
every row so the whole cohort can be grouped / filtered / plotted from a single frame:

    df.groupby("user_id") ...

The static per-user attributes (UUID, serials, design capacity, ...) live in the
companion ``user_master.csv`` and join back on ``user_id``.

    python build_timeseries.py

Writes ``data/processed/battery_timeseries_all.parquet`` (git-ignored). Parquet
keeps dtypes (datetime/ints) and is ~5-10x smaller / faster than the CSV it
replaces for this multi-million-row frame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from battery_usage.config import load_config, Config
from battery_usage.parse import load_user, iter_user_dirs
from vendor_normalize import normalize_vendor

# Identity / context columns prepended to every sample row (join key + labels).
#   batt_vendor = vendor.csv "Manufacturer" (the battery cell/pack maker)
#   batt_fru    = vendor.csv "Id"          (the battery FRU = part number / PN)
_ID_COLS = ["user_id", "device_model", "batt_vendor", "batt_fru"]


def _vendor_field(ud, key):
    """Read a field from the battery-vendor row; None if absent/NaN."""
    v = ud.vendor
    if v is not None and key in v:
        val = v[key]
        return val if pd.notna(val) else None
    return None


def build_timeseries(cfg: Config) -> pd.DataFrame:
    frames = []
    for d in iter_user_dirs(cfg.raw_dir):
        ud = load_user(d)
        df = ud.battery
        if df.empty:
            print(f"  skip {d.name}: empty/unparseable battery series")
            continue
        df = df.copy()
        # Per-sample State-of-Health vs design capacity: FCC * 100 / DesignCapacity.
        # DesignCapacity is a per-user constant (battery_info.csv -> vendor.csv).
        # FCC <= 0 (or missing design capacity) -> NaN, matching the pipeline's FCC>0 rule.
        design = ud.design_capacity
        if design and design > 0:
            fcc = df["fullChargeCapacity"]
            df["soh_design_pct"] = (fcc * 100.0 / design).where(fcc > 0).round(2)
        else:
            df["soh_design_pct"] = np.nan
        # insert(0, ...) prepends, so add in reverse to land as
        # [user_id, device_model, batt_vendor, batt_fru, <battery cols>, soh_design_pct].
        df.insert(0, "batt_fru", _vendor_field(ud, "Id"))         # battery PN (FRU)
        df.insert(0, "batt_vendor", normalize_vendor(ud.manufacturer))   # normalized battery vendor
        df.insert(0, "device_model", ud.device_model)
        df.insert(0, "user_id", ud.user_id)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    allts = pd.concat(frames, ignore_index=True)
    # Stable order: per user, chronological.
    return allts.sort_values(["user_id", "timestamp"]).reset_index(drop=True)


def main() -> None:
    cfg = load_config()
    df = build_timeseries(cfg)
    if df.empty:
        print("No time-series found under", cfg.raw_dir,
              "- run `python -m battery_usage download` first.")
        return

    cfg.ensure_dirs()
    out = cfg.processed_dir / "battery_timeseries_all.parquet"
    df.to_parquet(out, index=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)

    print(f"\n=== Consolidated time-series: {len(df):,} rows x {df.shape[1]} cols "
          f"-> {out} ===\n")

    print("rows per user:")
    print(df.groupby("user_id").size().sort_values(ascending=False).to_string())

    print("\ntime span per user:")
    span = df.groupby("user_id")["timestamp"].agg(["min", "max", "count"])
    print(span.to_string())

    print("\ncolumns / dtypes:")
    print(df.dtypes.to_string())

    print("\nhead (5 rows):")
    print(df.head().to_string(index=False))


if __name__ == "__main__":
    main()
