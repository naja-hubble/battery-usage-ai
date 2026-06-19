# 発明届ドラフト（Invention Disclosure v3）— FCC学習応答検出技術

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。先行技術の特許番号はAIサーベイ由来で未検証。出願前に登録弁理士のレビュー必須。

## 1. 技術分野
ノートPCバッテリ管理システム(BMS)の燃料計が学習する満充電容量(FCC)に基づくSoH診断、および
FCC再学習無応答（ゲージ凍結）の検出・原因切り分け・介入トリアージ。

## 2. 従来の技術的課題
SoH=FCC×100/DesignCapacity。SoHはFCCのステップ更新時のみ動く。FCC凍結は静的検査では正常（浅充放電）・
要再較正・FW/HW起因を判別不能。フリート規模で誤った保守アクションを抑えつつ機種非依存で振り分ける必要がある。

## 3. 失敗した先行アプローチ（本プロジェクトで実証）
- 使用挙動から very_stale を教師あり予測 → 公平領域 AUC≈0.54（ランダム同然）。
- FCC履歴を除いた規範モデルでの異常予測 → AUC≈0.56（near-random）。
→ 「予測」では解けない。**機会条件付き無応答の機械的監査**へ転換。

## 4. 全期間版の発明
RSOCの high→low→high 機会を抽出し、END-anchored 応答窓(72h)内のFCC有効ステップ(>=50mWh)を
responded/no_response/censored/unknown に分類。censored/unknown/LOW_LARGE_GAP を無応答に算入しない。
機会反復×無応答→FW候補、機会皆無→ゲージ再較正候補に二分岐。

## 5. 保持制約下の発明（rolling30）
直近30日raw可視の制約下で、解決済みイベントをepisode_idで時刻順リプレイする永続状態により
窓外エピソード証拠を回収（exact-once、complete<reset<deadline順序）。

## 6. デュアルトラックの発明
any-change(>=quantization=10mWh) と effective(>=50mWh) を分離追跡し、microのみはsoft-calibrationへ。
非対称リセット（microはany のみreset、effective証拠/pending/no-responseを保持）。

## 7. クローズドループの発明（prospective）
ラベル依存の具体的介入（ゲージ→OEM承認較正プロンプト／FW→エスカレーション）後、次のHIGH_OK機会での
FCC回復を観測してラベルを検証。**介入データは現状 NOT AVAILABLE**（schema/protocol/power sim を提示）。

## 8. 代替実施形態・パラメータ範囲
`fcc_alternative_embodiments_v3.md` 参照。

## 9. 実験的エビデンス（本v3で生成）
- ベースライン再現ゲート: **PASS**（16/16 一致）。
- Analysis A ablation: 静的(A0) 精度 0.3273（55件）→ ギャップ品質付与(A5) **0.8889**（9件）。
  二分岐+デュアルトラック(A6=production)で FW 14+Gauge 18 を全捕捉(recall 1.0)。
- Analysis C dual-track: n_steps=43230、quantization=10mWh、micro(<50mWh)=0.581。
- Analysis H: 静的stale 55件(二分岐不可) vs 全期間提案 32件(production-NORMAL 0件)、stateful-v2 core 9件(NORMAL 0件)。

## 10. 限界・欠測データ
- BIOS/EC/battery-FW version・介入結果は NOT AVAILABLE（捏造せず schema/protocol/power sim のみ）。
- 規範モデルAUC≈0.56（MLは独立クレームから除外、決定論カウンタで構成）。
- proxyラベルは production 出力であり真の地上真実ではない。
- 重い raw 再処理解析（negative controls / 完全 retention grid / missingness injection / response hazard）は PENDING（未捏造）。

## 11. 発明者・寄与（placeholder）
- [氏名] / [役割] / [寄与: 着想・実装・検証]

## 12. 開示タイムライン（placeholder）
- 着想日 [____]、社内開示日 [____]、外部公開 [無/有: ____]（新規性喪失の例外要確認）。
