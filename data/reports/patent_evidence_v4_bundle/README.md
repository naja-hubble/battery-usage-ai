# FCC Patent Evidence v4 Bundle (2026-06-19)

> 技術的特許性エビデンス（technical evidence for patent review）。法的結論ではない。
> 先行技術はUNVERIFIED。地上真実・介入結果・FWバージョン・因果結論は一切捏造していない。

## 構成
- `data/` : 解析成果物（CSV/parquet/JSON、内部キャッシュ `_*` は除外）
- `reports/` : v4報告書・発明届・カウンセルブリーフ・敵対的レビュー・介入schema/power-sim
- `figures/` : 全図（dpi=300・匿名、user_id/serial/UUID無し）

## 主要結論（独立エンドポイント、proxy非依存）
- IC1 機会条件付きEND無応答: STRONG（A2刺激-応答特異性 5/5・A3 END汚染0）
- IC2 デュアルトラック非対称リセット: STRONG（C2: 対称比+115証拠温存・hard減112）※production実装済を開示
- IC5 有界保持因果台帳+最小状態: STRONG（D: recall1/dup0 @ストレージ比0.042）
- IC6 ギャップ/censor品質: STRONG（E: 誤no-response naive→proposed 大幅減）
- IC7 クローズドループ: PROSPECTIVE（介入/version NOT AVAILABLE）
- IC8 機種非依存スクリーニング: MEDIUM / version局在 PROSPECTIVE

## 留保
技術エビデンス強度 ≠ 新規性リスク。先行技術は全てUNVERIFIED、出願前に正式FTO/特許性調査・弁理士レビュー必須。
法的novelty/inventive step/侵害自由/登録可能性は一切主張しない。

## ファイル一覧（66 files, SHA-256 16桁）

### data/
- `availability_probe_v4.json` (1489 B, sha256:24ca1523b9b3975c)
- `dual_track_erased_evidence_events.parquet` (33748 B, sha256:f764d6138b7cfa45)
- `dual_track_label_transitions.csv` (405 B, sha256:a56e69bfb7ff9987)
- `dual_track_reset_ablation.csv` (595 B, sha256:23339b4f776a1cc6)
- `dual_track_threshold_stability.csv` (144 B, sha256:8034545ed1323733)
- `effective_threshold_bootstrap.csv` (103 B, sha256:f3eeba8c6f54d980)
- `effective_threshold_label_sensitivity.csv` (1244 B, sha256:7c6a5dc34842c85e)
- `effective_threshold_model_selection.csv` (333 B, sha256:3eaaab835b1629cc)
- `effective_threshold_persistence_reversal.csv` (390 B, sha256:94dfd6d9c6869380)
- `effective_threshold_recommendation.json` (799 B, sha256:713dc188e0f3ec8a)
- `input_manifest_patent_v4.csv` (737 B, sha256:4f2c77efb445bb0a)
- `minimal_state_ablation.csv` (1417 B, sha256:7ff3e1d85940bee6)
- `missingness_label_transitions.csv` (768 B, sha256:47ed491ad4761ccd)
- `missingness_stress_replicates.parquet` (23666 B, sha256:a086b5a8a3c2fdd0)
- `missingness_stress_summary.csv` (5198 B, sha256:497961290c8f038d)
- `negative_control_detector_impact.csv` (371 B, sha256:f8e95deabda661d7)
- `negative_control_replicates.parquet` (143046 B, sha256:d204a8d2135b1e24)
- `negative_control_summary.csv` (4185 B, sha256:654671cef18456ce)
- `negative_control_user_bootstrap.csv` (413 B, sha256:c814ba0e8b28ebfe)
- `patent_baseline_gate_v4.csv` (774 B, sha256:52d6ccf7acbaded0)
- `patent_claim_scope_recommendations_v4.csv` (1006 B, sha256:471d4cecc63377e8)
- `patent_claim_support_matrix_v4.csv` (6676 B, sha256:21a878a156b18e24)
- `patent_evidence_strength_v4.csv` (2908 B, sha256:33f2e3afada93138)
- `patent_prior_art_feature_matrix_v4.csv` (1418 B, sha256:fc737a0c2948483f)
- `patent_results_manifest_v4.csv` (4596 B, sha256:2458f644786691db)
- `patent_technical_effects_v4.csv` (2080 B, sha256:a8da2fe60fedea32)
- `reference_event_ledger.parquet` (680525 B, sha256:4e909dc9800b90ce)
- `response_anchor_charge_termination_status.csv` (128 B, sha256:23f5e99201137d2e)
- `response_anchor_comparison.csv` (673 B, sha256:6afc7399041493ed)
- `response_anchor_contamination_bootstrap.csv` (245 B, sha256:50d590a2ee669f65)
- `response_anchor_delay_cdf_data.csv` (87413 B, sha256:67427e8e8edfc11b)
- `response_anchor_episode_assignments.parquet` (45085 B, sha256:b68f0baa609e58f4)
- `response_anchor_label_transition.csv` (135 B, sha256:ec6975915639b13f)
- `response_hazard_curves.parquet` (81073 B, sha256:9bf432d56994c6c5)
- `response_hazard_summary.csv` (1323 B, sha256:feccdbb756f39352)
- `retention_invariance_grid.parquet` (25257 B, sha256:51eab662e822370b)
- `retention_invariance_summary.csv` (6561 B, sha256:e05fce9b17fbf78c)
- `retention_stateful_verification.csv` (208 B, sha256:7a802e9298729705)
- `storage_compute_tradeoff.csv` (307 B, sha256:3af5d80c4110a166)

