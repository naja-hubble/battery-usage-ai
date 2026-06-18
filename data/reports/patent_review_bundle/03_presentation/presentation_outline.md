# 発表スライド構成＋スピーカーノート（台本）
## 特許出願レビュー — バッテリ燃料計 SoH凍結／FCC無応答検出

対応PPTX: `patent_review_slides.pptx`（同フォルダ）。各スライドの図は `../04_figures/` 由来（`FIGURE_INDEX.md` に対応表）。
想定時間: 20〜25分（質疑別）。**結論先出し**で進める。

---

### S1. タイトル
- バッテリ燃料計 SoH凍結／FCC無応答の検出・原因切り分けアルゴリズム — 特許性評価レビュー
- 整理番号(仮) BUA-FCC-FREEZE-2026 / 2026-06-18
- **ひとこと**: 「FCCが動かない事実」ではなく「動くべき機会で動かない機構的無応答」を検出し、ゲージ較正要 vs FW調査要に振り分ける発明。

### S2. 課題 ─ SoH凍結は静的に見えない（図: soh_overlay_by_class）
- SoH = FCC×100/DesignCapacity。DesignCapacity一定 → **SoHはFCCのステップ更新時のみ動く**。
- 凍結＝FCCが長期更新されない。だが健全機でも浅充放電なら更新されない（正常）。較正停止機・FW/HW起因機も同じ外形。
- **論点**: 一時点のFCC/SoHでは「正常／要再較正／要FW調査」の三者を判別不能。フリート752台からどう振り分けるか。

### S3. 凍結は使用挙動から予測できない（図: very_stale_xgb_shap）
- 教師あり（決定木/XGB）で very_stale を予測 → 公平領域 **AUC≈0.54（ランダム同然）**。
- 最重要 `min_rsoc` はSHAPで「深放電ほど凍結」という**反usage方向** → 行動では説明不能＝HW/FW起因を示唆。
- **これが発明の動機**: 「予測」を諦め、「機会条件付き無応答の監査」へ転換した。

### S4. 発明の核アイデア（図: opportunity_vs_response）
- **機会(opportunity)**: RSOC系列の high→low→high 遠足（深放電→再充電、主帯 80→20→80）を状態機械で抽出。
- **応答(response)**: 機会END +72h窓内でFCCが有効ステップ(≥50mWh)したか。
- **核**: 「機会あり×応答なし」を機会条件付き無応答として検出。右打ち切り(censored)・欠損(unknown)・ロガー休眠は無応答に算入しない。

### S5. パイプライン（図: final_funnel_counts）
- 全観測 → 平坦尾部抽出 → 機会検出 → 応答判定 → 品質ゲート → 二分岐。各段の絞り込み数を提示。

### S6. 二分岐：gauge-reset vs firmware-suspected（図: final_label_counts）
- 機会反復するのに無応答 → **firmware-suspected**（FW/HW調査へエスカレーション）。
- 機会が皆無 → **gauge-recalibration**（ユーザに深放電を促せば直る）。
- 機種名・ベンダ名は**判定に一切使わない**（モデル非依存）。

### S7. FW証拠：無応答機会 × サイクル（図: tail_unresponded_opportunities_vs_cycles_final）
- FW疑い群は active より多くサイクルし深放電するのにFCC無応答 — 「使えば直る」前提が崩れている群。

### S8. 閾値正当化① 有効ステップ ≥50mWh（図: effective_fcc_step_sensitivity）
- 1mWh(any-change)では量子化ノイズ(micro-wobble)を拾う → 50mWhを「有効再学習」と定義。感度カーブで妥当性。

### S9. 閾値正当化② 応答窓72h（図: response_delay_cdf_24_72_168）
- 観測されたFCC応答遅延CDF: 72hで約95%(0.9513)をカバー → 窓=72hの根拠。24/72/168hを併記。

### S10. 閾値正当化③ no-response 計数しきい k（図: no_response_probability_by_k）
- 健全応答確率下で連続k回無応答の確率（k=2で0.013）→ 閾値の統計的根拠。

### S11. ロバスト性：閾値感度（図: response_window_sensitivity_counts）
- 応答窓 24/72/168h 摂動でFW/GAUGE集合の **Jaccard=1.0** → 閾値が恣意的でないことの実証（進歩性補強）。

### S12. 右打ち切り／ギャップ品質ゲート（図: large_gap_opportunity_audit）
- ロガー休眠(large-gap)・観測打ち切りを「無応答証拠」から構造的に除外 → **active→actionable 誤分類 0件**。
- 「large-gapがある＝機会なし」と誤って結論しない安全策（gauge側への誤流入防止）。

