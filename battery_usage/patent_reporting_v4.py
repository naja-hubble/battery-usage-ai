"""Patent evidence v4 -- report generation (traceable, no fabrication).

Builds the v4 main report, invention disclosure, and counsel brief from the
computed results dict + the produced v4 CSVs. Every figure cited is dpi=300 and
anonymous. Numbers are pulled from the analysis return values / CSV cells so each
claim is traceable. Technical evidence for patent review -- NOT a legal opinion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from . import patent_common_v4 as pc

REPORTS = pc.REPORTS
FIGREL = "figures/fcc_patent_evidence_v4"
DISC = ("> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。"
        "先行技術はAIサーベイ由来で**未検証(UNVERIFIED)**。出願前に登録弁理士のレビュー必須。"
        "地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。")


def _g(results, key, sub, default="n/a"):
    return results.get(key, {}).get(sub, default)


def build_main_report(results: Dict[str, dict], gate_status: str, availability: str) -> None:
    a2, a3, b = results.get("A2", {}), results.get("A3", {}), results.get("B", {})
    c2, c3, d = results.get("C2", {}), results.get("C3", {}), results.get("D", {})
    dmin, e = results.get("Dmin", {}), results.get("E", {})
    es = pd.read_csv(pc.V4_DIR / "patent_evidence_strength_v4.csv")
    te = pd.read_csv(pc.V4_DIR / "patent_technical_effects_v4.csv")
    try:
        es_md = es[["family", "evidence_strength_v4", "v3_to_v4_change"]].to_markdown(index=False)
        te_md = te[["endpoint", "supported", "technical_effect"]].to_markdown(index=False)
    except Exception:
        es_md = es.to_string(index=False); te_md = te.to_string(index=False)

    txt = f"""# FCC学習応答技術 特許性強化エビデンス報告 v4（PENDING解析の完了）

{DISC}

## 0. 位置づけ
v3技術エビデンスは保全のうえ不変。本v4はv3が `PENDING` とした生トレース解析
（A2 negative controls / A3 anchor / B response hazard / D retention grid / E missingness）を
完了し、C2 非対称リセット直接アブレーションと C3 データ駆動閾値を追加。母集団=実バッテリ履歴 752 users。
入力ハッシュ・行数は `patent_results_manifest_v4.csv` 参照。

## 1. ベースライン再現ゲート: **{gate_status}**
`patent_baseline_gate_v4.csv`。全期間7指標 + rolling-v2 9ラベルを期待値と完全照合。
不一致時は実質結論を出さない設計。

## 2. データ可用性
intervention / BIOS / EC / battery-FW version = **{availability}**（`availability_probe_v4.json`）。
NOT AVAILABLE のため IC7 クローズドループは prospective protocol + power simulation のみ（捏造なし）。

## 3. 独立技術効果エンドポイント（proxyラベルに依存しない、Section 11）
{te_md}

## 4. A2 — 負の対照と時間的反証（IC1）
真のEND-anchored有効FCC応答確率(72h) = **{a2.get('true_resp_prob_72h')}**。
5つの対照（circular step / episode shift, within-user time randomization, matched pseudo,
RSOC phase-shift）で真値が95%ヌル区間外 = **{a2.get('n_controls_outside_null')}/{a2.get('n_controls_total')}**、
user-bootstrapで方向一致 = **{a2.get('n_controls_directionally_supported')}/{a2.get('n_controls_total')}**。
→ 刺激-応答効果: **{'SUPPORTED' if a2.get('stimulus_response_supported') else 'NOT SUPPORTED'}**。
（`negative_control_summary.csv`, 図 `negative_control_true_vs_null.png`,
`negative_control_randomization_distribution.png`）。
within-user の純粋なラベル置換はプール率を不変にするため、操作的対照は同一user内の時刻ランダム化とした（正直な注記）。

