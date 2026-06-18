# Rolling 30-day FCC Learning/Response Online Detector v2.0 — Report

*Generated 2026-06-08T10:02:59Z · code `rolling30-v2.0` · window=30d stride=1d effective-step=`abs_ge_50mWh` response-window=72h episode-max-gap=12.0h*

## 1. Executive summary

- Cohort **752 users**, 3,130,394 raw samples, 200,059 user-windows (stride 1d).
- Each user receives exactly one latest `stateful_label_v2` via a 9-level priority ladder. Counts: **REVIEW_DATA_QUALITY**=325, **FW_CHECK_CORE**=5, **GAUGE_RESET_CORE**=4, **FW_WATCH_HIGH_ANOMALY**=43, **GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY**=22, **GAUGE_REVIEW**=7, **WATCH_LARGE_GAP_OR_CENSORED**=128, **WATCH_LOW_EVIDENCE**=35, **NORMAL_RESPONDING**=183.
- Gauge is split into hard **Core**=4, soft **Soft-Calibration**=22, **Review**=7 (no single undifferentiated Gauge number).
- FW is tiered: **Core**=5 (high-confidence review target), **Watch/High-anomaly**=43, plus a ranked engineering queue (top50/top100).
- Normative model (`logreg`, GroupKFold by user): ROC AUC **0.5584**, PR AUC 0.4299, Brier 0.2513 (calibrated 0.2349), calibration slope 0.418; n_episodes 9512, positive (response) rate 0.3902.
- Personalized model (`lightgbm`, GroupKFold by user): ROC AUC **0.8166**, PR AUC 0.7494, Brier 0.1667 (calibrated 0.1651), calibration slope 0.973; n_episodes 9512, positive (response) rate 0.3902.
- **Honest caveat (do not hide this tradeoff):** the normative model's ROC AUC is only ~0.56 — *near-random discrimination*. That is the deliberate price of removing the FCC-history features (the personalized model reaches ~0.82 precisely because it keeps them). Consequently the operational FW gating is carried by the **deterministic no_response/staleness counters**, not by the ML probability; the normative anomaly is a directional, count-driven ranker, not a strong classifier (see Section 8).
- Same-threshold no-response detection: stateful=41, stateless(30d-only)=22, **stateful-only gain=29**.
- These are **candidates for review, not confirmed FW faults**; evidence is mechanistic (learning opportunity vs FCC response), evaluated against a proxy label set.

## 2. Why v2 was needed

v1 produced one broad `GAUGE_RESET_CANDIDATE` (45) that mixed genuine freezes with micro-wobble users active under any-change, and a strict `FW_CHECK_CANDIDATE` (3) with high precision but low recall. v2 adds: a dual any-change/effective state; a Gauge split (Core/Soft/Review); a **normative** response model that excludes prior FCC history so it cannot 'expect' an already-failing gauge to stay silent; graded gap-quality tiers; FW tiers + an engineering queue; a 9-level policy matrix; and a dual-basis false-alert audit.

## 3. 30-day sliding-window causality model

Raw telemetry is retained only for the trailing 30 days; the window slides daily. At each inference time `t` the detector uses only raw in `[t-29d, t]` plus derived state updated by events resolved at/before `t`. Response is **END-anchored** (`[end, end+72h]`); censored / unknown are never counted as no_response; an episode contributes to state once (stable `episode_id`). A no_response deadline fires only if `end+72h <= last observed sample`, so a censored episode never flips to no_response when the end-of-day grid walks past it.

## 4. Data and variables

`fullChargeCapacity` (FCC) is integer mWh; `remainingCapacityInPercentage` is RSOC; `acdcMode` 1=AC/0=DC; `chargeStatus` 0/1/2 = idle/charge/discharge. Design capacity is recovered per user from `FCC*100/soh_design_pct`. Hardware identity (device_model/batt_vendor/batt_fru/serial/uuid) is banned from every feature/cluster/policy input and used only post-classification for enrichment.

## 5. Dual-step state: any-change vs effective-step

Two parallel tracks are maintained per user/window. The **any-change** track resets on any integer FCC step and drives `days_since_any_fcc_change`; the **effective** track resets on a >= threshold step and drives `days_since_effective_fcc_change`, the since-last-effective opportunity counters, the pending/censored set, and the normative cumulative anomaly. A sub-threshold step is a *micro* step (tracked via `n_micro_steps_since_effective_change` / `micro_wobble_only_since_effective_change`). This separation is what distinguishes a hard freeze (stale under both) from micro-wobble-only (effective-stale, any-active).
- Latest snapshot: 466 users are micro-wobble-only (any-change active but no effective relearning since the last effective change).

