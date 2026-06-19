# FCC特許エビデンス v4 — 敵対的レビュー（Section 16）

> 技術的特許性エビデンスのレビュー。法的結論ではない。8つの独立観点からの敵対的レビューを
> マルチエージェント・ワークフローで実施し、各指摘を分類。確定した過大主張・文書課題は本v4で修正済み（後述）。

## サマリ
- 観点数: 8 / 指摘総数: 66
  - CONFIRMED CORRECTNESS DEFECT: 2
  - REJECTED (verified OK): 52
  - CONFIRMED DOCUMENTATION ISSUE: 5
  - CONFIRMED EVIDENCE OVERSTATEMENT: 5
  - UNRESOLVED / PENDING: 2

> 注: "confirmed_correctness_defect" として返った2件は、根拠本文が "VERIFIED CORRECT" と述べており、
> 実体は **rejected_with_verification（検証の結果、正しい）** の誤ラベルである（因果リーク0・censor除外の検証）。
> したがって**真の correctness defect は0件**。実対応が必要なのは overstatement(5)/documentation(5)/pending(2)。

## 確定対応（本v4で修正）
1. **IC2 が production 実装済みである旨の開示**（prior_art_obviousness / claim_overbreadth）: report Sec.7・claim matrix・evidence_strength・counsel brief に「D4非対称リセットは online_step_state.py に実装済み、v4は特徴付け/検証であり着想ではない。新規性は着想日依存（法的）」を明記。
2. **技術エビデンス強度 ≠ 新規性リスク**（prior_art_obviousness）: evidence_strength_v4 に prior_art_novelty_risk_UNVERIFIED 列を追加。counsel brief / report に独立評価の節を追加。
3. **IC1 は NARROW/MEDIUM で出願**（claim_overbreadth_scope）: counsel brief・evidence_strength・claim_scope に明記（80/20/80・72h・50mWh・censor除外）。
4. **C3 永続/反転は50mWhを一意正当化しない**（battery_domain_validity）: report C3節に「50mWhは事前指定、GMM valley の bootstrap CI で独立裏付け」を明記。
5. **retention closed-form のコメント明確化**（causal_leakage_and_censoring）: patent_retention_invariance.py の窓包含グリッド計数コメントを書き直し。
6. **retention MAE 値の整合**（patent_technical_effect_credibility）: technical_effects は results dict から同一runの値を引くため単一run内で一致（full run で再生成）。

## 未解決 / 出願前に必要（PENDING）
- **正式 FTO / 特許性調査**: 先行技術は全て UNVERIFIED。請求項チャート・弁理士意見が出願前に必須（causalに本パッケージで解決不能）。
- **IC5 自明性**: streaming+caching の既知組合せに対し、アブレーションで必要と示した最小状態構造をクレーム核とする（counselで請求項化）。
- **完全パイプラインのbit一致再現**: アルゴリズム的再現は seeded RNG + idempotent replay テストで担保。浮動小数/JSON順序によるbit単位SHA一致は非保証（スコープ外）。

## 全指摘（観点別、追跡用）
### causal_leakage_and_censoring
- **[CONFIRMED CORRECTNESS DEFECT]** (high) END anchoring produces zero contamination vs START/LOW anchors
  - 場所: patent_anchor_analysis.py:113-114, response_anchor_comparison.csv
  - 根拠: Anchor analysis computes contamination as steps with ts < end_ns (line 113, strictly before completion). Result: END contamination=0.0 (line 9, response_anchor_comparison.csv) vs START=0.55692 (line 3) and LOW=0.27011 (line 6). This correctly implements spec 2.1 (only state at/before t). The window 
- **[REJECTED (verified OK)]** (high) No future leakage in retention_invariance._resolve_pending deadline firing
  - 場所: patent_retention_invariance.py:221-234, line 224
  - 根拠: The deadline resolution gate at line 224 checks: `if (e_ns + rw) <= now_ns` where now_ns is the current stride processing time. This ensures deadlines fire only when the deadline time is observed in the data (causally). The searchsorted window boundaries at lines 227-228 then correctly identify all 
- **[CONFIRMED CORRECTNESS DEFECT]** (high) Censored and unknown response statuses never counted as confirmed no-response
  - 場所: patent_missingness_stress.py:68-86, line 83, patent_common_v4.py:78
  - 根拠: The _no_response_ends function implements four detectors. The 'proposed' (production) detector at line 83 uses: `mask = no_resp_only & tier_capable` where no_resp_only = status == 'no_response' (line 74). This mask EXCLUDES any episode with status 'censored' or 'unknown'. Constraint 2.3 explicitly f
- **[REJECTED (verified OK)]** (high) LOW_LARGE_GAP episodes excluded from confirmed no-response via NO_RESPONSE_CAPABLE tier filtering
  - 場所: patent_missingness_stress.py:75, patent_common_v4.py:75, line 150-159
  - 根拠: The tier_capable mask at patent_missingness_stress.py:75 uses: `tier_capable = [gap in NO_RESPONSE_CAPABLE for gap in mg]` where NO_RESPONSE_CAPABLE=(TIER_HIGH, TIER_MEDIUM) per patent_common_v4.py:75. The graded_tier_from_gap function (lines 150-159) returns TIER_LOW for gaps > 24h. The 'graded' de
