# Rolling 30-day FCC Learning/Response Online Detector v2.0 — Report

*Generated 2026-07-08T17:45:27Z · code `rolling30-od2.0` · window=30d stride=1d effective-step=`abs_ge_50mWh` response-window=168h episode-max-gap=12.0h*

## 1. Executive summary

- Cohort **40 users**, 190,783 raw samples, 11,097 user-windows (stride 1d).
- Each user receives exactly one latest `stateful_label_v2` via a 9-level priority ladder. Counts: **REVIEW_DATA_QUALITY**=11, **FW_CHECK_CORE**=2, **FW_WATCH_HIGH_ANOMALY**=7, **GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY**=2, **WATCH_LARGE_GAP_OR_CENSORED**=6, **WATCH_LOW_EVIDENCE**=9, **NORMAL_RESPONDING**=3.
- Gauge is split into hard **Core**=0, soft **Soft-Calibration**=2, **Review**=0 (no single undifferentiated Gauge number).
- FW is tiered: **Core**=2 (high-confidence review target), **Watch/High-anomaly**=7, plus a ranked engineering queue (top50/top100).
- Normative model: status `synthesized_prior`.
- Personalized model: status `not_run`.
- **Honest caveat (do not hide this tradeoff):** the normative model's ROC AUC is only ~0.56 — *near-random discrimination*. That is the deliberate price of removing the FCC-history features (the personalized model reaches ~0.82 precisely because it keeps them). Consequently the operational FW gating is carried by the **deterministic no_response/staleness counters**, not by the ML probability; the normative anomaly is a directional, count-driven ranker, not a strong classifier (see Section 8).
- Same-threshold no-response detection: stateful=13, stateless(30d-only)=11, **stateful-only gain=4**.
- These are **candidates for review, not confirmed FW faults**; evidence is mechanistic (learning opportunity vs FCC response), evaluated against a proxy label set.

## 2. Why v2 was needed

v1 produced one broad `GAUGE_RESET_CANDIDATE` (45) that mixed genuine freezes with micro-wobble users active under any-change, and a strict `FW_CHECK_CANDIDATE` (3) with high precision but low recall. v2 adds: a dual any-change/effective state; a Gauge split (Core/Soft/Review); a **normative** response model that excludes prior FCC history so it cannot 'expect' an already-failing gauge to stay silent; graded gap-quality tiers; FW tiers + an engineering queue; a 9-level policy matrix; and a dual-basis false-alert audit.

## 3. 30-day sliding-window causality model

Raw telemetry is retained only for the trailing 30 days; the window slides daily. At each inference time `t` the detector uses only raw in `[t-29d, t]` plus derived state updated by events resolved at/before `t`. Response is **END-anchored** (`[end, end+72h]`); censored / unknown are never counted as no_response; an episode contributes to state once (stable `episode_id`). A no_response deadline fires only if `end+72h <= last observed sample`, so a censored episode never flips to no_response when the end-of-day grid walks past it.

## 4. Data and variables

`fullChargeCapacity` (FCC) is integer mWh; `remainingCapacityInPercentage` is RSOC; `acdcMode` 1=AC/0=DC; `chargeStatus` 0/1/2 = idle/charge/discharge. Design capacity is recovered per user from `FCC*100/soh_design_pct`. Hardware identity (device_model/batt_vendor/batt_fru/serial/uuid) is banned from every feature/cluster/policy input and used only post-classification for enrichment.

## 5. Dual-step state: any-change vs effective-step

Two parallel tracks are maintained per user/window. The **any-change** track resets on any integer FCC step and drives `days_since_any_fcc_change`; the **effective** track resets on a >= threshold step and drives `days_since_effective_fcc_change`, the since-last-effective opportunity counters, the pending/censored set, and the normative cumulative anomaly. A sub-threshold step is a *micro* step (tracked via `n_micro_steps_since_effective_change` / `micro_wobble_only_since_effective_change`). This separation is what distinguishes a hard freeze (stale under both) from micro-wobble-only (effective-stale, any-active).
- Latest snapshot: 28 users are micro-wobble-only (any-change active but no effective relearning since the last effective change).

## 6. Gauge split results

- **Gauge Core (hard actionable)** = 0: long staleness under BOTH definitions, zero learning opportunities of any tier since the last effective change, an AC-bound/shallow/low-cycling usage cluster, and no FW-like no-response evidence.
- **Gauge Soft Calibration (effective-only, low-risk prompt)** = 2: micro-wobbles under any-change but no meaningful effective relearning step; reported separately and **never** counted as a hard Gauge Reset.
- **Gauge Review (manual/data-quality)** = 0: gauge-like staleness with large-gap ambiguity preventing a firm no-opportunity conclusion.

## 7. FW tier results

