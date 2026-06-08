"""Backtest / evaluation v2 (rolling30 v2 spec section 14).

Produces, against the final-validation PROXY labels (NOT ground truth, spec 3.3):
  * stateful_label_v2 x final_proxy cross-tab,
  * FW Core / FW Core+Watch / engineering top-N precision & recall vs proxy FW,
  * Gauge Core precision & recall vs proxy Gauge,
  * stateful-vs-stateless detection (the 30d-memory gain),
  * dual-basis active false-alert audit (legacy any-change soh_update_status, online any-change
    state, online effective-step state),
  * lead time per proxy label,
  * a sensitivity / Jaccard-stability grid for the core labels and the engineering queue.

Reuses the v1 stateless baseline (`extract_episodes_in_window`) and the apples-to-apples
detection gate; the policy-side sensitivity re-runs only the cheap snapshot gate, never the
full episode/state pipeline (the swept scope is logged, never silently capped — spec).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .online_episode_detector import (
    OnlineConfig, PRIMARY_THRESHOLD, extract_episodes_in_window, prepare_user,
    episodes_to_frame,
)
from . import online_gap_quality as gq
from . import online_policy_v2 as pol

PROXY_FW = "ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE"
PROXY_GAUGE = "ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY"
PROXY_WATCH = "WATCH_LOW_UPDATE_RATE_AMBIGUOUS"
PROXY_NORMAL = "NORMAL_OR_RESPONDING"
PROXY_REVIEW = "REVIEW_INSUFFICIENT_DATA"


# --------------------------------------------------------------------------- #
def final_proxy_crosstab(snap: pd.DataFrame, final: pd.DataFrame) -> pd.DataFrame:
    m = snap.merge(final[["user_id", "final_label"]], on="user_id", how="left")
    ct = pd.crosstab(m["stateful_label_v2"], m["final_label"])
    return ct


def _pr(snap_ids: set, proxy_ids: set, universe: set) -> Dict[str, float]:
    tp = len(snap_ids & proxy_ids)
    fp = len(snap_ids - proxy_ids)
    fn = len(proxy_ids - snap_ids)
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    return {"n_flagged": len(snap_ids), "n_proxy": len(proxy_ids), "tp": tp,
            "precision": round(prec, 4), "recall": round(rec, 4)}


def proxy_precision_recall(
    snap: pd.DataFrame, final: pd.DataFrame, fw_queue: Dict[int, pd.DataFrame],
) -> pd.DataFrame:
    """Precision/recall of each v2 population against the proxy FW / Gauge sets."""
    fl = final.set_index("user_id")["final_label"]
    universe = set(snap["user_id"])
    proxy_fw = set(fl[fl == PROXY_FW].index) & universe
    proxy_gauge = set(fl[fl == PROXY_GAUGE].index) & universe

    def ids(label):
        return set(snap.loc[snap["stateful_label_v2"] == label, "user_id"])

    rows = []
    fw_core = ids(pol.ST_FW_CORE)
    fw_watch = ids(pol.ST_FW_WATCH)
    rows.append({"population": "FW_CORE", "proxy": "FW", **_pr(fw_core, proxy_fw, universe)})
    rows.append({"population": "FW_CORE+FW_WATCH", "proxy": "FW",
                 **_pr(fw_core | fw_watch, proxy_fw, universe)})
    for N, q in sorted(fw_queue.items()):
        rows.append({"population": f"FW_ENGINEERING_TOP{N}", "proxy": "FW",
                     **_pr(set(q["user_id"]), proxy_fw, universe)})
    rows.append({"population": "GAUGE_CORE", "proxy": "GAUGE",
                 **_pr(ids(pol.ST_GAUGE_CORE), proxy_gauge, universe)})
    rows.append({"population": "GAUGE_CORE+SOFT", "proxy": "GAUGE",
                 **_pr(ids(pol.ST_GAUGE_CORE) | ids(pol.ST_GAUGE_SOFT), proxy_gauge, universe)})
    return pd.DataFrame(rows)


def topn_yield_v2(snap: pd.DataFrame, final: pd.DataFrame, score_col: str,
                  proxy_label: str, ns=(10, 20, 30, 50, 100)) -> pd.DataFrame:
    if score_col not in snap.columns:
        return pd.DataFrame()
    m = snap.merge(final[["user_id", "final_label"]], on="user_id", how="left")
    m = m.sort_values(score_col, ascending=False)
    total_pos = int((m["final_label"] == proxy_label).sum())
    rows = []
    for N in ns:
        top = m.head(N)
        hits = int((top["final_label"] == proxy_label).sum())
        rows.append({"score_col": score_col, "proxy_label": proxy_label, "N": N, "hits": hits,
                     "precision_at_N": round(hits / max(N, 1), 4),
                     "recall_at_N": round(hits / max(total_pos, 1), 4),
                     "total_proxy_pos": total_pos})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def proxy_misroute_table(snap: pd.DataFrame, final: pd.DataFrame) -> pd.DataFrame:
    """Proxy FW users falling into Normal/Gauge labels, and proxy Gauge users into FW labels
    (spec 14.1). Each such user is listed explicitly so nothing is silently misclassified."""
    m = snap.merge(final[["user_id", "final_label"]], on="user_id", how="left")
    fw_labels = {pol.ST_FW_CORE, pol.ST_FW_WATCH}
    gauge_labels = {pol.ST_GAUGE_CORE, pol.ST_GAUGE_SOFT, pol.ST_GAUGE_REVIEW}
    normal_labels = {pol.ST_NORMAL}
    rows = []
    for r in m.itertuples(index=False):
        fl = getattr(r, "final_label", None)
        lab = r.stateful_label_v2
        flag = None
        if fl == PROXY_FW and (lab in normal_labels or lab in gauge_labels):
            flag = "proxy_FW_in_normal_or_gauge"
        elif fl == PROXY_GAUGE and lab in fw_labels:
            flag = "proxy_GAUGE_in_fw"
        elif fl == PROXY_GAUGE and lab in normal_labels:
            flag = "proxy_GAUGE_in_normal"
        if flag:
            rows.append({"user_id": r.user_id, "final_label": fl, "stateful_label_v2": lab,
                         "misroute": flag,
                         "evidence_summary": getattr(r, "evidence_summary", "")})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def active_false_alert_audit(snap: pd.DataFrame,
                             soh_status: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Per-label dual/triple-basis active-false-alert audit (spec 14.2)."""
    s = snap.copy()
    if soh_status is not None and "soh_update_status" in soh_status.columns:
        s = s.merge(soh_status[["user_id", "soh_update_status"]], on="user_id", how="left")
    else:
        s["soh_update_status"] = np.nan
    rows = []
    for lab, g in s.groupby("stateful_label_v2"):
        rows.append({
            "label_v2": lab,
            "n_users": int(len(g)),
            "active_false_alert_legacy_any_change": int((g["soh_update_status"] == "active").sum()),
            "active_false_alert_online_any_state":
                int(g.get("legacy_any_active_flag", pd.Series(False, index=g.index)).fillna(False).sum()),
            "active_false_alert_online_effective_state":
                int(g.get("effective_active_flag", pd.Series(False, index=g.index)).fillna(False).sum()),
            "n_micro_wobble_only":
                int(g.get("micro_wobble_only_since_effective_change",
                          pd.Series(False, index=g.index)).fillna(False).sum()),
        })
    return pd.DataFrame(rows).sort_values("label_v2").reset_index(drop=True)


