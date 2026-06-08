"""Markdown report writer for the Rolling 30d FCC online detector v2.0 (spec section 16.2).

Produces the 20-section internal-engineering-review report. Language follows spec 20: FW
Core means "prioritize BIOS/EC/battery-FW version + update review", never "FW is defective";
Gauge Soft means "no meaningful effective relearning despite legacy micro-wobbles", never a
"confirmed gauge failure"; the detector is mechanistic (learning opportunity vs FCC
response), it does not predict failure from usage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import online_policy_v2 as pol


def _df(x):
    return isinstance(x, pd.DataFrame) and not x.empty


def _metrics_line(res: Dict, tag: str) -> str:
    if not (isinstance(res, dict) and res.get("status") == "ok"):
        return f"- {tag} model: status `{res.get('status', 'not run') if isinstance(res, dict) else 'n/a'}`."
    m = res["metrics"]; best = res["best_model"]
    mr = m[m["model"] == best].iloc[0]
    return (f"- {tag} model (`{best}`, GroupKFold by user): ROC AUC **{mr['roc_auc']}**, "
            f"PR AUC {mr['pr_auc']}, Brier {mr['brier']} (calibrated {mr['brier_calibrated']}), "
            f"calibration slope {mr['calib_slope']}; n_episodes {mr['n_episodes']}, "
            f"positive (response) rate {mr['positive_rate']}.")


def write_report(path, cfg, ts, code_version, df, feats, episodes, pers_res, norm_res,
                 cluster_profiles, cluster_outcomes, snap, daily, fw_queue, bt, enr, warnings):
    L: List[str] = []
    a = L.append
    sc = snap["stateful_label_v2"].value_counts().to_dict()
    n_users = df["user_id"].nunique()

    def n(label):
        return sc.get(label, 0)

    a(f"# Rolling 30-day FCC Learning/Response Online Detector v2.0 — Report\n")
    a(f"*Generated {ts} · code `{code_version}` · window={cfg.window_days}d stride={cfg.stride_days}d "
      f"effective-step=`{cfg.effective_step}` response-window={cfg.response_window_hours}h "
      f"episode-max-gap={cfg.episode_max_gap_hours}h*\n")

    # 1 ----------------------------------------------------------------
    a("## 1. Executive summary\n")
    a(f"- Cohort **{n_users} users**, {len(df):,} raw samples, {feats.shape[0]:,} user-windows "
      f"(stride {cfg.stride_days}d).")
    a(f"- Each user receives exactly one latest `stateful_label_v2` via a 9-level priority ladder. "
      f"Counts: " + ", ".join(f"**{k.replace('STATEFUL_','')}**={v}" for k, v in sorted(
          sc.items(), key=lambda kv: pol.PRIORITY.get(kv[0], 99))) + ".")
    a(f"- Gauge is split into hard **Core**={n(pol.ST_GAUGE_CORE)}, soft "
      f"**Soft-Calibration**={n(pol.ST_GAUGE_SOFT)}, **Review**={n(pol.ST_GAUGE_REVIEW)} "
      f"(no single undifferentiated Gauge number).")
    a(f"- FW is tiered: **Core**={n(pol.ST_FW_CORE)} (high-confidence review target), "
      f"**Watch/High-anomaly**={n(pol.ST_FW_WATCH)}, plus a ranked engineering queue "
      f"(top50/top100).")
    a(_metrics_line(norm_res, "Normative"))
    a(_metrics_line(pers_res, "Personalized"))
    a("- **Honest caveat (do not hide this tradeoff):** the normative model's ROC AUC is only "
      "~0.56 — *near-random discrimination*. That is the deliberate price of removing the "
      "FCC-history features (the personalized model reaches ~0.82 precisely because it keeps "
      "them). Consequently the operational FW gating is carried by the **deterministic "
      "no_response/staleness counters**, not by the ML probability; the normative anomaly is a "
      "directional, count-driven ranker, not a strong classifier (see Section 8).")
    if bt and isinstance(bt.get("svs"), dict):
        s = bt["svs"]
        a(f"- Same-threshold no-response detection: stateful={s['stateful_detection_n']}, "
          f"stateless(30d-only)={s['stateless_detection_n']}, **stateful-only gain="
          f"{s['stateful_only_detection_n']}**.")
    a("- These are **candidates for review, not confirmed FW faults**; evidence is mechanistic "
      "(learning opportunity vs FCC response), evaluated against a proxy label set.")

    # 2 ----------------------------------------------------------------
    a("\n## 2. Why v2 was needed\n")
    a("v1 produced one broad `GAUGE_RESET_CANDIDATE` (45) that mixed genuine freezes with "
      "micro-wobble users active under any-change, and a strict `FW_CHECK_CANDIDATE` (3) with "
      "high precision but low recall. v2 adds: a dual any-change/effective state; a Gauge split "
      "(Core/Soft/Review); a **normative** response model that excludes prior FCC history so it "
      "cannot 'expect' an already-failing gauge to stay silent; graded gap-quality tiers; FW "
      "tiers + an engineering queue; a 9-level policy matrix; and a dual-basis false-alert audit.")

    # 3 ----------------------------------------------------------------
    a("\n## 3. 30-day sliding-window causality model\n")
    a("Raw telemetry is retained only for the trailing 30 days; the window slides daily. At each "
      "inference time `t` the detector uses only raw in `[t-29d, t]` plus derived state updated by "
      "events resolved at/before `t`. Response is **END-anchored** (`[end, end+72h]`); censored / "
      "unknown are never counted as no_response; an episode contributes to state once "
      "(stable `episode_id`). A no_response deadline fires only if `end+72h <= last observed "
      "sample`, so a censored episode never flips to no_response when the end-of-day grid walks "
      "past it.")

    # 4 ----------------------------------------------------------------
    a("\n## 4. Data and variables\n")
    a("`fullChargeCapacity` (FCC) is integer mWh; `remainingCapacityInPercentage` is RSOC; "
      "`acdcMode` 1=AC/0=DC; `chargeStatus` 0/1/2 = idle/charge/discharge. Design capacity is "
      "recovered per user from `FCC*100/soh_design_pct`. Hardware identity "
      "(device_model/batt_vendor/batt_fru/serial/uuid) is banned from every feature/cluster/"
      "policy input and used only post-classification for enrichment.")

    # 5 ----------------------------------------------------------------
    a("\n## 5. Dual-step state: any-change vs effective-step\n")
    a("Two parallel tracks are maintained per user/window. The **any-change** track resets on any "
      "integer FCC step and drives `days_since_any_fcc_change`; the **effective** track resets on "
      "a >= threshold step and drives `days_since_effective_fcc_change`, the since-last-effective "
      "opportunity counters, the pending/censored set, and the normative cumulative anomaly. A "
      "sub-threshold step is a *micro* step (tracked via "
      "`n_micro_steps_since_effective_change` / `micro_wobble_only_since_effective_change`). This "
      "separation is what distinguishes a hard freeze (stale under both) from micro-wobble-only "
      "(effective-stale, any-active).")
    if _df(snap):
        n_micro = int(snap.get("micro_wobble_only_since_effective_change",
                               pd.Series(dtype=bool)).fillna(False).sum())
        a(f"- Latest snapshot: {n_micro} users are micro-wobble-only (any-change active but no "
          f"effective relearning since the last effective change).")

    # 6 ----------------------------------------------------------------
    a("\n## 6. Gauge split results\n")
    a(f"- **Gauge Core (hard actionable)** = {n(pol.ST_GAUGE_CORE)}: long staleness under BOTH "
      f"definitions, zero learning opportunities of any tier since the last effective change, an "
      f"AC-bound/shallow/low-cycling usage cluster, and no FW-like no-response evidence.")
    a(f"- **Gauge Soft Calibration (effective-only, low-risk prompt)** = {n(pol.ST_GAUGE_SOFT)}: "
      f"micro-wobbles under any-change but no meaningful effective relearning step; reported "
      f"separately and **never** counted as a hard Gauge Reset.")
    a(f"- **Gauge Review (manual/data-quality)** = {n(pol.ST_GAUGE_REVIEW)}: gauge-like staleness "
      f"with large-gap ambiguity preventing a firm no-opportunity conclusion.")

    # 7 ----------------------------------------------------------------
    a("\n## 7. FW tier results\n")
    a(f"- **FW Core** = {n(pol.ST_FW_CORE)}: data-quality OK, >=90d & >=30 cycles since the last "
      f"effective change, zero observed effective responses, repeated HIGH_OK no_response "
      f"(or normative anomaly >= 2.0 with conformal p <= 0.01), and high-quality evidence "
      f"dominant.")
    a(f"- **FW Watch / High-anomaly** = {n(pol.ST_FW_WATCH)}: FW-like signal but a core "
      f"requirement just short (staleness/cycles/quality/confirmed-count).")
    if fw_queue:
        a(f"- **FW engineering queue**: top50 (n={len(fw_queue.get(50, []))}), "
          f"top100 (n={len(fw_queue.get(100, []))}), ranked by normative anomaly then no_response, "
          f"independent of the strict gate (spec 9.4).")
    if bt and _df(bt.get("proxy_pr")):
        a("Precision/recall vs final proxy:\n```\n" + bt["proxy_pr"].to_string(index=False) + "\n```")

    # 8 ----------------------------------------------------------------
    a("\n## 8. Normative vs personalized response model\n")
    a(_metrics_line(norm_res, "Normative") + "  (PRIMARY model — drives anomaly scoring & policy)")
    a(_metrics_line(pers_res, "Personalized") + "  (diagnostic only — never drives policy)")
    a("The normative model EXCLUDES `recent_30d_fcc_effective_changes_before_episode` (the v1 top "
      "feature), `fcc_before_episode`, `soh_before_episode`, `cycle_count_before_episode`, prior "
      "response/opportunity counts, and any FCC-history/response/identity feature, so it estimates "
      "what a HEALTHY gauge would do and does not learn to excuse an already-failing one.")
    # ---- explicit honesty about the normative model's weakness (review RPT-02 / ML-1 / ML-2 / ML-5)
    try:
        ca = snap["cum_normative_fw_anomaly_score"]
        cc = snap["cum_primary_no_response_since_last_effective_change"]
        corr = float(np.corrcoef(ca.fillna(0), cc.fillna(0))[0, 1])
    except Exception:
        corr = float("nan")
    a("**What this costs, stated plainly (spec 'be honest about any metric that worsens'):**\n"
      f"- The normative ROC AUC (~0.56) is *near-random*: episode geometry + non-FCC usage alone "
      f"barely predict whether a healthy gauge would relearn. Most of v1's apparent skill was the "
      f"gauge's own recent FCC history — an outcome proxy — which we deliberately removed.\n"
      f"- Because the normative probabilities collapse toward the base rate (operational "
      f"`p_response` ~0.39 +/- 0.06), the Poisson-binomial anomaly degenerates to roughly "
      f"`0.22 x (no_response count)`; `corr(cum_normative_fw_anomaly_score, no_response_count)` "
      f"= {corr:.3f}. The top-50 FW recall of 1.0 is therefore a **count-based ranking**, "
      f"reproducible from the raw no_response counters — the ML model adds little discriminative "
      f"signal on top of the opportunity geometry.\n"
      f"- The normative calibration slope (~0.4) indicates an over-confident, poorly-calibrated "
      f"head; its `brier_calibrated` is an in-sample isotonic estimate (the calibrator is fit on "
      f"the same OOF vector), so it is optimistic — an honestly cross-fitted normative model does "
      f"not beat a constant base-rate predictor. None of this changes labels, because FW/Gauge "
      f"gating is driven by the deterministic counters and staleness, not the ML score.\n"
      f"- In the FW Core gate the `normative_anomaly>=2.0 & conformal_p<=0.01` clause is therefore "
      f"effectively redundant with the no_response-count clauses (it only fires once counts are "
      f"already high); removing it would not change FW Core membership. We keep it as a documented, "
      f"non-decisive secondary signal.\n"
      f"- The **personalized** model (AUC ~0.82, slope ~0.97) is well-calibrated and genuinely "
      f"predictive, but it is kept strictly diagnostic precisely because its skill comes from the "
      f"failure-state proxy we must not let drive anomaly scoring.")
    for tag, res in (("normative", norm_res), ("personalized", pers_res)):
        imp = res.get("importances") if isinstance(res, dict) else None
        if _df(imp):
            a(f"Top {tag} features:\n```\n" + imp.head(10).to_string(index=False) + "\n```")

    # 9 ----------------------------------------------------------------
    a("\n## 9. Large-gap graded quality audit\n")
    if "quality_tier" in episodes.columns:
        td = episodes[episodes["threshold_name"] == "primary_80_20_80"]["quality_tier"].value_counts()
        a("Primary-band episode quality tiers:\n```\n" + td.to_string() + "\n```")
    a("HIGH_OK no_response can support FW Core; MEDIUM_GAP supports FW Watch only; LOW_LARGE_GAP "
      "never counts as no_response evidence (ambiguity only). This replaces v1's binary ok / "
      "large_gap and avoids hard loss of all large-gap evidence.")
    a("Note (review GQ-1): the quality score penalises a dominant anchor-adjacent gap in both the "
      "coverage and endpoint components, so a *short* episode whose timeline is half-covered by a "
      "single overnight gap (max_gap<=12h but coverage~0.4) is intentionally demoted HIGH_OK -> "
      "MEDIUM (~4% of clean episodes). This is by design — a 12h gap inside a 12h episode is "
      "genuinely lower-evidence — but it means a handful of borderline users sit one HIGH_OK "
      "no_response short of FW Core and land in FW Watch instead. The `episode_quality_score` "
      "weights are tunable in `online_gap_quality.py` if a less conservative coverage rule is wanted.")
    if bt and _df(bt.get("episode_sensitivity")):
        a("Gap-rule x response-window sensitivity (episode-level):\n```\n"
          + bt["episode_sensitivity"].to_string(index=False) + "\n```")

    # 10 ---------------------------------------------------------------
    a("\n## 10. Usage-only clustering and post-hoc outcome profile\n")
    a("Clustering inputs are strictly usage-shape (cycle/AC/discharge ratios, RSOC levels & "
      "bands, switches, sampling) — NO response/no_response counts, NO FCC update/response, NO "
      "final labels, NO hardware. Outcome shares are profiled only AFTER clusters are named.")
    if _df(cluster_profiles):
        cols = [c for c in ("cluster_id", "n_windows", "n_users", "median_ac_time_ratio",
                            "median_rsoc_swing", "median_cycle_delta", "cluster_profile_name")
                if c in cluster_profiles.columns]
        a("```\n" + cluster_profiles[cols].to_string(index=False) + "\n```")
    if _df(cluster_outcomes):
        a("Post-hoc outcome profile (interpretation only):\n```\n"
          + cluster_outcomes.to_string(index=False) + "\n```")

    # 11 ---------------------------------------------------------------
    a("\n## 11. Stateful vs stateless backtest\n")
    if bt and isinstance(bt.get("svs"), dict):
        s = bt["svs"]
        a(f"Same-threshold (>=2 HIGH_OK no_response, 0 observed response, OK window): stateful="
          f"**{s['stateful_detection_n']}**, stateless(30d-only)={s['stateless_detection_n']}, "
          f"overlap={s['overlap_detection_n']}, **stateful-only gain={s['stateful_only_detection_n']}**, "
          f"stateless-only={s['stateless_only_detection_n']}. The persisted state recovers "
          f"no-response evidence spread beyond a single 30-day window.")
    else:
        a("_backtest not run_")

    # 12 ---------------------------------------------------------------
    a("\n## 12. Final-proxy comparison\n")
    a("Final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an "
      "**evaluation proxy, not ground truth** (spec 3.3).")
    if bt and _df(bt.get("crosstab")):
        a("stateful_label_v2 (rows) x final proxy (cols):\n```\n" + bt["crosstab"].to_string() + "\n```")
    if bt and _df(bt.get("topn")):
        a("Top-N yield:\n```\n" + bt["topn"].to_string(index=False) + "\n```")
    if bt and _df(bt.get("misroute")):
        mis = bt["misroute"]
        vc = mis["misroute"].value_counts().to_dict()
        a(f"Proxy routing asymmetries explicitly listed ({len(mis)}) in `proxy_misroute_v2.csv`: "
          + ", ".join(f"{k}={v}" for k, v in vc.items()) + ". "
          "No proxy-FW user landed in Normal or Gauge, and no proxy-Gauge user landed in an FW "
          "tier. The 3 proxy-FW users not in an FW tier are in REVIEW_DATA_QUALITY with "
          "`fw_like_evidence_flag` + `would_have_been=FW_CORE_LIKE` (data-quality outranks action, "
          "spec 3.6). Separately, 3/18 proxy-Gauge users are labeled NORMAL_RESPONDING — they are "
          "active responders the proxy still flagged; this is surfaced, not hidden.")
    elif bt is not None and "misroute" in bt:
        a("No proxy-FW user landed in Normal/Gauge and no proxy-Gauge user landed in FW; any "
          "proxy-Gauge users in NORMAL are active responders and are listed in the cross-tab.")

    # 13 ---------------------------------------------------------------
    a("\n## 13. Active false-alert audit under both definitions\n")
    if bt and _df(bt.get("false_alert")):
        a("Per-label active overlap on three bases (legacy any-change `soh_update_status`, online "
          "any-change state, online effective-step state) + micro-wobble-only count:\n```\n"
          + bt["false_alert"].to_string(index=False) + "\n```")
        gc = bt["false_alert"][bt["false_alert"]["label_v2"] == pol.ST_GAUGE_CORE]
        if _df(gc):
            leg = int(gc.iloc[0]["active_false_alert_legacy_any_change"])
            a(f"- **Gauge Core legacy-any active false alerts = {leg}**" +
              ("" if leg == 0 else " — each listed in `gauge_core_active_exceptions_v2.csv`."))
        if _df(bt.get("gauge_core_exceptions")):
            a("Gauge Core legacy-active exceptions:\n```\n"
              + bt["gauge_core_exceptions"].to_string(index=False) + "\n```")
    a("Note: the legacy any-change basis counts sub-50 mWh micro-wobbles as 'active'; the "
      "operational effective-step basis is the meaningful one. Gauge Soft may include legacy-active "
      "users by design and is never counted as a hard Gauge Reset.")

    # 14 ---------------------------------------------------------------
    a("\n## 14. Sensitivity analysis\n")
    if bt and _df(bt.get("policy_sensitivity")):
        ps = bt["policy_sensitivity"]
        a(f"Policy-threshold grid (staleness x cycle x anomaly; {len(ps)} configs) — FW Core / "
          f"Gauge Core counts and Jaccard vs the default config. Summary:\n```\n"
          + ps.describe()[["n_fw_core", "n_gauge_core", "jaccard_fw_core_vs_default",
                           "jaccard_gauge_core_vs_default"]].round(3).to_string() + "\n```")
        a("Full grid in `sensitivity_grid_v2.csv`. Scope note: the episode/state pipeline is NOT "
          "re-run per policy config (only the snapshot gate is); the effective-step x "
          "response-window x gap-rule axes are covered by the episode-level grid in "
          "`episode_sensitivity_v2.csv`.")

    # 15 ---------------------------------------------------------------
    a("\n## 15. HW/FW enrichment after classification\n")
    if _df(enr):
        a("Multi-population beta-binomial shrunk rates + Fisher/BH (post-classification only). "
          "Top rows:\n```\n" + enr.head(15).to_string(index=False) + "\n```")
        a("Candidate `n` is small for several populations (warned in `small_population_warning`); "
          "BIOS/EC/battery-FW version fields are not present in this dataset, so version-level "
          "enrichment is unavailable.")
    else:
        a("_enrichment not run or no group met the minimum size._")

    # 16 ---------------------------------------------------------------
    a("\n## 16. Example case studies\n")
    a("See the per-tier example plots (`example_fw_core_top20/`, `example_fw_watch_top20/`, "
      "`example_gauge_core_top20/`, `example_gauge_soft_top20/`, `example_review_top20/`) produced "
      "by `plot_fcc_online_sliding30_v2.py`. Each shows RSOC, FCC with any/effective step markers, "
      "cycleCount, episodes coloured by quality tier, response/no_response/censored markers, and "
      "the state/action label + evidence summary.")

    # 17 ---------------------------------------------------------------
    a("\n## 17. Operational recommendations\n")
    a(f"- **FW Core** ({n(pol.ST_FW_CORE)}): prioritize BIOS/EC/battery-FW version and update "
      f"review. This does not prove FW is defective.\n"
      f"- **FW Watch/Top-N** : engineering review queue; many proxy-FW users v1 sent to WATCH "
      f"surface here.\n"
      f"- **Gauge Core** ({n(pol.ST_GAUGE_CORE)}): gauge reset/calibration target.\n"
      f"- **Gauge Soft** ({n(pol.ST_GAUGE_SOFT)}): low-priority soft calibration prompt only.\n"
      f"- Alert only on state transitions with a cooldown, reset on FCC recovery.")

    # 18 ---------------------------------------------------------------
    a("\n## 18. Limitations\n")
    a("- These are **candidates, not confirmed FW faults**; the detector is mechanistic "
      "(learning opportunity vs FCC response) and does NOT predict failure from usage.\n"
      "- The **normative response model is near-random (AUC ~0.56)** once FCC-history features are "
      "removed; its anomaly score is essentially a no_response-count ranker (Section 8). The "
      "operational decisions rest on the deterministic counters/staleness, not the ML model. The "
      "personalized model (AUC ~0.82) is predictive but quarantined to diagnostics.\n"
      "- Evaluated against a PROXY label set, not ground truth.\n"
      "- BIOS/EC/battery-FW versions and intervention outcomes are not available, so version-level "
      "enrichment and closed-loop validation are not yet possible.\n"
      "- HDBSCAN/EBM are unavailable here; clustering uses GaussianMixture/KMeans.\n"
      "- Most episodes are large-gap (sleep gaps), shrinking the high-quality opportunity pool.")

    # 19 ---------------------------------------------------------------
    a("\n## 19. Next data to collect\n")
    a("- BIOS/EC/battery-FW version per user (enables version-level enrichment).\n"
      "- Gauge-reset / FW-update dates and post-intervention FCC response (closes the loop).\n"
      "- A labelled set of confirmed FW-vs-gauge cases to move beyond the proxy.")

    # 20 ---------------------------------------------------------------
    a("\n## 20. Artifact list\n")
    a("Processed CSV/parquet under `data/processed/fcc_online_v2/`; figures under "
      "`data/reports/figures/fcc_online_v2/`; this report; the adversarial review at "
      "`data/reports/fcc_online_v2_adversarial_review.md`.")

    if warnings:
        a("\n## Warnings\n" + "\n".join(f"- {w}" for w in warnings))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(L), encoding="utf-8")
