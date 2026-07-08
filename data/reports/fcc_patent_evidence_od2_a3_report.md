# OD2 Phase 4 - A3 response-anchor contamination per mechanism

_Code patent_evidence_od2_a3.0. Contamination = fraction of counted effective (>=50 mWh) FCC response steps in [anchor, anchor+W] whose timestamp is STRICTLY BEFORE the episode END (recharge completion) -- a step during the charge/discharge that produced the opportunity, not a response to it. OD2 primary window = 168h; 72h shown for direct OD1 A3 comparison._

> Anchors per mechanism: **Type A** = start (opening full) / low (deep sample) / end (full re-attainment); **Type B** = arm (= start = low, band entry while charging) / end; **union** = end (dedup on coincident ENDs).

## Headline: END anchoring removes contamination for both mechanisms

| mechanism   |   n_ok_episodes | non_end_anchor(s)   |   worst_non_end_contam_168h |   END_contam_168h |   END_contam_72h |   END_dup_rate_168h |
|:------------|----------------:|:--------------------|----------------------------:|------------------:|-----------------:|--------------------:|
| A           |             408 | start,low           |                     0.48507 |                 0 |                0 |             0.19867 |
| B           |           32228 | arm                 |                     0.03405 |                 0 |                0 |             0.65088 |
| union       |           30511 | -                   |                     0       |                 0 |                0 |             0.64007 |

OD1 A3 baseline (72h): END=0.000, START=0.557, LOW=0.270. In OD2, END contamination is structurally ~0 for both mechanisms (an END-anchored window starts AT completion, so no counted step can precede it); the non-END anchors (Type A start/low, Type B arm) recover the same mid-cycle contamination seen in OD1.

## END-anchor duplicate attribution: union dedup vs pooled A+B

_One effective FCC step attributed to >= 2 episodes because their END windows overlap. Union dedup on coincident ENDs removes the cross-mechanism double counting (an A and a B episode closing on the same full-charge END)._

|   window_h |   pooled_AB_duplicate_rate |   pooled_AB_n_duplicate |   pooled_AB_n_total_attr |   union_duplicate_rate |   union_n_duplicate |   union_n_total_attr |   duplicate_attr_removed |   rate_reduction |
|-----------:|---------------------------:|------------------------:|-------------------------:|-----------------------:|--------------------:|---------------------:|-------------------------:|-----------------:|
|         24 |                    0.15103 |                    1336 |                     8846 |                0.14268 |                1151 |                 8067 |                      185 |          0.00835 |
|         72 |                    0.42557 |                    8442 |                    19837 |                0.41301 |                7473 |                18094 |                      969 |          0.01256 |
|        168 |                    0.65605 |                   28260 |                    43076 |                0.64007 |               25257 |                39460 |                     3003 |          0.01598 |

## Full anchor x window grid

| mechanism   | anchor   |   window_h |   n_episodes |   n_episodes_counted |   n_counted_steps |   frac_steps_before_completion |   frac_steps_at_or_before_completion |   duplicate_attribution_rate |   n_duplicate_attr |   n_total_attr |
|:------------|:---------|-----------:|-------------:|---------------------:|------------------:|-------------------------------:|-------------------------------------:|-----------------------------:|-------------------:|---------------:|
| A           | start    |         24 |          408 |                  187 |               273 |                        0.92308 |                              0.95238 |                      0.0293  |                  8 |            273 |
| A           | start    |         72 |          408 |                  263 |               557 |                        0.68941 |                              0.71813 |                      0.10054 |                 56 |            557 |
| A           | start    |        168 |          408 |                  302 |               971 |                        0.48507 |                              0.50875 |                      0.17508 |                170 |            971 |
| A           | low      |         24 |          408 |                  267 |               375 |                        0.672   |                              0.74667 |                      0.05333 |                 20 |            375 |
| A           | low      |         72 |          408 |                  285 |               554 |                        0.45487 |                              0.50722 |                      0.14079 |                 78 |            554 |
| A           | low      |        168 |          408 |                  309 |               974 |                        0.25873 |                              0.2885  |                      0.21663 |                211 |            974 |
| A           | end      |         24 |          408 |                  125 |               162 |                        0       |                              0.17901 |                      0.03086 |                  5 |            162 |
| A           | end      |         72 |          408 |                  167 |               320 |                        0       |                              0.09062 |                      0.11875 |                 38 |            320 |
| A           | end      |        168 |          408 |                  258 |               750 |                        0       |                              0.03867 |                      0.19867 |                149 |            750 |
| B           | arm      |         24 |        32228 |                 5926 |              9317 |                        0.1567  |                              0.27895 |                      0.15305 |               1426 |           9317 |
| B           | arm      |         72 |        32228 |                 8573 |             20333 |                        0.0718  |                              0.12792 |                      0.42674 |               8677 |          20333 |
| B           | arm      |        168 |        32228 |                11816 |             42877 |                        0.03405 |                              0.06069 |                      0.65317 |              28006 |          42877 |
| B           | end      |         24 |        32228 |                 5708 |              8684 |                        0       |                              0.13151 |                      0.1421  |               1234 |           8684 |
| B           | end      |         72 |        32228 |                 8497 |             19517 |                        0       |                              0.05851 |                      0.41881 |               8174 |          19517 |
| B           | end      |        168 |        32228 |                11808 |             42326 |                        0       |                              0.02698 |                      0.65088 |              27549 |          42326 |
| union       | end      |         24 |        30511 |                 5290 |              8067 |                        0       |                              0.13301 |                      0.14268 |               1151 |           8067 |
| union       | end      |         72 |        30511 |                 7839 |             18094 |                        0       |                              0.0593  |                      0.41301 |               7473 |          18094 |
| union       | end      |        168 |        30511 |                10893 |             39460 |                        0       |                              0.02719 |                      0.64007 |              25257 |          39460 |

## Notes

- Charge-termination anchor is **NOT AVAILABLE** (no per-sample charge-current / voltage-taper telemetry); END is its operational proxy. Reported, not fabricated.

- Type B arm-anchor contamination quantifies the leakage that a band-entry-anchored response audit would suffer: charge-side steps between band entry and full charge would be miscounted as responses. END anchoring is required for Type B specifically.

- CSVs: `response_anchor_comparison_od2.csv`, `response_anchor_contamination_bootstrap_od2.csv`, `response_anchor_duplicate_od2.csv`, `response_anchor_charge_termination_status_od2.csv`.