def gauge_core_active_exceptions(snap: pd.DataFrame,
                                 soh_status: Optional[pd.DataFrame]) -> pd.DataFrame:
    """List every Gauge Core user that legacy any-change flags 'active' (spec 16.3 acceptance)."""
    g = snap[snap["stateful_label_v2"] == pol.ST_GAUGE_CORE].copy()
    if g.empty or soh_status is None or "soh_update_status" not in soh_status.columns:
        return pd.DataFrame()
    g = g.merge(soh_status[["user_id", "soh_update_status"]], on="user_id", how="left")
    ex = g[g["soh_update_status"] == "active"]
    cols = ["user_id", "soh_update_status", "days_since_any_fcc_change",
            "days_since_effective_fcc_change", "micro_wobble_only_since_effective_change",
            "cluster_profile_name", "evidence_summary"]
    return ex[[c for c in cols if c in ex.columns]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
def stateless_latest_v2(df_by_user, design_by_user, snap, cfg: OnlineConfig) -> pd.DataFrame:
    """Within-30d-window (stateless) no_response count at each user's latest window.

    Uses the SAME graded-tier definition as the stateful side (HIGH_OK + MEDIUM_GAP primary
    no_response) so the stateful-vs-stateless comparison is apples-to-apples; the only
    difference is memory (last 30d raw window vs cumulative since last effective change)."""
    rows = []
    snap_idx = snap.set_index("user_id")
    for uid, g in df_by_user.items():
        if uid not in snap_idx.index:
            continue
        t = pd.Timestamp(snap_idx.loc[uid, "window_end_ts"])
        start = t - pd.Timedelta(days=cfg.window_days)
        win = g[(g["timestamp"] > start) & (g["timestamp"] <= t)]
        win_sorted = prepare_user(win)
        eps = extract_episodes_in_window(win, uid, t, cfg, design_mwh=design_by_user.get(uid),
                                         last_observed_ts=t)
        n_resp = n_nr = 0
        if eps:
            ef = episodes_to_frame(eps)
            ef = gq.attach_gap_quality(ef, {uid: win_sorted}, cfg)
            prim = ef[(ef["threshold_name"] == PRIMARY_THRESHOLD)
                      & (ef["quality_tier"].isin(list(gq.NO_RESPONSE_CAPABLE_TIERS)))]
            n_resp = int((prim["response_status_72h"] == "responded").sum())
            n_nr = int((prim["response_status_72h"] == "no_response").sum())
        q_ok = snap_idx.loc[uid, "window_data_quality_label"] == "WINDOW_QUALITY_OK"
        rows.append({"user_id": uid, "stateless_n_no_response_30d": n_nr,
                     "stateless_n_responded_30d": n_resp,
                     "stateless_fw_flag": bool(n_nr >= 2 and n_resp == 0 and q_ok)})
    return pd.DataFrame(rows)


def stateful_vs_stateless(snap: pd.DataFrame, stateless: pd.DataFrame) -> Dict[str, object]:
    det = ((snap.get("cum_primary_no_response_since_last_effective_change", 0) >= 2)
           & (snap.get("observed_effective_responses_since_last_effective_change", 0) == 0)
           & (snap["window_data_quality_label"] == "WINDOW_QUALITY_OK"))
    st_det = set(snap.loc[det, "user_id"])
    sl_det = set(stateless.loc[stateless["stateless_fw_flag"], "user_id"]) \
        if not stateless.empty else set()
    return {
        "stateful_detection_n": len(st_det),
        "stateless_detection_n": len(sl_det),
        "overlap_detection_n": len(st_det & sl_det),
        "stateful_only_detection_n": len(st_det - sl_det),
        "stateless_only_detection_n": len(sl_det - st_det),
        "fw_core_n": int((snap["stateful_label_v2"] == pol.ST_FW_CORE).sum()),
        "fw_watch_n": int((snap["stateful_label_v2"] == pol.ST_FW_WATCH).sum()),
        "gauge_core_n": int((snap["stateful_label_v2"] == pol.ST_GAUGE_CORE).sum()),
        "gauge_soft_n": int((snap["stateful_label_v2"] == pol.ST_GAUGE_SOFT).sum()),
    }


# --------------------------------------------------------------------------- #
def lead_time_v2(daily: pd.DataFrame, df_by_user, final: Optional[pd.DataFrame]) -> pd.DataFrame:
    """First-alert vs last-observation lead time + alert persistence per user (spec 14.4)."""
    if "alert_fired" not in daily.columns:
        return pd.DataFrame()
    first_alert = (daily[daily["alert_fired"]].groupby("user_id")["window_end_date"].min()
                   .rename("first_alert_date").reset_index())
    n_alerts = (daily[daily["alert_fired"]].groupby("user_id")["window_end_date"].count()
                .rename("n_alert_transitions").reset_index())
    persist = (daily.groupby("user_id")["consecutive_windows_opportunity_no_response"].max()
               .rename("max_consecutive_no_response_windows").reset_index()) \
        if "consecutive_windows_opportunity_no_response" in daily.columns else None
    last_obs = pd.DataFrame({"user_id": list(df_by_user.keys()),
                             "last_obs_date": [pd.Timestamp(g["timestamp"].iloc[-1]).normalize()
                                               for g in df_by_user.values()]})
    lt = first_alert.merge(last_obs, on="user_id", how="left").merge(
        n_alerts, on="user_id", how="left")
    if persist is not None:
        lt = lt.merge(persist, on="user_id", how="left")
    lt["lead_time_days"] = (lt["last_obs_date"] - lt["first_alert_date"]).dt.days
    if final is not None and "final_label" in final.columns:
        lt = lt.merge(final[["user_id", "final_label"]], on="user_id", how="left")
    return lt


# --------------------------------------------------------------------------- #
# Sensitivity / Jaccard stability
# --------------------------------------------------------------------------- #
def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return round(len(a & b) / max(len(a | b), 1), 4)


def policy_sensitivity_grid(snap: pd.DataFrame) -> pd.DataFrame:
    """Re-run only the cheap snapshot gate over a policy-threshold grid; report core-label
    counts and Jaccard vs the default config (spec 14.5). Episode/state pipeline is NOT
    re-run here — that scope (effective_step x response_window x gap) is covered by
    episode-level sensitivity in the CLI."""
    base = pol.DEFAULT_POLICY_V2
    default_snap = pol.assign_labels_v2(snap, base)
    fw_default = set(default_snap.loc[default_snap["stateful_label_v2"] == pol.ST_FW_CORE, "user_id"])
    gc_default = set(default_snap.loc[default_snap["stateful_label_v2"] == pol.ST_GAUGE_CORE, "user_id"])
    rows = []
    for days in (60.0, 90.0, 120.0, 180.0):
        for cyc in (20.0, 30.0, 50.0):
            for anom in (1.3, 2.0, 3.0):
                cfg = pol.PolicyConfigV2(fw_core_days=days, fw_core_cycles=cyc,
                                         fw_core_anomaly=anom)
                lab = pol.assign_labels_v2(snap, cfg)
                fw = set(lab.loc[lab["stateful_label_v2"] == pol.ST_FW_CORE, "user_id"])
                gc = set(lab.loc[lab["stateful_label_v2"] == pol.ST_GAUGE_CORE, "user_id"])
                rows.append({
                    "fw_core_days": days, "fw_core_cycles": cyc, "fw_core_anomaly": anom,
                    "n_fw_core": len(fw), "n_gauge_core": len(gc),
                    "jaccard_fw_core_vs_default": _jaccard(fw, fw_default),
                    "jaccard_gauge_core_vs_default": _jaccard(gc, gc_default),
                })
    return pd.DataFrame(rows)


def episode_sensitivity_grid(episodes: pd.DataFrame) -> pd.DataFrame:
    """Episode-level response-evidence sensitivity over response_window x gap_rule, read off
    the already-computed multi-window response columns and per-episode max gap (spec 14.5)."""
    prim = episodes[episodes["threshold_name"] == PRIMARY_THRESHOLD].copy()
    rows = []
    for w in (24, 72, 168):
        col = f"response_status_{w}h"
        if col not in prim.columns:
            continue
        for gap_rule, gmax in (("6h", 6.0), ("12h", 12.0), ("24h", 24.0), ("graded", np.inf)):
            if gap_rule == "graded":
                ok = prim[prim["quality_tier"].isin(["HIGH_OK", "MEDIUM_GAP"])] \
                    if "quality_tier" in prim.columns else prim[prim["episode_quality"] == "ok"]
            else:
                ok = prim[prim["max_gap_h_episode"] <= gmax]
            st = ok[col]
            n_resp = int((st == "responded").sum())
            n_nr = int((st == "no_response").sum())
            n_cens = int((st == "censored").sum())
            rows.append({"response_window_h": w, "gap_rule": gap_rule,
                         "n_opportunities": int(len(ok)), "n_responded": n_resp,
                         "n_no_response": n_nr, "n_censored": n_cens,
                         "response_rate_complete": round(n_resp / max(n_resp + n_nr, 1), 4)})
    return pd.DataFrame(rows)
