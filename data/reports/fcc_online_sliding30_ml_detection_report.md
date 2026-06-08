# 30-day Sliding-Window FCC Learning/Response ML Detection — Report

*Generated 2026-06-08T06:25:28Z · code `rolling30-v1.0` · window=30d stride=1d effective-step=`abs_ge_50mWh` response-window=72h episode-max-gap=12.0h*

## 1. Executive summary

- Cohort: **752 users**, 3,130,394 raw samples, 200,059 user-windows at stride=1d.
- Latest-snapshot stateful labels: **STATEFUL_NORMAL**=439, **STATEFUL_REVIEW**=166, **STATEFUL_WATCH**=99, **STATEFUL_GAUGE_RESET_CANDIDATE**=45, **STATEFUL_FW_CHECK_CANDIDATE**=3.
- Episode response model (`hgb`, GroupKFold by user): ROC AUC **0.8028**, PR AUC 0.7324, Brier 0.1772 (calibrated 0.1705), calib slope 0.774; positive (response) rate 0.3943.
- Same-threshold detection (≥2 no_response, 0 response, OK window): stateful=24, stateless(30d-only)=14, **stateful-only gain=16** (evidence spread beyond 30 days). Strict action gate yields FW=3, Gauge=45.
- Active false-alert rate vs `soh_update_status` (any-change): 0.7083 (34/48); but by our 50 mWh-effective definition it is **0.0** (0/48) — the gap is the any-change vs effective-step definition, not a wrong call.

## 2. The 30-day constraint and the design change

Raw telemetry is assumed retained for only the trailing 30 days; the window slides daily (`[t-29,t]` -> `[t-28,t+1]`). The detector therefore separates a **stateless** view (the 30d raw window only) from a **stateful** online detector whose *derived* state (counters since the last effective FCC change, pending/censored episodes) may persist long-term. Every inference point uses only the trailing raw window plus state updated up to that point — no future raw, no raw older than 30 days, no look-ahead at final labels (spec 0.3 / 13.1).

## 3. Why direct very_stale prediction is inappropriate

Prior supervised work (PROJECT_STATUS.md) showed that predicting `very_stale` directly from usage behaviour reaches only AUC≈0.54 in the fair (obs≥180d) regime — essentially random. So we do **not** classify `30d usage -> FW fault`. Instead we estimate, per learning episode, the probability a healthy gauge would respond, and flag users/windows whose **observed** responses fall far below that **expected** response given real high→low→high opportunities (spec 0.2).

## 4. Data and variables

- `fullChargeCapacity` is integer **mWh** (PROJECT_STATUS PDF correction); SoH steps iff FCC steps. `remainingCapacityInPercentage` = RSOC. `acdcMode` 1=AC/0=DC. Design capacity recovered per user from `FCC*100/soh_design_pct` (median).
- Episode quality distribution (all bands): {'large_gap': 20314, 'ok': 4397}. Large-gap dominance reflects multi-hour sleep gaps inside otherwise full-range discharges; these are protected out of OK opportunities.

## 5. Rolling window features

One row per `user_id × window_end_date` with data-quality (n_samples, gaps, counter reset), usage (cycle delta/rate, AC/charge/discharge time ratios, RSOC levels & band fractions, switch and discharge-session counts) and FCC (start/end/min/max, any vs effective changes, last effective change ts/cycle) blocks. Time-weighted ratios use capped gap-to-next weights.

## 6. Episode / stateful detector

High→low→high RSOC excursions are detected for 3 bands (80/20, 85/15, 90/10). Response is **end-anchored**: an effective FCC step in `[end, end+72h]` is a response (spec 7.4). The online state replays events in time order: an effective FCC step **resets** the since-last-change counters and clears the pending set (those episodes just responded); a pending OK episode whose 72h window closes with no step becomes a confirmed **no_response**. Each episode is keyed by a stable `episode_id` so overlapping windows never double-count it (spec 7.5).

## 7. Effective FCC step definition and sensitivity

```
      effective_step  n_ok_complete_primary  n_responded  n_no_response  n_censored  response_rate
          any_change                   2309         1446            863          10         0.6262
        abs_ge_50mWh                   2303          901           1402          16         0.3912
       abs_ge_100mWh                   2303          827           1476          16         0.3591
abs_ge_0p1pct_design                   2303          863           1440          16         0.3747
abs_ge_0p5pct_design                   2300          705           1595          19         0.3065
```
Default `abs_ge_50mWh` avoids counting micro-wobbles (~58% of raw steps are <50 mWh) as learning responses, which would mask genuine no-response (spec 5.3).
Episode-gap sensitivity (6/12/24h):
```
 episode_max_gap_hours  n_ok  n_large_gap  ok_fraction
                   6.0   895        10447       0.0789
                  12.0  2319         9023       0.2045
                  24.0  5050         6292       0.4452
```
Response-window sensitivity (24/72/168h):
```
 response_window_hours  n_responded  n_no_response  n_censored  response_rate_complete
                    24          574           1734          11                  0.2487
                    72          901           1402          16                  0.3912
                   168         1338            959          22                  0.5825
```

