<!-- AI-generated technical patentability assessment (engineering view, NOT legal advice). Generated 2026-06-18 via multi-agent workflow (battery-usage-ai SoH-freeze / FCC non-response detector). Prior-art patent numbers (US7610172, US12061240, US6832171, US9330257, etc.) are AI-surfaced and MUST be independently verified by a registered patent attorney before any reliance. -->

I'll produce the final patentability report in Japanese, reconciling the draft and examiner critique. This is a self-contained drafting task — I have everything I need in the provided materials. Let me synthesize the balanced report.

# 特許性評価最終報告書
## バッテリ燃料計（フューエルゲージ）SoH凍結／FCC無応答検出アルゴリズム

**整理番号（仮）**: BUA-FCC-FREEZE-2026
**作成日**: 2026-06-18
**位置付け**: 出願人ドラフトと審査官側反論ストレステストを統合した最終版。社内の出願判断用。
**対象読者**: Lenovo バッテリ解析エンジニアリングチーム（出願可否の意思決定者）

---

## 1. エグゼクティブサマリ（結論先出し）

**総合判定: 「条件付きで出願に値する」。ただし出願範囲は当初ドラフトの8発明的要素（IC1〜IC8）から大幅に絞り込むべきである。** 特許性の核は2要素に集約される ── **IC1（機会条件付きFCC無応答検出＋右打ち切り除外＋二分岐原因切り分け）** と **IC5（状態永続化による30日窓外証拠回収＋同時刻イベント順序意味論）** であり、この2要素は単一先行文献での完全一致がなく、審査官側ストレステストでも「中（許可可能性あり）」と評価され生き残った。一方、**IC7（Poisson-binomial異常）は純粋な数学的方法として適格性で確実に拒絶される見込みで出願に値しない**。IC2/IC3/IC8は周知技術（デッドバンド処理・モデル非依存行動分類・監視系アラートデバウンス）として進歩性「低」、IC4/IC6は機能再定義すれば従属クレームとして延命可能な「低〜中」である。推奨スコープは「**中核IC1+IC5を独立クレーム化し、決定論カウンタ・フレーミングで構成（規範AUC=0.56のML空洞化リスクを回避）、独立クレームの保守アクションをラベル依存の具体的物理介入＋クローズドループに構造化して適格性を確保**」する版である。ただし出願実行の前提として、**(a) US12061240・US7610172の独立クレーム本文精読、(b) 介入→FCC回復のクローズドループ実証データ取得、(c) 既存の社内/外部公開有無による新規性喪失リスクの確認** が必須であり、これらが未了の現状は「時期尚早」と評価する。

---

## 2. 発明の技術的課題と解決（背景）

### 2-1. 技術的課題
ノートPCのバッテリ管理システム（BMS）における満充電容量 `fullChargeCapacity`（FCC, mWh整数）は、SoH（State of Health）= FCC × 100 / DesignCapacity を駆動する基礎量である。DesignCapacityは機ごとに一定のため、**SoHはFCCがステップ更新したときにのみ動く**。

問題は「**SoH凍結（freeze）**」、すなわちFCCが長期更新されない現象が、静的検査では正常と区別できないことである。
- 健全機でも浅い充放電しかなければFCCは更新されない（正常 ── 較正機会が無いだけ）。
- フューエルゲージの再較正サイクルがリセット／停止した機、あるいはFW/HW起因でFCC学習が止まった機でも、同じく「FCCが動かない」外形を呈する。

FCC値・SoH値を一瞬見ても、正常・要再較正・要FW/HW調査の三者は判別不能である。フリート（752ユーザ、3.13M行、24,711 episode）の中から、**「ユーザに深放電を促せば直る（gauge-reset）」機と「ファーム/ハード調査へエスカレーション（FW-check）」機をどう振り分けるか**を、誤検出を抑えつつ機種名・ベンダ名に依存せず自動化することが課題である。

### 2-2. 解決手段の要旨
本発明は、FCC値の静的閾値ではなく「**学習機会が発生したか**」と「**その機会後の応答窓内でFCCが有効ステップしたか**」という二つの動的条件の直積で凍結を診断する。
1. **機会検出**: RSOC系列から high→low→high の遠足（深放電→再充電）を状態機械で抽出し、再較正の「機会」と定義（主帯 80→20→80）。
2. **応答判定**: 機会END時刻から +72h 応答窓内でFCCが有効ステップ（>=50mWh）したかを `responded / no_response / censored / unknown` に分類。右打ち切り（censored）・欠損（unknown）は決して無応答に算入しない。
3. **機会条件付き無応答の二分岐**: 「機会が反復するのにFCC無応答」→FW疑い、「機会自体が皆無」→再較正要（gauge）。
4. **状態永続化による窓外回収**: 直近30日生データ可視の制約下で、`episode_id`キーの永続状態に無応答証拠を累積し窓外証拠を回収。

