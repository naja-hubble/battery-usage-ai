# battery-usage-ai — プロジェクト現状サマリ

最終更新時点の状態をまとめる。S3 から ThinkPad のバッテリーテレメトリを取得し、コホート全体の
使用状況・健全性（SoH）を分析するパイプライン。直近は「**SoH が長期間更新されない（凍結する）
ユーザーの原因分析**」に注力している。

---

## 1. データ取得

- **取得元**: S3 バケット `rprm-alpha-01`、プレフィックス `thinklog/formatted/battery/collection/`
- 配置: `collection/PRD||<DEVICE>_<user>/` 配下に、デバイス/ユーザーごとの 5 アーティファクト
- **走査**: プレフィックス全体を 1 回ページネーション走査（123,188 オブジェクト / 1,808 コレクション）し、
  クライアント側で索引化。時系列は累積（新ファイルが旧ファイルの上位集合）なので各カテゴリの **最新 1 ファイル**のみ取得。
- **取得実績**: 実バッテリー履歴のある **752 ユーザー全件**（`min_battery_bytes ≥ 20000` で空のプリロード/テスト機を除外）。
  ダウンロード 3,718 ファイル、**エラー 0**。731 名が全 5 アーティファクト、21 名が 3 アーティファクト（vendor 等欠落）。
- 保存先（すべて git-ignore）: `data/raw/<safe_id>/`、`data/raw/manifest.json`

---

## 2. データソースと変数の詳細

変数定義は `doc/Power Manager PWM Log file Decoder_20160204.pdf`（Lenovo Power Manager の PWM ログ仕様）に準拠。
このPDFを反映して `battery_usage/schema.py` を訂正済み。

### 2.1 `battery.csv` — メイン時系列（PWM ログ。**累積=各行が時刻順サンプル**）

PDF の 13 フィールド + `timestamp` + `serialNumber`。

| 列 | 単位/型 | 定義（PDF準拠） |
|---|---|---|
| `timestamp` | `MM/DD/YYYY HH:MM:SS` | サンプル時刻。ロガーは概ね **30 分間隔**（中央値30分、全機ほぼ固定） |
| `eventCat` (Event) | 0–5 | **0=Autonomic（30分タイマー or バッテリー挿入）**, 1=Login, 2=Logoff, 3=Suspend, 4=Resume, 5=AC/DC電源切替。分布: 0が72%、5が18% |
| `chargeStatus` | 0–2 | 0=No activity（充放電電流なし）, 1=Charge, 2=Discharge |
| `acdcMode` | 0/1 | **0=DC（バッテリー駆動）, 1=AC（給電）** |
| `remainingCapacityInPercentage` | 0–100 | **= RSOC**（Relative State of Charge = `remainingCapacity/fullChargeCapacity×100`）。実データで一致を確認（corr 0.9999） |
| `remainingCapacity` | **mWh** | 瞬時の残容量（PDF: mWh。従来 mAh と誤記していた） |
| `fullChargeCapacity` | **mWh** | 現在の学習済み満充電容量。**SoH を駆動**。ゲージが充放電サイクルで再学習し、ステップ的に更新される |
| `cycleCount` | 回 | 積算サイクル数（単調増加） |
| `RemainingTime` | 分 | 充電時=満充電までの推定、放電時=空までの推定 |
| `totalChargedCapacity` | Wh | 積算充電スループット |
| `totalBatteryAwakeHrs` | h | 積算のバッテリー稼働時間 |
| `hoursAtFullCharge` | h | 満充電付近の積算滞在時間（ストレス指標） |
| `hoursAtHighTemperature` | h | 高温（>45℃）の積算時間（ストレス指標） |
| `hoursAtFullChargeAndHighTemperature` | h | 満充電かつ高温の積算時間 |
| `serialNumber` | 文字列 | `<n>_<DEVICE>_<user>`。接頭辞 `<n>` がバッテリーパックSN。**全752名で不変（パック交換 0 件）** |

### 2.2 `battery_info.csv`（1 行）
`StartDate`, `Serial Number`, **`DesignCapacity`**（設計容量 mWh）, `product_uuid`

