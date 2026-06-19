# FCC学習応答技術 特許性強化エビデンス v3 — 成果物バンドル

**作成日**: 2026-06-19 ／ **対象**: `battery-usage-ai` の全期間版 + rolling30-v2.0 FCC学習応答検出技術
**位置付け**: `claude_code_prompt_fcc_patent_evidence_v3.md` に従って生成した技術的特許エビデンス一式。

> ⚠️ **technical evidence for patent review であり、法的結論ではありません。** 先行技術の特許番号はAIサーベイ由来で**未検証**。出願前に登録弁理士（弁理士）のレビュー必須。PIIは外部向け図・レポートに含めていません（PIIスキャンtest済）。

---

## 中身と読む順序

| # | フォルダ／ファイル | 内容 |
|---|---|---|
| 1 | `01_report/fcc_patent_evidence_v3_report.md` | **本体報告**（ベースラインゲート/可用性/Top3技術効果/Analysis A・C・H/弱点/family別evidence strength/PENDING） |
| 1 | `01_report/fcc_invention_disclosure_v3.md` | 発明届ドラフト（12節：技術分野→失敗アプローチ→4発明→限界→placeholder） |
| 2 | `02_matrices/fcc_claim_support_matrix_v3.csv` | **クレームサポート行列**（family/claim要素/code-module/入力変数/出力/図/技術効果/代替実施/evidence strength/欠落） |
| 2 | `02_matrices/fcc_prior_art_feature_matrix_v3.csv` | 先行技術-特徴対照（各特徴が**先行技術で開示されない点**。番号はUNVERIFIED） |
| 2 | `02_matrices/fcc_patent_figure_captions_v3.csv` | 図キャプション（invention_family/claim_elements/technical_problem/technical_effect） |
| 3 | `03_evidence_data/` | 解析の生CSV/JSON（manifest, baseline_gate, availability_probe, ablation, dual_track, technical_effects, storage） |
| 4 | `04_figures/` | **dpi=300・匿名**の図3枚（ablation / dual_track / technical_effect） |
| 5 | `05_intervention_NOT_AVAILABLE/` | 介入/version データ欠如時のschema + prospective protocol + power simulation（**捏造なし**） |
| 6 | `06_alternative_embodiments/` | 代替実施形態とパラメータ範囲 |
| 7 | `07_code/` | 再現用コード（新規モジュール・driver・plot・test。**すべてadditive**） |
| — | `08_spec/claude_code_prompt_fcc_patent_evidence_v3.md` | 生成元スペック（参照） |

---

## キー結果（30秒）

- **ベースライン再現ゲート: PASS（16/16一致）** — 全期間版7指標 + rolling-v2 9ラベルが期待値と完全一致。
- **最強の技術効果**: ①ギャップ品質ティア(IC6)で proxy precision **0.33→0.89** ②二分岐+dual-track(A6)で FW14+Gauge18 を recall **1.0** で回収 ③FCC量子化 **10mWh**・micro(<50mWh) **58.1%**・frozen率 ~50mWh超で頭打ち→50mWh定義を支持。
- **正直な弱点**: 規範モデル AUC≈0.56（ML空洞化）→ 決定論カウンタ構成を推奨。A6は production参照ゆえ precision/recall=1.0 は同義反復。dual-track 中央値ステップ30mWh<50mWh。
- **NOT AVAILABLE**: BIOS/EC/battery-FW version・介入結果データは存在せず → schema/protocol/power-simのみ（捏造なし）。
- **PENDING（未捏造で明示）**: negative controls / response-anchor / response hazard / 完全 retention grid / missingness injection。

## 再現方法（07_code を repo 直下に戻した場合）

```bash
python analyze_fcc_patent_evidence_v3.py --all      # manifest→gate→probe→A/C/H→report
python plot_fcc_patent_evidence_v3.py               # dpi=300 figures
python -m pytest tests/test_fcc_patent_evidence_v3.py -q   # 12 tests
```

## 監査ポイント
- 全数値は `03_evidence_data/` のCSVへ traceable（レポートは disk から読み戻して生成、手打ち数値なし）。
- 既存 production ラベル・出力・テストは**一切変更していない**（git: 新規untrackedのみ／既存tracked変更0）。全89テスト pass。
