# Claude Code Prompt: FCC Learning Opportunity Action Classifier — Final Validation, Threshold Justification, and ML Shadow Analysis

あなたは `battery-usage-ai` リポジトリで作業するシニアデータサイエンティスト兼Pythonエンジニアです。既存の `battery_usage/` スタイルに厳密に合わせ、既存成果物を壊さず、FCC/SoH凍結ユーザーに対する最終アクション分類を完成させてください。

## 0. 背景と目的

目的は、ThinkPad バッテリーテレメトリから `fullChargeCapacity`(FCC)/SoH が変化しない、またはほとんど変化していないユーザーを抽出し、次の介入アクションに分類することです。

- `ACTION_GAUGE_RESET`: FCC再学習に十分な学習機会が確認できない。OEM推奨のゲージリセット/キャリブレーションを促す。
- `ACTION_FW_CHECK`: 深い放電→再充電の学習機会が複数回確認されるのにFCCが応答していない。BIOS/EC/バッテリー関連FW version確認とupdate有無確認を促す。
- `ACTION_MONITOR_OR_MANUAL_REVIEW`: 証拠が境界的、またはlarge-gapなどで判定を保留。
- `ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW`: 観測期間不足、カウンタリセット、ログ疎、データ品質不足。
- `ACTION_NONE`: 正常またはFCC応答あり。

これは「FW不良を断定する分類」ではありません。データ単体ではFW/BIOS/EC versionおよびupdate適用有無は確認できません。最終出力は「次に取るべき確認・介入アクション」を与える監査ロジックです。

重要制約:

- 分類ルールに `device_model`, `batt_vendor`, `batt_fru`, `manufacturer`, `design_capacity`, MTM, UUID, serialを使わない。
- それらのハードウェア識別子は分類後の偏在分析、case-control設計、調査優先順位付けにのみ使う。
- 予測MLでラベルを置き換えない。MLは閾値妥当性・期待応答率・watch優先順位付けの補助としてのみ使う。
- 図はすべて `dpi=300` で保存する。
- 最終CSVは全752ユーザーに相互排他ラベルを付け、合計が必ず752になる。

最初に必ず以下を読む:

- `PROJECT_STATUS.md`
- `data/reports/fcc_learning_action_report.md` または現行の `fcc_learning_action_report.md`
- 既存コード:
  - `battery_usage/fcc_learning.py`
  - `battery_usage/fcc_action_classifier.py`
  - `analyze_fcc_learning_actions.py`
  - `plot_fcc_learning_actions.py`
  - `tests/test_fcc_learning.py`

入力データ候補:

- `data/processed/battery_timeseries_all.parquet`
- `data/processed/user_master.csv` があれば結合
- `data/processed/soh_update_status.csv` があれば照合
- `data/processed/soh_reason_features.csv` があれば照合・補助特徴量に使う
- 既存の `data/processed/fcc_learning_*.csv` があればbaseline比較に使う

## 1. 今回の必須修正

### 1.1 ラベル名の修正

現行の

```text
ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY
```

は強すぎるため、最終版では次にrenameする。

```text
ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY
```

意味は「学習機会が完全にゼロ」ではなく、「FCC再学習に十分な深い放電→再充電機会が確認できない」です。

互換性のため、旧ラベルとの対応表を `data/processed/fcc_label_name_mapping.csv` に出力する。

### 1.2 episode response window の右打ち切り処理

`episode_end + window` がユーザーの `last_ts` を超える場合、そのwindowの無応答判定はできない。以下の列をepisode単位で追加する。

```text
window_24h_complete
window_72h_complete
window_168h_complete
fcc_changed_24h
fcc_changed_72h
fcc_changed_168h
fcc_response_status_24h: responded / no_response / censored / unknown
fcc_response_status_72h: responded / no_response / censored / unknown
fcc_response_status_168h: responded / no_response / censored / unknown
```

ルール:

- complete windowかつFCC変化あり → `responded`
- complete windowかつFCC変化なし → `no_response`
- window未完了 → `censored`
- FCC/RSOC欠損等で判断不能 → `unknown`
- `censored` と `unknown` を `no_response` として扱ってはいけない。

FW_CHECK判定では、主判定として `episode_quality == ok` かつ `window_72h_complete == True` のepisodeのみを無応答証拠に使う。

