# Claude Code Prompt — FCC Patent Evidence v4 Completion

## 0. Role and objective

You are working in the existing `battery-usage-ai` repository as a senior battery diagnostics engineer, causal time-series scientist, Python engineer, and patent-evidence analyst.

The v3 technical-evidence package has already been completed and MUST remain intact. Your task is to complete the analyses that v3 explicitly marked `PENDING`, correct any overstatement in the current evidence narrative, and generate a v4 evidence package suitable for review by patent counsel.

This is **technical evidence for patent review, not a legal patentability opinion**. Do not fabricate ground truth, intervention outcomes, firmware versions, or causal conclusions.

Primary technical thesis to test:

> A host-side system can reconstruct qualified battery-gauge learning opportunities from telemetry, assess effective FCC response after the physical opportunity ends, distinguish lack of opportunity from opportunity-with-no-response, and preserve equivalent diagnostic evidence under bounded raw-data retention by maintaining a minimal causal event ledger.

Secondary thesis:

> Separating any FCC change from an effective FCC change with asymmetric reset semantics prevents micro-wobble from erasing unresolved learning-response evidence and allows hard-reset and soft-calibration actions to be separated.

## 1. Existing inputs

Read and preserve the following existing materials before coding:

- `PROJECT_STATUS.md`
- `data/processed/battery_timeseries_all.parquet`
- all production full-history FCC outputs
- all `data/processed/fcc_online_v2/` outputs
- `data/reports/fcc_final_learning_action_report.md`
- `data/reports/fcc_online_sliding30_v2_report.md`
- `data/reports/fcc_patent_evidence_v3_report.md`
- `data/reports/fcc_invention_disclosure_v3.md`
- `data/processed/fcc_patent_evidence_v3/`
- v3 claim-support and prior-art matrices
- all existing tests related to `fcc_learning`, `fcc_final`, `fcc_online`, and patent evidence

Run a baseline gate first. Abort all substantive conclusions if any expected baseline count differs.

Expected full-history counts:

- users = 752
- no/low candidate = 96
- Gauge = 18
- FW = 14
- Watch = 55
- Review = 338
- Normal = 327

Expected rolling-v2 current snapshot counts:

- REVIEW_DATA_QUALITY = 325
- NORMAL_RESPONDING = 183
- WATCH_LARGE_GAP_OR_CENSORED = 128
- FW_WATCH_HIGH_ANOMALY = 43
- WATCH_LOW_EVIDENCE = 35
- GAUGE_SOFT_CALIBRATION = 22
- GAUGE_REVIEW = 7
- FW_CHECK_CORE = 5
- GAUGE_RESET_CORE = 4

## 2. Non-negotiable causal and leakage constraints

1. At inference time `t`, only raw samples with timestamp `<= t` and state resolved at `<= t` may be used.
2. A response is anchored to `episode_end`, never to episode start unless explicitly used as a comparator in the anchor experiment.
3. `censored` and `unknown` must never be counted as `no_response`.
4. `LOW_LARGE_GAP` must never be counted as confirmed no-response evidence.
5. Overlapping rolling windows must not count the same physical episode more than once.
6. Hardware identity fields and final/proxy labels must not enter individual-level detector features or policy rules.
7. Final/proxy labels may be used only for descriptive comparison, never as training truth or causal truth.
8. Do not call a flagged user a confirmed fault.
9. Do not describe A6 precision/recall=1 as independent validation; it is the production reference and therefore tautological.
10. All uncertainty intervals involving users must bootstrap by user, not by episode.

## 3. Required new modules and CLIs

Implement additively. Preserve v1/v2/v3 modules and tests.

Suggested new modules:

- `battery_usage/patent_negative_controls.py`
- `battery_usage/patent_anchor_analysis.py`
- `battery_usage/patent_response_hazard.py`
- `battery_usage/patent_retention_invariance.py`
- `battery_usage/patent_state_minimality.py`
- `battery_usage/patent_missingness_stress.py`
- `battery_usage/patent_dual_track_ablation.py`
- `battery_usage/patent_effective_threshold.py`
- `battery_usage/patent_evidence_v4.py`
- `battery_usage/patent_reporting_v4.py`

New CLI:

```bash
python analyze_fcc_patent_evidence_v4.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --full-history-dir data/processed \
  --online-v2-dir data/processed/fcc_online_v2 \
  --v3-dir data/processed/fcc_patent_evidence_v3 \
  --out-dir data/processed/fcc_patent_evidence_v4 \
  --fig-dir data/reports/figures/fcc_patent_evidence_v4 \
  --report data/reports/fcc_patent_evidence_v4_report.md \
  --dpi 300 \
  --random-seed 42
```

