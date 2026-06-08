"""Graded episode gap-quality (rolling30 v2 spec section 11).

v1 collapsed an episode's sampling quality to a binary ``ok`` (max intra-episode gap
<= 12h) vs ``large_gap``. That throws away a lot of evidence: a discharge+recharge with a
single 14h overnight gap is much stronger no-response evidence than one stitched together
across a 40h gap, yet v1 treats them identically (both ``large_gap``). v2 grades each
episode on a continuous ``episode_quality_score`` and a 3-level ``quality_tier``:

  * ``HIGH_OK``       max_gap <= 12h and score >= 0.80  -> can support FW Core / Gauge Core
  * ``MEDIUM_GAP``    max_gap <= 24h and score >= 0.50  -> supports FW Watch, NOT FW Core alone
  * ``LOW_LARGE_GAP`` otherwise                          -> ambiguity only, NEVER no_response

Episodes whose v1 quality is ``missing_required_value`` / ``invalid_order`` are tagged
``INVALID`` and are ignored by every downstream counter (they were never clean
opportunities). The binary ``episode_quality`` column is preserved unchanged for backward
compatibility with v1 outputs/tests; ``quality_tier`` is an additive parallel field.

This module also attaches the episode-span context features the **normative** response
model is allowed to use (spec 10.2): in-episode AC/charge/discharge time ratios, observed
coverage fraction, sample density, and the graded gap geometry. None of these encode FCC
history, prior response state, or hardware identity.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .features import sample_weights
from .online_episode_detector import OnlineConfig, DEFAULT_ONLINE_CONFIG

# A sample "covers" the wall-clock time up to this many hours after it; gap time beyond it
# is counted as unobserved (idle) when computing observed_coverage_fraction.
COVERAGE_CAP_H = 3.0

# quality_score component weights (must sum to 1.0)
W_MAXGAP = 0.45
W_COVERAGE = 0.35
W_ENDPOINT = 0.20

TIER_HIGH = "HIGH_OK"
TIER_MEDIUM = "MEDIUM_GAP"
TIER_LOW = "LOW_LARGE_GAP"
TIER_INVALID = "INVALID"

# tiers that the spec treats as "no_response-capable" learning opportunities
NO_RESPONSE_CAPABLE_TIERS = (TIER_HIGH, TIER_MEDIUM)


# --------------------------------------------------------------------------- #
# Scalar component scorers (pure; unit-testable)
# --------------------------------------------------------------------------- #
def max_gap_component(max_gap_h: float) -> float:
    """1.0 if <=12h, linear to 0.5 at 24h, linear to 0.0 at 48h, 0.0 if >48h (spec 11)."""
    if not np.isfinite(max_gap_h):
        return 0.0
    g = float(max_gap_h)
    if g <= 12.0:
        return 1.0
    if g <= 24.0:
        return 1.0 - 0.5 * (g - 12.0) / 12.0      # 1.0 -> 0.5
    if g <= 48.0:
        return 0.5 - 0.5 * (g - 24.0) / 24.0      # 0.5 -> 0.0
    return 0.0


def endpoint_component(endpoint_gap_h: float) -> float:
    """1.0 if the worst anchor-adjacent gap <=6h, linear to 0.5 at 12h, 0.0 at 24h."""
    if not np.isfinite(endpoint_gap_h):
        return 0.0
    g = float(endpoint_gap_h)
    if g <= 6.0:
        return 1.0
    if g <= 12.0:
        return 1.0 - 0.5 * (g - 6.0) / 6.0
    if g <= 24.0:
        return 0.5 - 0.5 * (g - 12.0) / 12.0
    return 0.0


def gap_quality_tier(max_gap_h: float, quality_score: float) -> str:
    """Graded tier from (max gap, quality score). Spec 11 boundaries."""
    if not np.isfinite(max_gap_h) or not np.isfinite(quality_score):
        return TIER_LOW
    if max_gap_h <= 12.0 and quality_score >= 0.80:
        return TIER_HIGH
    if max_gap_h <= 24.0 and quality_score >= 0.50:
        return TIER_MEDIUM
    return TIER_LOW


# --------------------------------------------------------------------------- #
# Per-episode span geometry + context features
# --------------------------------------------------------------------------- #
def _segment_max_gap_h(gaps_h: np.ndarray, a: int, b: int) -> float:
    """Max inter-sample gap (hours) over positional sub-range [a, b] (gaps_h is diff array)."""
    if b <= a:
        return 0.0
    seg = gaps_h[a:b]
    return float(seg.max()) if seg.size else 0.0


def _episode_span_features(
    ts_ns: np.ndarray, acdc: np.ndarray, cs: Optional[np.ndarray],
    s: int, lo: int, e: int, n: int, weights: np.ndarray,
) -> Dict[str, object]:
    """Graded gap geometry + in-episode usage ratios for one episode span [s, e]."""
    span = slice(s, e + 1)
    seg_ts = ts_ns[span]
    gaps_h = np.diff(seg_ts) / 3.6e12 if seg_ts.size > 1 else np.array([])
    duration_h = float((ts_ns[e] - ts_ns[s]) / 3.6e12)
    n_samples = int(e - s + 1)

    # graded gap geometry: positional offsets within the span
    lo_off = lo - s
    e_off = e - s
    high_to_low = _segment_max_gap_h(gaps_h, 0, lo_off)        # start..low
    low_to_high = _segment_max_gap_h(gaps_h, lo_off, e_off)    # low..end
    # anchor-adjacent gaps (start out, into/out of low, into end)
    anchor_gaps = []
    if gaps_h.size:
        anchor_gaps.append(gaps_h[0])                                   # after start
        anchor_gaps.append(gaps_h[-1])                                  # before end
        if 0 < lo_off <= gaps_h.size:
            anchor_gaps.append(gaps_h[lo_off - 1])                      # into low
        if lo_off < gaps_h.size:
            anchor_gaps.append(gaps_h[lo_off])                          # out of low
    endpoint_gap_h = float(max(anchor_gaps)) if anchor_gaps else 0.0

    max_gap = float(gaps_h.max()) if gaps_h.size else 0.0
    if max_gap <= 1e-9:
        gap_pos = "none"
    elif high_to_low >= low_to_high:
        gap_pos = "high_to_low"
    else:
        gap_pos = "low_to_high"

    # observed coverage: fraction of wall-clock time within COVERAGE_CAP_H of a sample
    if gaps_h.size and duration_h > 0:
        idle = float(np.maximum(gaps_h - COVERAGE_CAP_H, 0.0).sum())
        coverage = max(0.0, min(1.0, 1.0 - idle / duration_h))
    else:
        coverage = 1.0 if n_samples >= 1 else 0.0
    sample_density = float(n_samples / max(duration_h / 24.0, 1e-6))

    # in-episode time-weighted usage ratios (allowed normative context, spec 10.2)
    w = weights[span]
    tw = float(w.sum())
    ac_ratio = float((w * (acdc[span])).sum() / tw) if tw > 0 else float("nan")
    if cs is not None and tw > 0:
        chg_ratio = float((w * (cs[span] == 1)).sum() / tw)
        dis_ratio = float((w * (cs[span] == 2)).sum() / tw)
    else:
        chg_ratio = dis_ratio = float("nan")

    return {
        "high_to_low_max_gap_h": round(high_to_low, 3),
        "low_to_high_max_gap_h": round(low_to_high, 3),
        "endpoint_gap_h": round(endpoint_gap_h, 3),
        "gap_position_category": gap_pos,
        "observed_coverage_fraction": round(coverage, 4),
        "sample_density_per_day": round(sample_density, 3),
        "ac_ratio_in_episode": round(ac_ratio, 4) if np.isfinite(ac_ratio) else float("nan"),
        "charge_ratio_in_episode": round(chg_ratio, 4) if np.isfinite(chg_ratio) else float("nan"),
        "discharge_ratio_in_episode": round(dis_ratio, 4) if np.isfinite(dis_ratio) else float("nan"),
    }


def attach_gap_quality(
    episodes: pd.DataFrame, df_by_user: Dict[str, pd.DataFrame],
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
) -> pd.DataFrame:
    """Add graded gap-quality + episode-span context columns to the episode table.

    Adds: high_to_low_max_gap_h, low_to_high_max_gap_h, endpoint_gap_h,
    gap_position_category, observed_coverage_fraction, sample_density_per_day,
    ac_ratio_in_episode, charge_ratio_in_episode, discharge_ratio_in_episode, rsoc_depth,
    episode_quality_score, quality_tier. The binary ``episode_quality`` is left untouched.
    """
    if episodes.empty:
        for c in ("episode_quality_score", "quality_tier"):
            episodes[c] = pd.Series(dtype="object")
        return episodes

    add_rows: List[Dict[str, object]] = []
    for uid, ueps in episodes.groupby("user_id", sort=False):
        g = df_by_user.get(uid)
        if g is None:
            continue
        ts = g["timestamp"]
        ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
        acdc = (g["acdcMode"].to_numpy() == 1).astype(float)
        cs = g["chargeStatus"].to_numpy() if "chargeStatus" in g.columns else None
        n = len(g)
        weights = sample_weights(ts, cfg.sample_weight_cap_h)
        for r in ueps.itertuples(index=False):
            s, lo, e = int(r.start_idx), int(r.low_idx), int(r.end_idx)
            base = {"episode_id": r.episode_id,
                    "rsoc_depth": float(getattr(r, "episode_depth", float("nan")))}
            quality = getattr(r, "episode_quality", "ok")
            if not (0 <= s < lo < e < n):
                base.update({"episode_quality_score": 0.0, "quality_tier": TIER_INVALID,
                             "high_to_low_max_gap_h": float("nan"),
                             "low_to_high_max_gap_h": float("nan"),
                             "endpoint_gap_h": float("nan"), "gap_position_category": "invalid",
                             "observed_coverage_fraction": 0.0, "sample_density_per_day": 0.0,
                             "ac_ratio_in_episode": float("nan"),
                             "charge_ratio_in_episode": float("nan"),
                             "discharge_ratio_in_episode": float("nan")})
                add_rows.append(base)
                continue
            feats = _episode_span_features(ts_ns, acdc, cs, s, lo, e, n, weights)
            max_gap = float(getattr(r, "max_gap_h_episode", feats.get("endpoint_gap_h", 0.0)))
            comp_gap = max_gap_component(max_gap)
            comp_cov = float(feats["observed_coverage_fraction"])
            comp_end = endpoint_component(feats["endpoint_gap_h"])
            score = W_MAXGAP * comp_gap + W_COVERAGE * comp_cov + W_ENDPOINT * comp_end
            if quality in ("missing_required_value", "invalid_order"):
                tier = TIER_INVALID
            else:
                tier = gap_quality_tier(max_gap, score)
            base.update(feats)
            base["episode_quality_score"] = round(float(score), 4)
            base["quality_tier"] = tier
            add_rows.append(base)

    add = pd.DataFrame(add_rows)
    return episodes.merge(add, on="episode_id", how="left")


def tier_distribution(episodes: pd.DataFrame, band: Optional[str] = None) -> pd.Series:
    """Count of episodes per quality_tier (optionally filtered to one band)."""
    df = episodes
    if band is not None and "threshold_name" in df.columns:
        df = df[df["threshold_name"] == band]
    if "quality_tier" not in df.columns:
        return pd.Series(dtype=int)
    return df["quality_tier"].value_counts()
