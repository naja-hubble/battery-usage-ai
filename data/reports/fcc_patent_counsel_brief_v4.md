# 特許カウンセル向けブリーフ v4（出願準備のための率直な順位付け）

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術はAIサーベイ由来で**未検証(UNVERIFIED)**。出願前に登録弁理士のレビュー必須。地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。

## エグゼクティブサマリ
ベースライン再現ゲート **PASS**。介入/version **NOT AVAILABLE**。
本v4はv3 PENDING（A2/A3/B/D/E）を完了し、C2非対称リセットを直接アブレーション、C3で有効閾値をデータ駆動化。
**いずれも proxy ラベルに依存しない独立エンドポイントで技術効果を確認**（`patent_technical_effects_v4.csv`）。
法的novelty/inventive step/侵害自由/登録可能性は主張しない。

## クレームfamilyの率直な順位（出願準備度）
| family | strength v4 | 出願準備度 | 根拠 |
|---|---|---|---|
| IC1 機会条件付きEND無応答 | STRONG | 出願候補（継続前に弁理士レビュー） | A2刺激-応答特異性 + A3 END汚染0 |
| IC6 ギャップ/censor品質 | STRONG | 出願候補 | E注入で誤no-response naive 643.317→4.1 |
| IC2 デュアルトラック非対称リセット | STRONG | 出願候補 | C2: 対称比+115温存, hard減 112 |
| IC5 有界保持因果台帳+最小状態 | STRONG | 出願候補（v3 MEDIUMから昇格） | D等価性(recall1/dup0) @ストレージ比 0.0417 |
| IC8 機種非依存スクリーニング | MEDIUM-SCREENING / PROSPECTIVE-LOCALIZATION | スクリーニングは出願候補/version局在は継続 | version NOT AVAILABLE |
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
