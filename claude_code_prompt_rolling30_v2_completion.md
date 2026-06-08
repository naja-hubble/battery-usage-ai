# Claude Code Prompt — Rolling 30-day FCC Online ML Detection v2.0 Completion

You are working in the `battery-usage-ai` repository as a senior data scientist and Python engineer. Your task is to upgrade the current `rolling30-v1.0` implementation into a production-oriented **Rolling 30-day FCC Learning/Response Online Detector v2.0**.

This is not a greenfield rewrite. Preserve the working v1.0 architecture, tests, and outputs unless the changes below explicitly require refactoring. Implement v2.0 as additive and versioned, with clear backward compatibility where feasible.

---

## 0. Context and objective

We are detecting FCC/SoH learning failures under a 30-day sliding raw-retention constraint.

The raw telemetry window slides daily:

```text
Day t     : raw window [t-29d, t]
Day t + 1 : raw window [t-28d, t+1]
```

Raw older than 30 days must not be used at inference time. However, **derived online state** may persist long-term. The detector must therefore use:

```text
trailing 30d raw telemetry + causal derived state only
```

The core detection principle is:

```text
Do not detect users merely because FCC did not change.
Detect users/windows where real high→low→high learning opportunities occurred,
but FCC failed to produce a meaningful learning response.
```

Prior work showed that direct supervised prediction of `very_stale` from usage behavior is nearly random in the fair regime. Do not build a direct `30d usage -> FW fault` model. Instead, model **episode-level FCC response probability** and detect deviations between expected response and observed response.

---

## 1. Current v1.0 status to preserve and improve

The current rolling detector already implements:

- rolling 30d user-window features
- high→low→high episode extraction for `80/20/80`, `85/15/85`, `90/10/90`
- causal response status: `responded`, `no_response`, `censored`, `unknown`
- online state replay and pending episode management
- effective FCC step definition, default `abs_ge_50mWh`
- self-supervised episode response model
- usage clustering
- anomaly scores
- stateful action policy
- enrichment after classification only
- 300dpi plots and report
- leakage guards and tests

v1.0 full run summary:

```text
cohort = 752 users
raw samples = 3,130,394
user-windows = 200,059, stride=1d
latest labels:
  STATEFUL_NORMAL = 439
  STATEFUL_REVIEW = 166
  STATEFUL_WATCH = 99
  STATEFUL_GAUGE_RESET_CANDIDATE = 45
  STATEFUL_FW_CHECK_CANDIDATE = 3

HGB episode model:
  ROC AUC = 0.8028
  PR AUC = 0.7324
  Brier = 0.1772
  calibrated Brier = 0.1705
  calibration slope = 0.774

same-threshold no-response detection:
  stateful = 24
  stateless 30d-only = 14
  stateful-only gain = 16

strict action gate:
  FW = 3
  Gauge = 45

active false alert:
  vs legacy any-change soh_update_status = 0.7083, 34/48
  vs 50mWh-effective definition = 0.0, 0/48
```

Interpretation:

- FW strict candidate set is a high-precision core but low recall.
- `cum_fw_response_anomaly_score` top-N is useful for engineering review; top-50 captured 11/14 final-proxy FW users.
- Gauge=45 is too broad to call uniformly `gauge reset`. It includes many users considered active under legacy any-change definitions. This is mainly due to micro-wobbles being ignored by the 50mWh-effective definition.
- The response model is useful, but its top feature is `recent_30d_fcc_effective_changes_before_episode`, which risks absorbing the failure state. A **normative model** is needed for anomaly scoring.
- Most episodes are large-gap, so binary `ok` vs `large_gap` is too coarse for final operation.

---

## 2. Deliverable goal

Create a v2.0 detector that is ready for internal engineering review and close to production pilot.

The v2.0 detector must add:

1. **Dual-track FCC state**: legacy `any_change` and effective-step states side-by-side.
2. **Gauge split**: `GAUGE_CORE`, `GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY`, `GAUGE_REVIEW`, instead of one broad Gauge bucket.
3. **Normative episode response model**: exclude FCC history/outcome-proxy features from the anomaly model.
4. **Personalized response model**: keep v1.0 model for prediction/calibration comparison only.
5. **Graded gap quality score**: avoid hard loss of evidence from all large-gap episodes; use high/medium/low evidence tiers.
6. **FW tiers**: high-confidence FW core, FW watch/high-anomaly queue, and FW review queue.
7. **Policy matrix**: final operational labels with priority, action, confidence, and explanation fields.
8. **Backtest comparison**: stateless vs stateful, v1.0 vs v2.0, final proxy cross-tab, top-N yield, lead time.
9. **Active false-alert audit under both definitions**: legacy any-change and effective-step.
10. **Enrichment on multiple candidate populations**: strict FW only, FW top-N anomaly, no-response queue, and watch-high-anomaly, not only strict FW n=3.
11. **Production-grade report and plots** at dpi=300.
12. **Adversarial validation and regression tests** for leakage, causality, and policy edge cases.