## 8. Unsupervised usage clustering

```
 cluster_id  n_windows  n_users  median_ac_time_ratio  median_rsoc_swing  median_cycle_delta  share_no_response          cluster_profile_name suggested_action_hint
          0      60836      541                0.7365               90.0                 7.0                NaN           LARGE_GAP_AMBIGUOUS            watch_hint
          1      49596      546                0.8651               52.0                 3.0                NaN                      AC_BOUND      gauge_reset_hint
          2      28302      287                0.5747               97.0                14.0           0.617807 MOBILE_DEEP_CYCLE_NO_RESPONSE         fw_check_hint
          3       9817       70                0.8081               54.0                 3.0                NaN                      AC_BOUND      gauge_reset_hint
          4      15426      524                0.6128               94.0                 5.0                NaN           LARGE_GAP_AMBIGUOUS            watch_hint
          5       3051       97                0.7096               85.0                10.0           0.648680           LARGE_GAP_AMBIGUOUS            watch_hint
```

## 9. Self-supervised episode response model

```
   model  n_episodes  n_users  positive_rate  roc_auc  pr_auc  brier  brier_calibrated  calib_slope  tp@0.5  fp@0.5  tn@0.5  fn@0.5  tp@0.7  fp@0.7  tn@0.7  fn@0.7  tp@0.9  fp@0.9  tn@0.9  fn@0.9
  logreg        4360      290         0.3943   0.7891  0.7234 0.1843            0.1757        0.828    1141     698    1943     578     645     164    2477    1074     393      37    2604    1326
     hgb        4360      290         0.3943   0.8028  0.7324 0.1772            0.1705        0.774     925     463    2178     794     591     149    2492    1128     317      25    2616    1402
lightgbm        4360      290         0.3943   0.8018  0.7317 0.1755            0.1698        0.838     913     456    2185     806     564     121    2520    1155     299      20    2621    1420
```
Top features:
```
                                        feature  weight  weight_std                kind
recent_30d_fcc_effective_changes_before_episode 0.29214     0.00699 permutation_roc_auc
          recent_30d_cycle_delta_before_episode 0.03922     0.00217 permutation_roc_auc
                     cycle_count_before_episode 0.03255     0.00121 permutation_roc_auc
                             soh_before_episode 0.02739     0.00168 permutation_roc_auc
                             fcc_before_episode 0.02050     0.00064 permutation_roc_auc
                              max_gap_h_episode 0.01643     0.00073 permutation_roc_auc
             recent_30d_ac_ratio_before_episode 0.01251     0.00085 permutation_roc_auc
                                       end_rsoc 0.01050     0.00059 permutation_roc_auc
            recent_30d_max_gap_h_before_episode 0.01044     0.00035 permutation_roc_auc
                             episode_duration_h 0.00832     0.00039 permutation_roc_auc
                              n_samples_episode 0.00823     0.00058 permutation_roc_auc
            recent_30d_n_samples_before_episode 0.00727     0.00040 permutation_roc_auc
```
Leakage guards asserted: no hardware identity, no future FCC/response, no final label, GroupKFold by user_id (29-day-overlapping windows never split).

## 10. User-window anomaly scores

Per window: `expected_response_30d = Σ p_i`, `observed_response_30d`, `p_all_no_response_30d = Π(1-clip(p_i))` over **resolved-by-t** OK primary opportunities, `fw_response_anomaly_score_30d = -log10(p_all_no_response)`, and an empirical `conformal_p` vs clean OK windows. Zero-opportunity windows get score 0 (no spurious anomaly, spec 16.15).
Score distribution over scored windows (n=27,493): p50=0.291, p90=1.940, p99=6.000, max=12.000.

## 11. Online stateful action policy

Window labels describe the last 30 days; stateful labels add the persisted state. FW-check needs ≥90d & ≥30 cycles since the last effective FCC change, repeated no_response or anomaly≥2.0, zero observed responses, and large-gap/censored not dominant. Gauge-reset needs the same staleness but **zero** opportunities (OK or large-gap) plus an AC-bound/shallow/low-cycling usage cluster. Data-quality review outranks any actionable call (spec 16.14). Alerts fire only on a state transition with a cooldown, reset by an effective FCC update (spec 12.6).

## 12. Backtest: stateful vs stateless

