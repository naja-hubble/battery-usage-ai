"""Final-validation tests (spec section 1.7): right-censoring, large-gap handling, label
ordering, effective-step boundaries, deterministic dedup, active-user regression, totals.

Run:  python -m pytest tests/test_fcc_final_validation.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battery_usage.fcc_learning import (                       # noqa: E402
    extract_user_episodes, process_user, _sorted_unique, fcc_step_indicator,
    DEFAULT_CONFIG, FccLearningConfig,
)
from battery_usage import fcc_final as F                       # noqa: E402

BASE = pd.Timestamp("2024-01-01 00:00:00")


def _df(hours, rsoc, fcc, cyc=None, acdc=None, soh=None):
    n = len(rsoc)
    return pd.DataFrame({
        "user_id": ["u"] * n,
        "timestamp": [BASE + pd.Timedelta(hours=h) for h in hours],
        "remainingCapacityInPercentage": rsoc,
        "fullChargeCapacity": fcc,
        "cycleCount": cyc if cyc is not None else list(range(n)),
        "acdcMode": acdc if acdc is not None else [0] * n,
        "serialNumber": ["SN1"] * n,
        "soh_design_pct": soh if soh is not None else [f / 50.0 for f in fcc],
    })


def _primary(eps):
    return [e for e in eps if e["threshold_name"] == "primary_80_20_80"]


# 1. episode_end + 72h > last_ts -> censored, not no_response
def test_censored_window_not_no_response():
    # episode (0,2,4) ends at hour 4; series ends at hour 5 -> 72h window extends past last_ts.
    g = _df([0, 1, 2, 3, 4, 5], [100, 50, 10, 30, 80, 100], [5000] * 6)
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert e["window_72h_complete"] is False
    assert e["fcc_response_status_72h"] == "censored"     # NOT "no_response"
    assert e["fcc_response_status_24h"] == "censored"


def test_complete_window_no_response():
    # last sample far beyond end+72h, FCC flat -> a genuine complete no_response.
    g = _df([0, 1, 2, 3, 4, 500], [100, 50, 10, 30, 80, 90], [5000] * 6)
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert e["window_72h_complete"] is True
    assert e["fcc_response_status_72h"] == "no_response"


# 2. OK==0 but large_gap>0 -> NOT gauge high confidence
def test_large_gap_blocks_gauge_high():
    base = {c: 0 for c in [
        "tail_n_80_20_80_ok", "tail_n_90_10_90_ok", "tail_n_80_20_80_large_gap",
        "tail_n_90_10_90_large_gap", "tail_cycle_delta", "tail_min_rsoc", "tail_rsoc_swing",
        "tail_ac_time_ratio", "fcc_changes"]}
    r = pd.Series({**base, "fcc_no_or_low_change_candidate": True, "flat_tail_days": 300,
                   "data_quality_label": "QUALITY_OK", "obs_days": 400, "n_samples": 5000,
                   "tail_cycle_delta": 5, "tail_ac_time_ratio": 0.9, "tail_min_rsoc": 50,
                   "tail_rsoc_swing": 30, "tail_n_80_20_80_large_gap": 2})
    # with large_gap present, _no_opportunity is False -> not gauge high/medium
    assert F._gauge_high(r, F.DEFAULT_FINAL_THRESHOLDS) is False
    out = F.classify_user_final(r)
    assert out["final_label"] != F.LABEL_GAUGE
    assert out["final_label"] == F.LABEL_WATCH
    assert out["watch_subreason"] == "WATCH_POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS"


# 3. tail OK opportunity with complete no-response -> FW (not GAUGE)
def test_complete_no_response_routes_to_fw_not_gauge():
    base = {c: 0 for c in [
        "tail_n_90_10_90_ok", "tail_n_80_20_80_large_gap", "tail_n_90_10_90_large_gap",
        "tail_min_rsoc", "tail_rsoc_swing", "tail_ac_time_ratio"]}
    r = pd.Series({**base, "fcc_no_or_low_change_candidate": True, "flat_tail_days": 300,
                   "data_quality_label": "QUALITY_OK", "obs_days": 400, "n_samples": 5000,
                   "fcc_changes": 0, "tail_cycle_delta": 60, "tail_n_80_20_80_ok": 5,
                   "tail_n_unresponded_80_20_80_complete_window": 5,
                   "tail_n_unresponded_80_20_80_complete_window_72h": 5,
                   "tail_n_unresponded_90_10_90_complete_window": 0,
                   "tail_n_unresponded_90_10_90_complete_window_72h": 0,
                   "relevant_response_rate_72h": 0.0})
    out = F.classify_user_final(r)
    assert out["final_label"] == F.LABEL_FW
    assert out["recommended_action"] == F.ACTION_FW_CHECK


# 4. effective FCC step thresholds at 49/50/99/100 mWh
@pytest.mark.parametrize("thr,steps_expected", [(49.0, 2), (50.0, 2), (99.0, 1), (100.0, 1)])
def test_effective_step_boundaries(thr, steps_expected):
    # FCC drops: 5000 -> 4950 (50 mWh) -> 4850 (100 mWh). 49->both, 50->both, 99->only 100, 100->only 100.
    fcc = np.array([5000., 4950., 4850.])
    is_step, _ = fcc_step_indicator(fcc, thr)
    assert int(is_step.sum()) == steps_expected


# 5. duplicate timestamp -> deterministic via stable sort (same input -> same output,
#    and keep="last" retains the last SOURCE row among equal timestamps).
def test_duplicate_timestamp_deterministic():
    g = _df([0, 0, 1], [100, 80, 10], [5000, 4900, 4900])   # two rows at hour 0 (100 then 80)
    s1 = _sorted_unique(g)
    s2 = _sorted_unique(g.copy())
    assert s1.reset_index(drop=True).equals(s2.reset_index(drop=True))   # deterministic
    assert len(s1) == 2
    assert s1.iloc[0]["remainingCapacityInPercentage"] == 80     # LAST source row at hour 0 kept


# 6. active-like user is never gauge/fw
def test_active_like_user_not_actionable():
    # FCC keeps changing recently -> short flat tail, not a candidate.
    hours = list(range(0, 40))
    rsoc = [100, 20] * 20
    fcc = list(np.linspace(5000, 4800, 40).round())          # frequently changing FCC
    g = _df(hours, rsoc, fcc, cyc=list(range(40)))
    feat, _ = process_user("u", g, FccLearningConfig())
    r = pd.Series({**feat, "fcc_no_or_low_change_candidate": False})
    out = F.classify_user_final(r)
    assert out["final_label"] in (F.LABEL_NORMAL, F.LABEL_REVIEW)
    assert out["recommended_action"] in (F.ACTION_NONE, F.ACTION_REVIEW)


# 7. mutual exclusivity + totals on a small synthetic frame
def test_labels_mutually_exclusive_and_total():
    rows = []
    common = {c: 0 for c in [
        "tail_n_80_20_80_ok", "tail_n_90_10_90_ok", "tail_n_80_20_80_large_gap",
        "tail_n_90_10_90_large_gap", "tail_n_unresponded_80_20_80_complete_window",
        "tail_n_unresponded_80_20_80_complete_window_72h",
        "tail_n_unresponded_90_10_90_complete_window", "tail_n_unresponded_90_10_90_complete_window_72h",
        "tail_n_censored_80_20_80", "tail_n_censored_90_10_90", "tail_cycle_delta",
        "tail_min_rsoc", "tail_max_rsoc", "tail_rsoc_swing", "tail_ac_time_ratio", "fcc_changes"]}
    common.update({"obs_days": 400, "n_samples": 5000, "data_quality_label": "QUALITY_OK",
                   "flat_tail_days": 300, "relevant_response_rate_72h": np.nan})
    rows.append(pd.Series({**common, "fcc_no_or_low_change_candidate": False}))           # normal
    rows.append(pd.Series({**common, "obs_days": 30, "fcc_no_or_low_change_candidate": True}))  # review
    rows.append(pd.Series({**common, "fcc_no_or_low_change_candidate": True, "tail_cycle_delta": 5,
                           "tail_ac_time_ratio": 0.9, "tail_min_rsoc": 50}))              # gauge
    df = pd.DataFrame(rows)
    res = F.classify_frame_final(df)
    assert res["final_label"].isin(F.LABEL_ORDER).all()
    assert len(res) == len(df)
    assert res.iloc[0]["final_label"] == F.LABEL_NORMAL
    assert res.iloc[1]["final_label"] == F.LABEL_REVIEW
    assert res.iloc[2]["final_label"] == F.LABEL_GAUGE
