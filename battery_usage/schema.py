"""Data schema for the formatted battery telemetry.

All column names, dtypes and categorical code maps are centralised here so the
parser and feature code stay in sync. Code-map semantics were derived empirically
from the data (see README "Data dictionary") and confirmed against the
acdcMode <-> capacity-trend relationship.
"""
from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# Main time-series: PmProgramData/battery/UP||<date>-<time>.csv
# These files are CUMULATIVE — each newer file is a superset of older ones, so
# only the latest file per user need be downloaded.
# ---------------------------------------------------------------------------
BATTERY_COLUMNS: List[str] = [
    "timestamp",
    "eventCat",
    "chargeStatus",
    "acdcMode",
    "remainingCapacityInPercentage",
    "cycleCount",
    "serialNumber",
    "remainingCapacity",            # mAh (or mWh) — instantaneous
    "fullChargeCapacity",           # mAh — current full-charge capacity (drives SOH)
    "RemainingTime",                # minutes estimate
    "totalChargedCapacity",         # cumulative throughput counter
    "totalBatteryAwakeHrs",         # cumulative awake-on-battery hours
    "hoursAtFullCharge",            # cumulative stress counter
    "hoursAtHighTemperature",       # cumulative stress counter
    "hoursAtFullChargeAndHighTemperature",
]

BATTERY_TIMESTAMP_FORMAT = "%m/%d/%Y %H:%M:%S"

# Numeric columns (everything except timestamp + serialNumber).
BATTERY_NUMERIC_COLUMNS: List[str] = [
    "eventCat",
    "chargeStatus",
    "acdcMode",
    "remainingCapacityInPercentage",
    "cycleCount",
    "remainingCapacity",
    "fullChargeCapacity",
    "RemainingTime",
    "totalChargedCapacity",
    "totalBatteryAwakeHrs",
    "hoursAtFullCharge",
    "hoursAtHighTemperature",
    "hoursAtFullChargeAndHighTemperature",
]

# Cumulative (monotonically non-decreasing) counters — used by features to take
# the last value as a lifetime total and to guard against logger resets.
BATTERY_CUMULATIVE_COLUMNS: List[str] = [
    "cycleCount",
    "totalChargedCapacity",
    "totalBatteryAwakeHrs",
    "hoursAtFullCharge",
    "hoursAtHighTemperature",
    "hoursAtFullChargeAndHighTemperature",
]

# ---------------------------------------------------------------------------
# Categorical code maps (empirically derived)
# ---------------------------------------------------------------------------
# acdcMode: 1 => on AC (capacity trends up), 0 => on battery (capacity trends down).
ACDC_MODE: Dict[int, str] = {0: "battery", 1: "ac"}

# chargeStatus correlates 1:1 with power state:
#   2 => discharging (always paired with acdcMode==0)
#   1 => charging    (acdcMode==1)
#   0 => ac_idle / maintained full (acdcMode==1, not actively charging)
CHARGE_STATUS: Dict[int, str] = {0: "ac_idle", 1: "charging", 2: "discharging"}

# eventCat: 0 dominates (periodic sample); 1..5 are transition/marker events.
# Exact 1..5 semantics are not documented; treat as opaque categorical markers.
EVENT_CAT: Dict[int, str] = {
    0: "periodic",
    1: "event_1",
    2: "event_2",
    3: "event_3",
    4: "event_4",
    5: "event_5",
}

# ---------------------------------------------------------------------------
# Auxiliary files
# ---------------------------------------------------------------------------
# PmProgramData/battery_info/UP||*.csv  (1 row)
BATTERY_INFO_COLUMNS = ["StartDate", "Serial Number", "DesignCapacity", "product_uuid"]

# sleepstudy_report_battery_vendor/UP||*.csv (1 row)
VENDOR_COLUMNS = [
    "tp-user-battery-sn", "Id", "Manufacturer", "SerialNumber", "ManufactureDate",
    "LongTerm", "RelativeCapacity", "DesignCapacity", "FullChargeCapacity", "CycleCount",
]

# sleepstudy_report_drain_rate/UP||*.csv  (many rows — modern-standby drain events)
DRAIN_RATE_COLUMNS = [
    "serialNumber", "Start Time", "Duration", "State", "% CAPACITY REMAINING AT START",
]

# wmi/wmi.Win32_ComputerSystemProduct/UP||*.json -> device model lives in top-level
# "Version" (e.g. "ThinkPad T14s Gen 4"), "Vendor", "Name", "UUID".
PRODUCT_MODEL_KEY = "Version"
PRODUCT_VENDOR_KEY = "Vendor"
PRODUCT_UUID_KEY = "UUID"

# Maps a download "artifact" name -> (category sub-path under the user folder,
# filename extension). The latest file in each category is what we fetch.
ARTIFACT_PATHS: Dict[str, Dict[str, str]] = {
    "battery":      {"subpath": "PmProgramData/battery/",                 "ext": ".csv"},
    "battery_info": {"subpath": "PmProgramData/battery_info/",            "ext": ".csv"},
    "vendor":       {"subpath": "sleepstudy_report_battery_vendor/",      "ext": ".csv"},
    "drain_rate":   {"subpath": "sleepstudy_report_drain_rate/",          "ext": ".csv"},
    "product":      {"subpath": "wmi/wmi.Win32_ComputerSystemProduct/",   "ext": ".json"},
}