---

## 3. Non-negotiable constraints

### 3.1 No future leakage

At each inference time `t`, use only:

```text
raw telemetry in [t-29d, t]
state updated by events resolved at or before t
```

Do not use:

```text
raw older than 30d
future FCC updates
future response status
final validation labels
full-history flat_tail values
future state values
```

### 3.2 Hardware and identity leakage ban

Do not use the following in individual-level classification, ML features, clustering inputs, anomaly scoring, or action policy:

```text
device_model
batt_vendor
batt_fru
manufacturer
design_capacity as an identifier
serialNumber
UUID
MTM
IdentifyingNumber
product_uuid
final_label
soh_update_status as a feature
```

`DesignCapacity` can be used only for physics/normalization such as `% design` step thresholds, not as a model feature if it can serve as hardware identity.

Hardware fields may be used only **after detection** for enrichment/case-control analysis.

Add runtime assertions that fail if these fields enter feature lists.

### 3.3 Do not directly predict `very_stale` or final labels

The final validation labels are evaluation proxies only. They are not ground truth and must not train the model.

### 3.4 Censoring separation

`censored` and `unknown` must never be counted as `no_response`.

An episode can be `no_response` only when:

```text
episode_end + response_window <= latest causally available raw sample timestamp
and no qualifying FCC step occurred in [episode_end, episode_end + response_window]
```

### 3.5 Episode de-duplication

A single episode must contribute to online state once only. Sliding windows overlap by 29 days; do not double-count episodes. Use stable episode IDs.

### 3.6 Data-quality priority

Data-quality review outranks actionable calls. However, still compute diagnostic scores and `would_have_been_*` labels for review users.

---

## 4. Inputs

Required:

```text
data/processed/battery_timeseries_all.parquet
```

Optional if present:

```text
data/processed/user_master.csv
data/processed/fcc_final_action_labels.csv
data/processed/soh_update_status.csv
data/processed/fcc_final_user_features.csv
data/processed/fcc_final_learning_episodes.csv
```

The code must run even if optional files are absent, but the report should include proxy comparisons when they are present.

---

## 5. Recommended file/module structure

Add or modify the following modules. Use existing `battery_usage/` style.

```text
battery_usage/online_step_state.py
battery_usage/online_gap_quality.py
battery_usage/fcc_response_normative.py
battery_usage/online_policy_v2.py
battery_usage/online_evaluation_v2.py
battery_usage/online_reporting_v2.py
battery_usage/online_plotting_v2.py
```

Keep existing v1 modules and reuse them where correct:

```text
battery_usage/online_episode_detector.py
battery_usage/rolling_window_features.py
battery_usage/online_state.py
battery_usage/fcc_response_ml.py
battery_usage/usage_clustering.py
battery_usage/online_anomaly_scores.py
battery_usage/online_action_policy.py
battery_usage/online_enrichment.py
```

Add CLI:

```text
analyze_fcc_online_sliding30_v2.py
plot_fcc_online_sliding30_v2.py
```

Add tests:

```text
tests/test_fcc_online_sliding30_v2.py
```

---

## 6. CLI requirement

Implement this CLI:

```bash
python analyze_fcc_online_sliding30_v2.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --user-master data/processed/user_master.csv \
  --final-labels data/processed/fcc_final_action_labels.csv \
  --soh-update-status data/processed/soh_update_status.csv \
  --window-days 30 \
  --stride-days 1 \
  --response-window-hours 72 \
  --delayed-response-window-hours 168 \
  --episode-max-gap-hours 12 \
  --episode-medium-gap-hours 24 \
  --effective-step abs_ge_50mWh \
  --run-any-change-track \
  --run-normative-model \
  --run-personalized-model \
  --run-clustering \
  --run-backtest \
  --run-enrichment \
  --out-dir data/processed/fcc_online_v2 \
  --fig-dir data/reports/figures/fcc_online_v2 \
  --report data/reports/fcc_online_sliding30_v2_report.md \
  --dpi 300
```

The CLI must be reproducible. Add `--random-seed 42`, defaulting to 42.

---

## 7. Dual-track FCC state

v1.0 used default `abs_ge_50mWh` as the effective FCC learning step. v2.0 must maintain at least two parallel tracks:

```text
any_change_track:
  any integer FCC step counts as an update

effective_track:
  default abs_ge_50mWh counts as effective update
  sensitivity modes: abs_ge_100mWh, abs_ge_0p1pct_design, abs_ge_0p5pct_design
```

For every user/window/state row, compute:

```text
last_any_fcc_change_ts
last_any_fcc_change_cycle
days_since_any_fcc_change
cycles_since_any_fcc_change

last_effective_fcc_change_ts
last_effective_fcc_change_cycle
days_since_effective_fcc_change
cycles_since_effective_fcc_change

n_any_fcc_steps_30d
n_effective_fcc_steps_30d
n_micro_steps_30d
n_micro_steps_since_effective_change
max_micro_step_mWh_since_effective_change
micro_wobble_only_since_effective_change
legacy_any_active_flag
effective_active_flag
```

Definitions:

```text
micro_step = any FCC step with abs(delta_mWh) < effective threshold
micro_wobble_only = any_change occurred but no effective_change occurred over the relevant interval
legacy_any_active_flag = days_since_any_fcc_change < 60, if state has sufficient history
effective_active_flag = days_since_effective_fcc_change < 60, if state has sufficient history
```

Use these columns to separate Gauge Core from Gauge Soft Calibration.

---

## 8. Gauge policy v2

Replace the single broad `STATEFUL_GAUGE_RESET_CANDIDATE` with a tiered output.

### 8.1 Gauge Core

Label:

```text
STATEFUL_GAUGE_RESET_CORE
```

This is a high-confidence gauge reset / calibration target.

Required conditions:

```text
data_quality_ok
state_history_sufficient

# Long staleness under both definitions
and days_since_any_fcc_change >= 120
and days_since_effective_fcc_change >= 120

# No learning opportunity since last relevant FCC change
and cum_primary_ok_opportunities_since_last_effective_change == 0
and cum_primary_medium_gap_opportunities_since_last_effective_change == 0
and cum_primary_large_gap_opportunities_since_last_effective_change == 0
and cum_strict_ok_opportunities_since_last_effective_change == 0
and cum_strict_medium_gap_opportunities_since_last_effective_change == 0
and cum_strict_large_gap_opportunities_since_last_effective_change == 0

# Usage explains lack of learning opportunity
and usage_cluster in {AC_BOUND, SHALLOW_TOPUP, LOW_CYCLING}

# Not FW-like
and cum_primary_no_response_since_last_effective_change == 0
and cum_strict_no_response_since_last_effective_change == 0
```

Expected property:

```text
active false alert vs legacy any-change should be 0 or explicitly explained case-by-case.
```

### 8.2 Gauge Soft Calibration — Effective-only

Label:

```text
STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY
```

Meaning:

```text
The user has micro-wobbles under legacy any-change, but no meaningful FCC relearning step under the effective threshold.
This is a soft calibration prompt, not a hard gauge reset target.
```

Required conditions:

```text
data_quality_ok
state_history_sufficient

days_since_effective_fcc_change >= 120
and days_since_any_fcc_change < 120 or micro_wobble_only_since_effective_change == True
and no high/medium confidence learning opportunities since last effective change
and usage_cluster in {AC_BOUND, SHALLOW_TOPUP, LOW_CYCLING}
and no FW-like repeated no-response evidence
```

Output separate CSV. Do not merge this with Gauge Core in headline actionable counts.

### 8.3 Gauge Review

Label:

```text
STATEFUL_GAUGE_REVIEW
```

Use when Gauge-like conditions are present but:

```text
data quality is not OK
counter reset occurred
state history is insufficient
large-gap evidence prevents firm no-opportunity conclusion
final proxy/review file indicates review-like behavior, if available
```

This is not a user-facing action; it is a support/engineering review queue.

### 8.4 Gauge reporting

Report Gauge as:

```text
Gauge Core: hard actionable
Gauge Soft Calibration: low-risk prompt / monitoring
Gauge Review: manual/data-quality review
```

Do not report one undifferentiated Gauge number.

---

## 9. FW policy v2

Replace a single strict FW bucket with multiple operational tiers.

### 9.1 FW Core

Label:

```text
STATEFUL_FW_CHECK_CORE
```

This is the high-confidence version of v1.0 FW=3.

Required conditions:

```text
data_quality_ok
state_history_sufficient

days_since_effective_fcc_change >= 90
cycles_since_effective_fcc_change >= 30

observed_effective_responses_since_last_effective_change == 0

and one of:
  cum_primary_ok_no_response_since_last_effective_change >= 3
  cum_strict_ok_no_response_since_last_effective_change >= 2
  cumulative_normative_fw_anomaly_score >= 2.0 and conformal_p <= 0.01

and high-quality evidence is dominant:
  high_quality_no_response_count >= 2
  censored_count not dominant
  large_gap_low_quality_count not dominant
```

### 9.2 FW Watch — High Anomaly

Label:

```text
STATEFUL_FW_WATCH_HIGH_ANOMALY
```

Use when:

```text
normative anomaly score is high
or p_all_no_response is low
or top-N anomaly rank is high
but one of the core requirements is missing:
  staleness slightly short
  cycle threshold slightly short
  only medium-gap evidence
  some censored/pending evidence
  data quality OK but not enough confirmed no_response count
```

This should capture many final-proxy FW users that v1.0 strict FW sent to WATCH.

### 9.3 FW Review

Label:

```text
STATEFUL_FW_REVIEW
```

Use when FW-like evidence exists but data quality review outranks action:

```text
counter reset
sparse logs
too many censored episodes
state history insufficient
large-gap dominant
```

### 9.4 FW Engineering Top-N queue

Create a ranked engineering queue independent of strict labels:

```text
online_fcc_fw_engineering_queue_top50.csv
online_fcc_fw_engineering_queue_top100.csv
```

Include users from:

```text
STATEFUL_FW_CHECK_CORE
STATEFUL_FW_WATCH_HIGH_ANOMALY
STATEFUL_FW_REVIEW
high cum_normative_fw_anomaly_score
high cum_personalized_fw_anomaly_score
no_response >= 2 but strict gate failed
```

The v1.0 top-50 anomaly score captured 11/14 final-proxy FW users; v2.0 should preserve or improve this ranking. If not, explain why in the report.

---

## 10. Normative vs personalized episode response models

v1.0's model was useful but potentially too personalized: the top feature was `recent_30d_fcc_effective_changes_before_episode`. This can make the model learn that already-failing gauges are expected not to respond, thereby suppressing anomaly scores.

Implement two model families.

### 10.1 Personalized response model

This is close to v1.0 and is used for prediction/calibration diagnostics only.

Allowed features include:

```text
episode features
recent usage features
recent FCC update history
fcc_before_episode
soh_before_episode
cycle_count_before_episode
```

Do not use hardware/identity/future/final-label features.

### 10.2 Normative opportunity response model

This model estimates:

```text
If the gauge were healthy, how likely is this episode to produce a meaningful FCC response?
```

It is the primary model for anomaly scoring.

Explicitly exclude:

```text
recent_30d_fcc_effective_changes_before_episode
recent_30d_any_fcc_changes_before_episode
fcc_before_episode
soh_before_episode
cycle_count_before_episode
days_since_last_fcc_change
cycles_since_last_fcc_change
prior response/no_response counts
any feature that directly encodes prior FCC response/failure state
hardware/identity/final labels
```

Allowed feature examples:

```text
threshold_name
start_rsoc
low_rsoc
end_rsoc
rsoc_depth
episode_duration_h
start_to_low_duration_h
low_to_end_duration_h
cycle_delta_episode
ac_ratio_in_episode
charge_ratio_in_episode
discharge_ratio_in_episode
n_samples_episode
max_gap_h_episode
median_gap_h_episode
episode_quality_score
recent_30d_cycle_delta_before_episode
recent_30d_ac_ratio_before_episode
recent_30d_rsoc_swing_before_episode
recent_30d_max_gap_h_before_episode
recent_30d_n_samples_before_episode
```

### 10.3 Model types

Train and compare:

```text
logistic regression + calibration
hist gradient boosting + calibration
lightgbm if available
explainable boosting machine if available, otherwise skip gracefully
```

Use:

```text
GroupKFold by user_id
optionally time-block holdout by window_end_date
no random split of overlapping windows
```

Metrics:

```text
ROC AUC
PR AUC
Brier
calibrated Brier
calibration slope/intercept
reliability curve bins
confusion at p>=0.5/0.7/0.9
permutation importance
SHAP if available, optional
```

### 10.4 Anomaly scoring

For each user-window, using resolved-by-time episodes only:

```text
p_i = normative P(response within 72h)
expected_response_30d = sum(p_i)
observed_response_30d = count observed responses
p_all_no_response_30d = product(1 - clip(p_i, eps, 1-eps))
fw_anomaly_score_30d = -log10(p_all_no_response_30d)
```

For stateful cumulative scoring since last effective FCC change:

```text
cum_expected_normative_response
cum_observed_effective_response
cum_p_all_no_response_log10
cum_normative_fw_anomaly_score
conformal_p_current
conformal_p_cumulative
```