Plot CLI if useful:

```bash
python plot_fcc_patent_evidence_v4.py \
  --in-dir data/processed/fcc_patent_evidence_v4 \
  --fig-dir data/reports/figures/fcc_patent_evidence_v4 \
  --dpi 300
```

## 4. Analysis A2 — negative controls and temporal falsification

### 4.1 Purpose

Demonstrate that FCC response is specifically associated with a true qualified learning opportunity and its causal end time, rather than merely with elapsed time, high activity, cycle accumulation, user identity, or the marginal distribution of episode times.

### 4.2 Required negative controls

Implement at least the following controls, preserving per-user marginal structure where applicable:

1. **Circular FCC-step shift within user**
   - shift effective FCC step timestamps by a random offset larger than 7 days and smaller than observation span minus 7 days;
   - wrap circularly;
   - preserve number and magnitudes of FCC steps.

2. **Circular episode shift within user**
   - shift episode end timestamps similarly;
   - preserve episode durations, thresholds, and quality tiers.

3. **Within-user opportunity/response permutation**
   - randomly permute response-event assignments among eligible episode windows for the same user.

4. **Matched pseudo-episode generation**
   - generate pseudo episode-end timestamps matched on user, calendar month, cycle-rate stratum, AC-ratio stratum, and observation availability;
   - pseudo events must not overlap a true qualified episode within a configurable exclusion radius.

5. **RSOC phase-shift control**
   - circularly shift RSOC relative to FCC and cycle signals within user, then re-extract episodes.

Run at least 1,000 replicates for inexpensive controls and at least 200 replicates for expensive raw re-extraction controls. Record runtime.

### 4.3 Metrics

For true and control events calculate:

- response probability within 24h / 72h / 168h;
- effective FCC step rate;
- median response delay among responders;
- number of confirmed no-response episodes;
- number of FW-like and Gauge-like classifications if the control is propagated through the full detector;
- difference and ratio true vs control;
- user-bootstrap 95% percentile CI;
- empirical randomization p-value.

### 4.4 Required outputs

- `negative_control_summary.csv`
- `negative_control_replicates.parquet`
- `negative_control_user_bootstrap.csv`
- `negative_control_detector_impact.csv`
- `negative_control_true_vs_null.png`
- `negative_control_randomization_distribution.png`

### 4.5 Acceptance criterion

Do not claim a stimulus-response technical effect unless the true-event response statistic is outside the 95% null interval for at least two controls and remains directionally consistent under user bootstrap.

## 5. Analysis A3 — response-anchor comparison

### 5.1 Anchors

Compare response windows anchored at:

- episode start;
- low-SOC timestamp;
- episode end (proposed);
- optional charge-termination timestamp if a robust telemetry definition is available.

### 5.2 Leakage/contamination metrics

For each anchor and response window 24h / 72h / 168h calculate:

- fraction of counted FCC steps occurring before physical recharge completion;
- fraction of response steps already visible at the anchor;
- duplicate attribution rate where one FCC step is assigned to multiple episodes;
- confirmed no-response count;
- censored count;
- downstream label changes;
- active/responder protection;
- agreement with full-history end-anchored production logic.

Explicitly define “causal contamination” and calculate it without proxy labels where possible.

### 5.3 Outputs

- `response_anchor_comparison.csv`
- `response_anchor_episode_assignments.parquet`
- `response_anchor_label_transition.csv`
- `response_anchor_contamination.png`
- `response_anchor_delay_cdf.png`

### 5.4 Acceptance criterion

The report must state whether END anchoring provides a measurable technical advantage. If not, downgrade the corresponding claim evidence.

## 6. Analysis B — response hazard and cumulative incidence

### 6.1 Event definition

For each qualified episode, time zero is episode end. Event is first FCC step after end, separately for:

- any-change;
- 20mWh;
- 30mWh;
- 40mWh;
- 50mWh;
- 75mWh;
- 100mWh;
- adaptive effective threshold candidates.

Right-censor at final observed sample or a maximum follow-up horizon, whichever comes first.

### 6.2 Estimation

Produce:

- Kaplan–Meier survival curves for time to first FCC response;
- cumulative incidence / response curves;
- 24h / 72h / 168h / 7d response probabilities;
- curves by opportunity threshold (80/20/80, 85/15/85, 90/10/90);
- curves by gap quality tier;
- true episodes vs matched pseudo episodes;
- user-clustered bootstrap confidence intervals.

Use methods appropriate for repeated episodes within user. At minimum, bootstrap users. Do not treat episodes as independent for CI.

### 6.3 Outputs