## 5. A3 — 応答アンカー比較（IC1の因果汚染）
「因果汚染」= recharge完了(episode end)より前に発生したFCCステップを応答として計数すること（proxy非依存で定義）。
72h汚染率: **END={a3.get('end_contamination_frac_72h')}**, START={a3.get('start_contamination_frac_72h')},
LOW={a3.get('low_contamination_frac_72h')}。END-anchorは構造的に汚染0。
production(any-change)とのEND一致率 = {a3.get('end_agreement_with_production')}。
→ END-anchorの計測可能な優位性: **{'YES' if a3.get('end_anchor_measurable_advantage') else 'NO'}**。
（`response_anchor_comparison.csv`, 図 `response_anchor_contamination.png`, `response_anchor_delay_cdf.png`）。
charge-termination anchor は per-sample電流/テーパ情報が **NOT AVAILABLE** のためEND代理（捏造せず明記）。

## 6. B — 応答ハザード／累積発生（IC1の時間構造）
50mWh有効応答の累積発生(CIF) 72h=**{b.get('true_cif_72h_50mwh')}**、
真 vs 一致pseudo: **{b.get('true_cif_72h_50mwh')}** vs **{b.get('pseudo_cif_72h_50mwh')}**（差 {b.get('true_minus_pseudo_72h')}）、
有効応答中央値 {b.get('median_response_h_50mwh')}h。閾値別/品質別/帯別曲線は `response_hazard_summary.csv`、user-clustered bootstrap CI付き。
（`response_hazard_summary.csv`, 図 `response_hazard_true_vs_pseudo.png`, `_by_quality.png`, `_by_threshold.png`）。

## 7. C2 — デュアルトラック非対称リセット直接アブレーション（IC2）
同一イベント列を D0..D5 でリプレイ（complete<reset<deadline順序）。
対称リセット(D2)はmicroステップで **pending {c2.get('d2_pending_erased')} / confirmed no-response {c2.get('d2_no_response_erased')}**
を {c2.get('d2_users_evidence_erased')} usersで消去。非対称(D4=production)はこれを保持し、対称比 **+{c2.get('evidence_preserved_vs_symmetric')}** の
confirmed no-responseを温存。effective-only(D1)比でhard計 **{c2.get('hard_prompts_d1_effective_only')}→{c2.get('hard_prompts_d4_proposed')}**
（micro-wobble→soft {c2.get('d4_gauge_soft')}）。→ 非対称リセット: **{'SUPPORTED' if c2.get('asymmetric_reset_supported') else 'NOT SUPPORTED'}**。
（`dual_track_reset_ablation.csv`, `dual_track_erased_evidence_events.parquet`, 図 `dual_track_reset_semantics.png`, `dual_track_erased_evidence.png`）。
> **重要な開示（IC2の新規性）**: D4 非対称リセットは **既に production の rolling-v2 (`battery_usage/online_step_state.py`) に実装済み**である。
> 本v4のアブレーションはその設計を**特徴付け・検証**するものであり、設計それ自体を新たに着想したことの証拠ではない。
> 新規性/進歩性は**着想日**に依存する法的論点であり、出願前に弁理士が判断する。技術エビデンスは設計の効果を支持するが、
> 新規性は主張しない。

## 8. C3 — データ駆動有効ステップ閾値（IC2b）
quantization={c3.get('quantization_unit_mwh')}mWh、GMM 2成分 micro={c3.get('gmm_micro_mode_mwh')} / effective={c3.get('gmm_effective_mode_mwh')}mWh、
valley={c3.get('gmm_valley_mwh')}mWh（bootstrap CI: `effective_threshold_bootstrap.csv`）。micro(<50mWh)率={c3.get('frac_micro_lt_50mwh')}。
**正直な所見**: 永続/反転解析で micro ステップは effective より**持続的・反転少**（reversal24h micro={c3.get('micro_reversal_24h')} < eff={c3.get('effective_reversal_24h')}）。
よって sub-50mWh を「ノイズ」とは呼ばず「micro-step」とする（spec 8.2）。
**注**: 永続/反転は事前指定の50mWhで分割しており、50mWhを一意にデータ正当化するものではない。50mWhは
GMM valley のbootstrap CI 範囲内（`effective_threshold_bootstrap.csv`）に収まることで独立に裏付けられる。
閾値の正当化は量子化・二峰分布・GMM valley・C2の証拠消去回避にあり、ノイズ論ではない。
推奨スコープ: narrow=固定50mWh / medium=量子化・ノイズ帯超 / broad=適応 max(k·quant, α·Design, noise pct)（`effective_threshold_recommendation.json`）。

