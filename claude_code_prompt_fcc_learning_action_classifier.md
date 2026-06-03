# Claude Code 用プロンプト: FCC学習機会ベースの介入対象分類器を実装する

あなたは `battery-usage-ai` リポジトリで作業するシニアデータサイエンティスト兼Pythonエンジニアです。目的は、ThinkPadバッテリーテレメトリから、`fullChargeCapacity`（FCC）/SoH が変化しない、またはほとんど変化していないユーザーを抽出し、次の2種類の介入対象に分類することです。

1. **学習機会なし**: 使用パターン上、ゲージがFCCを再学習する機会が不足している。推奨アクションは、ユーザーに安全な範囲でゲージリセット/キャリブレーションを促すこと。
2. **学習機会あり**: 深い放電・再充電・十分なサイクルなど、FCCが更新されてもよい機会があるにもかかわらずFCCが変化しない。推奨アクションは、FW/BIOS/EC/バッテリー関連FWのVersion確認とアップデート有無確認を促すこと。

この分類器は「予測モデル」ではなく、「介入アクションに直結する監査ロジック」です。解釈可能性と誤判定抑制を最優先してください。

---

## 0. 必ず最初に読むもの

リポジトリ内の `PROJECT_STATUS.md` を最初に読んでください。既存のデータ定義・既存解析・注意点を把握した上で実装してください。

重要な前提:

- `battery_timeseries_all.parquet` は全ユーザーのロング時系列。主な列は `user_id`, `device_model`, `batt_vendor`, `batt_fru`, `timestamp`, `chargeStatus`, `acdcMode`, `remainingCapacityInPercentage`（RSOC）, `cycleCount`, `fullChargeCapacity`, `soh_design_pct` など。
- SoH は `fullChargeCapacity / DesignCapacity` によって決まり、`fullChargeCapacity` がステップしたときのみSoHが更新される。
- 既存の flat-tail 分類では active/stale/very_stale が定義済み。
- 既存解析では、使用挙動だけで very_stale を予測するモデルは公平領域でほぼランダムに近い。したがって今回はMLで予測するのではなく、「学習機会に対してFCCが応答したか」を監査する。
- `device_model`, `batt_vendor`, `batt_fru` は分類ルールには使わない。分類後の偏在確認・FW調査優先順位付けにのみ使う。

---

## 1. 入力データ

基本入力:

- `data/processed/battery_timeseries_all.parquet`
- `data/processed/user_master.csv` が存在すれば結合に使う
- `data/processed/soh_update_status.csv` が存在すれば既存の active/stale/very_stale と照合に使う
- `data/processed/soh_reason_features.csv` が存在すれば既存特徴量との整合確認に使う

ただし、分類に必要な主要特徴量は、必ず `battery_timeseries_all.parquet` から再計算してください。既存CSVは照合・比較用としてください。

---

## 2. 出力成果物

以下を作成してください。

### 2.1 CSV

1. `data/processed/fcc_learning_episodes.csv`
   - 1行 = 1つの high→low→high 学習機会エピソード
   - `user_id`
   - `threshold_name`: `strict_90_10_90`, `primary_80_20_80`, `secondary_85_15_85`
   - `start_ts`, `low_ts`, `end_ts`
   - `start_idx`, `low_idx`, `end_idx` 相当
   - `start_rsoc`, `low_rsoc`, `end_rsoc`
   - `cycle_delta_episode`
   - `fcc_start`, `fcc_end`, `fcc_changed_during_episode`
   - `fcc_changed_24h`, `fcc_changed_72h`, `fcc_changed_168h`
   - `response_window_end_ts_24h`, `response_window_end_ts_72h`, `response_window_end_ts_168h`
   - `max_gap_h_in_episode`
   - `episode_quality`: `ok`, `large_gap`, `missing_fcc`, `invalid_order` など

2. `data/processed/fcc_learning_user_features.csv`
   - 1行 = 1ユーザー
   - データ品質、FCC更新、tail、学習機会、応答率、使用パターンをまとめる