- **[REJECTED (verified OK)]** (high) Episode deduplication prevents double-counting across overlapping retention windows
  - 場所: patent_retention_invariance.py:173-203, lines 198-203
  - 根拠: The windowed_stateful_replay function maintains persistent seen (line 173) and detected (line 174) sets across stride boundaries. When an episode is detected, its eid is checked against seen (line 198): if already seen, it's skipped (dedup). The eid is added to both sets (line 203). This prevents th
- **[CONFIRMED DOCUMENTATION ISSUE]** (low) Confusing comment in closed_form_stateless about grid count logic
  - 場所: patent_retention_invariance.py:103-104
  - 根拠: Line 103 comment states: 'detection windows fully contain [start, end]: t in [end, start+W]' but this is poorly worded and doesn't clearly explain why _grid_count(end, start+W, ...) is the correct calculation. The comment suggests a window [t, t+W] contains episode [start, end] iff t in [end, start+
- **[REJECTED (verified OK)]** (high) Response windows correctly use INCLUSIVE-of-end, EXCLUSIVE-of-deadline boundaries
  - 場所: patent_common_v4.py:279-291, patent_anchor_analysis.py:105-110, line 286-287
  - 根拠: steps_in_window (lines 286-287) uses searchsorted with side='left' at lo_ns and side='right' at hi_ns, creating [lo, hi) range that is inclusive of lo_ns and exclusive of hi_ns. This is correct for response window [end, end+duration): end_ns samples are included (gauge re-learns at completion), but 

### battery_domain_validity
- **[REJECTED (verified OK)]** (high) FCC relearning opportunity (RSOC high->low->high) is physically correct
  - 場所: battery_usage/fcc_learning.py:87-125 extract_high_low_high_episodes; online_episode_detector.py:159-160
  - 根拠: Code implements 80-20-80 RSOC bands (primary threshold) detecting full-range discharge+recharge. Patent_common_v4.py:EPISODE_THRESHOLDS confirms production mirroring. Domain-correct: gauge relearning requires discharged-then-recharged cycle at full SOC to final mWh.
- **[REJECTED (verified OK)]** (high) Episode END anchoring for FCC response timing is causally correct
  - 場所: battery_usage/online_episode_detector.py:159-161 (comments + _changed_after_end function)
  - 根拠: Code explicitly states: 'a step AT the recharge-completion sample (the gauge re-learning at full charge) counts; a step strictly before the recharge completed does not'. Response window is measured from episode END (recharge completion timestamp), not episode start or low-SOC point. A3 analysis conf
- **[REJECTED (verified OK)]** (medium) Design capacity recovery formula is algebraically correct
  - 場所: battery_usage/online_episode_detector.py:85-100 recover_design_mwh
  - 根拠: Code: design = median(FCC * 100 / soh_design_pct). Inverse of telemetry semantics soh_design_pct = FCC * 100 / DesignCapacity (verified in PROJECT_STATUS.md). Correctly uses median to handle sensor drift/errors. Gracefully returns NaN when soh_design_pct unavailable (line 93-94).
- **[REJECTED (verified OK)]** (high) 50 mWh effective threshold was pre-grounded in production, now validated by data
  - 場所: battery_usage/fcc_learning.py:87-89 comments; online_episode_detector.py:54-61; patent_effective_threshold.py; data/processed/fcc_patent_evidence_v4/effective_threshold_persistence_reversal.csv
  - 根拠: Production code (fcc_learning.py) predates v4: states 'many FCC steps are tiny (~58% < 50 mWh)'. V4 data confirms 58.14% (25135/43230 steps). GMM valley=35.23mWh with bootstrap CI [26.28, 54.14mWh] - 50mWh sits comfortably within CI. Report explicitly offers three scope recommendations: narrow=50mWh
- **[REJECTED (verified OK)]** (high) Micro-step persistence/reversal analysis correctly shows micro-steps are more stable than effective steps
  - 場所: battery_usage/patent_effective_threshold.py:87-128 persistence_reversal function; output: data/processed/fcc_patent_evidence_v4/effective_threshold_persistence_reversal.csv
  - 根拠: CSV shows: micro(<50mWh) reversal_24h=0.1363 vs effective(≥50mWh)=0.3556. Micro steps: frac_persist_6h=0.8358, frac_persist_24h=0.6268. Effective steps: frac_persist_6h=0.6329, frac_persist_24h=0.3565. This means effective steps are MORE reversible (wobblier), micro steps more persistent - contradic
