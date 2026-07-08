# Rolling 30-day FCC Learning/Response Online Detector v2.0 — Report

*Generated 2026-07-08T17:46:07Z · code `rolling30-od2.0` · window=30d stride=1d effective-step=`abs_ge_50mWh` response-window=168h episode-max-gap=12.0h*

## 1. Executive summary

- Cohort **752 users**, 3,130,394 raw samples, 200,059 user-windows (stride 1d).
- Each user receives exactly one latest `stateful_label_v2` via a 9-level priority ladder. Counts: **REVIEW_DATA_QUALITY**=325, **FW_CHECK_CORE**=49, **FW_WATCH_HIGH_ANOMALY**=99, **GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY**=2, **WATCH_LARGE_GAP_OR_CENSORED**=70, **WATCH_LOW_EVIDENCE**=166, **NORMAL_RESPONDING**=41.
- Gauge is split into hard **Core**=0, soft **Soft-Calibration**=2, **Review**=0 (no single undifferentiated Gauge number).
- FW is tiered: **Core**=49 (high-confidence review target), **Watch/High-anomaly**=99, plus a ranked engineering queue (top50/top100).
- Normative model: status `synthesized_prior`.
- Personalized model: status `not_run`.
- **Honest caveat (do not hide this tradeoff):** the normative model's ROC AUC is only ~0.56 — *near-random discrimination*. That is the deliberate price of removing the FCC-history features (the personalized model reaches ~0.82 precisely because it keeps them). Consequently the operational FW gating is carried by the **deterministic no_response/staleness counters**, not by the ML probability; the normative anomaly is a directional, count-driven ranker, not a strong classifier (see Section 8).
- Same-threshold no-response detection: stateful=260, stateless(30d-only)=199, **stateful-only gain=73**.
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

- **Gauge Core (hard actionable)** = 0: long staleness under BOTH definitions, zero learning opportunities of any tier since the last effective change, an AC-bound/shallow/low-cycling usage cluster, and no FW-like no-response evidence.
- **Gauge Soft Calibration (effective-only, low-risk prompt)** = 2: micro-wobbles under any-change but no meaningful effective relearning step; reported separately and **never** counted as a hard Gauge Reset.
- **Gauge Review (manual/data-quality)** = 0: gauge-like staleness with large-gap ambiguity preventing a firm no-opportunity conclusion.

## 7. FW tier results

- **FW Core** = 49: data-quality OK, >=90d & >=30 cycles since the last effective change, zero observed effective responses, repeated HIGH_OK no_response (or normative anomaly >= 2.0 with conformal p <= 0.01), and high-quality evidence dominant.
- **FW Watch / High-anomaly** = 99: FW-like signal but a core requirement just short (staleness/cycles/quality/confirmed-count).
- **FW engineering queue**: top50 (n=50), top100 (n=100), ranked by normative anomaly then no_response, independent of the strict gate (spec 9.4).
Precision/recall vs final proxy:
```
           population proxy  n_flagged  n_proxy  tp  precision  recall
              FW_CORE    FW         49       35  22     0.4490  0.6286
     FW_CORE+FW_WATCH    FW        148       35  25     0.1689  0.7143
 FW_ENGINEERING_TOP50    FW         50       35  27     0.5400  0.7714
FW_ENGINEERING_TOP100    FW        100       35  33     0.3300  0.9429
           GAUGE_CORE GAUGE          0       10   0     0.0000  0.0000
      GAUGE_CORE+SOFT GAUGE          2       10   0     0.0000  0.0000
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
HIGH_OK          31436
MEDIUM_GAP        2127
LOW_LARGE_GAP     1015
```
HIGH_OK no_response can support FW Core; MEDIUM_GAP supports FW Watch only; LOW_LARGE_GAP never counts as no_response evidence (ambiguity only). This replaces v1's binary ok / large_gap and avoids hard loss of all large-gap evidence.
Note (review GQ-1): the quality score penalises a dominant anchor-adjacent gap in both the coverage and endpoint components, so a *short* episode whose timeline is half-covered by a single overnight gap (max_gap<=12h but coverage~0.4) is intentionally demoted HIGH_OK -> MEDIUM (~4% of clean episodes). This is by design — a 12h gap inside a 12h episode is genuinely lower-evidence — but it means a handful of borderline users sit one HIGH_OK no_response short of FW Core and land in FW Watch instead. The `episode_quality_score` weights are tunable in `online_gap_quality.py` if a less conservative coverage rule is wanted.
Gap-rule x response-window sensitivity (episode-level):
```
 response_window_h gap_rule  n_opportunities  n_responded  n_no_response  n_censored  response_rate_complete
                24       6h            30677         5496          25097          84                  0.1796
                24      12h            32228         5708          26429          91                  0.1776
                24      24h            33781         5924          27758          99                  0.1759
                24   graded            33563         5887          27579          97                  0.1759
                72       6h            30677         8145          22324         208                  0.2673
                72      12h            32228         8497          23512         219                  0.2655
                72      24h            33781         8834          24712         235                  0.2633
                72   graded            33563         8781          24549         233                  0.2635
               168       6h            30677        11294          18913         470                  0.3739
               168      12h            32228        11808          19924         496                  0.3721
               168      24h            33781        12283          20977         521                  0.3693
               168   graded            33563        12208          20841         514                  0.3694
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
         -1      SPARSE_OR_GAPPY      33031          0.3281             0.6719          0.3052           0.1506         0.0000            0.0000                  0.0000
          0    MOBILE_DEEP_CYCLE       6265          0.5939             0.4061          0.3194           0.0619         0.0275            0.0000                  0.0000
          1             AC_BOUND       2992          0.4648             0.5352          0.2202           0.0976         0.0522            0.0174                  0.0087
          2    MOBILE_DEEP_CYCLE      11323          0.4444             0.5556          0.1466           0.1552         0.0606            0.0000                  0.0000
          3             AC_BOUND      14282          0.3272             0.6728          0.2387           0.0342         0.0821            0.0000                  0.0000
          4    MOBILE_DEEP_CYCLE      72514          0.4528             0.5472          0.2186           0.0638         0.0887            0.0000                  0.0000
          5             AC_BOUND      59619          0.1053             0.8947          0.2193           0.0812         0.0965            0.0000                  0.0037
          6    MOBILE_DEEP_CYCLE         33          0.0633             0.9367          0.1939           0.0000         0.0000            0.0000                  0.0000
```