### reports/
- `fcc_intervention_data_schema_v4.csv` (754 B, sha256:6cf2e940a5c93317)
- `fcc_intervention_power_simulation_v4.csv` (2047 B, sha256:58f3c8c28b405f09)
- `fcc_invention_disclosure_v4.md` (2789 B, sha256:faa75819c575fb1a)
- `fcc_patent_counsel_brief_v4.md` (4229 B, sha256:7f6cc64a37a00eff)
- `fcc_patent_evidence_v4_report.md` (13429 B, sha256:03386f88ef86bac7)
- `fcc_patent_summary_slides_v4.md` (12325 B, sha256:2522a4a194f315f6)
- `fcc_patent_summary_slides_v4.pptx` (882919 B, sha256:d1ff0749bf0b5710)
- `fcc_patent_v4_adversarial_review.md` (39602 B, sha256:6953a7c3e79e4e34)

### figures/
- `censor_injection_safety.png` (98804 B, sha256:a0bf21e87c9358e4)
- `dual_track_erased_evidence.png` (164517 B, sha256:df7245173b7ed434)
- `dual_track_reset_semantics.png` (164724 B, sha256:1036a67b5a218336)
- `effective_threshold_mixture_fit.png` (107814 B, sha256:4398244436f68ec3)
- `effective_threshold_technical_effect_curve.png` (115467 B, sha256:58de29369f3a00a8)
- `evidence_strength_table.png` (49749 B, sha256:ed280f5f5aec701a)
- `minimal_state_necessity.png` (100569 B, sha256:edb58ff8f9da2a08)
- `missingness_false_escalation.png` (158836 B, sha256:19dea7783c6e5355)
- `missingness_quality_tier_benefit.png` (100759 B, sha256:f33682c33d6fc4cd)
- `negative_control_randomization_distribution.png` (99899 B, sha256:155aa7fbee9761b4)
- `negative_control_true_vs_null.png` (166731 B, sha256:12565dab86f79439)
- `response_anchor_contamination.png` (70589 B, sha256:973215425a151bd3)
- `response_anchor_delay_cdf.png` (128318 B, sha256:e08c027e8b1d9481)
- `response_hazard_by_quality.png` (144264 B, sha256:3bb0b76b4e16065a)
- `response_hazard_by_threshold.png` (246727 B, sha256:e3d40c319b24875b)
- `response_hazard_true_vs_pseudo.png` (127111 B, sha256:da27aecd229e3b0b)
- `retention_invariance_heatmap.png` (79339 B, sha256:ad7d60e97cc75a77)
- `storage_vs_equivalence.png` (106336 B, sha256:444fd18a46962ac0)
- `technical_effect_waterfall.png` (116098 B, sha256:9dcf9aecf36cd27b)