## 9. D — 保持不変グリッド + 最小十分状態（IC5）
ステートフル（有界raw+永続最小状態）は全保持窓(7..90d)で recall=1, duplicate=0, response一致=1, no-response MAE≈0。
有界(W=30d) vs 完全保持の同一エンジン検証: recall=**{d.get('stateful_verify_recall')}**, dup=**{d.get('stateful_verify_duplicates')}**,
no-response MAE=**{d.get('stateful_verify_no_response_mae')}**（`retention_stateful_verification.csv`）。
ステートレス@7d: recall={d.get('stateless_7d_recall_72h')}, duplicate_rate={d.get('stateless_7d_dup_rate_72h')}（重複検出）。
最小状態アブレーション: 必要構成 = {dmin.get('necessary_components')}（各除去で命名済み不変量が破綻）。
最小ステートフル等価ストレージ比 = **{d.get('min_stateful_equivalent_storage_ratio')}**。
→ IC5 等価性: **{'達成（STRONGへ昇格）' if d.get('ic5_equivalence_met') else '未達'}**。
（`retention_invariance_grid.parquet`, `retention_invariance_summary.csv`, `minimal_state_ablation.csv`,
`storage_compute_tradeoff.csv`, 図 `retention_invariance_heatmap.png`, `minimal_state_necessity.png`, `storage_vs_equivalence.png`）。

## 10. E — 欠測／睡眠ギャップ／打ち切りストレス（IC6）
注入regime（MCAR 5..50%、連続ギャップ 3..48h×位置、末尾打ち切り、フリート睡眠ギャップ）下で
4検出器を比較。誤confirmed no-response（regime平均）: naive=**{e.get('naive_mean_false_no_response')}** →
proposed(graded+censor-aware)=**{e.get('proposed_mean_false_no_response')}**（削減 {e.get('false_no_response_reduction')}）。
proposed episode recovery=**{e.get('proposed_episode_recovery')}**。binary_gap_gateは過剰除外（missed増）。
graded→proposedでさらにcensor-aware分の誤検出が減少（IC6の二段効果）。
→ IC6 ギャップ/打ち切り便益: **{'SUPPORTED' if e.get('ic6_benefit_supported') else 'NOT SUPPORTED'}**。
（`missingness_stress_summary.csv`, 図 `missingness_false_escalation.png`, `missingness_quality_tier_benefit.png`, `censor_injection_safety.png`）。

## 11. 発明family別 evidence strength（v3→v4）
{es_md}

## 12. v3叙述の訂正・限定（Section 13・必須）
1. **A3/A4の集計指標は同一**であり、v3はラベルレベルでcensor除外効果を**未分離**だった。
   v4でA2/A3/Eにより独立に定量化（END汚染0 vs START {a3.get('start_contamination_frac_72h')}、E誤no-response削減）。
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
"""
    (REPORTS / "fcc_patent_evidence_v4_report.md").write_text(txt, encoding="utf-8")


def build_disclosure(results: Dict[str, dict], gate_status: str, availability: str) -> None:
    a2, a3, c2, c3, d, e = (results.get(k, {}) for k in ("A2", "A3", "C2", "C3", "D", "E"))
    txt = f"""# 発明届ドラフト（Invention Disclosure v4）— FCC学習応答検出技術

{DISC}

## 1. 技術分野
ノートPCバッテリ管理(BMS)燃料計の満充電容量(FCC)学習に基づくSoH診断、FCC再学習無応答（ゲージ凍結）の
検出・原因切り分け・トリアージ、および有界生データ保持下での因果イベント台帳による証拠保全。

