#!/usr/bin/env python
"""新定義 patent-review summary deck (.pptx) — successor to fcc_patent_summary_slides_v5.

Same visual grammar as build_v5_pptx.py (via od2_deck_common.Deck), refreshed for the
corrected DUAL-MECHANISM relearn definition (Type A deep-discharge / Type B charge-side),
the 168h primary window, the 5-pillar 新定義 evidence, and the dual-mechanism patent framing.

Numbers traceable to data/reports/fcc_relearn_od2_MASTER_report.md (verified). Figures from
data/reports/figures/fcc_relearn_od2/. NOT a legal opinion / prior art UNVERIFIED /
intervention+FW-version data NOT AVAILABLE / proxy labels / no fabrication.
"""
from __future__ import annotations
import sys
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from pptx.util import Inches, Pt
from pptx.enum.dml import MSO_LINE_DASH_STYLE as MSO_LINE
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
    "FCC再学習の『二機構』化と、機会条件付き無応答判定技術（学習機会の定義を刷新した改訂版）",
    "— 学習機会の定義を実機の再学習ロジックに合わせて刷新した再解析 —（社内 patent review 用）",
    ["★用語: 本資料の『旧定義』＝従来の学習機会（RSOC 80→20→80%の放電往復）／『新定義』＝実機の2機構（Type A・Type B）。以降この2語で対比する",
     "本題: 燃料計がFCCを再学習する『機会』を、実機の2機構で定義し直して凍結判定を再構築した",
     "訂正: 機会は放電band(80/20/80)ではなく Type A(満充電→RSOC≤6%→満充電) と Type B(充電中に60-80%通過→満充電)",
     "母集団: 実バッテリ履歴 752ユーザー / 3,130,394 サンプル。主応答窓は 72h→168h に是正",
     "核心: 両機構とも敵対的な負の対照を独立にパス → 発明は保存かつ『二機構』へ拡張",
     "全て新規 od2 ファイルで再現。現行旧定義版は無変更。技術効果は proxy 非依存指標で検証・法的結論なし"])

# =========================================================================== #
# 2. Executive summary
# =========================================================================== #
s = D.section("エグゼクティブサマリ — 1枚で全体像（新定義）", NAVY, "Summary")
tf = dc._tb(s, Inches(0.55), Inches(1.02), D.SW - Inches(1.1), Inches(5.3))
first = True
for head, body in [
    ("★用語（旧定義 / 新定義）", "本資料の『旧定義』＝従来の学習機会（RSOC 80→20→80%の放電往復）。『新定義』＝実機の2機構。"
                 "FCC再学習の学習機会を実機ロジックに合わせ2機構に再定義: Type A=満充電→深放電(RSOC≤6%)→満充電、"
                 "Type B=充電中にRSOC 60-80%帯を通過して満充電。両者とも END=満充電到達。応答窓は72h→168hへ是正。"),
    ("なぜ168hか", "実FCC更新のうち Type A/B の機会で説明できる割合は 72h=69% → 7日=86% → 14日=91%。"
                 "真の再学習レイテンシは72hより長く、旧72h窓は本物の応答を過小評価していた。"),
    ("核心の実証", "敵対的な負の対照(A2)で、真の応答確率が各機構『自分専用のニセ機会null』を超える: Type A 0.637 / Type B 0.368 / "
                 "union 0.359（各4/4でnull外・4/4方向一致）。★充電側Type Bも本物の学習刺激。5本柱(A2/A3/B/E/D)すべて成立。"),
    ("運用への影響", "『機会が多い』ため『機会不足→ゲージリセット』が縮小し『機会あるのに無応答→FW確認』が拡大: "
                 "オフライン FW 14→35・GAUGE 18→10、オンライン9段 FW_CORE 5→49・GAUGE_CORE 4→0・NORMAL 183→41。"),
    ("特許候補", "①機会条件付きEND起点168h無応答監査（★二機構へ拡張）②デュアルトラック非対称リセット ③有界保持の因果証拠台帳。"
                 "新規性の核心は『深放電を伴わない充電側部分再学習の検出』と『二機構を満充電ENDで統合＋機構別k較正』。"),
    ("reviewerへの依頼", "(1)二機構クレームの粒度・範囲 (2)充電側検出の新規性/先行技術調査の発注 (3)候補②の着想日確認 "
                 "(4)Type B重複帰属・online累積kの扱い（クレーム除外/従属化）判断"),
]:
    p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
    dc._set(p, "■ " + head, size=13, bold=True, color=NAVY); p.space_before = Pt(5)
    q = tf.add_paragraph(); dc._set(q, body, size=11.3, color=INK)
