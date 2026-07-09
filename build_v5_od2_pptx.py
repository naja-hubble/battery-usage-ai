#!/usr/bin/env python
"""FCC更新停止(ゲージ凍結)者の判定技術 — 社内 patent review 用サマリ deck (.pptx).

学習機会を実機のFCC再学習ロジック（2機構: Type A 深放電 / Type B 充電側）で定義し、
満充電END起点168h窓で無応答を機械的に監査する判定技術と、その特許候補をまとめる。
すべて『2機構の学習機会』を前提に、結果は単独の事実として提示する（過去の暫定定義との
比較は行わない）。

数値は data/reports/fcc_relearn_od2_MASTER_report.md（検証済）に準拠。図は
data/reports/figures/fcc_relearn_od2/。NOT a legal opinion / 先行技術 UNVERIFIED /
介入・FWバージョンデータ NOT AVAILABLE / proxy ラベル / 捏造なし。
"""
from __future__ import annotations
import sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from pptx.util import Inches, Pt
import od2_deck_common as dc
from od2_deck_common import (Deck, NAVY, BLUE, STEEL, GREY, RED, GREEN, DGREEN, WHITE,
                             ORANGE, TEAL, PURPLE, INK, LIGHT, status_styler)

REPO = Path(__file__).resolve().parent
FIG = REPO / "data" / "reports" / "figures" / "fcc_relearn_od2"
OUT = REPO / "data" / "reports" / "fcc_patent_summary_slides_v5_od2.pptx"
D = Deck(OUT, FIG)

# =========================================================================== #
# 1. Title
# =========================================================================== #
D.title_slide(
    "テレメトリからの FCC更新停止（ゲージ凍結）者の判定技術",
    "— 学習機会を実機の2機構で定義した、機会条件付き無応答監査 —（社内 patent review 用）",
    ["本題: ノートPCバッテリのテレメトリ(RSOC/FCC/サイクル/充電状態/時刻)だけで『FCCを再学習しなくなった個体』を判定する",
     "学習機会は実機の2機構で定義: Type A（満充電→RSOC≤6%→満充電, 深放電）/ Type B（充電中に60-80%通過→満充電, 充電側）",
     "母集団: 実バッテリ履歴 752ユーザー / 3,130,394 サンプル / 満充電END起点の応答窓 168h",
     "核心: 両機構とも敵対的な負の対照を独立にパス → 機会条件付き無応答監査は二機構で成立",
     "技術効果は proxy ラベルに依存しない独立指標(5本柱 A2/A3/B/E/D)で検証。法的結論は主張しない"])

# =========================================================================== #
# 2. Executive summary
# =========================================================================== #
s = D.section("エグゼクティブサマリ — 1枚で全体像", NAVY, "Summary")
tf = dc._tb(s, Inches(0.55), Inches(1.02), D.SW - Inches(1.1), Inches(5.3))
first = True
for head, body in [
    ("課題", "SoH健全性表示を駆動する満充電容量(FCC)が長期間更新されない『ゲージ凍結』は、静的検査では"
             "『浅い使い方で正常』『要再較正』『FW/HW起因』を判別できない。752台中114台が凍結、うち70台は使用で説明不能。"),
    ("学習機会の定義", "燃料計がFCCを再学習するのは実機の2機構: Type A=満充電→深放電(RSOC≤6%)→満充電、"
             "Type B=充電中にRSOC 60-80%帯を通過して満充電。両者とも END=満充電到達。"),
    ("手法", "『凍結を予測』は失敗(AUC≈0.54)。代わりに『再学習の機会に実際に応答したか』を満充電END起点168h窓で機械的に監査する。"
             "テレメトリのみ・機種非依存・欠測/打ち切りに頑健・30日保持でも全期間と等価。"),
    ("実績(実フリート752台)", "全履歴監査で FW確認候補35台 / ゲージ再較正候補10台に自動振り分け。30日オンライン運用版は"
             "FW_CORE 49台 / GAUGE_CORE 0台。5本柱の独立検証(A2/A3/B/E/D)で技術効果を実証。"),
    ("特許候補", "①機会条件付きEND起点168h無応答監査(中核) ②デュアルトラック非対称リセット ③有界保持の因果証拠台帳 ＋将来④⑤。"
             "新規性の核心は『深放電を伴わない充電側部分再学習の検出』と『2機構を満充電ENDで統合＋機構別k較正』。"),
    ("reviewerへの依頼", "(1)二機構クレームの粒度・範囲の判断 (2)充電側部分再学習検出の新規性/先行技術調査の発注 "
             "(3)候補②の着想日・公開有無の確認 (4)正式なFTO/特許性調査(弁理士)の発注判断"),
]:
    p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
    dc._set(p, "■ " + head, size=13, bold=True, color=NAVY); p.space_before = Pt(5)
    q = tf.add_paragraph(); dc._set(q, body, size=11.3, color=INK)
D.takeaway(s, "『動くべき機会に動かなかった』事実だけを、欠測に騙されず数える監査。深放電と充電側の両機構でエビデンスは強い。")
D.footer(s)

