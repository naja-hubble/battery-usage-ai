"""Normative vs personalized episode response models (rolling30 v2 spec section 10).

v1 trained ONE response model whose top feature was
``recent_30d_fcc_effective_changes_before_episode``. That is dangerous for anomaly scoring:
the model learns that an already-failing gauge (few recent effective changes) is *expected*
not to respond, so it suppresses exactly the anomaly we want to surface (spec 10 intro).

v2 trains two heads on the SAME opportunity population (HIGH_OK + MEDIUM_GAP episodes with a
resolved 72h status), differing only in their feature sets:

  * **personalized** — the full v1 feature set incl. recent FCC history. Kept for
    prediction/calibration diagnostics ONLY (spec 10.1); never drives policy.
  * **normative**    — "if the gauge were healthy, how likely is this episode to produce a
    meaningful FCC response?" It EXCLUDES every feature that encodes prior FCC
    history/response/failure state (spec 10.2). This is the PRIMARY model for anomaly
    scoring; its per-episode probability ``p_response_normative`` feeds the cumulative
    Poisson-binomial anomaly in ``online_step_state``.

Both heads reuse ``fcc_response_ml.train_response_model`` (GroupKFold by user, isotonic
calibration, HGB/LR/LGBM/XGB) — only the feature list and the leakage guard differ.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import fcc_response_ml as ml
from . import online_anomaly_scores as anom
from .online_episode_detector import OnlineConfig, DEFAULT_ONLINE_CONFIG
from .online_gap_quality import NO_RESPONSE_CAPABLE_TIERS

# The v2 opportunity population for BOTH heads (graded tiers, spec 11 / 10).
V2_QUALITY_COL = "quality_tier"
V2_OK_VALUES = tuple(NO_RESPONSE_CAPABLE_TIERS)   # ("HIGH_OK", "MEDIUM_GAP")

# Personalized = the full v1 episode feature set (incl. recent FCC history).
PERSONALIZED_FEATURES: List[str] = list(ml.EPISODE_TIME_FEATURES)

# Normative = episode geometry + sampling-quality + non-FCC usage context ONLY.
# Explicitly enumerated (not derived by subtraction) so the guard is auditable.
NORMATIVE_FEATURES: List[str] = [
    # episode geometry / shape
    "episode_depth", "rsoc_depth", "start_rsoc", "low_rsoc", "end_rsoc",
    "episode_duration_h", "start_to_low_duration_h", "low_to_end_duration_h",
    "cycle_delta_episode",
    # in-episode usage ratios (spec 10.2 allowed)
    "ac_ratio_in_episode", "charge_ratio_in_episode", "discharge_ratio_in_episode",
    # sampling density / gap geometry (quality, not FCC outcome)
    "n_samples_episode", "max_gap_h_episode", "median_gap_h_episode",
    "endpoint_gap_h", "high_to_low_max_gap_h", "low_to_high_max_gap_h",
    "observed_coverage_fraction", "sample_density_per_day", "episode_quality_score",
    # recent NON-FCC usage context strictly before the episode (spec 10.2 allowed)
    "recent_30d_cycle_delta_before_episode", "recent_30d_ac_ratio_before_episode",
    "recent_30d_rsoc_swing_before_episode", "recent_30d_max_gap_h_before_episode",
    "recent_30d_n_samples_before_episode",
]

# Substrings a normative feature MUST NOT contain (prior FCC history / response / state).
NORMATIVE_FORBIDDEN_SUBSTRINGS: Tuple[str, ...] = (
    "recent_30d_fcc", "recent_30d_any_fcc", "recent_30d_n_80_20_80",
    "recent_30d_n_90_10_90", "fcc_before", "soh_before", "cycle_count_before",
    "days_since", "cycles_since", "fcc_changed", "fcc_response", "no_response",
    "prior_response", "response_status", "final_label",
)


def assert_normative_excludes_history(columns) -> None:
    """Raise if a normative feature encodes prior FCC history / response / failure state."""
    bad = [c for c in columns
           if any(s in str(c).lower() for s in NORMATIVE_FORBIDDEN_SUBSTRINGS)]
    assert not bad, f"normative model leaked prior-FCC/response feature(s): {bad}"
    # also subject it to the standard hardware/future/label guard
    ml._assert_no_leakage(columns)


# --------------------------------------------------------------------------- #
# Training (both heads)
# --------------------------------------------------------------------------- #
def train_dual_models(
    eps_feat: pd.DataFrame, response_col: str = "response_status_72h",
    random_state: int = 42,
) -> Dict[str, object]:
    """Train personalized + normative heads. Returns a dict with both results/bundles."""
    out: Dict[str, object] = {}

    pers_feats = [c for c in PERSONALIZED_FEATURES if c in eps_feat.columns]
    pers_res, pers_bundle = ml.train_response_model(
        eps_feat, response_col, features=pers_feats,
        quality_col=V2_QUALITY_COL, ok_values=V2_OK_VALUES, random_state=random_state)
    out["personalized_result"] = pers_res
    out["personalized_bundle"] = pers_bundle

    norm_feats = [c for c in NORMATIVE_FEATURES if c in eps_feat.columns]
    assert_normative_excludes_history(norm_feats)
    norm_res, norm_bundle = ml.train_response_model(
        eps_feat, response_col, features=norm_feats,
        quality_col=V2_QUALITY_COL, ok_values=V2_OK_VALUES, random_state=random_state)
    # double-check no forbidden column survived band one-hot expansion
    assert_normative_excludes_history([c for c in norm_res.get("feature_columns", [])
                                       if not c.startswith("band_")])
    out["normative_result"] = norm_res
    out["normative_bundle"] = norm_bundle
    return out


def score_dual_models(models: Dict[str, object], eps_feat: pd.DataFrame) -> pd.DataFrame:
    """Per-episode probabilities for both heads over all no_response-capable episodes.

    Returns episode_id, p_response_personalized, p_response_normative (one row per
    HIGH_OK/MEDIUM_GAP episode).
    """
    pers = ml.predict_all_ok(models["personalized_bundle"], eps_feat,
                             V2_QUALITY_COL, V2_OK_VALUES).rename(
        columns={"p_response": "p_response_personalized"})
    norm = ml.predict_all_ok(models["normative_bundle"], eps_feat,
                             V2_QUALITY_COL, V2_OK_VALUES).rename(
        columns={"p_response": "p_response_normative"})
    return pers.merge(norm, on="episode_id", how="outer")


# --------------------------------------------------------------------------- #
# Dual window-level anomaly (normative = policy; personalized = diagnostic)
# --------------------------------------------------------------------------- #
_ANOM_COLS = ["expected_response_30d", "observed_response_30d", "no_response_count_30d",
              "n_complete_ok_opportunities_30d", "p_all_no_response_30d",
              "fw_response_anomaly_score_30d", "conformal_p"]


def compute_dual_window_scores(
    feats: pd.DataFrame, episodes: pd.DataFrame, ep_probs: pd.DataFrame,
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG, final_labels: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Attach window anomaly columns for BOTH heads.

    The NORMATIVE head keeps the canonical v1 column names (these drive policy); the
    PERSONALIZED head is suffixed ``_personalized`` and is diagnostic only (spec 10.4).
    """
    norm_probs = ep_probs.rename(columns={"p_response_normative": "p_response"})[
        ["episode_id", "p_response"]]
    feats = anom.compute_window_scores(feats, episodes, norm_probs, cfg, final_labels)

    pers_probs = ep_probs.rename(columns={"p_response_personalized": "p_response"})[
        ["episode_id", "p_response"]]
    base = feats[["user_id", "window_end_date", "window_end_ts",
                  "window_data_quality_label"]].copy()
    pers_feats = anom.compute_window_scores(base, episodes, pers_probs, cfg)
    ren = {c: f"{c}_personalized" for c in _ANOM_COLS if c in pers_feats.columns}
    pers_feats = pers_feats.rename(columns=ren)[
        ["user_id", "window_end_date"] + list(ren.values())]
    feats = feats.merge(pers_feats, on=["user_id", "window_end_date"], how="left")
    return feats