D.takeaway(s, "『動くべき機会に動かなかった』を数える監査を、実機の2つの再学習経路に合わせて作り直したら、発明はむしろ広がった。")
D.footer(s)

# =========================================================================== #
# 3. Guide
# =========================================================================== #
s = D.section("本資料の構成と読み方（新定義）", NAVY, "Guide")
parts = [
    ("§1 基礎知識", "燃料計/FCC・RSOC・SoH / FCC再学習の2機構 / なぜ問題か", STEEL, "非エンジニアはここから"),
    ("§2 用語定義", "バッテリ・学習機会(2機構) / 検証手法・統計", STEEL, "つまずいたら戻る辞書"),
    ("§3 本題(Part1)", "目的 → 失敗と発想転換 → ★機会定義の訂正 → 手法 → 実フリート結果", NAVY, "判定技術そのもの"),
    ("§4 根拠", "5本柱 A2/A3/B/E/D（図解説つき）+ 旧定義 vs 新定義 スコアボード", DGREEN, "なぜ信じてよいか"),
    ("§5 特許候補(Part2)", "候補①〜③（二機構拡張）+ 新規性の核心 + 将来④⑤", PURPLE, "reviewer判断の対象"),
    ("§6 開示とまとめ", "正直な開示 / 知財戦略 / 依頼事項", RED, "リスクと残課題"),
    ("§7 付録", "特徴量 / データと再現性 / 代替実施形態 / 先行技術差別化", GREY, "深掘り用"),
]
y = Inches(1.1)
for name, desc, col, note in parts:
    D.box(s, Inches(0.5), y, Inches(2.7), Inches(0.6), name, col, size=12)
    D.label(s, Inches(3.4), y + Inches(0.03), Inches(6.1), Inches(0.6), desc, size=11.5, color=INK)
    D.label(s, Inches(9.7), y + Inches(0.03), Inches(3.3), Inches(0.6), note, size=10.5, color=GREY)
    y += Inches(0.7)
tf = dc._tb(s, Inches(0.5), y + Inches(0.05), D.SW - Inches(1.0), Inches(0.9))
dc._set(tf.paragraphs[0], "急ぐ方は スライド 2→11→13→18→31 の5枚で概観できます。図スライドは4ブロック"
        "（何のグラフ/軸/主張/読み方）構成。各スライド下部の黄色帯（💡）は一言要約。", size=11.5, color=INK)
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

# basics② — the two mechanisms (with diagram figure)
D.figure("基礎② FCC再学習の『2つの機構』 — ここが今回の訂正の核心", "§1 基礎知識",
         "od2_mechanism_diagram.png",
         "実機のFCC再学習が起きる2つの充放電パターンをRSOC波形で示す模式図（左=Type A / 右=Type B）。",
         "縦=RSOC(%)、横=時間。緑破線=満充電(≥99%)、赤帯=深放電(≤6%)、橙帯=充電側の60-80%通過帯。",
         "旧定義(80/20/80の放電往復)は不正確。実機は Type A(満充電→≤6%→満充電) と Type B(充電中に60-80%を通過→満充電) の2経路で再学習する。",
         "どちらも END=満充電到達で完了 → END起点で応答を監査すれば一つの枠組みで両機構を扱える。",
         "凍結の結果は同じでも『再学習のきっかけ』は2種類。旧定義は片方(放電往復)しか見ておらず取りこぼしていた。",
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
    ("k(FW閾値)", "FW確認へ回す無応答回数の下限。機構別に再正当化: Type A=3 / Type B=5（healthy応答率 0.74/0.45 と (1-p)^k≤0.05 から）。"),
    ("proxyラベル", "本番システムの出力を仮の正解としたもの（地上真実ではない）。"),
], tag="§2 用語定義")

