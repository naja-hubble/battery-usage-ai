# Claude Code Prompt — FCC学習応答技術の特許性強化エビデンス生成 v3

あなたは `battery-usage-ai` リポジトリで作業する、シニアデータサイエンティスト、時系列システムエンジニア、バッテリー診断エンジニアです。目的は法律判断ではなく、既存の全期間版およびrolling30-v2.0の技術的効果、新規な構成、代替実施形態、因果性、再現性を、特許明細書・発明届・弁理士レビューに耐える形で実証することです。

## 0. 最重要原則

- 既存production outputs、v1/v2 modules、testsを破壊・上書きしない。すべてadditiveに実装する。
- 既存ラベルをground truthとして学習しない。比較用proxyとしてのみ使う。
- FW不良確定、Gauge故障確定と表現しない。`candidate` / `review target` とする。
- 介入結果、FW version、実験データが存在しない場合は絶対に捏造しない。`NOT AVAILABLE` と明示し、入力schema・prospective protocol・power simulationのみ作る。
- user ID、serial、UUID、端末名を図・外部向け表・レポートに出さない。内部case tableはhash化IDを用いる。
- future leakageを禁止する。時点`t`では`t`以前に確定したraw/stateだけを使う。
- censored / unknown / LOW_LARGE_GAPをconfirmed no_responseへ混入させない。
- すべての図はPNG dpi=300。図ごとに発明系列と技術効果をcaptionへ記載する。
- 法律上の結論は出さない。`technical evidence for patent review` として出力する。

## 1. 最初に読むもの

存在するものを探索し、パスをreport冒頭に記録する。

- `PROJECT_STATUS.md`
- `data/processed/battery_timeseries_all.parquet`
- 全期間版:
  - `fcc_final_learning_episodes.*`
  - `fcc_final_user_features.*`
  - `fcc_final_action_labels.*`
  - `fcc_final_learning_action_report.md`
- rolling版:
  - `data/processed/fcc_online_v2/`
  - `fcc_online_sliding30_v2_report.md`
  - `fcc_online_v2_adversarial_review.md`
- `soh_update_status.csv`
- `user_master.csv`
- patent review bundle / figure indexがあれば読む
- intervention / BIOS / EC / battery-FW versionファイルが存在するか探索する

各入力のSHA-256、行数、user数、timestamp範囲、主要列を `input_manifest_patent_v3.csv` に保存する。

## 2. Baseline再現ゲート

新規解析の前に既存結果を再現する。

### 全期間版 expected
- users = 752
- no/low candidates = 96
- Gauge actionable = 18
- FW actionable = 14
- Watch = 55
- Review = 338
- Normal = 327

### rolling30-v2 latest expected
- REVIEW_DATA_QUALITY = 325
- NORMAL_RESPONDING = 183
- WATCH_LARGE_GAP_OR_CENSORED = 128
- FW_WATCH_HIGH_ANOMALY = 43
- WATCH_LOW_EVIDENCE = 35
- GAUGE_SOFT_CALIBRATION = 22
- GAUGE_REVIEW = 7
- FW_CHECK_CORE = 5
- GAUGE_RESET_CORE = 4

一致しない場合は処理を停止せず、`BASELINE_MISMATCH` として差分を詳細報告し、原因が解決するまで特許エビデンス結論を出さない。

## 3. 実装ファイル

新規module例:

- `battery_usage/patent_opportunity_response.py`
- `battery_usage/patent_dual_track.py`
- `battery_usage/patent_retention_invariance.py`
- `battery_usage/patent_missingness_stress.py`
- `battery_usage/patent_intervention.py`
- `battery_usage/patent_claim_support.py`
- `analyze_fcc_patent_evidence_v3.py`
- `plot_fcc_patent_evidence_v3.py`
- `tests/test_fcc_patent_evidence_v3.py`

既存の実証済みepisode/state primitivesを再利用し、ロジックを複製してdriftさせない。

## 4. Analysis A — 全期間版のblack-box刺激応答診断を実証

### 4.1 比較器ablation

同じeligible cohortに対し以下を比較する。

A0. `flat_tail_days`のみ  
A1. flat tail + cycle delta  
A2. opportunity countのみ  
A3. opportunity + responseだがcensor/gapを無視  
A4. END-anchored response + censor-aware、single FCC step definition  
A5. A4 + gap tier  
A6. 完全提案法（opportunity / response / gap / dual track / action branch）

