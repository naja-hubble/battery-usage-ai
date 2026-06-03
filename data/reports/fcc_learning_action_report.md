# FCC学習機会ベースの介入対象分類レポート

_analysis_timestamp: 2026-06-03T12:47:30 · users: 752 · episodes: 24,711_

## 1. 目的と前提

本レポートは ThinkPad バッテリーテレメトリから、`fullChargeCapacity`(FCC)/SoH が長期間更新されない（凍結している）ユーザーを抽出し、**介入アクションに直結する監査ロジック**で 2 種に分類する。

- **学習機会なし → ゲージリセット/キャリブレーション促し** (`ACTION_GAUGE_RESET`)
- **学習機会あり・FCC無応答 → FW/BIOS/EC確認促し** (`ACTION_FW_CHECK`)

これは予測モデルではない。既存の教師あり検証で「使用挙動から very_stale を予測」は公平領域で AUC≈0.54（ほぼランダム）と判明しているため、ここでは**学習機会に対してFCCが応答したかを監査**する。

**前提**: SoH は `FCC/DesignCapacity`。FCC は整数 mWh で、ステップしたときのみ SoH が更新される。RSOC=`remainingCapacityInPercentage`。本コホートでは RSOC は 0–100 の整数で欠損なし、FCC も欠損なし、`serialNumber` は全ユーザーで不変（パック交換 0 件）。

**重要**: `device_model` / `batt_vendor` / `batt_fru` は分類ルールに一切使用していない（後述の偏在分析でのみ集計）。

## 2. データ品質確認

ユーザー単位のデータ品質ラベル分布:

- `QUALITY_OK`: 399
- `QUALITY_SHORT_OBS`: 285
- `QUALITY_COUNTER_RESET`: 52
- `QUALITY_SPARSE`: 16


- `obs_days < 120`: 301 人
- `n_samples < 200`: 1 人
- `cycle_decrease_count > 0`（カウンタリセット疑い）: 52 人
- `serial_number_distinct > 1`（パック交換疑い）: 0 人

`QUALITY_OK` 以外でも特徴量は計算するが、最終ラベルでは信頼度を下げるか `REVIEW_INSUFFICIENT_DATA` に回している。

## 3. FCC no/low change 候補の定義

Active reference cohort（`obs_days>=180 & cycle_delta>=20 & flat_tail_days<60 & QUALITY_OK`）= **214 人**。この群から更新率の分位点を算出:

- p05 fcc_changes_per_100_cycles = 4.244, p10 = 16.025
- p05 fcc_change_rate_per_100d = 1.411, p10 = 3.113

候補フラグ（いずれか該当で候補）: `no_fcc_update`(FCC変化0かつobs>=120), `long_terminal_flat`(flat_tail>=180), `low_update_per_cycle`(cycle_delta>=50かつper-cycle更新率<=p05), `low_update_per_time`(obs>=180かつper-100d更新率<=p05)。

**FCC no/low change 候補: 96 人**（内訳は重複あり）:
- no_fcc_update: 27
- long_terminal_flat: 55
- low_update_per_cycle: 49
- low_update_per_time: 72

## 4. 学習機会 episode の定義

RSOC を timestamp でsortし重複は最後の行を採用、状態機械で high→low→high を抽出する。3 種の閾値: `strict_90_10_90` / `primary_80_20_80` / `secondary_85_15_85`。各 episode に対し episode内・end+24h/72h/168h の FCC 応答を判定する（FCC欠損windowは unknown=NaN で 0応答と区別）。主判定は `episode_quality == ok`（最大サンプル間隔<=12h）のみを用い、感度分析で large_gap 込みも見る。

### threshold別 episode サマリ

| threshold_name | n_episodes | n_ok | n_large_gap | n_users_with_ok | ok_response_rate_72h |
| --- | --- | --- | --- | --- | --- |
| strict_90_10_90 | 5750 | 829 | 4921 | 180 | 0.7720 |
| primary_80_20_80 | 11342 | 2319 | 9023 | 294 | 0.6908 |
| secondary_85_15_85 | 7619 | 1249 | 6370 | 218 | 0.7334 |

## 5. 最終ラベル定義と優先順位

相互排他。適用順は **review > normal > fw_high > gauge_high > fw_medium > gauge_medium > watch**。spec 8.3(gauge)→8.4(fw) の列挙順に対し、判別の本質は「学習機会の有無」であるため、同一信頼度帯では 機会ありの FW を先に解決する（gauge_high は機会ゼロが要件のため FW と衝突しない）。詳細は `battery_usage/fcc_action_classifier.py` の docstring を参照。

## 6. ラベル別人数

