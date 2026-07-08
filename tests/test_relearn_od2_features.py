"""Contract tests for the OD2 -> classifier feature mapping (Phase 2).

Locks the agreed slot mapping consumed by fcc_final.classify_user_final:
    strict "90_10_90" slot  <- Type A (deep-discharge relearn)
    primary "80_20_80" slot <- Type B (charge-side relearn)
and that the 168h response columns the OD2 classifier config needs are emitted.
"""
import numpy as np
import pandas as pd

from battery_usage.relearn_od2_features import build_od2_user_row

T0 = pd.Timestamp("2025-01-01 00:00:00")


def _frozen_user_with_A1_B2():
    # One Type A (full->5->full) whose recharge also makes a Type B, plus a second
    # standalone Type B (charge 65->99). FCC constant => frozen => all episodes in the tail.
    rsoc = [100, 60, 5, 60, 100, 80, 40, 65, 99]
    chg = [0, 2, 2, 1, 1, 2, 2, 1, 1]
    n = len(rsoc)
    return pd.DataFrame({
        "timestamp": [T0 + pd.Timedelta(minutes=30 * i) for i in range(n)],
        "remainingCapacityInPercentage": [float(x) for x in rsoc],
        "chargeStatus": [float(x) for x in chg],
        "acdcMode": [1.0] * n,
        "fullChargeCapacity": [50000.0] * n,
        "cycleCount": list(range(n)),
        "soh_design_pct": [99.0] * n,
        "serialNumber": ["1_DEV_u"] * n,
    })


def test_typeA_maps_to_strict_slot_typeB_to_primary_slot():
    row = build_od2_user_row("u", _frozen_user_with_A1_B2())
    # Type A -> 90_10_90 slot; Type B -> 80_20_80 slot.
    assert row["tail_n_90_10_90_ok"] == row["od2_tail_n_typeA_ok"]
    assert row["tail_n_80_20_80_ok"] == row["od2_tail_n_typeB_ok"]
    assert row["od2_tail_n_typeA_ok"] == 1     # one deep-discharge relearn
    assert row["od2_tail_n_typeB_ok"] == 2     # two charge-side relearns


def test_168h_response_columns_present():
    row = build_od2_user_row("u", _frozen_user_with_A1_B2())
    for band in ("80_20_80", "90_10_90"):
        for w in (24, 72, 168):
            assert f"tail_n_unresponded_{band}_complete_window_{w}h" in row
            assert f"tail_response_rate_{band}_{w}h" in row
            assert f"tail_n_censored_{band}_{w}h" in row
    assert "relevant_response_rate_168h" in row
    assert "opportunity_definition" in row and row["opportunity_definition"] == "od2"


def test_frozen_fcc_all_episodes_in_tail():
    # FCC never changes -> flat-tail anchor is first sample -> total == tail counts.
    row = build_od2_user_row("u", _frozen_user_with_A1_B2())
    assert row["fcc_changes"] == 0
    assert row["total_n_80_20_80_ok"] == row["tail_n_80_20_80_ok"]
    assert row["total_n_90_10_90_ok"] == row["tail_n_90_10_90_ok"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
