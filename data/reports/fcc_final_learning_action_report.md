# FCC学習機会ベース介入分類 — 最終検証・閾値根拠・MLシャドウ レポート

_analysis_timestamp: 2026-06-03T16:38:27 · users: 752 · episodes: 24,711 · label/rule/threshold version: v2.0-final_

## 1. Executive summary

- 全752ユーザーに相互排他の最終ラベルを付与（合計=752）。
- FCC no/low change候補: **96**。
- ゲージリセット/キャリブレーション対象 (`ACTION_GAUGE_RESET`): **18**。
- FW/BIOS/EC確認対象 (`ACTION_FW_CHECK`): **14**。
- Watchlist: **55** / Review queue: **338** / Normal: **327**。
- 閾値は経験則ではなく、active-reference更新率p05・応答遅延72h CDF・無応答確率(k)・large-gap/打ち切り安全策で根拠付け。
- **限界**: 本データではFW/BIOS/EC versionもupdate適用有無も確認できない。FW不良の断定ではなく確認対象の抽出。

## 2. 目的

FCC/SoHが更新されない/ほぼ更新されないユーザーを抽出し、(a) 学習機会が十分確認できない→ゲージリセット促し、(b) 学習機会があるのにFCC無応答→FW確認促し、に変換する監査ロジック。予測MLはラベルを決めず、閾値説明と優先順位付けのshadowとしてのみ使用。

## 3. データと前提

入力 `battery_timeseries_all.parquet`（3.13M行・752ユーザー）。RSOCは0–100整数で欠損なし、FCCは整数mWhで欠損なし、`serialNumber`不変（パック交換0件）。`device_model/batt_vendor/batt_fru`等のHW識別子は分類ルールに不使用。

## 4. データ品質とREVIEW細分化

- `QUALITY_OK`: 399
- `QUALITY_SHORT_OBS`: 285
- `QUALITY_COUNTER_RESET`: 52
- `QUALITY_SPARSE`: 16


REVIEW内訳 (`review_subreason` × `review_priority`):

| review_subreason | review_priority | n |
| --- | --- | --- |
| REVIEW_COUNTER_RESET | high | 52 |
| REVIEW_NO_LOW_CHANGE_BUT_INSUFFICIENT_DATA | high | 1 |
| REVIEW_SHORT_OBS_ACTIVE_LIKE | low | 274 |
| REVIEW_SHORT_OBS_STALE_OR_VERY_STALE | high | 10 |
| REVIEW_SPARSE_LOG | medium | 1 |

## 5. FCC no/low change候補の定義

active reference cohort = 214人。p05/p10は §6 参照。候補フラグ (`no_fcc_update` ∨ `long_terminal_flat` ∨ `low_update_per_cycle` ∨ `low_update_per_time`) で **96人**。

## 6. 閾値根拠

### 6.1 active reference 更新率 p05/p10

| metric | n_active_reference | p05 | p10 | p25 | p50 | default_used |
| --- | --- | --- | --- | --- | --- | --- |
| fcc_changes_per_100_cycles | 214 | 4.2443 | 16.0253 | 100.0000 | 116.3980 | p05 |
| fcc_change_rate_per_100d | 214 | 1.4109 | 3.1128 | 10.4010 | 22.4715 | p05 |

図: `fcc_final_thresholds/reference_update_rate_distribution_per_cycle.png`, `fcc_final_thresholds/..._per_100d.png`

### 6.2 flat_tail 60/120/180
既存 active(<60)/stale(60–180)/very_stale(>=180) 境界に一致。感度は §11。

### 6.3 response window 72h
応答遅延CDF（応答したOK episode）:

| threshold_name | n_responded_ok | frac_captured_by_24h | frac_captured_by_72h | frac_captured_by_168h |
| --- | --- | --- | --- | --- |
| strict_90_10_90 | 663 | 0.9487 | 0.9653 | 1.0000 |
| primary_80_20_80 | 1684 | 0.9192 | 0.9513 | 1.0000 |
| secondary_85_15_85 | 955 | 0.9319 | 0.9592 | 1.0000 |