# =========================================================================== #
# 3. Guide
# =========================================================================== #
s = D.section("本資料の構成と読み方", NAVY, "Guide")
parts = [
    ("§1 基礎知識", "燃料計/FCC・RSOC・SoH / FCC再学習の2機構 / なぜ問題か", STEEL, "非エンジニアはここから"),
    ("§2 用語定義", "バッテリ・学習機会(2機構) / 検証手法・統計", STEEL, "つまずいたら戻る辞書"),
    ("§3 本題(Part1)", "目的 → 失敗と発想転換 → 学習機会の定義 → 手法 → 実フリート結果", NAVY, "判定技術そのもの"),
    ("§4 根拠", "5本柱 A2/A3/B/E/D（図解説つき）+ 技術効果まとめ", DGREEN, "なぜ信じてよいか"),
    ("§5 特許候補(Part2)", "候補①〜③ + 新規性の核心 + 将来④⑤", PURPLE, "reviewer判断の対象"),
    ("§6 開示とまとめ", "正直な開示 / 知財戦略 / 依頼事項", RED, "リスクと残課題"),
    ("§7 付録", "特徴量 / データと再現性 / 代替実施形態 / 先行技術差別化", GREY, "深掘り用"),
]
y = Inches(1.15)
for name, desc, col, note in parts:
    D.box(s, Inches(0.5), y, Inches(2.7), Inches(0.6), name, col, size=12)
    D.label(s, Inches(3.4), y + Inches(0.03), Inches(6.1), Inches(0.6), desc, size=11.5, color=INK)
    D.label(s, Inches(9.7), y + Inches(0.03), Inches(3.3), Inches(0.6), note, size=10.5, color=GREY)
    y += Inches(0.72)
tf = dc._tb(s, Inches(0.5), y + Inches(0.05), D.SW - Inches(1.0), Inches(0.9))
dc._set(tf.paragraphs[0], "図スライドは4ブロック（何のグラフ/軸/主張/読み方）構成。各スライド下部の黄色帯（💡）は非エンジニア向けの一言要約。",
        size=11.5, color=INK)
q = tf.add_paragraph()
dc._set(q, "正直さの記号 — UNVERIFIED: 先行技術は未検証 / NOT AVAILABLE: そのデータは存在しない(捏造しない) / "
        "proxy: 正解ラベルは本番システムの推定値。", size=11.5, bold=True, color=RED)
D.footer(s)

# =========================================================================== #
# §1 basics
# =========================================================================== #
s = D.section("基礎① 燃料計・FCC・RSOC・SoH とは", STEEL, "§1 基礎知識")
D.make_table(s, ["用語", "意味", "身近なたとえ"],
    [["FCC（満充電容量）", "『いま満タンでどれだけ入るか』の学習値(mWh)。劣化で減る", "計り直して覚える『いまの満タン量』"],
     ["RSOC（相対残量）", "いまの残量% = 残容量 ÷ FCC × 100", "ガソリンメーターの針"],
     ["SoH（健全性）", "健康度% = FCC × 100 ÷ 設計容量", "新品比の容量%"],
     ["FCC再学習(再較正)", "特定の充放電パターンのときだけ、ゲージICがFCCを計り直す", "体重計のゼロ点合わせ"],
     ["ゲージ凍結", "FCCが長期間更新されない。SoH表示も止まる", "校正が止まり表示が古いまま"]],
    Inches(0.45), Inches(1.05), [2.7, 6.3, 3.4], row_h=0.6, cell_size=11)
tf = dc._tb(s, Inches(0.5), Inches(4.95), D.SW - Inches(1.0), Inches(1.4))
D.bullets(tf, ["実容量は直接測れない。ゲージIC(燃料計チップ)が充放電から『推定』する",
               "FCCは整数mWh量子化(最小10mWh)で階段状にしか動かない",
               "SoH表示・残り時間・保証/リース判断はすべてこのFCC学習値に依存する"], size=12)
D.takeaway(s, "PCの電池残量・健康度は『実測』ではなく『燃料計チップの学習値』。学習が止まると表示だけが古いまま残る。")
D.footer(s)

# basics② — the two mechanisms (with diagram) = THE definition
D.figure("基礎② FCC再学習の『2つの機構』 — 本技術の学習機会の定義", "§1 基礎知識",
         "od2_mechanism_diagram.png",
         "実機のFCCが再学習される2つの充放電パターンをRSOC波形で示す模式図（左=Type A / 右=Type B）。",
         "縦=RSOC(%)、横=時間。緑破線=満充電(≥99%)、赤帯=深放電(≤6%)、橙帯=充電側の60-80%通過帯。",
         "実機のFCC再学習は2経路: Type A（満充電→RSOC≤6%→満充電）と Type B（充電中に60-80%を通過→満充電）。この2つを『学習機会』と定義する。",
         "どちらも END=満充電到達で完了 → END起点で応答を監査すれば一つの枠組みで両機構を扱える。",
         "燃料計がFCCを計り直す“チャンス”は、深放電フルサイクルと、充電側の部分再学習、の2種類。これを機会と定義する。",
         accent=STEEL)

s = D.section("基礎③ ゲージ凍結はなぜ問題か", STEEL, "§1 基礎知識")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(5.2))
D.bullets(tf, [
    "SoH表示が古いままだと: 劣化見逃し→突然のシャットダウン / 健全電池の誤交換→無駄コスト / 保証・リース判断の歪み（定性・金額効果は未算定）",
    "実フリート752台: 凍結114台(15.2%) = stale 59 + very_stale 55",
    "うち使用で説明可 44台（常時AC 22 / 低サイクル 16 / 浅放電 6）",
    "説明不能（HW/FW疑い）70台: activeより多くサイクル(96.9 vs 65.7 cyc/yr)・深く放電するのに凍結（『疑い』であり確定診断ではない）",
    "対処は原因ごとに異なる（較正で直る/FW確認が要る）。見分ける仕組みが無いと保守が空回りする"], size=12.5)
D.takeaway(s, "原因はユーザー起因〜FW疑いまで様々で対処も違う。凍結を見分ける仕組みが要る。")
D.footer(s)

