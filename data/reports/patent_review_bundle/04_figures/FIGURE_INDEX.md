# 図版インデックス（FIGURE_INDEX）

特許出願レビュー発表パッケージの厳選図版。テーマ別フォルダに格納。各図のキャプションと対応する発明的要素(IC)を示す。

> ⚠️ `09_examples_PII/` の個別端末パネルはファイル名に端末名・ユーザー名（仮名化されていない生ID）を含む。**社外配布・公開前に匿名化／除外**すること。

| テーマ | ファイル | 対応IC | キャプション |
|---|---|---|---|
| 00_problem | `00_problem/soh_overlay_by_class.png` | 背景 | 原因クラス別 SoH 軌跡。凍結群は末尾でFCCが張り付く（静的には正常と判別困難） |
| 00_problem | `00_problem/very_stale_xgb_shap.png` | 背景 | very_stale を使用挙動で予測したXGBoostのSHAP。最重要 min_rsoc は『深放電ほど凍結』の反usage方向 |
| 00_problem | `00_problem/very_stale_tree.png` | 背景 | 解釈可能な決定木。公平領域AUC≈0.54でランダム同然＝行動で説明不能 |
| 00_problem | `00_problem/cohort_soh_vs_cycles.png` | 背景 | SoH vs サイクル数の散布（コホート） |
| 00_problem | `00_problem/soh_reason_trends.png` | 背景 | 凍結トレンド要約（ベンダ別・HW疑い群機種構成・サイクル散布・クラス内訳） |
| 01_core_ic1 | `01_core_ic1/opportunity_vs_response.png` | IC1 | 【核】学習機会(opportunity) × FCC応答(response) の関係。機会あり×応答なしが検出対象 |
| 01_core_ic1 | `01_core_ic1/final_funnel_counts.png` | IC1 | 検出パイプラインのファネル（各段の絞り込み数） |
| 01_core_ic1 | `01_core_ic1/final_label_counts.png` | IC1 | 二分岐ラベル数（gauge-recalibration / firmware-suspected / 他） |
| 01_core_ic1 | `01_core_ic1/tail_unresponded_vs_cycles.png` | IC1 | 末尾の無応答機会 × サイクル。FW疑い群は深くサイクルするのに無応答 |
| 01_core_ic1 | `01_core_ic1/tail_opps_vs_flat_tail.png` | IC1 | 末尾機会数 × 平坦尾部日数 |
| 01_core_ic1 | `01_core_ic1/surrogate_decision_tree.png` | IC1 | 二分岐ロジックの代理決定木（解釈可能・非ブラックボックス） |
| 01_core_ic1 | `01_core_ic1/label_transition_heatmap.png` | IC1 | ベースライン→確定ラベルの遷移ヒートマップ |
| 02_thresholds | `02_thresholds/effective_fcc_step_sensitivity.png` | IC1/IC2 | 有効FCCステップ閾値の感度（≥50mWh で micro-wobble を除外） |
| 02_thresholds | `02_thresholds/response_delay_cdf.png` | IC1 | FCC応答遅延CDF。72hで約95%(0.9513)をカバー＝応答窓72hの根拠 |
| 02_thresholds | `02_thresholds/no_response_probability_by_k.png` | IC1 | 健全応答確率下での連続k回無応答の確率（k=2で0.013）＝計数閾値の根拠 |
| 02_thresholds | `02_thresholds/response_window_sensitivity.png` | IC1 | 応答窓 24/72/168h 摂動の集合安定性（Jaccard=1.0＝閾値非恣意の実証） |
| 02_thresholds | `02_thresholds/flat_tail_distribution.png` | IC1 | 平坦尾部日数分布としきい値（≥180d FW / ≥120d gauge） |
| 02_thresholds | `02_thresholds/tail_cycle_delta_distribution.png` | IC1 | 末尾サイクル増分分布としきい値（≥30） |
| 03_gap_quality_ic6 | `03_gap_quality_ic6/large_gap_opportunity_audit.png` | IC6 | large-gap機会の監査。ロガー休眠/打ち切りを無応答証拠から構造的に除外 |
| 03_gap_quality_ic6 | `03_gap_quality_ic6/large_gap_quality_distribution.png` | IC6 | ギャップ品質ティア分布（HIGH_OK/MEDIUM_GAP/LOW_LARGE_GAP） |
| 03_gap_quality_ic6 | `03_gap_quality_ic6/gap_rule_sensitivity_counts.png` | IC6 | ギャップルール感度（ラベル数の頑健性） |
| 04_stateful_ic5 | `04_stateful_ic5/stateful_vs_stateless_counts.png` | IC5 | 【最堅】stateful vs stateless 検出数。永続状態で窓外証拠を回収（gain=29） |
| 04_stateful_ic5 | `04_stateful_ic5/stateful_only_evidence_examples.png` | IC5 | 30日窓をまたぐエピソードの回収実例。episode_idキーで時刻順リプレイ |
| 05_dualtrack_ic2 | `05_dualtrack_ic2/any_vs_effective_state_scatter.png` | IC2 | any-change(≥1mWh) vs effective(≥50mWh) の二系統状態 |
| 05_dualtrack_ic2 | `05_dualtrack_ic2/micro_wobble_step_distribution.png` | IC2 | micro-wobble ステップ分布（軟较正 soft-calibration への分離） |
| 06_normative_ic4 | `06_normative_ic4/personalized_vs_normative_roc_pr.png` | IC4 | 個別(AUC≈0.82)vs規範(AUC≈0.56)のROC/PR。規範はリーク回避の代償でnear-random |
| 06_normative_ic4 | `06_normative_ic4/personalized_vs_normative_calibration.png` | IC4 | 個別/規範モデルの較正曲線 |
| 06_normative_ic4 | `06_normative_ic4/normative_feature_importance.png` | IC4 | 規範モデルの特徴量重要度（FCC履歴を構造的に除外） |
| 07_v2_results | `07_v2_results/v2_label_counts.png` | 結果 | v2 トリアージラベル数（FW Core5/Watch43/Gauge Core4/Soft22/Review325…） |
| 07_v2_results | `07_v2_results/v2_policy_matrix_heatmap.png` | IC8 | 9段単一ラベル方策マトリクス |
| 07_v2_results | `07_v2_results/v2_funnel_counts.png` | 結果 | v2 ファネル |
| 07_v2_results | `07_v2_results/v2_final_proxy_cross_tab.png` | 結果 | v2 ラベル × バッチ確定(proxy真値)のクロス集計 |
| 07_v2_results | `07_v2_results/fw_topn_yield_curve.png` | 結果 | FW top-N 収量曲線（top50 recall=1.0） |
| 07_v2_results | `07_v2_results/active_false_alert_dual_basis.png` | 結果 | 誤警報率（any-change基準0.71 vs effective基準0） |
| 07_v2_results | `07_v2_results/v2_transition_v1_to_v2.png` | 結果 | v1→v2 ラベル遷移 |
| 07_v2_results | `07_v2_results/lead_time_by_proxy_label.png` | 結果 | proxyラベル別の先行検知リードタイム |
| 08_hw_enrichment_ic3 | `08_hw_enrichment_ic3/hardware_enrichment_fw_core.png` | IC3 | FW Core のHW偏在（分類後の記述的富化。判定には不使用） |
| 08_hw_enrichment_ic3 | `08_hw_enrichment_ic3/eb_enrichment_fw_check.png` | IC3 | 経験ベイズ収縮によるFRU/機種別FW疑い率（Fisher+BH-FDR） |
| 09_examples_PII | `09_examples_PII/example_fw_core.png` | IC1 | FW core 実例：機会反復×FCC無応答（※ファイル名にPII） |
| 09_examples_PII | `09_examples_PII/example_gauge_core.png` | IC1 | Gauge core 実例：適格機会が皆無（※ファイル名にPII） |
| 09_examples_PII | `09_examples_PII/example_normal_responding.png` | 対照 | 正常応答の対照例（機会後にFCCが応答）（※ファイル名にPII） |

合計 41 図 / 欠落 0: []