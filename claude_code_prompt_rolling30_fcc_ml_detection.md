# Claude Code Prompt — 30-day Sliding Window FCC Learning/Response ML Detection

あなたは `battery-usage-ai` リポジトリで作業するシニアデータサイエンティスト兼Pythonエンジニアです。目的は、ThinkPadバッテリーテレメトリに対して、**30日sliding window制約下**でFCC/SoH学習不良を教師なし・自己教師ありML・オンライン状態管理により検出する、一気通貫の実装・解析・レポート作成を行うことです。

## 0. 背景と設計原則

### 0.1 重要な過去知見
既存長期解析では、`fullChargeCapacity`(FCC) が `SoH = FCC / DesignCapacity` を駆動し、FCCがステップ更新されないとSoHも更新されないことが確認済み。最終検証版では、全752ユーザー中、FCC no/low change候補96人、Gauge Reset高信頼18人、FW/BIOS/EC確認高信頼14人、Watch 55人、Review 338人、Normal 327人に分類している。

ただし、これは数か月〜数年のraw履歴を使った監査であり、今後の実運用ではraw telemetryは**直近30日window**しか参照できない。30日windowは日次でスライドする。つまり Day t では `[t-29, t]`、Day t+1 では `[t-28, t+1]` を見る。

過去の教師あり検証では、使用挙動から `very_stale` を直接予測するモデルは公平領域でAUC≈0.54とほぼランダムだった。したがって、今回は「30日使用特徴量→FW不良/very_staleを直接分類」という設計は禁止する。代わりに、**学習機会episodeに対して通常ならFCCが応答する確率を推定し、期待応答に対して実応答がないuser/windowを異常として検出する**。

### 0.2 中核思想
検出すべきは「FCCが動かないこと」そのものではなく、次である。

```text
通常ならFCCが応答するはずの高SOC→低SOC→高SOC学習機会があるにもかかわらず、FCCが有効更新しないこと。
```

### 0.3 raw retention制約
- raw telemetryは直近30日windowしか使えない想定で実装する。
- ただし、rawではない派生状態量は長期保持できる前提の **stateful online detector** を主設計にする。
- state保持が許されない場合の **stateless 30-day detector** も比較用に実装し、性能差をレポートする。
- backtestでは長期Parquetを使ってよいが、各推論時点では「直近30日raw + その時点までに更新されたstate」だけを入力にする。未来情報、30日より古いrawサンプル、最終ラベルの先読みは禁止。

### 0.4 禁止事項
- `device_model`, `batt_vendor`, `batt_fru`, `manufacturer`, `serialNumber`, `UUID`, `MTM`, `IdentifyingNumber`, `product_uuid` などのHW/ID識別子を、個人レベルのラベル決定・ML特徴量に使わない。
- これらは、検出後のfleet-level enrichment / case-control / FW version確認優先順位付けにのみ使う。
- 最終検証版の `final_label` を教師ラベルとしてML学習してはいけない。使ってよいのはbacktestの評価proxy、top-N yield、遷移比較、説明用のみ。
- 隣接する30日windowをランダムsplitしてtrain/testに分けない。29日重複により重大なリークになる。
- `censored` / `unknown` episodeを `no_response` として扱わない。
- large-gap episodeをOK品質の学習機会として扱わない。

---

## 1. 入力

想定入力。存在しない場合は探索し、見つからなければ明示的にwarningを出して処理を継続する。

```text
data/processed/battery_timeseries_all.parquet
  必須。全ユーザーlong時系列。

PROJECT_STATUS.md
  可能なら読む。変数定義・過去知見確認用。

data/processed/fcc_final_action_labels.csv
  任意。最終検証版ラベル。ML学習には使わず、backtest評価proxyとしてのみ使用。

data/processed/fcc_final_learning_episodes.csv
  任意。照合用。rolling実装ではepisodeを再抽出する。

data/processed/user_master.csv
  任意。DesignCapacity補完、HW enrichment用。

fcc_final_thresholds.zip or data/reports/figures/fcc_final_thresholds/
  任意。最終検証版plotとの比較用。
```

`battery_timeseries_all.parquet` 主要列:

```text
user_id, timestamp, remainingCapacityInPercentage, cycleCount,
fullChargeCapacity, soh_design_pct, acdcMode, chargeStatus,
remainingCapacity, RemainingTime, totalChargedCapacity,
hoursAtFullCharge, hoursAtHighTemperature,
hoursAtFullChargeAndHighTemperature,
device_model, batt_vendor, batt_fru, serialNumber
```