Zero-opportunity windows must get anomaly score 0.

Use normative anomaly for policy. Use personalized anomaly only as a secondary diagnostic column.

---

## 11. Graded episode gap quality

v1.0 uses binary `ok` if max_gap <= 12h and `large_gap` otherwise. v2.0 must compute a graded quality score.

Add per-episode columns:

```text
max_gap_h_episode
median_gap_h_episode
n_samples_episode
episode_duration_h
observed_coverage_fraction
high_to_low_max_gap_h
low_to_high_max_gap_h
gap_position_category
endpoint_gap_h
sample_density_per_day
episode_quality_score
quality_tier
```

Recommended scoring:

```text
max_gap_component:
  1.0 if max_gap <= 12h
  linearly decreases to 0.5 at 24h
  linearly decreases to 0.0 at 48h
  0.0 if >48h

coverage_component:
  observed_coverage_fraction capped to [0,1]

endpoint_component:
  penalize if start/low/end anchors are isolated by large gaps

quality_score = weighted mean of components
```

Tiers:

```text
HIGH_OK:
  max_gap <= 12h and quality_score >= 0.80

MEDIUM_GAP:
  max_gap <= 24h and quality_score >= 0.50

LOW_LARGE_GAP:
  otherwise
```

Policy use:

```text
HIGH_OK no_response can support FW Core.
MEDIUM_GAP no_response can support FW Watch, not FW Core by itself.
LOW_LARGE_GAP cannot be counted as no_response evidence, but counts as ambiguity.
```

Gauge use:

```text
Gauge Core requires no HIGH_OK, no MEDIUM_GAP, and no LOW_LARGE_GAP learning opportunities since last relevant FCC change.
Gauge Soft can allow some LOW_LARGE_GAP ambiguity only if usage is strongly AC-bound and no clear deep discharge exists.
```

Add sensitivity for max gap:

```text
6h / 12h / 24h / graded
```

---

## 12. Usage clustering v2

v1.0 clustering appeared to mix usage and response profiles. v2.0 must explicitly separate:

```text
usage-only clustering features
post-hoc outcome profiling
```

### 12.1 Usage-only features

Allowed clustering inputs:

```text
cycle_delta_30d
cycle_rate_30d
ac_time_ratio_30d
charge_time_ratio_30d
discharge_time_ratio_30d
rsoc_min_30d
rsoc_max_30d
rsoc_swing_30d
frac_below20_30d
frac_above80_30d
frac_above95_30d
n_discharge_sessions_30d
n_acdc_switches_30d
n_gap_gt_12h_30d
p95_gap_h_30d
n_samples_30d
```

Do not include:

```text
response/no_response counts
FCC response outcomes
FCC update counts
final labels
hardware identity
```

### 12.2 Outcome profiling

After clusters are assigned, compute:

```text
share_response
share_no_response
share_censored
share_large_gap
share_fw_core
share_gauge_core
share_soft_calibration
```

This is for interpretation only.

### 12.3 Cluster naming

Assign interpretable names using cluster medians:

```text
AC_BOUND
SHALLOW_TOPUP
LOW_CYCLING
MOBILE_DEEP_CYCLE
MOBILE_MODERATE_CYCLE
SPARSE_OR_GAPPY
```

Do not name a cluster `MOBILE_DEEP_CYCLE_NO_RESPONSE` unless response outcome was excluded from inputs and the name is clearly marked as post-hoc outcome profile. Prefer `MOBILE_DEEP_CYCLE_HIGH_NO_RESPONSE_PROFILE` if needed.

---

## 13. Action label taxonomy v2

Every latest-snapshot user must receive exactly one final stateful operational label.

Use this priority order:

```text
1. STATEFUL_REVIEW_DATA_QUALITY
2. STATEFUL_FW_CHECK_CORE
3. STATEFUL_GAUGE_RESET_CORE
4. STATEFUL_FW_WATCH_HIGH_ANOMALY
5. STATEFUL_GAUGE_SOFT_CALIBRATION_EFFECTIVE_ONLY
6. STATEFUL_GAUGE_REVIEW
7. STATEFUL_WATCH_LARGE_GAP_OR_CENSORED
8. STATEFUL_WATCH_LOW_EVIDENCE
9. STATEFUL_NORMAL_RESPONDING
```

Also output non-exclusive diagnostic flags:

```text
fw_like_evidence_flag
gauge_like_evidence_flag
micro_wobble_only_flag
large_gap_dominant_flag
censored_dominant_flag
state_history_insufficient_flag
data_quality_review_flag
```