技術的効果（実証済み）: censored/large-gap除外による誤検出抑制（active→actionable誤分類 0件）、応答窓 24/72/168h 摂動でFW/GAUGE集合のJaccard=1.0（閾値ロバスト）、stateful-only gain=29。

---

## 3. 発明的要素の一覧と特許性評価マトリクス

> 審査官ストレステストのランキングを反映。総合は新規性・進歩性・適格性を統合した許可可能性。

| IC | 新規性 | 進歩性 | 適格性 | 総合 | 一言根拠 |
|---|---|---|---|---|---|
| **IC1** 機会条件付きFCC無応答＋右打ち切り除外＋二分岐 | 中 | 中 | 中 | **中（最有望）** | 特定結合の単一引例なし。要素は公知だがUS7610172の組合せ動機が重荷。(f)を具体介入＋クローズドループ化すれば防御可。 |
| **IC5** 状態永続化窓外回収＋同時刻イベント意味論 | 中 | 中 | 中 | **中（最も堅い）** | windowingは公知だが跨窓未解決エピソード確定＋complete<reset<deadline順序意味論は設計事項論を退けやすい。引例特定に審査官が失敗すれば生存。 |
| **IC6** ギャップ品質ゲート | 低〜中 | 低 | 低 | **低〜中** | large-gap排除の機構は防御余地あり。だが重み0.45/0.35/0.20・breakpointは臨界性立証困難でルーチン最適化認定。 |
| **IC4** 規範/個別ツイン・リーク回避 | 低〜中 | 低 | 弱 | **低〜中** | 規範比較・リーク回避は公知（Song 2007／一般常識）。AUC=0.5584で効果実体が乏しい。機能再定義で延命のみ。 |
| **IC2** デュアルトラック | 低 | 低 | 中 | **低** | デッドバンド/ヒステリシス処理の常識。1mWh/50mWhはルーチン最適化。 |
| **IC3** モデル非依存分類＋EB富化 | 低 | 低 | 弱 | **低** | 識別子排除は別ドメインで公知（出願人自認）。EBは古典統計。富化は分類後descriptiveで機能無寄与。 |
| **IC8** トリアージラダー＋アラート制御 | 低 | 低 | 中 | **低** | 優先順位分類・デバウンス・クールダウンは監視系の常識。ただし適格性補強材として有用。 |
| **IC7** Poisson-binomial異常 | 低 | 低 | **最弱** | **最低（出願不可）** | 純粋な数学的方法。§101/EPC52(2)/29条柱書で直撃。進歩性も初等確率。**正直に言えば本要素単独は特許不可。** |

**読み方**: 出願の主軸は IC1 と IC5 のみ。IC4/IC6 は中核独立クレームを補強する従属に格下げ。IC2/IC3/IC7/IC8 は特許化を諦め、防御的公開または営業秘密に振り分けるのが honest な判断である。

---

## 4. 中核発明（最有望）の詳細

### 4-1. IC1 ── 機会条件付きFCC無応答検出（最有望・主軸）

**新規性 vs 最近接先行技術**
最近接は US5606242（Smart battery FCC学習＋失敗フラグ）、TI Impedance Track（US6832171, 適格放電でFCC/Qmax学習）、US6691049（較正ずれ検出）、US20170003351（Dialog, 再較正条件検出）。これらは個別に「機会＝適格放電」「relearn失敗の課題」を開示する。**しかし「機会の反復に条件付けた無応答（opportunity recurs but FCC step absent）を上位テレメトリ層から統計的に検出し、`censored`（右打ち切り）を無応答から構造的に除外する」という特定結合を開示する単一文献は、サーベイ範囲で発見されていない。** 審査官も「単一文献の完全一致はなく、新規性単独では拒絶を確定できない」と認めた点である。