`remainingCapacityInPercentage` をRSOCとして使う。`fullChargeCapacity` はmWh。`cycleCount` は積算サイクル数。`acdcMode`: 0=DC, 1=AC。

---

## 2. 出力

すべてのCSV/Parquetには `analysis_timestamp`, `code_version`, `window_days`, `stride_days`, `effective_step_definition` を付与する。

### 2.1 processed outputs

```text
data/processed/fcc_online/rolling_30d_user_features.parquet
  1 row = user_id × window_end_date。30日window特徴量。

data/processed/fcc_online/rolling_30d_learning_episodes.parquet
  1 row = unique learning episode。stateful/stateless由来、response status、ML probability付き。

data/processed/fcc_online/online_fcc_user_state_daily.parquet
  1 row = user_id × day。オンライン状態量のbacktest軌跡。

data/processed/fcc_online/online_fcc_daily_labels.parquet
  1 row = user_id × day。window label / stateful label / recommended action。

data/processed/fcc_online/online_fcc_current_snapshot.csv
  各userの最新window時点の状態と推奨action。

data/processed/fcc_online/online_fcc_action_candidates_fw_check.csv
  最新時点のFW/BIOS/EC確認候補。

data/processed/fcc_online/online_fcc_action_candidates_gauge_reset.csv
  最新時点のGauge Reset/Calibration候補。

data/processed/fcc_online/online_fcc_watchlist.csv
  Watch候補。

data/processed/fcc_online/online_fcc_review_queue.csv
  Data quality / counter reset / sparse / censored多発などreview候補。

data/processed/fcc_online/episode_response_model_metrics.csv
  GroupKFold/time-block metrics。ROC AUC, PR AUC, Brier, calibration。

data/processed/fcc_online/episode_response_model_predictions.parquet
  OOF or test predictions。episode_id, p_response, y, fold, censor flags。

data/processed/fcc_online/user_window_ml_scores.parquet
  expected_response, observed_response, p_all_no_response, anomaly score, conformal p。

data/processed/fcc_online/usage_cluster_profiles.csv
  教師なし使用クラスタの中心/分布/事後命名。

data/processed/fcc_online/usage_cluster_assignments.parquet
  user-windowごとのクラスタ。

data/processed/fcc_online/backtest_detection_summary.csv
  最終検証版ラベルをproxyとした検出性能、lead time、false alertなど。

data/processed/fcc_online/hardware_enrichment_online_fw_candidates.csv
  分類後のHW/FW偏在。分類には使わない。
```

### 2.2 reports and figures

```text
data/reports/fcc_online_sliding30_ml_detection_report.md

data/reports/figures/fcc_online/*.png
```

すべてのplotは `dpi=300` で保存する。図にはタイトル、軸ラベル、閾値線、n数を明記する。

---

## 3. 実装ファイル

既存 `battery_usage/` スタイルに合わせて実装する。

```text
battery_usage/rolling_window_features.py
  30日window特徴量生成。stateless/stateful両対応。

battery_usage/online_episode_detector.py
  high→low→high episode状態機械。window境界をまたぐpartial episode state対応。

battery_usage/online_state.py
  rawを保持しないユーザー状態量。FCC有効更新時のstate reset、pending episode管理、double-count防止。

battery_usage/fcc_response_ml.py
  episode-level self-supervised response model。特徴量作成、split、training、calibration、prediction。

battery_usage/usage_clustering.py
  30日使用パターンの教師なしクラスタリングとクラスタプロファイル命名。

battery_usage/online_anomaly_scores.py
  expected_response, p_all_no_response, -log10 anomaly score, conformal p-value。

battery_usage/online_action_policy.py
  window label / stateful label / action policy。large-gap/censored/data quality guards。

battery_usage/online_enrichment.py
  FW候補のHW/FW/FRU/vendor/model/version偏在集計。分類には不使用。

analyze_fcc_online_sliding30.py
  end-to-end CLI。特徴量、episode、state、ML、score、labels、backtest、reportに一気通貫。

plot_fcc_online_sliding30.py
  300dpi図生成。

tests/test_fcc_online_sliding30.py
  unit/regression tests。
```

---

## 4. CLI

