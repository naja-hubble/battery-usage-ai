"""Per-user usage & battery-health feature extraction.

``extract_features(user_data, cfg)`` returns a flat dict of scalar metrics — one
row of the cohort table. Helper functions return the intermediate time-series /
session frames used by the plotting layer.

Metric groups
-------------
* identity   : ids, device model, manufacturer
* coverage   : observation window, sample count, sampling cadence
* health     : SOH (vs design and vs peak), capacity fade, post-peak fade rate
               (fade since the healthiest sample, per cycle / per year)
* cycles     : cycle count, cycles per month/year
* usage mode : AC vs battery time/event ratios, low-battery exposure
* stress     : time held at full charge, high-temperature hours, throughput
* sessions   : discharge-session count, depth-of-discharge, drain rate
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import Config
from .parse import UserData

# Below these post-peak spans, the fade RATE is dominated by sampling noise and is
# suppressed (left as None) rather than reported as a wildly extrapolated value.
_MIN_POSTPEAK_YEARS = 0.1     # ~37 days
_MIN_POSTPEAK_CYCLES = 5


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if b == 0 or pd.isna(a) or pd.isna(b):
        return None
    return float(a) / float(b)


def sample_weights(ts: pd.Series, max_gap_hours: float) -> np.ndarray:
    """Hours each sample 'represents' = gap to the next sample, capped.

    The last sample gets 0 weight (no following interval). Capping prevents long
    logger-asleep gaps from dominating time-weighted ratios.
    """
    if len(ts) < 2:
        return np.zeros(len(ts))
    deltas = ts.diff().shift(-1).dt.total_seconds().to_numpy() / 3600.0
    deltas = np.nan_to_num(deltas, nan=0.0)
    deltas = np.clip(deltas, 0.0, max_gap_hours)
    return deltas


def discharge_sessions(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Detect on-battery discharge sessions (contiguous acdcMode==0 runs)."""
    cols = ["start", "end", "duration_min", "start_pct", "end_pct", "dod", "drain_pct_per_hr"]
    if df.empty or "acdcMode" not in df:
        return pd.DataFrame(columns=cols)

    on_batt = (df["acdcMode"] == 0).to_numpy()
    # Run id increments whenever the state changes.
    run_id = np.cumsum(np.concatenate([[True], on_batt[1:] != on_batt[:-1]]))
    work = df.assign(_run=run_id, _on=on_batt)

    a = cfg.analysis
    rows: List[dict] = []
    for _, g in work[work["_on"]].groupby("_run"):
        start, end = g["timestamp"].iloc[0], g["timestamp"].iloc[-1]
        dur_min = (end - start).total_seconds() / 60.0
        start_pct = g["remainingCapacityInPercentage"].iloc[0]
        end_pct = g["remainingCapacityInPercentage"].iloc[-1]
        dod = start_pct - end_pct
        # NaN dod (a malformed % cell) must be rejected explicitly — `NaN < 3`
        # is False, so it would otherwise slip past the threshold as a junk session.
        if pd.isna(dod) or dur_min < a["min_session_minutes"] or dod < a["min_session_drain_pct"]:
            continue
        drain_rate = _safe_div(dod, dur_min / 60.0)
        rows.append({
            "start": start, "end": end, "duration_min": dur_min,
            "start_pct": start_pct, "end_pct": end_pct, "dod": dod,
            "drain_pct_per_hr": drain_rate,
        })
    return pd.DataFrame(rows, columns=cols)


def soh_timeseries(df: pd.DataFrame, design_capacity: Optional[float]) -> pd.DataFrame:
    """Daily State-of-Health series from fullChargeCapacity.

    SOH is reported both vs design capacity and vs the observed peak FCC (the best
    estimate of healthy capacity when the logged history starts mid-life).
    """
    if df.empty or "fullChargeCapacity" not in df:
        return pd.DataFrame(columns=["date", "fcc", "soh_design", "soh_peak", "cycleCount"])
    valid = df[df["fullChargeCapacity"] > 0].copy()
    if valid.empty:
        return pd.DataFrame(columns=["date", "fcc", "soh_design", "soh_peak", "cycleCount"])
    valid["date"] = valid["timestamp"].dt.floor("D")
    daily = valid.groupby("date").agg(
        fcc=("fullChargeCapacity", "median"),
        cycleCount=("cycleCount", "max"),
    ).reset_index()
    peak = valid["fullChargeCapacity"].max()
    daily["soh_peak"] = daily["fcc"] / peak * 100.0
    if design_capacity and design_capacity > 0:
        daily["soh_design"] = daily["fcc"] / design_capacity * 100.0
    else:
        daily["soh_design"] = np.nan
    return daily