出力指標:
- actionable count
- legacy active false action
- effective-active false action
- final-proxy precision/recall
- proxy FW→Normal/Gauge silent misroute
- proxy Gauge→FW misroute
- Watch/Review routing
- label Jaccard

`patent_ablation_comparison.csv` と300dpi図を作る。

### 4.2 Negative controls

少なくとも以下をuser内で実施し、marginal distributionを極力保持する。

1. FCC effective-step timestampsのcircular shift
2. episode end timestampsのcircular shift
3. opportunity-response pairingのpermutation
4. pseudo-episode endを同じ時刻分布からsampling
5. RSOC系列のphase shift

各controlで、END-anchored response association、confirmed no-response odds、FW routingが真データより消失するかを評価する。user単位bootstrap CIを使う。

出力:
- `patent_negative_control_results.csv`
- `stimulus_response_negative_controls.png`

### 4.3 Response anchorの比較

response windowをepisode `start`, `low`, `end` の各anchorで比較する。

評価:
- pre-opportunity FCC step contamination
- 24/72/168h response capture
- active false alerts
- proxy routing

提案法のEND anchorが因果的に妥当であることを定量化する。

## 5. Analysis B — Qualified learning opportunityの物理的妥当性

### 5.1 Opportunity definitions

利用可能列に応じ、以下を比較する。

- RSOC-only: 70/30/70, 80/20/80, 85/15/85, 90/10/90
- charge termination / full-charge flag
- discharge depth / throughput / cycle increment
- current taper、voltage、temperature、rest/relaxation（列が存在する場合のみ）
- gap coverage

存在しない変数を推測しない。

### 5.2 Healthy responder cohortでのresponse hazard

active/effective responding usersを用い、episode end後のeffective FCC step hazardを推定する。

- Kaplan-Meier / cumulative incidence相当の記述
- 24/48/72/120/168h
- pseudo-episodeとの比較
- opportunity definition別response rate

目的は「qualified stimulus後に応答が集中する」ことの実証であり、FW classification modelを作ることではない。

出力:
- `qualified_opportunity_tradeoff.csv`
- `response_hazard_true_vs_pseudo.png`
- `opportunity_qualification_evidence.md`

## 6. Analysis C — any/effective dual-trackの特許エビデンス

### 6.1 Step magnitude distribution

全FCC stepを抽出し、user別・device別・DesignCapacity正規化で以下を計算する。

- observed quantization unit
- signed / absolute step histogram
- repeated peaks
- micro-step run length
- time between micro and effective steps

### 6.2 Threshold derivation

比較:
- any integer change
- fixed 10/20/30/40/50/75/100mWh
- 0.05/0.1/0.2/0.5% DesignCapacity
- `max(k * quantization_unit, alpha * DesignCapacity)`
- mixture-model / change-point derived threshold
- per-user noise percentile threshold

50mWhを正当化できない場合は正直に報告し、より良いadaptive embodimentを提案する。

### 6.3 State-machine ablation

比較:
1. any-trackのみ
2. effective-trackのみ
3. dual-trackだが両trackをmicro-stepでreset
4. dual-track symmetric reset
5. **提案するasymmetric reset**: micro-stepはanyのみreset、effective evidence/pending/no-responseを保持

評価:
- Gauge Core/Soft数
- hard-reset false prompts
- FW evidence消失数
- active overlap
- proxy routing
- label stability

出力:
- `dual_track_threshold_analysis.csv`
- `dual_track_state_ablation.csv`
- `micro_vs_effective_mixture.png`
- `asymmetric_reset_technical_effect.png`

## 7. Analysis D — raw retention制約下のwindow invariance

### 7.1 Full-history event ledgerをreferenceにする

同じ日次inference timestampについて、全履歴を参照したreference event ledgerを作る。rolling detectorのfuture leakageを禁止する。

### 7.2 Retention grid

- window: 7, 14, 30, 45, 60, 90 days, full
- stride: 1, 7 days
- alignment offset: 0〜6 days
- stateless / stateful

### 7.3 評価

- physical episode IDのprecision/recall
- response status agreement
- cumulative counter absolute error
- latest label agreement
- first-alert lead/lag
- stateful-only recovered evidence
- bytes/user of persistent state
- raw bytes deleted / retained
- runtime and peak memory