### 1.3 large-gap opportunity の扱いを明示

現状はOK episodeを主判定に使うが、large-gapが多い可能性がある。ユーザー単位・tail単位で以下を追加する。

```text
total_n_80_20_80_ok
total_n_80_20_80_large_gap
total_n_80_20_80_any
total_n_90_10_90_ok
total_n_90_10_90_large_gap
total_n_90_10_90_any
tail_n_80_20_80_ok
tail_n_80_20_80_large_gap
tail_n_80_20_80_any
tail_n_90_10_90_ok
tail_n_90_10_90_large_gap
tail_n_90_10_90_any
```

GAUGE_RESET high confidenceは次を満たす場合に限る。

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 120
and tail_n_80_20_80_ok == 0
and tail_n_90_10_90_ok == 0
and tail_n_80_20_80_large_gap == 0
and tail_n_90_10_90_large_gap == 0
and (
    tail_cycle_delta < 20
    or tail_min_rsoc > 20
    or tail_rsoc_swing < 60
    or tail_ac_time_ratio >= 0.80
)
and data_quality_label == QUALITY_OK
```

OK episodeは0だがlarge-gap episodeがある場合は、即GAUGE_RESETにせず、以下に落とす。

```text
WATCH_POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS
```

または、最終ラベルは `WATCH_LOW_UPDATE_RATE_AMBIGUOUS` のままでもよいが、必ず `watch_subreason = POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS` を付ける。

### 1.4 tail response rate のトートロジー回避

tailは「最後のFCC更新以降」なので、tail内のresponse_rateは構造的に0になりやすい。したがって、最終版ではresponse rateだけを主図にしない。

追加する主要特徴量:

```text
tail_n_unresponded_80_20_80_complete_window
tail_n_unresponded_90_10_90_complete_window
tail_n_censored_80_20_80
tail_n_censored_90_10_90
```

主要プロットは以下に変更する。

```text
x = tail_n_unresponded_80_20_80_complete_window
y = tail_cycle_delta
color = final_label
size = flat_tail_days
```

別図として、

```text
x = tail_n_80_20_80_ok
y = flat_tail_days
color = final_label
size = tail_cycle_delta
```

も作る。

### 1.5 REVIEWを細分化

最終ラベルは相互排他のまま `REVIEW_INSUFFICIENT_DATA` でよいが、必ず `review_subreason` と `review_priority` を出力する。

`review_subreason` 候補:

```text
REVIEW_COUNTER_RESET
REVIEW_SPARSE_LOG
REVIEW_SHORT_OBS_ACTIVE_LIKE
REVIEW_SHORT_OBS_STALE_OR_VERY_STALE
REVIEW_NO_LOW_CHANGE_BUT_INSUFFICIENT_DATA
REVIEW_OTHER_INSUFFICIENT_DATA
```

優先度:

```text
high: stale/very_stale相当、またはfcc_no_or_low_change_candidate、またはcounter reset
medium: sparse log、borderline
low: short observationだがactive-like
```

出力CSVに必ず以下を含める。

```text
review_subreason
review_priority
manual_review_reason
```

### 1.6 effective FCC step 感度分析

FCCは整数mWhでstepするが、微小ステップだけで更新ありとみなすと、更新率評価が過敏になる可能性がある。現行の `any integer change` は維持しつつ、感度分析として以下の有効ステップ定義を追加する。

```text
any_change
abs_ge_50mWh
abs_ge_100mWh
abs_ge_0p1pct_design
abs_ge_0p5pct_design
```

各定義で以下を再計算する。

```text
fcc_changes
fcc_changes_per_100_cycles
fcc_change_rate_per_100d
flat_tail_days
fcc_no_or_low_change_candidate
final_label
```

出力:

```text
data/processed/fcc_effective_step_sensitivity.csv
```

図:

```text
data/reports/figures/fcc_final_thresholds/effective_fcc_step_sensitivity.png
```

### 1.7 テスト追加

`tests/test_fcc_learning.py` または新規 `tests/test_fcc_final_validation.py` に追加する。

必須ケース:

1. `episode_end + 72h > last_ts` は `censored` になり、`no_response` として数えられない。
2. OK episode 0、large_gap episode >0 のユーザーはGAUGE_RESET high confidenceにならない。
3. `tail_n_80_20_80_ok > 0` かつ complete no-response がある場合、GAUGE_RESETではなくFWまたはWATCHに落ちる。
4. effective FCC step thresholdの境界: 49mWh, 50mWh, 99mWh, 100mWh。
5. duplicate timestampでもstable sortで結果が決定的。
6. active userがGAUGE/FWに誤分類されない回帰テスト。
7. final_labelの合計が全ユーザー数と一致し、相互排他である。

## 2. 閾値の説明責任を作る解析

他社に閾値根拠を説明できるよう、閾値は「経験則」ではなく、以下のデータ駆動根拠で説明する。

### 2.1 Active reference cohort と更新率p05/p10

Active reference cohort:

```text
obs_days >= 180
cycle_delta >= 20
flat_tail_days < 60
data_quality_label == QUALITY_OK
```

この群を「最近FCC応答がある正常参照群」として使い、以下の分布を作る。

```text
fcc_changes_per_100_cycles
fcc_change_rate_per_100d
```

p05をdefault候補閾値にする理由:

- active referenceの下位5%を下回る更新頻度は、正常応答群の中でも非常に稀。
- p10は感度分析として使い、候補数は増えるがFW_CHECK規模が大きく変わらないか確認する。
- p05/p10の比較でactionable対象の安定性を示す。

出力:

```text
data/processed/fcc_threshold_reference_quantiles.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/reference_update_rate_distribution_per_cycle.png
data/reports/figures/fcc_final_thresholds/reference_update_rate_distribution_per_100d.png
```

図の要件:

- histogram + ECDFを別々または1枚内に表示。
- p05/p10を縦線で示す。
- active reference、no/low candidates、normal/respondingを比較できるようにする。
- caption用の短い解釈テキストをreportに入れる。

### 2.2 flat_tail 60/120/180日の根拠

既存分類では active <60日, stale 60–180日, very_stale >=180日が使われている。最終アクションでは:

- 60日: warning / active境界
- 120日: gauge reset medium/highの下限候補
- 180日: FW high confidenceまたはvery_stale相当

として扱う。

やること:

- `flat_tail_days` 分布をstatus/label別に描く。
- 60/120/180日線を入れる。
- 閾値を60/120/180で振った感度分析を出す。
- 旧`soh_update_status`との照合を出す。

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/flat_tail_distribution_with_thresholds.png
data/reports/figures/fcc_final_thresholds/flat_tail_sensitivity_label_counts.png
```