def extract_features(ud: UserData, cfg: Config) -> Dict[str, object]:
    df = ud.battery
    a = cfg.analysis
    f: Dict[str, object] = {
        "safe_id": ud.safe_id,
        "user_id": ud.user_id,
        "device_model": ud.device_model,
        "manufacturer": ud.manufacturer,
        "design_capacity": ud.design_capacity,
        "n_samples": int(len(df)),
    }
    if df.empty:
        return f

    # ---- coverage ----
    first_ts, last_ts = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    span_days = (last_ts - first_ts).total_seconds() / 86400.0
    f["first_ts"] = first_ts.isoformat()
    f["last_ts"] = last_ts.isoformat()
    f["observation_days"] = round(span_days, 2)
    median_gap_min = df["timestamp"].diff().dt.total_seconds().median() / 60.0
    f["median_sample_gap_min"] = round(float(median_gap_min), 2) if pd.notna(median_gap_min) else None

    # ---- health (SOH / fade) ----
    fcc = df["fullChargeCapacity"].dropna()
    fcc = fcc[fcc > 0]
    design = ud.design_capacity
    capacity_fade_pct = None
    peak_ts = None          # timestamp of the healthiest (peak-FCC) sample
    peak_cyc = None         # cycle count at that sample
    if not fcc.empty:
        fcc_first, fcc_last, fcc_peak = float(fcc.iloc[0]), float(fcc.iloc[-1]), float(fcc.max())
        # Anchor on the LAST sample at peak capacity (where decline begins), so a long
        # healthy plateau isn't counted as "fading" — idxmax() would pick the first.
        peak_idx = fcc[fcc == fcc_peak].index[-1]
        peak_ts = df.loc[peak_idx, "timestamp"]
        peak_cyc = df.loc[peak_idx, "cycleCount"]
        f["fcc_first"] = fcc_first
        f["fcc_last"] = fcc_last
        f["fcc_peak"] = fcc_peak
        f["soh_design_pct"] = round(fcc_last / design * 100, 2) if design else None
        f["soh_peak_pct"] = round(fcc_last / fcc_peak * 100, 2) if fcc_peak else None
        capacity_fade_pct = (fcc_peak - fcc_last) / fcc_peak * 100 if fcc_peak else None
        f["capacity_fade_pct"] = round(capacity_fade_pct, 2) if capacity_fade_pct is not None else None

    # ---- cycles ----
    cyc = df["cycleCount"].dropna()
    if not cyc.empty:
        cyc_first, cyc_last = float(cyc.min()), float(cyc.max())
        cycles_total = cyc_last - cyc_first
        f["cycle_count_last"] = cyc_last
        f["cycles_in_window"] = cycles_total
        years = span_days / 365.25 if span_days > 0 else None
        months = span_days / 30.44 if span_days > 0 else None
        f["cycles_per_month"] = round(_safe_div(cycles_total, months), 2) if months else None
        f["cycles_per_year"] = round(_safe_div(cycles_total, years), 2) if years else None
        # Fade RATE: capacity_fade_pct is measured peak->last, so its denominator
        # must be the post-peak interval too (not the whole window), else the rate
        # is understated when the peak is logged mid-history. Guard short intervals
        # where the rate would be dominated by noise.
        if capacity_fade_pct is not None and peak_cyc is not None and pd.notna(peak_cyc):
            cycles_since_peak = cyc_last - float(peak_cyc)
            if cycles_since_peak >= _MIN_POSTPEAK_CYCLES:
                f["fade_pct_per_100_cycles"] = round(capacity_fade_pct / cycles_since_peak * 100, 3)
        if capacity_fade_pct is not None and peak_ts is not None:
            years_since_peak = (last_ts - peak_ts).total_seconds() / 86400.0 / 365.25
            if years_since_peak >= _MIN_POSTPEAK_YEARS:
                f["fade_pct_per_year"] = round(capacity_fade_pct / years_since_peak, 3)

    # ---- usage mode (AC vs battery) ----
    w = sample_weights(df["timestamp"], a["max_sample_gap_hours"])
    total_w = w.sum()
    ac_mask = (df["acdcMode"] == 1).to_numpy()
    f["ac_event_ratio"] = round(float(ac_mask.mean()), 4)
    f["ac_time_ratio"] = round(float(w[ac_mask].sum() / total_w), 4) if total_w > 0 else None
    f["battery_time_ratio"] = round(1 - w[ac_mask].sum() / total_w, 4) if total_w > 0 else None
    pct = df["remainingCapacityInPercentage"]
    f["mean_pct_remaining"] = round(float(pct.mean()), 2)
    f["median_pct_remaining"] = round(float(pct.median()), 2)
    low_mask = (pct < 20).to_numpy()
    f["time_ratio_below_20pct"] = round(float(w[low_mask].sum() / total_w), 4) if total_w > 0 else None

    # ---- stress / maintenance ----
    full_plugged = ((df["acdcMode"] == 1) & (pct >= 95)).to_numpy()
    f["time_ratio_full_on_ac"] = round(float(w[full_plugged].sum() / total_w), 4) if total_w > 0 else None
    for col, name in [
        ("hoursAtFullCharge", "hours_at_full_charge"),
        ("hoursAtHighTemperature", "hours_high_temp"),
        ("totalChargedCapacity", "total_charged_capacity"),
        ("totalBatteryAwakeHrs", "total_awake_hrs"),
    ]:
        if col in df and df[col].notna().any():
            f[name + "_last"] = float(df[col].max())
    awake = f.get("total_awake_hrs_last")
    f["frac_awake_high_temp"] = round(_safe_div(f.get("hours_high_temp_last"), awake), 4) if awake else None

    # ---- discharge sessions ----
    sess = discharge_sessions(df, cfg)
    f["n_discharge_sessions"] = int(len(sess))
    if not sess.empty:
        f["mean_dod_pct"] = round(float(sess["dod"].mean()), 2)
        f["median_dod_pct"] = round(float(sess["dod"].median()), 2)
        f["mean_session_minutes"] = round(float(sess["duration_min"].mean()), 1)
        f["median_drain_pct_per_hr"] = round(float(sess["drain_pct_per_hr"].median()), 2)

    # ---- sleep drain (modern standby) ----
    if ud.drain is not None and not ud.drain.empty and "duration_min" in ud.drain:
        d = ud.drain
        dur = d["duration_min"].fillna(0)
        f["sleep_events"] = int(len(d))
        f["sleep_total_hours"] = round(float(dur.sum()) / 60.0, 2)
    return f
