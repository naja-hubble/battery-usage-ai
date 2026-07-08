# OD2 re-analysis - Phase 1: OLD (discharge-band) vs NEW (gauge-relearn) opportunities

_Code version: relearn_od2.0. Cohort: 752 users, battery_timeseries_all.parquet. Response convention (both sides): END-anchored, effective step >=50 mWh, ok-quality, 72h primary window._

> The corrected fuel-gauge relearn logic replaces the OD1 high->low->high discharge bands (80/20/80, 90/10/90, 85/15/85) with two real mechanisms: **Type A** full->RSOC<=6%->full, and **Type B** charging through 60-80% -> full. END = full-charge attainment in both. OD1 files are untouched.

## 1. Episode & response summary (unified END-anchored / 50 mWh convention)

| definition             |   n_episodes |   n_users |   n_ok |   n_users_with_ok |   ok_responded_72h |   ok_no_response_72h |   ok_censored_72h |   ok_response_rate_72h |
|:-----------------------|-------------:|----------:|-------:|------------------:|-------------------:|---------------------:|------------------:|-----------------------:|
| OLD:strict_90_10_90    |         5750 |       517 |    829 |               180 |                328 |                  491 |                10 |                 0.4005 |
| OLD:primary_80_20_80   |        11342 |       598 |   2319 |               294 |                901 |                 1402 |                16 |                 0.3912 |
| OLD:secondary_85_15_85 |         7619 |       551 |   1249 |               218 |                490 |                  748 |                11 |                 0.3958 |
| OD2:typeA              |         3913 |       475 |    408 |               117 |                167 |                  233 |                 8 |                 0.4175 |
| OD2:typeB              |        34578 |       704 |  32228 |               692 |               8497 |                23512 |               219 |                 0.2655 |
| OD2:union              |        36225 |       706 |  30511 |               687 |               7839 |                22463 |               209 |                 0.2587 |

## 2. Per-user opportunity coverage movement (OD1 vs OD2 union)

| cell                                              |   n_users |
|:--------------------------------------------------|----------:|
| old_ok & od2_ok                                   |       290 |
| old_ok & od2_NO                                   |         4 |
| old_NO & od2_ok                                   |       397 |
| old_NO & od2_NO                                   |        61 |
| TOTAL users                                       |       752 |
| users_with_od2_opportunity(any_quality)           |       706 |
| users_with_ZERO_od2_opportunity(gauge_candidates) |        46 |

Users who had NO OD1 opportunity but DO under OD2 are newly auditable; users with ZERO OD2 opportunity are the gauge-reset candidate pool (no relearn chance observed).

## 3. Type A / Type B diagnostics

- **typeB_arm_to_full_h_median**: 1.16
- **typeB_arm_to_full_h_p90**: 11.34
- **typeB_arm_to_full_gt48h_frac**: 0.0198
- **typeB_band_entry_rsoc_median**: 71.0
- **typeA_depth_median**: 95.0
- **typeA_low_rsoc_median**: 5.0
- **typeA_typeB_coincident_END_rows**: 4532
- **pre_end_gap_gt12h_frac**: 0.0323

## 4. Sensitivity grid (one-factor-at-a-time)

| variant    | type   |   n_episodes |   n_users |   n_ok |   ok_response_rate_72h |
|:-----------|:-------|-------------:|----------:|-------:|-----------------------:|
| FULL=97    | typeA  |         3954 |       476 |    418 |                 0.4015 |
| FULL=97    | typeB  |        35603 |       705 |  33523 |                 0.266  |
| FULL=97    | union  |        37303 |       707 |  31811 |                 0.2596 |
| FULL=99    | typeA  |         3913 |       475 |    408 |                 0.4175 |
| FULL=99    | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| FULL=99    | union  |        36225 |       706 |  30511 |                 0.2587 |
| FULL=100   | typeA  |         3843 |       471 |    389 |                 0.4173 |
| FULL=100   | typeB  |        33531 |       703 |  31036 |                 0.2634 |
| FULL=100   | union  |        35102 |       704 |  29306 |                 0.256  |
| DEEP=4     | typeA  |         2522 |       417 |    203 |                 0.41   |
| DEEP=4     | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| DEEP=4     | union  |        35616 |       706 |  31033 |                 0.26   |
| DEEP=6     | typeA  |         3913 |       475 |    408 |                 0.4175 |
| DEEP=6     | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| DEEP=6     | union  |        36225 |       706 |  30511 |                 0.2587 |
| DEEP=8     | typeA  |         4689 |       502 |    549 |                 0.4241 |
| DEEP=8     | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| DEEP=8     | union  |        36573 |       706 |  30248 |                 0.2574 |
| DEEP=10    | typeA  |         5486 |       514 |    746 |                 0.4185 |
| DEEP=10    | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| DEEP=10    | union  |        36878 |       706 |  29978 |                 0.2561 |
| BAND=55-80 | typeA  |         3913 |       475 |    408 |                 0.4175 |
| BAND=55-80 | typeB  |        37798 |       704 |  35085 |                 0.2701 |
| BAND=55-80 | union  |        39164 |       706 |  33125 |                 0.2631 |
| BAND=60-80 | typeA  |         3913 |       475 |    408 |                 0.4175 |
| BAND=60-80 | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| BAND=60-80 | union  |        36225 |       706 |  30511 |                 0.2587 |
| BAND=60-85 | typeA  |         3913 |       475 |    408 |                 0.4175 |
| BAND=60-85 | typeB  |        44210 |       713 |  41400 |                 0.257  |
| BAND=60-85 | union  |        45541 |       715 |  39376 |                 0.2501 |
| ABORT=50   | typeA  |         3913 |       475 |    408 |                 0.4175 |
| ABORT=50   | typeB  |        34931 |       704 |  32282 |                 0.2653 |
| ABORT=50   | union  |        36559 |       706 |  30571 |                 0.2585 |
| ABORT=60   | typeA  |         3913 |       475 |    408 |                 0.4175 |
| ABORT=60   | typeB  |        34578 |       704 |  32228 |                 0.2655 |
| ABORT=60   | union  |        36225 |       706 |  30511 |                 0.2587 |

## Notes / caveats

- OLD-side response rates are recomputed END-anchored/50 mWh (NOT the production START-anchored/any-change 71.5%), so old vs new is comparable.

- Type B has no discharge low; `low_ts`/`low_rsoc` = band-entry (arming) sample.

- `union` de-duplicates coincident A/B ENDs (audited once). Per-type rows are descriptive.
