# FCC学習応答技術 特許性強化エビデンス報告 v4（PENDING解析の完了）

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術はAIサーベイ由来で**未検証(UNVERIFIED)**。出願前に登録弁理士のレビュー必須。地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。

## 0. 位置づけ
v3技術エビデンスは保全のうえ不変。本v4はv3が `PENDING` とした生トレース解析
（A2 negative controls / A3 anchor / B response hazard / D retention grid / E missingness）を
完了し、C2 非対称リセット直接アブレーションと C3 データ駆動閾値を追加。母集団=実バッテリ履歴 752 users。
入力ハッシュ・行数は `patent_results_manifest_v4.csv` 参照。

## 1. ベースライン再現ゲート: **PASS**
`patent_baseline_gate_v4.csv`。全期間7指標 + rolling-v2 9ラベルを期待値と完全照合。
不一致時は実質結論を出さない設計。

## 2. データ可用性
intervention / BIOS / EC / battery-FW version = **NOT AVAILABLE**（`availability_probe_v4.json`）。
NOT AVAILABLE のため IC7 クローズドループは prospective protocol + power simulation のみ（捏造なし）。

## 3. 独立技術効果エンドポイント（proxyラベルに依存しない、Section 11）
| endpoint                               | supported   | technical_effect                                                                            |
|:---------------------------------------|:------------|:--------------------------------------------------------------------------------------------|
| stimulus_response_specificity          | True        | response specifically tied to true qualified END, not elapsed time / activity / identity    |
| end_anchor_low_contamination           | True        | END anchoring removes mid-cycle causal contamination of the response count                  |
| response_time_to_event                 | True        | true qualified episodes trigger faster/greater effective response than matched pseudo       |
| evidence_preservation_under_micro_step | True        | asymmetric reset preserves unresolved learning-response evidence a micro step would erase   |
| hard_action_ambiguity_reduction        | True        | dual-track routes micro-wobble users to soft calibration, fewer hard resets                 |
| effective_threshold_data_support       | True        | bimodal step magnitude; 50mWh fallback sits above the data-driven micro/effective valley    |
| bounded_retention_equivalence          | True        | a bounded-retention causal ledger reproduces full-history evidence at a fraction of storage |
| minimal_sufficient_state               | True        | named state components are each necessary; removing one breaks an equivalence invariant     |
| censor_gap_false_escalation_robustness | True        | graded+censor-aware method suppresses false no-response under injected gaps/censoring       |

## 4. A2 — 負の対照と時間的反証（IC1）
真のEND-anchored有効FCC応答確率(72h) = **0.38990426457789384**。
5つの対照（circular step / episode shift, within-user time randomization, matched pseudo,
RSOC phase-shift）で真値が95%ヌル区間外 = **5/5**、
user-bootstrapで方向一致 = **4/5**。
→ 刺激-応答効果: **SUPPORTED**。
（`negative_control_summary.csv`, 図 `negative_control_true_vs_null.png`,
`negative_control_randomization_distribution.png`）。
within-user の純粋なラベル置換はプール率を不変にするため、操作的対照は同一user内の時刻ランダム化とした（正直な注記）。

## 5. A3 — 応答アンカー比較（IC1の因果汚染）
「因果汚染」= recharge完了(episode end)より前に発生したFCCステップを応答として計数すること（proxy非依存で定義）。
72h汚染率: **END=0.0**, START=0.55692,
LOW=0.27011。END-anchorは構造的に汚染0。
production(any-change)とのEND一致率 = 0.93273。
→ END-anchorの計測可能な優位性: **YES**。
（`response_anchor_comparison.csv`, 図 `response_anchor_contamination.png`, `response_anchor_delay_cdf.png`）。
charge-termination anchor は per-sample電流/テーパ情報が **NOT AVAILABLE** のためEND代理（捏造せず明記）。

## 6. B — 応答ハザード／累積発生（IC1の時間構造）
50mWh有効応答の累積発生(CIF) 72h=**0.39014462406052197**、
真 vs 一致pseudo: **0.39014462406052197** vs **0.28618781469964083**（差 0.10395680936088114）、
有効応答中央値 49.08h。閾値別/品質別/帯別曲線は `response_hazard_summary.csv`、user-clustered bootstrap CI付き。
（`response_hazard_summary.csv`, 図 `response_hazard_true_vs_pseudo.png`, `_by_quality.png`, `_by_threshold.png`）。