**技術的効果**
- active→actionable誤分類 0件（censored/large-gap除外による偽陽性抑制）。
- 応答窓 24/72/168h 摂動でFW/GAUGE集合のJaccard=1.0（閾値ロバスト性 ── arbitraryでないことの実証）。
- 静的閾値では原理的に不可能な「凍結の原因切り分け（gauge-reset対FW-check）」。

**なぜ非自明か（審査官の生存判定を取り込む）**
審査官の最強の拒絶論は「US7610172（非発生事象監視）が汎用フレームを与え、TI＋US6691049で動機付けされ、右打ち切りは生存時間解析の常識だから組合せは自明、しかも相乗効果は規範AUC=0.56で空洞」というものである。**この攻撃に対する生存条件は、審査官自身が第7節で明示した。** すなわち、**(f)の保守アクションをラベル依存の具体的二分岐物理介入（gauge→深放電プロンプト表示／FW→エスカレーションレコード生成）に構造化し、さらに介入→FCC回復観測のクローズドループを装置動作として織り込めば、「健全ゲージは機会があれば応答する」という物理的因果に基づく分岐が単なる非発生検知の応用を超え、容易想到性を否定する余地が生じる**。これにより相乗効果論を「ML予測性能」ではなく「決定論的な因果駆動トリアージ＋介入検証ループ」に移し替えられ、AUC=0.56攻撃が無効化される。

### 4-2. IC5 ── 状態永続化による窓外証拠回収（最も堅い）

**新規性 vs 最近接先行技術**
最近接は US20130085715/US9218527（streaming異常検知, スライディングウィンドウ＋確率密度）。スライディングウィンドウ＋ステートフル処理自体は公知（出願人自認）。**しかし「生データ可視範囲を直近30日に限定しつつ、`episode_id`キーの永続派生状態に解決済みイベントのみを時刻順リプレイし、30日窓境界をまたぐエピソード証拠を回収する」という、可視窓を超えた証拠回復のための状態永続化を開示する先行は発見されていない。**

**技術的効果**
- stateless比較器が窓先頭リセットで「開始highが窓前のエピソード」を取りこぼす特定の境界盲点を回収（stateful-only gain=29）。
- 30日生保持というメモリ/プライバシ制約を満たしつつ長期証拠を活用。

**なぜ非自明か（審査官が「拒絶しにくい」と正直に認めた点）**
審査官は「汎用windowing（Flink等のkeyed state＋late-event handling）の単純適用と言い切るには具体性がある」と認め、**「complete<reset<deadline の同時刻イベント優先順位の意味論的設計」と「seen_idsによる物理エピソード一度限り計数」を『設計事項』で潰すには、当該順序意味論を開示する具体的引例を審査官側が要し、引例特定に失敗すればこの要素は生き残る」**とした。ここを汎用late-event処理から差別化する鍵は「単なる遅延イベント処理ではなく、未解決エピソードの状態を跨窓で確定させるイベント順序意味論」に争点を絞ることである。本願で最も堅い要素であり、独立クレーム化を推奨する。

---

## 5. 先行技術の要約と最も脅威的な文献（top references）

| 順位 | 文献 | 脅威の内容 | 対応 |
|---|---|---|---|
| **1** | **US7610172 / US20070294056**（JPMorgan, 非発生事象監視＋重要度分類＋通知） | IC1+IC8の抽象骨格に正面から重なる。**最大の§103/29条2項リスク。** 組合せの「動機付け」を審査官に提供する主引例。 | 「燃料計の物理的機会条件付け」「右打ち切り処理」「FCC>=50mWhという具体的測定量」「クローズドループ介入検証」で技術的に具体化。**出願前に独立クレーム本文の精読必須。** |
| **2** | **US12061240**（Battery fleet monitoring, 母集団分類＋ML異常） | IC3/IC4の拡張に最接近。Claim 2（システム）の主引例になり得る。**独立クレーム文言が未精査（スキャンPDF）。** | **OCR取得して独立クレーム全文を精読。** 内容次第でIC3/IC4の新規性が削られる。出願前の最重要残課題。 |
| **3** | **TI Impedance Track US6832171**（適格放電＝FCC学習機会）/ **US5606242** | IC1の土台「機会＝適格放電、失敗＝学習せず」を機能的に開示。新規性を「外形的・上位層からの機会反復条件付き無応答」に絞らせる。 | 新規性論拠を上位層検出＋右打ち切り＋二分岐の特定結合に限定。クレーム本文確認（US6789026/US6892148含む）。 |
| **4** | **Qualcomm US9330257**（モデル非依存行動特徴分類） | IC3の「識別子排除」の進歩性を消す（別ドメインで公知）。 | IC3を進歩性主張から外し、descriptiveな事後富化に限定（または営業秘密化）。 |
| 5 | **Song 2007（Conditional Anomaly Detection）/ Performance Digital Twin** | IC4の「規範モデル比較」を開示。 | IC4を独立化せず従属維持。ML予測フレーミングを放棄。 |
| 6 | US20130085715 / US9218527（streaming異常検知） | IC5のスライディングウィンドウ部を開示。 | IC5の争点を「跨窓未解決エピソード確定＋イベント順序意味論」に絞る。 |