## 6. Gauge split results

- **Gauge Core (hard actionable)** = 4: long staleness under BOTH definitions, zero learning opportunities of any tier since the last effective change, an AC-bound/shallow/low-cycling usage cluster, and no FW-like no-response evidence.
- **Gauge Soft Calibration (effective-only, low-risk prompt)** = 22: micro-wobbles under any-change but no meaningful effective relearning step; reported separately and **never** counted as a hard Gauge Reset.
- **Gauge Review (manual/data-quality)** = 7: gauge-like staleness with large-gap ambiguity preventing a firm no-opportunity conclusion.

## 7. FW tier results

- **FW Core** = 5: data-quality OK, >=90d & >=30 cycles since the last effective change, zero observed effective responses, repeated HIGH_OK no_response (or normative anomaly >= 2.0 with conformal p <= 0.01), and high-quality evidence dominant.
- **FW Watch / High-anomaly** = 43: FW-like signal but a core requirement just short (staleness/cycles/quality/confirmed-count).
- **FW engineering queue**: top50 (n=50), top100 (n=100), ranked by normative anomaly then no_response, independent of the strict gate (spec 9.4).
Precision/recall vs final proxy:
```
           population proxy  n_flagged  n_proxy  tp  precision  recall
              FW_CORE    FW          5       14   5     1.0000  0.3571
     FW_CORE+FW_WATCH    FW         48       14  11     0.2292  0.7857
 FW_ENGINEERING_TOP50    FW         50       14  14     0.2800  1.0000
FW_ENGINEERING_TOP100    FW        100       14  14     0.1400  1.0000
           GAUGE_CORE GAUGE          4       18   4     1.0000  0.2222
      GAUGE_CORE+SOFT GAUGE         26       18   4     0.1538  0.2222
```

## 8. Normative vs personalized response model

- Normative model (`logreg`, GroupKFold by user): ROC AUC **0.5584**, PR AUC 0.4299, Brier 0.2513 (calibrated 0.2349), calibration slope 0.418; n_episodes 9512, positive (response) rate 0.3902.  (PRIMARY model — drives anomaly scoring & policy)
- Personalized model (`lightgbm`, GroupKFold by user): ROC AUC **0.8166**, PR AUC 0.7494, Brier 0.1667 (calibrated 0.1651), calibration slope 0.973; n_episodes 9512, positive (response) rate 0.3902.  (diagnostic only — never drives policy)
The normative model EXCLUDES `recent_30d_fcc_effective_changes_before_episode` (the v1 top feature), `fcc_before_episode`, `soh_before_episode`, `cycle_count_before_episode`, prior response/opportunity counts, and any FCC-history/response/identity feature, so it estimates what a HEALTHY gauge would do and does not learn to excuse an already-failing one.
**What this costs, stated plainly (spec 'be honest about any metric that worsens'):**
- The normative ROC AUC (~0.56) is *near-random*: episode geometry + non-FCC usage alone barely predict whether a healthy gauge would relearn. Most of v1's apparent skill was the gauge's own recent FCC history — an outcome proxy — which we deliberately removed.
- Because the normative probabilities collapse toward the base rate (operational `p_response` ~0.39 +/- 0.06), the Poisson-binomial anomaly degenerates to roughly `0.22 x (no_response count)`; `corr(cum_normative_fw_anomaly_score, no_response_count)` = 0.993. The top-50 FW recall of 1.0 is therefore a **count-based ranking**, reproducible from the raw no_response counters — the ML model adds little discriminative signal on top of the opportunity geometry.
- The normative calibration slope (~0.4) indicates an over-confident, poorly-calibrated head; its `brier_calibrated` is an in-sample isotonic estimate (the calibrator is fit on the same OOF vector), so it is optimistic — an honestly cross-fitted normative model does not beat a constant base-rate predictor. None of this changes labels, because FW/Gauge gating is driven by the deterministic counters and staleness, not the ML score.
- In the FW Core gate the `normative_anomaly>=2.0 & conformal_p<=0.01` clause is therefore effectively redundant with the no_response-count clauses (it only fires once counts are already high); removing it would not change FW Core membership. We keep it as a documented, non-decisive secondary signal.
- The **personalized** model (AUC ~0.82, slope ~0.97) is well-calibrated and genuinely predictive, but it is kept strictly diagnostic precisely because its skill comes from the failure-state proxy we must not let drive anomaly scoring.
Top normative features:
```
                              feature  weight        kind
recent_30d_cycle_delta_before_episode -0.3205 logreg_coef
           observed_coverage_fraction  0.2808 logreg_coef
                episode_quality_score -0.2166 logreg_coef
   recent_30d_ac_ratio_before_episode -0.1837 logreg_coef
  recent_30d_n_samples_before_episode  0.1827 logreg_coef
 recent_30d_rsoc_swing_before_episode  0.1470 logreg_coef
                   episode_duration_h -0.1249 logreg_coef
              start_to_low_duration_h -0.1237 logreg_coef
                    n_samples_episode  0.1201 logreg_coef
              charge_ratio_in_episode -0.1175 logreg_coef
```
Top personalized features:
```
                                        feature  weight              kind
                             fcc_before_episode     213 native_importance
recent_30d_fcc_effective_changes_before_episode     209 native_importance
                     cycle_count_before_episode     186 native_importance
          recent_30d_cycle_delta_before_episode     160 native_importance
                             soh_before_episode     141 native_importance
             recent_30d_ac_ratio_before_episode     124 native_importance
                              max_gap_h_episode     106 native_importance
                             episode_duration_h      88 native_importance
            recent_30d_max_gap_h_before_episode      76 native_importance
           recent_30d_rsoc_swing_before_episode      74 native_importance
```

