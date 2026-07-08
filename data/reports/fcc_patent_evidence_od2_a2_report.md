# OD2 Phase 4 (MVP) - A2 negative controls per mechanism

_Code patent_evidence_od2.0. Primary window 168h. Acceptance: TRUE resp_prob_168h outside the 95% null (greater) for >=2 of 4 cheap controls AND directionally supported (user-bootstrap lower CI > control null mean) for >=2._

> The decisive test: does each mechanism's true END-anchored effective-response probability beat its OWN mechanism-specific negative-control null? Type A is expected strong; Type B (charge-side) is the crux - its pooled 72h response sits near the OD1 null.

## Acceptance by mechanism

| mechanism   |   n_anchors |   n_users |   true_resp_168h |   true_resp_72h |   boot_lo_168h | null_mean_168h   | outside_null   | directional   | SUPPORTED   |
|:------------|------------:|----------:|-----------------:|----------------:|---------------:|:-----------------|:---------------|:--------------|:------------|
| A           |         388 |       108 |          0.6366  |         0.40979 |        0.5323  | 0.41703..0.5359  | 4/4            | 3/4           | True        |
| B           |       31543 |       674 |          0.36835 |         0.2645  |        0.32103 | 0.1808..0.29396  | 4/4            | 4/4           | True        |
| union       |       29868 |       670 |          0.35891 |         0.25767 |        0.31287 | 0.19957..0.28917 | 4/4            | 4/4           | True        |

## Interpretation

- **SUPPORTED** = the mechanism is a real learning stimulus (effect specific to the true opportunity END, not elapsed time / step density).

- If **Type B is NOT SUPPORTED**, the charge-side band traversal adds no stimulus and the invention reduces to Type A + full-charge END anchoring; the OD2 offline FW labels (which lean on Type B counts) would then need a Type-A-only variant.

- Full detail per control in `negative_control_summary_od2.csv`.