# =========================================================================== #
# §2 glossary
# =========================================================================== #
D.glossary("用語定義 (1/2) — バッテリと学習機会（2機構）", [
    ("FCC / RSOC", "燃料計が学習する満充電容量(mWh) / 相対残量% = 残容量÷FCC×100。"),
    ("満充電(END)", "RSOC ≥ 99%。両機構の学習機会の完了点＝応答監査の起点。"),
    ("Type A（深放電再学習）", "満充電 → RSOC ≤ 6% → 再び満充電。深いフル放電サイクル。健全機の168h応答率 0.74(強い刺激)。"),
    ("Type B（充電側再学習）", "充電中(chargeStatus=1)にRSOCが60-80%帯を通過して満充電へ。深放電不要。健全機の応答率 0.45(高頻度・弱い刺激)。"),
    ("有効ステップ / micro", "|ΔFCC| ≥ 50mWh を学習応答とみなす / <50mWhの微小変化。量子化最小は10mWh。"),
    ("応答ステータス(END後168h窓)", "responded / no_response(窓を全観測して無し) / censored(観測が途中終了→保留、無応答に数えない)。"),
    ("品質ティア", "HIGH_OK / MEDIUM_GAP / LOW_LARGE_GAP（エピソード内サンプル間隔で判定）。"),
], tag="§2 用語定義")

D.glossary("用語定義 (2/2) — 検証手法と統計", [
    ("負の対照 / ヌル分布(A2)", "ニセ機会で効果が無い場合の期待分布。真の値が95%区間の外なら『偶然では説明できない』。"),
    ("アンカー比較(A3)", "起点をSTART/LOW/ENDに変えたときの因果汚染（END前のステップ混入率）を定量化。"),
    ("応答ハザード(B)", "END後経過時間に対する累積応答率(CIF)。真の機会 vs matched-pseudo。"),
    ("欠測ストレス(E)", "データ欠落/打ち切りを注入し、誤って『無応答』と確定する件数を検出器間で比較。"),
    ("保持不変性(D)", "生データ保持を短くしても永続state(台帳)で全期間と同じ結論が出るか。"),
    ("k(FW閾値)", "FW確認へ回す無応答回数の下限。機構別に較正: Type A=3 / Type B=5（healthy応答率 0.74/0.45 と (1-p)^k≤0.05 から）。"),
    ("proxyラベル", "本番システムの出力を仮の正解としたもの（地上真実ではない）。"),
], tag="§2 用語定義")

# =========================================================================== #
# §3 Part1
# =========================================================================== #
s = D.section("本来の目的と、なぜ難しいか", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.1), D.SW - Inches(1.1), Inches(0.6))
dc._set(tf.paragraphs[0], "目的: テレメトリだけからゲージ凍結個体をフリート規模で正しく判定する。", size=14, bold=True, color=NAVY)
tf2 = dc._tb(s, Inches(0.55), Inches(1.85), D.SW - Inches(1.1), Inches(4.0))
D.bullets(tf2, [
    "静的検査では『浅充放電で正常』『要再較正』『FW/HW起因』を区別できない",
    "欠測・睡眠ギャップ・打ち切り: データの穴を『無応答』と誤判定しやすい",
    "生データ保持が有界（直近30日等）で過去の証拠が失われる",
    "機種非依存が必須（機種名ハードコードは過学習）",
    "そもそも『どういう時に再学習するか』を実機どおり(2機構)定義しなければ監査が的外れになる"], size=13)
D.takeaway(s, "『FCCが動かない』結果は同じでも原因は複数。まず実機どおり(2機構)に学習機会を定義するのが出発点。")
D.footer(s)

s = D.section("失敗した素朴アプローチ → 発想の転換", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.1), D.SW - Inches(1.1), Inches(4.6))
D.bullets(tf, [
    "教師あり予測(33特徴量, 公平比較領域 obs≥180d): AUC 0.535/0.540 — ほぼコイン投げ",
    "FCC履歴を除いた規範ML: AUC 0.5584 — near-random。最重要特徴 min_rsoc は『深放電ほど凍結』の反usage交絡",
    "→ 発想転換: 『凍結を当てる』のではなく『再学習“機会”に対して実際に応答したかを機械的に監査する』(決定論カウンタ)",
    "機会の定義が正しければ、この監査は機種非依存・欠測頑健・有界保持で全期間等価に作れる"], size=13)
D.takeaway(s, "壊れそうかをAIに予言させるのは失敗(コイン投げ並み)。『チャンスに応えたか』を出席簿のように数える方式に切替えたら解ける。")
D.footer(s)

s = D.section("提案手法の全体像", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(0.5))
dc._set(tf.paragraphs[0], "入力: RSOC / FCC / cycleCount / chargeStatus / timestamp のみ（HW識別子は不使用）。", size=12.5, bold=True, color=NAVY)
tf2 = dc._tb(s, Inches(0.55), Inches(1.55), D.SW - Inches(1.1), Inches(4.4))
D.bullets(tf2, [
    "1. 学習機会の抽出（Type A: 満充電→≤6%→満充電 / Type B: 充電中に60-80%通過→満充電）",
    "2. END起点で応答監査（END後168h窓の有効ステップ≥50mWh）",
    "3. 欠測/打ち切り耐性（段階品質ティア＋censored除外）",
    "4. 二分岐トリアージ（機会反復×無応答→FW / 機会皆無→ゲージ再較正）＋機構別k較正(A=3/B=5)",
    "5. 有界保持で証拠保全（最小状態の因果台帳、30日保持で全期間等価）"], size=13)
