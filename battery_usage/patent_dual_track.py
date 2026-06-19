"""Patent evidence — Analysis C: any/effective dual-track step-magnitude evidence.

ADDITIVE. Extracts the empirical distribution of FCC (fullChargeCapacity)
*step* magnitudes from the persisted long time-series, characterises the
quantization unit and the micro-wobble vs effective-step regimes, and compares
candidate effective-step thresholds. This justifies (or, honestly, fails to
justify) the production 50 mWh effective-step definition and supports the
any/effective dual-track invention family (IC2).

No production logic is duplicated: this only reads ``fullChargeCapacity`` deltas.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

THRESHOLDS_MWH = [10, 20, 30, 40, 50, 75, 100]
THRESHOLDS_PCT_DESIGN = [0.05, 0.1, 0.2, 0.5]  # percent of DesignCapacity


def fcc_steps(ts: pd.DataFrame) -> pd.DataFrame:
    """Return one row per FCC change event: user_id, signed step (mWh), |step|.

    A *step* is a change in fullChargeCapacity between consecutive in-time
    samples for a user. Zero-deltas (the dominant periodic samples) are dropped.
    """
    need = {"user_id", "timestamp", "fullChargeCapacity"}
    missing = need - set(ts.columns)
    if missing:
        raise KeyError(f"timeseries missing columns: {missing}")
    df = ts[["user_id", "timestamp", "fullChargeCapacity"]].copy()
    df = df.dropna(subset=["fullChargeCapacity"])
    df = df.sort_values(["user_id", "timestamp"])
    df["fcc_prev"] = df.groupby("user_id")["fullChargeCapacity"].shift(1)
    df["step"] = df["fullChargeCapacity"] - df["fcc_prev"]
    df = df.dropna(subset=["step"])
    df = df[df["step"] != 0]
    df["abs_step"] = df["step"].abs()
    return df[["user_id", "timestamp", "step", "abs_step"]]


def step_magnitude_summary(steps: pd.DataFrame) -> Dict[str, float]:
    a = steps["abs_step"].to_numpy()
    pos = a[a > 0]
    # quantization unit = smallest observed positive |step| (gauge reports integer mWh)
    quant = float(np.min(pos)) if pos.size else float("nan")
    return {
        "n_steps": int(a.size),
        "quantization_unit_mwh": quant,
        "abs_step_p05": float(np.percentile(a, 5)) if a.size else float("nan"),
        "abs_step_p50": float(np.percentile(a, 50)) if a.size else float("nan"),
        "abs_step_p90": float(np.percentile(a, 90)) if a.size else float("nan"),
        "abs_step_p99": float(np.percentile(a, 99)) if a.size else float("nan"),
        "frac_micro_lt_50mwh": float(np.mean(a < 50)) if a.size else float("nan"),
        "frac_effective_ge_50mwh": float(np.mean(a >= 50)) if a.size else float("nan"),
    }


def threshold_comparison(steps: pd.DataFrame, design_by_user: pd.Series) -> pd.DataFrame:
    """For each candidate effective-step threshold, count effective steps & the
    number of users whose *every* step is below the threshold (i.e. would be
    declared 'no effective update / frozen' under that threshold)."""
    rows: List[dict] = []
    n_users = steps["user_id"].nunique()
    grp_max = steps.groupby("user_id")["abs_step"].max()
    for t in THRESHOLDS_MWH:
        eff = steps["abs_step"] >= t
        users_all_below = int((grp_max < t).sum())
        rows.append({
            "threshold_kind": "fixed_mwh",
            "threshold": float(t),
            "n_effective_steps": int(eff.sum()),
            "frac_effective": round(float(eff.mean()), 4),
            "users_all_steps_below_thr": users_all_below,
            "users_all_steps_below_thr_frac": round(users_all_below / n_users, 4) if n_users else None,
        })
    # percent-of-DesignCapacity thresholds (per-user adaptive)
    dmap = design_by_user.to_dict()
    su = steps.copy()
    su["design"] = su["user_id"].map(dmap)
    su = su.dropna(subset=["design"])
    for p in THRESHOLDS_PCT_DESIGN:
        thr_user = su["design"] * (p / 100.0)
        eff = su["abs_step"] >= thr_user
        # per-user: is max step below its own pct threshold?
        gm = su.groupby("user_id").apply(lambda g: g["abs_step"].max() < (g["design"].iloc[0] * p / 100.0))
        rows.append({
            "threshold_kind": "pct_design",
            "threshold": float(p),
            "n_effective_steps": int(eff.sum()),
            "frac_effective": round(float(eff.mean()), 4),
            "users_all_steps_below_thr": int(gm.sum()),
            "users_all_steps_below_thr_frac": round(int(gm.sum()) / max(su["user_id"].nunique(), 1), 4),
        })
    return pd.DataFrame(rows)