### 2.3 response window 72hの根拠

`24h`, `72h`, `168h` の各windowについて、active referenceまたはresponding episodesで、episode endからFCC changeまでのdelayを集計する。

やること:

- complete windowのみで解析する。
- 応答したepisodeのdelay分布を作る。
- CDFに24/72/168hの縦線を入れる。
- 72hで応答の何%を捕捉するかを計算する。
- 24/72/168でfinal labelがどれだけ変わるかを表とplotで示す。

出力:

```text
data/processed/fcc_response_delay_distribution.csv
data/processed/fcc_response_window_sensitivity.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/response_delay_cdf_24_72_168.png
data/reports/figures/fcc_final_thresholds/response_window_sensitivity_counts.png
```

### 2.4 学習機会閾値 80/20/80, 85/15/85, 90/10/90の根拠

3閾値について以下を比較する。

```text
n_episodes
n_ok
n_large_gap
n_users_with_ok
ok_response_rate_72h
n_users_with_tail_opportunities
n_fw_check_if_used_as_primary
n_gauge_reset_if_used_as_no_opportunity_gate
```

説明方針:

- 90/10/90: 厳格。高信頼だが取り逃がしが多い。
- 85/15/85: 中間。
- 80/20/80: 主判定。ユーザー数・episode数が多く、深い放電→再充電機会を実用上拾える。
- ただしFW high confidenceでは、80/20/80の複数回無応答または90/10/90の強い証拠を組み合わせる。

注意:

- 現行の `tail_n_90_10_90_ok >= 1` がFW high confidenceとして強すぎないか、データで再評価する。
- active referenceで `k`回のstrict episode後に全部無応答となる経験確率を計算し、必要なら `tail_n_90_10_90_ok >= 2` に変更する。
- 最終閾値は「empirical false-alarm proxy <= 5%」を目安に選ぶ。ただし件数が少ない場合はWilson CIも併記し、過剰に機械的に決めない。

出力:

```text
data/processed/fcc_learning_threshold_tradeoff.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/learning_threshold_tradeoff.png
data/reports/figures/fcc_final_thresholds/learning_threshold_user_coverage_vs_response.png
```

### 2.5 無応答episode数 k の根拠

主に80/20/80 complete OK episodesを使い、active referenceまたはnormal/responding群で、k回連続無応答となる経験確率を推定する。

やること:

- k=1,2,3,4,5について、user-levelまたはbootstrapで `P(no response in k complete OK episodes)` を推定する。
- 単純理論値 `(1 - response_rate)^k` も補助線として出す。
- empirical false-alarm proxyが5%前後以下になるkを推奨する。
- 現行 `tail_n_80_20_80_ok >= 3` の妥当性を検証する。

出力:

```text
data/processed/fcc_no_response_k_justification.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/no_response_probability_by_k.png
```

### 2.6 tail_cycle_delta 20/30/50 cyclesの根拠

やること:

- active referenceで「FCC更新間に何cycle進むか」の分布を作る。
- stale/very_stale候補でtail_cycle_deltaの分布を作る。
- 20/30/50を比較し、30をdefaultにするなら、どの分位・運用リスクに相当するかを明記する。
- 30がデータに合わない場合は、データ駆動でより説明しやすい値に変更してよい。ただし変更理由をreportに明記する。

出力:

```text
data/processed/fcc_tail_cycle_threshold_justification.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/tail_cycle_delta_distribution_with_thresholds.png
data/reports/figures/fcc_final_thresholds/cycles_between_fcc_updates_active_reference.png
```

### 2.7 AC-bound 0.80、low-cycle、shallow-rangeの根拠

AC-bound:

- `tail_ac_time_ratio >= 0.80` を使う。
- 0.70/0.80/0.90の感度分析を行う。
- active/reference/no-opportunity/gauge candidatesで分布を比較する。

Shallow-range:

- `tail_min_rsoc > 20` は80/20/80のlow到達不能を意味するため定義的根拠あり。
- `tail_rsoc_swing < 60` は80→20の60ポイントレンジを満たさないため定義的根拠あり。

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/ac_time_ratio_distribution_with_080.png
data/reports/figures/fcc_final_thresholds/shallow_range_thresholds_tail_min_rsoc_swing.png
```

### 2.8 episode quality max-gap 12hの根拠

主判定のOK episodeは `max_gap_h <= 12` を使う。これが妥当か検証する。

やること:

- `max_gap_h` 分布を描く。
- 6h/12h/24h基準でOK episode数、ユーザーcoverage、response rate、final label countsを比較する。
- large-gapを含む/含まないでGAUGE/FW/WATCHがどう変わるかを出す。

出力:

```text
data/processed/fcc_episode_quality_gap_sensitivity.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/episode_max_gap_distribution.png
data/reports/figures/fcc_final_thresholds/episode_gap_threshold_sensitivity.png
data/reports/figures/fcc_final_thresholds/large_gap_opportunity_audit.png
```

## 3. 最終ラベルロジック

### 3.1 final_label 候補

相互排他の `final_label` は以下に統一する。

```text
REVIEW_INSUFFICIENT_DATA
NORMAL_OR_RESPONDING
ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE
ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY
WATCH_LOW_UPDATE_RATE_AMBIGUOUS
```

補助列として以下を持つ。

```text
recommended_action
confidence: high / medium / low / review
primary_reason
subreason
watch_subreason
review_subreason
review_priority
threshold_version
rule_version
label_version
```

### 3.2 適用順

```text
1. REVIEW_INSUFFICIENT_DATA
2. NORMAL_OR_RESPONDING
3. ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE
4. ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY
5. WATCH_LOW_UPDATE_RATE_AMBIGUOUS
```

FWをGAUGEより先に解決する理由:

- 学習機会あり・無応答を誤って「まず放電してください」に回さないため。
- GAUGE high confidenceはlarge-gapを含めて学習機会が確認されないことを要件にするため、FW high confidenceと衝突しない。

### 3.3 FW_CHECK high confidence

初期案:

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 180
and tail_cycle_delta >= 30
and (
    tail_n_unresponded_80_20_80_complete_window >= 3
    or tail_n_unresponded_90_10_90_complete_window >= K_STRICT
)
and data_quality_label == QUALITY_OK
```