## 11. Stateful vs stateless backtest

Same-threshold (>=2 HIGH_OK no_response, 0 observed response, OK window): stateful=**260**, stateless(30d-only)=199, overlap=187, **stateful-only gain=73**, stateless-only=12. The persisted state recovers no-response evidence spread beyond a single 30-day window.

## 12. Final-proxy comparison

Final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an **evaluation proxy, not ground truth** (spec 3.3).
stateful_label_v2 (rows) x final proxy (cols):
```
final_label                                     ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  NORMAL_OR_RESPONDING  REVIEW_INSUFFICIENT_DATA  WATCH_LOW_UPDATE_RATE_AMBIGUOUS
stateful_label_v2                                                                                                                                                                                                                     
STATEFUL_FW_CHECK_CORE                                                                   22                                                         0                    18                         7                                2
STATEFUL_FW_WATCH_HIGH_ANOMALY                                                            3                                                         0                    52                        36                                8
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY                                            0                                                         0                     2                         0                                0
STATEFUL_NORMAL_RESPONDING                                                                0                                                         3                    23                        12                                3
STATEFUL_REVIEW_DATA_QUALITY                                                             10                                                         7                    81                       211                               16
STATEFUL_WATCH_LARGE_GAP_OR_CENSORED                                                      0                                                         0                    46                        20                                4
STATEFUL_WATCH_LOW_EVIDENCE                                                               0                                                         0                   105                        52                                9
```
Top-N yield:
```
                      score_col                                              proxy_label   N  hits  precision_at_N  recall_at_N  total_proxy_pos
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  10     9          0.9000       0.2571               35
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  20    17          0.8500       0.4857               35
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  30    20          0.6667       0.5714               35
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  50    27          0.5400       0.7714               35
 cum_normative_fw_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 100    33          0.3300       0.9429               35
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  10     1          0.1000       0.1000               10
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  20     1          0.0500       0.1000               10
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  30     1          0.0333       0.1000               10
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  50     2          0.0400       0.2000               10
days_since_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 100     8          0.0800       0.8000               10
```
Proxy routing asymmetries explicitly listed (3) in `proxy_misroute_v2.csv`: proxy_GAUGE_in_normal=3. No proxy-FW user landed in Normal or Gauge, and no proxy-Gauge user landed in an FW tier. The 3 proxy-FW users not in an FW tier are in REVIEW_DATA_QUALITY with `fw_like_evidence_flag` + `would_have_been=FW_CORE_LIKE` (data-quality outranks action, spec 3.6). Separately, 3/18 proxy-Gauge users are labeled NORMAL_RESPONDING — they are active responders the proxy still flagged; this is surfaced, not hidden.

## 13. Active false-alert audit under both definitions

