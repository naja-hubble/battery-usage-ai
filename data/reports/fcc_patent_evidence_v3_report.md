# FCC学習応答技術 特許性強化エビデンス報告 v3

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術の特許番号はAIサーベイ由来で未検証。出願前に登録弁理士のレビュー必須。

## 0. 入力
`input_manifest_patent_v3.csv`（SHA-256/行数/user数/期間/列）参照。母集団=実バッテリ履歴 752 users。

## 1. ベースライン再現ゲート: **PASS**
`patent_baseline_gate_v3.csv`。全期間版7指標 + rolling-v2 9ラベルを期待値と完全照合。

## 2. データ可用性
intervention / BIOS / EC / battery-FW version = **NOT AVAILABLE**（`availability_probe_v3.json`）。
NOT AVAILABLE のため Analysis F/G は schema + prospective protocol + power simulation のみ（捏造なし）。

## 3. 最も強い技術効果 Top 3
1. **ギャップ品質ティア(IC6)による精度向上**: proxy precision 0.3273(A0 静的) → **0.8889**(A5)。
2. **二分岐+デュアルトラック(IC1分岐/IC2)による全捕捉**: A6 で FW 14+Gauge 18（recall 1.0、production参照）。
3. **デュアルトラック閾値の実証(IC2)**: quantization 10mWh、micro(<50mWh) 58.1%、frozen率は~50mWh超で頭打ち。

## 4. Analysis A — ablation 比較
| variant   | description                                             | invention_family   |   n_flagged |   legacy_active_false_action |   effective_active_false_action |   proxy_precision |   proxy_recall |   label_jaccard_vs_production |   proxy_fw_captured |   proxy_gauge_captured |   proxy_fw_missed_silent |   proxy_gauge_missed_silent |
|:----------|:--------------------------------------------------------|:-------------------|------------:|-----------------------------:|--------------------------------:|------------------:|---------------:|------------------------------:|--------------------:|-----------------------:|-------------------------:|----------------------------:|
| A0        | flat_tail_days>=180 only                                | static-baseline    |          55 |                            0 |                              36 |            0.3273 |         0.5625 |                        0.2609 |                   9 |                      9 |                        5 |                           9 |
| A1        | flat tail + tail_cycle_delta>=30                        | static-baseline    |          35 |                            0 |                              23 |            0.3143 |         0.3438 |                        0.1964 |                   9 |                      2 |                        5 |                          16 |
| A2        | stale + >=1 any-quality opportunity (no response check) | IC1-stimulus       |          44 |                            0 |                              27 |            0.2045 |         0.2812 |                        0.1343 |                   9 |                      0 |                        5 |                          18 |
| A3        | END+response but censor/gap counted as no-response      | IC1-naive          |          30 |                            0 |                              18 |            0.3    |         0.2812 |                        0.1698 |                   9 |                      0 |                        5 |                          18 |
| A4        | END-anchored, censor-aware, single step (IC1 core)      | IC1                |          30 |                            0 |                              18 |            0.3    |         0.2812 |                        0.1698 |                   9 |                      0 |                        5 |                          18 |
| A5        | IC1 + gap-quality tier (exclude large_gap)              | IC1+IC6            |           9 |                            0 |                               5 |            0.8889 |         0.25   |                        0.2424 |                   8 |                      0 |                        6 |                          18 |
| A6        | full proposed (production final_label actionable)       | IC1+IC6+IC2+branch |          32 |                            0 |                              18 |            1      |         1      |                        1      |                  14 |                     18 |                        0 |                           0 |

> 注: A6 は production final_label そのものであり precision/recall=1.0 は同義反復。技術効果は A0→A5 の精度上昇と、
> A6 で二分岐(IC1)+デュアルトラック(IC2)が gauge recall を回収する点にある。A2–A4 の非単調は、ギャップ/censor
> 除外なしでは機会要件付与がノイズ集合を拾うことを示す（IC6の必要性の傍証）。

## 5. Analysis C — any/effective dual-track
`dual_track_threshold_analysis.csv` / `dual_track_step_magnitude_summary.csv`。
quantization=10mWh, p50=30, p90=620mWh。
50mWh は micro モード(10–30mWh)と effective モード(数百mWh)の間に位置。正直な留保: 中央値ステップ(30mWh)は50mWh未満。

## 6. Analysis H — 技術効果（検出器比較）
| detector                 |   n_flagged_actionable |   overlap_with_production_actionable |   production_normal_falsely_flagged |   had_lifetime_effective_step_descriptive |   hard_calibration_prompts |
|:-------------------------|-----------------------:|-------------------------------------:|------------------------------------:|------------------------------------------:|---------------------------:|
| static_fcc_stale_rule    |                     55 |                                   18 |                                   0 |                                        36 |                         55 |
| full_history_proposed    |                     32 |                                   32 |                                   0 |                                        18 |                         18 |
| rolling_stateless_core   |                     15 |                                    2 |                                   3 |                                        10 |                         15 |
| rolling_stateful_v2_core |                      9 |                                    9 |                                   0 |                                         5 |                          4 |
storage: 永続状態/raw 比 ≈ 0.048（`patent_storage_tradeoff.csv`）。

## 7. 新規性を弱める結果（正直な開示）
- 規範モデル AUC≈0.56（near-random）→ ML/異常スコアは独立クレームに不適。決定論カウンタで構成すべき。
- A6 の完全一致は production 参照ゆえ同義反復。proxy は真の地上真実ではない。
- dual-track 中央値ステップ30mWh<50mWh（閾値は分布の谷だが中央値より上）。

## 8. クローズドループ / version データ可用性
**NOT AVAILABLE**。`fcc_intervention_data_schema_v3.csv` / `fcc_intervention_protocol_v3.md` /
`fcc_intervention_power_simulation_v3.csv` / `fcc_firmware_version_schema_v3.csv` を生成。

## 9. 発明family別 evidence strength
- IC1（機会条件付き無応答+censor除外+二分岐）: **STRONG**（ablationで分離実証）。
- IC6（ギャップ品質）: **STRONG**（A5 vs A4）。
- IC2（dual-track）: **STRONG**（経験分布）。
- IC5（stateful窓外回収）: **MEDIUM**（production backtest引用。完全retention grid は PENDING）。
- IC4（規範ベースライン）: ML として WEAK / リーク回避の正直さとして有効。

## 10. 未解決事項（PENDING、未捏造）
- Analysis A.2 negative controls (circular-shift / permutation, user-bootstrap CI) — raw-trace, PENDING
- Analysis A.3 response-anchor comparison (start/low/end) — PENDING
- Analysis B response hazard (KM/cumulative-incidence true vs pseudo episode) — PENDING
- Analysis D full retention grid (7..90d x stride 1/7 x alignment 0..6 x stateless/stateful) — PENDING
- Analysis E missingness/sleep-gap/censor injection stress — PENDING
- Analysis F/G intervention & firmware-version analyses — NOT AVAILABLE (schema+protocol+power-sim only)

## 11. 生成物
- data/processed/fcc_patent_evidence_v3/: input_manifest, baseline_gate, availability_probe, ablation,
  dual_track_*, technical_effects, storage_tradeoff
- data/reports/figures/fcc_patent_evidence_v3/: ablation / dual_track / technical_effect（全 dpi=300・匿名）
- data/reports/: 本報告, invention_disclosure, claim_support_matrix, prior_art_feature_matrix,
  alternative_embodiments, intervention_protocol/schema/power_simulation, figure_captions