`K_STRICT` は固定せず、2.4/2.5の分析で決める。初期値は2。もし経験的false-alarm proxyが十分低ければ1でも可。ただしreportに根拠を明記する。

subreason:

```text
ZERO_UPDATE_AFTER_OPPORTUNITIES
TERMINAL_FREEZE_AFTER_OPPORTUNITIES
LOW_UPDATE_RATE_WITH_OPPORTUNITIES
```

### 3.4 GAUGE_RESET high confidence

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 120
and tail_n_80_20_80_ok == 0
and tail_n_90_10_90_ok == 0
and tail_n_80_20_80_large_gap == 0
and tail_n_90_10_90_large_gap == 0
and (
    tail_cycle_delta < 20
    or tail_min_rsoc > 20
    or tail_rsoc_swing < 60
    or tail_ac_time_ratio >= 0.80
)
and data_quality_label == QUALITY_OK
```

subreasonは重複可で出力する。

```text
NO_OPPORTUNITY_AC_BOUND
NO_OPPORTUNITY_LOW_CYCLING
NO_OPPORTUNITY_SHALLOW_RANGE
```

ただしlabel名は `INSUFFICIENT_LEARNING_OPPORTUNITY` とする。

### 3.5 WATCH

以下のように細分化する。

```text
WATCH_POSSIBLE_OPPORTUNITY_WITH_LARGE_GAPS
WATCH_INSUFFICIENT_COMPLETE_WINDOWS
WATCH_LOW_UPDATE_RATE_BUT_SOME_RESPONSE
WATCH_BORDERLINE_FLAT_TAIL_OR_CYCLES
WATCH_ACTIVE_LOW_CADENCE
WATCH_OTHER_AMBIGUOUS
```

## 4. 閾値説明用plot一覧

すべて `dpi=300`, `bbox_inches="tight"` で保存する。matplotlibを使う。プロジェクト既存のCJKフォント対応を踏襲する。可能ならPDF/SVGも併せて保存するが、最低PNGは必須。

出力先:

```text
data/reports/figures/fcc_final_thresholds/
```

必須plot:

1. `reference_update_rate_distribution_per_cycle.png`
2. `reference_update_rate_distribution_per_100d.png`
3. `flat_tail_distribution_with_thresholds.png`
4. `flat_tail_sensitivity_label_counts.png`
5. `response_delay_cdf_24_72_168.png`
6. `response_window_sensitivity_counts.png`
7. `learning_threshold_tradeoff.png`
8. `learning_threshold_user_coverage_vs_response.png`
9. `no_response_probability_by_k.png`
10. `tail_cycle_delta_distribution_with_thresholds.png`
11. `cycles_between_fcc_updates_active_reference.png`
12. `ac_time_ratio_distribution_with_080.png`
13. `shallow_range_thresholds_tail_min_rsoc_swing.png`
14. `episode_max_gap_distribution.png`
15. `episode_gap_threshold_sensitivity.png`
16. `large_gap_opportunity_audit.png`
17. `effective_fcc_step_sensitivity.png`
18. `tail_unresponded_opportunities_vs_cycles_final.png`
19. `tail_opportunities_vs_flat_tail_final.png`
20. `label_transition_baseline_to_final_heatmap.png`
21. `review_subgroup_counts.png`
22. `final_funnel_counts.png`
23. `final_label_counts.png`
24. `hardware_enrichment_empirical_bayes_fw_check.png`
25. `fru_5B10W13975_case_control_summary.png` if the FRU exists in the data

## 5. ハードウェア偏在の最終分析

分類にhardware識別子は使わないが、分類後のFW調査優先順位として以下を出す。

### 5.1 Empirical Bayes / Beta-binomial shrinkage

`device_model`, `batt_vendor`, `batt_fru` それぞれについて、FW_CHECK率とGAUGE_RESET率を集計し、raw rateだけでなくbeta-binomial shrinkageまたはEmpirical Bayesで補正率と95% credible intervalを出す。

出力:

```text
data/processed/fcc_final_hardware_enrichment_empirical_bayes.csv
```

列:

```text
group_type
value
n_total
n_fw_check
n_gauge_reset
raw_fw_check_rate
shrunk_fw_check_rate
fw_check_ci_low
fw_check_ci_high
n_gauge_reset
raw_gauge_reset_rate
shrunk_gauge_reset_rate
gauge_reset_ci_low
gauge_reset_ci_high
rank_fw_check_shrunk
rank_gauge_reset_shrunk
```

### 5.2 多重検定つき探索分析

Fisher exact testまたはロジスティック回帰で、FW_CHECKと各groupの関連を探索する。Benjamini-HochbergでFDR補正する。ただしreportには以下を明記する。

- これは原因断定ではなく、FW version確認・case-control調査の優先順位付け。
- 母数が小さいgroupのraw rateは過大評価しやすい。
- 分類ルールにはhardware識別子を使っていない。

## 6. ML要素: shadow analysisとして追加する

機械学習はラベル決定に使わない。閾値説明・外部説明・watch優先順位付けの補助として、以下を実装する。

### 6.1 Episode-level FCC response model

目的:

```text
学習機会episodeに対して、通常ならFCCが応答する確率 P(FCC response within 72h) を推定する。
```

データ:

- 1行=1episode。
- main training dataは `episode_quality == ok` かつ `window_72h_complete == True`。
- target: `fcc_changed_72h`。
- `censored`, `unknown`, `large_gap` はmain trainingから除外。感度分析でlarge_gap込みも実施。
- Group splitは `user_id` 単位。episode単位で同一userがtrain/testにまたがらないよう `GroupKFold` または `GroupShuffleSplit` を使う。

特徴量候補、すべてepisode開始時点またはepisode中に観測可能なものに限定:

```text
threshold_name one-hot
start_rsoc
low_rsoc
end_rsoc
rsoc_depth = start_rsoc - low_rsoc
episode_duration_h
discharge_duration_h
recharge_duration_h
cycle_delta_episode
ac_ratio_episode
charge_ratio_episode
discharge_ratio_episode
time_since_last_fcc_change_before_episode_h
fcc_value_before_episode
soh_before_episode if design capacity available
cycle_count_before_episode
obs_age_days_at_episode
recent_ac_time_ratio_before_episode
recent_rsoc_swing_before_episode
```

禁止特徴量:

```text
fcc_changed_*, response_status_*, final_label, subreason, future FCC, future cycle, device_model, batt_vendor, batt_fru, manufacturer, MTM, UUID, serialNumber
```

モデル:

1. primary: LogisticRegression with standardization and class_weight if needed。
2. optional: HistGradientBoostingClassifier or XGBoost if available。XGBoostがなければskipしてよい。
3. evaluation: ROC AUC, PR AUC, Brier score, calibration curve, reliability diagram, coefficient plotまたはfeature importance。

出力:

```text
data/processed/fcc_episode_response_model_predictions.csv
data/processed/fcc_episode_response_model_metrics.csv
data/processed/fcc_user_expected_response_residuals.csv
```

ユーザー単位のshadow score:

```text
expected_tail_responses_72h = sum(predicted_response_prob for tail complete OK episodes)
observed_tail_responses_72h = sum(actual response)
response_residual = observed - expected
response_residual_z = (observed - expected) / sqrt(sum(p*(1-p)))
ml_fw_support_score_0_100 = monotonic transform of negative residual and number of opportunities
```

使い方:

- `ml_fw_support_score_0_100` はラベル決定には使わない。
- `ACTION_FW_CHECK` の中で優先順位付けに使う。
- `WATCH` の中でFW寄りかGAUGE寄りかの補助に使う。
- reportでは「ML shadow support」と明記する。

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/ml_response_model_roc_pr.png
data/reports/figures/fcc_final_thresholds/ml_response_model_calibration.png
data/reports/figures/fcc_final_thresholds/ml_response_model_coefficients.png
data/reports/figures/fcc_final_thresholds/ml_expected_vs_observed_tail_response.png
data/reports/figures/fcc_final_thresholds/ml_residual_by_final_label.png
```