D.box(s, Inches(0.55), Inches(5.95), D.SW - Inches(1.1), Inches(0.42),
      "対応: ①(手順1+2+3+4) / ②(dual-track) / ③(手順5)。新規性の核心は『2機構＋満充電END統合＋機構別k・168h窓』。",
      LIGHT, fg=NAVY, size=11)
D.footer(s)

# flowchart — acquisition to judgment
D.flowchart("処理フロー — データ取得から判定まで", "§3 Part1")

# detailed flow of ④⑤ (per opportunity) and ⑥ (per user)
D.detail_flow_audit()
D.detail_flow_triage()

# why 168h (attribution)
D.figure("なぜ応答窓は168hか — 再学習の応答は72hを越えて続く", "§3 Part1",
         "od2_attribution_window.png",
         "実際に起きたFCC更新のうち、直前にType A/Bの機会ENDがあるものの割合を、監査窓の幅ごとに示す。",
         "縦=Type A/Bの機会で説明できたFCC更新の割合(%)、横=応答窓(h)。緑破線=採用する主窓168h。",
         "窓が24h→72h→168h→336hと広がるほど説明率は 46.7%→69.1%→86.1%→91.1% と上がる。応答の多くは満充電の数日後に起きる。",
         "168h(7日)で86%を捕捉。実機の再学習レイテンシに整合する窓として168hを主窓に採用する。",
         "満充電の後どれだけFCCを計り直したかを数える。応答は数日遅れて起きるので、締切は7日(168h)が実機どおり。",
         accent=DGREEN)

# mechanism strength
D.figure("2機構の『強度』の違い — 深放電は強い、充電側は高頻度だが弱い", "§3 Part1",
         "od2_mechanism_strength.png",
         "健全な(active-reference)ゲージが、各機構の機会に168h以内で応答する割合。",
         "縦=健全機の応答率@168h、棒上=FW確認へ回す無応答回数の閾値k。",
         "Type A=0.74（強い深放電トリガ, k=3）、Type B=0.45（高頻度だが弱い充電側トリガ, k=5）。",
         "機構ごとに『健全でも応答しない率』が違うため、FW判定のkを機構別に較正する（Type Bは高めのk=5）。",
         "同じ『無応答』でも深放電(強)と充電側(弱)で健全機の応答率が違う。だからFW閾値kを機構別に較正する。",
         accent=STEEL)

# k justification
D.k_basis("§3 Part1")

# coverage
D.figure("監査可能カバレッジ — フリートの大半が学習機会を持つ", "§3 Part1",
         "od2_coverage.png",
         "OKクオリティの学習機会を1回以上持つユーザー数（=監査可能）と、機会が全く無いユーザー数。",
         "縦=ユーザー数、緑=監査可能(687)、橙=機会ゼロ=ゲージ候補(46)、点線=コホート752。",
         "2機構で数えると 687/752 が監査可能。機会が全く無い『ゲージ再較正候補』は46人。",
         "充電側(Type B)が遍在するため、ほとんどの端末が何らかの学習機会を持つ。機会ゼロは真にゲージ候補。",
         "実機どおり2機構で数えると、フリートの大半が監査できる。機会が全く無い端末だけがゲージ候補。",
         accent=DGREEN)

# offline triage
D.figure("実フリート結果① 全履歴監査のトリアージ", "§3 Part1",
         "od2_triage_offline.png",
         "no/low-change候補(96台)を、機会条件付き無応答監査で FW確認 / ゲージリセット / WATCH に振り分けた結果。",
         "縦=ユーザー数。FW確認=機会あるのに無応答、ゲージリセット=機会皆無、WATCH=境界/large-gap。",
         "FW確認35台 / ゲージリセット10台 / WATCH42台（NORMAL 327・REVIEW 338は候補外）。active層からの誤エスカレーション0件。",
         "機会があるのにFCCが応答しない端末(FW確認)が最多。機会皆無で較正候補が10台。境界はWATCHで保留。",
         "『機会に無応答→FW確認』が中心。機会が本当に無い端末だけを『ゲージ較正』に回す。",
         accent=DGREEN)

# online tiers
D.figure("実フリート結果② 30日オンライン運用版の9段判定", "§3 Part1",
         "od2_online_tiers.png",
         "直近30日の生データ＋永続stateで運用する版が、各ユーザーに与える9段ラベルの分布。",
         "横=ユーザー数。FW_CORE/FW_WATCH=FW確認系、GAUGE系=較正系、REVIEW_DQ=データ品質保留、WATCH系=保留。",
         "FW_CORE 49 / FW_WATCH 99 / GAUGE_CORE 0 / GAUGE_SOFT 2 / REVIEW_DQ 325 / NORMAL 41。Core判定 proxy精度は高精度・能動誤報0件。",
         "充電側機会がほぼ毎窓あるため『機会皆無=ゲージCore』はほぼ発生せず、確定信号はFW側に集中する。",
         "運用版でも同じ方向: 確定アクションはFW確認が中心。累積判定の副作用は§6で正直に開示する。",
         accent=DGREEN)

# =========================================================================== #
# §4 five pillars
# =========================================================================== #
s = D.section("判定法が機能する根拠 — 5本柱（機構別）", DGREEN, "§4 根拠")
D.make_table(s, ["根拠", "検証", "主張（本手法の技術効果）", "ひとことで"],
    [["A2", "負の対照(ニセ機会4種)", "真応答 A0.637/B0.368/union0.359 が各null外(4/4)", "プラセボでは効かず本物でだけ効く（両機構）"],
     ["A3", "応答起点の比較", "END汚染0(両機構)。起点をずらすと過大計上", "採点はテスト後(満充電)から"],
     ["B", "応答ハザード(CIF)", "真CIF>>pseudo。応答は72hを越えて続き168hで捕捉", "本物の機会の後ほど遅れて計り直す"],
     ["E", "欠測・打ち切り注入", "誤無応答 naive204→proposed5(~40x)・回収0.96", "データの穴を冤罪にしない"],
     ["D", "保持グリッド7〜90日", "stateful recall1.0/重複0・容量4.2%(@168h)", "30日のメモで全履歴と同じ結論"]],
    Inches(0.4), Inches(1.05), [0.8, 3.0, 5.9, 3.0], row_h=0.62, cell_size=10.5)