# =========================================================================== #
# §3 Part1
# =========================================================================== #
s = D.section("本来の目的と、なぜ難しいか", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.1), D.SW - Inches(1.1), Inches(2.0))
dc._set(tf.paragraphs[0], "目的: テレメトリだけからゲージ凍結個体をフリート規模で正しく判定する。", size=14, bold=True, color=NAVY)
tf2 = dc._tb(s, Inches(0.55), Inches(1.9), D.SW - Inches(1.1), Inches(4.0))
D.bullets(tf2, [
    "静的検査では『浅充放電で正常』『要再較正』『FW/HW起因』を区別できない",
    "欠測・睡眠ギャップ・打ち切り: データの穴を『無応答』と誤判定しやすい",
    "生データ保持が有界（直近30日等）で過去の証拠が失われる",
    "機種非依存が必須（機種名ハードコードは過学習）",
    "★そして本質的問題: そもそも『学習機会』の定義が実機の再学習ロジックと合っていなければ全てが崩れる"], size=13)
D.takeaway(s, "『FCCが動かない』結果は同じでも原因は複数。まず『どういう時に再学習するのか』を実機どおり定義することが出発点。")
D.footer(s)

s = D.section("失敗した素朴アプローチ → 発想の転換", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.1), D.SW - Inches(1.1), Inches(4.6))
D.bullets(tf, [
    "教師あり予測(33特徴量, 公平比較領域 obs≥180d): AUC 0.535/0.540 — ほぼコイン投げ",
    "FCC履歴を除いた規範ML: AUC 0.5584 — near-random。最重要特徴 min_rsoc は『深放電ほど凍結』の反usage交絡",
    "→ 発想転換: 『凍結を当てる』のではなく『再学習“機会”に対し実際に応答したかを機械的に監査する』(決定論カウンタ)",
    "この監査は、機会の定義が正しければ機種非依存・欠測頑健・有界保持で全期間等価に作れる"], size=13)
D.takeaway(s, "壊れそうかをAIに予言させるのは失敗(コイン投げ並み)。『チャンスに応えたか』を出席簿のように数える方式に切替えたら解ける。")
D.footer(s)

# ★ the correction (with diagram)
D.figure("★機会定義の訂正 — 放電band(80/20/80) から 実機の2機構へ", "§3 Part1",
         "od2_mechanism_diagram.png",
         "旧旧定義(放電往復)と新新定義(2機構)の学習機会の違い。左=Type A 深放電、右=Type B 充電側。",
         "旧: RSOC 80→20→80 の放電往復を機会とした（不正確）。新: Type A(99→≤6→99) と Type B(充電中60-80通過→99)。",
         "実機のFCC再学習は放電往復ではなく、深放電フルサイクル(A) と 充電側の部分再学習(B) の2経路。両者を満充電ENDで統合。",
         "旧定義 primary 11,342機会/598人 は完全再現（手法検証済）。新定義では Type A 3,913/475人・Type B 34,578/704人（放電bandの約3倍）。",
         "実機どおりに定義し直すと、監査できる機会が大幅に増え、特に充電側(B)が主役になる。",
         accent=NAVY)

s = D.section("提案手法の全体像（新定義）", NAVY, "§3 Part1")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(0.5))
dc._set(tf.paragraphs[0], "入力: RSOC / FCC / cycleCount / chargeStatus / timestamp のみ（HW識別子は不使用）。", size=12.5, bold=True, color=NAVY)
tf2 = dc._tb(s, Inches(0.55), Inches(1.55), D.SW - Inches(1.1), Inches(4.4))
D.bullets(tf2, [
    "1. 学習機会の抽出（Type A: 満充電→≤6%→満充電 / Type B: 充電中に60-80%通過→満充電）",
    "2. END起点で応答監査（END後168h窓の有効ステップ≥50mWh）※窓を72h→168hに是正",
    "3. 欠測/打ち切り耐性（段階品質ティア＋censored除外）",
    "4. 二分岐トリアージ（機会反復×無応答→FW / 機会皆無→ゲージ再較正）＋機構別k較正(A=3/B=5)",
    "5. 有界保持で証拠保全（最小状態の因果台帳、30日保持で全期間等価）"], size=13)
