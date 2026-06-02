"""Load and clean one user's raw files into tidy pandas structures."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import schema

log = logging.getLogger(__name__)

# Columns load_battery cannot proceed without (timestamp + the two it maps).
_REQUIRED_BATTERY_COLS = {"timestamp", "acdcMode", "chargeStatus"}


@dataclass
class UserData:
    """All parsed artifacts for a single user. Missing files => None/empty."""

    safe_id: str
    user_id: str
    battery: pd.DataFrame                      # cleaned time-series (may be empty)
    info: Optional[pd.Series] = None           # battery_info row
    vendor: Optional[pd.Series] = None         # vendor row
    drain: Optional[pd.DataFrame] = None       # sleep-study drain events
    product: Dict[str, object] = field(default_factory=dict)  # model/vendor/uuid

    @property
    def design_capacity(self) -> Optional[float]:
        """Design capacity (mAh), preferring battery_info, then vendor."""
        for src in (self.info, self.vendor):
            if src is not None and "DesignCapacity" in src:
                val = pd.to_numeric(src["DesignCapacity"], errors="coerce")
                if pd.notna(val) and val > 0:
                    return float(val)
        return None

    @property
    def device_model(self) -> Optional[str]:
        return self.product.get("model")

    @property
    def manufacturer(self) -> Optional[str]:
        if self.vendor is not None and "Manufacturer" in self.vendor:
            m = self.vendor["Manufacturer"]
            return str(m).strip() if pd.notna(m) else None
        return None


def _read_csv_safe(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return pd.read_csv(path, skipinitialspace=True, index_col=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, OSError) as exc:
        log.warning("malformed/unreadable CSV %s: %s", path, exc)
        return None


def load_battery(path: Path) -> pd.DataFrame:
    """Parse the main battery time-series: typed, de-duplicated, time-sorted."""
    empty = pd.DataFrame(columns=schema.BATTERY_COLUMNS)
    if not path.exists() or path.stat().st_size == 0:
        return empty
    try:
        # index_col=False stops a uniform trailing comma from silently promoting
        # the timestamp column to the index; on_bad_lines warns+skips ragged rows.
        df = pd.read_csv(path, skipinitialspace=True, index_col=False, on_bad_lines="warn")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, OSError) as exc:
        log.warning("malformed/unreadable battery CSV %s: %s", path, exc)
        return empty
    if df.empty:
        return empty
    # A structurally broken header (missing/renamed required cols) => treat as
    # no-history rather than crashing the whole cohort run.
    if not _REQUIRED_BATTERY_COLS.issubset(df.columns):
        missing = _REQUIRED_BATTERY_COLS - set(df.columns)
        log.warning("battery CSV %s missing required columns %s; skipping", path, sorted(missing))
        return empty

    # Parse timestamp; drop rows we cannot place in time.
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], format=schema.BATTERY_TIMESTAMP_FORMAT, errors="coerce"
    )
    df = df.dropna(subset=["timestamp"])

    # Coerce numeric columns.
    for col in schema.BATTERY_NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop exact duplicate rows (cumulative files are clean, but be safe), sort.
    df = df.drop_duplicates().sort_values("timestamp").reset_index(drop=True)

    # Clip the percentage to a sane range; physically it is 0..100.
    if "remainingCapacityInPercentage" in df:
        df["remainingCapacityInPercentage"] = df["remainingCapacityInPercentage"].clip(0, 100)

    # Derived convenience columns.
    df["acdc_label"] = df["acdcMode"].map(schema.ACDC_MODE)
    df["charge_label"] = df["chargeStatus"].map(schema.CHARGE_STATUS)
    return df


def _read_single_row(path: Path) -> Optional[pd.Series]:
    df = _read_csv_safe(path)
    if df is None or df.empty:
        return None
    row = df.iloc[0].copy()
    # Strip whitespace from string-like values (these CSVs use ", " separators).
    return row.map(lambda v: v.strip() if isinstance(v, str) else v)


def load_info(path: Path) -> Optional[pd.Series]:
    return _read_single_row(path)


def load_vendor(path: Path) -> Optional[pd.Series]:
    return _read_single_row(path)


def load_drain(path: Path) -> Optional[pd.DataFrame]:
    df = _read_csv_safe(path)
    if df is None or df.empty:
        return None
    df.columns = [c.strip() for c in df.columns]
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()
    if "Start Time" in df:
        df["Start Time"] = pd.to_datetime(df["Start Time"], errors="coerce")
    # "% CAPACITY REMAINING AT START" arrives like "74%" -> numeric 74.
    pct_col = "% CAPACITY REMAINING AT START"
    if pct_col in df:
        df[pct_col] = pd.to_numeric(
            df[pct_col].astype(str).str.replace("%", "", regex=False), errors="coerce"
        )
    # Duration "HH:MM:SS" -> minutes.
    if "Duration" in df:
        td = pd.to_timedelta(df["Duration"], errors="coerce")
        df["duration_min"] = td.dt.total_seconds() / 60.0
    return df


def load_product(path: Path) -> Dict[str, object]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            d = json.load(fh)
        if not isinstance(d, dict):     # a top-level list/scalar has no .get()
            return {}
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        log.warning("malformed/unreadable product.json %s: %s", path, exc)
        return {}
    return {
        "model": d.get(schema.PRODUCT_MODEL_KEY),
        "vendor": d.get(schema.PRODUCT_VENDOR_KEY),
        "uuid": d.get(schema.PRODUCT_UUID_KEY),
        "name": d.get("Name"),
    }


def load_user(user_dir: Path, user_id: Optional[str] = None) -> UserData:
    """Load every artifact present in ``user_dir`` into a :class:`UserData`."""
    user_dir = Path(user_dir)
    safe_id = user_dir.name
    battery = load_battery(user_dir / "battery.csv")
    return UserData(
        safe_id=safe_id,
        user_id=user_id or safe_id,
        battery=battery,
        info=load_info(user_dir / "battery_info.csv"),
        vendor=load_vendor(user_dir / "vendor.csv"),
        drain=load_drain(user_dir / "drain_rate.csv"),
        product=load_product(user_dir / "product.json"),
    )


def iter_user_dirs(raw_dir: Path) -> List[Path]:
    """Return per-user directories under ``raw_dir`` (those holding a battery.csv)."""
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        return []
    return sorted(
        p for p in raw_dir.iterdir()
        if p.is_dir() and (p / "battery.csv").exists()
    )