3. `data/processed/fcc_learning_action_labels.csv`
   - 1行 = 1ユーザー
   - 最終ラベル、推奨アクション、根拠、信頼度、主要特徴量を含める

4. `data/processed/fcc_intervention_targets_gauge_reset.csv`
   - `recommended_action == ACTION_GAUGE_RESET`
   - ユーザー連絡/運用対象として使える列だけに整理

5. `data/processed/fcc_intervention_targets_fw_check.csv`
   - `recommended_action == ACTION_FW_CHECK`
   - FW/BIOS/EC確認依頼対象として使える列だけに整理

6. `data/processed/fcc_action_sensitivity.csv`
   - 閾値を変えたときの分類件数比較

7. `data/processed/fcc_action_enrichment_by_hardware.csv`
   - 最終ラベル別の `device_model`, `batt_vendor`, `batt_fru` 分布
   - 分類には使わず、分類後に集計する

### 2.2 レポート

`data/reports/fcc_learning_action_report.md` を作成してください。以下を含めてください。

- 目的と前提
- データ品質確認
- FCC no/low change 候補の定義
- 学習機会 episode の定義
- 最終ラベル定義
- ラベル別人数
- 推奨アクション別人数
- 閾値感度分析
- 代表ユーザーの時系列プロット一覧
- `device_model` / `batt_vendor` / `batt_fru` の偏在。ただし分類には使っていないことを明記
- 注意点: このデータ単体ではFW versionやupdate有無は確認できない。FW確認対象を抽出するだけであること

### 2.3 図

`data/reports/figures/fcc_action/` に保存してください。

- `funnel_counts.png`: 全ユーザー → no/low FCC candidates → no opportunity / has opportunity → action labels
- `label_counts.png`: 最終ラベル別件数
- `opportunity_vs_response.png`: 学習機会数とFCC応答率
- `flat_tail_vs_tail_cycles.png`: `flat_tail_days` vs `tail_cycle_delta`、最終ラベルで色分け
- `hardware_enrichment_fw_check.png`: FW確認対象のmodel/vendor/FRU偏在。母数も表示
- 代表ユーザーの個別時系列プロット:
  - `examples_gauge_reset_top20/*.png`
  - `examples_fw_check_top20/*.png`
  - 各図は timestamp x軸で、RSOC、FCC/SoH、cycleCount、AC/DC、学習機会エピソード、FCC変化点、最後のFCC変化点を見えるようにする

---

## 3. 実装ファイル案

既存構成を壊さず、以下を追加してください。

- `battery_usage/fcc_learning.py`
  - episode抽出、FCC応答判定、ユーザー特徴量集計
- `battery_usage/fcc_action_classifier.py`
  - 最終ラベル付け、スコアリング、推奨アクション生成
- `analyze_fcc_learning_actions.py`
  - メインスクリプト。全CSV・レポート・図を作成
- `plot_fcc_learning_actions.py`
  - 可視化専用でもよい
- `tests/test_fcc_learning.py`
  - episode抽出と応答判定の単体テスト

既存の `battery_usage/` パッケージのスタイルに合わせてください。CLI引数は最低限以下を持たせてください。

```bash
python analyze_fcc_learning_actions.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --out-dir data/processed \
  --fig-dir data/reports/figures/fcc_action \
  --report data/reports/fcc_learning_action_report.md
```

---

## 4. データ品質ゲート

ユーザー単位で以下を計算してください。

- `n_samples`
- `first_ts`, `last_ts`, `obs_days`
- `median_interval_h`, `p95_interval_h`
- `gaps_gt6h`, `gaps_gt24h`
- `duplicate_timestamp_count`
- `cycle_decrease_count`
- `fcc_missing_count`
- `rsoc_missing_count`
- `serial_number_distinct`
- `data_quality_label`

推奨ラベル:

- `QUALITY_OK`
- `QUALITY_SHORT_OBS`: `obs_days < 120`
- `QUALITY_SPARSE`: `p95_interval_h > 24` またはサンプルが極端に少ない
- `QUALITY_COUNTER_RESET`: `cycle_decrease_count > 0` または累積カウンタが大きく減少
- `QUALITY_PACK_CHANGE_OR_ID_CHANGE`: `serial_number_distinct > 1`