tf = dc._tb(s, Inches(0.5), Inches(5.2), D.SW - Inches(1.0), Inches(1.1))
dc._set(tf.paragraphs[0], "いずれも proxy 非依存の独立エンドポイント。user-clustered bootstrap。各機構(Type A/Type B/union)で個別に検証。",
        size=12, color=INK)
D.takeaway(s, "5本柱すべて成立。特に A2 で『充電側 Type B も本物の学習刺激』であることが決定的に示された。")
D.footer(s)

D.figure("根拠① A2 負の対照 — 両機構が『自分専用のnull』を超える", "§4 根拠",
         "od2_negative_control_by_mechanism.png",
         "真の応答確率(赤線)と、機会と応答の対応を壊した4種のニセ機会null(灰棒)を、機構別に比較(168h)。",
         "縦=END起点の有効応答確率@168h、横=4つの負の対照。赤線=真値。左=Type A/中=Type B/右=union。",
         "Type A 0.637 / Type B 0.368 / union 0.359 がいずれも自分専用null(0.18〜0.53)の95%上端を超える(各4/4・4/4方向一致→SUPPORTED)。",
         "★Type Bは短窓では自分のnull近くだが168hで0.368に上がり明確に超える → 充電側は背景充電でなく本物の学習刺激。",
         "プラセボ(ニセ機会)では効かず本物の機会でだけ効く。★充電側Type Bも本物の学習刺激だと確定した。",
         accent=DGREEN)

D.figure("根拠② B 応答ハザード — 応答は72hを越えて続く", "§4 根拠",
         "od2_response_hazard_by_mechanism.png",
         "END後の累積応答率(CIF)を、真の機会(赤)と matched-pseudo(灰破線)で、機構別に時間軸で示す。",
         "縦=累積応答率(CIF)、横=END後経過時間(h)。緑破線=採用する主窓168h。",
         "真CIFは常に pseudo を上回り、差は時間とともに増大: Type A 0.643(168h)、Type B 0.368(168h)。応答中央値≈48h。",
         "本物の機会の後ほど遅れてFCCを計り直す。応答が72h以降にも続くため、168h窓が時間分解能で裏付けられる。",
         "本物の機会の後ほど遅れて計り直す。応答は72hを越えて続くので168h窓が時間分解能でも妥当。",
         accent=DGREEN)

s = D.section("根拠③ A3 アンカー汚染 — END起点は構造的に汚染ゼロ", DGREEN, "§4 根拠")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.2))
D.bullets(tf, [
    "汚染 = 計上した応答ステップのうち『満充電ENDより前』に起きた割合（充電途中の変化は応答ではなく充放電の一部）",
    "END起点: 両機構とも汚染 0.0（構造的性質）。起点をSTART/LOWにずらすと 0.45〜0.69 の過大計上",
    "Type B の帯入口(arm)起点の汚染は小さい（72h=0.072 / 168h=0.034）— エピソードが短いため",
    "★正直な注意: Type B の END重複帰属率=0.65。密な168h窓が重なり、1つの再学習ステップが複数エピソードに帰属する",
    "対処は first-step-only 帰属（1ステップは最初のエピソードにのみ帰属）。union は同時刻ENDの重複を約1.6pt緩和（§6）",
    "charge-termination(充電完了)アンカーは per-sample の電流/テーパ情報が無く NOT AVAILABLE。END を運用代理に使用"], size=12)
D.takeaway(s, "採点は満充電(END)の後から数えるので構造的に汚染ゼロ。ただしType Bは窓が重なりやすく重複帰属が課題(正直開示)。")
D.footer(s)

D.figure("根拠④ E 欠測ストレス — 提案検出器は誤無応答を~40x圧縮", "§4 根拠",
         "od2_missingness.png",
         "データ欠落/打ち切りを注入したとき、誤って『無応答』と確定する件数を naive と proposed(censor-aware) で比較。",
         "縦=平均の誤・確定無応答件数、機構別。赤=naive、緑=proposed(段階品質+censored除外)。",
         "union で naive 203.7 → proposed 5.0（約40x削減）。機会回収率は0.96を維持。censored/unknownを無応答に数えないのが効く。",
         "データの穴をそのまま『無応答』と数える素朴検出器は大量に冤罪を出すが、提案法はほぼ出さない（IC6成立）。",
         "データの穴をそのまま無応答と数えると大量に冤罪。提案法(censored除外)はほぼ冤罪を出さない。",
         accent=DGREEN)

D.figure("根拠⑤ D 有界保持 — 30日保持でも全履歴と等価", "§4 根拠",
         "od2_retention.png",
         "生データ保持を短くしたとき、無応答判定が全履歴と一致する度合いを、stateless と stateful で比較。",
         "縦=全履歴との一致度、横=生データ保持日数。緑=stateful(保持不問=1.0)、灰/赤=stateless。",
         "statefulは W=30日・168h窓で recall 1.0/重複0/MAE 0、容量比 0.0417(4.2%)。168h窓は最小7日の先読みが要る(<30日)ので30日保持で十分。",
         "生データを捨てても、最小状態の因果台帳で全履歴と同じ結論。stateless は7日保持だと168h窓を観測できず破綻する。",
         "レシートは30日で捨てても、少数項目の家計簿(最小状態台帳)があれば全履歴と同じ結論が出る。",
         accent=DGREEN)