→ primary 80/20/80 の応答の大半を72hで捕捉。図 `fcc_final_thresholds/response_delay_cdf_24_72_168.png`。

### 6.4 学習機会帯 80/20/80 vs 85/15/85 vs 90/10/90

| threshold_name | n_episodes | n_ok | n_large_gap | n_users_with_ok | ok_response_rate_72h | n_users_with_tail_opportunities | n_fw_check_if_used_as_primary | n_gauge_reset_if_used_as_no_opportunity_gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strict_90_10_90 | 5750 | 829 | 4921 | 180 | 0.7739 | 15 | 4 | 29 |
| primary_80_20_80 | 11342 | 2319 | 9023 | 294 | 0.6920 | 37 | 16 | 17 |
| secondary_85_15_85 | 7619 | 1249 | 6370 | 218 | 0.7340 | 19 | 8 | 26 |

90/10/90=厳格・高信頼だが取り逃し多、85/15/85=中間、80/20/80=主判定（数が多く実用的）。

### 6.5 無応答エピソード数 k

| band | k | n_users | n_episodes | response_rate_p | p_no_response_theory | p_no_response_bootstrap | boot_ci_lo | boot_ci_hi | false_alarm_proxy_le_5pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| primary_80_20_80 | 1 | 248 | 1728 | 0.8860 | 0.1140 | 0.1148 | 0.0673 | 0.1730 | False |
| primary_80_20_80 | 2 | 248 | 1728 | 0.8860 | 0.0130 | 0.0135 | 0.0043 | 0.0293 | True |
| primary_80_20_80 | 3 | 248 | 1728 | 0.8860 | 0.0015 | 0.0018 | 0.0000 | 0.0060 | True |
| primary_80_20_80 | 4 | 248 | 1728 | 0.8860 | 0.0002 | 0.0002 | 0.0000 | 0.0013 | True |
| primary_80_20_80 | 5 | 248 | 1728 | 0.8860 | 0.0000 | 0.0000 | 0.0000 | 0.0007 | True |

→ primary無応答 k=3、strict(90/10/90) K_STRICT=2 で false-alarm proxy が概ね5%以下。図 `fcc_final_thresholds/no_response_probability_by_k.png`。

### 6.6 tail_cycle_delta 20/30/50

| metric | n | p50 | p75 | p90 | p95 | note |
| --- | --- | --- | --- | --- | --- | --- |
| cycles_between_fcc_updates_active_reference | 214 | 0.860 | 1.000 | 6.320 | 23.570 | FW-high requires tail_cycle_delta >= 30 so a non-update spans well beyond the typical active-reference update gap. |
| candidate_tail_cycle_ge_20 | 96 | 0.510 |  |  |  | share of no/low-change candidates with tail_cycle_delta >= 20 |
| candidate_tail_cycle_ge_30 | 96 | 0.438 |  |  |  | share of no/low-change candidates with tail_cycle_delta >= 30 |
| candidate_tail_cycle_ge_50 | 96 | 0.354 |  |  |  | share of no/low-change candidates with tail_cycle_delta >= 50 |

### 6.7 AC-bound 0.80 / shallow-range
AC>=0.80（感度0.70/0.90）。shallow: min_rsoc>20 または swing<60（80→20の60ptレンジ・low到達の定義的根拠）。

### 6.8 episode max_gap 12h
ロガー約30分間隔。>12hはスリープ欠測でepisode品質低下。感度6/12/24hは §11。

### 6.9 effective FCC step 感度 (1.6)

