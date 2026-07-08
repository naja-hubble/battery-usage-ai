"""OD2 online-detector adapter — the band-remap seam for the rolling-30d Phase-3 fork.

Phase 3 (the online sliding-window 9-tier detector) was written against OD1's RSOC
high->low->high *discharge* opportunity (bands ``primary_80_20_80`` / ``strict_90_10_90``).
OD2 redefines the FCC-relearn "learning opportunity" as TWO mechanisms
(``relearn_od2.py``):

  * **Type A** — deep-discharge relearn (full -> RSOC<=6% -> full).
  * **Type B** — charge-side partial relearn (charging through 60-80% -> full).

Rather than re-plumb the whole online stack, this adapter maps the OD2 mechanisms onto the
two band slots the OD1 online layer already understands, so ``online_step_state`` /
``online_policy_v2`` / ``rolling_window_features`` are reused verbatim by import:

  * **Type B  -> ``primary_80_20_80``**  (the FW-core PRIMARY band; healthy p_response 0.45)
  * **Type A  -> ``strict_90_10_90``**   (the strict/nested band; healthy p_response 0.74)

The native OD2 name is preserved in ``od2_threshold_name`` alongside ``opportunity_type``
and ``is_union_primary`` so nothing is lost. This module is strictly ADDITIVE — it imports
the OD1 online primitives and never edits them; every symbol carries the ``od2`` token.

Four seams live here (spec: the four substitutions of the v2 DAG):
  1. :func:`extract_od2_episodes_causal` — wrap ``process_user_od2`` + band-remap.
  2. :func:`attach_gap_quality_od2`      — MANDATORY FORK of ``online_gap_quality.attach_gap_quality``:
     the OD1 order gate ``0 <= s < lo < e < n`` tags EVERY Type B episode (low_idx==start_idx)
     INVALID and silently empties the primary band. Here the gate is type-aware (s<=lo for B),
     the discharge-span geometry is degenerated for B (high_to_low=0; span = arm->full), and the
     scalar scorers are reused verbatim by import.
  3. :func:`synthesize_od2_ep_probs`     — fixed mechanism-specific normative priors (skip GBM).
  4. :func:`stateless_latest_od2`        — fork of ``stateless_latest_v2`` on the trailing 30d window.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import relearn_od2
from . import online_gap_quality as gq
from .online_episode_detector import (
    OnlineConfig, DEFAULT_ONLINE_CONFIG, PRIMARY_THRESHOLD, STRICT_THRESHOLD, prepare_user,
)
from .online_gap_quality import (
    TIER_INVALID, NO_RESPONSE_CAPABLE_TIERS,
)

CODE_VERSION = "online_od2_adapter.0"

# Mechanism-specific normative response priors (168h), read off the offline k-justification
# (data/processed/fcc_relearn_od2/offline/od2_k_justification.csv):
#   p_response_90_10_90_168h = 0.7399  -> Type A / strict band
#   p_response_80_20_80_168h = 0.4542  -> Type B / primary band
P_RESPONSE_NORMATIVE_TYPE_A = 0.74
P_RESPONSE_NORMATIVE_TYPE_B = 0.45

# Band-remap seam.
_TYPE_TO_BAND = {"A": STRICT_THRESHOLD, "B": PRIMARY_THRESHOLD}


# --------------------------------------------------------------------------- #
# (1) Causal episode extraction + band-remap
# --------------------------------------------------------------------------- #
def _remap_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """In-place: stash native OD2 name in ``od2_threshold_name`` and set ``threshold_name``
    to the OD1 band slot the online layer understands (Type B -> primary, Type A -> strict)."""
    for r in rows:
        r["od2_threshold_name"] = r["threshold_name"]
        r["threshold_name"] = _TYPE_TO_BAND[r["opportunity_type"]]
    return rows


def extract_od2_episodes_causal(
    g: pd.DataFrame, uid: str,
    od2_cfg: relearn_od2.Od2Config = relearn_od2.DEFAULT_OD2_CONFIG,
    online_cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
    design_mwh: Optional[float] = None,
) -> List[Dict[str, object]]:
    """All OD2 (Type A + Type B) episodes for one user, band-remapped for the online layer.

    ``g`` should be the ``prepare_user`` (sorted/de-duplicated) frame so the returned
    positional ``start_idx/low_idx/end_idx`` align with ``df_by_user[uid]`` for gap-quality.
    ``add_union_flags`` is applied by the caller at cohort level (after concat) so a coincident
    A/B END is deduplicated once across the whole cohort.
    """
    rows = relearn_od2.process_user_od2(uid, g, od2_cfg, design_mwh=design_mwh)
    return _remap_rows(rows)


def _rows_to_remapped_frame(rows: List[Dict[str, object]]) -> pd.DataFrame:
    """Build an episode frame from remapped rows + cohort/user union flags (Type A wins)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return relearn_od2.add_union_flags(df)