---

## 6. 適格性の論点（JP/US/EP）と推奨フレーミング

審査官は全独立クレームに共通の急所として「**保守アクションが結果志向・機能的（"generating a battery maintenance control action"）で具体的構造を欠き、Alice Step 2Bの "significantly more" を満たさない**」と指摘した。これは draft の防御がこの一語の具体化に全面依存している実態を突いた、正当な hit である。以下、法域別に推奨フレーミングを示す。

### 6-1. 日本（特許法29条1項柱書）
- **論点**: 特徴部（機会検出→計数→閾値比較→分類）が純粋演算と読まれると「情報の単なる演算・分類」で柱書非該当。BMS紐付けが前提部のみだと防御が薄い。
- **推奨フレーミング**: 「データを分析して分類する」を避け、「BMSが取得したテレメトリから凍結を検出し、**ラベルに応じて深放電プロンプト表示／FWエスカレーションレコード生成という異なる物理的処理を起動し、介入後のFCC回復を観測してラベル妥当性を検証する**」と、ソフトウェアとハードウェア資源（バッテリ/BMS/ゲージIC）の協働を特徴部に織り込む。

### 6-2. 米国（35 USC 101, Alice/Mayo）
- **論点**: Step 2A Prong 1 ── ステップ(b)〜(e)は「観測・計数・閾値比較」でメンタルプロセス／数学的概念に向けられる（審査官の的中指摘）。Prong 2 ── (f)が結果志向で practical application に統合されない（Electric Power Group型で否定リスク）。Claim 6（Poisson-binomial）は純数学で最弱。
- **推奨フレーミング**: 独立クレームに **(i) ラベル依存の具体的物理介入、(ii) 介入→FCC回復のクローズドループ装置動作、(iii) 右打ち切り/欠損/30日短期保持という具体的技術制約の解決** を必須化し、Enfish/McRO/Diehr ライン（特定技術プロセスの改善）に乗せる。**ML/Poisson-binomialは独立クレームから排除し補助的従属に留める。**

### 6-3. 欧州（EPO, Comvik / T 0641/00）
- **論点**: (b)〜(e)の閾値計数・分類は数学的方法（非技術的特徴）。技術的特徴は「FCC測定」と「(f)の制御」だが(f)が抽象的で技術的貢献が希薄。near-random規範モデル（AUC=0.56）ゆえ「診断精度向上」の技術的効果も立証不十分。
- **推奨フレーミング**: 「to detect a malfunction of a battery fuel gauge / to control battery maintenance」という技術的目的を明示。ギャップ品質ゲート・右打ち切り・状態永続化を「テレメトリ計測の不完全性という技術的制約の解決手段」として technical contribution に算入させる。**ML予測性能ではなく決定論的診断＋介入制御を技術的効果の中心に据える。**

---

## 7. 推奨クレーム・セット（独立2 + 従属8）

> **審査官フィードバック反映後の補正版。** 主な補正: (A) 中核を決定論カウンタに純化（規範AUC=0.56問題を回避）、(B) 保守アクションをラベル依存の具体的物理介入に構造化（適格性確保）、(C) 介入→FCC回復のクローズドループを装置動作として追加、(D) IC5のイベント順序意味論を独立クレーム化、(E) ML/Poisson-binomial（旧Claim 6）を独立から排除し補助従属化。閾値（>=50mWh, 30日, 72h, ギャップ階層, 日数カットオフ）は具体的に保持。

### Claim 1（独立・方法）── IC1 + 具体的二分岐介入 + クローズドループ
**[日本語注釈: 機会条件付き無応答＋右打ち切り＋二分岐原因切り分けを、ラベル依存の具体的物理介入とクローズドループ検証に紐付け、適格性と進歩性を同時に確保。決定論カウンタ構成でAUC0.56リスクを回避。]**