Output fields:

```text
stateful_label_v2
window_label_v2
recommended_action
confidence
priority
primary_reason
secondary_reasons
evidence_summary
user_message_template
engineering_message_template
```

Recommended actions:

```text
ACTION_NONE
ACTION_FW_VERSION_CHECK_CORE
ACTION_FW_ENGINEERING_REVIEW
ACTION_GAUGE_RESET_CORE
ACTION_SOFT_CALIBRATION_PROMPT
ACTION_MONITOR_NEXT_WINDOW
ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW
```

---

## 14. Evaluation and backtest

### 14.1 Compare against final validation proxy

If `fcc_final_action_labels.csv` is available, compare v2 labels against:

```text
ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE = 14
ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY = 18
WATCH = 55
REVIEW = 338
NORMAL = 327
```

Remember: proxy labels are not ground truth. They are evaluation references.

Report:

```text
stateful_label_v2 × final_proxy_label cross-tab
FW Core precision/recall vs proxy
FW Core + FW Watch recall vs proxy
FW engineering top50 precision/recall vs proxy
Gauge Core precision/recall vs proxy
Gauge Core + Soft Calibration relationship to proxy
proxy FW users falling into Normal/Gauge labels, if any
proxy Gauge users falling into FW labels, if any
```

### 14.2 Active false alert audit

Report false alerts using both bases:

```text
legacy any-change soh_update_status active
online any-change state active
online effective-step state active
```

Required table:

```text
label_v2
n_users
active_false_alert_legacy_any_change
active_false_alert_online_any_state
active_false_alert_online_effective_state
n_micro_wobble_only
```

Acceptance target:

```text
Gauge Core should have 0 legacy-any active false alerts, or each case must be listed with explanation.
Gauge Soft Calibration may include legacy active users, but must be reported separately and never counted as hard Gauge Reset.
FW Core should have 0 legacy active false alerts unless individually justified.
```

### 14.3 Stateful vs stateless

Report:

```text
stateless no-response candidates
stateful no-response candidates
overlap
stateful-only gain
stateless-only set
```

Also report the same after v2 policy tiers:

```text
FW Core stateless vs stateful
FW Watch stateless vs stateful
Gauge Core stateless vs stateful
Soft Calibration stateless vs stateful
```

### 14.4 Lead time

For each proxy label if available:

```text
first alert date
last observation date
lead time days
alert persistence windows
number of alert transitions
```

### 14.5 Threshold and sensitivity grid

Run sensitivity over:

```text
effective step: any_change, abs_ge_50mWh, abs_ge_100mWh, abs_ge_0p1pct_design, abs_ge_0p5pct_design
response window: 24h, 72h, 168h
core staleness days: 60, 90, 120, 180
cycle threshold: 20, 30, 50
gap rule: 6h, 12h, 24h, graded
FW anomaly threshold: 1.3, 2.0, 3.0 or conformal p 0.05, 0.01, 0.001
```

Output stability/Jaccard tables for core labels and engineering queues.

---

## 15. Enrichment v2

Do not limit enrichment to strict FW n=3. Run enrichment on multiple populations:

```text
FW_CORE
FW_CORE + FW_WATCH_HIGH_ANOMALY
FW_ENGINEERING_TOP50
FW_ENGINEERING_TOP100
no_response_ge2_queue
Gauge_Core
Gauge_Soft_Calibration
```

Group axes:

```text
batt_fru
batt_vendor
device_model
```

If BIOS/EC/battery FW version files are present in the future, include:

```text
bios_version
ec_version
battery_fw_version
```

Methods:

```text
beta-binomial empirical Bayes shrinkage
Fisher exact test + BH correction
case-control matched tables by same FRU/model when possible
```

Report raw rates and shrunk rates. Warn when candidate n is too small.

---

## 16. Required outputs

### 16.1 Processed files