D.box(s, Inches(0.55), Inches(5.95), D.SW - Inches(1.1), Inches(0.42),
      "対応: ①(手順1+2+3+4) / ②(dual-track) / ③(手順5)。新規性の核心は『2機構＋満充電END統合＋機構別k・168h窓』。",
      LIGHT, fg=NAVY, size=11)
D.footer(s)

# attribution / latency figure
D.figure("再学習レイテンシは72hより長い → 主応答窓を168hに是正", "§3 Part1",
         "od2_attribution_window.png",
         "実際のFCC更新のうち、直前にType A/Bの機会ENDがある割合を、監査窓の幅ごとに示す。",
         "縦=説明できたFCC更新の割合(%)、横=応答窓(h)。灰点線=旧72h、緑破線=新定義主窓168h。",
         "72hでは69%しか説明できないが、7日(168h)で86%、14日で91%。ゲージは満充電の数日後にFCCを書くことが多い。",
         "旧72h窓は本物の応答を過小評価し無応答を過大計上していた。168hが実機のレイテンシに整合する。",
         "満充電の後どれだけFCCを計り直したかを数える監査。その締切は72hでは早すぎ、7日(168h)が実機どおり。",
         accent=DGREEN)

# mechanism strength
D.figure("2機構の『強度』の違い — 深放電は強い、充電側は高頻度だが弱い", "§3 Part1",
         "od2_mechanism_strength.png",
         "健全な(active-reference)ゲージが、各機構の機会に168h以内で応答する割合。",
         "縦=健全機の応答率@168h、棒上=FW確認へ回す無応答回数の閾値k。",
         "Type A=0.74(強い深放電トリガ, k=3)、Type B=0.45(高頻度だが弱い充電側トリガ, k=5)。旧primaryのk=3は強トリガ向けの較正。",
         "機構ごとに『健全でも応答しない率』が違うため、FW判定のkを機構別に較正する必要がある（Type Bは高めのk=5）。",
         "同じ『無応答』でも深放電(強)と充電側(弱)で健全機の応答率が違う。だからFW閾値kを機構別に較正する。",
         accent=STEEL)

# coverage
D.figure("機会カバレッジが倍増 — 充電側(Type B)が非常に多い", "§3 Part1",
         "od2_coverage.png",
         "OKクオリティの学習機会を1回以上持つユーザー数（監査可能なユーザー）を 旧定義 と 新定義 で比較。",
         "縦=監査可能ユーザー数、灰=旧定義(80/20/80)、緑=新定義(Type A+B)、点線=コホート752人。",
         "294→687人に倍増。Type B(充電側)が遍在するため。機会が全く無い『ゲージ候補』は46人まで縮小。",
         "実機どおりに定義すると、ほとんどの端末が何らかの充電側機会を持つ → 『機会不足』の解釈は激減する。",
         "実機どおりの2機構で数えると監査できる端末が倍増し、充電側(Type B)が主役になる。",
         accent=DGREEN)

# offline triage
D.figure("実フリート結果① オフライン再トリアージ — FW確認が拡大", "§3 Part1",
         "od2_triage_offline.png",
         "全履歴監査の最終トリアージ(FW確認 / ゲージリセット / WATCH)を 旧定義 と 新定義 で比較。",
         "縦=ユーザー数、灰=旧定義(72h)、青=新定義(168h・機構別k)。REVIEW 338/NORMAL 327 は機会非依存で不変。",
         "FW確認 14→35、ゲージリセット 18→10、WATCH 55→42。旧WATCH 55→FW 19/GAUGE 4/WATCH 32、旧GAUGE 18→FW 3/WATCH 10。",
         "充電側機会が多いので『機会不足→ゲージ』が減り『機会あるのに無応答→FW確認』が増える、という定性シフト。",
         "充電側の機会が多いので『機会不足でゲージ較正』は減り、『機会に無応答でFW確認』が増える。",
         accent=DGREEN)

