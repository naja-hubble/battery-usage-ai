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
    "remainingCapacityInPercentage",  # = RSOC (remainingCapacity/fullChargeCapacity*100), 0-100
    "cycleCount",
    "serialNumber",
    "remainingCapacity",            # mWh (per Power Manager PWM decoder) — instantaneous
    "fullChargeCapacity",           # mWh — current full-charge capacity (drives SOH)
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

# chargeStatus (Power Manager PWM decoder):
#   0 => No activity (no charge or discharge current)
#   1 => Charge
#   2 => Discharge
CHARGE_STATUS: Dict[int, str] = {0: "no_activity", 1: "charging", 2: "discharging"}

# eventCat / "Event" (Power Manager PWM decoder):
#   0 => Autonomic (30-minute timer OR battery-insertion event) — the dominant periodic sample
#   1 => Login   2 => Logoff   3 => Suspend   4 => Resume   5 => AC/DC power source change
EVENT_CAT: Dict[int, str] = {
    0: "autonomic",
    1: "login",
    2: "logoff",
    3: "suspend",
    4: "resume",
    5: "ac_dc_change",
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