s = D.section("5本柱まとめ — 本手法の技術効果", DGREEN, "§4 根拠")
D.make_table(s, ["柱", "検証", "技術効果（proxy非依存）", "判定"],
    [["A2", "負の対照", "真応答 A0.637/B0.368/union0.359 が各null外(4/4)", "✅ 両機構とも本物の刺激"],
     ["A3", "アンカー汚染", "END汚染 0.0（両機構）※Type B重複帰属0.65は開示", "✅ END無汚染"],
     ["B", "応答ハザード", "真CIF>>pseudo。応答は72hを越え168hで捕捉", "✅ 168h窓を裏付け"],
     ["E", "欠測ストレス", "誤無応答 naive204→proposed5(~40x)、回収0.96", "✅ IC6成立"],
     ["D", "有界保持", "stateful recall1.0/重複0/容量4.2%（30日保持で等価）", "✅ IC5成立"]],
    Inches(0.4), Inches(1.05), [0.8, 2.6, 6.6, 2.5], row_h=0.62, cell_size=10.5,
    styler=status_styler([3]))
D.takeaway(s, "5本柱すべて成立し、機会条件付き無応答監査は深放電・充電側の二機構で技術的に強く裏付けられる。")
D.footer(s)

# =========================================================================== #
# §5 patent candidates
# =========================================================================== #
s = D.section("特許候補の位置づけ（集約）", PURPLE, "§5 Part2")
D.make_table(s, ["特許候補", "手法段", "技術エビデンス", "新規性リスク(UNVERIFIED)"],
    [["① 機会条件付き無応答監査（二機構）", "1+2+3+4", "STRONG", "MEDIUM-HIGH"],
     ["  └ 新規性の核: 充電側部分再学習の検出", "(Type B)", "STRONG", "MEDIUM（要調査）"],
     ["② デュアルトラック非対称リセット", "dual-track", "STRONG", "HIGH（着想日依存）"],
     ["③ 有界保持の因果証拠台帳", "5", "STRONG", "MEDIUM-HIGH"],
     ["(将来④) クローズドループ介入検証", "介入後検証", "PROSPECTIVE", "—"],
     ["(将来⑤) 機種非依存+version局在", "原因局在", "MEDIUM/PROSP.", "MEDIUM"]],
    Inches(0.4), Inches(1.05), [5.6, 1.8, 2.4, 2.9], row_h=0.6, cell_size=10.5,
    styler=status_styler([2, 3]))
D.takeaway(s, "『技術エビデンスが強い』と『特許が取れる』は別軸。核心の新規性は『充電側部分再学習の無応答検出』にある。")
D.footer(s)

D.concept("候補① 機会条件付き無応答監査（二機構）", "§5 候補①",
          "STRONG", "MEDIUM-HIGH",
          "FCC再学習は学習機会でしか起きないが、機会有無と応答有無は静的検査で分離不能。実機の機会は Type A(深放電) と Type B(充電側) の2経路。",
          "凍結が『機会なし(正常/再較正)』か『機会あるのに無応答(FW/HW疑い)』か判別できない。",
          "欠測・打ち切り・機種依存に頑健で、かつ2機構を一つの枠組みで扱う必要がある。",
          "Type A/B の機会を抽出→満充電END起点168h窓で responded/no_response/censored 分類→品質ティア+censor除外→機構別k(A=3/B=5)で二分岐。",
          "A2特異性(両機構)・A3汚染0・E欠測耐性で実証。★新規性の核=『深放電を伴わない充電側部分再学習の無応答検出』＋『2機構を満充電ENDで統合』＋『機構別k・168h窓』。狭め/中位で出願推奨。",
          "『満充電の後に計り直さなかった』を、深放電と充電側の両方の機会について、欠測に騙されず数える監査。",
          accent=PURPLE)

D.concept("候補② デュアルトラック非対称リセット", "§5 候補②",
          "STRONG", "HIGH（着想日依存）",
          "量子化最小10mWh。micro(<50mWh)とeffective(≥50mWh)が混在。1系統だとmicroが未解決の無応答証拠を消しFW疑いを見逃す。",
          "microステップが effective系統の未解決『無応答』証拠を誤って消去してしまう。",
          "any系統(任意変化でリセット)とeffective系統(≥50mWhのみリセット)を分離し、microは any系統のみリセット(非対称)する必要。",
          "同時刻順序は complete<reset<deadline。microは any系統のみリセットし effective系統の無応答証拠は保持。",
          "【リスク高】production実装済（本パスは特徴付け/検証であり着想ではない）+ deadband は一般先行技術 → 新規性は着想日依存。要・着想日/公開有無の確認。",
          "微小なゆらぎで『まだ計り直していない』証拠を消さないよう、2つの帳簿を非対称に運用する。",
          accent=PURPLE)

D.concept("候補③ 有界保持下の因果証拠台帳", "§5 候補③",
          "STRONG", "MEDIUM-HIGH",
          "生テレメトリ保持は有界(例:30日)。窓をまたぐ機会の証拠が失われる/二重計上。",
          "168h窓は最小7日の先読みが要り、保持が短いと窓をまたぐ証拠が失われる（stateless 7日保持で一致0.011）。",
          "生データを捨てても、因果的にリプレイ可能な最小状態(FSM/pending期限/seen_ids/直近有効変化/gap-censor/順序規則)を永続化する必要。",
          "Type A の high-low-high FSM と Type B の WAIT/ARMED(充電) FSM を並置し、満充電ENDで統合・重複排除。期限は窓観測時のみ発火。",
          "Dグリッドで recall 1.0・重複0・MAE≈0 を保持比 0.0417(4.2%)で達成(rw=168h)。stateless は168h窓で破綻するため最小状態台帳の価値が明確。『最小状態構造』をクレーム核に。",
          "レシートは30日で捨てても、少数項目の家計簿(最小状態台帳)があれば全履歴と同じ結論。",
          accent=PURPLE)

