"""OD2 per-user feature table for the offline triage classifier (Phase 2).

The final triage classifier (``fcc_final.classify_user_final``) reads two kinds of
per-user columns:

  * OPPORTUNITY-INDEPENDENT freeze / usage / quality features
    (flat_tail_days, fcc_changes, tail_cycle_delta, tail_min_rsoc, tail_ac_time_ratio,
    data_quality_label, obs_days, candidate-flag inputs ...). These do NOT depend on how a
    "learning opportunity" is defined -- they come from the raw RSOC / FCC / cycle stream
    -- so we REUSE them verbatim from ``fcc_learning.process_user``.
  * OPPORTUNITY-DERIVED counts / response columns (tail_n_80_20_80_ok,
    tail_n_unresponded_80_20_80_complete_window_{w}, tail_response_rate_*, ...). These DO
    change under the corrected relearn definition. We recompute them from the OD2 episodes
    and write them into the SAME band-named slots the classifier expects, using the mapping
    agreed in the OD2 plan:

        classifier "90_10_90" (strict, "one opportunity is strong evidence")  <- Type A
        classifier "80_20_80" (primary, the workhorse count)                  <- Type B

  * The "no opportunity" gauge gate (``_no_opportunity``) then means "no Type A AND no
    Type B opportunity" -- i.e. the union is empty -- which is exactly right.

Nothing in the OD1 pipeline is modified; this module composes OD1 + OD2 by import only.
The classifier is driven with ``FinalThresholds(response_window="168h")`` per the Phase-1
finding that the true relearn latency exceeds 72h.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .fcc_learning import process_user, DEFAULT_CONFIG, FccLearningConfig
from .relearn_od2 import Od2Config, DEFAULT_OD2_CONFIG, process_user_od2, RESPONSE_WINDOWS_H

# classifier slot  <-  OD2 opportunity type
BAND_FOR_TYPE = {"B": "80_20_80", "A": "90_10_90"}
PRIMARY_WINDOW_H = 168   # OD2 primary response window (Phase-1 decision)


def _resp_rate(eps: List[Dict], w: int) -> float:
    """Fraction responded among KNOWN (responded|no_response) episodes at window w. NaN if none."""
    known = [e for e in eps if e[f"response_status_{w}h"] in ("responded", "no_response")]
    if not known:
        return float("nan")
    return round(sum(1 for e in known if e[f"response_status_{w}h"] == "responded") / len(known), 4)


def build_od2_user_row(
    uid: str, g: pd.DataFrame,
    od1_cfg: FccLearningConfig = DEFAULT_CONFIG, od2_cfg: Od2Config = DEFAULT_OD2_CONFIG,
) -> Dict[str, object]:
    """One merged feature row: OD1 freeze/usage features + OD2-mapped opportunity columns."""
    feat, _od1_eps = process_user(uid, g, od1_cfg)          # freeze + tail-usage + candidate inputs
    last_change = feat["last_fcc_change_ts"]
    od2_eps = process_user_od2(uid, g, od2_cfg)

    # Overwrite the band-named opportunity columns with OD2-derived values.
    for opp_type, band in BAND_FOR_TYPE.items():
        eps = [e for e in od2_eps if e["opportunity_type"] == opp_type]
        tail_eps = [e for e in eps if e["start_ts"] >= last_change]
        tail_ok = [e for e in tail_eps if e["episode_quality"] == "ok"]
        tail_lg = [e for e in tail_eps if e["episode_quality"] == "large_gap"]
        total_ok = [e for e in eps if e["episode_quality"] == "ok"]
        feat[f"tail_n_{band}_ok"] = len(tail_ok)
        feat[f"tail_n_{band}_large_gap"] = len(tail_lg)
        feat[f"tail_n_{band}_any"] = len(tail_eps)
        feat[f"total_n_{band}_ok"] = len(total_ok)
        for w in RESPONSE_WINDOWS_H:
            feat[f"tail_n_unresponded_{band}_complete_window_{w}h"] = sum(
                1 for e in tail_ok if e[f"response_status_{w}h"] == "no_response")
            feat[f"tail_n_censored_{band}_{w}h"] = sum(
                1 for e in tail_ok if e[f"response_status_{w}h"] == "censored")
            feat[f"tail_response_rate_{band}_{w}h"] = _resp_rate(tail_ok, w)
            feat[f"total_response_rate_{band}_{w}h"] = _resp_rate(total_ok, w)
        # canonical (unsuffixed) aliases used by the classifier's default-window helpers
        feat[f"tail_n_unresponded_{band}_complete_window"] = \
            feat[f"tail_n_unresponded_{band}_complete_window_{PRIMARY_WINDOW_H}h"]
        feat[f"tail_n_censored_{band}"] = feat[f"tail_n_censored_{band}_{PRIMARY_WINDOW_H}h"]

    # relevant_response_rate at each window: primary band (Type B) first, fall back to strict (Type A).
    for w in RESPONSE_WINDOWS_H:
        rel = feat[f"tail_response_rate_80_20_80_{w}h"]
        if pd.isna(rel):
            rel = feat[f"tail_response_rate_90_10_90_{w}h"]
        feat[f"relevant_response_rate_{w}h"] = rel

    # OD2 union bookkeeping (descriptive; the no-opportunity gate uses A==0 & B==0 which == union==0)
    tail_union = [e for e in od2_eps if e["start_ts"] >= last_change]
    feat["od2_tail_n_union_any"] = len({(e["end_idx"]) for e in tail_union})
    feat["od2_tail_n_typeA_ok"] = feat["tail_n_90_10_90_ok"]
    feat["od2_tail_n_typeB_ok"] = feat["tail_n_80_20_80_ok"]
    feat["opportunity_definition"] = "od2"
    return feat


def build_od2_cohort_features(
    df: pd.DataFrame, od2_cfg: Od2Config = DEFAULT_OD2_CONFIG,
    progress_every: int = 100,
) -> pd.DataFrame:
    """Per-user OD2 feature table for the whole cohort (one row per user)."""
    rows: List[Dict[str, object]] = []
    groups = df.groupby("user_id", sort=False)
    n = groups.ngroups
    for i, (uid, g) in enumerate(groups):
        rows.append(build_od2_user_row(uid, g, od2_cfg=od2_cfg))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  ... {i + 1}/{n} users", flush=True)
    return pd.DataFrame(rows)