| step_definition | median_fcc_changes | median_fcc_changes_per_100_cycles | median_fcc_change_rate_per_100d | median_flat_tail_days | n_candidates | n_review | n_normal | n_fw_check | n_gauge_reset | n_watch |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| any_change | 16.000 | 101.246 | 13.966 | 5.100 | 96 | 338 | 327 | 14 | 18 | 55 |
| abs_ge_50mWh | 4.000 | 14.286 | 1.985 | 29.200 | 146 | 338 | 278 | 15 | 39 | 82 |
| abs_ge_100mWh | 3.000 | 12.987 | 1.807 | 31.900 | 150 | 338 | 274 | 15 | 42 | 83 |
| abs_ge_0p1pct_design | 3.000 | 13.383 | 1.845 | 30.500 | 150 | 338 | 274 | 15 | 42 | 83 |
| abs_ge_0p5pct_design | 3.000 | 11.494 | 1.613 | 34.000 | 160 | 338 | 265 | 17 | 43 | 89 |

→ 微小ステップ(<50mWh)を除くとFCC更新回数が減り候補が増えるが、actionable規模の大小関係は保たれる。

## 7. 追加検証での変更点

- ラベル改名 `..._NO_OPPORTUNITY` → `..._INSUFFICIENT_LEARNING_OPPORTUNITY`（対応表 `fcc_label_name_mapping.csv`）。
- 応答窓の右打ち切り: `censored`/`unknown` を `no_response` に混入させない。
- large-gap機会の明示: GAUGE highはok=0かつlarge_gap=0を要件化。large_gapのみ→WATCH。
- tail response-rateのトートロジー回避: 主図を `unresponded_complete_window` 系に変更。
- REVUEW細分化 (`review_subreason`/`review_priority`)。

## 8. 最終ラベル定義

適用順: review > normal > fw_high > gauge_high > fw_medium > gauge_medium > watch。FWはGAUGEより先（機会ありを「まず放電」に回さない）。GAUGE highは機会ゼロ(ok&large_gap)要件なのでFWと衝突しない。

## 9. 最終ラベル件数とfunnel

| final_label | n | pct |
| --- | --- | --- |
| REVIEW_INSUFFICIENT_DATA | 338 | 44.9 |
| NORMAL_OR_RESPONDING | 327 | 43.5 |
| ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE | 14 | 1.9 |
| ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY | 18 | 2.4 |
| WATCH_LOW_UPDATE_RATE_AMBIGUOUS | 55 | 7.3 |

合計=752。funnel: {'all_users': 752, 'candidates': 96, 'gauge_reset': 18, 'fw_check': 14, 'watch': 55, 'review': 338, 'normal': 327}
図 `fcc_final_thresholds/final_funnel_counts.png`, `fcc_final_thresholds/final_label_counts.png`。

## 10. intervention target lists

- `fcc_final_intervention_targets_gauge_reset.csv` (18件)
- `fcc_final_intervention_targets_fw_check.csv` (14件, ml_fw_support_scoreで優先順位付け)
- `fcc_final_watchlist.csv` (55件) / `fcc_final_review_queue.csv` (338件)

## 11. 感度分析とJaccard安定性

| dimension | variant | n_candidates | n_review | n_normal | n_fw_check | n_gauge_reset | n_watch | n_ok_episodes | n_users_with_ok | ok_response_rate_72h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| candidate_pct | p05 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| candidate_pct | p10 | 126 | 338 | 299 | 14 | 19 | 82 |  |  |  |
| flat_tail_days[gauge_hi] | 60 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| flat_tail_days[gauge_hi] | 120 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| flat_tail_days[gauge_hi] | 180 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| response_window | 24h | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| response_window | 72h | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| response_window | 168h | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| ac_time_ratio[gauge_hi] | 0.7 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| ac_time_ratio[gauge_hi] | 0.8 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| ac_time_ratio[gauge_hi] | 0.9 | 96 | 338 | 327 | 14 | 18 | 55 |  |  |  |
| episode_max_gap_h | 6 |  | 338 | 327 | 6 | 18 | 63 | 1620 | 196 | 1 |
| episode_max_gap_h | 12 |  | 338 | 327 | 14 | 18 | 55 | 4397 | 294 | 1 |
| episode_max_gap_h | 24 |  | 338 | 327 | 20 | 18 | 49 | 9823 | 390 | 1 |