最終的に以下で一気通貫実行できるようにする。

```bash
python analyze_fcc_online_sliding30.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --user-master data/processed/user_master.csv \
  --final-labels data/processed/fcc_final_action_labels.csv \
  --window-days 30 \
  --stride-days 1 \
  --effective-step abs_ge_50mWh \
  --response-window-hours 72 \
  --episode-max-gap-hours 12 \
  --out-dir data/processed/fcc_online \
  --fig-dir data/reports/figures/fcc_online \
  --report data/reports/fcc_online_sliding30_ml_detection_report.md \
  --dpi 300 \
  --run-ml \
  --run-clustering \
  --run-backtest \
  --run-enrichment
```

高速デバッグ用に以下も用意する。

```bash
python analyze_fcc_online_sliding30.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --window-days 30 \
  --stride-days 7 \
  --out-dir data/processed/fcc_online_debug \
  --fig-dir data/reports/figures/fcc_online_debug \
  --report data/reports/fcc_online_debug_report.md \
  --dpi 150 \
  --run-ml \
  --run-backtest
```

---

## 5. データ前処理

### 5.1 timestamp / sort

- `timestamp` を `datetime64[ns]` に変換。
- user_id, timestampで安定sortする。`kind="stable"` を使う。
- 重複timestampは原則最後の行を採用。ただし、重複timestampにFCC値の不整合がある場合はdata_quality flagに残す。

### 5.2 DesignCapacity推定

`DesignCapacity` がtimeseriesにない場合は以下で推定する。

```text
1. user_master.csv の design_capacity / DesignCapacity があれば使用。
2. timeseriesに soh_design_pct があれば、fullChargeCapacity * 100 / soh_design_pct のuser内medianを使用。
3. それでも無理なら effective-stepのpercent-design系は欠損扱い。
```

### 5.3 effective FCC step定義

主判定では `abs_ge_50mWh` をdefaultにする。理由は、30日運用では微小FCC stepを学習応答として数えるとno-responseをmaskする可能性があるため。感度分析として以下を全て再計算する。

```text
any_change
abs_ge_50mWh
abs_ge_100mWh
abs_ge_0p1pct_design
abs_ge_0p5pct_design
```

`effective_fcc_changed` は、隣接サンプル差分 `abs(diff(fullChargeCapacity))` が閾値以上ならtrue。

---

## 6. 30日sliding window特徴量

1 row = `user_id × window_end_date`。

### 6.1 window定義

```text
window_start = window_end - 30 days
window_end inclusive
```

strideは1日が主、7日を高速/debug用に許容。ユーザーの観測開始〜終了の範囲でwindowを作る。最低観測日数や最低サンプル数に満たないwindowは `WINDOW_DATA_QUALITY_REVIEW` に回す。

### 6.2 data quality features

```text
n_samples_30d
obs_days_in_window
median_interval_h
p95_interval_h
max_gap_h
gaps_gt_6h_count
gaps_gt_12h_count
gaps_gt_24h_count
duplicate_timestamp_count
cycle_decrease_count
fcc_missing_count
rsoc_missing_count
has_counter_reset
window_data_quality_label
```

品質ラベル:

```text
WINDOW_QUALITY_OK
WINDOW_QUALITY_SHORT_OBS
WINDOW_QUALITY_SPARSE
WINDOW_QUALITY_COUNTER_RESET
WINDOW_QUALITY_DUPLICATE_CONFLICT
```

### 6.3 usage features

```text
cycle_start_30d
cycle_end_30d
cycle_delta_30d
cycle_rate_per_30d
ac_time_ratio_30d
charge_time_ratio_30d
discharge_time_ratio_30d
rsoc_min_30d
rsoc_max_30d
rsoc_swing_30d
rsoc_p05_30d
rsoc_p50_30d
rsoc_p95_30d
frac_below_10_30d
frac_below_20_30d
frac_above_80_30d
frac_above_90_30d
frac_above_95_30d
n_acdc_switches_30d
n_charge_status_switches_30d
n_discharge_sessions_30d
```

### 6.4 FCC features

```text
fcc_start_30d
fcc_end_30d
fcc_min_30d
fcc_max_30d
fcc_abs_delta_30d
fcc_any_changes_30d
fcc_effective_changes_30d
fcc_effective_step_abs_max_30d
last_effective_fcc_change_ts_in_window
last_effective_fcc_change_cycle_in_window
soh_start_30d
soh_end_30d
```