| final_label | n_users | pct |
| --- | --- | --- |
| REVIEW_INSUFFICIENT_DATA | 338 | 44.9 |
| NORMAL_OR_RESPONDING | 327 | 43.5 |
| ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY | 43 | 5.7 |
| ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE | 20 | 2.7 |
| WATCH_LOW_UPDATE_RATE_AMBIGUOUS | 24 | 3.2 |

合計 = 752（=全 752 ユーザー、相互排他）

## 7. 推奨アクション別人数

- `ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW`: 338
- `ACTION_NONE`: 327
- `ACTION_GAUGE_RESET`: 43
- `ACTION_MONITOR_OR_MANUAL_REVIEW`: 24
- `ACTION_FW_CHECK`: 20


## 8. 閾値感度分析

| dimension | variant | n_candidates | n_review | n_normal | n_gauge_reset | n_fw_check | n_watch |
| --- | --- | --- | --- | --- | --- | --- | --- |
| candidate_pct | p05 | 96 | 338 | 327 | 43 | 20 | 24 |
| candidate_pct | p10 | 126 | 338 | 299 | 51 | 20 | 44 |
| response_window | 24h | 96 | 338 | 327 | 43 | 20 | 24 |
| response_window | 72h | 96 | 338 | 327 | 43 | 20 | 24 |
| response_window | 168h | 96 | 338 | 327 | 43 | 20 | 24 |
| flat_tail_days[fw_hi&gauge_hi] | 60 | 96 | 338 | 327 | 43 | 21 | 23 |
| flat_tail_days[fw_hi&gauge_hi] | 120 | 96 | 338 | 327 | 43 | 20 | 24 |
| flat_tail_days[fw_hi&gauge_hi] | 180 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_cycle_delta[fw_hi&fw_med] | 20 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_cycle_delta[fw_hi&fw_med] | 30 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_cycle_delta[fw_hi&fw_med] | 50 | 96 | 338 | 327 | 44 | 16 | 27 |
| tail_n_80_20_80_ok[fw_hi] | 1 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_n_80_20_80_ok[fw_hi] | 2 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_n_80_20_80_ok[fw_hi] | 3 | 96 | 338 | 327 | 43 | 20 | 24 |
| tail_n_80_20_80_ok[fw_hi] | 5 | 96 | 338 | 327 | 43 | 20 | 24 |

結論の安定性: candidate判定(p05↔p10)・応答window(24/72/168h)・flat_tail(60/120/180)・tail_cycle(20/30/50)・tail_n_80_20_80_ok(1/2/3/5) を振っても、actionable 群(gauge/fw)の規模感と大小関係は概ね保たれる（上表参照）。

## 9. 既存 soh_update_status との照合

- 既存CSV: {'active': 638, 'stale': 59, 'very_stale': 55}
- 本解析の再現(flat_tail 60/180): {'active': 639, 'stale': 58, 'very_stale': 55}
- merged 752 人, flat_tail 中央絶対差 0.0 日（重複除去・変化検出の差に起因）


既存status × 本ラベル クロス集計:

| soh_update_status | ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE | ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY | NORMAL_OR_RESPONDING | REVIEW_INSUFFICIENT_DATA | WATCH_LOW_UPDATE_RATE_AMBIGUOUS |
| --- | --- | --- | --- | --- | --- |
| active | 0 | 0 | 302 | 320 | 16 |
| stale | 5 | 15 | 25 | 13 | 1 |
| very_stale | 15 | 28 | 0 | 5 | 7 |

## 10. 代表ユーザーの時系列プロット

- `fcc_action/examples_gauge_reset_top20/*.png`: ゲージリセット対象 上位20件
- `fcc_action/examples_fw_check_top20/*.png`: FW確認対象 上位20件
各図は timestamp x軸で RSOC・FCC/SoH・cycleCount・AC/DC・学習機会エピソード・FCC変化点・最後のFCC変化点を表示する。
- 集計図: `fcc_action/funnel_counts.png`, `fcc_action/label_counts.png`, `fcc_action/opportunity_vs_response.png`, `fcc_action/flat_tail_vs_tail_cycles.png`, `fcc_action/hardware_enrichment_fw_check.png`

## 11. ハードウェア偏在（分類には不使用）

> **重要**: device_model / batt_vendor / batt_fru は分類ルールに一切使っていない。以下は分類確定後の集計のみ。母数(n_total)とともに表示する。


**device_model**（n_total>=5, fw_check降順 上位10）:

| value | n_total | n_fw_check | n_gauge_reset | fw_check_rate | gauge_reset_rate |
| --- | --- | --- | --- | --- | --- |
| ThinkPad X1 Carbon Gen 9 | 16 | 4 | 1 | 0.250 | 0.062 |
| ThinkPad X1 Carbon Gen 10 | 31 | 3 | 8 | 0.097 | 0.258 |
| ThinkPad X1 Yoga Gen 6 | 8 | 3 | 0 | 0.375 | 0.000 |
| ThinkPad X1 Carbon Gen 11 | 10 | 2 | 4 | 0.200 | 0.400 |
| ThinkPad T14 Gen 4 | 8 | 2 | 1 | 0.250 | 0.125 |
| ThinkPad X1 Yoga Gen 7 | 15 | 1 | 3 | 0.067 | 0.200 |
| ThinkPad X1 Yoga Gen 8 | 13 | 1 | 2 | 0.077 | 0.154 |
| ThinkPad X1 Carbon Gen 13 | 57 | 0 | 2 | 0.000 | 0.035 |
| ThinkPad T14s Gen 6 | 54 | 0 | 0 | 0.000 | 0.000 |
| ThinkPad X1 Carbon Gen 12 | 43 | 0 | 1 | 0.000 | 0.023 |

**batt_vendor**（n_total>=5, fw_check降順 上位10）:

| value | n_total | n_fw_check | n_gauge_reset | fw_check_rate | gauge_reset_rate |
| --- | --- | --- | --- | --- | --- |
| Sunwoda | 203 | 10 | 6 | 0.049 | 0.030 |
| LG | 18 | 4 | 6 | 0.222 | 0.333 |
| SMP | 226 | 3 | 17 | 0.013 | 0.075 |
| (none) | 22 | 3 | 3 | 0.136 | 0.136 |
| Celxpert | 130 | 0 | 8 | 0.000 | 0.061 |
| BYD | 85 | 0 | 3 | 0.000 | 0.035 |
| COSMX | 40 | 0 | 0 | 0.000 | 0.000 |
| ATL | 28 | 0 | 0 | 0.000 | 0.000 |

**batt_fru**（n_total>=5, fw_check降順 上位10）:

| value | n_total | n_fw_check | n_gauge_reset | fw_check_rate | gauge_reset_rate |
| --- | --- | --- | --- | --- | --- |
| 5B10W13975 | 26 | 10 | 5 | 0.385 | 0.192 |
| 5B10W13973 | 30 | 3 | 7 | 0.100 | 0.233 |
| (none) | 22 | 3 | 3 | 0.136 | 0.136 |
| 5B11M90100 | 25 | 0 | 0 | 0.000 | 0.000 |
| 5B11H56383 | 23 | 0 | 1 | 0.000 | 0.043 |
| 5B11M37553 | 23 | 0 | 0 | 0.000 | 0.000 |
| 5B11M90097 | 23 | 0 | 2 | 0.000 | 0.087 |
| LNV-5B11H56403 | 22 | 0 | 0 | 0.000 | 0.000 |
| 5B11M90162 | 20 | 0 | 0 | 0.000 | 0.000 |
| 5B10W13974 | 19 | 0 | 1 | 0.000 | 0.053 |

## 12. 注意点

- このデータ単体では **FW/BIOS/EC version も update 適用有無も確認できない**。本分類は「FW確認に回すべき対象」を抽出するだけであり、FW不良を断定するものではない。
- `ACTION_GAUGE_RESET` も「ゲージリセットで必ず直る」ことを意味しない。安全な環境での実施と実施後 72h〜7日のFCC更新有無の確認が前提。
- 候補判定では FCC 指標を使う（FCC凍結そのものを探す監査だから）。一方 gauge/fw の分岐は FCC の結果ではなくRSOC・cycle・AC/DC の使用履歴と episode 後の FCC 応答で行う。

## 13. 最終的に確認したい問い への回答

1. **FCC no/low change 候補**: 96 人
2. うち **ACTION_GAUGE_RESET**: 43 人
3. うち **ACTION_FW_CHECK**: 20 人
4. **WATCH_LOW_UPDATE_RATE_AMBIGUOUS**: 24 人
5. FW_CHECK のサブ理由内訳: ZERO_UPDATE_AFTER_OPPORTUNITIES=3, TERMINAL_FREEZE_AFTER_OPPORTUNITIES=5, LOW_UPDATE_RATE_WITH_OPPORTUNITIES=12
6. GAUGE_RESET 主因内訳（重複可）: AC-bound=24, low-cycling=29, shallow-range=10
7. FW_CHECK のハードウェア偏在: 第11節参照（母数併記）。分類には device/vendor/FRU を使っていない。
8. 閾値感度: 第8節の通り、結論（actionable 群の規模と gauge≷fw の関係）は概ね安定。
9. **次に収集すべきデータ**: BIOS/EC/バッテリー関連 FW version、FW update 適用日時、intervention（ゲージリセット/FW更新）実施日時、intervention 後の FCC 更新有無（72h〜7日の追跡テレメトリ）。これらがあれば本監査は「介入→効果」の因果評価に格上げできる。