1. A computer-implemented method for diagnosing a fuel-gauge state-of-health freeze in a battery management system, the method comprising:
   (a) obtaining, from telemetry of a battery managed by the battery management system, a time series of a full charge capacity value (FCC) in milliwatt-hours and a relative state-of-charge value (RSOC), wherein a state-of-health is driven by stepwise changes of the FCC against a per-device constant design capacity;
   (b) detecting, from the RSOC time series, one or more learning opportunities, each being a high→low→high excursion identified by a state machine that opens on RSOC ≥ a high threshold of 80, reaches a low on RSOC ≤ a low threshold of 20, and closes on RSOC ≥ the high threshold;
   (c) for each learning opportunity, determining a response status within a response window extending 72 hours from an end of the opportunity, the status being **responded** if an effective FCC step ≥ 50 mWh occurs within the window, **no_response** if no such step occurs and the window completes before a last observed timestamp, **censored** if no such step occurs and the window extends beyond the last observed timestamp, and **unknown** if FCC is missing within the window, wherein **censored and unknown statuses are excluded from a no-response count**;
   (d) assigning to each learning opportunity a gap-quality tier from a maximum inter-sample gap and a quality score, and counting toward the no-response count only opportunities whose tier is HIGH_OK or MEDIUM_GAP, thereby excluding logger-sleep intervals from non-response evidence;
   (e) assigning, within a flat tail since a last FCC change, a **firmware-suspected** label when learning opportunities recur but the no-response count reaches a predetermined count, and a **gauge-recalibration** label when no qualifying learning opportunity exists in the flat tail under any quality tier;
   (f) **responsive to the gauge-recalibration label, causing a user device to present a deep-discharge prompt, and responsive to the firmware-suspected label, generating an escalation record into a firmware-engineering queue**; and
   (g) **observing a subsequent decrease in a days-since-effective-FCC-change value as an FCC recovery, and feeding said recovery back as a validation of the assigned label.**

### Claim 2（独立・システム）── IC5 状態永続化＋イベント順序意味論（最も堅い要素を独立化）
**[日本語注釈: 30日生保持下の窓外証拠回収を、同時刻イベント優先順位とID重複防止という具体的意味論で独立クレーム化。審査官が「設計事項で潰しにくい」と認めた核を権利化。]**

2. A battery diagnostic system comprising one or more processors and a non-transitory computer-readable medium storing instructions that, when executed, cause the system to:
   limit raw telemetry visibility at each inference time to a trailing 30-day window advanced at a 1-day stride;
   detect learning opportunities and per-opportunity FCC response statuses as recited in claim 1;
   **recover evidence of FCC non-response from opportunities whose start precedes the 30-day window by replaying, in timestamp order, resolved events keyed by an episode identifier into a persistent derived state, the events comprising an opportunity-completion event, an FCC-reset event, and a response-deadline event ordered at equal timestamps by completion < reset < deadline, and counting each physical episode at most once by its episode identifier**, thereby recovering episodes whose opening high precedes the visible window and which a stateless comparator would miss;
   classify each battery into one of mutually exclusive triage labels by the firmware-suspected and gauge-recalibration criteria of claim 1; and
   emit, per battery, a single triage label and a corresponding label-dependent maintenance action.

### 従属クレーム

**Claim 3（IC1: 二分岐の閾値詳細）**
3. The method of claim 1, wherein the firmware-suspected label requires a flat tail of at least 180 days, a tail cycle delta of at least 30, and a no-response count of complete-window, OK-quality opportunities of at least 3 in a primary 80/20/80 band or at least 2 in a strict 90/10/90 band, and the gauge-recalibration label requires a flat tail of at least 120 days.
**[注釈: 二分岐の具体的閾値。strict帯併用で頑健化。]**

**Claim 4（IC6: ギャップ品質ゲートを機能・効果に限定）**
4. The method of claim 1, wherein assigning the gap-quality tier comprises classifying as LOW_LARGE_GAP an opportunity containing a logger-sleep interval, and structurally excluding LOW_LARGE_GAP opportunities from the no-response count to suppress false positives arising from observation gaps, while not concluding "no opportunity" when a large-gap opportunity exists.
**[注釈: 審査官指摘を反映し、臨界性立証困難な数値(0.45/0.35/0.20)を外し機構として権利化。large-gap排除＋gauge誤分類防止の安全策。]**