## 7. C2 — デュアルトラック非対称リセット直接アブレーション（IC2）
同一イベント列を D0..D5 でリプレイ（complete<reset<deadline順序）。
対称リセット(D2)はmicroステップで **pending 1802 / confirmed no-response 462**
を 281 usersで消去。非対称(D4=production)はこれを保持し、対称比 **+115** の
confirmed no-responseを温存。effective-only(D1)比でhard計 **209→97**
（micro-wobble→soft 112）。→ 非対称リセット: **SUPPORTED**。
（`dual_track_reset_ablation.csv`, `dual_track_erased_evidence_events.parquet`, 図 `dual_track_reset_semantics.png`, `dual_track_erased_evidence.png`）。
> **重要な開示（IC2の新規性）**: D4 非対称リセットは **既に production の rolling-v2 (`battery_usage/online_step_state.py`) に実装済み**である。
> 本v4のアブレーションはその設計を**特徴付け・検証**するものであり、設計それ自体を新たに着想したことの証拠ではない。
> 新規性/進歩性は**着想日**に依存する法的論点であり、出願前に弁理士が判断する。技術エビデンスは設計の効果を支持するが、
> 新規性は主張しない。

## 8. C3 — データ駆動有効ステップ閾値（IC2b）
quantization=10.0mWh、GMM 2成分 micro=14.15 / effective=216.85mWh、
valley=35.23mWh（bootstrap CI: `effective_threshold_bootstrap.csv`）。micro(<50mWh)率=0.5814。
**正直な所見**: 永続/反転解析で micro ステップは effective より**持続的・反転少**（reversal24h micro=0.1363 < eff=0.3556）。
よって sub-50mWh を「ノイズ」とは呼ばず「micro-step」とする（spec 8.2）。
**注**: 永続/反転は事前指定の50mWhで分割しており、50mWhを一意にデータ正当化するものではない。50mWhは
GMM valley のbootstrap CI 範囲内（`effective_threshold_bootstrap.csv`）に収まることで独立に裏付けられる。
閾値の正当化は量子化・二峰分布・GMM valley・C2の証拠消去回避にあり、ノイズ論ではない。
推奨スコープ: narrow=固定50mWh / medium=量子化・ノイズ帯超 / broad=適応 max(k·quant, α·Design, noise pct)（`effective_threshold_recommendation.json`）。

## 9. D — 保持不変グリッド + 最小十分状態（IC5）
ステートフル（有界raw+永続最小状態）は全保持窓(7..90d)で recall=1, duplicate=0, response一致=1, no-response MAE≈0。
有界(W=30d) vs 完全保持の同一エンジン検証: recall=**1.0**, dup=**0**,
no-response MAE=**0.02**（`retention_stateful_verification.csv`）。
ステートレス@7d: recall=0.8146, duplicate_rate=2.1304（重複検出）。
最小状態アブレーション: 必要構成 = ['eff_cycle', 'fsm', 'gap_censor', 'last_eff_ts', 'ordering', 'pending', 'seen_ids']（各除去で命名済み不変量が破綻）。
最小ステートフル等価ストレージ比 = **0.0417**。
→ IC5 等価性: **達成（STRONGへ昇格）**。
（`retention_invariance_grid.parquet`, `retention_invariance_summary.csv`, `minimal_state_ablation.csv`,
`storage_compute_tradeoff.csv`, 図 `retention_invariance_heatmap.png`, `minimal_state_necessity.png`, `storage_vs_equivalence.png`）。

## 10. E — 欠測／睡眠ギャップ／打ち切りストレス（IC6）
注入regime（MCAR 5..50%、連続ギャップ 3..48h×位置、末尾打ち切り、フリート睡眠ギャップ）下で
4検出器を比較。誤confirmed no-response（regime平均）: naive=**643.317** →
proposed(graded+censor-aware)=**4.1**（削減 639.217）。
proposed episode recovery=**0.9663**。binary_gap_gateは過剰除外（missed増）。
graded→proposedでさらにcensor-aware分の誤検出が減少（IC6の二段効果）。
→ IC6 ギャップ/打ち切り便益: **SUPPORTED**。
（`missingness_stress_summary.csv`, 図 `missingness_false_escalation.png`, `missingness_quality_tier_benefit.png`, `censor_injection_safety.png`）。