s = D.section("将来候補（PROSPECTIVE — データは存在しない、捏造しない）", PURPLE, "§5 Part2")
tf = dc._tb(s, Inches(0.55), Inches(1.1), D.SW - Inches(1.1), Inches(4.6))
first = True
for head, body in [
    ("将来④ クローズドループ介入検証",
     "診断別介入(安全な較正/FW更新)後、最初のHIGH_OK機会から168h以内の有効応答を主要評価項目に。介入・versionデータは NOT AVAILABLE（power simulationとスキーマのみ）。"),
    ("将来⑤ 機種非依存スクリーニング + version局在",
     "分類は行動特徴のみ。分類後の記述統計でHW偏在を集計（分類には不使用）。BIOS/EC/FW version列 NOT AVAILABLE → PROSPECTIVE。"),
]:
    p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
    dc._set(p, "■ " + head, size=13.5, bold=True, color=PURPLE); p.space_before = Pt(8)
    q = tf.add_paragraph(); dc._set(q, body, size=12.5, color=INK)
D.takeaway(s, "介入効果とFW versionが取れれば『直したら本当に直った』まで示せる。今はデータが無いので将来候補として正直に留保。")
D.footer(s)

# =========================================================================== #
# §6 disclosure + IP + summary
# =========================================================================== #
s = D.section("正直な開示① — 必須の開示事項", RED, "§6 開示")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "Type B 重複帰属 0.65: 密な168h窓が重なり、1つの再学習ステップが複数エピソードに帰属。union dedupは同時刻ENDのみ緩和(約1.6pt) → first-step-only帰属で対処予定",
    "オンライン累積kの副作用: 確定信号がFW側に大きく振れる(FW_CORE 49・NORMAL 41)。Type Bのhealthy応答が0.45と低く累積で無応答が貯まる。全履歴の tail-scoped 版(FW 35)がより保守的 → tail-scope化/累積対応閾値が改善余地",
    "残差 ~9%: 監査窓を14日に広げても未説明のFCC更新(中央値260mWh=ノイズでない)が残る。第3の再学習経路 or 満充電END取りこぼし(conservationモード上限・ロガー寝過ごし)の可能性。46台はRSOC≥99に未到達",
    "charge-termination アンカー NOT AVAILABLE（per-sample電流/テーパ無し）。END を運用代理に使用（捏造しない）",
    "proxyラベルは地上真実でない / 先行技術は全て UNVERIFIED / 本資料は技術エビデンスであり法的意見ではない"], size=11.8)
D.takeaway(s, "強い結果ほど弱点を明示する。Type B重複帰属・online累積k・未説明残差の3点はクレーム設計と追加検証で対処する。")
D.footer(s)

s = D.section("正直な開示② — 限界と残課題", RED, "§6 開示")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "proxy一致は『FW確認対象の抽出』であって『FW不良の検出』ではない（確定診断ではない）",
    "END汚染0は定義から従う構造的性質（発見ではない）。MCAR極端条件では回収率が低下しうる",
    "充電側部分再学習の無応答検出（新規性の核）は正式な先行技術/特許性調査が未実施 → 弁理士による FTO/特許性調査が出願前必須",
    "候補②は production 実装済 → 新規性は着想日依存。社内外の公開有無の確認（新規性喪失の例外含む法務確認）が必要",
    "介入→FCC回復のクローズドループ実証データ・BIOS/EC/FW version は未取得（将来④⑤の前提）"], size=12)
D.takeaway(s, "エビデンスは強いが、特許性(新規性)判断・FTO・着想日確認はここから先が本番。データ未取得の主張は将来候補に留保。")
D.footer(s)

s = D.section("知財戦略オプション & reviewerへの依頼", RED, "§6 まとめ")
D.make_table(s, ["特許候補", "エビデンス", "新規性リスク", "出願準備度の目安"],
    [["① 無応答監査（二機構・中核）", "STRONG", "MEDIUM-HIGH", "出願候補(狭め/中位, 二機構明記)"],
     ["  └ 充電側部分再学習の検出", "STRONG", "MEDIUM(要調査)", "新規性調査を優先発注"],
     ["② 非対称リセット", "STRONG", "HIGH", "着想日要確認 or 防御的公開"],
     ["③ 因果証拠台帳", "STRONG", "MEDIUM-HIGH", "最小状態を核に出願候補"],
     ["(将来④⑤) 介入/version局在", "PROSPECTIVE", "—/MEDIUM", "継続/将来開示"]],
    Inches(0.4), Inches(1.02), [4.9, 1.9, 2.4, 3.5], row_h=0.58, cell_size=10.5,
    styler=status_styler([1, 2]))
tf = dc._tb(s, Inches(0.5), Inches(4.85), D.SW - Inches(1.0), Inches(1.4))
dc._set(tf.paragraphs[0], "reviewerへの依頼:", size=12.5, bold=True, color=RED)
D.bullets(tf, [
    "(1) 二機構クレームの粒度・範囲の判断（Type A+B を独立/従属どちらで組むか）",
    "(2) 『充電側部分再学習の無応答検出』の新規性・先行技術調査の発注判断",
    "(3) 候補②の着想日・社内外公開有無の確認  (4) Type B重複帰属・online累積k のクレーム上の扱い（除外/従属化）"],
    size=11.5, first=False)