### 6.2 Unsupervised clustering for WATCH/no-low candidates

目的:

```text
WATCHやno/low候補を、AC-bound / shallow-range / high-opportunity-no-response / sparse/censored などの構造に分ける。
```

対象:

```text
final_label in {WATCH_LOW_UPDATE_RATE_AMBIGUOUS, ACTIONABLE_GAUGE_RESET_*, ACTIONABLE_FW_CHECK_*}
```

特徴量:

```text
flat_tail_days
tail_cycle_delta
tail_ac_time_ratio
tail_min_rsoc
tail_rsoc_swing
tail_n_80_20_80_ok
tail_n_80_20_80_large_gap
tail_n_unresponded_80_20_80_complete_window
fcc_changes_per_100_cycles
fcc_change_rate_per_100d
```

モデル:

- StandardScaler + HDBSCAN if installed, otherwise KMeans/GaussianMixture with silhouette/BIC for k=2..6。
- これは分類を変更しない。`cluster_id`, `cluster_description` を補助列として出す。

出力:

```text
data/processed/fcc_no_low_candidate_clusters.csv
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/watch_candidate_cluster_pca.png
data/reports/figures/fcc_final_thresholds/watch_candidate_cluster_feature_means.png
```

### 6.3 Surrogate decision tree for external explanation