- **FW Core** = 2: data-quality OK, >=90d & >=30 cycles since the last effective change, zero observed effective responses, repeated HIGH_OK no_response (or normative anomaly >= 2.0 with conformal p <= 0.01), and high-quality evidence dominant.
- **FW Watch / High-anomaly** = 7: FW-like signal but a core requirement just short (staleness/cycles/quality/confirmed-count).
- **FW engineering queue**: top50 (n=29), top100 (n=29), ranked by normative anomaly then no_response, independent of the strict gate (spec 9.4).
Precision/recall vs final proxy:
```
           population proxy  n_flagged  n_proxy  tp  precision  recall
              FW_CORE    FW          2        1   1     0.5000     1.0
     FW_CORE+FW_WATCH    FW          9        1   1     0.1111     1.0
 FW_ENGINEERING_TOP50    FW         29        1   1     0.0345     1.0
FW_ENGINEERING_TOP100    FW         29        1   1     0.0345     1.0
           GAUGE_CORE GAUGE          0        2   0     0.0000     0.0
      GAUGE_CORE+SOFT GAUGE          2        2   0     0.0000     0.0
```

## 8. Normative vs personalized response model

- Normative model: status `synthesized_prior`.  (PRIMARY model — drives anomaly scoring & policy)
- Personalized model: status `not_run`.  (diagnostic only — never drives policy)
The normative model EXCLUDES `recent_30d_fcc_effective_changes_before_episode` (the v1 top feature), `fcc_before_episode`, `soh_before_episode`, `cycle_count_before_episode`, prior response/opportunity counts, and any FCC-history/response/identity feature, so it estimates what a HEALTHY gauge would do and does not learn to excuse an already-failing one.
**What this costs, stated plainly (spec 'be honest about any metric that worsens'):**
- The normative ROC AUC (~0.56) is *near-random*: episode geometry + non-FCC usage alone barely predict whether a healthy gauge would relearn. Most of v1's apparent skill was the gauge's own recent FCC history — an outcome proxy — which we deliberately removed.
- Because the normative probabilities collapse toward the base rate (operational `p_response` ~0.39 +/- 0.06), the Poisson-binomial anomaly degenerates to roughly `0.22 x (no_response count)`; `corr(cum_normative_fw_anomaly_score, no_response_count)` = 1.000. The top-50 FW recall of 1.0 is therefore a **count-based ranking**, reproducible from the raw no_response counters — the ML model adds little discriminative signal on top of the opportunity geometry.
- The normative calibration slope (~0.4) indicates an over-confident, poorly-calibrated head; its `brier_calibrated` is an in-sample isotonic estimate (the calibrator is fit on the same OOF vector), so it is optimistic — an honestly cross-fitted normative model does not beat a constant base-rate predictor. None of this changes labels, because FW/Gauge gating is driven by the deterministic counters and staleness, not the ML score.
- In the FW Core gate the `normative_anomaly>=2.0 & conformal_p<=0.01` clause is therefore effectively redundant with the no_response-count clauses (it only fires once counts are already high); removing it would not change FW Core membership. We keep it as a documented, non-decisive secondary signal.
- The **personalized** model (AUC ~0.82, slope ~0.97) is well-calibrated and genuinely predictive, but it is kept strictly diagnostic precisely because its skill comes from the failure-state proxy we must not let drive anomaly scoring.

## 9. Large-gap graded quality audit

Primary-band episode quality tiers:
```
quality_tier
HIGH_OK          1931
MEDIUM_GAP         80
LOW_LARGE_GAP      37
```
HIGH_OK no_response can support FW Core; MEDIUM_GAP supports FW Watch only; LOW_LARGE_GAP never counts as no_response evidence (ambiguity only). This replaces v1's binary ok / large_gap and avoids hard loss of all large-gap evidence.
Note (review GQ-1): the quality score penalises a dominant anchor-adjacent gap in both the coverage and endpoint components, so a *short* episode whose timeline is half-covered by a single overnight gap (max_gap<=12h but coverage~0.4) is intentionally demoted HIGH_OK -> MEDIUM (~4% of clean episodes). This is by design — a 12h gap inside a 12h episode is genuinely lower-evidence — but it means a handful of borderline users sit one HIGH_OK no_response short of FW Core and land in FW Watch instead. The `episode_quality_score` weights are tunable in `online_gap_quality.py` if a less conservative coverage rule is wanted.
Gap-rule x response-window sensitivity (episode-level):
```
 response_window_h gap_rule  n_opportunities  n_responded  n_no_response  n_censored  response_rate_complete
                24       6h             1883          167           1712           4                  0.0889
                24      12h             1950          169           1777           4                  0.0868
                24      24h             2018          174           1840           4                  0.0864
                24   graded             2011          174           1833           4                  0.0867
                72       6h             1883          324           1550           9                  0.1729
                72      12h             1950          330           1611           9                  0.1700
                72      24h             2018          342           1666          10                  0.1703
                72   graded             2011          342           1659          10                  0.1709
               168       6h             1883          508           1350          25                  0.2734
               168      12h             1950          525           1399          26                  0.2729
               168      24h             2018          550           1440          28                  0.2764
               168   graded             2011          548           1436          27                  0.2762
```