## 11. 発明family別 evidence strength（v3→v4）
| family   | evidence_strength_v4                        | v3_to_v4_change                                                                                                                                   |
|:---------|:--------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------|
| IC1      | STRONG                                      | v3->v4: ADD raw-trace negative controls + anchor contamination (was PENDING)                                                                      |
| IC2      | STRONG                                      | v3->v4: ADD direct D0..D5 ablation (design ALREADY IN PRODUCTION online_step_state.py; v4 CHARACTERIZES/VALIDATES it, does not newly conceive it) |
| IC5      | STRONG                                      | v3->v4: UPGRADE MEDIUM->STRONG (full grid + verified equivalence, was PENDING)                                                                    |
| IC6      | STRONG                                      | v3->v4: ADD injection stress test (was PENDING)                                                                                                   |
| IC7      | PROSPECTIVE                                 | remains PROSPECTIVE until real intervention columns exist (non-fabrication)                                                                       |
| IC8      | MEDIUM-SCREENING / PROSPECTIVE-LOCALIZATION | screening MEDIUM; localization PROSPECTIVE until version fields exist                                                                             |
| IC4      | WEAK-as-ML / STRONG-as-honesty              | not relied on for inventive step (honest caveat retained)                                                                                         |

## 12. v3叙述の訂正・限定（Section 13・必須）
1. **A3/A4の集計指標は同一**であり、v3はラベルレベルでcensor除外効果を**未分離**だった。
   v4でA2/A3/Eにより独立に定量化（END汚染0 vs START 0.55692、E誤no-response削減）。
2. **A5 precision=0.8889** は production proxy・小標本(n=9)・recall低下に基づく。v4は直接技術エンドポイント
   （`patent_technical_effects_v4.csv`）とuser-bootstrap CIを提示し、precision単独に依存しない。
3. **A6 precision/recall=1.0 は同義反復**（production参照そのもの）であり、独立validationとして提示しない。
4. **「False action」は独立エンドポイントに紐づかない限り使用しない**。"production-NORMAL flagged" /
   "observed responder flagged" / "hard intervention issued" を用いる（responder保護はC2/Eで計測）。
5. **固定50mWhは一実施形態**。広い発明概念はゲージ量子化・ノイズ帯を超える（できれば適応）有効閾値（C3）。
6. **規範MLは発明的性能結果ではない**（AUC≈0.56 near-random）。決定論カウンタで構成。
7. **クローズドループ回復は実介入データが出るまで prospective**（IC7、NOT AVAILABLE、捏造なし）。

## 13. 限界（正直な開示）
- proxyラベルは production 出力であり真の地上真実ではない。技術効果は独立エンドポイント（Sec.3）で評価。
- A2のmatched-pseudo / RSOC phase-shift対照は保守的（実観測時刻に依存）で部分ヌル。強い対照(circular/within-user)で方向一致。
- MCAR 50%では proposed でも episode recovery低下（~0.84）。現実的regime（連続ギャップ・打ち切り）では堅牢。
- D等価性は「同一検出器の有界 vs 完全保持」で検証（応答定義に非依存）。微小残差は末尾deadlineの境界効果。
- 先行技術番号はUNVERIFIED。novelty/inventive step/侵害自由/登録可能性は一切主張しない。

## 14. 生成物
`data/processed/fcc_patent_evidence_v4/` 配下に全CSV/parquet + `patent_results_manifest_v4.csv`（SHA-256）。
図は `data/reports/figures/fcc_patent_evidence_v4/`（全 dpi=300・匿名、user_id/serial/UUID無し）。
報告書: 本報告 / `fcc_invention_disclosure_v4.md` / `fcc_patent_counsel_brief_v4.md` / `fcc_patent_v4_adversarial_review.md`。
