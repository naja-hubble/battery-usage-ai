"""Cross-user aggregation: build the cohort table, summary stats and personas."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .anon import display_id
from .config import Config
from .features import extract_features
from .parse import UserData, iter_user_dirs, load_user


def build_cohort_table(cfg: Config, user_dirs: Optional[List[Path]] = None) -> pd.DataFrame:
    """Parse every downloaded user and assemble one feature row each.

    Resilient per user: a single malformed user is logged and skipped rather than
    aborting the whole cohort. Users with fewer than ``cohort.min_rows`` parsed rows
    are dropped. A pseudonymous ``display_id`` is attached for shareable outputs.
    """
    if user_dirs is None:
        user_dirs = iter_user_dirs(cfg.raw_dir)
    min_rows = cfg.cohort.get("min_rows", 0) or 0
    anonymize = cfg.analysis.get("anonymize", True)
    rows = []
    skipped_short = 0
    for ud_dir in user_dirs:
        try:
            ud = load_user(ud_dir)
            if len(ud.battery) < min_rows:
                skipped_short += 1
                continue
            row = extract_features(ud, cfg)
        except Exception as exc:  # noqa: BLE001 - never let one user abort the run
            print(f"  WARN: skipping {ud_dir.name}: {exc!r}")
            continue
        row["display_id"] = display_id(ud.safe_id, anonymize)
        rows.append(row)
    if skipped_short:
        print(f"  skipped {skipped_short} users with < {min_rows} parsed rows")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Surface display_id first; keep users with a usable series up front (sort by health).
    cols = ["display_id"] + [c for c in df.columns if c != "display_id"]
    df = df[cols]
    sort_col = "soh_peak_pct" if "soh_peak_pct" in df else "n_samples"
    return df.sort_values(sort_col, ascending=False, na_position="last").reset_index(drop=True)


# Features that define a usage "persona" (scale-invariant behavioural signals).
PERSONA_FEATURES = [
    "ac_time_ratio",
    "mean_pct_remaining",
    "mean_dod_pct",
    "cycles_per_year",
    "time_ratio_full_on_ac",
]


def assign_personas(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """KMeans usage personas + a human-readable label. No-op if too few users."""
    n = cfg.analysis.get("n_personas", 0)
    df = df.copy()
    if not n or len(df) < n:
        df["persona"] = -1
        df["persona_label"] = "unclustered"
        return df

    feats = [c for c in PERSONA_FEATURES if c in df.columns]
    X = df[feats].apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median(numeric_only=True))
    # Standardise then cluster.
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
    except Exception:
        df["persona"] = -1
        df["persona_label"] = "unclustered"
        return df

    Xs = StandardScaler().fit_transform(X.to_numpy())
    km = KMeans(n_clusters=n, n_init=10, random_state=cfg.cohort.get("seed", 42))
    df["persona"] = km.fit_predict(Xs)
    df["persona_label"] = _label_personas(df)
    return df


def _label_personas(df: pd.DataFrame) -> pd.Series:
    """Derive a descriptive label per cluster from its centroid behaviour."""
    labels = {}
    ac_med = df["ac_time_ratio"].median() if "ac_time_ratio" in df else 0.5
    cyc_med = df["cycles_per_year"].median() if "cycles_per_year" in df else np.nan
    for pid, g in df.groupby("persona"):
        ac = g["ac_time_ratio"].mean() if "ac_time_ratio" in g else np.nan
        cyc = g["cycles_per_year"].mean() if "cycles_per_year" in g else np.nan
        if pd.notna(ac) and ac >= max(0.85, ac_med):
            mobility = "desk-bound (mostly AC)"
        elif pd.notna(ac) and ac <= min(0.6, ac_med):
            mobility = "mobile (heavy battery use)"
        else:
            mobility = "mixed use"
        wear = ""
        if pd.notna(cyc) and pd.notna(cyc_med):
            wear = " · high cycling" if cyc >= cyc_med else " · low cycling"
        labels[pid] = f"{mobility}{wear}"
    return df["persona"].map(labels)


# Columns summarised in the cohort report (numeric).
SUMMARY_COLUMNS = [
    "observation_days", "n_samples",
    "soh_design_pct", "soh_peak_pct", "capacity_fade_pct",
    "cycle_count_last", "cycles_per_year", "fade_pct_per_year", "fade_pct_per_100_cycles",
    "ac_time_ratio", "mean_pct_remaining", "time_ratio_below_20pct", "time_ratio_full_on_ac",
    "n_discharge_sessions", "mean_dod_pct", "median_drain_pct_per_hr",
    "hours_high_temp_last", "frac_awake_high_temp",
]


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Distribution table (count/mean/median/std/min/max) over summary columns."""
    cols = [c for c in SUMMARY_COLUMNS if c in df.columns]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    out = num.describe(percentiles=[0.25, 0.5, 0.75]).T
    return out[["count", "mean", "50%", "std", "min", "max"]].rename(columns={"50%": "median"})


def run_aggregation(cfg: Config) -> Dict[str, object]:
    """Full aggregation step: cohort table + personas + summary, persisted to disk."""
    cfg.ensure_dirs()
    cohort = build_cohort_table(cfg)
    if cohort.empty:
        raise RuntimeError(f"No parseable users found under {cfg.raw_dir}. Run `download` first.")
    cohort = assign_personas(cohort, cfg)
    summary = summarize(cohort)

    cohort_path = cfg.processed_dir / "cohort_features.csv"
    summary_path = cfg.processed_dir / "cohort_summary.csv"
    cohort.to_csv(cohort_path, index=False)
    summary.to_csv(summary_path)
    print(f"  wrote {cohort_path}  ({len(cohort)} users, {cohort.shape[1]} features)")
    print(f"  wrote {summary_path}")
    return {"cohort": cohort, "summary": summary,
            "cohort_path": cohort_path, "summary_path": summary_path}