---

## 7. Online episode detector

### 7.1 episode definitions

3種類を抽出する。

```text
primary_80_20_80: RSOC >= 80 → RSOC <= 20 → RSOC >= 80
secondary_85_15_85: RSOC >= 85 → RSOC <= 15 → RSOC >= 85
strict_90_10_90: RSOC >= 90 → RSOC <= 10 → RSOC >= 90
```

### 7.2 state machine

状態:

```text
WAIT_HIGH
WAIT_LOW
WAIT_HIGH_AGAIN
```

window境界をまたぐepisodeに対応するため、以下のpartial stateを保存する。

```text
episode_detector_state_by_threshold
current_episode_start_ts
current_episode_start_rsoc
current_episode_low_ts
current_episode_low_rsoc
min_rsoc_since_high
max_rsoc_since_low
```

### 7.3 episode quality

episodeごとに以下を計算。

```text
episode_id
user_id
threshold_name
start_ts
low_ts
end_ts
start_rsoc
low_rsoc
end_rsoc
episode_depth
start_to_low_duration_h
low_to_end_duration_h
episode_duration_h
cycle_delta_episode
n_samples_episode
max_gap_h_episode
median_gap_h_episode
episode_quality
```

quality:

```text
ok: max_gap_h_episode <= episode_max_gap_hours and no missing RSOC/FCC
large_gap: max_gap_h_episode > episode_max_gap_hours
invalid_order
missing_required_value
```

Default `episode_max_gap_hours = 12`。感度分析で6/12/24hを回す。

### 7.4 response status

response windowはepisode endから72h。24/168hも感度用に計算する。

```text
response_status_24h
response_status_72h
response_status_168h
```

値:

```text
responded
no_response
censored
unknown
```

判定:

```text
responded:
  episode_end <= t <= episode_end + response_window 内にFCC effective changeあり

no_response:
  response windowが完全に観測されており、FCC effective changeなし

censored:
  episode_end + response_window > last_observed_ts_at_current_inference_time

unknown:
  FCC欠損、不整合、または品質上判定不能
```

`censored` と `unknown` は絶対に `no_response` に混ぜない。

### 7.5 double-count防止

sliding windowでは同じepisodeが多数のwindowに入る。state更新時は `episode_id` で一度だけ加算する。episode response statusがpending/censoredからcompleteへ変わる場合の再評価を正しく扱う。

---

## 8. Online state store

rawを保持せず、日次で以下のstateを保持する。

```text
user_id
state_as_of_date
last_seen_ts
first_seen_ts

last_effective_fcc_value
last_effective_fcc_change_ts
last_effective_fcc_change_cycle
days_since_last_effective_fcc_change
cycles_since_last_effective_fcc_change

cum_primary_ok_since_last_fcc_change
cum_primary_response_since_last_fcc_change
cum_primary_no_response_since_last_fcc_change
cum_primary_large_gap_since_last_fcc_change
cum_primary_censored_since_last_fcc_change

cum_strict_ok_since_last_fcc_change
cum_strict_response_since_last_fcc_change
cum_strict_no_response_since_last_fcc_change
cum_strict_large_gap_since_last_fcc_change
cum_strict_censored_since_last_fcc_change

cum_expected_response_since_last_fcc_change
cum_observed_response_since_last_fcc_change
cum_log_p_all_no_response_since_last_fcc_change

consecutive_windows_without_effective_fcc_update
consecutive_windows_opportunity_no_response
consecutive_windows_insufficient_opportunity
consecutive_windows_large_gap_ambiguous

last_window_label
last_stateful_label
last_action_label
last_alert_ts
alert_cooldown_until

processed_episode_ids_hash_or_count
pending_episode_ids
```

FCC有効更新が発生したら、`since_last_fcc_change` 系の累積カウンタをresetする。ただし監査ログとしてreset前値は履歴に残す。

---

## 9. ML Layer 1 — 30日使用パターン教師なしクラスタリング

### 9.1 目的

FW不良を直接検出するものではない。目的は、30日windowを使用パターンで分け、Gauge Reset寄り / FW Check寄り / Watch寄りの説明補助にすること。

### 9.2 特徴量

HW/IDは使わない。