## 9. Large-gap graded quality audit

Primary-band episode quality tiers:
```
LOW_LARGE_GAP    6424
MEDIUM_GAP       2710
HIGH_OK          2208
```
HIGH_OK no_response can support FW Core; MEDIUM_GAP supports FW Watch only; LOW_LARGE_GAP never counts as no_response evidence (ambiguity only). This replaces v1's binary ok / large_gap and avoids hard loss of all large-gap evidence.
Note (review GQ-1): the quality score penalises a dominant anchor-adjacent gap in both the coverage and endpoint components, so a *short* episode whose timeline is half-covered by a single overnight gap (max_gap<=12h but coverage~0.4) is intentionally demoted HIGH_OK -> MEDIUM (~4% of clean episodes). This is by design — a 12h gap inside a 12h episode is genuinely lower-evidence — but it means a handful of borderline users sit one HIGH_OK no_response short of FW Core and land in FW Watch instead. The `episode_quality_score` weights are tunable in `online_gap_quality.py` if a less conservative coverage rule is wanted.
Gap-rule x response-window sensitivity (episode-level):
```
 response_window_h gap_rule  n_opportunities  n_responded  n_no_response  n_censored  response_rate_complete
                24       6h              895          220            673           2                  0.2464
                24      12h             2319          574           1734          11                  0.2487
                24      24h             5050         1299           3727          24                  0.2585
                24   graded             4918         1261           3633          24                  0.2577
                72       6h              895          351            540           4                  0.3939
                72      12h             2319          901           1402          16                  0.3912
                72      24h             5050         1978           3035          37                  0.3946
                72   graded             4918         1917           2964          37                  0.3927
               168       6h              895          519            370           6                  0.5838
               168      12h             2319         1338            959          22                  0.5825
               168      24h             5050         2855           2141          54                  0.5715
               168   graded             4918         2773           2092          53                  0.5700
```

## 10. Usage-only clustering and post-hoc outcome profile