# --------------------------------------------------------------------------- #
# (2) MANDATORY FORK of online_gap_quality.attach_gap_quality
# --------------------------------------------------------------------------- #
def attach_gap_quality_od2(
    episodes: pd.DataFrame, df_by_user: Dict[str, pd.DataFrame],
    cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
) -> pd.DataFrame:
    """Graded gap-quality for OD2 episodes with a TYPE-AWARE order gate.

    Identical to :func:`online_gap_quality.attach_gap_quality` except the invalid-order gate
    allows ``s == lo`` for Type B (where ``low_idx == start_idx`` by construction — the arm is
    the "low" slot). The discharge-span geometry is degenerated for B (``high_to_low_max_gap_h``
    forced to 0; the graded span is arm->full). All scalar scorers and tier constants are reused
    verbatim by import from ``online_gap_quality`` — nothing is copied.

    ASSERTS that no Type B episode is tagged INVALID for *order* reasons (which would silently
    empty the primary band — the exact trap this fork exists to close).
    """
    if episodes.empty:
        for c in ("episode_quality_score", "quality_tier"):
            episodes[c] = pd.Series(dtype="object")
        return episodes

    add_rows: List[Dict[str, object]] = []
    order_invalid_ids: List[object] = []
    for uid, ueps in episodes.groupby("user_id", sort=False):
        g = df_by_user.get(uid)
        if g is None:
            continue
        ts = g["timestamp"]
        ts_ns = ts.to_numpy().astype("datetime64[ns]").astype(np.int64)
        acdc = (g["acdcMode"].to_numpy() == 1).astype(float)
        cs = g["chargeStatus"].to_numpy() if "chargeStatus" in g.columns else None
        n = len(g)
        weights = gq.sample_weights(ts, cfg.sample_weight_cap_h)
        for r in ueps.itertuples(index=False):
            s, lo, e = int(r.start_idx), int(r.low_idx), int(r.end_idx)
            opp = getattr(r, "opportunity_type", "A")
            base = {"episode_id": r.episode_id,
                    "rsoc_depth": float(getattr(r, "episode_depth", float("nan")))}
            quality = getattr(r, "episode_quality", "ok")
            # type-aware order gate: Type B has a degenerate low (lo == s), Type A is strict
            ok_order = (0 <= s <= lo < e < n) if opp == "B" else (0 <= s < lo < e < n)
            if not ok_order:
                if opp == "B":
                    order_invalid_ids.append(r.episode_id)
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
            feats = gq._episode_span_features(ts_ns, acdc, cs, s, lo, e, n, weights)
            if opp == "B":
                # degenerate the discharge-span geometry: there is no high->low discharge leg;
                # the graded span is the charge-side arm->full run (low_to_high already covers it).
                feats["high_to_low_max_gap_h"] = 0.0
            max_gap = float(getattr(r, "max_gap_h_episode", feats.get("endpoint_gap_h", 0.0)))
            comp_gap = gq.max_gap_component(max_gap)
            comp_cov = float(feats["observed_coverage_fraction"])
            comp_end = gq.endpoint_component(feats["endpoint_gap_h"])
            score = gq.W_MAXGAP * comp_gap + gq.W_COVERAGE * comp_cov + gq.W_ENDPOINT * comp_end
            if quality in ("missing_required_value", "invalid_order"):
                tier = TIER_INVALID
            else:
                tier = gq.gap_quality_tier(max_gap, score)
            base.update(feats)
            base["episode_quality_score"] = round(float(score), 4)
            base["quality_tier"] = tier
            add_rows.append(base)

    assert not order_invalid_ids, (
        f"attach_gap_quality_od2: {len(order_invalid_ids)} Type B episode(s) tagged INVALID for "
        f"order reasons — the primary band would be silently emptied. e.g. {order_invalid_ids[:3]}")

    add = pd.DataFrame(add_rows)
    return episodes.merge(add, on="episode_id", how="left")


