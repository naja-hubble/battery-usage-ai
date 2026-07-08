# OD2 re-analysis - Phase 2: offline triage labels on corrected relearn opportunities

_Cohort 752 users. Classifier = fcc_final.classify_user_final (reused by import), response window **168h**, Type A->strict slot / Type B->primary slot. OD1 files untouched._

## 1. k-threshold re-justification (healthy per-opportunity response @168h)

- **n_active_reference**: 214
- **p_response_80_20_80_168h**: 0.4542
- **n_known_80_20_80**: 18017
- **k_fa05_80_20_80**: 5
- **k_fa10_80_20_80**: 4
- **p_response_90_10_90_168h**: 0.7399
- **n_known_90_10_90**: 173
- **k_fa05_90_10_90**: 3
- **k_fa10_90_10_90**: 2

Re-justified FW thresholds used: primary(Type B) k=5 (medium k=4), strict(Type A) k=3.

## 2. Label distributions (baseline vs OD2)

| label   |   baseline(OD1,72h) |   OD2 old-k(168h) |   OD2 rejustified-k(168h) |
|:--------|--------------------:|------------------:|--------------------------:|
| REVIEW  |                 338 |               338 |                       338 |
| NORMAL  |                 327 |               327 |                       327 |
| FW      |                  14 |                36 |                        35 |
| GAUGE   |                  18 |                10 |                        10 |
| WATCH   |                  55 |                41 |                        42 |

## 3. Transition matrix - baseline (rows) -> OD2 rejustified-k (cols)

| baseline_label   |   REVIEW |   NORMAL |   FW |   GAUGE |   WATCH |
|:-----------------|---------:|---------:|-----:|--------:|--------:|
| REVIEW           |      338 |        0 |    0 |       0 |       0 |
| NORMAL           |        0 |      327 |    0 |       0 |       0 |
| FW               |        0 |        0 |   13 |       1 |       0 |
| GAUGE            |        0 |        0 |    3 |       5 |      10 |
| WATCH            |        0 |        0 |   19 |       4 |      32 |

## 4. Transition matrix - baseline (rows) -> OD2 old-k (cols)

| baseline_label   |   REVIEW |   NORMAL |   FW |   GAUGE |   WATCH |
|:-----------------|---------:|---------:|-----:|--------:|--------:|
| REVIEW           |      338 |        0 |    0 |       0 |       0 |
| NORMAL           |        0 |      327 |    0 |       0 |       0 |
| FW               |        0 |        0 |   13 |       1 |       0 |
| GAUGE            |        0 |        0 |    3 |       5 |      10 |
| WATCH            |        0 |        0 |   20 |       4 |      31 |

## Notes

- Candidate flags (fcc_no_or_low_change_candidate) and REVIEW/NORMAL gates are opportunity-INDEPENDENT, so the re-triage moves users only among FW/GAUGE/WATCH (and REVIEW where data-quality dominates).

- 'GAUGE = insufficient learning opportunity' now means no Type A AND no Type B (union empty). Type B's high frequency shrinks the no-opportunity pool.