### 2.3 `vendor.csv`（1 行、sleepstudy battery vendor）
`tp-user-battery-sn`, **`Id`=FRU（バッテリーの部品番号/PN）**, **`Manufacturer`=バッテリーセル/パックのベンダー**,
`SerialNumber`(パックSN), `ManufactureDate`, `LongTerm`, `RelativeCapacity`, `DesignCapacity`, `FullChargeCapacity`, `CycleCount`

### 2.4 `drain_rate.csv`（複数行、モダンスタンバイのドレインイベント）
`serialNumber`, `Start Time`, `Duration`, `State`, `% CAPACITY REMAINING AT START`

### 2.5 `product.json`（WMI Win32_ComputerSystemProduct）
`Version`=**device_model**（例 "ThinkPad T14s Gen 6"）, `Name`=**MTM/型番**（例 21N2ZC5RUS）,
`IdentifyingNumber`=**筐体シリアル**（例 PW0C7G1S）, `UUID`=デバイスUUID, `Vendor`=LENOVO

### 2.6 データソース採用方針（重複フィールドの権威）
- **`cycleCount` / `FullChargeCapacity`** → **battery.csv を採用**（live・最新。vendor.csv は約1サイクル遅れるスナップショット）
- **`DesignCapacity`** → battery_info.csv 優先 → vendor.csv フォールバック（battery.csv に無い）
- **`batt_vendor` 正規化**（`vendor_normalize.py`）: 制御文字（`\x08`）除去 + 年号サフィックス統合（SMP2023→SMP 等）
  + ブランド別名統合（**LGC+LGES→LG**、**SWD→Sunwoda**）→ **13 → 7 ベンダー**
  - SMP 226 / Sunwoda 203 / Celxpert 130 / BYD 85 / COSMX 40 / ATL 28 / **LG 18** / （None 22）

---

## 3. 集約データフレーム（`data/processed/`）

| ファイル | 形状 | 内容 |
|---|---|---|
| `battery_timeseries_all.parquet` | **3,130,394 行 × 22 列** | 全ユーザーの時系列を縦結合（ロング）。Parquet（CSV 543MB → 40MB、dtype保持）。行ごとに固有ID・device_model・batt_vendor・batt_fru・`soh_design_pct` を付与 |
| `user_master.csv` | 752 × 26 | 1ユーザー=1行の静的サマリ（識別子・パック情報・観測サマリ）。`user_id` で時系列に結合 |
| `soh_reason_features.csv` | **752 × 61** | 原因分析用の統合テーブル（`extract_features` 39 + FCC更新ダイナミクス + RSOC特徴量） |
| `soh_reason_labeled.csv` | 752 × 62 | 上記 + 原因クラス `soh_reason_class` |
| `soh_update_status.csv` | 752 | 凍結ステータス（flat-tail ベース） |
| `feature_audit.csv` | — | 全特徴量の凍結相関監査 + 学習適格フラグ |
| `device_models.csv` | 103 | 全機種一覧 + 凍結統計 |
| `very_stale_{tree,xgb}_importances.csv` | — | 教師あり重要度 |

`battery_timeseries_all.parquet` の列:
`user_id, device_model, batt_vendor, batt_fru, timestamp, eventCat, chargeStatus, acdcMode,
remainingCapacityInPercentage(=RSOC), cycleCount, serialNumber, remainingCapacity, fullChargeCapacity,
RemainingTime, totalChargedCapacity, totalBatteryAwakeHrs, hoursAtFullCharge, hoursAtHighTemperature,
hoursAtFullChargeAndHighTemperature, acdc_label, charge_label, soh_design_pct`

---

## 4. 派生特徴量（`soh_reason_features.csv` の主な61列）

- **健全性**: `soh_design_pct`（=FCC×100/DesignCapacity）, `soh_peak_pct`, `capacity_fade_pct`, `fade_pct_per_year/100_cycles`
- **FCC更新ダイナミクス（凍結の指標）**: `fcc_distinct`（FCC の異なり値数）, `fcc_changes`（ステップ回数）,
  **`fcc_change_rate_per_100d`**（観測100日あたりFCC更新回数＝span頑健な更新率）, **`soh_flat_tail_days`**（末尾でFCCが最後に
  変化してからの日数）, `flat_pct_of_span`, `stale_days`（今日 − 最終サンプル）
- **RSOC / 充電レンジ**（`build_rsoc_features.py`）: `min_rsoc`, `rsoc_p05/p95`, `rsoc_swing`, `frac_below_10/5`,
  `n_deep_dis10`（深放電イベント数）, `reaches_full`, `frac_at_full`, **`n_full_range_dis`**（90%→10% の適格放電回数）