`QUALITY_OK` 以外でも特徴量は計算するが、最終介入ラベルでは信頼度を下げるか `REVIEW_INSUFFICIENT_DATA` に回してください。

---

## 5. FCC no/low change 候補の定義

まず全ユーザーに対して以下を計算してください。

- `fcc_start`, `fcc_end`, `fcc_min`, `fcc_max`
- `fcc_distinct`
- `fcc_changes`: `fullChargeCapacity` の値が変わった回数。原則 `delta != 0`。必要なら `abs(delta) >= 1 mWh`。
- `fcc_pos_changes`, `fcc_neg_changes`
- `last_fcc_change_ts`
- `flat_tail_days = last_ts - last_fcc_change_ts`
- `fcc_change_rate_per_100d = fcc_changes / obs_days * 100`
- `cycle_start`, `cycle_end`, `cycle_delta`
- `cycles_per_year`
- `fcc_changes_per_100_cycles = fcc_changes / max(cycle_delta, epsilon) * 100`
- `soh_span_pct = max(soh_design_pct) - min(soh_design_pct)` if available
- `near_design_plateau`: `abs(soh_end - 100) <= 2 and fcc_changes == 0`
- `near_101_plateau`: `100.8 <= soh_end <= 101.2 and fcc_changes == 0`

Active reference cohort:

- `obs_days >= 180`
- `cycle_delta >= 20`
- `flat_tail_days < 60`
- `data_quality_label == QUALITY_OK`

このactive referenceから、以下の分位点を算出してください。

- `p05_fcc_changes_per_100_cycles_active`
- `p10_fcc_changes_per_100_cycles_active`
- `p05_fcc_change_rate_per_100d_active`
- `p10_fcc_change_rate_per_100d_active`

候補フラグ:

```text
no_fcc_update = fcc_changes == 0 and obs_days >= 120
long_terminal_flat = flat_tail_days >= 180
low_update_per_cycle = cycle_delta >= 50 and fcc_changes_per_100_cycles <= p05_fcc_changes_per_100_cycles_active
low_update_per_time = obs_days >= 180 and fcc_change_rate_per_100d <= p05_fcc_change_rate_per_100d_active
fcc_no_or_low_change_candidate = no_fcc_update or long_terminal_flat or low_update_per_cycle or low_update_per_time
```

注意:

- `device_model`, `batt_vendor`, `batt_fru` を候補判定に使わない。
- 候補判定ではFCC関連指標を使ってよい。これは予測モデルではなく、FCC凍結そのものを見つける監査だから。
- ただし「学習機会あり/なし」の分岐には、FCCの結果そのものを過剰に使わず、RSOC・cycle・AC/DCなどの使用履歴と、episode後のFCC応答を使う。

---

## 6. 学習機会 episode の定義

`remainingCapacityInPercentage` を RSOC として使います。ユーザーごとに timestamp でsortし、重複timestampは原則最後の行を採用してください。

3種類の high→low→high episode を抽出してください。

1. `strict_90_10_90`: `RSOC >= 90` → `RSOC <= 10` → `RSOC >= 90`
2. `primary_80_20_80`: `RSOC >= 80` → `RSOC <= 20` → `RSOC >= 80`
3. `secondary_85_15_85`: `RSOC >= 85` → `RSOC <= 15` → `RSOC >= 85`

実装は状態機械で行ってください。

疑似コード:

```python
def extract_high_low_high_episodes(g, high, low):
    state = "WAIT_HIGH"
    start_idx = None
    low_idx = None
    episodes = []

    for idx, row in g.iterrows():
        rsoc = row["remainingCapacityInPercentage"]
        if pd.isna(rsoc):
            continue

        if state == "WAIT_HIGH":
            if rsoc >= high:
                start_idx = idx
                state = "WAIT_LOW"

        elif state == "WAIT_LOW":
            if rsoc <= low:
                low_idx = idx
                state = "WAIT_HIGH_AGAIN"

        elif state == "WAIT_HIGH_AGAIN":
            if rsoc >= high:
                episodes.append((start_idx, low_idx, idx))
                # 次のepisodeの開始点としてこのhighを再利用してよい
                start_idx = idx
                low_idx = None
                state = "WAIT_LOW"

    return episodes
```