# online tiers
D.figure("実フリート結果② オンライン9段検出 — さらに顕著にFW側へ", "§3 Part1",
         "od2_online_tiers.png",
         "30日オンライン運用版の9段ラベルを 旧定義(rolling30-v2) と 新定義 で比較。",
         "横=ユーザー数、灰=旧定義、青=新定義。REVIEW_DQは同数(325)。",
         "FW_CORE 5→49、FW_WATCH 43→99、GAUGE_CORE 4→0、NORMAL 183→41。状態繰越の検出増 +29→+73。",
         "Type B機会がほぼ毎窓あるため『機会なし=ゲージ』が消滅。信号はFW側へ集中（累積kの副作用は§6で正直に開示）。",
         "オンラインでも同じ方向だがより顕著。ゲージ判定は消え、信号はFW側へ集中する（累積kは§6で開示）。",
         accent=DGREEN)

# =========================================================================== #
# §4 five pillars
# =========================================================================== #
s = D.section("判定法が機能する根拠 — 5本柱（新定義, 機構別）", DGREEN, "§4 根拠")
D.make_table(s, ["根拠", "検証", "新定義 主張", "ひとことで"],
    [["A2", "負の対照(ニセ機会4種)", "真 A0.637/B0.368/union0.359 が各null外(4/4)", "プラセボでは効かず本物でだけ効く（両機構）"],
     ["A3", "応答起点の比較", "END汚染0(両機構) / Type A START0.689・LOW0.455", "採点はテスト後(満充電)から"],
     ["B", "応答ハザード(CIF)", "真CIF>>pseudo・分離が72h→168hで増大", "本物の機会の後ほど遅れて計り直す"],
     ["E", "欠測・打ち切り注入", "誤無応答 naive204→proposed5(~40x)・回収0.96", "データの穴を冤罪にしない"],
     ["D", "保持グリッド7〜90日", "stateful recall1.0/重複0・容量4.2%(@168h)", "30日のメモで全履歴と同じ結論"]],
    Inches(0.4), Inches(1.05), [0.8, 3.0, 5.9, 3.0], row_h=0.62, cell_size=10.5)
tf = dc._tb(s, Inches(0.5), Inches(5.2), D.SW - Inches(1.0), Inches(1.1))
dc._set(tf.paragraphs[0], "いずれも proxy 非依存の独立エンドポイント。user-clustered bootstrap。各機構(Type A/Type B/union)で個別に検証。",
        size=12, color=INK)
D.takeaway(s, "5本柱すべて 新定義 でも成立。特に A2 で『充電側 Type B も本物の学習刺激』であることが決定的に示された。")
D.footer(s)

D.figure("根拠① A2 負の対照 — 両機構が『自分専用のnull』を超える", "§4 根拠",
         "od2_negative_control_by_mechanism.png",
         "真の応答確率(赤線)と、機会と応答の対応を壊した4種のニセ機会null(灰棒)を、機構別に比較(168h)。",
         "縦=END起点の有効応答確率@168h、横=4つの負の対照。赤線=真値。左=Type A/中=Type B/右=union。",
         "Type A 0.637 / Type B 0.368 / union 0.359 がいずれも自分専用null(0.18〜0.53)の95%上端を超える(各4/4・4/4方向一致→SUPPORTED)。",
         "★Type Bは72hでは0.265(≈旧null)だが168hで0.368に上がり自分のnullを明確に超える → 充電側は背景充電でなく本物の刺激。",
         "プラセボ(ニセ機会)では効かず本物の機会でだけ効く。★充電側Type Bも本物の学習刺激だと確定した。",
         accent=DGREEN)

D.figure("根拠② B 応答ハザード — 分離が72hを越えて増大", "§4 根拠",
         "od2_response_hazard_by_mechanism.png",
         "END後の累積応答率(CIF)を、真の機会(赤)と matched-pseudo(灰破線)で、機構別に時間軸で示す。",
         "縦=累積応答率(CIF)、横=END後経過時間(h)。灰点線=72h、緑破線=168h。",
         "真CIFは常に pseudo を上回り、差は72h→168hで増大: Type A +0.16→+0.28、Type B +0.11→+0.13。応答中央値≈48h。",
         "本物の機会の後ほど遅れてFCCを計り直す。応答が72h以降にも続くため、168h窓が妥当と時間分解能で裏付けられる。",
         "本物の機会の後ほど遅れて計り直す。応答は72hを越えて続くので168h窓が時間分解能でも妥当。",
         accent=DGREEN)