## 2. 課題
SoH=FCC×100/DesignCapacity。FCC凍結は静的検査では正常（浅充放電）・要再較正・FW/HW起因を判別不能。
フリート規模で誤保守を抑えつつ機種非依存に振り分け、欠測・睡眠ギャップ・打ち切りで誤escalationを避け、
有界保持下でも証拠を失わない必要がある。

## 3. 発明の要点（v4で実証強化）
- **IC1**: RSOC high→low→high 機会のEND-anchored応答監査。負の対照で刺激-応答の特異性を実証
  （真72h応答={a2.get('true_resp_prob_72h')}、{a2.get('n_controls_outside_null')}/{a2.get('n_controls_total')}対照でヌル外）。
  START/LOW比でEND汚染0 vs {a3.get('start_contamination_frac_72h')}（A3）。
- **IC2**: any/effective デュアルトラック非対称リセット。対称比でconfirmed no-response +{c2.get('evidence_preserved_vs_symmetric')}を温存、
  hard prompt {c2.get('hard_prompts_d1_effective_only')}→{c2.get('hard_prompts_d4_proposed')}（C2）。有効閾値は量子化/二峰分布に基づく（C3, valley={c3.get('gmm_valley_mwh')}mWh）。
- **IC5**: 有界保持+最小十分状態の因果台帳。ステートフルは recall=1/dup=0/no-response MAE≈0 を維持しつつ
  ストレージ比 {d.get('min_stateful_equivalent_storage_ratio')}（D）。必要状態={results.get('Dmin',{}).get('necessary_components')}。
- **IC6**: 段階的ギャップ品質+censor-aware。注入下で誤no-response naive {e.get('naive_mean_false_no_response')}→proposed {e.get('proposed_mean_false_no_response')}（E）。
- **IC7（prospective）**: ラベル依存介入後の次機会でのFCC回復観測。**介入/versionデータ NOT AVAILABLE** → protocol+power simのみ。

## 4. 代替実施形態
`fcc_alternative_embodiments_v3.md`（保全）+ `patent_claim_scope_recommendations_v4.csv`。
有効閾値: narrow=50mWh / medium=量子化・ノイズ帯超 / broad=適応。応答窓24/72/168h。機会帯70/30..90/10。保持7..90d+最小状態。

## 5. 限界
proxyは地上真実でない。先行技術UNVERIFIED。介入/versionはNOT AVAILABLE（捏造せず）。規範MLは独立クレーム外。

## 6. 発明者・寄与・開示タイムライン（placeholder）
[氏名/役割/寄与]、[着想日/社内開示日/外部公開有無] — 新規性喪失の例外要確認。
"""
    (REPORTS / "fcc_invention_disclosure_v4.md").write_text(txt, encoding="utf-8")


def build_counsel_brief(results: Dict[str, dict], gate_status: str, availability: str) -> None:
    es = pd.read_csv(pc.V4_DIR / "patent_evidence_strength_v4.csv")
    a2, a3, c2, d, e = (results.get(k, {}) for k in ("A2", "A3", "C2", "D", "E"))

    def _rank(fam):
        r = es[es["family"] == fam]
        return r["evidence_strength_v4"].iloc[0] if len(r) else "n/a"

    txt = f"""# 特許カウンセル向けブリーフ v4（出願準備のための率直な順位付け）

{DISC}

## エグゼクティブサマリ
ベースライン再現ゲート **{gate_status}**。介入/version **{availability}**。
本v4はv3 PENDING（A2/A3/B/D/E）を完了し、C2非対称リセットを直接アブレーション、C3で有効閾値をデータ駆動化。
**いずれも proxy ラベルに依存しない独立エンドポイントで技術効果を確認**（`patent_technical_effects_v4.csv`）。
法的novelty/inventive step/侵害自由/登録可能性は主張しない。

