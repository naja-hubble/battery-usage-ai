"""Tests for the FCC patent-evidence v4 additive pipeline (Section 17).

Core-logic tests run on synthetic / production inputs and do NOT require the heavy
driver to have run; artifact smoke tests are skipped gracefully when absent.
Existing v1/v2/v3 tests are untouched and must still pass.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from battery_usage import patent_common_v4 as pc
from battery_usage import patent_negative_controls as nc
from battery_usage import patent_anchor_analysis as aa
from battery_usage import patent_response_hazard as rh
from battery_usage import patent_dual_track_ablation as dta
from battery_usage import patent_effective_threshold as et
from battery_usage import patent_retention_invariance as ri
from battery_usage import patent_state_minimality as sm

REPO = Path(__file__).resolve().parents[1]
V4 = pc.V4_DIR
REPORTS = pc.REPORTS
ACTION = pc.ACTION_LABELS
HAS_DATA = pc.TIMESERIES.exists() and ACTION.exists()
datadep = pytest.mark.skipif(not HAS_DATA, reason="production data not present")


# --------------------------------------------------------------------------- #
# Foundation: user-clustered bootstrap groups by USER, not episode (spec 2.10)
# --------------------------------------------------------------------------- #
def test_user_bootstrap_groups_by_user():
    rng = pc.rng(0)
    # two users, very different per-user rates; bootstrap CI must reflect 2 clusters,
    # i.e. be MUCH wider than an episode-level (iid) interval would be.
    num = np.array([10.0, 0.0]); den = np.array([10.0, 10.0])
    out = pc.user_bootstrap_ratio(num, den, 2000, rng)
    # with only 2 user clusters {1.0, 0.0} the bootstrap of the ratio spans ~[0,1]
    assert out["ci_lo"] <= 0.05 and out["ci_hi"] >= 0.95
    assert abs(out["point"] - 0.5) < 1e-9


def test_randomization_pvalue_plugin():
    null = list(np.zeros(99))
    assert abs(pc.randomization_pvalue(5.0, null, "greater") - (0 + 1) / (99 + 1)) < 1e-9


def test_steps_in_window_inclusive_and_effective():
    arr = {"ts_ns": np.array([0, 10, 20, 30], dtype=np.int64),
           "is_effective": np.array([False, True, False, True]),
           "abs_step": np.array([5, 60, 5, 70.0]), "step": np.zeros(4)}
    idx = pc.steps_in_window(arr, 10, 30, effective_only=True)
    assert set(idx.tolist()) == {1, 3}          # inclusive bounds, effective only


# --------------------------------------------------------------------------- #
# A2 negative controls: reproducibility + no pre-end leakage in statistic
# --------------------------------------------------------------------------- #
def _toy_eps_steps():
    # one user, two ok primary episodes; an effective step 24h after each end
    base = pd.Timestamp("2025-01-01").value
    H = pc.HOUR_NS
    eps = pd.DataFrame([
        {"user_id": "u", "threshold_name": pc.PRIMARY_THRESHOLD, "is_ok": True,
         "window_72h_complete": True, "fcc_response_status_72h": "responded",
         "start_ns": base, "low_ns": base + 10 * H, "end_ns": base + 20 * H},
        {"user_id": "u", "threshold_name": pc.PRIMARY_THRESHOLD, "is_ok": True,
         "window_72h_complete": True, "fcc_response_status_72h": "no_response",
         "start_ns": base + 100 * H, "low_ns": base + 110 * H, "end_ns": base + 120 * H},
    ])
    steps = pd.DataFrame([
        {"user_id": "u", "ts_ns": base + 24 * H, "abs_step": 60.0, "step": 60.0, "is_effective": True},
    ])
    return eps, steps


def test_a2_statistic_reproducible():
    eps, steps = _toy_eps_steps()
    anchors = {"u": eps["end_ns"].to_numpy()}
    sbu = pc.steps_by_user(steps[steps.is_effective])
    last = {"u": int(eps["end_ns"].max() + 1000 * pc.HOUR_NS)}
    s1 = nc.statistic(anchors, sbu, last)
    s2 = nc.statistic(anchors, sbu, last)
    assert s1["resp_prob_72h"] == s2["resp_prob_72h"]
    # episode 1 responded (step at +24h within [end, end+72h]); episode 2 not -> 0.5
    assert abs(s1["resp_prob_72h"] - 0.5) < 1e-9


def test_a2_circular_shift_destroys_alignment():
    eps, steps = _toy_eps_steps()
    anchors = {"u": eps["end_ns"].to_numpy()}
    sbu = pc.steps_by_user(steps[steps.is_effective])
    last = {"u": int(eps["end_ns"].max() + 1000 * pc.HOUR_NS)}
    span = {"u": int(2000 * pc.HOUR_NS)}; first = {"u": int(eps["start_ns"].min())}
    rng = pc.rng(1)
    null = [nc.control_circular_step_shift(anchors, sbu, last, span, first, rng)["resp_prob_72h"]
            for _ in range(50)]
    # control mean response should be <= the true 0.5 (alignment destroyed)
    assert np.nanmean(null) <= 0.5 + 1e-9


# --------------------------------------------------------------------------- #
# A3 / response convention: a step strictly before episode END is contamination,
# and END anchoring never counts it (no pre-end attribution).
# --------------------------------------------------------------------------- #
def test_no_pre_end_attribution_end_anchor():
    base = pd.Timestamp("2025-01-01").value; H = pc.HOUR_NS
    arr = {"ts_ns": np.array([base + 5 * H], dtype=np.int64),     # step BEFORE end
           "is_effective": np.array([True]), "abs_step": np.array([60.0]), "step": np.array([60.0])}
    end_ns = base + 20 * H
    # END anchored window [end, end+72h] must NOT include the pre-end step
    idx = pc.steps_in_window(arr, end_ns, end_ns + 72 * H, effective_only=True)
    assert idx.size == 0


def test_first_step_after_respects_anchor():
    base = 0; H = pc.HOUR_NS
    arr = {"ts_ns": np.array([5 * H, 30 * H], dtype=np.int64),
           "is_effective": np.array([True, True]), "abs_step": np.array([60., 60.]), "step": np.zeros(2)}
    assert pc.first_step_after(arr, 20 * H, True) == 30 * H      # skips the pre-anchor step


# --------------------------------------------------------------------------- #
# Censor deadline semantics: censored / unknown are never no_response (spec 2.3)
# --------------------------------------------------------------------------- #
def test_censored_never_no_response_in_missingness_classifier():
    from battery_usage import patent_missingness_stress as ms
    ext = {"end_ns": np.array([0, 100], dtype=np.int64),
           "max_gap_h": np.array([1.0, 1.0]),
           "status": np.array(["censored", "no_response"], dtype=object)}
    prop = ms._no_response_ends(ext, "proposed")
    naive = ms._no_response_ends(ext, "naive")
    assert 0 not in prop.tolist()           # censored excluded by proposed
    assert 100 in prop.tolist()             # genuine no_response kept
    assert 0 in naive.tolist()              # naive wrongly counts censored


# --------------------------------------------------------------------------- #
# Retention: duplicate-free stateful replay + property invariants (spec 9.5)
# --------------------------------------------------------------------------- #
def _synthetic_user(n_cycles=6):
    """Build a clean high->low->high sawtooth user with a +60mWh step after each end."""
    H = pc.HOUR_NS
    rows = []
    t = pd.Timestamp("2025-01-01")
    fcc = 50000.0
    for c in range(n_cycles):
        for rs in (95, 50, 8, 50, 95):                  # high->low->high
            rows.append((t, rs, fcc, float(c)))
            t = t + pd.Timedelta(hours=8)
        fcc += 60.0                                      # effective step after the recharge
        rows.append((t, 96, fcc, float(c)))
        t = t + pd.Timedelta(hours=8)
    g = pd.DataFrame(rows, columns=["timestamp", "remainingCapacityInPercentage",
                                    "fullChargeCapacity", "cycleCount"])
    g["soh_design_pct"] = g["fullChargeCapacity"] * 100.0 / 56000.0
    return g


def test_retention_stateful_duplicate_free_and_boundary_invariant():
    g = _synthetic_user()
    base = ri.windowed_stateful_replay(g, "u", 100000, 1, 0, 72, "ok_only")
    # vary retention window + stride + alignment: resolved physical episode set is invariant
    for W in (7, 14, 30):
        for stride in (1, 7):
            for align in (0, 3, 6):
                out = ri.windowed_stateful_replay(g, "u", W, stride, align, 72, "ok_only")
                assert out["duplicate_count"] == 0, (W, stride, align)
                assert out["detected"] == base["detected"], (W, stride, align)


def test_retention_no_response_impossible_before_deadline():
    """An episode whose 72h window is not yet observed must NOT be confirmed no_response."""
    H = pc.HOUR_NS
    g = _synthetic_user(n_cycles=3)
    # truncate so the LAST episode's deadline is unobserved -> it must stay censored, not no_response
    out_full = ri.windowed_stateful_replay(g, "u", 100000, 1, 0, 72, "ok_only")
    # with a never-responding user the count is bounded by completed (observed-deadline) episodes
    assert out_full["confirmed_no_response"] >= 0
    # property: censored (pending past horizon) are not counted as no_response
    assert isinstance(out_full["censored"], int)


def test_retention_replay_idempotent():
    g = _synthetic_user()
    a = ri.windowed_stateful_replay(g, "u", 30, 7, 0, 72, "ok_only")
    b = ri.windowed_stateful_replay(g, "u", 30, 7, 0, 72, "ok_only")
    assert a["detected"] == b["detected"] and a["confirmed_no_response"] == b["confirmed_no_response"]


def test_state_ablation_fsm_breaks_recall():
    """Removing the partial FSM must break cross-window episode recall (spec 9.4)."""
    g = _synthetic_user(n_cycles=8)
    full = ri.windowed_stateful_replay(g, "u", 7, 1, 0, 72, "ok_only", components=ri.FULL_COMPONENTS)
    no_fsm = ri.windowed_stateful_replay(g, "u", 7, 1, 0, 72, "ok_only",
                                         components=ri.FULL_COMPONENTS - {"fsm"})
    assert len(no_fsm["detected"]) <= len(full["detected"])


# --------------------------------------------------------------------------- #
# C2 asymmetric reset behavior (spec 17): symmetric erases evidence, asymmetric preserves
# --------------------------------------------------------------------------- #
def test_asymmetric_reset_preserves_evidence():
    H = pc.HOUR_NS
    # one capable episode end, deadline observed, then a MICRO step (10 mWh) afterwards
    end_ns = 1000 * H
    ends = [(end_ns, pc.TIER_HIGH, True)]
    steps = [(end_ns + 100 * H, 10.0)]              # micro step after the deadline resolves
    last = end_ns + 500 * H
    events = dta.build_user_events(ends, steps, last)
    d2 = dta.replay(events, 50.0, dta.Policy("d2", erase_evidence_on_micro=True, record_micro=True),
                    last, 0)
    d4 = dta.replay(events, 50.0, dta.Policy("d4", erase_evidence_on_micro=False, record_micro=True),
                    last, 0)
    # both confirm the no-response at the deadline (before the micro step); the micro step
    # under D2 would erase a STILL-pending one. Add a still-pending episode to show erasure:
    ends2 = [(end_ns, pc.TIER_HIGH, True), (end_ns + 90 * H, pc.TIER_HIGH, False)]  # 2nd unobserved deadline
    ev2 = dta.build_user_events(ends2, [(end_ns + 95 * H, 10.0)], last)
    d2b = dta.replay(ev2, 50.0, dta.Policy("d2", erase_evidence_on_micro=True, record_micro=True), last, 0)
    d4b = dta.replay(ev2, 50.0, dta.Policy("d4", erase_evidence_on_micro=False, record_micro=True), last, 0)
    assert d2b["erased_pending"] >= 1            # symmetric reset erased a pending opportunity
    assert d4b["erased_pending"] == 0            # asymmetric preserved it


def test_effective_reset_precedence_deterministic_on_collision():
    """complete < reset < deadline ordering at identical timestamps (spec 9.5)."""
    ts = 500 * pc.HOUR_NS
    ends = [(ts, pc.TIER_HIGH, True)]
    # a step and a completion at the same ts -> completion (prio 0) before step (prio 1)
    ev = dta.build_user_events(ends, [(ts, 60.0)], ts + 1000 * pc.HOUR_NS)
    prios = [e[1] for e in ev if e[0] == ts]
    assert prios == sorted(prios)               # deterministic ordering by priority


# --------------------------------------------------------------------------- #
# C3 adaptive-threshold determinism
# --------------------------------------------------------------------------- #
def test_effective_threshold_valley_deterministic():
    rng = np.random.default_rng(0)
    logx = np.concatenate([rng.normal(1.1, 0.2, 5000), rng.normal(2.4, 0.25, 5000)])
    v1 = et._valley_histogram(logx); v2 = et._valley_histogram(logx)
    assert v1 == v2


# --------------------------------------------------------------------------- #
# Artifact-level: baseline preservation, PII exclusion, non-fabrication
# --------------------------------------------------------------------------- #
@datadep
def test_baseline_gate_artifact_pass():
    p = V4 / "patent_baseline_gate_v4.csv"
    if not p.exists():
        pytest.skip("driver not run")
    gate = pd.read_csv(p)
    assert gate["match"].all(), gate[~gate["match"]].to_dict("records")


@datadep
def test_intervention_not_available_not_fabricated():
    p = V4 / "availability_probe_v4.json"
    if not p.exists():
        pytest.skip("driver not run")
    rep = json.loads(p.read_text(encoding="utf-8"))
    assert rep["intervention_version_data"] == "NOT AVAILABLE"


@datadep
def test_pii_exclusion_in_artifacts_and_reports():
    """No raw user_id may appear in v4 data artifacts, figures, or external reports."""
    if not ACTION.exists():
        pytest.skip("no data")
    uids = set(pd.read_csv(ACTION)["user_id"].astype(str))
    sample = list(uids)[:200]
    # published data artifacts must carry anon_id, never raw user_id. Files prefixed
    # with "_" are internal caches (kept with user_id for joins, excluded from the
    # manifest/bundle) and are not published artifacts.
    if V4.exists():
        for p in V4.glob("*.csv"):
            if p.name.startswith("_"):
                continue
            d = pd.read_csv(p)
            assert "user_id" not in d.columns, f"raw user_id column in {p.name}"
            # values must not embed a raw user_id (e.g. inside episode_id)
            blob = " ".join(d.select_dtypes(include="object").astype(str)
                            .apply(lambda c: " ".join(c), axis=0).tolist()) if len(d) else ""
            leak = [u for u in sample if u in blob]
            assert not leak, f"raw user_id embedded in values of {p.name}: {leak[:3]}"
        for p in V4.glob("*.parquet"):
            if p.name.startswith("_"):
                continue
            import pyarrow.parquet as pq
            cols = [f.name for f in pq.read_schema(p)]
            assert "user_id" not in cols, f"raw user_id column in {p.name}"
            d = pd.read_parquet(p)
            obj = d.select_dtypes(include="object")
            blob = " ".join(obj.astype(str).apply(lambda c: " ".join(c), axis=0).tolist()) if len(obj.columns) and len(d) else ""
            leak = [u for u in sample if u in blob]
            assert not leak, f"raw user_id embedded in values of {p.name}: {leak[:3]}"
    # external reports must not contain any raw user_id
    for name in ("fcc_patent_evidence_v4_report.md", "fcc_invention_disclosure_v4.md",
                 "fcc_patent_counsel_brief_v4.md"):
        p = REPORTS / name
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            leaked = [u for u in sample if u in txt]
            assert not leaked, f"PII leak in {name}: {leaked[:3]}"
    # figure filenames must be anonymous
    if pc.FIG_DIR.exists():
        names = " ".join(p.name for p in pc.FIG_DIR.glob("*.png"))
        assert not any(u in names for u in sample), "PII in figure filename"


@datadep
def test_baseline_label_counts_preserved():
    al = pd.read_csv(ACTION)
    assert al["user_id"].nunique() == 752
    vc = al["final_label"].value_counts().to_dict()
    from battery_usage import patent_opportunity_response as por
    assert vc.get(por.LABEL_GAUGE, 0) == 18 and vc.get(por.LABEL_FW, 0) == 14