s = D.section("根拠③ A3 アンカー汚染 — END起点は構造的に汚染ゼロ", DGREEN, "§4 根拠")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.2))
D.bullets(tf, [
    "汚染 = 計上した応答ステップのうち『満充電ENDより前』に起きた割合（充電途中の変化は応答ではなく充放電の一部）",
    "END起点: 両機構とも汚染 0.0（構造的性質）。Type A START=0.689・LOW=0.455（起点をずらすと過大計上）",
    "Type B の arm(帯入口)起点の汚染は小さい（72h=0.072 / 168h=0.034）— エピソードが短いため",
    "★正直な注意: Type B の END重複帰属率=0.65。密な168h窓が重なり、1つの再学習ステップが複数エピソードに帰属する",
    "union dedup は機構間の同時ENDのみ緩和(約1.6pt)。機構内の重なりは残る → 対処は first-step-only 帰属（§6）",
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

D.figure("根拠⑤ D 有界保持 — 30日保持でも全履歴と等価（168h窓で再確認）", "§4 根拠",
         "od2_retention.png",
         "生データ保持を短くしたとき、無応答判定が全履歴と一致する度合いを、stateless(rw=72h/168h)と stateful で比較。",
         "縦=全履歴との一致度、横=生データ保持日数。緑=stateful(保持不問=1.0)、灰/赤=stateless(72h/168h)。",
         "stateful は W=30d・rw=168h で recall 1.0/重複0/MAE 0、容量比 0.0417。stateless は7日保持だと168h窓を観測できず破綻(一致0.011)。",
         "168h窓では最小7日の先読みが要る(<30日)ので30日保持は妥当。ただし stateless では成立せず、最小状態台帳が一層効く。",
         "レシートは30日で捨てても、少数項目の家計簿(最小状態台帳)があれば全履歴と同じ結論。168h窓では一層効く。",
         accent=DGREEN)

s = D.section("旧定義 → 新定義 スコアボード（5本柱＋運用）", DGREEN, "§4 根拠")
D.make_table(s, ["項目", "旧定義", "新定義", "判定"],
    [["A2 負の対照(真 vs null)", "0.39 vs 0.25", "A0.637/B0.368/union0.359 各4/4 null外", "✅ 両機構とも本物"],
     ["A3 END汚染", "0.0 (START0.557)", "0.0 両機構 (Type B重複帰属0.65)", "✅ END無汚染"],
     ["B 応答ハザード", "0.39 vs 0.29 @72h", "真CIF>>pseudo, 分離72h→168hで増大", "✅ 168h裏付け"],
     ["E 欠測(naive→proposed)", "643 → 4.1", "union 204 → 5.0 (~40x), 回収0.96", "✅ IC6成立"],
     ["D 保持(recall/重複/容量)", "1.0/0/0.0417 @72h", "1.0/0/0.0417 @168h・W30d", "✅ IC5成立"],
     ["オフライン FW/GAUGE", "14 / 18", "35 / 10", "FW拡大・GAUGE縮小"],
     ["オンライン FW_CORE/GAUGE_CORE", "5 / 4", "49 / 0", "信号がFW側へ"]],
    Inches(0.4), Inches(1.02), [3.6, 2.5, 4.7, 1.9], row_h=0.6, cell_size=10.5,
    styler=status_styler([3]))
D.takeaway(s, "5本柱すべて修正定義下でも成立。結論=発明は保存され、むしろ二機構へ拡張された。")
D.footer(s)

# =========================================================================== #
# §5 patent candidates
# =========================================================================== #
s = D.section("特許候補の位置づけ（新定義・集約）", PURPLE, "§5 Part2")
D.make_table(s, ["特許候補", "手法段", "技術エビデンス", "新規性リスク(UNVERIFIED)"],
    [["① 機会条件付き無応答監査（★二機構へ拡張）", "1+2+3+4", "STRONG", "MEDIUM-HIGH"],
     ["  └ 新規性の核心: 充電側部分再学習の無応答検出", "(Type B)", "STRONG", "MEDIUM（要調査）"],
     ["② デュアルトラック非対称リセット", "dual-track", "STRONG", "HIGH（着想日依存）"],
     ["③ 有界保持の因果証拠台帳（168hで再確認）", "5", "STRONG", "MEDIUM-HIGH"],
     ["(将来④) クローズドループ介入検証", "介入後検証", "PROSPECTIVE", "—"],
     ["(将来⑤) 機種非依存+version局在", "原因局在", "MEDIUM/PROSP.", "MEDIUM"]],
    Inches(0.4), Inches(1.05), [5.6, 1.8, 2.4, 2.9], row_h=0.6, cell_size=10.5,
    styler=status_styler([2, 3]))
D.takeaway(s, "『技術エビデンスが強い』と『特許が取れる』は別軸。新定義で新たに『充電側部分再学習の検出』という新規性の核が加わった。")
D.footer(s)

D.concept("候補① 機会条件付き無応答監査（★二機構へ拡張）", "§5 候補①",
          "STRONG", "MEDIUM-HIGH",
          "FCC再学習は学習機会でしか起きないが、機会有無と応答有無は静的検査で分離不能。実機の機会は Type A(深放電) と Type B(充電側) の2経路。",
          "凍結が『機会なし(正常/再較正)』か『機会あるのに無応答(FW/HW疑い)』か判別できない。旧定義は放電往復しか見ず取りこぼしていた。",
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

D.concept("候補③ 有界保持下の因果証拠台帳（168hで再確認）", "§5 候補③",
          "STRONG", "MEDIUM-HIGH",
          "生テレメトリ保持は有界(例:30日)。窓をまたぐ機会の証拠が失われる/二重計上。",
          "168h窓は最小7日の先読みが要り、保持が短いと窓をまたぐ証拠が失われる（stateless 7日で一致0.011）。",
          "生データを捨てても、因果的にリプレイ可能な最小状態(FSM/pending期限/seen_ids/直近有効変化/gap-censor/順序規則)を永続化する必要。",
          "Type A の high-low-high FSM と Type B の WAIT/ARMED(充電) FSM を並置し、満充電ENDで統合・重複排除。期限は窓観測時のみ発火。",
          "Dグリッドで recall 1.0・重複0・MAE≈0 を保持比 0.0417(4.2%)で達成(rw=168h)。stateless は168hで破綻するため最小状態台帳の価値が旧定義より一層明確。『最小状態構造』をクレーム核に。",
          "レシートは30日で捨てても、少数の項目の家計簿があれば全履歴と同じ結論。168h窓ではこの台帳が一層効く。",
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
s = D.section("正直な開示① — 新定義で新たに必要な開示", RED, "§6 開示")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "Type B 重複帰属 0.65: 密な168h窓が重なり、1つの再学習ステップが複数エピソードに帰属。union dedupは機構間のみ緩和(約1.6pt) → first-step-only帰属で対処予定",
    "オンライン累積kの副作用: NORMAL 183→41 に崩壊、FW_CORE=49(中央値43無応答)。Type Bのhealthy応答が0.45と低く累積で無応答が貯まる。オフラインの tail-scoped FW=35 が保守的 → tail-scope化/累積対応閾値が改善余地",
    "残差 ~9%: 14日でも未説明のFCC更新(中央値260mWh=ノイズでない)。第3の再学習経路 or 満充電END取りこぼし(conservationモード上限・ロガー寝過ごし)の可能性。46人はRSOC≥99に未到達",
    "charge-termination アンカー NOT AVAILABLE（per-sample電流/テーパ無し）。END を運用代理に使用（捏造しない）",
    "proxyラベルは地上真実でない / 先行技術は全て UNVERIFIED / 本資料は技術エビデンスであり法的意見ではない"], size=11.8)
D.takeaway(s, "強い結果ほど弱点を明示する。Type B重複帰属・online累積k・未説明残差の3点はクレーム設計と追加検証で対処する。")
D.footer(s)

s = D.section("正直な開示② — 限界と残課題", RED, "§6 開示")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "proxy一致は『FW確認対象の抽出』であって『FW不良の検出』ではない（確定診断ではない）",
    "END汚染0は定義から従う構造的性質（発見ではない）。MCAR極端条件では回収率が低下しうる",
    "Type B の新規性（充電側部分再学習の無応答検出）は正式な先行技術/特許性調査が未実施 → 弁理士による FTO/特許性調査が出願前必須",
    "候補②は production 実装済 → 新規性は着想日依存。社内外の公開有無の確認（新規性喪失の例外含む法務確認）が必要",
    "介入→FCC回復のクローズドループ実証データ・BIOS/EC/FW version は未取得（将来④⑤の前提）"], size=12)