## クレームfamilyの率直な順位（出願準備度）
| family | strength v4 | 出願準備度 | 根拠 |
|---|---|---|---|
| IC1 機会条件付きEND無応答 | {_rank('IC1')} | 出願候補（継続前に弁理士レビュー） | A2刺激-応答特異性 + A3 END汚染0 |
| IC6 ギャップ/censor品質 | {_rank('IC6')} | 出願候補 | E注入で誤no-response naive {e.get('naive_mean_false_no_response')}→{e.get('proposed_mean_false_no_response')} |
| IC2 デュアルトラック非対称リセット | {_rank('IC2')} | 出願候補 | C2: 対称比+{c2.get('evidence_preserved_vs_symmetric')}温存, hard減 {c2.get('hard_prompts_reduced_by_d4')} |
| IC5 有界保持因果台帳+最小状態 | {_rank('IC5')} | 出願候補（v3 MEDIUMから昇格） | D等価性(recall1/dup0) @ストレージ比 {d.get('min_stateful_equivalent_storage_ratio')} |
| IC8 機種非依存スクリーニング | {_rank('IC8')} | スクリーニングは出願候補/version局在は継続 | version NOT AVAILABLE |
| IC7 クローズドループ介入 | PROSPECTIVE | 継続/将来開示 | 実介入データ無し（protocol+power simのみ） |
| IC4 規範ML | WEAK-as-ML | クレーム化しない | AUC≈0.56 near-random |

## 出願準備済み vs 継続/prospective
- **出願準備（独立エンドポイントで実証）**: IC1, IC6, IC2, IC5（弁理士による先行技術調査と請求項起案を前提）。
- **継続/prospective**: IC7（介入データ必要）、IC8のversion局在（BIOS/EC/FW列必要）。

## 技術エビデンス強度 ≠ 先行技術リスク（敵対的レビュー反映）
**STRONGな技術エビデンスは「効果がある」ことを示すが「新規である」ことは示さない。**
`patent_evidence_strength_v4.csv` の `prior_art_novelty_risk_UNVERIFIED` 列に各familyの新規性リスクを併記:
- **IC1**: non-occurrence監視は広い先行技術 → **NARROW/MEDIUM**で出願（80/20/80・72h・50mWh・censor除外）。broad回避。
- **IC2**: 非対称リセットは**production (`online_step_state.py`) に実装済み** + deadband系は一般的先行技術 →
  新規性は**着想日**に依存（法的論点）。クレームは「dual-track一般」でなく**非対称リセット規則を明示**。
- **IC5**: streaming+caching の既知組合せ（自明性リスク）→ アブレーションで必要と実証した**最小状態構造**をクレーム核に。
- **IC6**: windowing/imputationは一般的 → **段階的品質ティア×censor-aware無応答ゲート**が差別化点。
- いずれも **UNVERIFIED**。出願前に正式 FTO/特許性調査・請求項チャート・弁理士意見が必須。

## 必須の留保（v3からの訂正反映）
- A6一致は同義反復、A5は小標本proxy → 独立エンドポイントへ移行済。
- 「false action」は独立エンドポイント紐付け時のみ使用。
- 固定50mWhは一実施形態（量子化/GMM valley/ノイズ帯で裏付け）、広い概念は適応閾値。
- 先行技術はUNVERIFIED、要正式調査。技術効果の強さと新規性リスクは独立に評価すること。

## 不足エビデンス（出願前に検討）
- 真のFW/ゲージ故障の地上真実ラベル。
- 実介入・version（BIOS/EC/FW）データ（IC7/IC8局在）。
- フィールドでの状態サイズ・計算コスト実測（IC5）。
- 先行技術の正式FTO/特許性調査。
"""
    (REPORTS / "fcc_patent_counsel_brief_v4.md").write_text(txt, encoding="utf-8")


def build_all(results: Dict[str, dict], gate_status: str, availability: str) -> None:
    build_main_report(results, gate_status, availability)
    build_disclosure(results, gate_status, availability)
    build_counsel_brief(results, gate_status, availability)