各episodeについて、FCC応答を判定してください。

```text
fcc_changed_during_episode = fullChargeCapacityがepisode start〜episode endの間に変化したか
fcc_changed_24h = episode start〜episode end+24hの間に変化したか
fcc_changed_72h = episode start〜episode end+72hの間に変化したか
fcc_changed_168h = episode start〜episode end+168hの間に変化したか
```

`episode_quality`:

- `ok`: episode内の最大サンプル間隔が12h以下、FCC/RSOCに欠損なし
- `large_gap`: episode内の最大サンプル間隔が12h超
- `missing_fcc`: episode/window内でFCC欠損あり
- `invalid_order`: start < low < end が崩れている

大きな欠測があるepisodeは件数には残すが、主判定では `ok` のみを優先してください。感度分析では `large_gap` を含めた場合も集計してください。

---

## 7. tail特徴量: 最後のFCC更新後を見る

ユーザーごとに `last_fcc_change_ts` を求め、その時刻以降を tail として以下を計算してください。

- `tail_days`
- `tail_cycle_delta`
- `tail_cycles_per_year`
- `tail_min_rsoc`, `tail_max_rsoc`, `tail_rsoc_swing`
- `tail_ac_time_ratio`
- `tail_full_time_ratio`
- `tail_below20_time_ratio`
- `tail_n_90_10_90_ok`
- `tail_n_80_20_80_ok`
- `tail_n_85_15_85_ok`
- `tail_n_90_10_90_any_quality`
- `tail_n_80_20_80_any_quality`
- `tail_n_85_15_85_any_quality`
- `tail_response_rate_80_20_80_72h`
- `tail_response_rate_90_10_90_72h`

`fcc_changes == 0` の場合、`last_fcc_change_ts = first_ts` として tail を全観測期間にしてください。

---

## 8. 最終ラベル定義

最終ラベルは相互排他的にしてください。分類の優先順位は下記順です。

### 8.1 `REVIEW_INSUFFICIENT_DATA`

条件例:

```text
obs_days < 120
or n_samples < 200
or data_quality_label in {QUALITY_COUNTER_RESET, QUALITY_PACK_CHANGE_OR_ID_CHANGE}
```

推奨アクション:

```text
ACTION_COLLECT_MORE_DATA_OR_MANUAL_REVIEW
```

### 8.2 `NORMAL_OR_RESPONDING`

条件:

```text
not fcc_no_or_low_change_candidate
```

推奨アクション:

```text
ACTION_NONE
```

### 8.3 `ACTIONABLE_GAUGE_RESET_NO_OPPORTUNITY`

意味:

FCCが変化しない/少ないが、ゲージが再学習するための利用機会が不足している。これはFW不良とは限らない。まず安全なゲージリセット/キャリブレーションを促す。

High confidence条件:

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 120
and tail_n_80_20_80_ok == 0
and tail_n_90_10_90_ok == 0
and (
    tail_cycle_delta < 20
    or tail_min_rsoc > 20
    or tail_rsoc_swing < 60
    or tail_ac_time_ratio >= 0.80
)
and data_quality_label == QUALITY_OK
```

Medium confidence条件:

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 60
and tail_n_80_20_80_ok <= 1
and (
    tail_cycle_delta < 30
    or tail_min_rsoc > 25
    or tail_rsoc_swing < 50
    or tail_ac_time_ratio >= 0.75
)
```

サブ理由を付けてください。

- `NO_OPPORTUNITY_AC_BOUND`: `tail_ac_time_ratio >= 0.80`
- `NO_OPPORTUNITY_LOW_CYCLING`: `tail_cycle_delta < 20`
- `NO_OPPORTUNITY_SHALLOW_RANGE`: `tail_min_rsoc > 20` or `tail_rsoc_swing < 60`
- 複数該当なら `;` で連結

推奨アクション:

```text
ACTION_GAUGE_RESET
```

運用メッセージ案もCSVに含めてください:

```text
FCC/SoHが長期間更新されていませんが、ログ上は深い放電→再充電の学習機会が不足しています。安全な環境でOEM推奨のバッテリーゲージリセット/キャリブレーションを実施し、その後72h〜7日間のテレメトリでFCC更新有無を確認してください。
```

### 8.4 `ACTIONABLE_FW_CHECK_OPPORTUNITY_NO_RESPONSE`

意味:

FCCが変化しない/少ないだけでなく、学習機会が複数ある。それでもFCCが応答していないため、FW/BIOS/EC/バッテリー関連FW確認を優先する。

High confidence条件:

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 180
and tail_cycle_delta >= 30
and (
    tail_n_80_20_80_ok >= 3
    or tail_n_90_10_90_ok >= 1
)
and (
    tail_response_rate_80_20_80_72h == 0
    or tail_response_rate_90_10_90_72h == 0
)
and data_quality_label == QUALITY_OK
```

さらに強い条件:

```text
fcc_changes == 0
and total_n_80_20_80_ok >= 5
and total_response_rate_80_20_80_72h == 0
```

Medium confidence条件:

```text
fcc_no_or_low_change_candidate
and flat_tail_days >= 120
and tail_cycle_delta >= 20
and (
    tail_n_80_20_80_ok >= 2
    or tail_min_rsoc <= 10 and tail_max_rsoc >= 90
)
and relevant_response_rate_72h <= 0.10
```

サブ理由:

- `ZERO_UPDATE_AFTER_OPPORTUNITIES`: `fcc_changes == 0 and total_n_80_20_80_ok >= 5 and response_rate == 0`
- `TERMINAL_FREEZE_AFTER_OPPORTUNITIES`: `fcc_changes > 0 and flat_tail_days >= 180 and tail_n_80_20_80_ok >= 3 and tail_response_rate == 0`
- `LOW_UPDATE_RATE_WITH_OPPORTUNITIES`: low rateだが完全ゼロではない

推奨アクション:

```text
ACTION_FW_CHECK
```

運用メッセージ案:

```text
FCC/SoHが長期間更新されておらず、ログ上は深い放電→再充電の学習機会が複数回確認されています。通常のキャリブレーション機会があったにもかかわらずFCC応答がないため、BIOS/EC/バッテリー関連FWのVersion確認とアップデート有無確認を優先してください。アップデート後、次回の学習機会後72h〜7日間でFCC更新有無を確認してください。
```

### 8.5 `WATCH_LOW_UPDATE_RATE_AMBIGUOUS`

条件:

```text
fcc_no_or_low_change_candidate
but not classified above
```

推奨アクション:

```text
ACTION_MONITOR_OR_MANUAL_REVIEW
```

理由:

- 学習機会が1〜2回しかなく、FW確認に回すには弱い
- データ品質がやや悪い
- cycleはあるがRSOCレンジが微妙
- FCC更新率は低いが完全凍結ではない

---

## 9. スコアリング

各ユーザーに以下を付与してください。

- `gauge_reset_score_0_100`
- `fw_check_score_0_100`
- `confidence`: `high`, `medium`, `low`, `review`
- `primary_evidence`: 根拠を短く説明する文字列

スコア例:

```text
gauge_reset_score =
  30 * long_flat_component
+ 25 * no_opportunity_component
+ 20 * shallow_or_ac_component
+ 15 * low_cycle_component
+ 10 * data_quality_component

fw_check_score =
  30 * long_flat_component
