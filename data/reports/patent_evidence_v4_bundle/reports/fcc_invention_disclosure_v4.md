# 発明届ドラフト（Invention Disclosure v4）— FCC学習応答検出技術

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術はAIサーベイ由来で**未検証(UNVERIFIED)**。出願前に登録弁理士のレビュー必須。地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。

## 1. 技術分野
ノートPCバッテリ管理(BMS)燃料計の満充電容量(FCC)学習に基づくSoH診断、FCC再学習無応答（ゲージ凍結）の
検出・原因切り分け・トリアージ、および有界生データ保持下での因果イベント台帳による証拠保全。

## 2. 課題
SoH=FCC×100/DesignCapacity。FCC凍結は静的検査では正常（浅充放電）・要再較正・FW/HW起因を判別不能。
フリート規模で誤保守を抑えつつ機種非依存に振り分け、欠測・睡眠ギャップ・打ち切りで誤escalationを避け、
有界保持下でも証拠を失わない必要がある。

## 3. 発明の要点（v4で実証強化）
- **IC1**: RSOC high→low→high 機会のEND-anchored応答監査。負の対照で刺激-応答の特異性を実証
  （真72h応答=0.38990426457789384、5/5対照でヌル外）。
  START/LOW比でEND汚染0 vs 0.55692（A3）。
- **IC2**: any/effective デュアルトラック非対称リセット。対称比でconfirmed no-response +115を温存、
  hard prompt 209→97（C2）。有効閾値は量子化/二峰分布に基づく（C3, valley=35.23mWh）。
- **IC5**: 有界保持+最小十分状態の因果台帳。ステートフルは recall=1/dup=0/no-response MAE≈0 を維持しつつ
  ストレージ比 0.0417（D）。必要状態=['eff_cycle', 'fsm', 'gap_censor', 'last_eff_ts', 'ordering', 'pending', 'seen_ids']。
- **IC6**: 段階的ギャップ品質+censor-aware。注入下で誤no-response naive 643.317→proposed 4.1（E）。
- **IC7（prospective）**: ラベル依存介入後の次機会でのFCC回復観測。**介入/versionデータ NOT AVAILABLE** → protocol+power simのみ。

## 4. 代替実施形態
`fcc_alternative_embodiments_v3.md`（保全）+ `patent_claim_scope_recommendations_v4.csv`。
有効閾値: narrow=50mWh / medium=量子化・ノイズ帯超 / broad=適応。応答窓24/72/168h。機会帯70/30..90/10。保持7..90d+最小状態。

## 5. 限界
proxyは地上真実でない。先行技術UNVERIFIED。介入/versionはNOT AVAILABLE（捏造せず）。規範MLは独立クレーム外。

## 6. 発明者・寄与・開示タイムライン（placeholder）
[氏名/役割/寄与]、[着想日/社内開示日/外部公開有無] — 新規性喪失の例外要確認。
