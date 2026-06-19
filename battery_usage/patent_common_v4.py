"""Shared foundation for the FCC patent-evidence v4 completion package.

ADDITIVE & READ-ONLY w.r.t. production. This module centralises the primitives
that the v4 raw-trace analyses (A2 negative controls, A3 anchor comparison, B
response hazard, C2 dual-track reset ablation, C3 effective-threshold, D
retention invariance + state minimality, E missingness stress) all share, so
every analysis uses *one* causal convention and *one* clustered-bootstrap:

  * episode / step / sample loaders (full-history production episodes + a cached
    per-user FCC-step event table extracted from the long time series);
  * the END-anchored, censor-aware response convention (re-using the production
    ``online_episode_detector`` primitives verbatim, so nothing is re-derived);
  * USER-clustered bootstrap helpers (never episode-clustered -- spec section 2.10);
  * an empirical randomization p-value;
  * a PII guard + deterministic anonymisation hash for any per-entity artifact.

Technical evidence for patent review -- NOT a legal opinion.  No ground truth,
intervention outcome, firmware version or causal conclusion is fabricated here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .fcc_learning import EPISODE_THRESHOLDS, fcc_step_indicator
from .online_episode_detector import (
    PRIMARY_THRESHOLD, STRICT_THRESHOLD, SECONDARY_THRESHOLD,
    recover_design_mwh, step_threshold_mwh, OnlineConfig, DEFAULT_ONLINE_CONFIG,
    extract_episodes_causal, prepare_user,
)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parents[1]
PROC = REPO / "data" / "processed"
REPORTS = REPO / "data" / "reports"
V3_DIR = PROC / "fcc_patent_evidence_v3"
V4_DIR = PROC / "fcc_patent_evidence_v4"
FIG_DIR = REPORTS / "figures" / "fcc_patent_evidence_v4"

TIMESERIES = PROC / "battery_timeseries_all.parquet"
FULL_EPISODES = PROC / "fcc_final_learning_episodes.csv"
ACTION_LABELS = PROC / "fcc_final_action_labels.csv"
ONLINE_SNAPSHOT = PROC / "fcc_online_v2" / "online_latest_snapshot_v2.csv"
ONLINE_STATEFUL = PROC / "fcc_online_v2" / "online_stateful_labels_v2.parquet"

# cached compact shared inputs (built once by ``ensure_shared_inputs``)
STEPS_CACHE = V4_DIR / "_fcc_steps_full.parquet"
DESIGN_CACHE = V4_DIR / "_design_by_user.csv"
LEDGER_CACHE = V4_DIR / "_reference_event_ledger.parquet"      # internal (keeps user_id for joins)

CODE_VERSION = "patent_evidence_v4.0"

# --------------------------------------------------------------------------- #
# Conventions (mirror production -- do not diverge)
# --------------------------------------------------------------------------- #
EFFECTIVE_STEP_MWH = 50.0
RESPONSE_WINDOWS_H: Tuple[int, ...] = (24, 72, 168)
PRIMARY_WINDOW_H = 72
EPISODE_MAX_GAP_H = 12.0       # ok vs large_gap (production binary)
MEDIUM_GAP_H = 24.0            # graded MEDIUM_GAP ceiling

HOUR_NS = 3600 * 1_000_000_000
DAY_NS = 86_400 * 1_000_000_000

# quality tiers (graded; mirror online_gap_quality)
TIER_HIGH = "HIGH_OK"
TIER_MEDIUM = "MEDIUM_GAP"
TIER_LOW = "LOW_LARGE_GAP"
NO_RESPONSE_CAPABLE = (TIER_HIGH, TIER_MEDIUM)

# response statuses that may *never* be counted as confirmed no-response (spec 2.3/2.4)
NEVER_NO_RESPONSE = ("censored", "unknown")

# fields that must never leave the cohort as raw identifiers (spec 14 / 17 PII)
PII_COLUMNS = (
    "user_id", "serialNumber", "serial_number", "product_uuid", "uuid",
    "batt_fru", "IdentifyingNumber", "device_model", "batt_vendor", "manufacturer",
)
_HASH_SALT = "fcc_patent_v4"   # fixed (not random) so anon ids are reproducible


# --------------------------------------------------------------------------- #
# Determinism / dirs
# --------------------------------------------------------------------------- #
def rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


def ensure_dirs() -> None:
    V4_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Anonymisation / PII guard
# --------------------------------------------------------------------------- #
def hash_id(value: object) -> str:
    return hashlib.sha1(f"{_HASH_SALT}|{value}".encode("utf-8")).hexdigest()[:12]


def add_anon_id(df: pd.DataFrame, src: str = "user_id", dst: str = "anon_id") -> pd.DataFrame:
    out = df.copy()
    if src in out.columns:
        out[dst] = out[src].map(hash_id)
    return out


def _anon_episode_id(series: pd.Series) -> pd.Series:
    """Anonymise an episode_id of the form ``user_id|band|start|end`` by hashing the
    embedded user_id (first '|'-segment) -- otherwise stripping the user_id column
    still leaks the raw id inside episode_id."""
    def _one(eid):
        s = str(eid)
        if "|" not in s:
            return s
        head, _, rest = s.partition("|")
        return f"{hash_id(head)}|{rest}"
    return series.map(_one)


def strip_pii(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with every raw PII column removed (anon_id is kept) and any
    user-id-embedding ``episode_id`` anonymised."""
    out = df.copy()
    if "episode_id" in out.columns:
        out["episode_id"] = _anon_episode_id(out["episode_id"])
    return out.drop(columns=[c for c in PII_COLUMNS if c in out.columns], errors="ignore")


