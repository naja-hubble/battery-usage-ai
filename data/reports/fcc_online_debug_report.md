# 30-day Sliding-Window FCC Learning/Response ML Detection — Report

*Generated 2026-06-08T06:25:06Z · code `rolling30-v1.0` · window=30d stride=7d effective-step=`abs_ge_50mWh` response-window=72h episode-max-gap=12.0h*

## 1. Executive summary

- Cohort: **40 users**, 190,783 raw samples, 1,607 user-windows at stride=7d.
- Latest-snapshot stateful labels: **STATEFUL_NORMAL**=23, **STATEFUL_WATCH**=12, **STATEFUL_REVIEW**=4, **STATEFUL_GAUGE_RESET_CANDIDATE**=1.
- Episode response model (`hgb`, GroupKFold by user): ROC AUC **0.62**, PR AUC 0.4725, Brier 0.2796 (calibrated 0.2221), calib slope 0.184; positive (response) rate 0.3882.
- Same-threshold detection (≥2 no_response, 0 response, OK window): stateful=1, stateless(30d-only)=1, **stateful-only gain=1** (evidence spread beyond 30 days). Strict action gate yields FW=0, Gauge=1.
- Active false-alert rate vs `soh_update_status` (any-change): 0.0 (0/1); but by our 50 mWh-effective definition it is **0.0** (0/1) — the gap is the any-change vs effective-step definition, not a wrong call.

## 2. The 30-day constraint and the design change

Raw telemetry is assumed retained for only the trailing 30 days; the window slides daily (`[t-29,t]` -> `[t-28,t+1]`). The detector therefore separates a **stateless** view (the 30d raw window only) from a **stateful** online detector whose *derived* state (counters since the last effective FCC change, pending/censored episodes) may persist long-term. Every inference point uses only the trailing raw window plus state updated up to that point — no future raw, no raw older than 30 days, no look-ahead at final labels (spec 0.3 / 13.1).

## 3. Why direct very_stale prediction is inappropriate

Prior supervised work (PROJECT_STATUS.md) showed that predicting `very_stale` directly from usage behaviour reaches only AUC≈0.54 in the fair (obs≥180d) regime — essentially random. So we do **not** classify `30d usage -> FW fault`. Instead we estimate, per learning episode, the probability a healthy gauge would respond, and flag users/windows whose **observed** responses fall far below that **expected** response given real high→low→high opportunities (spec 0.2).

## 4. Data and variables

- `fullChargeCapacity` is integer **mWh** (PROJECT_STATUS PDF correction); SoH steps iff FCC steps. `remainingCapacityInPercentage` = RSOC. `acdcMode` 1=AC/0=DC. Design capacity recovered per user from `FCC*100/soh_design_pct` (median).
- Episode quality distribution (all bands): {'large_gap': 1660, 'ok': 480}. Large-gap dominance reflects multi-hour sleep gaps inside otherwise full-range discharges; these are protected out of OK opportunities.

## 5. Rolling window features

One row per `user_id × window_end_date` with data-quality (n_samples, gaps, counter reset), usage (cycle delta/rate, AC/charge/discharge time ratios, RSOC levels & band fractions, switch and discharge-session counts) and FCC (start/end/min/max, any vs effective changes, last effective change ts/cycle) blocks. Time-weighted ratios use capped gap-to-next weights.

## 6. Episode / stateful detector

High→low→high RSOC excursions are detected for 3 bands (80/20, 85/15, 90/10). Response is **end-anchored**: an effective FCC step in `[end, end+72h]` is a response (spec 7.4). The online state replays events in time order: an effective FCC step **resets** the since-last-change counters and clears the pending set (those episodes just responded); a pending OK episode whose 72h window closes with no step becomes a confirmed **no_response**. Each episode is keyed by a stable `episode_id` so overlapping windows never double-count it (spec 7.5).

## 7. Effective FCC step definition and sensitivity

```
      effective_step  n_ok_complete_primary  n_responded  n_no_response  n_censored  response_rate
          any_change                    240          144             96           1         0.6000
        abs_ge_50mWh                    239           91            148           2         0.3808
       abs_ge_100mWh                    239           88            151           2         0.3682
abs_ge_0p1pct_design                    239           91            148           2         0.3808
abs_ge_0p5pct_design                    239           80            159           2         0.3347
```
Default `abs_ge_50mWh` avoids counting micro-wobbles (~58% of raw steps are <50 mWh) as learning responses, which would mask genuine no-response (spec 5.3).
Episode-gap sensitivity (6/12/24h):
```
 episode_max_gap_hours  n_ok  n_large_gap  ok_fraction
                   6.0    74          899       0.0761
                  12.0   241          732       0.2477
                  24.0   479          494       0.4923
```
Response-window sensitivity (24/72/168h):
```
 response_window_hours  n_responded  n_no_response  n_censored  response_rate_complete
                    24           51            189           1                  0.2125
                    72           91            148           2                  0.3808
                   168          143             96           2                  0.5983
```