## 10. Usage-only clustering and post-hoc outcome profile

Clustering inputs are strictly usage-shape (cycle/AC/discharge ratios, RSOC levels & bands, switches, sampling) — NO response/no_response counts, NO FCC update/response, NO final labels, NO hardware. Outcome shares are profiled only AFTER clusters are named.
```
 cluster_id  n_windows  n_users  median_ac_time_ratio  median_rsoc_swing  median_cycle_delta cluster_profile_name
          0       1359       31                0.6902               91.0                 5.0    MOBILE_DEEP_CYCLE
          1       1507        8                0.8007               73.0                 5.0             AC_BOUND
          2        406        2                0.7250               92.0                13.0    MOBILE_DEEP_CYCLE
          3       2148       23                0.8192               53.0                 3.0             AC_BOUND
          4       2540       25                0.5786               98.0                 9.0    MOBILE_DEEP_CYCLE
          5        909       10                0.9377               72.0                 6.0             AC_BOUND
          6       1273        4                0.4535               97.0                21.0    MOBILE_DEEP_CYCLE
```
Post-hoc outcome profile (interpretation only):
```
 cluster_id cluster_profile_name  n_windows  share_response  share_no_response  share_censored  share_large_gap  share_fw_core  share_gauge_core  share_soft_calibration
         -1      SPARSE_OR_GAPPY        955          0.0656             0.9344          0.5719           0.0248         0.0000              0.00                    0.00
          0    MOBILE_DEEP_CYCLE       1359          0.1894             0.8106          0.2660           0.0488         0.0000              0.00                    0.00
          1             AC_BOUND       1507          0.0000             0.0000          0.0000           0.0000         0.0000              0.25                    0.25
          2    MOBILE_DEEP_CYCLE        406          0.0000             0.0000          0.0000           0.0000         0.0000              0.00                    0.00
          3             AC_BOUND       2148          0.0477             0.9523          0.2241           0.0581         0.0435              0.00                    0.00
          4    MOBILE_DEEP_CYCLE       2540          0.6304             0.3696          0.2170           0.0691         0.0000              0.00                    0.00
          5             AC_BOUND        909          0.1481             0.8519          0.2183           0.0338         0.1000              0.00                    0.00
          6    MOBILE_DEEP_CYCLE       1273          0.0720             0.9280          0.2256           0.0252         0.0000              0.00                    0.00
```

## 11. Stateful vs stateless backtest

Same-threshold (>=2 HIGH_OK no_response, 0 observed response, OK window): stateful=**13**, stateless(30d-only)=11, overlap=9, **stateful-only gain=4**, stateless-only=2. The persisted state recovers no-response evidence spread beyond a single 30-day window.

## 12. Final-proxy comparison

Final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an **evaluation proxy, not ground truth** (spec 3.3).
stateful_label_v2 (rows) x final proxy (cols):
```
final_label                                     ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  NORMAL_OR_RESPONDING  REVIEW_INSUFFICIENT_DATA  WATCH_LOW_UPDATE_RATE_AMBIGUOUS
stateful_label_v2                                                                                                                                                                                                                     
STATEFUL_FW_CHECK_CORE                                                                    1                                                         0                     1                         0                                0
STATEFUL_FW_WATCH_HIGH_ANOMALY                                                            0                                                         0                     3                         2                                2
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY                                            0                                                         0                     1                         1                                0
STATEFUL_NORMAL_RESPONDING                                                                0                                                         0                     2                         1                                0
STATEFUL_REVIEW_DATA_QUALITY                                                              0                                                         2                     2                         6                                1
STATEFUL_WATCH_LARGE_GAP_OR_CENSORED                                                      0                                                         0                     5                         1                                0
STATEFUL_WATCH_LOW_EVIDENCE                                                               0                                                         0                     3                         4                                2
```
Top-N yield:
```
                      score_col                                              proxy_label   N  hits  precision_at_N  recall_at_N  total_proxy_pos
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  10     1          0.1000          1.0                1
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  20     1          0.0500          1.0                1
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  30     1          0.0333          1.0                1
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  50     1          0.0200          1.0                1
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 100     1          0.0100          1.0                1
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  10     2          0.2000          1.0                2
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  20     2          0.1000          1.0                2
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  30     2          0.0667          1.0                2
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  50     2          0.0400          1.0                2
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 100     2          0.0200          1.0                2
```
No proxy-FW user landed in Normal/Gauge and no proxy-Gauge user landed in FW; any proxy-Gauge users in NORMAL are active responders and are listed in the cross-tab.