```text
cycle_delta_30d
cycle_rate_per_30d
ac_time_ratio_30d
charge_time_ratio_30d
discharge_time_ratio_30d
rsoc_min_30d
rsoc_max_30d
rsoc_swing_30d
frac_below_20_30d
frac_above_80_30d
frac_above_95_30d
n_discharge_sessions_30d
n_acdc_switches_30d
n_80_20_80_ok_complete_30d
n_80_20_80_large_gap_30d
n_90_10_90_ok_complete_30d
fcc_effective_changes_30d
```

### 9.3 アルゴリズム

依存関係の可用性に応じて使い分ける。

```text
Preferred:
  HDBSCAN if installed
Fallback:
  GaussianMixture / BayesianGaussianMixture / KMeans / MiniBatchKMeans from sklearn
```

標準化・欠損処理は `Pipeline(SimpleImputer, RobustScaler, model)` で行い、CV/fit内でリークしないようにする。

### 9.4 cluster profiling

クラスタごとに以下を出力し、事後命名する。

```text
n_windows
n_users
median_cycle_delta
median_ac_ratio
median_rsoc_swing
median_n_opportunities
median_fcc_effective_changes
share_response_windows
share_no_response_windows
share_large_gap
suggested_profile_name
suggested_action_hint
```

想定profile:

```text
AC_BOUND
SHALLOW_TOPUP
LOW_CYCLING_LOW_INFORMATION
MOBILE_DEEP_CYCLE_RESPONDING
MOBILE_DEEP_CYCLE_NO_RESPONSE
LARGE_GAP_AMBIGUOUS
SPARSE_OR_REVIEW
```

---

## 10. ML Layer 2 — episode-level FCC response model

### 10.1 目的

1 row = unique learning episode。目的変数は、人手ラベルではなく、telemetry上のFCC有効応答。

```text
y = 1 if FCC effective change within 72h after episode end
y = 0 if 72h window complete and no effective FCC change
exclude or censor if response window incomplete/unknown
```

Primary targetは `response_eff_50mWh_72h`。感度で `any_change`, `100mWh`, `0.1%design` も比較。

### 10.2 特徴量

episode終了時点までに分かる特徴だけを使う。未来情報は禁止。

```text
threshold_name one-hot
episode_depth
episode_duration_h
start_to_low_duration_h
low_to_end_duration_h
cycle_delta_episode
start_rsoc
low_rsoc
end_rsoc
n_samples_episode
max_gap_h_episode
median_gap_h_episode

fcc_before_episode
soh_before_episode
cycle_count_before_episode

recent_30d_cycle_delta_before_episode
recent_30d_ac_ratio_before_episode
recent_30d_rsoc_swing_before_episode
recent_30d_n_80_20_80_ok_before_episode
recent_30d_fcc_effective_changes_before_episode
recent_30d_data_quality_features
```

禁止特徴:

```text
device_model, batt_vendor, batt_fru, manufacturer, serialNumber, UUID, MTM, product_uuid
future FCC values after episode end
flat_tail_days computed using future
final_label or previous audit label
```

### 10.3 モデル

以下を実装・比較する。

```text
Baseline:
  LogisticRegression with class_weight if needed

Main:
  HistGradientBoostingClassifier

Optional if dependencies available:
  LightGBM / XGBoost / Explainable Boosting Machine
```

scikit-learnのみで成立する実装を必須にする。外部依存がない場合でも完走すること。

### 10.4 validation

- `GroupKFold` by `user_id` を必須。
- 追加でtime-block validationも実施可能なら行う。
- sliding window由来の重複をtrain/testに跨がせない。
- metrics:

```text
n_episodes
n_users
positive_rate
ROC AUC
PR AUC
Brier score
calibration slope/intercept if feasible
confusion at probability thresholds 0.5/0.7/0.9
```

### 10.5 calibration

確率を異常スコアに使うため、calibrationを確認する。

```text
calibration_curve
reliability diagram
Brier score
```

`CalibratedClassifierCV` がGroupKFoldと相性問題を起こす場合は、out-of-fold predictionに対してPlatt scalingまたはisotonic regressionを別途fitする。実装が難しい場合はuncalibrated probabilityとして明示し、Brier/calibration plotを出す。

---

## 11. ML Layer 3 — user-window anomaly scoring

### 11.1 expected/observed response

各user-windowについて、complete OK episodeのモデル応答確率 `p_i` を集約する。

