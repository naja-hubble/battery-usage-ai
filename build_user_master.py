"""Build a consolidated, human-readable master table (one row per user).

Joins identity + device + battery-pack + observed-from-time-series fields and keys
them all on the unique ``user_id`` (plus the strong hardware ids: device UUID and
machine serial), so a person can understand the whole cohort at a glance.

Reuses the package's own loaders / feature code (``parse.load_user``,
``features.extract_features``) so the derived numbers match the analysis pipeline
exactly — this is a *view*, not a second source of truth.

    python build_user_master.py

Writes ``data/processed/user_master.csv`` (git-ignored) and prints a readable view.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from battery_usage.config import load_config, Config
from battery_usage.parse import load_user, iter_user_dirs, UserData
from battery_usage.features import extract_features
from vendor_normalize import normalize_vendor


def _vendor_get(ud: UserData, key: str):
    """Read a field from the battery-vendor row, returning None if absent/NaN."""
    v = ud.vendor
    if v is not None and key in v:
        val = v[key]
        return val if pd.notna(val) else None
    return None


def _product_raw(user_dir: Path) -> Dict[str, object]:
    """Top-level product.json dict (it carries IdentifyingNumber / Name that the
    package's trimmed ``load_product`` drops)."""
    p = user_dir / "product.json"
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        with open(p, "r", encoding="utf-8-sig") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 - identity is best-effort, never fatal
        return {}


def build_master_row(user_dir: Path, cfg: Config) -> Dict[str, object]:
    ud = load_user(user_dir)
    feat = extract_features(ud, cfg)          # same derivations as the pipeline
    prod = _product_raw(user_dir)

    # user_id is "<DEVICE>_<winuser>"; DEVICE itself may contain hyphens, so split
    # on the LAST underscore.
    device_name, sep, win_user = ud.user_id.rpartition("_")
    if not sep:                                # no underscore -> all device name
        device_name, win_user = ud.user_id, ""

    df = ud.battery
    last = df.iloc[-1] if not df.empty else None      # most-recent observed sample

    return {
        # ---- key + identity --------------------------------------------------
        "user_id": ud.user_id,                         # primary key
        "device_name": device_name,
        "win_user": win_user,
        "device_uuid": prod.get("UUID")
            or (ud.info.get("product_uuid") if ud.info is not None else None),
        "machine_serial": prod.get("IdentifyingNumber"),   # e.g. PF5HTJH6
        "type_model": prod.get("Name"),                    # e.g. 21R4ZCZ9US
        "device_model": ud.device_model,                   # e.g. "ThinkPad T14s ..."
        "oem": prod.get("Vendor"),
        "ts_serial": (last["serialNumber"] if last is not None and "serialNumber" in df else None),
        # ---- battery pack (static nameplate) ---------------------------------
        # NOTE: cycleCount and FullChargeCapacity also appear in vendor.csv, but we
        # deliberately take them from the battery.csv time-series below (the live,
        # most-current source; the vendor snapshot lags by ~1 cycle). Only
        # vendor-exclusive nameplate fields are pulled here.
        "batt_vendor": normalize_vendor(ud.manufacturer),  # vendor.csv Manufacturer, normalized
        "batt_fru": _vendor_get(ud, "Id"),                 # vendor.csv Id = FRU (battery PN)
        "batt_pack_sn": _vendor_get(ud, "SerialNumber"),
        "batt_mfg_date": _vendor_get(ud, "ManufactureDate"),
        "design_capacity_mAh": ud.design_capacity,
        # ---- observed from the time-series (authoritative for cycle / FCC) ----
        "n_samples": feat.get("n_samples"),
        "first_ts": feat.get("first_ts"),
        "last_ts": feat.get("last_ts"),
        "observation_days": feat.get("observation_days"),
        "pct_last": (float(last["remainingCapacityInPercentage"])
                     if last is not None and pd.notna(last["remainingCapacityInPercentage"]) else None),
        "fcc_last_mAh": feat.get("fcc_last"),
        "fcc_peak_mAh": feat.get("fcc_peak"),
        "cycle_count_last": feat.get("cycle_count_last"),
        "soh_design_pct": feat.get("soh_design_pct"),
        "soh_peak_pct": feat.get("soh_peak_pct"),
        "capacity_fade_pct": feat.get("capacity_fade_pct"),
        "sleep_events": feat.get("sleep_events"),
    }


def build_master(cfg: Config) -> pd.DataFrame:
    rows = []
    for d in iter_user_dirs(cfg.raw_dir):
        try:
            rows.append(build_master_row(d, cfg))
        except Exception as exc:  # noqa: BLE001 - one bad user must not abort the run
            print(f"  WARN: skipping {d.name}: {exc!r}")
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("soh_peak_pct", ascending=False, na_position="last").reset_index(drop=True)
    return df


def main() -> None:
    cfg = load_config()
    df = build_master(cfg)
    if df.empty:
        print("No users found under", cfg.raw_dir,
              "- run `python -m battery_usage download` first.")
        return

    cfg.ensure_dirs()
    out = cfg.processed_dir / "user_master.csv"
    df.to_csv(out, index=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 30)

    print(f"\n=== Consolidated master: {len(df)} users x {df.shape[1]} fields -> {out} ===\n")

    # Per-user transposed view (one user = one readable block).
    for _, r in df.iterrows():
        print(f"--- {r['user_id']}   ({r.get('device_model') or '?'}) ---")
        print(r.to_string())
        print()

    # Compact cross-user headline table.
    key_cols = [c for c in [
        "user_id", "device_model", "design_capacity_mAh", "fcc_last_mAh",
        "soh_design_pct", "soh_peak_pct", "cycle_count_last",
        "observation_days", "n_samples",
    ] if c in df.columns]
    print("=== Headline table ===")
    print(df[key_cols].to_string(index=False))


if __name__ == "__main__":
    main()
