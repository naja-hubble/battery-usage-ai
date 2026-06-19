"""Patent evidence — Analysis A: opportunity/response comparator ablation (A0..A6).

ADDITIVE & READ-ONLY w.r.t. production. This module does NOT re-implement the
production episode/response detection. It operates on the *already-computed*
per-user tail features that the production full-history pipeline persisted in
``fcc_final_action_labels.csv`` (columns ``tail_n_*``, ``flat_tail_days``,
``tail_cycle_delta``, ``fcc_effective_changes_50mwh`` ...).  The production
``final_label`` is used ONLY as a comparison proxy (never as a training target).

Each ablation variant re-derives an "actionable / flagged" decision from a
progressively richer subset of those features, so we can measure the *marginal
technical effect* of each invention family:

    A0  flat_tail_days only                      (static stale rule)
    A1  flat tail + cycle delta                  (+ throughput gate)
    A2  opportunity count only (any quality)      (stimulus, no response)
    A3  opportunity + response, ignore censor/gap (naive response)
    A4  END-anchored + censor-aware, single step  (IC1 core)
    A5  A4 + gap tier (exclude large_gap)         (+ IC6 gap quality)
    A6  full proposed (production final_label)     (IC1+IC6+dual-track+branch)

The proxy reference set is the production *actionable* set (FW + Gauge).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

import numpy as np
import pandas as pd

# ---- production label vocabulary (full-history v2.0-final) ----
LABEL_FW = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
LABEL_GAUGE = "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY"
LABEL_WATCH = "WATCH_LOW_UPDATE_RATE_AMBIGUOUS"
LABEL_REVIEW = "REVIEW_INSUFFICIENT_DATA"
LABEL_NORMAL = "NORMAL_OR_RESPONDING"
ACTIONABLE_LABELS = {LABEL_FW, LABEL_GAUGE}

# ---- thresholds (mirror production gate values; documented in claim 3) ----
FLAT_TAIL_FW_DAYS = 180.0
FLAT_TAIL_GAUGE_DAYS = 120.0
TAIL_CYCLE_DELTA_MIN = 30.0
UNRESP_PRIMARY_MIN = 3      # 80/20/80 complete-window OK no-response count
UNRESP_STRICT_MIN = 2       # 90/10/90 complete-window OK no-response count
OPP_ANY_MIN = 1             # at least one (any-quality) opportunity


def _safe(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise KeyError(f"required column missing: {col}")
    return df[col]


def _flagged_set(mask: pd.Series, ids: pd.Series) -> Set[str]:
    return set(ids[mask.fillna(False).astype(bool)].tolist())


@dataclass
class AblationResult:
    variant: str
    description: str
    invention_family: str
    flagged: Set[str] = field(default_factory=set)


def derive_variants(df: pd.DataFrame) -> Dict[str, AblationResult]:
    """Return per-variant flagged user-id sets, computed from per-user features."""
    ids = _safe(df, "user_id")
    flat = _safe(df, "flat_tail_days").astype(float)
    tcyc = _safe(df, "tail_cycle_delta").astype(float)
    # opportunity counts (tier-graded), END-anchored unresponded counts, censored
    opp_any = _safe(df, "tail_n_80_20_80_any").astype(float) + _safe(df, "tail_n_90_10_90_any").astype(float)
    opp_ok = _safe(df, "tail_n_80_20_80_ok").astype(float) + _safe(df, "tail_n_90_10_90_ok").astype(float)
    unresp_ok_80 = _safe(df, "tail_n_unresponded_80_20_80_complete_window").astype(float)
    unresp_ok_90 = _safe(df, "tail_n_unresponded_90_10_90_complete_window").astype(float)
    large_gap = _safe(df, "tail_n_80_20_80_large_gap").astype(float) + _safe(df, "tail_n_90_10_90_large_gap").astype(float)
    censored = _safe(df, "tail_n_censored_80_20_80").astype(float) + _safe(df, "tail_n_censored_90_10_90").astype(float)
    final = _safe(df, "final_label").astype(str)

    out: Dict[str, AblationResult] = {}

    # A0: static stale rule — flat tail only
    m = flat >= FLAT_TAIL_FW_DAYS
    out["A0"] = AblationResult("A0", "flat_tail_days>=180 only", "static-baseline", _flagged_set(m, ids))

    # A1: + throughput (cycle delta)
    m = (flat >= FLAT_TAIL_FW_DAYS) & (tcyc >= TAIL_CYCLE_DELTA_MIN)
    out["A1"] = AblationResult("A1", "flat tail + tail_cycle_delta>=30", "static-baseline", _flagged_set(m, ids))

    # A2: opportunity count only (any quality), stale gate — stimulus, no response check
    m = (flat >= FLAT_TAIL_FW_DAYS) & (opp_any >= OPP_ANY_MIN)
    out["A2"] = AblationResult("A2", "stale + >=1 any-quality opportunity (no response check)", "IC1-stimulus", _flagged_set(m, ids))

    # A3: opportunity + response but censor/gap-blind (count ANY no-response incl. large_gap & censored)
    # naive no-response = opportunities that are not OK-responded; approximate by (any opportunities) minus (none) and
    # treat large_gap/censored as no-response evidence.
    naive_noresp = unresp_ok_80 + unresp_ok_90 + large_gap + censored
    m = (flat >= FLAT_TAIL_FW_DAYS) & (tcyc >= TAIL_CYCLE_DELTA_MIN) & (naive_noresp >= UNRESP_PRIMARY_MIN)
    out["A3"] = AblationResult("A3", "END+response but censor/gap counted as no-response", "IC1-naive", _flagged_set(m, ids))

    # A4: END-anchored + censor-aware, single FCC step def (censored excluded; large_gap STILL counted)
    noresp_a4 = unresp_ok_80 + large_gap  # OK complete-window no-response + large_gap (gap tier not yet applied), censored excluded
    m = (flat >= FLAT_TAIL_FW_DAYS) & (tcyc >= TAIL_CYCLE_DELTA_MIN) & (
        (noresp_a4 >= UNRESP_PRIMARY_MIN) | (unresp_ok_90 + large_gap >= UNRESP_STRICT_MIN)
    )
    out["A4"] = AblationResult("A4", "END-anchored, censor-aware, single step (IC1 core)", "IC1", _flagged_set(m, ids))

    # A5: A4 + gap tier (exclude large_gap from no-response evidence)
    m = (flat >= FLAT_TAIL_FW_DAYS) & (tcyc >= TAIL_CYCLE_DELTA_MIN) & (
        (unresp_ok_80 >= UNRESP_PRIMARY_MIN) | (unresp_ok_90 >= UNRESP_STRICT_MIN)
    )
    out["A5"] = AblationResult("A5", "IC1 + gap-quality tier (exclude large_gap)", "IC1+IC6", _flagged_set(m, ids))

    # A6: full proposed — production actionable (FW + Gauge), branch + dual-track included
    m = final.isin(ACTIONABLE_LABELS)
    out["A6"] = AblationResult("A6", "full proposed (production final_label actionable)", "IC1+IC6+IC2+branch", _flagged_set(m, ids))

    return out


def evaluate(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-variant metrics vs the production proxy reference."""
    ids = _safe(df, "user_id")
    final = _safe(df, "final_label").astype(str)
    eff = _safe(df, "fcc_effective_changes_50mwh").astype(float)

    proxy_actionable = set(ids[final.isin(ACTIONABLE_LABELS)].tolist())
    proxy_fw = set(ids[final == LABEL_FW].tolist())
    proxy_gauge = set(ids[final == LABEL_GAUGE].tolist())
    normal_ids = set(ids[final == LABEL_NORMAL].tolist())
    # "effective-active" = a user that DID produce >=1 effective FCC step (a true responder)
    eff_active_ids = set(ids[eff >= 1].tolist())

    variants = derive_variants(df)
    rows: List[dict] = []
    for key, res in variants.items():
        flagged = res.flagged
        nf = len(flagged) or 0
        tp = len(flagged & proxy_actionable)
        prec = tp / nf if nf else float("nan")
        rec = tp / len(proxy_actionable) if proxy_actionable else float("nan")
        union = len(flagged | proxy_actionable)
        jacc = tp / union if union else float("nan")
        rows.append({
            "variant": res.variant,
            "description": res.description,
            "invention_family": res.invention_family,
            "n_flagged": nf,
            "legacy_active_false_action": len(flagged & normal_ids),
            "effective_active_false_action": len(flagged & eff_active_ids),
            "proxy_precision": round(prec, 4) if nf else None,
            "proxy_recall": round(rec, 4) if proxy_actionable else None,
            "label_jaccard_vs_production": round(jacc, 4) if union else None,
            "proxy_fw_captured": len(flagged & proxy_fw),
            "proxy_gauge_captured": len(flagged & proxy_gauge),
            "proxy_fw_missed_silent": len(proxy_fw - flagged),
            "proxy_gauge_missed_silent": len(proxy_gauge - flagged),
        })
    return pd.DataFrame(rows)