```text
data/processed/fcc_online_v2/rolling_30d_user_features_v2.parquet
data/processed/fcc_online_v2/rolling_30d_learning_episodes_v2.parquet
data/processed/fcc_online_v2/online_dual_step_state_daily.parquet
data/processed/fcc_online_v2/online_stateful_labels_v2.parquet
data/processed/fcc_online_v2/online_latest_snapshot_v2.csv

data/processed/fcc_online_v2/online_fcc_fw_core.csv
data/processed/fcc_online_v2/online_fcc_fw_watch_high_anomaly.csv
data/processed/fcc_online_v2/online_fcc_fw_engineering_queue_top50.csv
data/processed/fcc_online_v2/online_fcc_fw_engineering_queue_top100.csv

data/processed/fcc_online_v2/online_fcc_gauge_core.csv
data/processed/fcc_online_v2/online_fcc_gauge_soft_calibration_effective_only.csv
data/processed/fcc_online_v2/online_fcc_gauge_review.csv

data/processed/fcc_online_v2/online_fcc_watchlist_v2.csv
data/processed/fcc_online_v2/online_fcc_review_queue_v2.csv

data/processed/fcc_online_v2/episode_response_model_metrics_personalized.csv
data/processed/fcc_online_v2/episode_response_model_metrics_normative.csv
data/processed/fcc_online_v2/episode_response_model_predictions_personalized.parquet
data/processed/fcc_online_v2/episode_response_model_predictions_normative.parquet

data/processed/fcc_online_v2/user_window_anomaly_scores_v2.parquet
data/processed/fcc_online_v2/usage_cluster_profiles_v2.csv
data/processed/fcc_online_v2/usage_cluster_assignments_v2.parquet

data/processed/fcc_online_v2/backtest_stateful_vs_stateless_v2.csv
data/processed/fcc_online_v2/final_proxy_cross_tab_v2.csv
data/processed/fcc_online_v2/topn_yield_v2.csv
data/processed/fcc_online_v2/active_false_alert_audit_v2.csv
data/processed/fcc_online_v2/sensitivity_grid_v2.csv
data/processed/fcc_online_v2/hardware_enrichment_v2.csv
```

### 16.2 Report

```text
data/reports/fcc_online_sliding30_v2_report.md
```

The report must include:

```text
1. Executive summary
2. Why v2 was needed
3. 30-day sliding-window causality model
4. Data and variables
5. Dual-step state: any-change vs effective-step
6. Gauge split results
7. FW tier results
8. Normative vs personalized response model
9. Large-gap graded quality audit
10. Usage-only clustering and post-hoc outcome profile
11. Stateful vs stateless backtest
12. Final-proxy comparison
13. Active false-alert audit under both definitions
14. Sensitivity analysis
15. HW/FW enrichment after classification
16. Example case studies
17. Operational recommendations
18. Limitations
19. Next data to collect
20. Artifact list
```

### 16.3 Plots at dpi=300

Save to:

```text
data/reports/figures/fcc_online_v2/
```

Required plots:

```text
v2_funnel_counts.png
v2_label_counts.png
v2_policy_matrix_heatmap.png
v2_transition_v1_to_v2_heatmap.png
v2_final_proxy_cross_tab_heatmap.png

any_vs_effective_state_scatter.png
micro_wobble_step_distribution.png
days_since_any_vs_effective_fcc_change.png
active_false_alert_dual_basis.png

personalized_vs_normative_roc_pr.png
personalized_vs_normative_calibration.png
normative_feature_importance.png
personalized_feature_importance.png
expected_vs_observed_response_normative.png
fw_anomaly_score_distribution.png
fw_topn_yield_curve.png

large_gap_quality_distribution.png
gap_rule_sensitivity_counts.png
response_window_sensitivity_effective.png

stateful_vs_stateless_counts.png
stateful_only_evidence_examples.png
lead_time_by_proxy_label.png

usage_cluster_profiles.png
usage_cluster_outcome_profile.png

hardware_enrichment_fw_core.png
hardware_enrichment_fw_top50.png
fru_case_control_if_available.png

example_fw_core_top20/*.png
example_fw_watch_top20/*.png
example_gauge_core_top20/*.png
example_gauge_soft_top20/*.png
example_review_top20/*.png
```

Individual user plots must show:

```text
RSOC trajectory
FCC trajectory with any/effective step markers
cycleCount
AC/DC status if available
learning episodes colored by quality tier
response/no_response/censored markers
last any FCC change
last effective FCC change
state/action label and evidence summary
```

---

## 17. Tests

Add tests covering at least:

### 17.1 Causality and censoring

```text
episode_end + 72h after current window end -> censored, not no_response
future FCC step after inference time not used
window-end grid cannot extend beyond latest sample and falsely close censoring
```

### 17.2 Episode de-duplication

```text
same episode appears in overlapping windows but state counts it once
stable episode_id deterministic across reruns
```

### 17.3 State reset

```text
effective FCC step resets effective counters and pending set
any-change FCC step resets only any-change track, not effective track if micro-step
```

### 17.4 Dual-step policy

```text
micro-wobble-only user goes to Gauge Soft, not Gauge Core
any-change stale and effective stale user can go to Gauge Core
Gauge Core has no learning opportunities and no FW-like no-response evidence
```

### 17.5 Normative feature guard