**Claim 5（IC2: デュアルトラック）**
5. The method of claim 1, further comprising maintaining an any-change track reset on any FCC step ≥ 1 mWh and an effective track reset on any FCC step ≥ 50 mWh, and classifying a battery whose effective track is stale but whose any-change track exhibits only sub-threshold micro-wobble steps into a soft-calibration label distinct from a hard freeze label.
**[注釈: micro-wobble分離。進歩性は弱いが従属として保持。]**

**Claim 6（IC1: 窓・閾値のデータ駆動サポート根拠）**
6. The method of claim 1, wherein the 72-hour response window is selected such that at least 95% of observed FCC responses in the primary band occur within the window, and the no-response count threshold is selected such that, under a normative responding probability, a probability of that many consecutive no-responses is at most 0.05.
**[注釈: サポート要件補強用（応答遅延CDF 0.9513、k=2で0.013）。ただし審査官は「事後CDF逆算＝ルーチン最適化の自認」と読むため、明細書サポート専用とし進歩性主張には依拠しない。]**

**Claim 7（IC4: ツインモデルを「基準線確立」に機能再定義）**
7. The system of claim 2, wherein the system trains a normative response model that structurally excludes all FCC-history, days-since-change, and prior-response features by a forbidden-substring guard enforced at training time, and **uses the normative model solely to establish a healthy-gauge response baseline for validating the deterministic no-response count, not as a predictive anomaly score**.
**[注釈: 審査官のAUC0.56攻撃を回避するため「異常スコア」フレーミングを放棄し基準線検証に限定。独立化せず従属維持。]**

**Claim 8（IC8: DQ最優先ゲート）**
8. The system of claim 2, wherein a data-quality review gate has highest priority such that a battery is labeled for review when a window data-quality label is not OK, a state history is shorter than 60 days, or a counter reset is present, before any firmware-suspected or gauge-recalibration label is considered.
**[注釈: DQ最優先の単一ラベルラダー。適格性補強。]**

**Claim 9（IC8: アラート・クールダウン制御 ── 適格性補強の要）**
9. The system of claim 2, wherein the maintenance action includes firing an alert only upon transition into an actionable label, suppressing further alerts for a cooldown period of 30 days, and resetting the cooldown upon a decrease in a days-since-effective-FCC-change value indicating FCC recovery.
**[注釈: 具体的制御アクション。審査官も「適格性論争で出願人に最も使われる従属」と認めた§101補強材。]**

**Claim 10（IC3: 経験ベイズ富化を分類後descriptiveに限定）**
10. The system of claim 2, wherein, only after said classification and without feeding into the classification, the system estimates a per-identifier prevalence of the firmware-suspected label by method-of-moments Beta-prior empirical-Bayes shrinkage with Fisher exact significance and Benjamini–Hochberg FDR correction over identifier groups having at least 5 members.
**[注釈: 事後HW富化。進歩性主張には依拠せず、分類後descriptiveとして明確に切り分け。]**

> **クレーム構成の意図**: 独立2件（Claim 1=IC1, Claim 2=IC5）に最有望2要素を配置し、いずれも決定論カウンタ＋具体的物理介入＋クローズドループで構成して適格性・進歩性を両立。旧draftで独立だったPoisson-binomial（IC7）は**全面削除**（純数学で適格性不可のため）。IC4はClaim 7で「基準線検証」に機能再定義し延命。

---

## 8. リスク・弱点と未解決事項

審査官のストレステストで露呈した弱点を率直に列挙する。

### 8-1. 規範モデルAUC≈0.56の扱い（重要・的中hit）
規範モデルの ROC AUC = 0.5584 は near-random であり、**「MLによる異常検出」フレーミングを著しく弱める。** 審査官は「near-randomなモデルに基づく異常スコアに技術的効果なし」「異常スコアと無応答カウントの相関0.993 ── 実質同一物」と攻撃し、主張する相乗効果（ML+統計の高度な組合せ）を出願人自身のデータで否定した。**これは正当なhitである。**
- **対応**: 中核クレーム（Claim 1/2）を**決定論的 no_response カウント＋閾値**で構成し、ML/Poisson-binomial（旧Claim 6=IC7）は独立から削除。IC4（Claim 7）は「異常スコア」を放棄し「健全ゲージ基準線の検証」に機能再定義。これによりAUC=0.56攻撃の射程外に出る。なお、AUC=0.56は裏返せば「FCC履歴を抜くと健全前提（機会があれば応答する）が基準線として確立する」ことの実証でもあり、IC4のリーク回避効果の証拠としては有効に使える（ただし進歩性の主軸には置かない）。