- **使用パターン**: `cycles_per_year/month`, `ac_time_ratio`/`ac_event_ratio`（給電比率）, `mean_dod_pct`（放電深度）,
  `time_ratio_below_20pct`, `time_ratio_full_on_ac`, `n_discharge_sessions`, `median_drain_pct_per_hr`, `mean_pct_remaining`
- **ストレス/睡眠**: `hours_high_temp_last`, `frac_awake_high_temp`, `hours_at_full_charge_last`, `sleep_events`, `sleep_total_hours`

---

## 5. SoH 凍結の定義と分類

### 5.1 定義
- **SoH は整数 `fullChargeCapacity` がステップしたときのみ更新される**（DesignCapacity は一定なので）。
- 「凍結」= FCC が一定値に張り付く。`soh_flat_tail_days` = 末尾の平坦継続日数。

### 5.2 ステータス分類（しきい値ベース、`soh_update_status.py`）
| 区分 | 定義（flat-tail） | 人数 |
|---|---|---:|
| active | < 60 日 | 638 |
| stale | 60–180 日 | 59 |
| **very_stale** | ≥ 180 日 | **55** |

### 5.3 原因サブ分類（使用挙動ベース、**機種非依存**、`classify_reason.py`）
凍結（stale/very_stale = 114名）に対して、**汎用的な使用挙動特徴のみ**で原因を割り当てる。
`device_model`・世代・ベンダー名は分類ルールに**一切使わない**（過去にハードコードした X1 世代ルールはユーザー指摘で撤去）。

使用特徴量は 4 つ: `ac_time_ratio`, `cycles_per_year`, `min_rsoc`, `n_full_range_dis`

| クラス | 定義 | very_stale | stale | 計 |
|---|---|---:|---:|---:|
| USE_ac_bound_no_cycling | 常時AC(≥0.80) かつ 低サイクル(<p25=30.27) | 7 | 15 | 22 |
| USE_low_cycling | 低サイクル(<p25) | 10 | 6 | 16 |
| USE_shallow_discharge | 真に浅い（min_rsoc>10 かつ 適格放電0回） | 3 | 3 | 6 |
| **HW_firmware_suspected** | 深く/フルレンジで放電するのに凍結（除外定義） | 35 | 35 | **70** |

→ **使用で説明可 44 / ハードウェア・ファームウェア疑い 70**

> 注: 旧 `USE_shallow_discharge` は `mean_dod_pct`（平均放電深度）基準だったが、RSOC 解析で「頻繁な継ぎ足し＋
> 時折の深放電」を平均が薄める交絡と判明し、`min_rsoc`（実到達深度）基準に是正。誤分類されていた深放電ユーザーは HW へ移った。

### 5.4 学習特徴量の除外ポリシー（`classify_reason.EXCLUDED_FROM_LEARNING`）
- **ハードウェア識別子（記述専用、学習に使わない）**: `device_model`, `batt_vendor`, `manufacturer`, `design_capacity`
- その他除外: リーク系（fcc_*, soh_flat_tail_days, flat_pct_of_span, stale_days …）、結果系（soh_design_pct, capacity_fade …）、
  サンプリング統制（n_samples, observation_days …）、ID/時刻
- **学習適格 = 33 特徴量**（`learning_features(df)` が返す）

---

## 6. 主要な発見（検証済み）

複数の敵対的マルチエージェント解析 + 教師あり学習で確認。詳細は `data/processed/_soh_reason_report.md` /
`_soh_rsoc_report.md`。

1. **凍結の最強予測子は「充放電サイクル量」** — `cycles_per_year` の更新率への Spearman +0.60（観測長を統制しても不変）。
   他の全特徴量は cycling を偏相関で抜くと |rho|≤0.12 に崩壊。
2. **RSOC 深度・適格放電は独立した駆動因子ではない** — cycling の代理。深放電の最上位帯でも凍結が残存し
   （n_full_range_dis≥10 で 18%）、その群内では frozen と active が全 RSOC 特徴で区別不能。
