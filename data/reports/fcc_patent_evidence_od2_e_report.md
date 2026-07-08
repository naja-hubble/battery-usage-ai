# OD2 Phase 4 - E missingness / censor stress (per mechanism)

_Dense users; inject MCAR / contiguous-gap / sleep-gap / truncation regimes; compare four detectors' FALSE confirmed no-response vs the clean reference. Truth = `proposed` on clean OD2 relearn ENDs at the **168h** primary window; truncation extended to (168h, 336h). Censored/unknown are NEVER no-response._

> IC6: the `proposed` detector should emit far fewer FALSE confirmed no-response episodes than `naive` under injection, while keeping recovery. `union` is the headline (OD1 baseline: naive ~643 -> proposed ~4.1).

## Headline per mechanism (mean false no-response across regimes)

| mechanism   |   n_clean_ends |   naive_false_no_response |   proposed_false_no_response |   reduction |   proposed_recovery | IC6_supported   |
|:------------|---------------:|--------------------------:|-----------------------------:|------------:|--------------------:|:----------------|
| A           |            624 |                   246.611 |                        0.333 |     246.278 |              0.937  | True            |
| B           |           6122 |                    49.533 |                        2.589 |      46.944 |              0.9573 | True            |
| union       |           6344 |                   203.704 |                        5.007 |     198.696 |              0.9602 | True            |


## Per-detector per-regime (union)

| regime                  |   naive |   binary_gap_gate |   graded |   proposed |
|:------------------------|--------:|------------------:|---------:|-----------:|
| gap_12h_around_low      |  210.73 |             17.2  |    18.2  |       0.27 |
| gap_24h_after_end       |  213.53 |             16.93 |    18    |       0.13 |
| gap_24h_around_deadline |  211.4  |             17.2  |    18.2  |       0.2  |
| gap_24h_around_low      |  211    |             17.07 |    18.07 |       0.07 |
| gap_24h_high_to_low     |  210.93 |             17    |    18    |       0.07 |
| gap_24h_low_to_high     |  210.93 |             17    |    18    |       0    |
| gap_3h_around_low       |  210.87 |             17.27 |    18.27 |       0.33 |
| gap_48h_around_low      |  210.27 |             16.93 |    17.93 |       0.2  |
| gap_6h_around_low       |  211    |             17.13 |    18.13 |       0.13 |
| mcar_10pct              |  207.6  |             20.73 |    22.2  |       5.2  |
| mcar_20pct              |  202.53 |             24.6  |    27.13 |      12.27 |
| mcar_30pct              |  193.47 |             29    |    32.4  |      17.87 |
| mcar_50pct              |  176    |             29.4  |    35.33 |      24.27 |
| mcar_5pct               |  208.47 |             18.07 |    19.67 |       2.27 |
| sleepgaps_fleet         |  188    |             32.87 |    37.07 |      26.8  |
| truncate_168h           |  191    |              2    |     2    |       0    |
| truncate_336h           |  188    |              1    |     1    |       0    |