FW/GAUGE集合のJaccard安定性（応答窓摂動 vs 既定）:

| perturbation | jaccard_fw | jaccard_gauge |
| --- | --- | --- |
| response_window=24h | 1.0000 | 1.0000 |
| response_window=72h | 1.0000 | 1.0000 |
| response_window=168h | 1.0000 | 1.0000 |

## 12. ML shadow analysis

episode応答モデル（complete OK 72h, GroupKFold by user, 特徴はepisode開始時点のみ・HW識別子禁止）:

| model | n_episodes | n_users | positive_rate | roc_auc | pr_auc | brier |
| --- | --- | --- | --- | --- | --- | --- |
| logreg | 4351 | 289 | 0.7168 | 0.8399 | 0.9052 | 0.1472 |
| hgb | 4351 | 289 | 0.7168 | 0.8992 | 0.9466 | 0.1013 |

サロゲート決定木 fidelity=0.9242（`fcc_action_surrogate_tree_rules.txt`）。クラスタ: `fcc_no_low_candidate_clusters.csv`。ml_fw_support_scoreはラベル決定に使わずFW優先順位付けのshadow。
図 `fcc_final_thresholds/ml_response_model_roc_pr.png` ほか。

## 13. hardware enrichment (Empirical Bayes, case-control候補)

> 分類にHW識別子は不使用。以下は分類後の偏在（FW version確認の優先順位付け）。母数小群のraw率は過大評価に注意。


| group_type | value | n_total | n_fw_check | raw_fw_check_rate | shrunk_fw_check_rate | fw_check_ci_low | fw_check_ci_high | fw_fisher_q_bh |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| batt_fru | 5B10W13975 | 26 | 6 | 0.2308 | 0.1968 | 0.0793 | 0.3513 | 0.0001 |
| batt_fru | (none) | 22 | 3 | 0.1364 | 0.1147 | 0.0261 | 0.2565 | 0.1447 |
| batt_fru | 5B10W13973 | 30 | 2 | 0.0667 | 0.0599 | 0.0081 | 0.1577 | 1.0000 |
| batt_fru | 5B10W51875 | 5 | 0 | 0.0000 | 0.0093 | 0.0000 | 0.0935 | 1.0000 |
| batt_fru | 5B10W51883 | 5 | 0 | 0.0000 | 0.0093 | 0.0000 | 0.0935 | 1.0000 |
| batt_fru | 5B11H56397 | 5 | 0 | 0.0000 | 0.0093 | 0.0000 | 0.0935 | 1.0000 |
| batt_fru | 5B11H56406 | 5 | 0 | 0.0000 | 0.0093 | 0.0000 | 0.0935 | 1.0000 |
| batt_fru | 5B11H56412 | 5 | 0 | 0.0000 | 0.0093 | 0.0000 | 0.0935 | 1.0000 |

図 `fcc_final_thresholds/hardware_enrichment_empirical_bayes_fw_check.png`, `fcc_final_thresholds/fru_5B10W13975_case_control_summary.png`。

## 14. 既存 soh_update_status との照合

- 既存: {'active': 638, 'stale': 59, 'very_stale': 55} / 本再現(flat_tail 60/180): {'active': 639, 'stale': 58, 'very_stale': 55}
- active→actionable 誤分類: **0**件


既存status × 最終ラベル:

| soh_update_status | ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE | ACTIONABLE_GAUGE_RESET_INSUFFICIENT_LEARNING_OPPORTUNITY | NORMAL_OR_RESPONDING | REVIEW_INSUFFICIENT_DATA | WATCH_LOW_UPDATE_RATE_AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| active | 0 | 0 | 302 | 320 | 16 |
| stale | 5 | 9 | 25 | 13 | 7 |
| very_stale | 9 | 9 | 0 | 5 | 32 |