3. **パック交換は 0/752** — FCC 変化は真のゲージ再学習であり、交換由来ではない。
4. **HW_firmware_suspected 残差（70名）は真にハードウェア/ファームウェア**（敵対的検証 2 件とも `residual_is_hardware`）—
   active より多くサイクル（96.9 vs 65.7 cyc/yr）し、深く（min_rsoc=1）・フルレンジで放電するのに FCC が凍結。
   温度 null・サンプリング同等・観測打ち切りなしで、行動・熱・ロギングのいずれでも説明不能。
5. **記述的なハードウェア偏在（分類には不使用）**: LG セル（18名中 55.6% が very_stale）、旧世代 X1 Carbon/Yoga が高率。
   ただし HW 疑い群は X1 以外にも **T14 Gen3/4・X13 Gen4・X9-15 Gen1・T14s 等、15 機種以上に分散**（X1 専用ではない）。
   全 103 機種。

---

## 7. 教師あり検証（very_stale を 33 特徴量で予測）

機種/ベンダー/容量を除外し、`very_stale` を予測。**span 交絡対策**として、累積カウンタ（観測期間に比例＝span代理）を除いた
**強度特徴量（rate/ratio/level）22 個**で「正直な」モデルを評価。

| 特徴量セット | 決定木 AUC | XGBoost AUC |
|---|---:|---:|
| 全33 | 0.737 | 0.806 | ← span交絡で水増し |
| 強度22（span頑健） | 0.585 | 0.635 |
| 強度22・公平領域(obs≥180d) | **0.535** | **0.540** | ← **ほぼランダム(0.5)** |

- 素朴なモデルは `total_awake_hrs_last`（重要度最大）等の累積カウンタ＝span代理に支配される（罠）。
- **両モデルとも公平比較で AUC ≈ 0.54** → very_stale は使用挙動から学習不能。最重要 `min_rsoc` は「深放電ほど凍結」という
  **反usage方向**（SHAP で確認）。
- 結論: **凍結は使用挙動では予測/説明できない＝ハードウェア/ファームウェア起因**という結論を、最強の教師あり手法でも追認。

---

## 8. 成果物一覧

### データ（`data/processed/`）
`battery_timeseries_all.parquet`, `user_master.csv`, `soh_reason_features.csv`, `soh_reason_labeled.csv`,
`soh_update_status.csv`, `feature_audit.csv`, `device_models.csv`, `very_stale_{tree,xgb}_importances.csv`,
`very_stale_tree_rules.txt`, `_soh_reason_report.md`, `_soh_rsoc_report.md`

### 図（`data/reports/figures/`）
- `soh_by_user_100.png` / `soh_by_user_all.png` — date vs SoH 個別パネル（100名 / 全752名、原因色分け）
- `soh_overlay_by_class.png` — 原因クラス別 SoH 軌跡オーバーレイ
- `soh_reason_trends.png` — 凍結トレンド要約（ベンダー別・HW疑い群機種構成・サイクル散布・クラス内訳）
- `very_stale_tree.png` — 解釈可能な決定木
- `very_stale_xgb_shap.png` — XGBoost SHAP

### コード
- パッケージ `battery_usage/`（config, **schema[PDF反映]**, parse, features, aggregate, s3_download, anon, visualize, report）
- 集約: `build_user_master.py`, `build_timeseries.py`, `build_reason_table.py`, `build_rsoc_features.py`
- 加工/分類: `vendor_normalize.py`, `soh_update_status.py`, `classify_reason.py`, `apply_relabel.py`
- 可視化: `plot_soh_by_user.py`, `plot_soh_all.py`, `plot_reason_trends.py`
- 学習: `supervised_tree.py`, `supervised_xgb.py`

---

## 9. 既知の課題・次のステップ候補

- `batt_mfg_date` はソース不正（`-4-20` 等）で製造日基準分析には使えない。時間軸は `first_ts/last_ts` を使用。
- まだ特徴量化していない生変数: `eventCat` 由来の活動頻度、`RemainingTime`、`hoursAtFullChargeAndHighTemperature`
  （構成要素の高温は検証済みで null）。
- 候補: ① HW疑い70名の内部構造（完全凍結 rate=0 vs 部分更新）の教師なしクラスタリング、
  ② 目的変数を stale-or-worse(114) や連続量に変えた感度分析、③ 本ドキュメント/知見の `report.md` への統合、
  ④ FCC 再学習トリガ条件（温度・充電上限設定等）のさらなる特定。
