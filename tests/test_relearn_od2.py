"""Unit tests for the OD2 gauge-relearn opportunity extractor (battery_usage/relearn_od2).

Locks the load-bearing invariants of the corrected opportunity definition:
  * Type A = full -> deep(<=6%) -> full (both ends full); back-to-back reuse.
  * Type B = charging through the 60-80% band -> full; drops below abort void the pass.
  * A Type-B degenerate low == start must not trip invalid_order.
  * censored is NEVER read as no_response (right-censoring safety carried from OD1).
  * The effective-step threshold (>=50 mWh) gates 'responded' vs 'no_response'.
  * NaN / out-of-range RSOC samples are skipped by both machines.
"""
import numpy as np
import pandas as pd
import pytest

from battery_usage.relearn_od2 import (
    Od2Config, TypeADef, TypeBDef, DEFAULT_OD2_CONFIG,
    process_user_od2, add_union_flags,
    extract_typeA_episodes, extract_typeB_episodes,
)

T0 = pd.Timestamp("2025-01-01 00:00:00")


def _series(rsoc, chg, fcc=None, hours=None, cyc=None):
    """Build a one-user frame. `hours` = per-sample offset hours (default 0.5h cadence)."""
    n = len(rsoc)
    if hours is None:
        ts = [T0 + pd.Timedelta(minutes=30 * i) for i in range(n)]
    else:
        ts = [T0 + pd.Timedelta(hours=h) for h in hours]
    if fcc is None:
        fcc = [50000.0] * n
    if cyc is None:
        cyc = list(range(n))
    return pd.DataFrame({
        "timestamp": ts,
        "remainingCapacityInPercentage": [float(x) if x is not None else np.nan for x in rsoc],
        "chargeStatus": [float(x) if x is not None else np.nan for x in chg],
        "acdcMode": [1.0] * n,
        "fullChargeCapacity": [float(x) for x in fcc],
        "cycleCount": [float(x) for x in cyc],
        "soh_design_pct": [99.0] * n,
    })


# --------------------------------------------------------------------------- #
# Type A
# --------------------------------------------------------------------------- #
def test_typeA_full_deep_full_single_episode():
    rsoc = [100, 50, 5, 50, 100]
    trips = extract_typeA_episodes(np.array(rsoc, float), TypeADef())
    assert trips == [(0, 2, 4)]


def test_typeA_back_to_back_reuse():
    rsoc = [100, 5, 100, 4, 100]
    trips = extract_typeA_episodes(np.array(rsoc, float), TypeADef())
    assert trips == [(0, 1, 2), (2, 3, 4)]


def test_typeA_record_geometry():
    df = _series([100, 5, 100], chg=[0, 2, 1])
    rows = process_user_od2("u", df, DEFAULT_OD2_CONFIG)
    a = [r for r in rows if r["opportunity_type"] == "A"]
    assert len(a) == 1
    r = a[0]
    assert r["start_rsoc"] >= 99 and r["low_rsoc"] <= 6 and r["end_rsoc"] >= 99


def test_typeA_deep_threshold_configurable():
    # low of 8% does NOT qualify at deep=6 but DOES at deep=10
    rsoc = [100, 8, 100]
    assert extract_typeA_episodes(np.array(rsoc, float), TypeADef(deep_pct=6.0)) == []
    assert extract_typeA_episodes(np.array(rsoc, float), TypeADef(deep_pct=10.0)) == [(0, 1, 2)]


# --------------------------------------------------------------------------- #
# Type B
# --------------------------------------------------------------------------- #
def test_typeB_charge_band_to_full():
    rsoc = [65, 80, 99]
    chg = [1, 1, 1]
    trips = extract_typeB_episodes(np.array(rsoc, float), np.array(chg, float), TypeBDef())
    assert trips == [(0, 0, 2)]


def test_typeB_abort_on_drop_below_abort():
    rsoc = [65, 55, 99]      # drops below abort(60) before reaching full -> void
    chg = [1, 1, 1]
    trips = extract_typeB_episodes(np.array(rsoc, float), np.array(chg, float), TypeBDef())
    assert trips == []


def test_typeB_requires_charging_to_arm():
    rsoc = [65, 80, 99]
    chg = [2, 2, 1]          # not charging in the band -> never arms
    trips = extract_typeB_episodes(np.array(rsoc, float), np.array(chg, float), TypeBDef())
    assert trips == []


def test_typeB_degenerate_low_equals_start_not_invalid_order():
    df = _series([65, 99], chg=[1, 1])
    rows = process_user_od2("u", df, DEFAULT_OD2_CONFIG)
    b = [r for r in rows if r["opportunity_type"] == "B"]
    assert len(b) == 1
    assert b[0]["episode_quality"] != "invalid_order"
    assert b[0]["low_idx"] == b[0]["start_idx"]


# --------------------------------------------------------------------------- #
# Response audit: censoring + effective step
# --------------------------------------------------------------------------- #
def test_censored_never_no_response():
    # END is the last sample -> 72h window runs past last_ts -> censored, not no_response.
    df = _series([100, 5, 100], chg=[0, 2, 1])
    rows = process_user_od2("u", df, DEFAULT_OD2_CONFIG)
    a = [r for r in rows if r["opportunity_type"] == "A"][0]
    assert a["response_status_72h"] == "censored"


def test_effective_step_gates_response():
    # A 30 mWh change inside the 72h window (complete): no_response at 50 mWh, responded at any_change.
    hours = [0.0, 0.5, 1.0, 2.0, 74.0]
    fcc = [50000, 50000, 50000, 50030, 50030]   # +30 mWh micro-step at sample 3
    rsoc = [100, 5, 100, 100, 100]
    chg = [0, 2, 1, 0, 0]
    df = _series(rsoc, chg, fcc=fcc, hours=hours)

    rows50 = process_user_od2("u", df, DEFAULT_OD2_CONFIG)     # abs_ge_50mWh
    a50 = [r for r in rows50 if r["opportunity_type"] == "A"][0]
    assert a50["window_72h_complete"] is True
    assert a50["response_status_72h"] == "no_response"

    cfg_any = Od2Config(effective_step="any_change")
    rows_any = process_user_od2("u", df, cfg_any)
    a_any = [r for r in rows_any if r["opportunity_type"] == "A"][0]
    assert a_any["response_status_72h"] == "responded"


# --------------------------------------------------------------------------- #
# RSOC validity + union
# --------------------------------------------------------------------------- #
def test_invalid_rsoc_skipped():
    rsoc = [100, None, 5, 200, 100]   # None and 200 are invalid -> skipped, not state changes
    trips = extract_typeA_episodes(np.array([np.nan if x is None else x for x in rsoc], float),
                                   TypeADef())
    assert trips == [(0, 2, 4)]


def test_union_dedup_prefers_typeA_on_coincident_end():
    # full->6->full where the recharge also transits 60-80 while charging: A and B share END.
    hours = [0, 0.5, 1.0, 1.5, 2.0]
    rsoc = [100, 5, 65, 80, 99]
    chg = [0, 2, 1, 1, 1]
    df = _series(rsoc, chg, hours=hours)
    rows = process_user_od2("u", df, DEFAULT_OD2_CONFIG)
    d = add_union_flags(pd.DataFrame(rows))
    # Type A END index (4) and Type B END index (4) coincide -> one primary, Type A wins.
    coincident = d[d["end_idx"] == 4]
    primaries = coincident[coincident["is_union_primary"]]
    assert len(primaries) == 1
    assert primaries.iloc[0]["opportunity_type"] == "A"
    assert set(primaries.iloc[0]["union_types"].split(",")) == {"A", "B"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