Clustering inputs are strictly usage-shape (cycle/AC/discharge ratios, RSOC levels & bands, switches, sampling) — NO response/no_response counts, NO FCC update/response, NO final labels, NO hardware. Outcome shares are profiled only AFTER clusters are named.
```
 cluster_id  n_windows  n_users  median_ac_time_ratio  median_rsoc_swing  median_cycle_delta cluster_profile_name
          0       6265      400                0.4392               96.0                 5.0    MOBILE_DEEP_CYCLE
          1       2992      115                0.8030               93.0                 6.0             AC_BOUND
          2      11323       66                0.7852               61.0                 4.0    MOBILE_DEEP_CYCLE
          3      14282      402                0.8497               93.0                 7.0             AC_BOUND
          4      72514      541                0.6166               94.0                10.0    MOBILE_DEEP_CYCLE
          5      59619      539                0.8768               53.0                 3.0             AC_BOUND
          6         33        1                0.4293               73.0                22.0    MOBILE_DEEP_CYCLE
```
Post-hoc outcome profile (interpretation only):
```
 cluster_id cluster_profile_name  n_windows  share_response  share_no_response  share_censored  share_large_gap  share_fw_core  share_gauge_core  share_soft_calibration
         -1      SPARSE_OR_GAPPY      33031          0.5769             0.4231          0.0250           0.8689         0.0000            0.0000                  0.0000
          0    MOBILE_DEEP_CYCLE       6265          0.5012             0.4988          0.0286           0.7806         0.0000            0.0000                  0.0000
          1             AC_BOUND       2992          0.3941             0.6059          0.0289           0.7102         0.0087            0.0261                  0.0435
          2    MOBILE_DEEP_CYCLE      11323          0.3145             0.6855          0.0079           0.9214         0.0000            0.0000                  0.0000
          3             AC_BOUND      14282          0.4471             0.5529          0.0275           0.6986         0.0124            0.0025                  0.0149
          4    MOBILE_DEEP_CYCLE      72514          0.3582             0.6418          0.0203           0.7970         0.0074            0.0000                  0.0000
          5             AC_BOUND      59619          0.6942             0.3058          0.0045           0.9288         0.0056            0.0223                  0.0705
          6    MOBILE_DEEP_CYCLE         33          0.0000             0.0000          0.0000           1.0000         0.0000            0.0000                  0.0000
```

## 11. Stateful vs stateless backtest

Same-threshold (>=2 HIGH_OK no_response, 0 observed response, OK window): stateful=**41**, stateless(30d-only)=22, overlap=12, **stateful-only gain=29**, stateless-only=10. The persisted state recovers no-response evidence spread beyond a single 30-day window.

## 12. Final-proxy comparison

Final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an **evaluation proxy, not ground truth** (spec 3.3).
stateful_label_v2 (rows) x final proxy (cols):
```
final_label                                     ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  NORMAL_OR_RESPONDING  REVIEW_INSUFFICIENT_DATA  WATCH_LOW_UPDATE_RATE_AMBIGUOUS
stateful_label_v2                                                                                                                                                                                                                     
STATEFUL_FW_CHECK_CORE                                                                    5                                                         0                     0                         0                                0
STATEFUL_FW_WATCH_HIGH_ANOMALY                                                            6                                                         0                    16                        12                                9
STATEFUL_GAUGE_RESET_CORE                                                                 0                                                         4                     0                         0                                0
STATEFUL_GAUGE_REVIEW                                                                     0                                                         1                     0                         1                                5
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY                                            0                                                         0                    21                         1                                0
STATEFUL_NORMAL_RESPONDING                                                                0                                                         3                   121                        55                                4
STATEFUL_REVIEW_DATA_QUALITY                                                              3                                                        10                    81                       211                               20
STATEFUL_WATCH_LARGE_GAP_OR_CENSORED                                                      0                                                         0                    71                        42                               15
STATEFUL_WATCH_LOW_EVIDENCE                                                               0                                                         0                    17                        16                                2
```
Top-N yield:
```
                      score_col                                              proxy_label   N  hits  precision_at_N  recall_at_N  total_proxy_pos
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  10     7          0.7000       0.5000               14
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  20    12          0.6000       0.8571               14
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  30    13          0.4333       0.9286               14
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  50    14          0.2800       1.0000               14
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 100    14          0.1400       1.0000               14
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  10     0          0.0000       0.0000               18
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  20     1          0.0500       0.0556               18
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  30     1          0.0333       0.0556               18
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  50     5          0.1000       0.2778               18
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 100    10          0.1000       0.5556               18
```
Proxy routing asymmetries explicitly listed (3) in `proxy_misroute_v2.csv`: proxy_GAUGE_in_normal=3. No proxy-FW user landed in Normal or Gauge, and no proxy-Gauge user landed in an FW tier. The 3 proxy-FW users not in an FW tier are in REVIEW_DATA_QUALITY with `fw_like_evidence_flag` + `would_have_been=FW_CORE_LIKE` (data-quality outranks action, spec 3.6). Separately, 3/18 proxy-Gauge users are labeled NORMAL_RESPONDING — they are active responders the proxy still flagged; this is surfaced, not hidden.

## 13. Active false-alert audit under both definitions

