"""Tests for the FCC patent-evidence v3 additive pipeline.

Network-free. Core logic tests run on synthetic / production-label inputs and do
NOT require the heavy driver to have run; smoke tests for produced artifacts are
skipped gracefully when absent. Existing production tests are untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_usage import patent_opportunity_response as por
from battery_usage import patent_dual_track as pdt

REPO = Path(__file__).resolve().parents[1]
PROC = REPO / "data" / "processed"
EVID = PROC / "fcc_patent_evidence_v3"
REPORTS = REPO / "data" / "reports"
ACTION = PROC / "fcc_final_action_labels.csv"

EXPECTED_FULL = {
    por.LABEL_GAUGE: 18, por.LABEL_FW: 14, por.LABEL_WATCH: 55,
    por.LABEL_REVIEW: 338, por.LABEL_NORMAL: 327,
}

pytestmark = pytest.mark.skipif(not ACTION.exists(), reason="production action labels not present")


# ----------------------------------------------------------------------
def test_baseline_reproduction():
    al = pd.read_csv(ACTION)
    assert al["user_id"].nunique() == 752
    assert int(al["fcc_no_or_low_change_candidate"].sum()) == 96
    vc = al["final_label"].value_counts().to_dict()
    for label, exp in EXPECTED_FULL.items():
        assert vc.get(label, 0) == exp, f"{label}: {vc.get(label, 0)} != {exp}"


def test_ablation_a6_equals_production_actionable():
    al = pd.read_csv(ACTION)
    res = por.evaluate(al)
    a6 = res.set_index("variant").loc["A6"]
    assert a6["n_flagged"] == 32                 # 18 gauge + 14 fw
    assert a6["proxy_precision"] == 1.0 and a6["proxy_recall"] == 1.0
    assert a6["proxy_fw_captured"] == 14 and a6["proxy_gauge_captured"] == 18


def test_ablation_idempotent():
    al = pd.read_csv(ACTION)
    a = por.evaluate(al); b = por.evaluate(al)
    pd.testing.assert_frame_equal(a, b)


def test_no_hardware_identity_in_ablation_inputs():
    """derive_variants must not depend on device_model / batt_vendor / batt_fru."""
    al = pd.read_csv(ACTION)
    stripped = al.drop(columns=[c for c in ["device_model", "batt_vendor", "batt_fru"] if c in al.columns])
    out_full = por.derive_variants(al)
    out_strip = por.derive_variants(stripped)
    for k in out_full:
        assert out_full[k].flagged == out_strip[k].flagged


def _row(**kw):
    base = dict(
        user_id="u", flat_tail_days=400.0, tail_cycle_delta=80.0,
        tail_n_80_20_80_any=5.0, tail_n_90_10_90_any=5.0,
        tail_n_80_20_80_ok=0.0, tail_n_90_10_90_ok=0.0,
        tail_n_unresponded_80_20_80_complete_window=0.0,
        tail_n_unresponded_90_10_90_complete_window=0.0,
        tail_n_80_20_80_large_gap=0.0, tail_n_90_10_90_large_gap=0.0,
        tail_n_censored_80_20_80=0.0, tail_n_censored_90_10_90=0.0,
        final_label=por.LABEL_REVIEW, fcc_effective_changes_50mwh=0.0,
    )
    base.update(kw)
    return base


def test_censored_excluded_from_no_response():
    """A user whose only 'evidence' is censored must NOT be flagged by A4/A5 (IC1 censor-aware)."""
    df = pd.DataFrame([_row(user_id="censored_only", tail_n_censored_80_20_80=10.0)])
    v = por.derive_variants(df)
    assert "censored_only" not in v["A4"].flagged
    assert "censored_only" not in v["A5"].flagged


def test_large_gap_excluded_by_gap_tier():
    """large_gap counts in A4 but is excluded by the A5 gap tier (IC6)."""
    df = pd.DataFrame([_row(user_id="gap_only", tail_n_80_20_80_large_gap=10.0)])
    v = por.derive_variants(df)
    assert "gap_only" in v["A4"].flagged        # A4 still counts large_gap
    assert "gap_only" not in v["A5"].flagged     # A5 gap tier excludes it


def test_confirmed_no_response_flags_fw():
    """OK complete-window no-response above threshold IS flagged (positive control)."""
    df = pd.DataFrame([_row(user_id="real_fw", tail_n_unresponded_80_20_80_complete_window=5.0)])
    v = por.derive_variants(df)
    assert "real_fw" in v["A4"].flagged and "real_fw" in v["A5"].flagged


# ----------------------------------------------------------------------
def test_dual_track_quantization_and_determinism():
    ts = pd.DataFrame({
        "user_id": ["a"] * 5,
        "timestamp": pd.date_range("2026-01-01", periods=5, freq="D"),
        "fullChargeCapacity": [1000, 1000, 1030, 1030, 1130],  # steps: +30, +100
    })
    s1 = pdt.fcc_steps(ts); s2 = pdt.fcc_steps(ts)
    pd.testing.assert_frame_equal(s1.reset_index(drop=True), s2.reset_index(drop=True))
    summ = pdt.step_magnitude_summary(s1)
    assert summ["n_steps"] == 2
    assert summ["quantization_unit_mwh"] == 30.0      # smallest positive |step|
    assert summ["frac_micro_lt_50mwh"] == 0.5         # one of two steps < 50


def test_dual_track_drops_zero_deltas():
    ts = pd.DataFrame({
        "user_id": ["a"] * 4,
        "timestamp": pd.date_range("2026-01-01", periods=4, freq="h"),
        "fullChargeCapacity": [900, 900, 900, 960],
    })
    s = pdt.fcc_steps(ts)
    assert len(s) == 1 and s["abs_step"].iloc[0] == 60.0


# ----------------------------------------------------------------------
@pytest.mark.skipif(not (EVID / "availability_probe_v3.json").exists(),
                    reason="driver not run yet")
def test_intervention_data_not_available_not_fabricated():
    rep = json.loads((EVID / "availability_probe_v3.json").read_text(encoding="utf-8"))
    assert rep["intervention_version_data"] == "NOT AVAILABLE"
    # protocol must exist and must NOT claim computed outcomes
    proto = (REPORTS / "fcc_intervention_protocol_v3.md").read_text(encoding="utf-8")
    assert "NOT AVAILABLE" in proto
    norm = " ".join(proto.lower().replace(">", " ").split())  # drop blockquote markers + collapse wraps
    assert "no intervention outcome is computed or claimed" in norm


@pytest.mark.skipif(not (EVID / "patent_baseline_gate_v3.csv").exists(),
                    reason="driver not run yet")
def test_baseline_gate_artifact_pass():
    gate = pd.read_csv(EVID / "patent_baseline_gate_v3.csv")
    assert gate["match"].all(), gate[~gate["match"]].to_dict("records")


@pytest.mark.skipif(not (REPORTS / "fcc_patent_evidence_v3_report.md").exists(),
                    reason="driver not run yet")
def test_pii_scan_external_outputs():
    """No raw user_id may appear in external report text or figure filenames."""
    uids = set(pd.read_csv(ACTION)["user_id"].astype(str))
    report = (REPORTS / "fcc_patent_evidence_v3_report.md").read_text(encoding="utf-8")
    disclosure = (REPORTS / "fcc_invention_disclosure_v3.md").read_text(encoding="utf-8")
    leaked = [u for u in uids if u in report or u in disclosure]
    assert not leaked, f"PII leak in external report: {leaked[:5]}"
    figdir = REPORTS / "figures" / "fcc_patent_evidence_v3"
    if figdir.exists():
        names = " ".join(p.name for p in figdir.glob("*.png"))
        assert not any(u in names for u in uids), "PII in figure filename"