## 15. 運用メッセージ案

- GAUGE: FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会が十分に確認できません（OK品質の機会が無く、large-gapを含めても判定可能な機会がない）。安全な環境でOEM推奨のバッテリーゲージリセット/キャリブレーションを実施し、その後72h〜7日間のテレメトリでFCC更新有無を確認してください。
- FW: FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会（完全窓・OK品質）が複数回確認されるのにFCCが応答していません。BIOS/EC/バッテリー関連FWのVersion確認とアップデート有無確認を優先してください。アップデート後、次回の学習機会後72h〜7日間でFCC更新有無を確認してください。

## 16. 限界

- FW不良の断定ではない。FW/BIOS/EC version・update適用有無は本データで確認不可。
- ゲージリセットはOEM推奨手順前提。実施後72h〜7日の追跡が必要。
- large-gap/打ち切りで判定不能な機会は保守的にWATCHへ。

## 17. 次に収集すべきデータ

BIOS/EC/バッテリーFW version、update適用日時、intervention実施日時、intervention後72h〜7日のFCC更新有無。これらで本監査は「介入→効果」の因果評価へ格上げ可能。


## 生成物一覧

CSV/TXT:
- `data/processed/fcc_final_learning_episodes.csv`
- `data/processed/fcc_final_user_features.csv`
- `data/processed/fcc_final_action_labels.csv`
- `data/processed/fcc_final_intervention_targets_gauge_reset.csv`
- `data/processed/fcc_final_intervention_targets_fw_check.csv`
- `data/processed/fcc_final_watchlist.csv`
- `data/processed/fcc_final_review_queue.csv`
- `data/processed/fcc_label_name_mapping.csv`
- `data/processed/fcc_threshold_reference_quantiles.csv`
- `data/processed/fcc_final_sensitivity_grid.csv`
- `data/processed/fcc_final_jaccard_stability.csv`
- `data/processed/fcc_response_delay_distribution.csv`
- `data/processed/fcc_response_window_sensitivity.csv`
- `data/processed/fcc_learning_threshold_tradeoff.csv`
- `data/processed/fcc_no_response_k_justification.csv`
- `data/processed/fcc_tail_cycle_threshold_justification.csv`
- `data/processed/fcc_effective_step_sensitivity.csv`
- `data/processed/fcc_episode_quality_gap_sensitivity.csv`
- `data/processed/fcc_final_hardware_enrichment_empirical_bayes.csv`
- `data/processed/fcc_final_threshold_justification_summary.csv`
- `data/processed/fcc_final_ml_shadow_scores.csv`
- `data/processed/fcc_episode_response_model_predictions.csv`
- `data/processed/fcc_episode_response_model_metrics.csv`
- `data/processed/fcc_user_expected_response_residuals.csv`
- `data/processed/fcc_no_low_candidate_clusters.csv`
- `data/processed/fcc_action_surrogate_tree_rules.txt`

図 (dpi=300): `C:/Users/you/Desktop/wk/battery-usage-ai/data/reports/figures/fcc_final_thresholds/` 配下（reference/flat_tail/response_delay/learning_tradeoff/no_response_k/tail_cycle/ac/shallow/episode_gap/large_gap/effective_step/final scatters/label_transition/review_subgroup/funnel/label_counts/EB enrichment/FRU case-control/ML/cluster/surrogate)。


## Final actionable summary
```
Final actionable summary:
- Total users: 752
- FCC no/low change candidates: 96
- Gauge reset / calibration targets: 18
- FW/BIOS/EC check targets: 14
- Watchlist: 55
- Review queue: 338
- Main threshold rationale: active-reference p05 update cadence, 72h response delay CDF, empirical no-response probability by k episodes, large-gap/censoring safeguards.
- Important limitation: FW defect is not proven without version/update/intervention follow-up data.
```