+ 30 * opportunity_count_component
+ 20 * zero_response_component
+ 10 * tail_cycle_component
+ 10 * data_quality_component
```

各componentは0〜1に正規化してください。スコアは運用優先順位付け用であり、最終ラベルはルールで決めてください。

---

## 10. 検証と感度分析

必ず以下を実施してください。

1. 既存の `soh_update_status.csv` があれば、active/stale/very_stale件数を再現または差異を説明する。
2. `threshold_name` ごとに episode数、応答率、ラベル件数を出す。
3. response windowを `24h`, `72h`, `168h` で比較する。
4. `flat_tail_days` 閾値を `60`, `120`, `180` で比較する。
5. `tail_cycle_delta` 閾値を `20`, `30`, `50` で比較する。
6. `tail_n_80_20_80_ok` 閾値を `1`, `2`, `3`, `5` で比較する。
7. `device_model`, `batt_vendor`, `batt_fru` を分類に使っていないことをレポートに明記し、分類後の偏在のみ表示する。
8. `ACTION_GAUGE_RESET` と `ACTION_FW_CHECK` の上位20件を個別時系列プロットで目視確認できるようにする。

---

## 11. 実装上の注意

- pandasで実装してよいが、ユーザーごとのgroupby処理は3.1M行程度を想定し、過度に遅くならないようにする。
- timestampは `pd.to_datetime` で処理し、ユーザー内でsortする。
- `remainingCapacityInPercentage` は0〜100にclipせず、異常値は品質指標として数える。episode抽出では0〜100外を欠損扱いにしてよい。
- FCCが欠損しているwindowでは応答判定を `NaN` または `unknown` にし、0応答と誤認しない。
- `cycleCount` が減るユーザーはカウンタリセットやデータ異常としてreviewに回す。
- `serialNumber` が変わる場合はパック交換疑いとしてreviewに回す。既存解析では交換0件だが再確認する。
- 閾値はコード上部の定数またはdataclassにまとめる。magic numberを散らさない。
- 既存コードを壊さない。新規成果物として追加する。
- すべての出力CSVに `created_at` または `analysis_timestamp` を含める。

---

## 12. 単体テスト

`tests/test_fcc_learning.py` を作成し、最低限以下をテストしてください。

1. `100, 90, 50, 20, 10, 30, 80, 100` から `80_20_80` が1件抽出される。
2. `100, 70, 30, 100` では `80_20_80` は抽出されないが、設定次第で `70_30_70` を使う場合は抽出できるよう設計が汎用である。
3. episode内でFCCが変わった場合 `fcc_changed_during_episode=True`。
4. episode終了後72h以内にFCCが変わった場合 `fcc_changed_72h=True`。
5. 72h超過後にFCCが変わった場合 `fcc_changed_72h=False`, `fcc_changed_168h=True` になり得る。
6. FCC欠損がある場合にゼロ応答と誤判定しない。
7. timestamp順序が乱れていてもsort後に正しく抽出される。

---

## 13. 最終的に確認したい問い

レポートの最後に、以下の問いに答えてください。

1. FCC no/low change 候補は何人か。
2. そのうち `ACTION_GAUGE_RESET` は何人か。
3. そのうち `ACTION_FW_CHECK` は何人か。
4. `WATCH_LOW_UPDATE_RATE_AMBIGUOUS` は何人か。
5. `ACTION_FW_CHECK` の中で `ZERO_UPDATE_AFTER_OPPORTUNITIES` と `TERMINAL_FREEZE_AFTER_OPPORTUNITIES` は何人か。
6. `ACTION_GAUGE_RESET` の主因内訳は AC-bound / low-cycling / shallow-range でどう分かれるか。
7. `ACTION_FW_CHECK` は特定の `device_model`, `batt_vendor`, `batt_fru` に偏在するか。ただし分類にはそれらを使っていないこと。
8. 閾値を少し変えても結論は安定か。
9. 次に収集すべき追加データは何か。特に BIOS/EC/FW version, update適用日時, intervention実施日時, intervention後のFCC更新有無を挙げる。

---

## 14. 完了条件

- `python analyze_fcc_learning_actions.py ...` がエラーなく完走する。
- 752ユーザーすべてに最終ラベルが付く。
- 最終ラベルは相互排他的で合計が752になる。
- `device_model`, `batt_vendor`, `batt_fru` を分類ルールに使っていない。
- `fcc_learning_action_report.md` に分類件数、根拠、感度分析、代表図、注意点が含まれる。
- `ACTION_GAUGE_RESET` と `ACTION_FW_CHECK` の対象CSVが運用に使える形式で出力される。