- `response_hazard_summary.csv`
- `response_hazard_curves.parquet`
- `response_hazard_true_vs_pseudo.png`
- `response_hazard_by_quality.png`
- `response_hazard_by_threshold.png`

## 7. Analysis C2 — dual-track asymmetric reset ablation

### 7.1 Compare state semantics

Replay the same chronological event stream under:

- D0: any-change only;
- D1: effective-change only;
- D2: dual-track, symmetric reset on any step;
- D3: dual-track, symmetric reset only on effective step;
- D4: proposed dual-track asymmetric reset:
  - micro step resets any-track only;
  - effective state, pending episodes, and no-response evidence remain;
- D5: adaptive-threshold asymmetric reset.

### 7.2 Metrics

- pending opportunities erased by micro step;
- confirmed no-response evidence erased;
- users moved from FW-like to Normal/Gauge by micro reset;
- users moved from Gauge Core to Soft;
- hard calibration prompts;
- false hard-reset proxy count;
- responder protection;
- state transition count;
- label stability under threshold sweep.

Do not use production labels as the only outcome. Include direct state-machine effects.

### 7.3 Outputs

- `dual_track_reset_ablation.csv`
- `dual_track_erased_evidence_events.parquet`
- `dual_track_label_transitions.csv`
- `dual_track_reset_semantics.png`
- `dual_track_erased_evidence.png`

### 7.4 Acceptance criterion

IC2 “asymmetric reset” must be downgraded if D4 does not measurably preserve unresolved evidence or reduce hard-action ambiguity relative to symmetric alternatives.

## 8. Analysis C3 — data-driven effective threshold

### 8.1 Threshold candidates

Evaluate:

- fixed 10 / 20 / 30 / 40 / 50 / 75 / 100 / 150mWh;
- 0.05 / 0.1 / 0.2 / 0.5% DesignCapacity;
- `k × quantization_unit`, k = 2..10;
- per-device or per-user noise percentile;
- hybrid `max(k*quantization, alpha*DesignCapacity, noise_percentile)`.

### 8.2 Distribution modeling

Fit and compare where valid:

- finite mixture model on log step magnitude;
- change-point / elbow detection;
- valley detection between micro and macro modes;
- robust empirical quantile approach.

Assess stability by bootstrap user and by vendor/model only as post-hoc descriptive strata, never as classification inputs.

Also test whether a small step is physically/temporally consistent with micro-wobble rather than meaningful relearning:

- persistence of the new FCC value for 6h / 24h / 72h;
- probability of full or partial reversal within 6h / 24h / 72h;
- repeated oscillation between adjacent quantized FCC values;
- association with a qualified opportunity end;
- association with charge-status transition or full-charge completion;
- consistency with derived SoH and remaining-capacity fields;
- step magnitude normalized by DesignCapacity.

Do not call sub-threshold steps noise unless the persistence/reversal analysis supports that description. Use “micro-step” otherwise.

### 8.3 Technical-effect curves

For every candidate threshold calculate:

- fraction of steps classified micro;
- users with no effective step;
- Gauge Core/Soft counts;
- FW Core/Watch counts;
- evidence erased/preserved under dual-track replay;
- label Jaccard;
- bootstrap CI;
- sensitivity by design capacity band.

### 8.4 Outputs

- `effective_threshold_model_selection.csv`
- `effective_threshold_bootstrap.csv`
- `effective_threshold_label_sensitivity.csv`
- `effective_threshold_mixture_fit.png`
- `effective_threshold_technical_effect_curve.png`

### 8.5 Claim drafting note

Generate a machine-readable recommendation distinguishing:

- narrow fallback: fixed 50mWh;
- medium scope: threshold above gauge quantization/noise band;
- broad preferred scope: adaptive threshold based on quantization, design capacity, and observed noise.

## 9. Analysis D — full retention invariance grid

### 9.1 Reference ledger

Create a full-history reference event ledger containing, per user:

- canonical physical episode ID;
- episode start / low / end;
- quality tier;
- response deadline;
- resolved response status;
- any/effective reset events;
- cumulative state transitions;
- final state/action.

### 9.2 Grid

Run both stateless and stateful processing over:

- raw retention windows: 7 / 14 / 21 / 30 / 45 / 60 / 90 days;
- strides: 1 / 7 days;
- alignment offsets: 0..6 days;
- response windows: 24 / 72 / 168h;
- at least two gap-quality configurations.

The stateful algorithm must process data causally and must not initialize from future/full-history state.

### 9.3 Invariance metrics

Relative to full-history reference:

