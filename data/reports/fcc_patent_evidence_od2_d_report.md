# OD2 Phase 4 - pillar D: bounded-retention invariance (UNION ledger, rw=168h primary)

_Reference ledger = OD2 union-primary opportunities (Type A deep-discharge + Type B charge-side, END = full-charge attainment); reference response status = the 168h status. Stateful verifier runs both mechanism FSMs in parallel with END dedup on `end_ns`. Technical evidence for patent review - NOT legal advice._

Cohort: 752 users, median span 172.92d, 8806 reference ENDs over 752 users (verified subset).

## Claim (a): bounded stateful == unbounded at W=30d / rw=168h

> Since 168h = 7d < 30d, keeping the last 30 days of raw plus a small persistent causal state reproduces the full-history UNION detector exactly.

| config                                                                     |   stateful_recall |   stateful_episode_id_symmetric_diff |   stateful_duplicate_count |   stateful_no_response_mae |   n_users_verified |   n_reference_ends |   peak_pending_per_user_max |   peak_pending_per_user_mean |
|:---------------------------------------------------------------------------|------------------:|-------------------------------------:|---------------------------:|---------------------------:|-------------------:|-------------------:|----------------------------:|-----------------------------:|
| bounded W=30d stride=7d vs full-retention, rw=168h gap=ok_only (UNION A+B) |                 1 |                                    0 |                          0 |                          0 |                200 |               8806 |                          11 |                        3.555 |

OD1 baseline: recall 1.0 / dup 0 / no_response MAE ~0.02 (rw=72h). OD2: recall 1.0 / dup 0 / symdiff 0 / no_response MAE 0.0 (rw=168h, UNION A+B).

## Claim (b): stateless degrades at rw=168h vs rw=72h (7d retention)

- response-status agreement @7d: 168h = **0.0107** vs 72h = **0.766**

- response resolvable rate @7d: 168h = **0.0** vs 72h = **0.7602**

- physical-episode recall @7d (rw-independent) = 0.9782, duplicate rate @7d/168h = 2.8727

|   retention_days |   response_window_h |   recall |   resolvable_rate |   response_agreement |   no_response_mae |   storage_ratio |
|-----------------:|--------------------:|---------:|------------------:|---------------------:|------------------:|----------------:|
|                7 |                  24 | 0.9824   |          0.909621 |            0.911829  |        2.29819    |          0.0405 |
|                7 |                  72 | 0.9824   |          0.764764 |            0.770507  |        6.28216    |          0.0405 |
|                7 |                 168 | 0.9824   |          0        |            0.0108429 |       27.8719     |          0.0405 |
|               14 |                  24 | 0.993621 |          0.99055  |            0.99275   |        0.0144429  |          0.081  |
|               14 |                  72 | 0.993621 |          0.984571 |            0.990321  |        0.04045    |          0.081  |
|               14 |                 168 | 0.993621 |          0.961607 |            0.972429  |        0.464043   |          0.081  |
|               30 |                  24 | 0.994157 |          0.991186 |            0.993393  |        0.00563571 |          0.1735 |
|               30 |                  72 | 0.994157 |          0.985429 |            0.991164  |        0.0296143  |          0.1735 |
|               30 |                 168 | 0.994157 |          0.972971 |            0.983807  |        0.166057   |          0.1735 |

## Claim (c): storage / compute tradeoff (Type B pending density)

- stateful storage ratio @7d = **0.0417** (OD1 baseline 0.0417); well under 0.1.

- peak pending-queue depth per user: max 11, mean 3.555 (Type B enlarges the queue; folded into `stateful_storage_ratio_od2_pending`).

|   retention_days |   stateless_storage_ratio |   stateful_storage_ratio |   stateful_storage_ratio_od2_pending |   state_bytes_per_user |   pending_bytes_per_user_peak |   raw_bytes_total |
|-----------------:|--------------------------:|-------------------------:|-------------------------------------:|-----------------------:|------------------------------:|------------------:|
|                7 |                    0.0405 |                   0.0417 |                               0.0433 |                     65 |                            88 |       4.05007e+07 |
|               14 |                    0.081  |                   0.0822 |                               0.0838 |                     65 |                            88 |       4.05007e+07 |
|               21 |                    0.1214 |                   0.1227 |                               0.1243 |                     65 |                            88 |       4.05007e+07 |
|               30 |                    0.1735 |                   0.1747 |                               0.1763 |                     65 |                            88 |       4.05007e+07 |
|               45 |                    0.2602 |                   0.2614 |                               0.2631 |                     65 |                            88 |       4.05007e+07 |
|               60 |                    0.347  |                   0.3482 |                               0.3498 |                     65 |                            88 |       4.05007e+07 |
|               90 |                    0.5205 |                   0.5217 |                               0.5233 |                     65 |                            88 |       4.05007e+07 |

## Verdict

- IC5 bounded-retention causal-equivalence at rw=168h: **MET** (min equivalent stateful storage ratio 0.0417).

- Grid configs evaluated: 1176. Runtime 43.28s.