def assert_no_pii(df: pd.DataFrame, context: str = "") -> None:
    bad = [c for c in PII_COLUMNS if c in df.columns]
    if bad:
        raise AssertionError(f"PII columns present in figure-backing data{(' ' + context) if context else ''}: {bad}")


def save_anon_csv(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    """Persist an artifact that may carry per-entity rows: replace raw user_id with
    a deterministic anon_id and drop every other raw identifier."""
    out = add_anon_id(df) if "user_id" in df.columns else df.copy()
    out = strip_pii(out)
    out.to_csv(path, index=index)


def save_anon_parquet(df: pd.DataFrame, path: Path) -> None:
    out = add_anon_id(df) if "user_id" in df.columns else df.copy()
    out = strip_pii(out)
    out.to_parquet(path, index=False)


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def graded_tier_from_gap(max_gap_h: float) -> str:
    """Graded quality tier from the intra-episode max gap alone (full-history
    fallback -- the long-history episode table carries only a binary quality)."""
    if not np.isfinite(max_gap_h):
        return TIER_LOW
    if max_gap_h <= EPISODE_MAX_GAP_H:
        return TIER_HIGH
    if max_gap_h <= MEDIUM_GAP_H:
        return TIER_MEDIUM
    return TIER_LOW


def load_full_episodes() -> pd.DataFrame:
    """Production full-history learning episodes (per user x threshold), with
    timestamps parsed and a graded ``quality_tier`` attached.

    The canonical production quality is the binary ``episode_quality`` (ok /
    large_gap); ``quality_tier`` is an additive graded view for sensitivity.
    ``is_no_response_capable`` follows the production binary (ok only) so the
    baseline analyses reproduce production; the graded tier is available for the
    IC6 sensitivity sweeps.
    """
    ep = pd.read_csv(FULL_EPISODES)
    for c in ("start_ts", "low_ts", "end_ts",
              "response_window_end_ts_24h", "response_window_end_ts_72h",
              "response_window_end_ts_168h"):
        if c in ep.columns:
            ep[c] = pd.to_datetime(ep[c], errors="coerce")
    ep["end_ns"] = ep["end_ts"].astype("datetime64[ns]").astype("int64")
    ep["start_ns"] = ep["start_ts"].astype("datetime64[ns]").astype("int64")
    ep["low_ns"] = ep["low_ts"].astype("datetime64[ns]").astype("int64")
    ep["quality_tier"] = ep["max_gap_h_in_episode"].map(graded_tier_from_gap)
    # production canonical: only 'ok' episodes are no-response-capable
    ep["is_ok"] = ep["episode_quality"].astype(str).eq("ok")
    ep["episode_id"] = (ep["user_id"].astype(str) + "|" + ep["threshold_name"].astype(str)
                        + "|" + ep["start_ns"].astype(str) + "|" + ep["end_ns"].astype(str))
    return ep


def load_action_labels() -> pd.DataFrame:
    return pd.read_csv(ACTION_LABELS)


def load_snapshot() -> pd.DataFrame:
    return pd.read_csv(ONLINE_SNAPSHOT)


def load_timeseries(columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    return pd.read_parquet(TIMESERIES, columns=list(columns) if columns else None)


# --------------------------------------------------------------------------- #
# Per-user FCC step event table (cached)
# --------------------------------------------------------------------------- #
def _extract_steps_one(g: pd.DataFrame, uid: str) -> List[dict]:
    g = g.sort_values("timestamp")
    fcc = g["fullChargeCapacity"].to_numpy(dtype=float)
    cyc = g["cycleCount"].to_numpy(dtype=float)
    ts_ns = g["timestamp"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    is_step, _ = fcc_step_indicator(fcc, 1.0)           # any integer change
    pos = np.flatnonzero(is_step)
    rows = []
    for i in pos:
        delta = float(fcc[i] - fcc[i - 1])
        rows.append({
            "user_id": uid, "ts_ns": int(ts_ns[i]),
            "fcc_value": float(fcc[i]), "cycle": float(cyc[i]),
            "step": delta, "abs_step": abs(delta),
            "is_effective": abs(delta) >= EFFECTIVE_STEP_MWH,
        })
    return rows


def build_fcc_steps_full(force: bool = False) -> pd.DataFrame:
    """Extract every any-change FCC step (>=1 mWh) for every user from the long
    time series and cache it. Carries cycle + effective flag so the dual-track
    and hazard analyses share one event source."""
    ensure_dirs()
    if STEPS_CACHE.exists() and not force:
        return pd.read_parquet(STEPS_CACHE)
    ts = load_timeseries(["user_id", "timestamp", "fullChargeCapacity", "cycleCount"])
    ts = ts.dropna(subset=["fullChargeCapacity"])
    rows: List[dict] = []
    for uid, g in ts.groupby("user_id", sort=False):
        rows.extend(_extract_steps_one(g, uid))
    out = pd.DataFrame(rows)
    out["ts"] = pd.to_datetime(out["ts_ns"])
    out.to_parquet(STEPS_CACHE, index=False)
    return out


def steps_by_user(steps: pd.DataFrame) -> Dict[str, Dict[str, np.ndarray]]:
    """user_id -> {ts_ns, abs_step, step, is_effective} sorted arrays (for fast
    window-membership tests)."""
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for uid, g in steps.sort_values("ts_ns").groupby("user_id", sort=False):
        out[uid] = {
            "ts_ns": g["ts_ns"].to_numpy(dtype=np.int64),
            "abs_step": g["abs_step"].to_numpy(dtype=float),
            "step": g["step"].to_numpy(dtype=float),
            "is_effective": g["is_effective"].to_numpy(dtype=bool),
        }
    return out


# --------------------------------------------------------------------------- #
# Design capacity per user (cached)
# --------------------------------------------------------------------------- #
def build_design_by_user(force: bool = False) -> pd.Series:
    ensure_dirs()
    if DESIGN_CACHE.exists() and not force:
        d = pd.read_csv(DESIGN_CACHE)
        return d.set_index("user_id")["design_mwh"]
    ts = load_timeseries(["user_id", "fullChargeCapacity", "soh_design_pct"])
    ts = ts[(ts["soh_design_pct"] > 0) & ts["fullChargeCapacity"].notna()]
    ts["design"] = ts["fullChargeCapacity"] * 100.0 / ts["soh_design_pct"]
    s = ts.groupby("user_id")["design"].median()
    s.name = "design_mwh"
    s.reset_index().to_csv(DESIGN_CACHE, index=False)
    return s


def ensure_shared_inputs(force: bool = False) -> Tuple[pd.DataFrame, pd.Series]:
    return build_fcc_steps_full(force=force), build_design_by_user(force=force)


# --------------------------------------------------------------------------- #
# END-anchored, censor-aware response convention (window membership of FCC steps)
# --------------------------------------------------------------------------- #
def steps_in_window(arr: Dict[str, np.ndarray], lo_ns: int, hi_ns: int,
                    effective_only: bool = True) -> np.ndarray:
    """Positional indices of this user's FCC steps with lo_ns <= ts <= hi_ns.

    Inclusive of both bounds (a step AT the episode-end sample counts; a step AT
    the deadline counts). ``effective_only`` restricts to >=50 mWh steps."""
    ts = arr["ts_ns"]
    a = int(np.searchsorted(ts, lo_ns, side="left"))
    b = int(np.searchsorted(ts, hi_ns, side="right"))
    idx = np.arange(a, b)
    if effective_only and idx.size:
        idx = idx[arr["is_effective"][idx]]
    return idx


def first_step_after(arr: Dict[str, np.ndarray], anchor_ns: int,
                     effective_only: bool = True,
                     horizon_ns: Optional[int] = None) -> Optional[int]:
    """ts_ns of the first (effective) FCC step at/after ``anchor_ns`` (None if
    none within the optional horizon)."""
    ts = arr["ts_ns"]
    a = int(np.searchsorted(ts, anchor_ns, side="left"))
    n = ts.size
    while a < n:
        if (not effective_only) or arr["is_effective"][a]:
            if horizon_ns is not None and ts[a] > anchor_ns + horizon_ns:
                return None
            return int(ts[a])
        a += 1
    return None


# --------------------------------------------------------------------------- #
# USER-clustered bootstrap (spec 2.10 -- never bootstrap by episode)
# --------------------------------------------------------------------------- #
def _ci(arr: np.ndarray, alpha: float = 0.05) -> Tuple[float, float]:
    lo = float(np.nanpercentile(arr, 100 * alpha / 2))
    hi = float(np.nanpercentile(arr, 100 * (1 - alpha / 2)))
    return lo, hi


def user_bootstrap_ratio(num_by_user: np.ndarray, den_by_user: np.ndarray,
                         B: int, rng_: np.random.Generator,
                         alpha: float = 0.05) -> Dict[str, float]:
    """Percentile CI for sum(num)/sum(den) under resampling of USERS with
    replacement. ``num_by_user``/``den_by_user`` are per-user totals (aligned)."""
    num = np.asarray(num_by_user, dtype=float)
    den = np.asarray(den_by_user, dtype=float)
    n = num.size
    point = float(num.sum() / den.sum()) if den.sum() > 0 else float("nan")
    if n == 0:
        return {"point": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    boot = np.empty(B)
    for b in range(B):
        s = rng_.integers(0, n, n)
        d = den[s].sum()
        boot[b] = num[s].sum() / d if d > 0 else np.nan
    lo, hi = _ci(boot, alpha)
    return {"point": point, "ci_lo": lo, "ci_hi": hi}


def user_bootstrap_mean(values_by_user: List[np.ndarray], B: int,
                        rng_: np.random.Generator, alpha: float = 0.05) -> Dict[str, float]:
    """Percentile CI for the pooled mean of per-episode values, clustered by
    user. ``values_by_user`` is a list of arrays (one per user)."""
    vbu = [np.asarray(v, dtype=float) for v in values_by_user if len(v)]
    n = len(vbu)
    allv = np.concatenate(vbu) if vbu else np.array([])
    point = float(np.nanmean(allv)) if allv.size else float("nan")
    if n == 0:
        return {"point": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    boot = np.empty(B)
    for b in range(B):
        s = rng_.integers(0, n, n)
        pooled = np.concatenate([vbu[i] for i in s])
        boot[b] = np.nanmean(pooled) if pooled.size else np.nan
    lo, hi = _ci(boot, alpha)
    return {"point": point, "ci_lo": lo, "ci_hi": hi}


def user_bootstrap_stat(df: pd.DataFrame, stat_fn: Callable[[pd.DataFrame], float],
                        B: int, rng_: np.random.Generator, user_col: str = "user_id",
                        alpha: float = 0.05) -> Dict[str, float]:
    """Generic clustered bootstrap: resample users, recompute ``stat_fn`` on the
    pooled rows. Slower than the ratio/mean helpers; use only when a statistic is
    not expressible as a ratio or mean."""
    d = df.reset_index(drop=True)
    pos_by_user = {u: np.asarray(idx, dtype=int) for u, idx in d.groupby(user_col).indices.items()}
    users = np.array(list(pos_by_user.keys()))
    n = users.size
    point = float(stat_fn(d))
    if n == 0:
        return {"point": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    boot = np.empty(B)
    for b in range(B):
        s = rng_.integers(0, n, n)
        pos = np.concatenate([pos_by_user[users[i]] for i in s])
        boot[b] = stat_fn(d.iloc[pos])
    lo, hi = _ci(boot, alpha)
    return {"point": point, "ci_lo": lo, "ci_hi": hi}


# --------------------------------------------------------------------------- #
# Empirical randomization p-value
# --------------------------------------------------------------------------- #
def randomization_pvalue(observed: float, null: Sequence[float],
                         alternative: str = "two-sided") -> float:
    """Empirical p-value of ``observed`` against a null/control distribution.

    Uses the (#extreme + 1)/(B + 1) plug-in so p is never exactly 0."""
    a = np.asarray([x for x in null if np.isfinite(x)], dtype=float)
    B = a.size
    if B == 0 or not np.isfinite(observed):
        return float("nan")
    if alternative == "greater":
        c = int((a >= observed).sum())
    elif alternative == "less":
        c = int((a <= observed).sum())
    else:
        med = float(np.median(a))
        c = int((np.abs(a - med) >= abs(observed - med)).sum())
    return (c + 1) / (B + 1)


# --------------------------------------------------------------------------- #
# Lightweight per-user raw episode re-extraction (for D / E) -- production logic
# --------------------------------------------------------------------------- #
def extract_episodes_frame(g: pd.DataFrame, uid: str,
                           cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
                           design_mwh: Optional[float] = None,
                           inference_last_ts: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Production causal episode extraction for one user as a DataFrame.

    Re-uses ``online_episode_detector.extract_episodes_causal`` verbatim so D/E
    re-extraction is faithful to production (END-anchored, censor-aware)."""
    g = prepare_user(g)
    if len(g) < 3:
        return pd.DataFrame()
    rows = extract_episodes_causal(g, uid, cfg, design_mwh=design_mwh,
                                   inference_last_ts=inference_last_ts)
    return pd.DataFrame(rows)


def run_meta(extra: Optional[dict] = None) -> dict:
    meta = {"code_version": CODE_VERSION,
            "effective_step_mwh": EFFECTIVE_STEP_MWH,
            "primary_window_h": PRIMARY_WINDOW_H}
    if extra:
        meta.update(extra)
    return meta