D.takeaway(s, "エビデンスは強いが、特許性(新規性)判断・FTO・着想日確認はここから先が本番。データ未取得の主張は将来候補に留保。")
D.footer(s)

s = D.section("知財戦略オプション & reviewerへの依頼（新定義）", RED, "§6 まとめ")
D.make_table(s, ["特許候補", "エビデンス", "新規性リスク", "出願準備度の目安"],
    [["① 無応答監査（二機構・中核）", "STRONG", "MEDIUM-HIGH", "出願候補(狭め/中位, 二機構明記)"],
     ["  └ 充電側部分再学習の検出", "STRONG", "MEDIUM(要調査)", "新規性調査を優先発注"],
     ["② 非対称リセット", "STRONG", "HIGH", "着想日要確認 or 防御的公開"],
     ["③ 因果証拠台帳（168h再確認）", "STRONG", "MEDIUM-HIGH", "最小状態を核に出願候補"],
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
D.takeaway(s, "出願・営業秘密・防御的公開の切り分けと、二機構化で増えた新規性面（充電側検出）の調査発注がreviewerへの問い。")
D.footer(s)

# =========================================================================== #
# §7 appendix
# =========================================================================== #
D.features("付録A — 特徴量（raw と派生・HW識別子不使用）", "§7 付録",
    [["RSOC / FCC / cycleCount / chargeStatus / timestamp", dc.__dict__.get("RAW", "raw"),
      "生入力（HW識別子は不使用）"],
     ["Type A エピソード(満充電→≤6%→満充電)", "派生", "high-low-high FSM (high=99, low=6)"],
     ["Type B エピソード(充電中60-80通過→満充電)", "派生", "WAIT/ARMED FSM (chargeStatus=1, 60-80帯, abort<60)"],
     ["有効ステップ(≥50mWh) / micro(<50mWh)", "派生", "|ΔFCC| 閾値。量子化最小10mWh"],
     ["応答ステータス(END後24/72/168h)", "派生", "responded/no_response/censored/unknown"],
     ["品質ティア / 最小状態台帳", "派生", "HIGH_OK/MEDIUM_GAP/LOW_LARGE_GAP / FSM+pending+seen_ids…"],
     ["BIOS/EC/FW version・介入", "NOT AVAIL", "本データに存在しない（NOT AVAILABLE）"]])

s = D.section("付録B — データと再現性（新定義）", GREY, "§7 付録")
tf = dc._tb(s, Inches(0.55), Inches(1.05), D.SW - Inches(1.1), Inches(4.7))
D.bullets(tf, [
    "母集団: 752ユーザー / 3,130,394 サンプル / PWMログ約30分間隔 / パック交換 0件",
    "機会数: Type A 3,913(475人) / Type B 34,578(704人) / union 36,225。旧定義 primary 11,342/598人 を完全再現(手法検証)",
    "全て新規 od2 ファイルに出力（現行旧定義版 build_v5_pptx.py 等は無変更）。新定義ユニットテスト15件pass",
    "主要成果物: data/reports/fcc_relearn_od2_MASTER_report.md（総括）、data/processed/fcc_relearn_od2/・fcc_patent_evidence_od2/・fcc_online_od2/",
    "数値は proxy 非依存の独立エンドポイント。user-clustered bootstrap。決定的シード。PII匿名化。"], size=12)
D.takeaway(s, "手法は旧定義で完全再現できることを確認済み。新定義は全て新規ファイルで、現行版を壊さず並存する。")
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

# =========================================================================== #
n = D.save()
print(f"新定義 summary deck: {n} slides")