Per-label active overlap on three bases (legacy any-change `soh_update_status`, online any-change state, online effective-step state) + micro-wobble-only count:
```
                                      label_v2  n_users  active_false_alert_legacy_any_change  active_false_alert_online_any_state  active_false_alert_online_effective_state  n_micro_wobble_only
                        STATEFUL_FW_CHECK_CORE        5                                     0                                    0                                          0                    0
                STATEFUL_FW_WATCH_HIGH_ANOMALY       43                                    20                                   20                                          0                   24
                     STATEFUL_GAUGE_RESET_CORE        4                                     0                                    0                                          0                    1
                         STATEFUL_GAUGE_REVIEW        7                                     0                                    0                                          0                    0
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY       22                                    22                                   22                                          0                   22
                    STATEFUL_NORMAL_RESPONDING      183                                   171                                  171                                        134                  108
                  STATEFUL_REVIEW_DATA_QUALITY      325                                   275                                  100                                         63                  197
          STATEFUL_WATCH_LARGE_GAP_OR_CENSORED      128                                   115                                  115                                         85                   95
                   STATEFUL_WATCH_LOW_EVIDENCE       35                                    35                                   35                                         35                   19
```
- **Gauge Core legacy-any active false alerts = 0**
Note: the legacy any-change basis counts sub-50 mWh micro-wobbles as 'active'; the operational effective-step basis is the meaningful one. Gauge Soft may include legacy-active users by design and is never counted as a hard Gauge Reset.

## 14. Sensitivity analysis

Policy-threshold grid (staleness x cycle x anomaly; 36 configs) — FW Core / Gauge Core counts and Jaccard vs the default config. Summary:
```
       n_fw_core  n_gauge_core  jaccard_fw_core_vs_default  jaccard_gauge_core_vs_default
count     36.000          36.0                      36.000                           36.0
mean       4.000           4.0                       0.800                            1.0
std        1.242           0.0                       0.248                            0.0
min        2.000           4.0                       0.400                            1.0
25%        3.500           4.0                       0.700                            1.0
50%        4.500           4.0                       0.900                            1.0
75%        5.000           4.0                       1.000                            1.0
max        5.000           4.0                       1.000                            1.0
```
Full grid in `sensitivity_grid_v2.csv`. Scope note: the episode/state pipeline is NOT re-run per policy config (only the snapshot gate is); the effective-step x response-window x gap-rule axes are covered by the episode-level grid in `episode_sensitivity_v2.csv`.

## 15. HW/FW enrichment after classification

Multi-population beta-binomial shrunk rates + Fisher/BH (post-classification only). Top rows:
```
population group_axis     group_value  n_total  n_candidate  raw_rate  shrunk_rate  ci_low  ci_high  fisher_p  q_value  fleet_rate  population_n  small_population_warning
   FW_CORE   batt_fru      5B10W13975       26            3    0.1154       0.0901  0.0199   0.2054   0.00004  0.00177      0.0041             5                      True
   FW_CORE   batt_fru      5B11H56412        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11M90164        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B10W51875        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B10W51883        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11M90106        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11M90125        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11M90171        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11H56397        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11H56406        5            0    0.0000       0.0036  0.0000   0.0415   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru        L24B4PE2        6            0    0.0000       0.0033  0.0000   0.0384   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru LNV-5B11M90101@        6            0    0.0000       0.0033  0.0000   0.0384   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11M90169        6            0    0.0000       0.0033  0.0000   0.0384   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11H56401        6            0    0.0000       0.0033  0.0000   0.0384   1.00000  1.00000      0.0041             5                      True
   FW_CORE   batt_fru      5B11H56407        6            0    0.0000       0.0033  0.0000   0.0384   1.00000  1.00000      0.0041             5                      True
```
Candidate `n` is small for several populations (warned in `small_population_warning`); BIOS/EC/battery-FW version fields are not present in this dataset, so version-level enrichment is unavailable.

## 16. Example case studies

See the per-tier example plots (`example_fw_core_top20/`, `example_fw_watch_top20/`, `example_gauge_core_top20/`, `example_gauge_soft_top20/`, `example_review_top20/`) produced by `plot_fcc_online_sliding30_v2.py`. Each shows RSOC, FCC with any/effective step markers, cycleCount, episodes coloured by quality tier, response/no_response/censored markers, and the state/action label + evidence summary.

## 17. Operational recommendations

- **FW Core** (5): prioritize BIOS/EC/battery-FW version and update review. This does not prove FW is defective.
- **FW Watch/Top-N** : engineering review queue; many proxy-FW users v1 sent to WATCH surface here.
- **Gauge Core** (4): gauge reset/calibration target.
- **Gauge Soft** (22): low-priority soft calibration prompt only.
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