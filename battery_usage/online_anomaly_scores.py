"""ML Layer 3 — user-window anomaly scoring (rolling30 spec 11).

For each user-window we aggregate the episode response model's probabilities over the
PRIMARY-band OK opportunities that are **resolved as of the window end** (so the score is
strictly causal: a window ending at ``t`` only ever uses opportunities whose 72h response
window also closed by ``t``, i.e. episode end ``e`` with ``e + W <= t``). The anomaly is the
Poisson-binomial probability that a healthy gauge would have produced NO response across all
those opportunities:

    p_all_no_response_30d            = Pi (1 - clip(p_i))
    fw_response_anomaly_score_30d    = -log10(max(p_all_no_response_30d, eps))

A window with zero complete OK opportunities gets an empty product (p_all = 1) and therefore
score 0 — never a spuriously high anomaly (spec 16.15). An empirical/conformal p-value is
derived against a calibration set of clean OK windows (spec 11.3).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .online_episode_detector import OnlineConfig, DEFAULT_ONLINE_CONFIG, PRIMARY_THRESHOLD

HOUR_NS = 3600 * 1_000_000_000
DAY_NS = 86_400 * 1_000_000_000
P_CLIP = (0.001, 0.999)
EPS = 1e-12


def compute_window_scores(
    feats: pd.DataFrame, episodes: pd.DataFrame, ep_probs: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    final_labels: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Attach expected/observed/anomaly/conformal columns to the feature table.

    ``ep_probs`` : episode_id -> p_response (operational, all OK episodes).
    ``final_labels`` : optional; if present a separate ``conformal_p_proxy_final_normal`` is
    added using final-NORMAL users as the calibration set (kept clearly separate, spec 11.3).
    """
    win_ns = int(cfg.response_window_hours) * HOUR_NS
    win_len_ns = cfg.window_days * DAY_NS

    ep = episodes[(episodes["threshold_name"] == PRIMARY_THRESHOLD)
                  & (episodes["episode_quality"] == "ok")
                  & (episodes["response_status_72h"].isin(["responded", "no_response"]))].copy()
    if "p_response" in ep.columns:
        ep = ep.drop(columns=["p_response"])
    ep = ep.merge(ep_probs, on="episode_id", how="left")
    if "p_response" not in ep.columns:
        ep["p_response"] = np.nan
    mean_p = float(np.nanmean(ep["p_response"])) if ep["p_response"].notna().any() else 0.5
    ep["p_response"] = ep["p_response"].fillna(mean_p).clip(*P_CLIP)

    feats = feats.reset_index(drop=True)
    n = len(feats)
    sum_p = np.zeros(n); sum_logq = np.zeros(n); n_ok = np.zeros(n, int)
    n_obs = np.zeros(n, int); n_nr = np.zeros(n, int)

    # index windows per user by end_ns
    win_idx: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for uid, sub in feats.groupby("user_id", sort=False):
        ends = sub["window_end_ts"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        win_idx[uid] = (sub.index.to_numpy(), ends)

    for r in ep.itertuples(index=False):
        uid = r.user_id
        if uid not in win_idx:
            continue
        rows_idx, ends = win_idx[uid]
        e_ns = int(pd.Timestamp(r.end_ts).value)
        # causal membership: window end t in [e+W, e+30d)  (episode contained AND resolved by t)
        j0 = int(np.searchsorted(ends, e_ns + win_ns, side="left"))
        j1 = int(np.searchsorted(ends, e_ns + win_len_ns, side="left"))
        sel = rows_idx[j0:j1]
        if sel.size == 0:
            continue
        p = float(min(max(r.p_response, P_CLIP[0]), P_CLIP[1]))
        sum_p[sel] += p
        sum_logq[sel] += np.log(1.0 - p)
        n_ok[sel] += 1
        if r.response_status_72h == "responded":
            n_obs[sel] += 1
        else:
            n_nr[sel] += 1

    p_all = np.exp(sum_logq)                       # empty product -> 1.0 -> score 0
    score = -np.log10(np.maximum(p_all, EPS))
    score[n_ok == 0] = 0.0
    feats["expected_response_30d"] = np.round(sum_p, 4)
    feats["observed_response_30d"] = n_obs
    feats["no_response_count_30d"] = n_nr
    feats["n_complete_ok_opportunities_30d"] = n_ok
    feats["p_all_no_response_30d"] = np.where(n_ok == 0, np.nan, np.round(p_all, 6))
    feats["fw_response_anomaly_score_30d"] = np.round(score, 4)

    # ---- conformal / empirical p-value ----
    calib_mask = ((feats["window_data_quality_label"] == "WINDOW_QUALITY_OK")
                  & (feats["n_complete_ok_opportunities_30d"] >= 1)).to_numpy()
    feats["conformal_p"] = _empirical_p(score, score[calib_mask])
    feats.loc[feats["n_complete_ok_opportunities_30d"] == 0, "conformal_p"] = np.nan

    if final_labels is not None and "final_label" in final_labels.columns:
        normal_users = set(final_labels.loc[
            final_labels["final_label"] == "NORMAL_OR_RESPONDING", "user_id"])
        proxy_mask = (feats["user_id"].isin(normal_users)
                      & (feats["n_complete_ok_opportunities_30d"] >= 1)).to_numpy()
        if proxy_mask.sum() >= 10:
            feats["conformal_p_proxy_final_normal"] = _empirical_p(score, score[proxy_mask])
            feats.loc[feats["n_complete_ok_opportunities_30d"] == 0,
                      "conformal_p_proxy_final_normal"] = np.nan
    return feats


def _empirical_p(scores: np.ndarray, calib: np.ndarray) -> np.ndarray:
    """share(calib >= score) for every score (spec 11.3). Calibrated against ``calib``."""
    if calib.size == 0:
        return np.full(scores.shape, np.nan)
    cs = np.sort(calib)
    # count of calib >= score  =  N - searchsorted(cs, score, 'left')
    ge = cs.size - np.searchsorted(cs, scores, side="left")
    return np.round(ge / cs.size, 5)