- Same-threshold no-response detection (≥2 OK no_response, 0 observed response, OK window) — stateful (cumulative since last effective change): **24**, stateless (last 30d raw only): 14, overlap: 8, **stateful-only gain: 16**. The persisted state recovers no-response evidence spread across >30 days that a single 30-day window cannot hold; the stateless-only set (6) is users who very recently accumulated ≥2 within one window.
- The strict **action** gates (adding ≥90d/≥30-cycle staleness, anomaly, and large-gap protection) deliberately convert far fewer of these into FW=3 / Gauge=45 candidates; the remainder route to WATCH.

## 13. Final-validation label proxy comparison

The final-validation labels (FW=14, Gauge=18, Watch=55, Normal=327, Review=338) are an **evaluation proxy, not ground truth** (spec 13.2).
Stateful (rows) × final proxy (cols):
```
final_label                     ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE  ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY  NORMAL_OR_RESPONDING  REVIEW_INSUFFICIENT_DATA  WATCH_LOW_UPDATE_RATE_AMBIGUOUS
stateful_label                                                                                                                                                                                                        
STATEFUL_FW_CHECK_CANDIDATE                                               3                                                         0                     0                         0                                0
STATEFUL_GAUGE_RESET_CANDIDATE                                            0                                                         7                    25                        12                                1
STATEFUL_NORMAL                                                           0                                                         1                   181                       247                               10
STATEFUL_REVIEW                                                           3                                                        10                    81                        52                               20
STATEFUL_WATCH                                                            8                                                         0                    40                        27                               24
```
Top-N yield:
```
                           score_col                                              proxy_label  N  hits  precision_at_N  recall_at_N  total_proxy_pos
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 10     2          0.2000       0.1429               14
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 20     5          0.2500       0.3571               14
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 30     6          0.2000       0.4286               14
       cum_fw_response_anomaly_score              ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE 50    11          0.2200       0.7857               14
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 10     0          0.0000       0.0000               18
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 20     1          0.0500       0.0556               18
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 30     1          0.0333       0.0556               18
days_since_last_effective_fcc_change ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY 50     5          0.1000       0.2778               18
```

## 14. Active false alert / lead time / top-N

- Active false-alert rate vs `soh_update_status` (any-change basis): 0.7083 (34/48). On our 50 mWh-effective basis it is 0.0 (0/48). The difference is definitional: `soh_update_status=active` counts sub-50 mWh micro-wobbles as updates, which the rolling detector intentionally ignores (spec 5.3). Gauge candidates with micro-drift but no full re-learning are still legitimate calibration prompts.
- ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE: alerted 4 cases, median lead time 83d before last observation.
- ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY: alerted 12 cases, median lead time 172d before last observation.

## 15. Large-gap / censored safety audit

- `censored`/`unknown` episodes are never counted as `no_response` (status separation in `_response_status`).
- `large_gap` episodes never count as OK opportunities (quality gate).
- Each episode contributes once to state (keyed by `episode_id`).
- Zero-opportunity windows cannot produce a high anomaly score.

## 16. HW/FW enrichment (post-classification only)

Top FW-candidate enrichment groups (beta-binomial shrunk rate, Fisher+BH):
```
group_axis     group_value  n_total  n_candidate  raw_rate  shrunk_rate  ci_low  ci_high  fisher_p  q_value  fleet_rate
  batt_fru      5B10W13975       26            1    0.0385       0.0204  0.0006   0.0724   0.03562      1.0      0.0014
  batt_fru        L24B4PE2        6            0    0.0000       0.0016  0.0000   0.0180   1.00000      1.0      0.0014
  batt_fru      5B11H56407        6            0    0.0000       0.0016  0.0000   0.0180   1.00000      1.0      0.0014
  batt_fru LNV-5B11M90101@        6            0    0.0000       0.0016  0.0000   0.0180   1.00000      1.0      0.0014
  batt_fru      5B11M90164        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B10W51875        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B10W51883        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11M90171        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11M90125        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11M90169        6            0    0.0000       0.0016  0.0000   0.0180   1.00000      1.0      0.0014
  batt_fru      5B11M90106        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11H56397        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11H56401        6            0    0.0000       0.0016  0.0000   0.0180   1.00000      1.0      0.0014
  batt_fru      5B11H56412        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
  batt_fru      5B11H56406        5            0    0.0000       0.0016  0.0000   0.0186   1.00000      1.0      0.0014
```
Hardware identity is asserted absent from every classification feature list (`assert_no_hw_in_classification`).

## 17. Latest snapshot action candidates

See `online_fcc_action_candidates_fw_check.csv` (3), `..._gauge_reset.csv` (45), `online_fcc_watchlist.csv` (99), `online_fcc_review_queue.csv` (166).

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