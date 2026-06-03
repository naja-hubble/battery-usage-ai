"""Unit tests for the FCC-learning audit layer (episode extraction + FCC response).

Covers spec section 12 (the 7 required cases) plus a few robustness checks for the
missing-FCC / NaN-response handling and classifier mutual-exclusivity.

Run with:  python -m pytest tests/test_fcc_learning.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battery_usage.fcc_learning import (                       # noqa: E402
    extract_high_low_high_episodes, extract_user_episodes, fcc_step_indicator,
    _sorted_unique, process_user, _response_rate,
)
from battery_usage import fcc_action_classifier as C           # noqa: E402

BASE = pd.Timestamp("2024-01-01 00:00:00")


def _df(hours, rsoc, fcc, cyc=None, acdc=None):
    """Build a minimal per-user battery frame from hour-offsets + parallel lists."""
    n = len(rsoc)
    return pd.DataFrame({
        "user_id": ["u"] * n,
        "timestamp": [BASE + pd.Timedelta(hours=h) for h in hours],
        "remainingCapacityInPercentage": rsoc,
        "fullChargeCapacity": fcc,
        "cycleCount": cyc if cyc is not None else list(range(n)),
        "acdcMode": acdc if acdc is not None else [0] * n,
        "serialNumber": ["SN1"] * n,
    })


def _primary(eps):
    return [e for e in eps if e["threshold_name"] == "primary_80_20_80"]


# --------------------------------------------------------------------------- #
# 1 & 2: episode extraction (generic in high/low)
# --------------------------------------------------------------------------- #
def test_case1_80_20_80_extracts_one():
    seq = [100, 90, 50, 20, 10, 30, 80, 100]
    eps = extract_high_low_high_episodes(seq, 80, 20)
    assert eps == [(0, 3, 6)]            # start@100, low@first<=20, end@first>=80 again


def test_case2_no_8020_but_generic_7030_works():
    seq = [100, 70, 30, 100]
    assert extract_high_low_high_episodes(seq, 80, 20) == []      # never reaches <=20
    assert extract_high_low_high_episodes(seq, 70, 30) == [(0, 2, 3)]  # generic design


# --------------------------------------------------------------------------- #
# 3-5: FCC response timing
# --------------------------------------------------------------------------- #
def test_case3_change_during_episode():
    # 80_20_80 over idx 0..4; FCC steps at the low point (inside the episode).
    g = _df([0, 1, 2, 3, 4], [100, 50, 10, 30, 80],
            [5000, 5000, 4900, 4900, 4900])
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert (e["start_idx"], e["low_idx"], e["end_idx"]) == (0, 2, 4)
    assert e["fcc_changed_during_episode"] is True
    assert e["fcc_changed_24h"] is True   # change inside episode -> all windows True


def test_case4_change_within_72h_after_end():
    # FCC flat through the episode; steps 48h after the end (<=72h, >24h).
    g = _df([0, 1, 2, 3, 4, 5, 52], [100, 50, 10, 30, 80, 100, 90],
            [5000, 5000, 5000, 5000, 5000, 5000, 4900])
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert e["fcc_changed_during_episode"] is False
    assert e["fcc_changed_24h"] is False
    assert e["fcc_changed_72h"] is True
    assert e["fcc_changed_168h"] is True


def test_case5_change_after_72h_only_in_168h():
    # FCC steps 96h after the end: outside 72h, inside 168h.
    g = _df([0, 1, 2, 3, 4, 5, 100], [100, 50, 10, 30, 80, 100, 90],
            [5000, 5000, 5000, 5000, 5000, 5000, 4900])
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert e["fcc_changed_72h"] is False
    assert e["fcc_changed_168h"] is True


# --------------------------------------------------------------------------- #
# 6: missing FCC must NOT be read as a zero response
# --------------------------------------------------------------------------- #
def test_case6_missing_fcc_is_unknown_not_zero():
    g = _df([0, 1, 2, 3, 4, 5, 30], [100, 50, 10, 30, 80, 100, 90],
            [5000, 5000, 5000, 5000, 5000, np.nan, 5000])  # NaN inside the windows
    e = _primary(extract_user_episodes(g, "u"))[0]
    assert e["fcc_changed_72h"] is None        # unknown, NOT False
    assert e["fcc_changed_24h"] is None
    # And an unknown response is excluded from rate denominators (never counted as 0).
    assert np.isnan(_response_rate([e], "fcc_changed_72h"))


# --------------------------------------------------------------------------- #
# 7: out-of-order timestamps are handled after sorting
# --------------------------------------------------------------------------- #
def test_case7_unsorted_timestamps_sorted_first():
    order = [4, 0, 2, 6, 1, 5, 3, 7]                       # scrambled row order
    hours = [0, 1, 2, 3, 4, 5, 6, 7]
    rsoc = [100, 90, 50, 20, 10, 30, 80, 100]
    fcc = [5000] * 8
    g = _df([hours[i] for i in order], [rsoc[i] for i in order], [fcc[i] for i in order])
    g = _sorted_unique(g)
    e = _primary(extract_user_episodes(g, "u"))
    assert len(e) == 1
    ep = e[0]
    assert ep["start_idx"] < ep["low_idx"] < ep["end_idx"]
    assert ep["start_ts"] < ep["low_ts"] < ep["end_ts"]
    assert ep["start_rsoc"] >= 80 and ep["low_rsoc"] <= 20 and ep["end_rsoc"] >= 80


# --------------------------------------------------------------------------- #
# Robustness extras
# --------------------------------------------------------------------------- #
def test_start_boundary_step_not_counted_as_response():
    """Regression (review finding FCC-WIN-START-BOUNDARY): the only FCC step lands ON the
    episode's opening (high) sample — a transition that completed AS the episode opened,
    not during it. It must NOT be read as a response, else a genuine no-response user is
    masked out of FW_CHECK."""
    # idx: 0=pre(50), 1=open(85)<-step here, 2=low(15), 3=close(85), then flat high.
    g = _df([0, 1, 2, 3, 4, 5], [50, 85, 15, 85, 90, 95],
            [5000, 4900, 4900, 4900, 4900, 4900])      # single step at idx0->idx1
    eps = _primary(extract_user_episodes(g, "u"))
    assert len(eps) == 1
    e = eps[0]
    assert (e["start_idx"], e["low_idx"], e["end_idx"]) == (1, 2, 3)
    assert e["fcc_changed_during_episode"] is False    # step was at the open, not during
    assert e["fcc_changed_72h"] is False
    assert e["fcc_changed_168h"] is False
    # A genuine step at the LOW point inside the episode is still detected (sanity).
    g2 = _df([0, 1, 2, 3, 4, 5], [50, 85, 15, 85, 90, 95],
             [5000, 5000, 4900, 4900, 4900, 4900])     # step at idx1->idx2 (the low)
    e2 = _primary(extract_user_episodes(g2, "u"))[0]
    assert e2["fcc_changed_during_episode"] is True


def test_fcc_step_indicator_flags_nan_as_unknown():
    is_step, is_unknown = fcc_step_indicator(np.array([5000., 5000., np.nan, 4900.]), 1.0)
    assert not is_step.any()                 # no comparison involving NaN counts as a step
    assert is_unknown[2] and is_unknown[3]   # both neighbours of the NaN are unknown


def test_dedup_keeps_last_row_per_timestamp():
    g = _df([0, 0, 1], [100, 80, 10], [5000, 4900, 4900])   # duplicate ts at hour 0
    s = _sorted_unique(g)
    assert len(s) == 2
    assert s.iloc[0]["remainingCapacityInPercentage"] == 80  # the LAST of the dupes


def test_zero_fcc_change_anchors_tail_at_first_ts():
    # FCC never changes -> whole observation is the tail (last_fcc_change_ts == first_ts).
    g = _df(list(range(6)), [100, 50, 10, 30, 80, 100], [5000] * 6)
    feat, _ = process_user("u", g)
    assert feat["fcc_changes"] == 0
    assert pd.Timestamp(feat["last_fcc_change_ts"]) == g["timestamp"].min()


def test_classifier_labels_are_mutually_exclusive_and_total():
    # A handful of synthetic feature rows exercise each branch; every row gets exactly
    # one label drawn from the known set.
    cols = {c: 0 for c in [
        "obs_days", "n_samples", "flat_tail_days", "fcc_changes", "cycle_delta",
        "tail_cycle_delta", "tail_min_rsoc", "tail_max_rsoc", "tail_rsoc_swing",
        "tail_ac_time_ratio", "tail_n_80_20_80_ok", "tail_n_90_10_90_ok",
        "tail_n_85_15_85_ok", "total_n_80_20_80_ok",
        "tail_response_rate_80_20_80_72h", "tail_response_rate_90_10_90_72h",
        "total_response_rate_80_20_80_72h", "relevant_response_rate_72h",
    ]}
    base = pd.Series({**cols, "obs_days": 400, "n_samples": 5000,
                      "data_quality_label": "QUALITY_OK",
                      "fcc_no_or_low_change_candidate": True,
                      "relevant_response_rate_72h": np.nan,
                      "tail_response_rate_80_20_80_72h": np.nan,
                      "tail_response_rate_90_10_90_72h": np.nan,
                      "total_response_rate_80_20_80_72h": np.nan})
    rows = [
        base.copy(),
        pd.Series({**base.to_dict(), "obs_days": 50}),                       # review
        pd.Series({**base.to_dict(), "fcc_no_or_low_change_candidate": False}),  # normal
    ]
    labels = [C.classify_user(r)["final_label"] for r in rows]
    assert all(l in C.LABEL_ORDER for l in labels)
    assert C.classify_user(rows[1])["final_label"] == C.LABEL_REVIEW
    assert C.classify_user(rows[2])["final_label"] == C.LABEL_NORMAL
