"""Unit / regression tests for the Rolling 30d FCC online detector v2.0 (spec section 17).

Run:  python -m pytest tests/test_fcc_online_sliding30_v2.py -q
The v1 suite (tests/test_fcc_online_sliding30.py) must keep passing unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battery_usage.online_episode_detector import (                         # noqa: E402
    OnlineConfig, extract_episodes_causal, prepare_user, episodes_to_frame, PRIMARY_THRESHOLD,
)
from battery_usage import online_gap_quality as gq                          # noqa: E402
from battery_usage import online_step_state as ss                           # noqa: E402
from battery_usage import fcc_response_normative as nrm                     # noqa: E402
from battery_usage import fcc_response_ml as ml                             # noqa: E402
from battery_usage import usage_clustering as uc                           # noqa: E402
from battery_usage import online_policy_v2 as pol                           # noqa: E402

BASE = pd.Timestamp("2024-01-01")
CFG = OnlineConfig(effective_step="abs_ge_50mWh", response_window_hours=72)


def mkdf(hours, rsoc, fcc, cyc=None, acdc=None, cs=None):
    n = len(rsoc)
    return pd.DataFrame({
        "user_id": ["u"] * n,
        "timestamp": [BASE + pd.Timedelta(hours=h) for h in hours],
        "remainingCapacityInPercentage": rsoc,
        "fullChargeCapacity": fcc,
        "cycleCount": cyc if cyc is not None else list(range(n)),
        "acdcMode": acdc if acdc is not None else [0] * n,
        "chargeStatus": cs if cs is not None else [2] * n,
        "serialNumber": ["SN"] * n,
        "soh_design_pct": [f / 600.0 for f in fcc],
    })


def _grid(base, days):
    g = pd.date_range(base, base + pd.Timedelta(days=days - 1), freq="1D")
    return (g + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).values.astype(
        "datetime64[ns]").astype(np.int64)


def _eps_with_quality(g, p_norm=0.8):
    eps = episodes_to_frame(extract_episodes_causal(g, "u", CFG))
    eps = gq.attach_gap_quality(eps, {"u": g}, CFG)
    eps["p_response_normative"] = p_norm
    eps["p_response_personalized"] = p_norm
    return eps


# ---- 11. graded gap quality -------------------------------------------------
def test_v2_gap_tier_high_ok():
    g = prepare_user(mkdf([0, 1, 2, 3, 4, 200], [100, 50, 10, 30, 85, 85], [60000] * 6))
    eps = _eps_with_quality(g)
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert prim["max_gap_h_episode"] <= 12
    assert prim["quality_tier"] == "HIGH_OK"


def test_v2_gap_tier_medium_gap():
    # densely-sampled episode with a single 14h gap (>12, <=24) and decent coverage -> MEDIUM_GAP
    hours = [0, 1, 2, 3, 4, 5, 6, 20, 21, 22, 200]
    rsoc = [100, 90, 70, 50, 30, 20, 10, 50, 70, 85, 85]
    g = prepare_user(mkdf(hours, rsoc, [60000] * len(hours)))
    eps = _eps_with_quality(g)
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert 12 < prim["max_gap_h_episode"] <= 24
    assert prim["quality_tier"] == "MEDIUM_GAP"


def test_v2_gap_tier_low_large_gap():
    # 40h gap -> LOW_LARGE_GAP
    g = prepare_user(mkdf([0, 1, 2, 42, 200], [100, 50, 10, 85, 85], [60000] * 5))
    eps = _eps_with_quality(g)
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert prim["max_gap_h_episode"] > 24
    assert prim["quality_tier"] == "LOW_LARGE_GAP"


def test_v2_gap_tier_pure_function():
    assert gq.gap_quality_tier(5.0, 0.9) == "HIGH_OK"
    assert gq.gap_quality_tier(11.0, 0.6) == "MEDIUM_GAP"      # gap ok but score < 0.8
    assert gq.gap_quality_tier(20.0, 0.7) == "MEDIUM_GAP"
    assert gq.gap_quality_tier(40.0, 0.9) == "LOW_LARGE_GAP"   # huge gap dominates


# ---- 17.7 large-gap LOW never supports no_response in state -----------------
def test_v2_low_tier_not_no_response_in_state():
    g = prepare_user(mkdf([0, 1, 2, 42, 200], [100, 50, 10, 85, 85], [60000] * 5))
    eps = _eps_with_quality(g)
    grid = _grid(BASE, days=12)
    rows, _ = ss.build_user_dual_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert sd["cum_primary_no_response_since_last_effective_change"].max() == 0
    assert sd["cum_primary_large_gap_opportunities_since_last_effective_change"].max() == 1


# ---- 17.1 dual state: censored never no_response (regression #16 analog) -----
def test_v2_dual_state_censored_not_no_response():
    g = prepare_user(mkdf([0, 1, 2, 3, 4, 5], [100, 50, 10, 30, 85, 86], [60000] * 6))
    eps = _eps_with_quality(g)
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert prim["response_status_72h"] == "censored"            # last sample ~1h after end
    grid = _grid(BASE, days=5)                                  # grid runs past end+72h
    rows, _ = ss.build_user_dual_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert sd["cum_primary_no_response_since_last_effective_change"].max() == 0
    assert sd["cum_primary_censored_since_last_effective_change"].max() == 1


# ---- 17.2 episode de-duplication across overlapping windows -----------------
def test_v2_no_double_count_in_state():
    g = prepare_user(mkdf([0, 1, 2, 3, 4, 200], [100, 50, 10, 30, 85, 85], [60000] * 6))
    eps = _eps_with_quality(g)
    grid = _grid(BASE, days=12)
    rows, _ = ss.build_user_dual_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert sd["cum_primary_no_response_since_last_effective_change"].max() == 1


# ---- 17.3 effective FCC step resets effective counters + pending ------------
def test_v2_effective_reset_clears_counters():
    hours = [0, 1, 2, 3, 4, 100, 400]
    rsoc = [100, 50, 10, 30, 85, 85, 85]
    fcc = [60000, 60000, 60000, 60000, 60000, 60000, 59000]    # effective drop at h400
    g = prepare_user(mkdf(hours, rsoc, fcc))
    eps = _eps_with_quality(g)
    grid = _grid(BASE, days=20)
    rows, audit = ss.build_user_dual_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    eff_audit = [a for a in audit if a["is_effective"]]
    assert len(eff_audit) == 1 and eff_audit[0]["fcc_value"] == 59000.0
    after = sd[sd["last_effective_fcc_value"] == 59000.0]
    assert (after["cum_primary_no_response_since_last_effective_change"] == 0).all()


# ---- 17.3 micro step resets ONLY the any-change track -----------------------
def test_v2_micro_step_any_track_only():
    # +10 mWh micro step at h400 (below 50 mWh effective threshold)
    hours = [0, 1, 2, 3, 4, 400]
    rsoc = [100, 50, 10, 30, 85, 85]
    fcc = [60000, 60000, 60000, 60000, 60000, 60010]
    g = prepare_user(mkdf(hours, rsoc, fcc))
    eps = _eps_with_quality(g)
    grid = _grid(BASE, days=20)
    rows, audit = ss.build_user_dual_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows).iloc[-1]
    # any track reset at h400, effective track did NOT
    assert sd["days_since_any_fcc_change"] < sd["days_since_effective_fcc_change"]
    assert sd["micro_wobble_only_since_effective_change"] is True or \
        bool(sd["micro_wobble_only_since_effective_change"]) is True
    assert sd["n_micro_steps_since_effective_change"] == 1
    assert sd["max_micro_step_mWh_since_effective_change"] == 10.0
    assert not any(a["is_effective"] for a in audit)


# ---- 17.5 normative feature guard -------------------------------------------
def test_v2_normative_excludes_history():
    nrm.assert_normative_excludes_history(nrm.NORMATIVE_FEATURES)             # passes
    for bad in ("recent_30d_fcc_effective_changes_before_episode", "fcc_before_episode",
                "soh_before_episode", "cycle_count_before_episode",
                "recent_30d_n_80_20_80_ok_before_episode", "days_since_last_fcc_change",
                "final_label", "device_model"):
        with pytest.raises(AssertionError):
            nrm.assert_normative_excludes_history(["episode_depth", bad])


def test_v2_normative_feature_list_is_subset_without_history():
    forbidden = ("recent_30d_fcc", "fcc_before", "soh_before", "cycle_count_before",
                 "recent_30d_n_80_20_80", "days_since", "cycles_since")
    assert not any(any(s in f for s in forbidden) for f in nrm.NORMATIVE_FEATURES)
    # personalized keeps hardware/future/label free but DOES include recent FCC history
    assert "recent_30d_fcc_effective_changes_before_episode" in nrm.PERSONALIZED_FEATURES


# ---- 17.6 clustering feature guard ------------------------------------------
def test_v2_clustering_usage_only_guard():
    uc._assert_usage_only(uc.USAGE_ONLY_CLUSTER_FEATURES)                    # passes
    for bad in ("n_80_20_80_no_response_30d", "fcc_effective_changes_30d",
                "cum_normative_fw_anomaly_score", "device_model", "final_label"):
        with pytest.raises(AssertionError):
            uc._assert_usage_only(["cycle_delta_30d", bad])


# ---- 17.9 leakage: dual models exclude HW/final, GroupKFold by user ---------
def _synthetic_eps_feat(n_users=6, per_user=12, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(n_users):
        for i in range(per_user):
            tier = "HIGH_OK" if rng.random() < 0.6 else "MEDIUM_GAP"
            resp = "responded" if rng.random() < 0.45 else "no_response"
            rows.append({
                "episode_id": f"u{u}|{i}", "user_id": f"user{u}",
                "threshold_name": PRIMARY_THRESHOLD, "episode_quality": "ok",
                "quality_tier": tier, "response_status_72h": resp,
                "start_ts": BASE + pd.Timedelta(days=i),
                "end_ts": BASE + pd.Timedelta(days=i, hours=12),
                "episode_depth": rng.uniform(60, 95), "rsoc_depth": rng.uniform(60, 95),
                "episode_duration_h": rng.uniform(5, 40),
                "start_to_low_duration_h": rng.uniform(2, 20),
                "low_to_end_duration_h": rng.uniform(2, 20),
                "cycle_delta_episode": rng.uniform(0, 2), "start_rsoc": rng.uniform(80, 100),
                "low_rsoc": rng.uniform(5, 20), "end_rsoc": rng.uniform(80, 100),
                "n_samples_episode": rng.integers(5, 50), "max_gap_h_episode": rng.uniform(0, 10),
                "median_gap_h_episode": rng.uniform(0.5, 2),
                "endpoint_gap_h": rng.uniform(0, 8), "high_to_low_max_gap_h": rng.uniform(0, 8),
                "low_to_high_max_gap_h": rng.uniform(0, 8),
                "observed_coverage_fraction": rng.uniform(0.6, 1.0),
                "sample_density_per_day": rng.uniform(5, 50),
                "episode_quality_score": rng.uniform(0.5, 1.0),
                "ac_ratio_in_episode": rng.uniform(0, 1),
                "charge_ratio_in_episode": rng.uniform(0, 1),
                "discharge_ratio_in_episode": rng.uniform(0, 1),
                "fcc_before_episode": 60000.0, "soh_before_episode": 100.0,
                "cycle_count_before_episode": rng.uniform(0, 300),
                "recent_30d_cycle_delta_before_episode": rng.uniform(0, 10),
                "recent_30d_ac_ratio_before_episode": rng.uniform(0, 1),
                "recent_30d_rsoc_swing_before_episode": rng.uniform(0, 90),
                "recent_30d_n_80_20_80_ok_before_episode": rng.integers(0, 5),
                "recent_30d_fcc_effective_changes_before_episode": rng.integers(0, 3),
                "recent_30d_n_samples_before_episode": rng.integers(20, 500),
                "recent_30d_max_gap_h_before_episode": rng.uniform(0, 20),
            })
    return pd.DataFrame(rows)


def test_v2_dual_models_groupkfold_and_no_leak():
    eps = _synthetic_eps_feat()
    eps["device_model"] = "ThinkPad X"; eps["final_label"] = "FW"
    models = nrm.train_dual_models(eps, "response_status_72h", random_state=42)
    norm = models["normative_result"]; pers = models["personalized_result"]
    assert norm["status"] == "ok" and pers["status"] == "ok"
    # normative must not contain any prior-FCC / hardware / label feature
    nrm.assert_normative_excludes_history(
        [c for c in norm["feature_columns"] if not c.startswith("band_")])
    for fc in (norm["feature_columns"], pers["feature_columns"]):
        assert not any(any(s in c.lower() for s in ("device_model", "final_label", "serial"))
                       for c in fc)
    # GroupKFold: each user in exactly one held-out fold
    for res in (norm, pers):
        preds = res["predictions"]
        assert (preds.groupby("user_id")["fold"].nunique() == 1).all()


# ---- v2 policy rows ---------------------------------------------------------
def _v2_row(**over):
    base = {
        "user_id": "u", "window_end_date": BASE,
        "window_data_quality_label": "WINDOW_QUALITY_OK", "has_counter_reset": False,
        "state_history_sufficient": True,
        "days_since_effective_fcc_change": 10.0, "days_since_any_fcc_change": 10.0,
        "cycles_since_effective_fcc_change": 5.0,
        "cum_primary_ok_opportunities_since_last_effective_change": 0,
        "cum_primary_medium_gap_opportunities_since_last_effective_change": 0,
        "cum_primary_large_gap_opportunities_since_last_effective_change": 0,
        "cum_strict_ok_opportunities_since_last_effective_change": 0,
        "cum_strict_medium_gap_opportunities_since_last_effective_change": 0,
        "cum_strict_large_gap_opportunities_since_last_effective_change": 0,
        "cum_primary_ok_no_response_since_last_effective_change": 0,
        "cum_primary_medium_gap_no_response_since_last_effective_change": 0,
        "cum_primary_no_response_since_last_effective_change": 0,
        "cum_strict_ok_no_response_since_last_effective_change": 0,
        "cum_strict_no_response_since_last_effective_change": 0,
        "cum_primary_censored_since_last_effective_change": 0,
        "high_quality_no_response_count": 0, "censored_count": 0,
        "large_gap_low_quality_count": 0,
        "observed_effective_responses_since_last_effective_change": 0,
        "cum_normative_fw_anomaly_score": 0.0, "fw_response_anomaly_score_30d": 0.0,
        "conformal_p": 1.0, "micro_wobble_only_since_effective_change": False,
        "cluster_profile_name": "MOBILE_MODERATE_CYCLE", "fcc_effective_changes_30d": 0,
        "fcc_any_changes_30d": 0, "cycle_delta_30d": 5.0, "n_discharge_sessions_30d": 3,
        "observed_response_30d": 0, "n_80_20_80_ok_complete_30d": 0,
        "n_80_20_80_no_response_30d": 0, "n_80_20_80_large_gap_30d": 0,
        "n_80_20_80_censored_30d": 0,
    }
    base.update(over)
    return pd.DataFrame([base])


def _label(row):
    return pol.assign_labels_v2(row).iloc[0]["stateful_label_v2"]


# ---- 17.8 action priority ---------------------------------------------------
def test_v2_dq_outranks_actionable():
    fw = _fw_core_overrides()
    fw["window_data_quality_label"] = "WINDOW_QUALITY_SPARSE"
    assert _label(_v2_row(**fw)) == pol.ST_REVIEW_DQ


def _fw_core_overrides():
    return dict(days_since_effective_fcc_change=130.0, days_since_any_fcc_change=130.0,
                cycles_since_effective_fcc_change=40.0,
                cum_primary_ok_no_response_since_last_effective_change=4,
                cum_primary_no_response_since_last_effective_change=4,
                high_quality_no_response_count=4,
                cum_primary_ok_opportunities_since_last_effective_change=4,
                cum_normative_fw_anomaly_score=3.0, conformal_p=0.004,
                cluster_profile_name="MOBILE_DEEP_CYCLE")


def test_v2_fw_core_fires():
    assert _label(_v2_row(**_fw_core_overrides())) == pol.ST_FW_CORE


def test_v2_fw_core_outranks_gauge_when_no_response():
    # long staleness + gauge cluster (gauge-like) BUT high-quality no_response present -> FW Core
    ov = _fw_core_overrides()
    ov["cluster_profile_name"] = "AC_BOUND"           # gauge-relevant cluster
    assert _label(_v2_row(**ov)) == pol.ST_FW_CORE


def test_v2_gauge_core_fires():
    ov = dict(days_since_effective_fcc_change=200.0, days_since_any_fcc_change=200.0,
              cluster_profile_name="AC_BOUND")
    assert _label(_v2_row(**ov)) == pol.ST_GAUGE_CORE


def test_v2_gauge_core_and_fw_core_mutually_exclusive():
    # Gauge Core requires zero no_response; FW Core requires no_response. Never both.
    ov_gc = dict(days_since_effective_fcc_change=200.0, days_since_any_fcc_change=200.0,
                 cluster_profile_name="AC_BOUND")
    assert _label(_v2_row(**ov_gc)) == pol.ST_GAUGE_CORE
    ov_fw = _fw_core_overrides()
    assert _label(_v2_row(**ov_fw)) == pol.ST_FW_CORE


def test_v2_micro_wobble_goes_to_gauge_soft_not_core():
    # effective-stale 200d but any-change active 10d ago (micro wobble) -> Gauge Soft, NOT Core
    ov = dict(days_since_effective_fcc_change=200.0, days_since_any_fcc_change=10.0,
              micro_wobble_only_since_effective_change=True, cluster_profile_name="AC_BOUND")
    assert _label(_v2_row(**ov)) == pol.ST_GAUGE_SOFT


def test_v2_gauge_soft_not_counted_as_hard_reset():
    ov = dict(days_since_effective_fcc_change=200.0, days_since_any_fcc_change=10.0,
              micro_wobble_only_since_effective_change=True, cluster_profile_name="AC_BOUND")
    snap = _v2_row(**ov)
    out = pol.assign_labels_v2(snap).iloc[0]
    assert out["stateful_label_v2"] == pol.ST_GAUGE_SOFT
    assert out["recommended_action"] == "ACTION_SOFT_CALIBRATION_PROMPT"
    assert out["stateful_label_v2"] != pol.ST_GAUGE_CORE


def test_v2_normal_when_no_evidence():
    assert _label(_v2_row()) == pol.ST_NORMAL


def test_v2_hw_token_guard_covers_banned_identity_fields():
    from battery_usage import online_enrichment as enr
    enr.assert_no_hw_in_classification(nrm.NORMATIVE_FEATURES, nrm.PERSONALIZED_FEATURES,
                                       uc.USAGE_ONLY_CLUSTER_FEATURES)            # all clean
    for bad in ("IdentifyingNumber", "DesignCapacity", "design_capacity", "type_model",
                "MTM", "product_uuid", "serialNumber"):
        with pytest.raises(AssertionError):
            enr.assert_no_hw_in_classification(["episode_depth", bad])


def test_v2_priority_values_unique_and_ordered():
    assert pol.PRIORITY[pol.ST_REVIEW_DQ] == 1
    assert pol.PRIORITY[pol.ST_FW_CORE] < pol.PRIORITY[pol.ST_GAUGE_CORE]
    assert pol.PRIORITY[pol.ST_GAUGE_CORE] < pol.PRIORITY[pol.ST_FW_WATCH]
    assert pol.PRIORITY[pol.ST_NORMAL] == 9
    assert len(set(pol.PRIORITY.values())) == 9