### 7.4 Minimal sufficient state ablation

以下を1つずつ除外する。

- partial FSM state
- pending deadline
- seen episode IDs
- last effective change timestamp/cycle
- censored counter
- gap-quality summary
- any/effective separate timestamps

どの欠落がどの誤判定を生むかを示す。

### 7.5 Property tests

- same physical episode is counted exactly once
- censored never becomes no_response before deadline
- effective reset invalidates only eligible prior evidence
- overlapping windows do not change result
- output is invariant to reprocessing the same day
- stable under equal-timestamp event ordering

出力:
- `retention_invariance_grid.csv`
- `minimal_state_ablation.csv`
- `state_memory_cost.csv`
- `retention_vs_equivalence.png`
- `state_component_ablation.png`

## 8. Analysis E — Missingness / sleep-gap / censor stress test

元データの観測gap分布を推定し、以下をsynthetic injectionする。

- MCAR point dropout: 5/10/20/30/40%
- block dropout: 3/6/12/24/48h
- empirical sleep-pattern block dropout
- episode high→low区間、low→high区間、response window内で別々に注入
- window末尾censor

比較:
1. naive: 欠測を無視
2. binary OK/large-gap
3. graded HIGH_OK/MEDIUM/LOW
4. graded + censored/unknown state

評価:
- false confirmed no_response
- false no-opportunity
- false FW escalation
- false hard Gauge reset
- sensitivity loss

出力:
- `missingness_stress_results.csv`
- `gap_censor_false_action_curves.png`
- `gap_location_effect.png`

## 9. Analysis F — Intervention closed loop

### 9.1 実データ探索

次の列/ファイルを探索する。

- BIOS version
- EC version
- battery gauge FW version
- update availability/applied timestamp
- gauge reset/calibration timestamp
- intervention outcome

存在すれば厳密なschemaをreportする。存在しない場合、以下のanalysisを実行したと偽らない。

### 9.2 データがある場合

Gauge intervention:
- Gauge Core / Soft vs matched controls
- 次回HIGH_OK opportunity後72/168h effective response
- time/cycles to response

FW intervention:
- same user pre/post update
- same FRU/model matched non-updated controls
- opportunity-adjusted response rate

統計:
- mixed-effects logisticまたはGEE
- difference-in-differences
- interrupted time series
- exact/Firth or hierarchical Bayesian for small n

### 9.3 データがない場合

作成するもの:
- `intervention_data_schema.csv`
- `prospective_intervention_protocol.md`
- empirical baseline rateを使うpower simulation
- safe OEM procedure notes

安全上、危険な強制放電を指示しない。`OEM-approved controlled calibration within thermal/voltage safety limits` とする。

## 10. Analysis G — Firmware/version localization

versionデータがある場合のみ:

- individual policyにidentity/versionを入力しない
- detection後のcase-controlとして使用
- FRU/model/vendor内でversion比較
- opportunity exposure, observation time, cycle intensityをmatch/adjust
- pre/post update within-device analysis
- BH-FDRとsmall-n warning

出力:
- `firmware_version_case_control.csv`
- `firmware_update_prepost.csv`
- `version_response_recovery.png`

データがない場合は必要schemaと解析コードstubを作る。

## 11. Analysis H — 技術的効果・運用効果

比較対象:
- static FCC stale rule
- full-history proposed
- rolling stateless
- rolling stateful v2

定量化:
- hard calibration prompts avoided
- FW-like cases not routed to Gauge
- active responders protected
- delayed/pending episodes protected
- storage and compute reduction
- time-to-detection

ビジネスKPIだけでなく、誤ったbattery control/maintenance actionの削減、計測不完全性下の診断信頼性、有限storage下の同等性を主要technical effectとする。

## 12. 特許図面・説明図

すべて匿名・dpi=300で作成する。

最低限:
1. 全期間版black-box stimulus-response architecture
2. qualified opportunity state machine
3. END-anchored 4-state response lifecycle
4. no-opportunity vs opportunity-no-response branch
5. any/effective coupled state machines and asymmetric reset
6. rolling raw window + persistent state ledger
7. exact-once episode replay and event ordering
8. gap/censor safety gate
9. closed-loop calibration/FW intervention and recovery verification
10. ablation technical effects
11. retention equivalence and memory tradeoff
12. threshold/mixture evidence