D.takeaway(s, "出願・営業秘密・防御的公開の切り分けと、核心の新規性面（充電側検出）の調査発注がreviewerへの問い。")
D.footer(s)

# =========================================================================== #
# §7 appendix
# =========================================================================== #
D.features("付録A — 特徴量（raw と派生・HW識別子不使用）", "§7 付録",
    [["RSOC / FCC / cycleCount / chargeStatus / timestamp", "raw", "生入力（HW識別子は不使用）"],
     ["Type A エピソード(満充電→≤6%→満充電)", "派生", "high-low-high FSM (high=99, low=6)"],
     ["Type B エピソード(充電中60-80通過→満充電)", "派生", "WAIT/ARMED FSM (chargeStatus=1, 60-80帯, abort<60)"],
     ["有効ステップ(≥50mWh) / micro(<50mWh)", "派生", "|ΔFCC| 閾値。量子化最小10mWh"],
     ["応答ステータス(END後24/72/168h)", "派生", "responded/no_response/censored/unknown"],
     ["品質ティア / 最小状態台帳", "派生", "HIGH_OK/MEDIUM_GAP/LOW_LARGE_GAP / FSM+pending+seen_ids…"],
     ["BIOS/EC/FW version・介入", "NOT AVAIL", "本データに存在しない（NOT AVAILABLE）"]])

s = D.section("付録B — データと再現性", GREY, "§7 付録")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "母集団: 752ユーザー / 3,130,394 サンプル / PWMログ約30分間隔 / パック交換 0件",
    "学習機会: Type A 3,913(475人) / Type B 34,578(704人) / union(満充電END重複排除) 36,225。監査可能 687/752",
    "全て新規ファイルに出力（現行の本番コードは無変更）。ユニットテスト15件pass",
    "主要成果物: data/reports/fcc_relearn_od2_MASTER_report.md（総括）、data/processed/fcc_relearn_od2/・fcc_patent_evidence_od2/・fcc_online_od2/",
    "数値は proxy 非依存の独立エンドポイント。user-clustered bootstrap。決定的シード。PII匿名化。"], size=12)
D.takeaway(s, "全て新規ファイルで再現し、本番コードを壊さず並存する。数値は proxy 非依存の独立指標で検証済み。")
D.footer(s)

s = D.section("付録C — 代替実施形態 / 先行技術差別化（全件UNVERIFIED）", GREY, "§7 付録")
tf = dc._tb(s, Inches(0.55), Inches(1.02), Inches(6.2), Inches(4.8))
dc._set(tf.paragraphs[0], "代替実施形態:", size=12.5, bold=True, color=NAVY)
D.bullets(tf, [
    "満充電閾値 97/99/100%（既定99）",
    "Type A 深放電 4/6/8/10%（既定6）",
    "Type B 帯 55-80 / 60-80 / 60-85、abort 50/60",
    "応答窓 72/168/336h（主168h）",
    "有効ステップ 固定10-100mWh・容量比・適応式",
    "リセット規則・保持7-90日・ギャップ処理"], size=11.5, first=False)
tf2 = dc._tb(s, Inches(7.0), Inches(1.02), Inches(6.0), Inches(4.8))
dc._set(tf2.paragraphs[0], "先行技術差別化(UNVERIFIED):", size=12.5, bold=True, color=NAVY)
D.bullets(tf2, [
    "US7610172: 非発生イベント監視（充電側部分再学習の無応答は未教示）",
    "TI Impedance-Track US6832171: 機会=qualified discharge が前提（充電側部分再学習を教示しない）",
    "US20130085715 / US9218527: streaming窓（有界保持の最小状態台帳を教示しない）",
    "汎用deadband: micro/effectiveの非対称リセットを教示しない",
    "→ 二機構(特に充電側)の統合監査は差別化余地。要・弁理士による正式調査"], size=11.5, first=False)
D.takeaway(s, "先行技術は全て未検証(AI提示)。特にType B(充電側部分再学習)の差別化は正式なFTO/特許性調査で確定が必要。")
D.footer(s)

# 付録D — 判定閾値一覧
D.thresholds_slide("§7 付録")

# 付録E — 品質ティア＋censored除外（⑤の詳細）
D.quality_tier_slide("§7 付録")

# 付録F — 品質スコアの3成分（図解）
D.figure("付録 — 品質スコアの3成分（最大ギャップ / カバレッジ / 端点ギャップ）", "§7 付録",
         "od2_quality_components.png",
         "1つの学習機会の区間を RSOC 波形＋サンプル点(●)で示し、観測の“穴”の3つの見方を図示した模式図。",
         "縦=RSOC(%)、横=時間(h)。●=観測サンプル、赤帯=未観測の穴、灰破線=未観測区間の推定、START/LOW/END=機会のアンカー。",
         "①最大ギャップ=区間内の最大の穴（赤帯=20h） ②観測カバレッジ=“見えていた”時間の割合（赤帯の外） ③端点ギャップ=END等の境界付近の穴（小さいほど良い）。",
         "この例は中央に大穴があり①↓・②↓（LOWも未観測）だが、END付近は密で③↑。3成分を 0.45/0.35/0.20 で合成→score→ティア判定。",
         "観測の“穴”を『最悪の大きさ①／全体の密度②／境界の精度③』の3面で評価し、信頼できる機会だけを数える。",
         accent=GREY)

# =========================================================================== #
n = D.save()
print(f"summary deck (2-mechanism, no legacy definition): {n} slides")
