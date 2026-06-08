"""Unit / regression tests for the 30-day sliding-window FCC response detector
(rolling30 spec section 16 — the 15 required checks, plus a few guards).

Run:  python -m pytest tests/test_fcc_online_sliding30.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from battery_usage.online_episode_detector import (                       # noqa: E402
    OnlineConfig, extract_episodes_causal, extract_episodes_in_window, prepare_user,
    episodes_to_frame, step_threshold_mwh, recover_design_mwh, PRIMARY_THRESHOLD,
)
from battery_usage.online_state import build_user_state_daily              # noqa: E402
from battery_usage.rolling_window_features import attach_window_episode_counts  # noqa: E402
from battery_usage import online_anomaly_scores as anom                    # noqa: E402
from battery_usage import online_action_policy as policy                   # noqa: E402
from battery_usage import fcc_response_ml as ml                            # noqa: E402

BASE = pd.Timestamp("2024-01-01")


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


def _primary(eps):
    return [e for e in eps if e["threshold_name"] == PRIMARY_THRESHOLD]


CFG = OnlineConfig(effective_step="abs_ge_50mWh", response_window_hours=72)


# 1. high->low->high episode extraction is correct
def test_01_episode_extraction():
    g = mkdf([0, 2, 4, 6, 8, 200], [100, 50, 10, 30, 85, 85], [60000] * 6)
    g = prepare_user(g)
    e = _primary(extract_episodes_causal(g, "u", CFG))
    assert len(e) == 1
    assert (e[0]["start_idx"], e[0]["low_idx"], e[0]["end_idx"]) == (0, 2, 4)
    assert e[0]["start_rsoc"] >= 80 and e[0]["low_rsoc"] <= 20 and e[0]["end_rsoc"] >= 80


# 2 & 3. boundary: stateful (causal) sees a window-straddling episode; stateless does not
def test_02_03_window_boundary_stateful_vs_stateless():
    cfg10 = OnlineConfig(window_days=10, effective_step="abs_ge_50mWh")
    # open high at day0 (outside the [day10,day20] window), low day15, recharge-high day17.
    hours = [0, 120, 240, 360, 384, 408, 432, 480]   # day 0,5,10,15,16,17,18,20
    rsoc = [100, 60, 40, 15, 50, 85, 90, 95]
    g = prepare_user(mkdf(hours, rsoc, [60000] * len(hours)))
    # stateful: full causal series finds the episode opening at day0
    stateful = _primary(extract_episodes_causal(g, "u", cfg10))
    assert len(stateful) == 1 and stateful[0]["start_ts"] == BASE  # opened at day0

    # stateless: only the [day10, day20] raw window -> opening high is gone, episode missed
    t = BASE + pd.Timedelta(days=20)
    win = g[(g["timestamp"] > t - pd.Timedelta(days=10)) & (g["timestamp"] <= t)]
    stateless = _primary(extract_episodes_in_window(win, "u", t, cfg10, last_observed_ts=t))
    assert len(stateless) == 0


# 4. end+72h beyond current time -> censored, never no_response
def test_04_censored_not_no_response():
    g = prepare_user(mkdf([0, 2, 4, 6, 8, 9], [100, 50, 10, 30, 85, 86], [60000] * 6))
    e = _primary(extract_episodes_causal(g, "u", CFG))[0]   # last sample 1h after end
    assert e["response_status_72h"] == "censored"
    assert e["window_72h_complete"] is False


# 5. large-gap episode is not counted as an OK opportunity in state
def test_05_large_gap_not_ok_opportunity():
    # 20h gap between low and recharge -> max_gap_h_episode > 12 -> large_gap quality
    g = prepare_user(mkdf([0, 2, 4, 24, 200], [100, 50, 10, 85, 85], [60000] * 5))
    eps = episodes_to_frame(extract_episodes_causal(g, "u", CFG))
    eps["p_response"] = 0.8
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert prim["episode_quality"] == "large_gap"
    grid = _grid(BASE, days=9)
    rows, _ = build_user_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert sd["cum_primary_ok_since_last_fcc_change"].max() == 0
    assert sd["cum_primary_large_gap_since_last_fcc_change"].max() == 1


# 6. the same episode in many overlapping windows is not double-counted in state
def test_06_no_double_count_in_state():
    g = prepare_user(mkdf([0, 2, 4, 6, 8, 200], [100, 50, 10, 30, 85, 85], [60000] * 6))
    eps = episodes_to_frame(extract_episodes_causal(g, "u", CFG))
    eps["p_response"] = 0.7
    grid = _grid(BASE, days=12)                  # many daily windows after the single episode
    rows, _ = build_user_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    # exactly one primary no_response ever accrues, no matter how many windows it appears in
    assert sd["cum_primary_no_response_since_last_fcc_change"].max() == 1


# 7. an effective FCC change resets the since-last-change counters
def test_07_reset_on_effective_change():
    # episode no_response, then a big effective FCC drop later -> counters reset to 0
    hours = [0, 2, 4, 6, 8, 100, 400]
    rsoc = [100, 50, 10, 30, 85, 85, 85]
    fcc = [60000, 60000, 60000, 60000, 60000, 60000, 59000]   # effective change at h400
    g = prepare_user(mkdf(hours, rsoc, fcc))
    eps = episodes_to_frame(extract_episodes_causal(g, "u", CFG))
    eps["p_response"] = 0.7
    grid = _grid(BASE, days=20)
    rows, audit = build_user_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert len(audit) == 1 and audit[0]["fcc_value"] == 59000.0
    # after the change day, counters are zeroed and last value updated
    after = sd[sd["last_effective_fcc_value"] == 59000.0]
    assert (after["cum_primary_no_response_since_last_fcc_change"] == 0).all()


# 8. micro FCC step: no response under abs_ge_50mWh, response under any_change
def test_08_micro_step_effective_vs_any():
    g = prepare_user(mkdf([0, 2, 4, 6, 8, 52, 200],
                          [100, 50, 10, 30, 85, 85, 85],
                          [60000, 60000, 60000, 60000, 60000, 60010, 60010]))  # +10 mWh after end
    e50 = _primary(extract_episodes_causal(g, "u", OnlineConfig(effective_step="abs_ge_50mWh")))[0]
    eany = _primary(extract_episodes_causal(g, "u", OnlineConfig(effective_step="any_change")))[0]
    assert e50["response_status_72h"] == "no_response"
    assert eany["response_status_72h"] == "responded"


# 9. hardware identity / final label never enter the ML feature matrix
def test_09_no_hw_or_label_in_model_features():
    eps = _synthetic_eps_feat()
    eps["device_model"] = "ThinkPad X"; eps["batt_vendor"] = "SMP"
    eps["batt_fru"] = "5B11"; eps["serialNumber"] = "SN"; eps["final_label"] = "FW"
    X, y, groups, feats, band_cols = ml._build_xy(eps, "response_status_72h")
    forbidden = ("device_model", "batt_vendor", "batt_fru", "serial", "uuid", "final_label")
    assert not any(any(s in c.lower() for s in forbidden) for c in X.columns)
    # and the explicit guard raises if a forbidden feature is forced in
    with pytest.raises(AssertionError):
        ml._assert_no_leakage(["episode_depth", "device_model"])


# 10. GroupKFold by user -> no user split across train/test
def test_10_groupkfold_users_disjoint():
    eps = _synthetic_eps_feat(n_users=6, per_user=12)
    result, _ = ml.train_response_model(eps, "response_status_72h")
    assert result["status"] == "ok"
    preds = result["predictions"]
    folds_per_user = preds.groupby("user_id")["fold"].nunique()
    assert (folds_per_user == 1).all()           # each user lands in exactly one held-out fold


# 11. p_all_no_response = product(1 - clip(p_i)); clipping bounds the score
def test_11_p_all_no_response_product_and_clip():
    # two complete-OK primary no_response episodes, p = 0.8 and 0.5, in one scored window
    ep = pd.DataFrame({
        "episode_id": ["e1", "e2"], "user_id": ["u", "u"],
        "threshold_name": [PRIMARY_THRESHOLD, PRIMARY_THRESHOLD],
        "episode_quality": ["ok", "ok"],
        "response_status_72h": ["no_response", "no_response"],
        "end_ts": [BASE, BASE + pd.Timedelta(days=1)],
    })
    probs = pd.DataFrame({"episode_id": ["e1", "e2"], "p_response": [0.8, 0.5]})
    feats = _one_window_feats(end=BASE + pd.Timedelta(days=5))
    out = anom.compute_window_scores(feats, ep, probs, CFG)
    r = out.iloc[0]
    assert abs(r["p_all_no_response_30d"] - (0.2 * 0.5)) < 1e-6
    assert abs(r["fw_response_anomaly_score_30d"] - 1.0) < 1e-3

    # p_i = 1.0 must clip to 0.999 -> finite score ~3, never inf
    probs2 = pd.DataFrame({"episode_id": ["e1", "e2"], "p_response": [1.0, 0.0]})
    out2 = anom.compute_window_scores(_one_window_feats(BASE + pd.Timedelta(days=5)), ep, probs2, CFG)
    assert np.isfinite(out2.iloc[0]["fw_response_anomaly_score_30d"])
    assert out2.iloc[0]["fw_response_anomaly_score_30d"] <= 3.001


# 12. empirical/conformal p-value is monotone non-increasing in the score
def test_12_conformal_pvalue_monotone():
    calib = np.array([0.0, 1.0, 2.0, 3.0])
    scores = np.array([0.0, 0.5, 1.0, 2.5, 4.0])
    p = anom._empirical_p(scores, calib)
    assert np.all(np.diff(p) <= 1e-9)            # higher score -> smaller (or equal) p


# 13. alert cooldown suppresses repeated same-state alerts
def test_13_alert_cooldown():
    days = pd.date_range(BASE, periods=20, freq="1D")
    daily = pd.DataFrame({
        "user_id": ["u"] * 20,
        "window_end_date": days,
        "stateful_label": [policy.ST_FW] * 20,
        "window_label": [policy.WIN_NO_RESP] * 20,
        "window_data_quality_label": ["WINDOW_QUALITY_OK"] * 20,
        "days_since_last_effective_fcc_change": np.arange(100, 120.0),  # monotone up (no recovery)
    })
    out = policy.apply_alert_cooldown(daily, cooldown_days=30)
    # within a single 30-day cooldown, only the first actionable day fires
    assert int(out["alert_fired"].sum()) == 1
    assert bool(out.iloc[0]["alert_fired"]) is True


# 14. data-quality review outranks an actionable call
def test_14_review_outranks_actionable():
    # a row that otherwise satisfies FW, but the window quality is not OK
    daily = _fw_qualifying_row()
    daily.loc[0, "window_data_quality_label"] = "WINDOW_QUALITY_SPARSE"
    out = policy.assign_labels(daily, CFG)
    assert out.iloc[0]["stateful_label"] == policy.ST_REVIEW


# 15. a zero-opportunity window does not get a spuriously high anomaly score
def test_15_zero_opportunity_zero_score():
    feats = _one_window_feats(BASE + pd.Timedelta(days=5))
    empty_ep = pd.DataFrame(columns=["episode_id", "user_id", "threshold_name",
                                     "episode_quality", "response_status_72h", "end_ts"])
    out = anom.compute_window_scores(feats, empty_ep, pd.DataFrame(columns=["episode_id", "p_response"]), CFG)
    r = out.iloc[0]
    assert r["n_complete_ok_opportunities_30d"] == 0
    assert r["fw_response_anomaly_score_30d"] == 0.0
    assert pd.isna(r["conformal_p"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _grid(base, days):
    g = pd.date_range(base, base + pd.Timedelta(days=days - 1), freq="1D")
    return (g + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)).values.astype(
        "datetime64[ns]").astype(np.int64)


def _one_window_feats(end):
    return pd.DataFrame([{
        "user_id": "u", "window_end_date": pd.Timestamp(end).normalize(),
        "window_end_ts": pd.Timestamp(end),
        "window_data_quality_label": "WINDOW_QUALITY_OK",
    }])


def _synthetic_eps_feat(n_users=4, per_user=10, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(n_users):
        for i in range(per_user):
            depth = rng.uniform(60, 95)
            resp = "responded" if rng.random() < 0.4 else "no_response"
            rows.append({
                "episode_id": f"u{u}|{i}", "user_id": f"user{u}",
                "threshold_name": PRIMARY_THRESHOLD, "episode_quality": "ok",
                "response_status_72h": resp,
                "start_ts": BASE + pd.Timedelta(days=i), "end_ts": BASE + pd.Timedelta(days=i, hours=12),
                "episode_depth": depth, "episode_duration_h": rng.uniform(5, 40),
                "start_to_low_duration_h": rng.uniform(2, 20),
                "low_to_end_duration_h": rng.uniform(2, 20),
                "cycle_delta_episode": rng.uniform(0, 2), "start_rsoc": rng.uniform(80, 100),
                "low_rsoc": rng.uniform(5, 20), "end_rsoc": rng.uniform(80, 100),
                "n_samples_episode": rng.integers(5, 50), "max_gap_h_episode": rng.uniform(0, 10),
                "median_gap_h_episode": rng.uniform(0.5, 2),
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


def _fw_qualifying_row():
    return pd.DataFrame([{
        "user_id": "u", "window_end_date": BASE, "window_data_quality_label": "WINDOW_QUALITY_OK",
        "days_since_last_effective_fcc_change": 200.0,
        "cycles_since_last_effective_fcc_change": 60.0,
        "cum_primary_no_response_since_last_fcc_change": 5,
        "cum_strict_no_response_since_last_fcc_change": 3,
        "cum_primary_ok_since_last_fcc_change": 5,
        "cum_primary_large_gap_since_last_fcc_change": 0,
        "cum_primary_censored_since_last_fcc_change": 0,
        "cum_strict_ok_since_last_fcc_change": 3, "cum_strict_large_gap_since_last_fcc_change": 0,
        "cum_observed_response_since_last_fcc_change": 0,
        "cum_fw_response_anomaly_score": 3.0, "fw_response_anomaly_score_30d": 3.0,
        "conformal_p": 0.005, "cluster_profile_name": "MOBILE_DEEP_CYCLE_NO_RESPONSE",
        "fcc_effective_changes_30d": 0, "cycle_delta_30d": 10.0, "ac_time_ratio_30d": 0.3,
        "rsoc_swing_30d": 80.0, "rsoc_min_30d": 8.0, "n_discharge_sessions_30d": 5,
        "observed_response_30d": 0, "no_response_count_30d": 5,
        "n_complete_ok_opportunities_30d": 5, "n_80_20_80_large_gap_30d": 0,
        "n_80_20_80_censored_30d": 0,
    }])


def test_14b_fw_row_is_fw_when_quality_ok():
    """Sanity: the same row WITH OK quality is FW (so test_14 really tests the override)."""
    out = policy.assign_labels(_fw_qualifying_row(), CFG)
    assert out.iloc[0]["stateful_label"] == policy.ST_FW


# 4b (regression for review finding). The STATE MACHINE must also keep a censored episode out of
# no_response, even though the window-end grid runs past end+72h in wall-clock time.
def test_16_state_machine_censored_not_no_response():
    g = prepare_user(mkdf([0, 2, 4, 6, 8, 9], [100, 50, 10, 30, 85, 86], [60000] * 6))
    eps = episodes_to_frame(extract_episodes_causal(g, "u", CFG))
    eps["p_response"] = 0.8
    prim = eps[eps.threshold_name == PRIMARY_THRESHOLD].iloc[0]
    assert prim["response_status_72h"] == "censored"          # last sample only 1h after end
    grid = _grid(BASE, days=5)                                # grid runs to end-of-day, past end+72h
    rows, _ = build_user_state_daily(g, "u", grid, eps, CFG, design_mwh=60000)
    sd = pd.DataFrame(rows)
    assert sd["cum_primary_no_response_since_last_fcc_change"].max() == 0   # never flips to no_response
    assert sd["cum_primary_censored_since_last_fcc_change"].max() == 1      # stays censored/pending


# 6b (regression for review finding). Window episode-count membership is causal: a window ending at
# t with e <= t < e+72h counts the opportunity as censored, NOT ok_complete (no future status leak).
def test_17_attach_counts_causal_censored_split():
    e = BASE + pd.Timedelta(days=10)
    ep = pd.DataFrame({"episode_id": ["x"], "user_id": ["u"], "threshold_name": [PRIMARY_THRESHOLD],
                       "episode_quality": ["ok"], "response_status_72h": ["no_response"], "end_ts": [e]})
    ends = [e + pd.Timedelta(days=d) for d in (1, 2, 4, 5)]   # +1,+2 < e+72h (censored); +4,+5 resolved
    feats = pd.DataFrame({"user_id": ["u"] * 4, "window_end_ts": ends,
                          "window_end_date": [t.normalize() for t in ends]})
    out = attach_window_episode_counts(feats, ep, CFG)
    assert out.iloc[0]["n_80_20_80_censored_30d"] == 1 and out.iloc[0]["n_80_20_80_ok_complete_30d"] == 0
    assert out.iloc[1]["n_80_20_80_censored_30d"] == 1
    assert out.iloc[2]["n_80_20_80_ok_complete_30d"] == 1 and out.iloc[2]["n_80_20_80_no_response_30d"] == 1
    assert out.iloc[2]["n_80_20_80_censored_30d"] == 0
    assert out.iloc[3]["n_80_20_80_ok_complete_30d"] == 1