```text
expected_response_30d = Σ p_i
observed_response_30d = number of responded episodes
no_response_count_30d = number of no_response episodes
```

### 11.2 Poisson-binomial all-no-response probability

実装:

```text
p_all_no_response_30d = Π(1 - p_i)
fw_response_anomaly_score_30d = -log10(max(p_all_no_response_30d, eps))
```

`p_i` は [0.001, 0.999] にclipして数値安定化する。

累積state版:

```text
cum_expected_response_since_last_fcc_change
cum_observed_response_since_last_fcc_change
cum_log_p_all_no_response_since_last_fcc_change
cum_fw_response_anomaly_score = -log10(exp(cum_log_p_all_no_response))
```

### 11.3 conformal / empirical p-value

calibration setを定義し、scoreの経験的p値を出す。

推奨calibration set:

```text
WINDOW_QUALITY_OK
complete OK opportunities >= 1
not in data-quality review
not actioned in previous state
```

過去final labelはcalibrationには使わない。使う場合は別列 `conformal_p_proxy_final_normal` として明確に分ける。

```text
conformal_p = share(calibration_scores >= new_score)
```

### 11.4 thresholds

初期policy:

```text
FW_WATCH:
  p_all_no_response <= 0.05 OR conformal_p <= 0.05

FW_CHECK_CANDIDATE:
  p_all_no_response <= 0.01 OR conformal_p <= 0.01
  and n_complete_ok_opportunities_30d >= 2
  and observed_response_30d == 0
  and data_quality_ok
  and large_gap/censored not dominant

FW_HIGH_CONFIDENCE:
  p_all_no_response <= 0.001 OR strict_no_response_complete >= 2 OR primary_no_response_complete >= 3
```

これらは最終レポートで感度分析する。

---

## 12. Online action policy

window labelとstateful labelを分ける。

### 12.1 window labels

直近30日だけのラベル。

```text
WINDOW_NORMAL_RESPONDING
WINDOW_INSUFFICIENT_LEARNING_OPPORTUNITY
WINDOW_OPPORTUNITY_NO_RESPONSE
WINDOW_LARGE_GAP_AMBIGUOUS
WINDOW_CENSORED_PENDING
WINDOW_DATA_QUALITY_REVIEW
WINDOW_LOW_INFORMATION
```

### 12.2 stateful labels

stateを含む長期action候補。

```text
STATEFUL_NORMAL
STATEFUL_GAUGE_RESET_CANDIDATE
STATEFUL_FW_CHECK_CANDIDATE
STATEFUL_WATCH
STATEFUL_REVIEW
```

### 12.3 FW policy

```text
STATEFUL_FW_CHECK_CANDIDATE if:
  recent window quality OK
  and days_since_last_effective_fcc_change >= 90 or 120
  and cycles_since_last_effective_fcc_change >= 30
  and (
      cum_primary_no_response_since_last_fcc_change >= 3
      or cum_strict_no_response_since_last_fcc_change >= 2
      or cum_fw_response_anomaly_score >= 2.0
      or current fw_response_anomaly_score_30d >= 2.0
  )
  and cum_observed_response_since_last_fcc_change == 0
  and large_gap/censored are not dominant
```

### 12.4 Gauge policy

```text
STATEFUL_GAUGE_RESET_CANDIDATE if:
  recent window quality OK
  and days_since_last_effective_fcc_change >= 90 or 120
  and fcc_effective_changes_recent == 0
  and cum_primary_ok_since_last_fcc_change == 0
  and cum_primary_large_gap_since_last_fcc_change == 0
  and cum_strict_ok_since_last_fcc_change == 0
  and cum_strict_large_gap_since_last_fcc_change == 0
  and recent usage cluster/profile in {AC_BOUND, SHALLOW_TOPUP, LOW_CYCLING_LOW_INFORMATION}
  and (
      ac_time_ratio_30d >= 0.80
      or rsoc_swing_30d < 60
      or rsoc_min_30d > 20
      or cycle_delta_30d below fleet p25
  )
```

### 12.5 Watch policy

```text
STATEFUL_WATCH if:
  no/low FCC or response anomaly signs exist
  but evidence is incomplete due to large_gap/censored/borderline score/low opportunity count
```

### 12.6 alert cooldown

同一userに毎日同じalertを出さない。