```text
normative feature list excludes recent FCC changes, fcc_before, soh_before, cycle_count_before, prior response counts, final labels, hardware identity
personalized feature list still excludes hardware/future/final labels
```

### 17.6 Clustering feature guard

```text
usage clustering input excludes FCC response outcomes, no_response counts, FCC update counts, final labels, hardware identity
post-hoc profiles may include outcomes
```

### 17.7 Gap quality

```text
max_gap <=12 -> HIGH_OK if coverage sufficient
12<max_gap<=24 -> possible MEDIUM_GAP
large low-quality episodes cannot support FW Core
medium gap can support Watch but not Core alone
```

### 17.8 Action priority

```text
data-quality review outranks action
FW Core outranks Gauge when opportunity no-response exists
Gauge Core and FW Core cannot both be true
Gauge Soft does not count as hard Gauge Reset
```

### 17.9 Leakage assertions

```text
hardware fields banned from classification/model/clustering lists
final labels banned from training features
GroupKFold by user used for model validation
```

### 17.10 Regression tests

Include regression tests for the two previously found causal bugs:

```text
window-end grid extending to end-of-day caused censored -> no_response bug
future resolved status in attach_window_episode_counts bug
```

All tests must pass with existing test suite.

---

## 18. Acceptance criteria

A run is complete only if all criteria are satisfied:

1. All 752 users receive exactly one latest `stateful_label_v2`.
2. v2 output separates hard Gauge Core from soft calibration candidates.
3. Gauge Core legacy-any active false alert is 0 or every exception is listed with an individual explanation.
4. Gauge Soft Calibration reports legacy-any active overlap explicitly and is not counted as hard reset.
5. FW Core is high precision against final proxy; if precision is not high, explain each false positive.
6. FW Core + FW Watch or top50 queue should capture most final-proxy FW cases. Target: top50 recall >= 0.70 unless impossible; explain if lower.
7. Final-proxy FW users must not be silently classified as Normal/Gauge Core without explicit evidence and report table.
8. Normative model and personalized model are both trained and compared.
9. Normative anomaly score is used for policy; personalized score is diagnostic only.
10. Normative model feature guard passes.
11. Usage clustering feature guard passes.
12. `censored`/`unknown` are never counted as `no_response`.
13. Large-gap LOW tier never supports FW Core.
14. Episode de-duplication under sliding windows is verified.
15. Stateful vs stateless comparison is reported.
16. Active false-alert audit is reported under legacy-any and effective-step bases.
17. Enrichment is run for FW Core and FW top-N queues, not just strict FW.
18. All plots are saved at dpi=300.
19. Report includes explicit limitations: candidates, not confirmed FW faults; need BIOS/EC/battery FW versions and interventions.
20. All tests pass.

---

## 19. Adversarial review workflow

After implementing and running v2.0, run an adversarial review before finalizing.

Use at least these review agents/roles:

```text
1. Causality/leakage reviewer
2. Battery-gauge domain reviewer
3. ML/calibration reviewer
4. Online-state/replay reviewer
5. Data-quality/large-gap reviewer
6. Operations/action-policy reviewer
7. Enrichment/statistics reviewer
8. Report/readability reviewer
```

For each reviewer, record:

```text
issue_id
severity: high/medium/low
claim
check performed
result
fix or rejection reason
files changed
whether labels changed after fix
```

Output:

```text
data/reports/fcc_online_v2_adversarial_review.md
```

---

## 20. Final report language

Use precise language.

Do say:

```text
FW_CHECK_CORE means the user should be prioritized for BIOS/EC/battery FW version and update review.
```

Do not say:

```text
FW_CHECK_CORE proves FW is defective.
```

Do say:

```text
Gauge Soft Calibration means no meaningful FCC relearning step under the effective threshold, despite legacy micro-wobbles.
```

Do not say:

```text
Gauge Soft Calibration is a confirmed gauge failure.
```

Do say:

```text
The detector is mechanistic: learning opportunity vs FCC response.
```

Do not say:

```text
The detector predicts battery failure from usage.
```

---

## 21. Final answer expected from Claude Code

When finished, return:

```text
1. Short implementation summary
2. New/modified files
3. Latest label counts
4. Gauge Core / Soft / Review counts
5. FW Core / Watch / Review / top50 counts
6. Normative vs personalized model metrics
7. Stateful vs stateless results
8. Active false-alert audit summary
9. Final-proxy cross-tab summary
10. Major plots generated
11. Adversarial review fixes
12. Known limitations
13. Exact commands to rerun
14. Paths to report, CSVs, plots
```

Be honest about any metric that worsens. Do not hide tradeoffs.