最終ルールベースラベルを教師ラベルとして、浅い決定木を訓練し、外部説明用の「ルールがどの特徴量で分岐しているか」を可視化する。

注意:

- これは分類器ではなく説明用surrogate。
- 学習にハードウェア識別子は禁止。
- depth=3程度に制限。
- fidelity、つまりrule labelとの一致率をreportする。

出力:

```text
data/processed/fcc_action_surrogate_tree_rules.txt
```

図 `dpi=300`:

```text
data/reports/figures/fcc_final_thresholds/surrogate_decision_tree.png
```

## 7. 最終CSV出力

出力先:

```text
data/processed/fcc_final_learning_episodes.csv
data/processed/fcc_final_user_features.csv
data/processed/fcc_final_action_labels.csv
data/processed/fcc_final_intervention_targets_gauge_reset.csv
data/processed/fcc_final_intervention_targets_fw_check.csv
data/processed/fcc_final_watchlist.csv
data/processed/fcc_final_review_queue.csv
data/processed/fcc_final_threshold_justification_summary.csv
data/processed/fcc_final_sensitivity_grid.csv
data/processed/fcc_final_hardware_enrichment_empirical_bayes.csv
data/processed/fcc_final_ml_shadow_scores.csv
```

`fcc_final_action_labels.csv` 必須列:

```text
analysis_timestamp
user_id
final_label
recommended_action
confidence
primary_reason
subreason
watch_subreason
review_subreason
review_priority
fcc_no_or_low_change_candidate
no_fcc_update
long_terminal_flat
low_update_per_cycle
low_update_per_time
fcc_changes
fcc_effective_changes_50mwh
fcc_effective_changes_100mwh
fcc_changes_per_100_cycles
fcc_change_rate_per_100d
flat_tail_days
obs_days
cycle_delta
tail_days
tail_cycle_delta
tail_min_rsoc
tail_max_rsoc
tail_rsoc_swing
tail_ac_time_ratio
tail_n_80_20_80_ok
tail_n_80_20_80_large_gap
tail_n_80_20_80_any
tail_n_90_10_90_ok
tail_n_90_10_90_large_gap
tail_n_90_10_90_any
tail_n_unresponded_80_20_80_complete_window
tail_n_unresponded_90_10_90_complete_window
tail_n_censored_80_20_80
tail_n_censored_90_10_90
expected_tail_responses_72h
observed_tail_responses_72h
response_residual_z
ml_fw_support_score_0_100
cluster_id
cluster_description
device_model
batt_vendor
batt_fru
```

注: device_model/vendor/FRUは出力には含めてよいが、分類ルールでは使わない。reportでその旨を明記する。

## 8. 最終レポート

出力:

```text
data/reports/fcc_final_learning_action_report.md
```

構成:

1. Executive summary
2. 目的: FCC no/low changeを、学習機会不足と学習機会あり無応答に分け、介入アクションに変換する
3. データと前提
4. データ品質とREVIEW細分化
5. FCC no/low change候補の定義
6. 閾値根拠
   - active reference p05/p10
   - flat_tail 60/120/180
   - response window 72h
   - 80/20/80 vs 85/15/85 vs 90/10/90
   - unresponded opportunity count k
   - tail_cycle_delta 20/30/50
   - AC-bound 0.80
   - shallow-range定義
   - max_gap 12h
   - effective FCC step sensitivity
7. 追加検証での変更点
   - label rename
   - right-censor処理
   - large-gap handling
   - tail response-rate plot廃止/置換
   - review subgrouping
8. 最終ラベル定義
9. 最終ラベル件数とfunnel
10. intervention target lists
11. sensitivity analysisとJaccard stability
12. ML shadow analysis
   - episode response model
   - expected vs observed response residual
   - watch/no-low clustering
   - surrogate decision tree
13. hardware enrichment, empirical Bayes, case-control候補
14. 既存 `soh_update_status` との照合
15. 運用メッセージ案
16. 限界
   - FW不良断定ではない
   - FW/BIOS/EC versionは別途必要
   - ゲージリセットはOEM推奨手順前提
   - 介入後追跡が必要
17. 次に収集すべきデータ

必ず、各閾値について「なぜその閾値か」「データ上どう見えるか」「閾値を振ると結論がどう変わるか」を書く。

## 9. CLI

既存CLIを拡張してよいが、最終版として以下を動かせるようにする。

```bash
python analyze_fcc_learning_actions_final.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --user-master data/processed/user_master.csv \
  --soh-update-status data/processed/soh_update_status.csv \
  --out-dir data/processed \
  --fig-dir data/reports/figures/fcc_final_thresholds \
  --report data/reports/fcc_final_learning_action_report.md \
  --dpi 300
```

plotだけ再実行:

```bash
python plot_fcc_learning_actions_final.py \
  --labels data/processed/fcc_final_action_labels.csv \
  --episodes data/processed/fcc_final_learning_episodes.csv \
  --threshold-summary data/processed/fcc_final_threshold_justification_summary.csv \
  --out-dir data/reports/figures/fcc_final_thresholds \
  --dpi 300
```

ML shadow analysisのみ再実行:

```bash
python analyze_fcc_response_model.py \
  --episodes data/processed/fcc_final_learning_episodes.csv \
  --user-features data/processed/fcc_final_user_features.csv \
  --labels data/processed/fcc_final_action_labels.csv \
  --out-dir data/processed \
  --fig-dir data/reports/figures/fcc_final_thresholds \
  --dpi 300
```

## 10. Acceptance criteria

完了条件:

1. 全752ユーザーに相互排他final_labelが付く。合計が752。
2. `ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY` にrename済み。
3. right-censored episodesが`no_response`に混入していない。
4. large-gap opportunityがGAUGE high confidenceを誤って作らない。
5. REVIEWに`review_subreason`と`review_priority`が付く。
6. active既存statusからGAUGE/FWへの誤分類が0または、もし非0なら全例理由をreportに記載。
7. effective FCC step感度分析がある。
8. 閾値根拠plotがすべてdpi=300で保存されている。
9. ML shadow analysisがラベルを上書きせず、support scoreとして出力されている。
10. hardware識別子が分類ロジックに使われていないことをコードとreportで確認できる。
11. testsがすべて通る。
12. 最終reportに、各閾値の根拠・感度・限界が記載されている。
13. `fcc_final_intervention_targets_gauge_reset.csv` と `fcc_final_intervention_targets_fw_check.csv` が運用に使える列を持つ。
14. baselineからfinalへのlabel transition heatmapが出ている。
15. 生成物一覧をreport末尾に出す。

## 11. 最後に必ず出す短い結論

reportとCLIの最後に、以下の形式で要約を出す。

```text
Final actionable summary:
- Total users: N
- FCC no/low change candidates: N
- Gauge reset / calibration targets: N
- FW/BIOS/EC check targets: N
- Watchlist: N
- Review queue: N
- Main threshold rationale: active-reference p05 update cadence, 72h response delay CDF, empirical no-response probability by k episodes, large-gap/censoring safeguards.
- Important limitation: FW defect is not proven without version/update/intervention follow-up data.
```