```text
alert only on state transition
cooldown 30 or 60 days
reset cooldown if effective FCC update occurs
post-intervention monitoring state if action was recorded
```

Intervention dataがない場合は、実施後評価はreportのfuture workにする。

---

## 13. Backtest design

### 13.1 simulation

過去long dataを使うが、各日では以下だけを使う。

```text
current raw window = [t-29d, t]
previous online state up to t-1
pending episode state
```

未来のraw、最終flat_tail、最終labelは推論入力に使わない。

### 13.2 evaluation proxy

`fcc_final_action_labels.csv` があれば、最終検証版labelを評価proxyとして使う。これはground truthではないとreportに明記する。

比較対象:

```text
final ACTION_FW_CHECK 14
final ACTION_GAUGE_RESET 18
final WATCH 55
final NORMAL_OR_RESPONDING 327
final REVIEW 338
existing soh_update_status active/stale/very_stale if available
```

### 13.3 metrics

```text
latest snapshot counts by label
actionable counts over time
active false actionable rate if existing status available
time_to_first_alert for final FW/Gauge proxy cases
lead_time_days relative to last observed date or final classification date
top-N yield: score上位Nにfinal FW/Gauge proxyがどれだけ含まれるか
precision@N, recall@N against final proxy
stateless vs stateful detection counts
stateful incremental gain
watch-to-action transition rates
large-gap/censored protection counts
model calibration metrics
cluster stability across adjacent windows
```

### 13.4 leakage checks

必ずreportに以下を出す。

```text
No HW/ID features in model feature list
No final labels in training features
Group split by user for episode model
No censored episodes counted as no_response
No duplicate episode counted multiple times in state
```

---

## 14. Fleet-level enrichment

分類後にのみ実施する。

### 14.1 group axes

```text
batt_fru
batt_vendor
device_model
BIOS version if available
EC version if available
battery FW version if available
```

今回のデータにBIOS/EC/FW versionがなければ、それは明示する。

### 14.2 methods

```text
Beta-binomial empirical Bayes shrinkage
Fisher exact test + BH correction
monthly control chart of FW candidates by group
case-control table for top groups
```

出力には `n_total`, `n_candidate`, `raw_rate`, `shrunk_rate`, `CI`, `q_value` を含める。

分類にはHWを使っていないことをコード上assertする。

---

## 15. Plots, all dpi=300

最低限以下を作成する。

### 15.1 dataset / window coverage

```text
rolling_window_user_coverage.png
window_data_quality_counts.png
window_sample_interval_distribution.png
```

### 15.2 episode / response

```text
rolling_episode_counts_by_threshold.png
response_delay_cdf_online.png
episode_quality_gap_sensitivity_online.png
censored_pending_counts_over_time.png
```

### 15.3 ML response model

```text
episode_response_model_roc_pr.png
episode_response_model_calibration.png
episode_response_model_feature_importance.png
p_response_distribution_by_observed_status.png
```

### 15.4 anomaly scores

```text
fw_response_anomaly_score_distribution.png
p_all_no_response_distribution.png
expected_vs_observed_response_by_window.png
score_vs_complete_opportunities.png
conformal_pvalue_distribution.png
```

### 15.5 usage clustering

```text
usage_cluster_profile_heatmap.png
usage_cluster_counts.png
usage_cluster_umap_or_pca.png
cluster_action_hint_distribution.png
```

UMAPがなければPCAでよい。

### 15.6 online/backtest

```text
online_latest_funnel_counts.png
online_label_counts.png
stateful_vs_stateless_counts.png
time_to_first_alert_fw_proxy.png
time_to_first_alert_gauge_proxy.png
topn_yield_curve_fw_proxy.png
topn_yield_curve_gauge_proxy.png
active_false_alert_rate_over_time.png
watch_to_action_transition_matrix.png
```

### 15.7 enrichment

```text
online_hardware_enrichment_fw_candidates.png
top_fru_case_control_online.png
```

### 15.8 example users

各カテゴリ上位10〜20人の時系列プロット。

```text
examples_fw_check_candidates/*.png
examples_gauge_reset_candidates/*.png
examples_watch_large_gap/*.png
examples_normal_responding/*.png
```

各図に以下を表示する。

```text
RSOC trajectory
FCC trajectory
cycleCount
AC/DC if available
learning episodes
FCC effective change points
pending/censored/no_response markers
window label/stateful label/score
```

---

## 16. Tests