### 8-2. プロキシラベル依存
FW precision/recall（FW Core precision 1.0 / recall 0.357、top50 recall 1.0）は**プロキシラベル**（真の地上真実=実FW不具合確定ではない）に基づく。conformal_p_proxy 等の評価が代理指標依存である点は技術的効果の立証強度を弱める。
- **対応**: 実機FW不具合の確定ラベルでの再検証が望ましい（8-3とセットで取得）。

### 8-3. BIOS/FWバージョン・介入結果データの欠如（最大の実証ギャップ）
- **BIOS/FWバージョン情報が分類入力に無い**（意図的にモデル非依存だが、「FW起因」確証には本来FW版相関が欲しい ── 事後富化として）。
- **介入→FCC応答のクローズドループ証拠が無い**: 「gauge-resetラベル機にユーザが深放電したらFCCが応答した」「FW更新したら凍結が解けた」という介入結果データが未取得。審査官は「actionable triageの技術的効果という進歩性・適格性双方の根幹が未立証」とし、**現状の出願を『時期尚早』と認定した。** これは最も重い未解決事項である。
- **対応**: Claim 1(g)でクローズドループを装置動作として織り込んだが、その**実証データ取得が出願強化の最優先事項**（第9節）。

### 8-4. クレーム抽象性リスク（的中hit）
独立クレームの "maintenance control action" が結果志向・機能的だと、全法域で「汎用コンピュータ上の抽象的判定＋名目的な後付けアクション」と認定される。
- **対応**: Claim 1(f)を**ラベル依存の具体的物理介入（深放電プロンプト表示／FWエスカレーションレコード生成）**に構造化済み。(e)の「freeze threshold」「predetermined count」等の機能的プレースホルダはClaim 3で具体的閾値に限定済み（§112/36条6項対応）。

### 8-5. その他の留保
- **閾値の事後逆算自認（Claim 6）**: Claim 6（旧11）が「閾値は観測CDFからの逆算」と自認しており、審査官はこれを「全閾値=ルーチン最適化」の弾薬に使う。→ Claim 6を進歩性主張から切り離し、明細書のサポート要件専用に限定。閾値ロバスト性（Jaccard=1.0）は「効果が閾値選択に頑健」という反論材料だが「どの閾値でも同じ=臨界性なし」とも読める諸刃である点に留意。
- **観測長バイアス**: `very_stale`（>=180日フラット）は obs_days と機械的相関。span-robust指標（fcc_change_rate_per_100d, Cliff d=0.894）で無害化済みだが、明細書に反論材料を記載。
- **NOW=2026-06-02固定参照**: バックテスト用。実運用クレームでは「現在時刻」に置換要（明細書で両立担保）。

---

## 9. 出願戦略・次アクション

### 9-1. 法域戦略（JP優先 → PCT → US/EP）
- **日本先願（JP first）を推奨**。理由: (i) 29条1項柱書はソフトウェア＋ハードウェア協働で比較的クリアしやすい、(ii) 適格性ハードルが米国Aliceより低く権利化基盤を先に確保できる。
- 続いて**PCT出願**で優先日確保。
- **米国移行**: クレームをBMS/制御アクション/クローズドループに強く紐付けた版（Claim 1/2/9型）で§101対応。**ML/Poisson-binomialは独立から排除。**
- **欧州移行**: Comvik対応で技術的目的（fuel-gauge malfunction detection）を前面化。決定論診断＋介入制御を技術的効果の中心に。

### 9-2. 補強に必要な追加データ・実験（優先順）
1. **介入→FCC応答のクローズドループ実証（最優先）**: gauge-resetラベル機で深放電プロンプト後にFCCが応答した率、FW疑い機でFW更新後に凍結解消した率を収集。これがあればClaim 1(g)の装置動作が実体を伴い、「actionable triageの技術的効果」を因果的に立証でき、進歩性・適格性が劇的に強化される（8-3解消）。**これなしの出願は時期尚早。**
2. **真のFW不具合確定ラベル**: プロキシでなく実FW欠陥/ゲージ故障の確定データで precision/recall を再検証（8-2解消）。
3. **BIOS/FWバージョン相関**: FW疑い群がFW版に有意偏在することを示す（分類入力には入れず事後富化）。
4. 閾値ロバスト性（Jaccard=1.0, 応答遅延CDF）は既に強い実証であり、明細書のサポート要件・進歩性論拠に全面活用。