- physical episode recall;
- exact episode-ID match;
- duplicate episode count;
- response-status agreement;
- no-response counter absolute error;
- censored counter error;
- last-effective-change timestamp error;
- action-label agreement;
- first-alert lead/lag;
- state bytes per user;
- raw bytes retained;
- total storage ratio;
- compute time.

### 9.4 Minimal sufficient state ablation

Remove one state component at a time:

- partial FSM;
- pending deadline queue;
- seen episode IDs;
- last any-change timestamp;
- last effective-change timestamp;
- cycle at last effective change;
- gap/censor counters;
- resolved event ledger/hash;
- event ordering rule.

Measure which invariants fail.

### 9.5 Property-based tests

Generate synthetic event streams and assert:

- shifting window boundaries does not change resolved physical events;
- overlapping windows do not double count;
- unresolved events remain pending after raw eviction;
- no-response is impossible before deadline;
- effective reset precedence is deterministic when timestamps collide;
- replay is idempotent;
- state serialization/deserialization is lossless.

### 9.6 Outputs

- `retention_invariance_grid.parquet`
- `retention_invariance_summary.csv`
- `minimal_state_ablation.csv`
- `storage_compute_tradeoff.csv`
- `retention_invariance_heatmap.png`
- `minimal_state_necessity.png`
- `storage_vs_equivalence.png`

### 9.7 Acceptance criterion

IC5 can be upgraded to STRONG only if at least one bounded-retention stateful configuration achieves near-full-history equivalence with:

- response-status agreement >= 0.99;
- duplicate rate = 0;
- no-response counter MAE close to 0;
- no future leakage;
- materially lower storage than full raw history.

If not achieved, state the exact failure mode and downgrade scope.

## 10. Analysis E — missingness, sleep-gap, and censor stress

### 10.1 Injection regimes

Starting from users/episodes with sufficiently dense telemetry, inject:

- MCAR random sample removal: 5/10/20/30/50%;
- contiguous gaps: 3/6/12/24/48h;
- gap placed in high→low leg;
- gap placed around low SOC;
- gap placed in low→high leg;
- gap immediately after episode end;
- gap around 72h deadline;
- end-of-record truncation causing right censoring;
- realistic sleep-gap distributions sampled from the observed fleet.

Run at least 100 replicates per regime where computationally feasible.

### 10.2 Compare detectors

- naive no-response (censored/gap treated as no-response);
- binary gap gate;
- graded quality tier;
- graded quality + censor-aware proposed method.

### 10.3 Metrics

Relative to the uninjected dense reference:

- episode recovery;
- false confirmed no-response;
- missed confirmed no-response;
- FW escalation error;
- Gauge hard-reset error;
- Watch/Review deferral;
- calibration of quality score;
- label stability;
- user-bootstrap CI.

### 10.4 Outputs

- `missingness_stress_summary.csv`
- `missingness_stress_replicates.parquet`
- `missingness_label_transitions.csv`
- `missingness_false_escalation.png`
- `missingness_quality_tier_benefit.png`
- `censor_injection_safety.png`

## 11. Independent technical-effect endpoints

Proxy labels are not ground truth. Add endpoints that do not rely on production labels:

1. protection of observed responders from hard intervention;
2. number of unresolved/censored cases safely deferred;
3. preservation of pending evidence under micro steps;
4. agreement with full-history physical event ledger;
5. storage reduction at a fixed equivalence target;
6. future effective response after a flagged window, used only as a descriptive prospective endpoint and not as a feature;
7. time-to-effective-response curves.

Use careful language: “observed subsequent response”, not “confirmed healthy”.

## 12. Intervention and firmware data

Probe again for:

- BIOS version;
- EC version;
- battery firmware version;
- update availability/applied date;
- gauge reset/calibration execution date;
- post-intervention response.

If absent:

- keep status `NOT_AVAILABLE`;
- do not create synthetic outcomes;
- update the prospective schema and protocol only;
- produce a power calculation for realistic effect sizes and multiple endpoint definitions;
- specify how intervention events will enter the causal event ledger.

## 13. Report corrections required

The v4 report must explicitly correct or qualify the following v3 points:

1. A3 and A4 aggregate metrics were identical; therefore v3 did **not** yet isolate a censor-exclusion effect at the label level.
2. A5 precision=0.8889 is based on a production proxy, small `n=9`, and reduced recall; report CI and direct technical endpoints.
3. A6 precision/recall=1.0 is tautological and must not be presented as validation.
4. “False action” must not be used unless tied to an independently defined endpoint. Use “production-NORMAL flagged”, “observed responder flagged”, or “hard intervention issued” as applicable.
5. Fixed 50mWh is one embodiment; the broader inventive concept is an effective threshold above the gauge quantization/noise band, preferably adaptive.
6. The normative ML model is not an inventive performance result.
7. Closed-loop recovery remains prospective until real intervention data exist.