`tests/test_fcc_online_sliding30.py` を追加し、少なくとも以下を確認する。

1. high→low→high episode抽出が正しい。
2. episodeが30日window境界をまたいでも、partial episode stateによりstateful detectorで検出できる。
3. stateless detectorではwindow外startのepisodeを検出しない、または別flagになる。
4. `episode_end + 72h` がcurrent timeを超える場合、`censored` になり `no_response` に混ざらない。
5. large-gap episodeはOK opportunityに数えない。
6. 同じepisodeがsliding windowで複数回現れてもstateに二重加算されない。
7. FCC effective change発生時にsince-last-FCC countersがresetされる。
8. micro FCC stepが `abs_ge_50mWh` ではresponseにならず、`any_change` ではresponseになる。
9. `device_model`, `batt_vendor`, `batt_fru`, `serialNumber`, `UUID`, `final_label` がML feature matrixに入らない。
10. GroupKFold by userで同一userがtrain/testに跨がらない。
11. `p_all_no_response = Π(1-p_i)` が正しい。p_i clippingもテスト。
12. calibration/conformal p-valueが単調なscoreに対して妥当。
13. alert cooldownが同一userの連続同一alertを抑制する。
14. data quality reviewがactionableより優先される。
15. zero-opportunity windowでFW anomaly scoreが不正に高くならない。

既存テストも全て通す。

---

## 17. Report structure

`data/reports/fcc_online_sliding30_ml_detection_report.md` に以下を含める。

```text
1. Executive summary
2. 30日sliding window制約と今回の設計変更
3. 過去知見: very_stale直接予測が不適切な理由
4. データと変数定義
5. rolling window特徴量定義
6. episode/stateful detector設計
7. effective FCC step定義と感度
8. 教師なし使用クラスタリング結果
9. self-supervised episode response model結果
10. user-window anomaly score設計と分布
11. online stateful action policy
12. backtest結果: stateful vs stateless
13. final検証版labelをproxyにした比較
14. active false alert / watch-to-action / lead time / top-N yield
15. large-gap/censored safety audit
16. HW/FW enrichment: 分類には使わず、検出後偏在としてのみ扱う
17. 最新snapshotのaction候補リスト
18. 運用提案: alert cooldown, post-intervention monitoring, required additional data
19. 限界: FW不良断定ではない、30日windowとstate保持の制約、proxy評価であること
20. Next steps
```

---

## 18. Acceptance criteria

完了条件:

```text
1. End-to-end CLIがエラーなく実行される。
2. 全user-windowにwindow labelが付く。
3. 最新snapshotで全752ユーザーにstateful label/recommended actionが付く。
4. raw 30日window + stateだけを推論入力とするbacktestが実装されている。
5. stateless版とstateful版の比較が出力されている。
6. episode response modelがGroupKFold by userで評価され、metricsとcalibration plotが出力される。
7. model feature listにHW/ID/final labels/future featuresが入っていないことをコードassertしている。
8. censored/unknownがno_responseに混ざっていない。
9. large-gap episodeがOK opportunityに混ざっていない。
10. 同じepisodeがstateに二重加算されていない。
11. usage clusteringが完走し、cluster profileが出力されている。
12. p_all_no_response / expected_response / observed_response / conformal_p がuser-windowごとに出力される。
13. final検証版ラベルをproxyとしたbacktest summaryが出る。
14. HW enrichmentは分類後のみ実施されている。
15. 全plotがdpi=300で保存される。
16. Reportが生成される。
17. testsが全て通る。
18. 失敗・不足・依存関係欠落があればreportに明記される。
```

---

## 19. 期待される最終メッセージ

実行完了後、以下を簡潔に報告する。

```text
- 最新snapshotの人数: Normal / Gauge / FW / Watch / Review
- stateful detectorがstateless detectorよりどれだけ検出力を改善したか
- episode response modelのROC AUC / PR AUC / Brier / calibration所見
- FW候補上位の根拠: p_all_no_response, expected vs observed, opportunities, days/cycles since FCC update
- Gauge候補上位の根拠: insufficient opportunity, usage cluster, days/cycles since FCC update
- final検証版proxyとの一致/不一致
- active false alertがあるか
- HW/FW enrichmentの上位group
- 運用上必要な追加データ: BIOS/EC/Battery FW version, update date, gauge reset date, post-intervention FCC response
```