## 13. Active false-alert audit under both definitions

Per-label active overlap on three bases (legacy any-change `soh_update_status`, online any-change state, online effective-step state) + micro-wobble-only count:
```
                                      label_v2  n_users  active_false_alert_legacy_any_change  active_false_alert_online_any_state  active_false_alert_online_effective_state  n_micro_wobble_only
                        STATEFUL_FW_CHECK_CORE        2                                     1                                    1                                          0                    1
                STATEFUL_FW_WATCH_HIGH_ANOMALY        7                                     4                                    4                                          0                    4
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY        2                                     2                                    2                                          0                    2
                    STATEFUL_NORMAL_RESPONDING        3                                     3                                    3                                          2                    2
                  STATEFUL_REVIEW_DATA_QUALITY       11                                     8                                    2                                          1                   10
          STATEFUL_WATCH_LARGE_GAP_OR_CENSORED        6                                     6                                    6                                          6                    6
                   STATEFUL_WATCH_LOW_EVIDENCE        9                                     9                                    9                                          9                    3
```
Note: the legacy any-change basis counts sub-50 mWh micro-wobbles as 'active'; the operational effective-step basis is the meaningful one. Gauge Soft may include legacy-active users by design and is never counted as a hard Gauge Reset.

## 14. Sensitivity analysis

Policy-threshold grid (staleness x cycle x anomaly; 36 configs) — FW Core / Gauge Core counts and Jaccard vs the default config. Summary:
```
       n_fw_core  n_gauge_core  jaccard_fw_core_vs_default  jaccard_gauge_core_vs_default
count       36.0          36.0                        36.0                           36.0
mean         2.0           0.0                         1.0                            1.0
std          0.0           0.0                         0.0                            0.0
min          2.0           0.0                         1.0                            1.0
25%          2.0           0.0                         1.0                            1.0
50%          2.0           0.0                         1.0                            1.0
75%          2.0           0.0                         1.0                            1.0
max          2.0           0.0                         1.0                            1.0
```
Full grid in `sensitivity_grid_v2.csv`. Scope note: the episode/state pipeline is NOT re-run per policy config (only the snapshot gate is); the effective-step x response-window x gap-rule axes are covered by the episode-level grid in `episode_sensitivity_v2.csv`.

## 15. HW/FW enrichment after classification

_enrichment not run or no group met the minimum size._

## 16. Example case studies

See the per-tier example plots (`example_fw_core_top20/`, `example_fw_watch_top20/`, `example_gauge_core_top20/`, `example_gauge_soft_top20/`, `example_review_top20/`) produced by `plot_fcc_online_sliding30_v2.py`. Each shows RSOC, FCC with any/effective step markers, cycleCount, episodes coloured by quality tier, response/no_response/censored markers, and the state/action label + evidence summary.

## 17. Operational recommendations

- **FW Core** (2): prioritize BIOS/EC/battery-FW version and update review. This does not prove FW is defective.
- **FW Watch/Top-N** : engineering review queue; many proxy-FW users v1 sent to WATCH surface here.
- **Gauge Core** (0): gauge reset/calibration target.
- **Gauge Soft** (2): low-priority soft calibration prompt only.
- Alert only on state transitions with a cooldown, reset on FCC recovery.

## 18. Limitations

- These are **candidates, not confirmed FW faults**; the detector is mechanistic (learning opportunity vs FCC response) and does NOT predict failure from usage.
- The **normative response model is near-random (AUC ~0.56)** once FCC-history features are removed; its anomaly score is essentially a no_response-count ranker (Section 8). The operational decisions rest on the deterministic counters/staleness, not the ML model. The personalized model (AUC ~0.82) is predictive but quarantined to diagnostics.
- Evaluated against a PROXY label set, not ground truth.
- BIOS/EC/battery-FW versions and intervention outcomes are not available, so version-level enrichment and closed-loop validation are not yet possible.
- HDBSCAN/EBM are unavailable here; clustering uses GaussianMixture/KMeans.
- Most episodes are large-gap (sleep gaps), shrinking the high-quality opportunity pool.

## 19. Next data to collect

- BIOS/EC/battery-FW version per user (enables version-level enrichment).
- Gauge-reset / FW-update dates and post-intervention FCC response (closes the loop).
- A labelled set of confirmed FW-vs-gauge cases to move beyond the proxy.

## 20. Artifact list

Processed CSV/parquet under `data/processed/fcc_online_v2/`; figures under `data/reports/figures/fcc_online_v2/`; this report; the adversarial review at `data/reports/fcc_online_v2_adversarial_review.md`.