## 8. Unsupervised usage clustering

```
 cluster_id  n_windows  n_users  median_ac_time_ratio  median_rsoc_swing  median_cycle_delta  share_no_response          cluster_profile_name suggested_action_hint
          0        197       10                0.4471               97.0                21.0           0.922360 MOBILE_DEEP_CYCLE_NO_RESPONSE         fw_check_hint
          1        228        6                0.7971               73.0                 4.5           1.000000           LARGE_GAP_AMBIGUOUS            watch_hint
          2        398       33                0.7092               94.0                 6.0           1.000000           LARGE_GAP_AMBIGUOUS            watch_hint
          3         70        2                0.7224               93.0                13.5           0.000000           LARGE_GAP_AMBIGUOUS            watch_hint
          4          8        1                0.6448               85.0                17.0           0.000000  MOBILE_DEEP_CYCLE_RESPONDING           normal_hint
          5        183       14                0.4074               98.0                17.0           0.436293  MOBILE_DEEP_CYCLE_RESPONDING           normal_hint
          6        382       24                0.8846               54.0                 4.0                NaN                      AC_BOUND      gauge_reset_hint
```

## 9. Self-supervised episode response model

```
   model  n_episodes  n_users  positive_rate  roc_auc  pr_auc  brier  brier_calibrated  calib_slope  tp@0.5  fp@0.5  tn@0.5  fn@0.5  tp@0.7  fp@0.7  tn@0.7  fn@0.7  tp@0.9  fp@0.9  tn@0.9  fn@0.9
  logreg         474       20         0.3882   0.5647  0.5311 0.2799            0.2168        0.120      84      72     218     100      58      41     249     126      26       8     282     158
     hgb         474       20         0.3882   0.6200  0.4725 0.2796            0.2221        0.184      93      88     202      91      58      55     235     126      14      19     271     170
lightgbm         474       20         0.3882   0.5991  0.4580 0.2895            0.2240        0.142      74      81     209     110      42      51     239     142      14      16     274     170
```
Top features:
```
                                        feature  weight  weight_std                kind
recent_30d_fcc_effective_changes_before_episode 0.11428     0.00857 permutation_roc_auc
             recent_30d_ac_ratio_before_episode 0.01568     0.00311 permutation_roc_auc
                              n_samples_episode 0.00681     0.00121 permutation_roc_auc
                                       end_rsoc 0.00231     0.00096 permutation_roc_auc
                              max_gap_h_episode 0.00070     0.00025 permutation_roc_auc
            recent_30d_max_gap_h_before_episode 0.00049     0.00007 permutation_roc_auc
                          low_to_end_duration_h 0.00037     0.00021 permutation_roc_auc
                             episode_duration_h 0.00026     0.00018 permutation_roc_auc
                             fcc_before_episode 0.00016     0.00004 permutation_roc_auc
          recent_30d_cycle_delta_before_episode 0.00007     0.00005 permutation_roc_auc
                            cycle_delta_episode 0.00005     0.00001 permutation_roc_auc
                        start_to_low_duration_h 0.00004     0.00003 permutation_roc_auc
```
Leakage guards asserted: no hardware identity, no future FCC/response, no final label, GroupKFold by user_id (29-day-overlapping windows never split).

## 10. User-window anomaly scores

Per window: `expected_response_30d = Σ p_i`, `observed_response_30d`, `p_all_no_response_30d = Π(1-clip(p_i))` over **resolved-by-t** OK primary opportunities, `fw_response_anomaly_score_30d = -log10(p_all_no_response)`, and an empirical `conformal_p` vs clean OK windows. Zero-opportunity windows get score 0 (no spurious anomaly, spec 16.15).
Score distribution over scored windows (n=321): p50=0.319, p90=1.605, p99=3.225, max=3.708.

## 11. Online stateful action policy

Window labels describe the last 30 days; stateful labels add the persisted state. FW-check needs ≥90d & ≥30 cycles since the last effective FCC change, repeated no_response or anomaly≥2.0, zero observed responses, and large-gap/censored not dominant. Gauge-reset needs the same staleness but **zero** opportunities (OK or large-gap) plus an AC-bound/shallow/low-cycling usage cluster. Data-quality review outranks any actionable call (spec 16.14). Alerts fire only on a state transition with a cooldown, reset by an effective FCC update (spec 12.6).

## 12. Backtest: stateful vs stateless