# --------------------------------------------------------------------------- #
# (3) Synthesized mechanism-specific normative priors (skip GBM training)
# --------------------------------------------------------------------------- #
def synthesize_od2_ep_probs(episodes: pd.DataFrame) -> pd.DataFrame:
    """Fixed normative per-episode response prior per mechanism (no model training).

    ``p_response_normative`` = 0.74 for Type A rows, 0.45 for Type B rows (offline
    od2_k_justification). ``p_response_personalized`` = NaN (there is no personalized head in
    the OD2 online fork). Returns one row per episode: episode_id, p_response_normative,
    p_response_personalized.
    """
    if episodes.empty:
        return pd.DataFrame(columns=["episode_id", "p_response_normative",
                                     "p_response_personalized"])
    opp = episodes["opportunity_type"].to_numpy()
    p_norm = np.where(opp == "A", P_RESPONSE_NORMATIVE_TYPE_A, P_RESPONSE_NORMATIVE_TYPE_B)
    return pd.DataFrame({
        "episode_id": episodes["episode_id"].to_numpy(),
        "p_response_normative": p_norm.astype(float),
        "p_response_personalized": np.full(len(episodes), np.nan),
    })


# --------------------------------------------------------------------------- #
# (4) Stateless (within-30d-window) latest-snapshot no_response count
# --------------------------------------------------------------------------- #
def stateless_latest_od2(
    df_by_user: Dict[str, pd.DataFrame], design_by_user: Dict[str, float],
    snap: pd.DataFrame,
    od2_cfg: relearn_od2.Od2Config = relearn_od2.DEFAULT_OD2_CONFIG,
    online_cfg: OnlineConfig = DEFAULT_ONLINE_CONFIG,
) -> pd.DataFrame:
    """Within-30d-window (stateless) primary-band (Type B) no_response count at each user's
    latest window — the memory-free comparison for the stateful-vs-stateless gain.

    Runs ``process_user_od2`` on ONLY the samples in ``(t-30d, t]`` with ``inference_last_ts=t``
    (so responses in the unobserved tail are censored, never no_response), band-remaps, applies
    :func:`attach_gap_quality_od2`, and counts the PRIMARY (Type B) 168h no_response over the
    no_response-capable tiers — the same graded definition the stateful side uses (apples-to-apples;
    the only difference is memory).
    """
    rows: List[Dict[str, object]] = []
    snap_idx = snap.set_index("user_id")
    rcol = f"response_status_{online_cfg.response_window_hours}h"
    for uid, g in df_by_user.items():
        if uid not in snap_idx.index:
            continue
        t = pd.Timestamp(snap_idx.loc[uid, "window_end_ts"])
        start = t - pd.Timedelta(days=online_cfg.window_days)
        win = g[(g["timestamp"] > start) & (g["timestamp"] <= t)]
        win_sorted = prepare_user(win)
        n_resp = n_nr = 0
        if len(win_sorted) >= 2:
            rws = relearn_od2.process_user_od2(
                uid, win_sorted, od2_cfg, design_mwh=design_by_user.get(uid),
                inference_last_ts=t)
            ef = _rows_to_remapped_frame(_remap_rows(rws))
            if not ef.empty:
                ef = attach_gap_quality_od2(ef, {uid: win_sorted}, online_cfg)
                prim = ef[(ef["threshold_name"] == PRIMARY_THRESHOLD)
                          & (ef["quality_tier"].isin(list(NO_RESPONSE_CAPABLE_TIERS)))]
                if rcol in prim.columns:
                    n_resp = int((prim[rcol] == "responded").sum())
                    n_nr = int((prim[rcol] == "no_response").sum())
        q_ok = snap_idx.loc[uid, "window_data_quality_label"] == "WINDOW_QUALITY_OK"
        rows.append({"user_id": uid, "stateless_n_no_response_30d": n_nr,
                     "stateless_n_responded_30d": n_resp,
                     "stateless_fw_flag": bool(n_nr >= 2 and n_resp == 0 and q_ok)})
    return pd.DataFrame(rows)