### 9-3. 防御的公開 vs 営業秘密 vs 特許の振り分け
- **特許化すべき中核**: **IC1（機会条件付き無応答＋右打ち切り＋二分岐＋クローズドループ）、IC5（状態永続化＋イベント順序意味論）。** 外形的に製品挙動から推測されにくく新規性余地が大きい。IC4/IC6は補強従属。
- **営業秘密として保持**: 具体的閾値の微調整値（active-reference分位、EB集中度 k0∈[1,500]、スコアリング係数 30/25/20/15/10、コホート派生定数 CYC_LO=30.27 等）。データ駆動更新でリバースエンジニアリング困難。クレームには構造的閾値（>=50mWh, 30日, 72h, >=180日）のみ入れ、微調整値は明細書 best mode に留める。
- **防御的公開**: **IC2/IC3/IC7/IC8** ── 進歩性「低」かつ周知技術寄せ集めのため特許化を諦め、他社の権利化阻止のため防御的公開に回すのが honest な判断。とくにIC7（Poisson-binomial）は純数学で特許不可のため公開向き。US12061240精読の結果、IC3/IC4のフリート分類部分の新規性が薄いと判明した場合も同部分を防御的公開に。

### 9-4. タイムライン上の注意 ── 新規性喪失リスク（出願前必須確認）
- **既存の社内/外部公開有無の確認（最優先・法的時限）**: 本アルゴリズム・閾値・実証結果が、社内Wiki/技術ブログ/学会発表/製品リリースノート/GitHub等で**既に公開されていないか**を出願前に必ず確認する。公開済みなら新規性喪失（JP29条1項各号/US §102）で出願不能、または新規性喪失の例外（JP30条/US grace period 1年）の適用可否を弁理士と精査。**これは出願タイミングを左右する最重要の時間的論点。**
- **US12061240 および US7610172/US20070294056 の独立クレーム全文精読（スキャンPDFのOCR取得）**: 進歩性論争の主戦場。精読なしに出願範囲を確定すべきでない。
- TI Impedance Track 特許群（US6832171/US6789026/US6892148）のクレーム本文確認。
- 明細書に **(i) 右打ち切り処理、(ii) ギャップ品質ゲート、(iii) 状態永続化、(iv) クローズドループ介入検証** の各々につき「解決する具体的技術課題」「従来法で生じる偽陽性/偽陰性の具体例」を記載し、Comvik/Aliceの技術的効果立証と進歩性の相乗効果論拠を厚くする。

### 9-5. 出願可否の最終判断（意思決定者向け）
**「IC1+IC5に絞り、第9-2節の追加データ（特にクローズドループ実証）取得後に出願」を推奨する。** 現状クレームのままでも IC1/IC5 は中程度の許可可能性があるが、(a) 介入結果データ欠如、(b) US12061240未精査、(c) 公開有無未確認 の3点が未了の限り、進歩性・適格性の最終評価は確定できず、審査官側も「時期尚早」と認定している。これら3点を解消し、本報告の補正クレーム（決定論カウンタ＋具体的二分岐介入＋クローズドループ＋IC5イベント意味論独立化）で出願すれば、IC1/IC5を中核とした防御可能な権利取得が見込める。

---

## DISCLAIMER（免責事項）

**本報告書は、エンジニアリング/技術的観点からの特許性評価であり、法的助言（legal advice）ではありません。** 本書の新規性・進歩性・適格性に関する評価、先行技術の解釈、クレーム文言、および出願戦略は、提供された抽出資料・サーベイ・社内データに基づく技術的見解であって、特許権の取得可能性を保証するものではありません。先行技術調査は本報告で参照した範囲に限定されており、網羅的なものではありません。出願の可否、クレームの最終的な文言、各法域での権利化可能性、新規性喪失の例外（JP特許法30条/US grace period）の適用、および本書で指摘した未精査文献（US12061240・US7610172等）の影響については、**出願前に必ず登録弁理士（patent attorney）による正式なレビューを受けてください。** 本報告書の利用に起因する一切の結果について、作成者は法的責任を負いません。