- Same-threshold no-response detection (≥2 OK no_response, 0 observed response, OK window) — stateful (cumulative since last effective change): **1**, stateless (last 30d raw only): 1, overlap: 0, **stateful-only gain: 1**. The persisted state recovers no-response evidence spread across >30 days that a single 30-day window cannot hold; the stateless-only set (1) is users who very recently accumulated ≥2 within one window.
- The strict **action** gates (adding ≥90d/≥30-cycle staleness, anomaly, and large-gap protection) deliberately convert far fewer of these into FW=0 / Gauge=1 candidates; the remainder route to WATCH.

## 13. Final-validation label proxy comparison

The final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an **evaluation proxy, not ground truth** (spec 13.2).
Stateful (rows) × final proxy (cols):
```
final_label                     ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  NORMAL_OR_RESPONDING  REVIEW_INSUFFICIENT_DATA  WATCH_LOW_UPDATE_RATE_AMBIGUOUS
stateful_label                                                                                                                                                           
STATEFUL_GAUGE_RESET_CANDIDATE                                                         1                     0                         0                                0
STATEFUL_NORMAL                                                                        0                     8                        13                                2
STATEFUL_REVIEW                                                                        2                     1                         0                                1
STATEFUL_WATCH                                                                         0                     8                         2                                2
```
Top-N yield:
```
                           score_col                                              proxy_label  N  hits  precision_at_N  recall_at_N  total_proxy_pos
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 10     0            0.00       0.0000                0
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 20     0            0.00       0.0000                0
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 30     0            0.00       0.0000                0
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 50     0            0.00       0.0000                0
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 10     2            0.20       0.6667                3
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 20     3            0.15       1.0000                3
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 30     3            0.10       1.0000                3
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 50     3            0.06       1.0000                3
```

## 14. Active false alert / lead time / top-N

- Active false-alert rate vs `soh_update_status` (any-change basis): 0.0 (0/1). On our 50 mWh-effective basis it is 0.0 (0/1). The difference is definitional: `soh_update_status=active` counts sub-50 mWh micro-wobbles as updates, which the rolling detector intentionally ignores (spec 5.3). Gauge candidates with micro-drift but no full re-learning are still legitimate calibration prompts.
- ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY: alerted 2 cases, median lead time 132d before last observation.

## 15. Large-gap / censored safety audit

- `censored`/`unknown` episodes are never counted as `no_response` (status separation in `_response_status`).
- `large_gap` episodes never count as OK opportunities (quality gate).
- Each episode contributes once to state (keyed by `episode_id`).
- Zero-opportunity windows cannot produce a high anomaly score.

## 16. HW/FW enrichment (post-classification only)

Top FW-candidate enrichment groups (beta-binomial shrunk rate, Fisher+BH):
```
  group_axis          group_value  n_total  n_candidate  raw_rate  shrunk_rate  ci_low  ci_high  fisher_p  q_value  fleet_rate
 batt_vendor                  BYD        5            0       0.0       0.0001     0.0      0.0       1.0      1.0         0.0
 batt_vendor             Celxpert        6            0       0.0       0.0001     0.0      0.0       1.0      1.0         0.0
 batt_vendor                  SMP       11            0       0.0       0.0001     0.0      0.0       1.0      1.0         0.0
 batt_vendor              Sunwoda       11            0       0.0       0.0001     0.0      0.0       1.0      1.0         0.0
device_model ThinkPad X9-14 Gen 1        5            0       0.0       0.0001     0.0      0.0       1.0      1.0         0.0
```
Hardware identity is asserted absent from every classification feature list (`assert_no_hw_in_classification`).

## 17. Latest snapshot action candidates

See `online_fcc_action_candidates_fw_check.csv` (0), `..._gauge_reset.csv` (1), `online_fcc_watchlist.csv` (12), `online_fcc_review_queue.csv` (4).

## 18. Operational recommendations

- Alert only on state transitions with a 30–60d cooldown, reset on FCC recovery.
- Record post-intervention FCC response to close the loop (not available now).
- Collect BIOS/EC/battery-FW version + gauge-reset/update dates to enable version-level enrichment and intervention evaluation.

## 19. Limitations

- This flags *candidates*, not confirmed FW faults. Evidence is mechanistic (opportunity vs response), evaluated against a **proxy** label set.
- HDBSCAN and EBM are unavailable here; clustering uses GaussianMixture/KMeans.
- The 30d raw constraint limits the stateless view; the stateful detector mitigates but assumes faithful long-term state.
- Most episodes are large-gap (sleep gaps), shrinking the clean-opportunity pool.

## 20. Next steps

- Acquire BIOS/EC/battery-FW versions and intervention outcomes.
- Validate the response model on labelled post-intervention recoveries.
- Tune gap/step/window thresholds against operational feedback.