"""OD2 (Opportunity Definition 2) gauge-relearn opportunity extractor.

Motivation
----------
The OD1 pipeline (``fcc_learning.py`` / ``online_episode_detector.py``) defines a
fuel-gauge "learning opportunity" as an RSOC high->low->high *discharge* excursion using
the bands 90/10, 80/20 (primary) and 85/15. Per a domain correction from the project
owner, that is NOT how the gauge actually re-learns full-charge-capacity (FCC). The real
FCC-relearn logic has TWO distinct mechanisms:

  * **Type A - deep-discharge relearn:** full charge (RSOC >= FULL_PCT) -> discharge down
    to RSOC <= DEEP_PCT (default 6%) -> reach full charge again.
  * **Type B - charge-side partial relearn:** while *charging* (chargeStatus == 1), RSOC
    passes through the [BAND_LO, BAND_HI] band (default 60-80%), then reaches full charge.

In BOTH mechanisms the relearn COMPLETES when the pack reaches full charge, so the
episode END = full-charge attainment and the END-anchored 72h FCC-response audit is
structurally unchanged: did FCC step (>= 50 mWh) within [end, end+W]?

This module is strictly ADDITIVE. It imports the OD1 primitives it can reuse and never
modifies them; all OD1 modules, processed files and reports remain intact. Everything
here carries the ``od2`` version token.

Telemetry semantics (verified, PROJECT_STATUS.md):
  * ``remainingCapacityInPercentage`` IS RSOC (0-100, integer in this cohort).
  * ``fullChargeCapacity`` (FCC, mWh integer) drives SoH; SoH steps iff FCC steps.
  * ``chargeStatus`` 0 = no activity / idle, 1 = charge, 2 = discharge.
  * ``acdcMode`` 1 = AC, 0 = on battery. Duplicate timestamps: keep the LAST row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Reuse OD1 primitives verbatim (import only -- never edited).
from .fcc_learning import (
    extract_high_low_high_episodes,   # Type A reuses this exactly (high=FULL, low=DEEP)
    fcc_step_indicator,
    _sorted_unique,
)
from .online_episode_detector import (
    episode_response,          # END-anchored response at 24/72/168h (side="left")
    recover_design_mwh,
    step_threshold_mwh,
    DEFAULT_EFFECTIVE_STEP,
)

CODE_VERSION = "relearn_od2.0"
LABEL_VERSION = "od2.0"
THRESHOLD_VERSION = "od2_thresholds_1"

# FCC-response look-ahead windows (hours), measured from episode END. 72h is primary.
RESPONSE_WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
HOUR_NS = 3600 * 1_000_000_000


# --------------------------------------------------------------------------- #
# Opportunity definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TypeADef:
    """Deep-discharge relearn: full (>=full_pct) -> deep (<=deep_pct) -> full."""
    full_pct: float = 99.0
    deep_pct: float = 6.0
    kind: str = "A"

    @property
    def name(self) -> str:
        return f"typeA_full{int(self.full_pct)}_deep{int(self.deep_pct)}"


@dataclass(frozen=True)
class TypeBDef:
    """Charge-side partial relearn: charging through [band_lo, band_hi] -> full.

    Arms on the first *charging* (chargeStatus == 1) sample with band_lo <= RSOC <=
    band_hi. Closes when RSOC >= full_pct. Aborts (voids the attempt) if RSOC drops below
    ``abort_pct`` before full is reached (a real discharge interrupted the charge).
    """
    full_pct: float = 99.0
    band_lo: float = 60.0
    band_hi: float = 80.0
    abort_pct: float = 60.0
    kind: str = "B"

    @property
    def name(self) -> str:
        return f"typeB_band{int(self.band_lo)}_{int(self.band_hi)}_full{int(self.full_pct)}"


@dataclass(frozen=True)
class Od2Config:
    """All tunable OD2 thresholds (no magic numbers downstream)."""
    type_a: TypeADef = field(default_factory=TypeADef)
    type_b: TypeBDef = field(default_factory=TypeBDef)
    effective_step: str = DEFAULT_EFFECTIVE_STEP   # "abs_ge_50mWh"
    episode_max_gap_hours: float = 12.0            # max intra-episode gap for quality "ok"
    response_windows_h: Tuple[int, ...] = RESPONSE_WINDOWS_H


DEFAULT_OD2_CONFIG = Od2Config()


# --------------------------------------------------------------------------- #
# Type B state machine (charge-side; no discharge "low")
# --------------------------------------------------------------------------- #
def extract_typeB_episodes(
    rsoc: np.ndarray, charge_status: np.ndarray, d: TypeBDef,
) -> List[Tuple[int, int, int]]:
    """Return (arm, arm, end) POSITIONAL index triples for every Type-B relearn pass.

    ``arm`` is duplicated into the "low" slot for schema compatibility with the (start,
    low, end) episode record used across the codebase. RSOC that is NaN or outside
    [0, 100] is skipped (it neither arms, aborts nor closes a pass).
    """
    state = "WAIT"
    arm_idx: Optional[int] = None
    episodes: List[Tuple[int, int, int]] = []

    rs_seq = rsoc.tolist() if hasattr(rsoc, "tolist") else list(rsoc)
    cs_seq = charge_status.tolist() if hasattr(charge_status, "tolist") else list(charge_status)
    for idx, rs in enumerate(rs_seq):
        if rs is None or (isinstance(rs, float) and np.isnan(rs)) or rs < 0 or rs > 100:
            continue
        cs = cs_seq[idx]
        if state == "WAIT":
            if cs == 1 and d.band_lo <= rs <= d.band_hi:
                arm_idx = idx
                state = "ARMED"
        elif state == "ARMED":
            if rs >= d.full_pct:
                episodes.append((arm_idx, arm_idx, idx))
                arm_idx = None
                state = "WAIT"
            elif rs < d.abort_pct:
                arm_idx = None
                state = "WAIT"
    return episodes


def extract_typeA_episodes(rsoc: np.ndarray, d: TypeADef) -> List[Tuple[int, int, int]]:
    """Type A reuses the OD1 high->low->high machine with high=full_pct, low=deep_pct."""
    return extract_high_low_high_episodes(rsoc, d.full_pct, d.deep_pct)


# --------------------------------------------------------------------------- #
# Episode quality (type-aware ordering)
# --------------------------------------------------------------------------- #
def _episode_quality_od2(
    ts_ns: np.ndarray, fcc: np.ndarray, rsoc: np.ndarray,
    s: int, lo: int, e: int, opp_type: str, max_gap_hours: float,
) -> Tuple[str, float, float]:
    """Quality label + (max gap, median gap) hours over [s, e]. Type-aware order check.

    Priority: invalid_order > missing_required_value > large_gap > ok. Type A requires the
    strict discharge order s < lo < e; Type B has no discharge low (lo == s) so it requires
    only s <= lo < e (a degenerate lo == s must not trip invalid_order).
    """
    ok_order = (s < lo < e) if opp_type == "A" else (s <= lo < e)
    if not ok_order:
        return "invalid_order", float("nan"), float("nan")
    seg = slice(s, e + 1)
    gaps_h = np.diff(ts_ns[seg]) / 3.6e12
    max_gap = float(gaps_h.max()) if gaps_h.size else 0.0
    med_gap = float(np.median(gaps_h)) if gaps_h.size else 0.0
    fcc_missing = bool(np.isnan(fcc[seg]).any())
    rsoc_seg = rsoc[seg]
    rsoc_missing = bool(np.isnan(rsoc_seg).any() or ((rsoc_seg < 0) | (rsoc_seg > 100)).any())
    if fcc_missing or rsoc_missing:
        return "missing_required_value", max_gap, med_gap
    if max_gap > max_gap_hours:
        return "large_gap", max_gap, med_gap
    return "ok", max_gap, med_gap


def _episode_id(uid: str, def_name: str, start_ns: int, end_ns: int) -> str:
    return f"{uid}|{def_name}|{start_ns}|{end_ns}"


def _build_records(
    uid: str, d, opp_type: str, triples: List[Tuple[int, int, int]],
    ts_ns: np.ndarray, ts: pd.Series, rsoc: np.ndarray, fcc: np.ndarray,
    cyc: np.ndarray, chg: np.ndarray, acdc: np.ndarray, is_step: np.ndarray,
    last_ts_ns: int, cfg: Od2Config,
) -> List[Dict[str, object]]:
    """Turn positional (start, low, end) triples into full OD2 episode records."""
    rows: List[Dict[str, object]] = []
    for (s, lo, e) in triples:
        start_ns, end_ns = int(ts_ns[s]), int(ts_ns[e])
        qual, max_gap, med_gap = _episode_quality_od2(
            ts_ns, fcc, rsoc, s, lo, e, opp_type, cfg.episode_max_gap_hours)
        pre_end_gap_h = (float((ts_ns[e] - ts_ns[e - 1]) / 3.6e12) if e > 0 else float("nan"))
        if opp_type == "A":
            depth = float(rsoc[s] - rsoc[lo])            # discharge depth (~93)
        else:
            depth = float(rsoc[e] - rsoc[lo])            # charge span from band entry (~20-39)
        rec: Dict[str, object] = {
            "episode_id": _episode_id(uid, d.name, start_ns, end_ns),
            "user_id": uid,
            "opportunity_type": opp_type,
            "threshold_name": d.name,        # reuse the OD1 column name for tooling compat
            "start_ts": ts.iloc[s], "low_ts": ts.iloc[lo], "end_ts": ts.iloc[e],
            "start_idx": int(s), "low_idx": int(lo), "end_idx": int(e),
            "start_rsoc": float(rsoc[s]), "low_rsoc": float(rsoc[lo]), "end_rsoc": float(rsoc[e]),
            "band_entry_rsoc": (float(rsoc[lo]) if opp_type == "B" else float("nan")),
            "episode_depth": round(depth, 2),
            "arm_to_full_duration_h": (round(float((end_ns - start_ns) / 3.6e12), 3)
                                       if opp_type == "B" else float("nan")),
            "episode_duration_h": round(float((end_ns - start_ns) / 3.6e12), 3),
            "cycle_delta_episode": round(float(cyc[e] - cyc[s]), 2),
            "fcc_before_episode": float(fcc[s]),
            "pre_end_gap_h": round(pre_end_gap_h, 3) if np.isfinite(pre_end_gap_h) else float("nan"),
            "end_charge_status": (float(chg[e]) if np.isfinite(chg[e]) else float("nan")),
            "end_acdc": (float(acdc[e]) if np.isfinite(acdc[e]) else float("nan")),
            "n_samples_episode": int(e - s + 1),
            "max_gap_h_episode": round(max_gap, 3) if np.isfinite(max_gap) else float("nan"),
            "median_gap_h_episode": round(med_gap, 3) if np.isfinite(med_gap) else float("nan"),
            "episode_quality": qual,
        }
        # END-anchored FCC response at 24/72/168h (imported verbatim from OD1 online layer).
        rec.update(episode_response(ts_ns, fcc, is_step, e, last_ts_ns, cfg.response_windows_h))
        rows.append(rec)
    return rows


# --------------------------------------------------------------------------- #
# Per-user processing
# --------------------------------------------------------------------------- #
def process_user_od2(
    uid: str, g: pd.DataFrame, cfg: Od2Config = DEFAULT_OD2_CONFIG,
    design_mwh: Optional[float] = None, inference_last_ts: Optional[pd.Timestamp] = None,
) -> List[Dict[str, object]]:
    """All OD2 opportunities (Type A + Type B) for one user, with END-anchored response.

    ``g`` need not be pre-sorted -- this sorts & de-duplicates internally (spec 5.1). The
    returned rows are episode-level; union de-duplication on (user_id, end_idx) is done by
    the caller so the same full-charge END is audited once.
    """
    g = _sorted_unique(g)
    if len(g) < 2:
        return []
    if design_mwh is None:
        design_mwh = recover_design_mwh(g)
    min_mwh = step_threshold_mwh(cfg.effective_step, design_mwh)

    rsoc = g["remainingCapacityInPercentage"].to_numpy(dtype=float)
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    chg = g["chargeStatus"].to_numpy(dtype=float) if "chargeStatus" in g else np.full(len(g), np.nan)
    acdc = g["acdcMode"].to_numpy(dtype=float) if "acdcMode" in g else np.full(len(g), np.nan)
    ts = g["timestamp"]
    ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
    last_ts_ns = (int(ts_ns[-1]) if inference_last_ts is None
                  else int(pd.Timestamp(inference_last_ts).value))
    is_step, _ = fcc_step_indicator(fcc, min_mwh)

    rows: List[Dict[str, object]] = []
    a_triples = extract_typeA_episodes(rsoc, cfg.type_a)
    rows.extend(_build_records(uid, cfg.type_a, "A", a_triples, ts_ns, ts, rsoc, fcc,
                               cyc, chg, acdc, is_step, last_ts_ns, cfg))
    b_triples = extract_typeB_episodes(rsoc, chg, cfg.type_b)
    rows.extend(_build_records(uid, cfg.type_b, "B", b_triples, ts_ns, ts, rsoc, fcc,
                               cyc, chg, acdc, is_step, last_ts_ns, cfg))
    return rows


def add_union_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Mark one representative row per distinct relearn END (dedup on user_id, end_idx).

    Adds:
      * ``is_union_primary`` (bool): True for exactly one row per (user_id, end_idx); when
        both Type A and Type B close on the same END, the Type A row (deeper information)
        is kept as primary.
      * ``union_types`` (str): comma-joined set of opportunity types sharing that END.
    The union is the headline opportunity set for user counts and the response audit, so a
    coincident A/B END is never double-counted.
    """
    if df.empty:
        df["is_union_primary"] = pd.Series(dtype=bool)
        df["union_types"] = pd.Series(dtype=object)
        return df
    df = df.copy()
    # union_types per (user, end)
    types = (df.groupby(["user_id", "end_idx"])["opportunity_type"]
             .agg(lambda s: ",".join(sorted(set(s)))))
    df["union_types"] = df.set_index(["user_id", "end_idx"]).index.map(types).to_numpy()
    # primary = Type A if present at that END else Type B; keep first row of the winning type
    a_rank = {"A": 0, "B": 1}
    df["_rank"] = df["opportunity_type"].map(a_rank)
    df = df.sort_values(["user_id", "end_idx", "_rank"], kind="stable")
    is_primary = ~df.duplicated(subset=["user_id", "end_idx"], keep="first")
    df["is_union_primary"] = is_primary.to_numpy()
    return df.drop(columns="_rank")