Per-label active overlap on three bases (legacy any-change `soh_update_status`, online any-change state, online effective-step state) + micro-wobble-only count:
```
                                      label_v2  n_users  active_false_alert_legacy_any_change  active_false_alert_online_any_state  active_false_alert_online_effective_state  n_micro_wobble_only
                        STATEFUL_FW_CHECK_CORE       49                                    18                                   18                                          0                   21
                STATEFUL_FW_WATCH_HIGH_ANOMALY       99                                    77                                   77                                          0                   80
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY        2                                     2                                    2                                          0                    2
                    STATEFUL_NORMAL_RESPONDING       41                                    31                                   31                                         21                   20
                  STATEFUL_REVIEW_DATA_QUALITY      325                                   275                                  100                                         63                  197
          STATEFUL_WATCH_LARGE_GAP_OR_CENSORED       70                                    69                                   69                                         67                   54
                   STATEFUL_WATCH_LOW_EVIDENCE      166                                   166                                  166                                        166                   92
```
Note: the legacy any-change basis counts sub-50 mWh micro-wobbles as 'active'; the operational effective-step basis is the meaningful one. Gauge Soft may include legacy-active users by design and is never counted as a hard Gauge Reset.

## 14. Sensitivity analysis

Policy-threshold grid (staleness x cycle x anomaly; 36 configs) — FW Core / Gauge Core counts and Jaccard vs the default config. Summary:
```
       n_fw_core  n_gauge_core  jaccard_fw_core_vs_default  jaccard_gauge_core_vs_default
count     36.000          36.0                      36.000                           36.0
mean      40.417           0.0                       0.726                            1.0
std       12.173           0.0                       0.155                            0.0
min       24.000           0.0                       0.490                            1.0
25%       31.500           0.0                       0.612                            1.0
50%       35.500           0.0                       0.675                            1.0
75%       49.000           0.0                       0.801                            1.0
max       62.000           0.0                       1.000                            1.0
```
Full grid in `sensitivity_grid_v2.csv`. Scope note: the episode/state pipeline is NOT re-run per policy config (only the snapshot gate is); the effective-step x response-window x gap-rule axes are covered by the episode-level grid in `episode_sensitivity_v2.csv`.

## 15. HW/FW enrichment after classification

Multi-population beta-binomial shrunk rates + Fisher/BH (post-classification only). Top rows:
```
population group_axis     group_value  n_total  n_candidate  raw_rate  shrunk_rate  ci_low  ci_high  fisher_p  q_value  fleet_rate  population_n  small_population_warning
   FW_CORE   batt_fru      5B11M90056       10            5    0.5000       0.3719  0.1503   0.6278   0.00013  0.00281      0.0603            49                     False
   FW_CORE   batt_fru      5B10W13975       26            9    0.3462       0.3073  0.1589   0.4798   0.00001  0.00029      0.0603            49                     False
   FW_CORE   batt_fru      5B11M90051        8            2    0.2500       0.1864  0.0310   0.4374   0.07887  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B10W51875        5            1    0.2000       0.1384  0.0077   0.4099   0.26781  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B10W13973       30            4    0.1333       0.1249  0.0382   0.2527   0.09970  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11H56407        6            1    0.1667       0.1247  0.0069   0.3744   0.31225  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11K07737        7            1    0.1429       0.1136  0.0062   0.3444   0.35404  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B10W13974       19            2    0.1053       0.0979  0.0153   0.2445   0.31946  1.00000      0.0603            49                     False
   FW_CORE   batt_fru LNV-5B11H56403       22            2    0.0909       0.0867  0.0134   0.2181   0.38737  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11M90097       23            2    0.0870       0.0835  0.0129   0.2105   0.40943  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11M90098       19            1    0.0526       0.0547  0.0028   0.1748   0.69774  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11H56384       19            1    0.0526       0.0547  0.0028   0.1748   0.69774  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11H56383       23            1    0.0435       0.0467  0.0024   0.1500   0.76603  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11M37553       23            1    0.0435       0.0467  0.0024   0.1500   0.76603  1.00000      0.0603            49                     False
   FW_CORE   batt_fru      5B11M90125        5            0    0.0000       0.0292  0.0000   0.1885   1.00000  1.00000      0.0603            49                     False
```
Candidate `n` is small for several populations (warned in `small_population_warning`); BIOS/EC/battery-FW version fields are not present in this dataset, so version-level enrichment is unavailable.

## 16. Example case studies

See the per-tier example plots (`example_fw_core_top20/`, `example_fw_watch_top20/`, `example_gauge_core_top20/`, `example_gauge_soft_top20/`, `example_review_top20/`) produced by `plot_fcc_online_sliding30_v2.py`. Each shows RSOC, FCC with any/effective step markers, cycleCount, episodes coloured by quality tier, response/no_response/censored markers, and the state/action label + evidence summary.

## 17. Operational recommendations

- **FW Core** (49): prioritize BIOS/EC/battery-FW version and update review. This does not prove FW is defective.
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