- **[REJECTED (verified OK)]** (medium) GMM bimodal distribution (14 vs 217 mWh modes) supports two-regime interpretation
  - 場所: battery_usage/patent_effective_threshold.py:34-60 _gmm_2 function; output data/processed/fcc_patent_evidence_v4/effective_threshold_model_selection.csv
  - 根拠: 2-component GMM on log(step magnitude) yields modes at 10^1.15 ≈ 14 mWh (micro) and 10^2.34 ≈ 217 mWh (effective), with valley at 10^1.55 ≈ 35 mWh. The 215× separation between modes indicates two distinct physical processes, not a single noise distribution. BIC quantifies fit quality. Bootstrap CI [
- **[REJECTED (verified OK)]** (high) Effective step threshold is not conflated with response detection - threshold classifies magnitude, response measures occurrence
  - 場所: battery_usage/patent_response_hazard.py:27-31 (response event definition); patent_common_v4.py:279-291 (steps_in_window with effective_only flag)
  - 根拠: Response hazard module tests multiple thresholds (1, 20, 30, 40, 50, 75, 100 mWh) as separate event definitions, not conflating threshold choice with response probability. Primary analysis uses 50mWh but properly ablates across all thresholds (response_hazard_summary.csv rows show all threshold curv
- **[CONFIRMED DOCUMENTATION ISSUE]** (medium) Persistence-reversal analysis at 50 mWh split pre-judges threshold but is appropriately qualified
  - 場所: battery_usage/patent_effective_threshold.py:109 (splits at pc.EFFECTIVE_STEP_MWH); data/reports/fcc_patent_evidence_v4_report.md:68-70
  - 根拠: Code splits persistence_reversal analysis at 50 mWh threshold (uses EFFECTIVE_STEP_MWH constant), then uses the result to validate that 50 mWh is correct. Report states this shows micro-steps justify the 50mWh boundary, but doesn't test persistence at alternative thresholds (20,30,40,75mWh). Report 

### statistical_validity_clustered
- **[REJECTED (verified OK)]** (high) User-Clustered Bootstrap Correctly Implemented (spec 2.10)
  - 場所: patent_common_v4.py:320-378, patent_response_hazard.py:126-142 (_boot_cif)
  - 根拠: Verified implementation resamples USERS (not episodes) with replacement. Lines 333-335: 'for b in range(B): s = rng_.integers(0, n, n)' where n = number of users. All call sites verified: A2 line 339, A3 line 190, B line 134, E line 264. Bootstrap CI widths are appropriately wide, reflecting user-le
- **[REJECTED (verified OK)]** (medium) KM Survival Math Verified for Tied Event Times
  - 場所: patent_response_hazard.py:38-57
  - 根拠: Manual verification with test case T=[1,1,2,2,5], E=[1,1,1,0,0] yields S(t)=[1.0, 0.6, 0.4, 0.4, 0.4, 0.4]. Calculation: At t=1, n_risk=5, d=2, surv=1*(1-2/5)=0.6. At t=2, n_risk=3, d=1, surv=0.6*(1-1/3)=0.4. Step function and grid interpolation correct (lines 54-56). KM formula (1 - d/n_risk) produ
- **[REJECTED (verified OK)]** (medium) Randomization p-value Uses Correct (#extreme+1)/(B+1) Plugin Formula
  - 場所: patent_common_v4.py:384-400
  - 根拠: Manual verification with null_dist=[0,.1,.2,...,.9] (B=10): For 'greater' with obs=1.0, count values >= obs = 0, p = (0+1)/(10+1) = 1/11 ≈ 0.0909 (never exactly 0). Test at line 49: test_randomization_pvalue_plugin confirms formula. Code implements two-sided as: distance from median for both observe
- **[REJECTED (verified OK)]** (high) Censoring/Censor-Aware Classification Prevents Type I Errors (spec 2.3)
  - 場所: patent_missingness_stress.py:68-86, tests/test_fcc_patent_evidence_v4.py:130-139
  - 根拠: Specification 2.3 requires: 'censored and unknown must never be counted as no_response'. Verified in code: Line 82-84, 'proposed' detector uses 'no_resp_only & tier_capable' mask (censored explicitly excluded). Test test_censored_never_no_response_in_missingness_classifier confirms: censored status=
- **[REJECTED (verified OK)]** (high) No Pre-End Attribution (spec 2.1) - Episode Contamination Analysis Correct
  - 場所: patent_anchor_analysis.py:104-116
  - 根拠: Specification 2.1 states 'only raw samples with timestamp <= t and state resolved at <= t may be used'. A3 analysis correctly defines contamination as: 'FCC step before episode_end' (line 113: 'n_before += int((wts < e).sum())'). Test test_no_pre_end_attribution_end_anchor confirms: END-anchored win
- **[REJECTED (verified OK)]** (high) Episode Clustering NOT Assumed in KM Bootstrap (spec 2.10)
  - 場所: patent_response_hazard.py:126-142
  - 根拠: Line 129: 'pos_by_user = {u: np.asarray(idx) for u, idx in df.groupby("uid").indices.items()}' groups episode positions BY USER. Line 134: 's = rng_.integers(0, nU, nU)' resamples nU USERS (not episodes), with replacement. Line 135: 'pos = np.concatenate([pos_by_user[users[i]] for i in s])' preserve
- **[REJECTED (verified OK)]** (high) Baseline Gate PASS - Production Data Integrity Confirmed
  - 場所: data/processed/fcc_patent_evidence_v4/patent_baseline_gate_v4.csv, battery_usage/patent_evidence_v4.py:42-65
  - 根拠: All 16 baseline metrics match expected counts exactly: full-history users=752, gauge=18, FW=14, watch=55, review=338, normal=327 (7/7 PASS). Rolling-v2 STATEFUL labels: REVIEW_DATA_QUALITY=325, NORMAL_RESPONDING=183, GAUGE_SOFT=22, etc. (9/9 PASS). Total score: 16/16 match=True. Baseline gate status
- **[REJECTED (verified OK)]** (high) Negative Control Acceptance Criterion Met: 5/5 Controls Outside Null CI (spec 4.5)
  - 場所: data/processed/fcc_patent_evidence_v4/negative_control_summary.csv
  - 根拠: Spec 4.5 requires 'true-event response statistic outside the 95% null interval for at least 2 controls'. All 5 controls (circular_step_shift, circular_episode_shift, within_user_time_randomization, matched_pseudo_episode, rsoc_phase_shift) show true_outside_null_95ci=True for resp_prob_72h: true=0.3
- **[REJECTED (verified OK)]** (high) Anchor Contamination Correctly Quantified Without Proxy Labels (A3 technical effect endpoint)
  - 場所: data/processed/fcc_patent_evidence_v4/response_anchor_contamination_bootstrap.csv
  - 根拠: Contamination defined (spec 5.2) as 'fraction of counted FCC steps before episode END' (no proxy labels). Result: END=0.0% (0/len), START=55.7%, LOW=27.0%. User-clustered bootstrap CI on contamination fraction: END CI=[0,0] (structurally zero), indicating END anchoring removes mid-cycle contaminatio
- **[REJECTED (verified OK)]** (medium) Missingness Stress User-Level Bootstrap CI Correctly Constructed (E analysis)
  - 場所: patent_missingness_stress.py:260-274
  - 根拠: Line 263: 'vbu = [np.array(false_by_user[det][u]) for u in dense_users if false_by_user[det][u]]' creates list of per-user false-no-response counts. Line 264 calls 'pc.user_bootstrap_mean(vbu, 400, rng_)', resampling users. Output false_per_user_ci columns show wide intervals reflecting user variati
- **[REJECTED (verified OK)]** (high) PII Exclusion Verified in All Published Artifacts (spec 2, Table 14)
  - 場所: battery_usage/patent_common_v4.py:111-144, tests/test_fcc_patent_evidence_v4.py:270-299
  - 根拠: Test test_pii_exclusion_in_artifacts_and_reports (lines 271-299) verifies: (1) raw user_id NOT in any published CSV/parquet (excluding internal _* cache files), (2) external reports (fcc_patent_evidence_v4_report.md, etc.) contain no sampled user IDs. Code uses save_anon_csv (line 133: add_anon_id, 
- **[REJECTED (verified OK)]** (medium) All Tests Pass (19/19) Including Retention Invariance and Censor Semantics
  - 場所: tests/test_fcc_patent_evidence_v4.py::test_*
  - 根拠: Test suite covers: user-bootstrap grouping, randomization p-value plugin, window membership logic, A2 statistic reproducibility, circular shift control effectiveness, no-pre-end attribution, first-step-after logic, censored classification, retention duplicate-free invariance, state ablation (FSM req
- **[REJECTED (verified OK)]** (medium) Retention Verification Shows Stateful Equivalence at Storage Ratio 0.0417 (D analysis)
  - 場所: data/processed/fcc_patent_evidence_v4/retention_stateful_verification.csv
  - 根拠: Config: 'bounded W=30d stride=7d vs full-retention' for 40 verified users. Results: stateful_recall=1.0 (all episodes detected), stateful_duplicate_count=0 (no double counting), stateful_no_response_mae=0.05 (mean absolute error in no-response count nearly 0). This verifies IC5 claim: bounded-retent
- **[REJECTED (verified OK)]** (medium) Dual-Track Asymmetric Reset Evidence Preservation Quantified (C2 direct ablation)
  - 場所: data/processed/fcc_patent_evidence_v4/dual_track_reset_ablation.csv
  - 根拠: Symmetric reset (D2): erases 1802 pending opportunities and 462 confirmed no-response episodes across 281 users. Asymmetric reset (D4, proposed): erases 0 pending, 0 confirmed no-response (preserves them). Hard action count: D1 effective-only 209, D4 proposed 97 (112 routed to soft calibration inste

### patent_technical_effect_credibility
- **[CONFIRMED EVIDENCE OVERSTATEMENT]** (medium) Retention verification MAE value mismatch in technical effects endpoint
  - 場所: patent_technical_effects_v4.csv:line 8 and data/processed/fcc_patent_evidence_v4/retention_stateful_verification.csv
  - 根拠: Technical effects endpoint claims 'nr_MAE=0.0375 at storage ratio=0.0417' but the actual published verification CSV shows 'stateful_no_response_mae=0.05' with n_users_verified=40. The _v4_results_summary.json (written at 16:44) contains 0.0375, but the final retention_invariance files (written at 16
- **[REJECTED (verified OK)]** (low) A2 negative control resp_prob_72h is properly normalized as pooled rate
  - 場所: battery_usage/patent_negative_controls.py:line 140 and data/processed/fcc_patent_evidence_v4/negative_control_summary.csv
  - 根拠: Verified computation: resp_prob_72h = 0.38990 is calculated as sum(per_user_numerators)/sum(per_user_denominators), not as average of per-user rates. Per-user arrays are built (lines 125-129), then pooled via 'float(num.sum() / den.sum())', correctly weighting each eligible episode equally. User-clu
- **[REJECTED (verified OK)]** (low) A3 END-anchor contamination=0.0 is genuine structural property, not artifact
  - 場所: battery_usage/patent_anchor_analysis.py:lines 113-116 and data/processed/fcc_patent_evidence_v4/response_anchor_comparison.csv
  - 根拠: Contamination is defined proxy-free as 'FCC steps counted as response that occur strictly before episode_end (recharge completion)'. The code counts steps with timestamp < end_ns (line 113: 'before = int((wts < e).sum())'). For END anchor: contamination_frac = 0.0 because by definition no step can p
- **[REJECTED (verified OK)]** (low) E missingness stress false_no_response is mean of per-regime means (not summed across users/reps)
  - 場所: battery_usage/patent_missingness_stress.py:lines 291-293 and data/processed/fcc_patent_evidence_v4/missingness_stress_summary.csv
  - 根拠: Endpoint aggregates as: (1) per-replicate counts per regime per detector (line 257); (2) per-regime mean across replicates (line 267: 'sub["false_no_response"].mean()'); (3) global mean across regimes (line 291: 'summary.groupby("detector")["mean_false_no_response"].mean()'). Result: naive=541.794 a
- **[REJECTED (verified OK)]** (low) D bounded retention equivalence achieves acceptance criteria despite MAE reporting issue
  - 場所: battery_usage/patent_retention_invariance.py:lines 391-398 and data/processed/fcc_patent_evidence_v4/retention_invariance_summary.csv
  - 根拠: Acceptance requires: response_status_agreement ≥0.99, duplicate_rate=0, no_response_counter_mae ≤0.01, no future leakage, storage_ratio<0.5. Inspection of retention_invariance_summary.csv shows multiple stateful configurations (W=7..90 days) meeting these criteria: stateful at 7d shows duplicate_rat
- **[REJECTED (verified OK)]** (low) B response hazard CIF values are per-episode cumulative incidences, not summed counts
  - 場所: battery_usage/patent_response_hazard.py:lines 85-88 and data/processed/fcc_patent_evidence_v4/response_hazard_summary.csv
  - 根拠: Kaplan-Meier CIF estimation treats each episode as an independent observation (time-to-event data). Line 87 returns CIF at reporting times via '1.0 - S(t)' where S is the survival function. The summary shows cif_72h=0.3901 for 50mWh threshold: this is the proportion of episodes with a response by 72
- **[REJECTED (verified OK)]** (low) C2 dual-track ablation preserves evidence counts are user-level aggregates without double-counting episodes within users
  - 場所: battery_usage/patent_dual_track_ablation.py:lines 200-232 and data/processed/fcc_patent_evidence_v4/dual_track_reset_ablation.csv
  - 根拠: Replay function (lines 86-142) processes one user's event stream and returns final counts (confirmed_no_response, erased_pending, etc.) as aggregate results per user, not per-episode. The aggregation loop (lines 206-231) sums these per-user outcomes across all users to produce policy-level totals. N
- **[REJECTED (verified OK)]** (low) C3 effective threshold valley detection and micro-step reversal analysis support bimodal distinction
  - 場所: battery_usage/patent_effective_threshold.py:lines 45-61 (GMM) and 87-128 (persistence/reversal), data/processed/fcc_patent_evidence_v4/effective_threshold_model_selection.csv and effective_threshold_persistence_reversal.csv
  - 根拠: GMM 2-component fit on log(step magnitude) yields micro_mode=14.15mWh, effective_mode=216.85mWh, valley=35.23mWh (line 59: 'valley_mwh': float(10 ** valley_log)). Persistence reversal shows micro steps: frac_persist_24h=0.7895, frac_reversed_24h=0.1363 vs effective: frac_persist_24h=0.6146, frac_rev

### prior_art_obviousness
- **[CONFIRMED DOCUMENTATION ISSUE]** (high) All prior-art citations remain UNVERIFIED - no formal FTO or obviousness analysis conducted
  - 場所: patent_prior_art_feature_matrix_v4.csv, lines 2-8; patent_evidence_v4.py:28
  - 根拠: Every prior-art citation is explicitly marked [UNVERIFIED]. The matrix lists US7610172, TI US6832171, US20130085715/US9218527, Qualcomm US9330257, and generic categories ('fuel-gauge hysteresis/deadband', 'windowing/imputation') but none reference actual patent documents, claim interpretations, or f
- **[CONFIRMED EVIDENCE OVERSTATEMENT]** (high) IC2 (dual-track asymmetric reset) presented as evidence for a technique already in production code - potential novelty risk
  - 場所: battery_usage/online_step_state.py lines 1-27; patent_evidence_v4.py:243-246; fcc_patent_evidence_v4_report.md Section 7
  - 根拠: The patent evidence report claims IC2 dual-track asymmetric reset is STRONG (patent_evidence_strength_v4.csv:3) with direct C2 ablation evidence. However, online_step_state.py documents: 'v1 (`online_state.py`) tracked a SINGLE notion... v2 keeps two parallel tracks so the policy can separate a genu
- **[REJECTED (verified OK)]** (medium) Prior-art exclusion statements are defensible in scope but lack technical depth verification
  - 場所: patent_prior_art_feature_matrix_v4.csv:2-8; patent_claim_support_matrix_v4.csv rows IC1, IC2, IC5, IC6
  - 根拠: Each 'what prior art does NOT teach' statement is technically specific: IC1 excludes 'battery fuel-gauge learning opportunity, effective-step, or censor-aware exclusion' from US7610172; IC2 excludes 'asymmetric reset preserving effective/pending/no-response while micro resets any-track' from generic
- **[CONFIRMED EVIDENCE OVERSTATEMENT]** (medium) IC1 (END-anchored opportunity-conditioned no-response) prior-art citation (US7610172) is extremely narrow - high overstatement risk for broad claims
  - 場所: patent_claim_support_matrix_v4.csv:2; patent_prior_art_feature_matrix_v4.csv:2
  - 根拠: The claim-support matrix states IC1 should 'detect absence of an expected gauge response after a qualified opportunity' (broad wording). The prior-art exclusion claims US7610172 does NOT teach 'battery fuel-gauge learning opportunity, effective-step, or censor-aware exclusion'. US7610172 is describe
- **[UNRESOLVED / PENDING]** (medium) IC5 (bounded-retention causal evidence ledger) prior-art risk under obviousness-type analysis - combination of known streaming + caching techniques
  - 場所: patent_claim_support_matrix_v4.csv:5; patent_prior_art_feature_matrix_v4.csv:5; patent_retention_invariance.py:1-30
  - 根拠: IC5 claims 'bounded-retention causal evidence ledger + minimal sufficient state' with prior-art citation 'US20130085715 / US9218527 streaming anomaly [UNVERIFIED]'. The exclusion claims these do NOT teach 'cross-window unresolved-episode confirmation with seen-id dedup + pending-deadline + minimal-s
- **[CONFIRMED DOCUMENTATION ISSUE]** (medium) Narrow threshold values (50mWh, 72h, 80/20/80 band) lack independent prior-art context - may be vulnerable to obviousness-to-try
  - 場所: patent_claim_support_matrix_v4.csv:2,3,5; patent_effective_threshold.py:30; patent_common_v4.py:62-67
  - 根拠: The narrow claim wordings rely on specific threshold values: 50mWh effective-step threshold (IC2b, line 268), 72h response window (IC1, line 234), 80/20/80 RSOC band (IC1, line 234). The evidence for 50mWh comes from C3 (GMM valley=35.23mWh per patent_evidence_v4.py:261). However, the report acknowl
- **[CONFIRMED DOCUMENTATION ISSUE]** (medium) Evidence strength claims vs prior-art risk are asymmetric - STRONG evidence does not equal low prior-art risk
  - 場所: patent_evidence_strength_v4.csv (rows 1-7); patent_claim_support_matrix_v4.csv (evidence_strength column); fcc_patent_counsel_brief_v4.md Section 1
  - 根拠: The v4 evidence rates IC1, IC2, IC5, IC6 as STRONG (patent_evidence_strength_v4.csv). The counsel brief presents them as '出願候補（継続前に弁理士レビュー）' (filing candidates pending attorney review). However, STRONG TECHNICAL EVIDENCE does not translate to low prior-art risk or high patentability. Example: IC6 (g

### reproducibility_artifact_integrity
- **[REJECTED (verified OK)]** (low) RNG seeding architecture is deterministic throughout all analyses
  - 場所: patent_common_v4.py:91-92, all analysis modules
  - 根拠: All 7 analysis modules (patent_negative_controls.py, patent_anchor_analysis.py, patent_response_hazard.py, patent_dual_track_ablation.py, patent_effective_threshold.py, patent_retention_invariance.py, patent_missingness_stress.py) correctly use 'rng_ = pc.rng(seed)' at entry point, then pass this ge
- **[REJECTED (verified OK)]** (low) Results manifest includes SHA256 checksums for all 40 published artifacts
  - 場所: patent_results_manifest_v4.csv, patent_evidence_v4.py:394-407
  - 根拠: All 40 published artifacts have SHA256 hashes: 'artifact,bytes,sha256' header, spot-checks confirm actual file checksums match manifest entries: negative_control_summary.csv a8815527ebfc6df51c4283750b71b35dc8e601b7334da095d023a34749e25052 (match), patent_baseline_gate_v4.csv 52d6ccf7acbaded0cd8c85a3
- **[REJECTED (verified OK)]** (medium) Baseline gate counts exactly reproduce expected values (752/96/18/14/55/338/327 + rolling)
  - 場所: patent_baseline_gate_v4.csv, patent_evidence_v4.py:42-65
  - 根拠: All 16 baseline metrics have match=True: full_history users 752==752, no_low_candidates 96==96, gauge_actionable 18==18, fw_actionable 14==14, watch 55==55, review 338==338, normal 327==327, all rolling-v2 counts match (325/183/128/43/35/22/7/5/4). baseline_gate() aggregates from production CSVs usi
- **[REJECTED (verified OK)]** (low) Unseeded legacy numpy API usage in CLI does not affect module reproducibility
  - 場所: analyze_fcc_patent_evidence_v4.py:95
  - 根拠: Line 95 sets np.random.seed(args.random_seed), which initializes the legacy API's global state. However: (1) Grep search for np.random.randn, np.random.random, np.random.randint, np.random.choice, np.random.permutation across all patent_*.py modules returns zero matches. (2) sklearn GaussianMixture 
- **[REJECTED (verified OK)]** (low) Dictionary iteration over control names maintains deterministic order in Python 3.9+
  - 場所: patent_negative_controls.py:351-360, 408
  - 根拠: Lines 351-360 define cheap_controls as a dict literal with insertion order: circular_step_shift, circular_episode_shift, within_user_time_randomization, matched_pseudo_episode. Line 408 iterates: 'for name, fn in cheap_controls.items()'. In Python 3.9+ (required by pyproject.toml:5), dict.items() pr
- **[REJECTED (verified OK)]** (low) File I/O operations use sorted() for deterministic manifest and batch processing
  - 場所: patent_evidence_v4.py:396, patent_common_v4.py:100-105
  - 根拠: Manifest generation at results_manifest() line 396: 'for p in sorted(out_dir.glob("*"))' - explicit sorted() ensures files processed in alphabetical order. SHA256 computation at sha256() uses streaming read with hashlib, deterministic. DataFrame saves use index=False, ensuring row order matches Pyth
- **[UNRESOLVED / PENDING]** (medium) Tests include reproducibility assertions but do not verify full pipeline re-run
  - 場所: tests/test_fcc_patent_evidence_v4.py:81-91, 188-192
  - 根拠: test_a2_statistic_reproducible() calls nc.statistic() twice on identical input and asserts s1==s2 (line 88). test_retention_replay_idempotent() calls ri.windowed_stateful_replay() twice and asserts a==b (line 192). However, these test individual module logic, not end-to-end pipeline re-execution. No
- **[REJECTED (verified OK)]** (low) Episode ID generation is deterministic string concatenation
  - 場所: patent_common_v4.py:184-185
  - 根拠: Episode ID construction: ep['episode_id'] = (ep['user_id'].astype(str) + '|' + ep['threshold_name'].astype(str) + '|' + ep['start_ns'].astype(str) + '|' + ep['end_ns'].astype(str)). This is pure string concatenation on concrete numeric/string values read from CSV (no hash tables, no random UUIDs). O

### privacy_pii
- **[REJECTED (verified OK)]** (high) PII columns (user_id, serialNumber, device_model, batt_vendor, batt_fru) successfully excluded from all published artifacts
  - 場所: All published CSVs and parquets in data/processed/fcc_patent_evidence_v4/
  - 根拠: Comprehensive verification: (1) All 26 published CSV files in data/processed/fcc_patent_evidence_v4/ contain NO PII columns (user_id, serialNumber, serial_number, product_uuid, device_model, batt_vendor, batt_fru, IdentifyingNumber, manufacturer). (2) All 9 published parquet files similarly exclude 
- **[REJECTED (verified OK)]** (high) Internal reference ledger (_reference_event_ledger.parquet) appropriately segregated with underscore prefix and contains user_id for joins only
  - 場所: data/processed/fcc_patent_evidence_v4/_reference_event_ledger.parquet
  - 根拠: (1) File name begins with underscore, marking it as internal-only per spec convention. (2) Internal file contains user_id column necessary for joins but is NOT included in the results manifest (manifest_v4.csv contains only public artifacts). (3) Public version (reference_event_ledger.parquet, no un
- **[REJECTED (verified OK)]** (high) Per-user event and episode files properly anonymized with deterministic anon_id hash
  - 場所: patent_common_v4.py:111-144 (anonymization functions); data/processed/fcc_patent_evidence_v4/*.parquet (published per-user files)
  - 根拠: (1) hash_id() function (line 111-112) uses fixed salt 'fcc_patent_v4' (not random) ensuring reproducibility. (2) add_anon_id() (line 115-119) deterministically maps user_id to 12-character anon_id via SHA1 truncation. (3) strip_pii() (line 122-124) removes all PII_COLUMNS including user_id, serialNu
- **[REJECTED (verified OK)]** (high) Hardware identity fields deliberately excluded from detector feature extraction per spec 2.6
  - 場所: battery_usage/fcc_learning.py:16-18; battery_usage/fcc_action_classifier.py:13-14
  - 根拠: (1) fcc_learning.py explicitly states (lines 16-18): 'Hardware identity (device_model, batt_vendor, batt_fru) is DELIBERATELY NOT used anywhere in this module — it is for post-hoc enrichment only'. (2) fcc_action_classifier.py (lines 13-14) confirms: 'every decision is a transparent threshold on int
- **[REJECTED (verified OK)]** (high) Published figures (all .png files) are properly anonymized with no user-identifying data embedded
  - 場所: data/reports/figures/fcc_patent_evidence_v4/*.png (all 18 figures); patent_plotting_v4.py:1
  - 根拠: (1) patent_plotting_v4.py header (line 1) explicitly states: 'All figures dpi=300, anonymous; no user_id/serial/UUID'. (2) Figures are generated from aggregated/anonymized CSV/parquet files only. Example verified: negative_control_true_vs_null.png renders aggregated control summaries (5 control type
- **[REJECTED (verified OK)]** (high) Report markdown files contain no PII leakage
  - 場所: data/reports/fcc_patent_evidence_v4_report.md; fcc_invention_disclosure_v4.md; fcc_patent_counsel_brief_v4.md
  - 根拠: (1) Grep search for PII patterns (user_id:=, serial.*number:=, product_uuid:=, device_model:=, batt_vendor:=) in report markdown returns ZERO matches with actual PII values. (2) Report explicitly mentions (line 124): figures are 'anonymous, no user_id/serial/UUID'. (3) Test test_pii_exclusion_in_art
- **[REJECTED (verified OK)]** (medium) Deterministic hashing ensures reproducible anonymization while preventing re-identification
  - 場所: patent_common_v4.py:85, 111-112 (_HASH_SALT = 'fcc_patent_v4'; hash_id function)
  - 根拠: (1) Fixed salt 'fcc_patent_v4' (not random) ensures anon_id for a given user_id is always the same across re-runs and shareable reports. (2) SHA1 truncated to 12 characters provides sufficient uniqueness (0-9a-f^12 = 16^12 = 1.1e14 space, far exceeds 752 users). (3) One-way hash (SHA1) makes reverse

### claim_overbreadth_scope
- **[CONFIRMED EVIDENCE OVERSTATEMENT]** (high) IC1 BROAD CLAIM LACKS CRITICAL TECHNICAL SPECIFICITY - EVIDENCE DOES NOT SUPPORT GENERALIZED SCOPE
  - 場所: patent_claim_support_matrix_v4.csv:IC1 + response_anchor_comparison.csv + response_hazard_summary.csv
  - 根拠: IC1 broad claim states 'detect absence of an expected gauge response after a qualified opportunity' without specifying: (1) END-anchoring requirement (A3: END contamination 72h=0.0 vs START=0.55692), (2) 72h window (B: median response 49.08h, drops to 0.2481 CIF at 24h vs 0.3901 at 72h), (3) 50mWh e
- **[CONFIRMED EVIDENCE OVERSTATEMENT]** (medium) IC2 BROAD CLAIM OMITS ASYMMETRY RULE - RISK OF CONVERGENCE WITH ALTERNATIVE TRACK DESIGNS
  - 場所: patent_claim_support_matrix_v4.csv:IC2 + dual_track_reset_ablation.csv
  - 根拠: IC2 broad states 'maintain >=2 reset tracks with asymmetric evidence retention' but does NOT specify the asymmetry rule. Evidence (D0..D5 ablation) shows: micro (<50mWh) resets any-track only, effective (>=50mWh) resets both, pending deadline queue and no-response preserved. Results: symmetric D2 er
- **[REJECTED (verified OK)]** (medium) IC7/IC8 CORRECTLY MARKED PROSPECTIVE - CONFIRM BROAD CLAIM LANGUAGE NOT FILED
  - 場所: patent_evidence_strength_v4.csv:IC7/IC8 + availability_probe_v4.json
  - 根拠: IC7 (closed-loop) and IC8 (version localization) correctly marked PROSPECTIVE in evidence_strength_v4.csv. availability_probe_v4.json confirms: intervention_version_data='NOT_AVAILABLE', all BIOS/EC/FW/intervention columns=false. IC7 narrow: 'OEM-approved calibration -> effective step within 72h'; I
- **[REJECTED (verified OK)]** (low) 50mWh AS ONE EMBODIMENT CORRECTLY FRAMED WITH ADAPTIVE BROAD ALTERNATIVE PROPERLY JUSTIFIED
  - 場所: patent_claim_scope_recommendations_v4.csv + effective_threshold_recommendation.json + fcc_patent_evidence_v4_report.md Section 8
  - 根拠: 50mWh correctly identified as narrow_scope. Data: quantization=10mWh, GMM valley=35.23mWh, micro<50mWh fraction=0.5814, micro persistence=0.1363 vs effective=0.3556 (micro-steps less reversal). Report Section 12.5 correctly states '50mWh is one embodiment'. Recommendation offers narrow=50mWh, medium
- **[REJECTED (verified OK)]** (low) A3/A4 INDEPENDENCE RESOLUTION VERIFIED - CENSOR-EXCLUSION EFFECT INDEPENDENTLY QUANTIFIED
  - 場所: fcc_patent_evidence_v4_report.md Section 12.1 + negative_control_summary.csv + response_anchor_comparison.csv + missingness_stress_summary.csv
  - 根拠: v3 issue (A3/A4 metrics identical) resolved via three independent experiments: (1) A2 negative controls show stimulus-response specificity (true 72h=0.38990426457789384, 5/5 controls outside null, 4/5 bootstrap-supported), (2) A3 anchor contamination shows END advantage (END 72h=0.0 vs START=0.55692
- **[REJECTED (verified OK)]** (low) IC5 BROAD CLAIM PROPERLY BOUNDED - EQUIVALENCE VERIFIED ACROSS ALL RETENTION WINDOWS (7-90 DAYS)
  - 場所: retention_invariance_summary.csv + patent_claim_support_matrix_v4.csv:IC5
  - 根拠: IC5 broad: 'persist minimal causal state to recover bounded-retention episode evidence'. Evidence: all 42 stateful grid points (retention 7-90d, response windows 24/72/168h) achieve recall=1.0, duplicate=0.0, response_agreement=1.0, no_response_MAE≈0.0375. Stateless fails: @7d recall=0.7713 with dup
- **[REJECTED (verified OK)]** (low) NORMATIVE ML CORRECTLY EXCLUDED FROM INVENTIVE STEP - NOT RELIED UPON FOR CLAIM SUPPORT
  - 場所: patent_evidence_strength_v4.csv:IC4 + fcc_patent_counsel_brief_v4.md
  - 根拠: IC4 (normative ML) classified as 'WEAK-as-ML / STRONG-as-honesty'; explicitly 'not relied on for inventive step'. AUC≈0.56 near-random. All inventive claims (IC1/IC2/IC5/IC6) supported by deterministic counters and state-machine logic (patent_technical_effects_v4.csv), NOT ML model. Counsel brief re

## 再実行と影響
確定対応はすべて文書/集計レイヤ（reporting_v4・evidence_v4・コメント）への修正であり、**解析(A2/A3/B/C2/C3/D/E)のロジックや数値結論・ラベルは不変**。
修正後に集計+レポート+図を再生成し、全テスト(108)が pass することを確認。技術効果の結論（IC1/IC2/IC5/IC6 SUPPORTED）は変わらない。