### S13. 解釈可能な判定ルール（図: surrogate_decision_tree）
- 代理決定木で二分岐ロジックを可視化（ブラックボックスでない＝適格性・説明性に有利）。

### S14. IC5 状態永続化：窓外証拠の回収（図: stateful_vs_stateless_counts）
- オンライン制約=直近30日生データのみ可視。stateless比較器は窓先頭で「開始highが窓前」の機会を取りこぼす。
- 永続状態で跨窓エピソードを回収 → **stateful-only gain = 29**。

### S15. IC5 実例：窓外回収（図: stateful_only_evidence_examples）
- 30日窓をまたぐエピソードを `episode_id` キーで時刻順リプレイ、`complete<reset<deadline` 順序意味論で確定、物理エピソード一度限り計数。
- **本願で最も堅い要素**（審査官も「設計事項で潰しにくい」と評価）。

### S16. IC2 デュアルトラック（図: any_vs_effective_state）
- any-change(≥1mWh) と effective(≥50mWh) の二系統を並列追跡。micro-wobbleのみ=軟较正(soft-calibration)に分離 → 誤検出抑制。

### S17. IC4 規範 vs 個別モデル（図: personalized_vs_normative_roc_pr）
- 個別モデル AUC≈0.82 だが**自分の無応答を「劣化ゲージなら当然」と学習してしまうリーク**。
- 規範モデル（FCC履歴を全除外）AUC≈0.56 = near-random。**正直な開示**: 異常スコアは実質「無応答カウンタ」。
- **戦略的含意**: 中核クレームは**決定論カウンタ**で構成。ML/異常スコアは独立から外す（適格性確保）。

### S18. v2 結果：トリアージ階層（図: v2_label_counts ＋ v2_policy_matrix_heatmap）
- 9段単一ラベルラダー。FW Core 5 / FW Watch 43 / engineering queue top50 / Gauge Core 4 / Gauge Soft 22 / Review 325 …。
- 高信頼の確定アクション = FW 5 + Gauge 4 = **9台**に厳格化。

### S19. v2 精度：proxy照合（図: v2_final_proxy_cross_tab_heatmap ＋ fw_topn_yield_curve）
- バッチ確定版(fcc_final)をproxy真値に: FW Core precision 1.0、top50 recall 1.0、Gauge Core precision 1.0。

### S20. 誤警報ゼロ（図: active_false_alert_dual_basis）
- any-change基準では誤警報率0.71に見えるが、**effective基準では0** — 差はmicro-wobbleの定義差で誤判定ではない。

### S21. HW富化（記述的・分類後）（図: hardware_enrichment_fw_core）
- 分類確定**後**にのみ、FRU/機種の偏在を経験ベイズ(Beta事前・Fisher・BH-FDR)で記述的に集計。**判定には逆流させない**。

### S22. 実例パネル（図: example_fw_core / example_gauge_core）
- FW core 例（機会反復×無応答）と Gauge core 例（機会皆無）の時系列。視覚的な「動かぬ証拠」。
- ※ファイル名にPII。社外配布前に匿名化。

### S23. 特許性マトリクス（テキスト表）
- IC1 中（最有望）/ IC5 中（最も堅い）/ IC6・IC4 低〜中 / IC2・IC3・IC8 低 / **IC7 最低（純数学で出願不可）**。
- 主軸は IC1+IC5。他は防御的公開／営業秘密へ。

### S24. 推奨クレーム要旨（テキスト）
- 独立2件: Claim 1（方法=IC1＋具体的二分岐物理介入＋クローズドループ）、Claim 2（システム=IC5状態永続化＋イベント順序意味論）。
- 従属: 閾値詳細／ギャップゲート／デュアルトラック／規範モデルを「基準線検証」に機能再定義／アラート・クールダウン／経験ベイズ富化。
- **Poisson-binomial（IC7）は独立から全面削除**。

### S25. リスク・未解決（テキスト）
- 規範AUC≈0.56（ML空洞化）→決定論フレーミングで回避。proxyラベル依存。**BIOS/FWバージョン・介入結果データ欠如（最大ギャップ）**。クレーム抽象性。
- 適格性の共通急所: 保守アクションが結果志向 → ラベル依存の具体的物理介入＋クローズドループで構造化。

### S26. 出願戦略・次アクション（テキスト）＋ Disclaimer
- JP先願 → PCT → US/EP。補強最優先 = **介入→FCC回復のクローズドループ実証**。
- 出願前必須: 主要先行特許の独立クレーム精読／既存公開有無の確認（新規性喪失の時限）。
- **Disclaimer**: 技術的評価であり法的助言ではない。出願前に弁理士レビュー必須。先行特許番号は未検証。
