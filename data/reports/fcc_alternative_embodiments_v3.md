# 代替実施形態とパラメータ範囲（v3）

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術の特許番号はAIサーベイ由来で未検証。出願前に登録弁理士のレビュー必須。

## 機会定義（opportunity）
- RSOC帯: 70/30/70, 80/20/80（主）, 85/15/85, 90/10/90（strict）。複数帯併用で頑健化。
- 代替トリガ: charge-termination / full-charge flag、discharge depth/throughput、cycle increment、gap coverage。
- per-sample の current taper / voltage / temperature / rest は本データに NOT AVAILABLE（列が存在する実装では追加可能）。

## 応答判定（response）
- アンカー: episode end（主）。代替: start / low（因果汚染リスクをAnalysis Cで定量化予定）。
- 応答窓: 24/48/72(主)/120/168h。
- 有効ステップ閾値: any整数, 固定10/20/30/40/50(主)/75/100mWh, DesignCapacityの0.05/0.1/0.2/0.5%,
  適応 `max(k*quantization_unit, alpha*DesignCapacity)`, mixture/change-point導出, per-user noise percentile。
  実測: quantization=10mWh、micro(<50mWh)=58.1%、frozen率は~50mWh超で頭打ち。

## デュアルトラック状態機械（dual-track）
- any-track（>=1quant=10mWh）と effective-track（>=50mWh）。
- リセット規則の代替: (1)any only (2)effective only (3)both reset on micro (4)symmetric (5)**非対称（提案: microはany のみreset、effective/pending/no-responseを保持）**。

## 保持制約下の窓（retention）
- window 7/14/30(主)/45/60/90/full、stride 1/7、alignment offset 0..6、stateless/stateful。
- 永続状態の最小十分集合: partial FSM, pending deadline, seen episode ids, last effective change ts/cycle, censored counter, gap-quality summary, any/effective separate timestamps。

## 欠測安全策（gap/censor）
- naive / binary OK-large_gap / graded HIGH_OK-MEDIUM-LOW / graded+censored-unknown。

## 介入クローズドループ（NOT AVAILABLE → prospective）
- OEM承認の熱・電圧安全範囲内較正のみ。危険な強制放電は指示しない。schema/protocol/power simは生成済。