各図に以下を付ける。
- `invention_family`
- `claim_elements_supported`
- `technical_problem`
- `technical_effect`

## 13. 発明届・クレームサポート成果物

生成:

- `data/reports/fcc_patent_evidence_v3_report.md`
- `data/reports/fcc_invention_disclosure_v3.md`
- `data/reports/fcc_claim_support_matrix_v3.csv`
- `data/reports/fcc_prior_art_feature_matrix_v3.csv`
- `data/reports/fcc_alternative_embodiments_v3.md`
- `data/reports/fcc_intervention_protocol_v3.md`
- `data/reports/fcc_patent_figure_captions_v3.csv`

### Invention disclosure sections

1. technical field
2. prior technical problem
3. failed approaches (usage ML AUC≈0.54; history-free normative AUC≈0.56)
4. full-history invention
5. retention-constrained invention
6. dual-track invention
7. closed-loop invention
8. alternative embodiments and parameter ranges
9. experimental evidence
10. limitations and missing data
11. inventors/contribution placeholders
12. disclosure timeline placeholders

### Claim-support matrix columns

- family
- claim_element_id
- claim_element_text
- code_module/function
- input variables
- experiment/output file
- figure
- technical effect
- alternative embodiment
- current evidence strength
- missing evidence

### Prior-art feature matrix

技術的比較のみを行い、法的結論を出さない。既知文献番号が入力に含まれる場合は、各文献の確認済みclaim/description要素と本技術要素を表形式にする。未確認内容を推測しない。

## 14. CLI

例:

```bash
python analyze_fcc_patent_evidence_v3.py \
  --timeseries data/processed/battery_timeseries_all.parquet \
  --full-history-dir data/processed \
  --rolling-v2-dir data/processed/fcc_online_v2 \
  --user-master data/processed/user_master.csv \
  --soh-update-status data/processed/soh_update_status.csv \
  --window-grid 7,14,30,45,60,90 \
  --stride-grid 1,7 \
  --response-windows 24,48,72,120,168 \
  --effective-step-grid any,10mWh,20mWh,30mWh,40mWh,50mWh,75mWh,100mWh,0.1pct,0.5pct,adaptive \
  --run-ablation \
  --run-negative-controls \
  --run-retention-invariance \
  --run-missingness-stress \
  --run-intervention-if-available \
  --out-dir data/processed/fcc_patent_evidence_v3 \
  --fig-dir data/reports/figures/fcc_patent_evidence_v3 \
  --report data/reports/fcc_patent_evidence_v3_report.md \
  --dpi 300 \
  --random-seed 42
```

## 15. Tests

最低限:

- baseline count reproduction
- no future leakage
- END anchor boundary
- censored/unknown exclusion
- LOW_LARGE_GAP exclusion
- exact-once episode across overlapping windows
- idempotent replay
- equal-timestamp ordering
- any/effective asymmetric reset
- adaptive threshold deterministic behavior
- raw retention enforcement
- full-history equivalence on synthetic trace
- missingness injection reproducibility
- PII scan of all external outputs
- no hardware identity in individual policy/model inputs
- missing intervention data produces `NOT AVAILABLE`, not fabricated results

既存testsを全て維持する。

## 16. Acceptance criteria

1. 既存full-history/rolling-v2 baselineを再現または差分を明示。
2. 各発明系列について少なくとも1つのablation technical effectを出す。
3. 真データのstimulus-response associationがnegative controlsより有意に強いか、強くなければ正直に報告。
4. dual-track asymmetric resetの増分効果を定量化。
5. retention window/stride/alignmentに対するstateful invarianceを定量化。
6. missingness/censor安全策によるfalse action削減を定量化。
7. intervention/versionデータの有無を明示し、捏造しない。
8. すべての外部向け図・表が匿名。
9. すべての図がdpi=300。
10. claim-support matrixがcode/data/figureへtraceable。
11. 既存production labelは変更しない。
12. 全tests pass。
13. reportは良い結果だけでなく、失敗・弱点・prior-art riskも明記。

## 17. 最終メッセージ

実行完了時は以下を簡潔に報告する。

- baseline再現状況
- 最も強い3つのtechnical effects
- 新規性を弱める結果
- closed-loop/version data availability
- 発明family別evidence strength
- 生成物パス
- tests
- 未解決事項