## 14. Required deliverables

### Data

- `patent_baseline_gate_v4.csv`
- all files required in Sections 4–12
- `patent_technical_effects_v4.csv`
- `patent_evidence_strength_v4.csv`
- `patent_claim_support_matrix_v4.csv`
- `patent_prior_art_feature_matrix_v4.csv`
- `patent_claim_scope_recommendations_v4.csv`
- `patent_results_manifest_v4.csv`

### Reports

- `data/reports/fcc_patent_evidence_v4_report.md`
- `data/reports/fcc_invention_disclosure_v4.md`
- `data/reports/fcc_patent_counsel_brief_v4.md`
- `data/reports/fcc_patent_v4_adversarial_review.md`
- updated intervention protocol if necessary

### Figures

All figures at `dpi=300`, anonymous, no `user_id`, UUID, serial number, or identifying device fields.

At minimum:

- true vs negative-control response;
- anchor contamination;
- response hazard;
- dual-track reset ablation;
- adaptive threshold evidence;
- retention invariance heatmap;
- minimal-state necessity;
- missingness false escalation;
- technical-effect waterfall;
- evidence-strength radar/table.

## 15. Claim-support matrix requirements

For every proposed claim element include:

- technical problem;
- exact algorithm/state transition;
- implementation module/function;
- required input variables;
- direct experiment;
- result and uncertainty interval;
- figure;
- technical effect;
- nearest known prior-art category, marked `UNVERIFIED` unless formally verified;
- broad, medium, and narrow fallback wording;
- evidence strength: STRONG / MEDIUM / WEAK / PROSPECTIVE;
- remaining missing evidence.

Candidate families:

- IC1 full-history qualified-opportunity response auditing;
- IC2 dual-track asymmetric FCC state;
- IC5 bounded-retention causal evidence ledger;
- IC6 gap/censor quality control;
- IC7 diagnosis-dependent closed-loop intervention (prospective);
- IC8 identity-free screening followed by version-level localization (prospective if version absent).

## 16. Adversarial review

Run an adversarial review from at least these perspectives:

1. causal leakage and censoring;
2. battery-domain validity;
3. statistical validity and clustered data;
4. patent technical-effect credibility;
5. prior-art combination/obviousness risk;
6. reproducibility and artifact integrity;
7. privacy/PII;
8. claim overbreadth and unsupported scope.

Every finding must be classified:

- confirmed correctness defect;
- confirmed evidence overstatement;
- confirmed documentation issue;
- rejected with verification evidence;
- unresolved/PENDING.

Re-run affected analyses after every confirmed fix. Report whether labels or technical-effect conclusions changed.

## 17. Tests

Add tests for all critical properties, including:

- negative-control reproducibility;
- user-bootstrap grouping;
- no pre-end response attribution;
- censor deadline semantics;
- duplicate-free episode replay across every retention/alignment grid;
- state ablation expected failures;
- asymmetric reset behavior;
- adaptive-threshold determinism;
- missingness injection reproducibility;
- PII exclusion;
- unavailable-data non-fabrication;
- baseline preservation.

All existing tests plus new tests must pass.

## 18. Completion criteria

The task is complete only when:

1. baseline gate passes;
2. all v3 PENDING raw analyses A2/A3/B/D/E are completed or a concrete computational blocker is documented;
3. IC1 censor/anchor effect is independently quantified;
4. IC2 asymmetric reset is directly ablated;
5. IC5 retention invariance and minimal state are quantified;
6. IC6 is tested under injected missingness;
7. confidence intervals respect user clustering;
8. no technical effect relies solely on proxy labels;
9. no future leakage or double count exists;
10. all figures are 300dpi and anonymous;
11. all tests pass;
12. report wording distinguishes observed fact, inference, proxy comparison, and prospective embodiment;
13. intervention/version results remain `NOT_AVAILABLE` unless real columns are found;
14. final report gives an honest ranking of claim families and identifies which are ready for filing versus continuation/prospective disclosure.

## 19. Final console summary

Print:

- baseline status;
- runtime and artifacts;
- top three independently supported technical effects;
- negative-control results;
- anchor result;
- retention equivalence result;
- missingness-stress result;
- dual-track asymmetric reset result;
- adaptive-threshold recommendation;
- updated evidence strength for IC1/IC2/IC5/IC6/IC7/IC8;
- every remaining limitation;
- exact rerun commands.

Do not claim legal novelty, inventive step, infringement freedom, or patent grant likelihood. Use “technical evidence supports/does not support” language.
