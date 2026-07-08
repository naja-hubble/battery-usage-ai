"""Shared slide primitives for the OD2 patent-review decks (mirrors build_v5_pptx.py).

A ``Deck`` wraps a python-pptx Presentation and exposes the exact visual grammar of the
OD1 v5 deck — section band, 💡 takeaway band, boxes, connectors, tables, glossary, the
patent-candidate ``concept`` slide (背景/問題/課題/解決法/特許性), the 4-block ``figure``
slide (何のグラフ/軸/主張/読み方), and the honesty footer — so the OD2 decks look identical
to the originals. 16:9, Meiryo UI with CJK run wiring.
"""
from __future__ import annotations

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE as MSO_LINE
from pptx.oxml.ns import qn

# ---- palette (identical to build_v5_pptx.py) ----
NAVY = RGBColor(0x1F, 0x37, 0x5B); BLUE = RGBColor(0x1F, 0x77, 0xB4)
STEEL = RGBColor(0x33, 0x66, 0x99); GREY = RGBColor(0x55, 0x55, 0x55)
RED = RGBColor(0xC0, 0x39, 0x2B); GREEN = RGBColor(0x2C, 0xA0, 0x2C)
DGREEN = RGBColor(0x37, 0x6B, 0x3A); WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xEE, 0xF2, 0xF7); ORANGE = RGBColor(0xB0, 0x5A, 0x00)
TEAL = RGBColor(0x2E, 0x6E, 0x6A); PURPLE = RGBColor(0x6A, 0x3D, 0x8A)
BROWN = RGBColor(0x6B, 0x4A, 0x1F); INK = RGBColor(0x22, 0x22, 0x22)
YELLOW_BG = RGBColor(0xFF, 0xF6, 0xDA); YELLOW_LN = RGBColor(0xD9, 0xA4, 0x2A)
LGREEN_BG = RGBColor(0xE4, 0xF0, 0xE4); LBLUE_BG = RGBColor(0xE2, 0xEC, 0xF7)
LRED_BG = RGBColor(0xF7, 0xE4, 0xE2); LGREY_BG = RGBColor(0xEC, 0xEC, 0xEC)

FONT = "Meiryo UI"
DISC = ("技術的特許性エビデンス（NOT a legal opinion）。先行技術は UNVERIFIED。"
        "特許化の粒度・範囲の最終判断は社内reviewer/弁理士。捏造（地上真実/介入/FW/因果結論）なし。")


def EM(v):
    return Emu(int(round(v)))


def _cjk(run):
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {}); rPr.append(e)
        e.set("typeface", FONT)


def _style(run, size=14, bold=False, color=None):
    run.font.size = Pt(size); run.font.bold = bold; run.font.name = FONT
    if color is not None:
        run.font.color.rgb = color
    _cjk(run)


def _tb(slide, left, top, width, height):
    tb = slide.shapes.add_textbox(EM(left), EM(top), EM(width), EM(height))
    tb.text_frame.word_wrap = True
    return tb.text_frame


def _set(p, text, size=14, bold=False, color=None, align=None):
    p.text = text
    for run in p.runs:
        _style(run, size, bold, color)
    if align is not None:
        p.alignment = align


class Deck:
    def __init__(self, out_path, fig_dir, disc=DISC):
        self.prs = Presentation()
        self.prs.slide_width = Inches(13.333); self.prs.slide_height = Inches(7.5)
        self.SW, self.SH = self.prs.slide_width, self.prs.slide_height
        self.BLANK = self.prs.slide_layouts[6]
        self.FIG = fig_dir; self.OUT = out_path; self.DISC = disc

    def add(self):
        return self.prs.slides.add_slide(self.BLANK)

    def band(self, slide, color, height):
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, EM(self.SW), EM(height))
        shp.fill.solid(); shp.fill.fore_color.rgb = color; shp.line.fill.background()
        shp.shadow.inherit = False
        return shp

    def footer(self, slide):
        tf = _tb(slide, Inches(0.3), self.SH - Inches(0.38), self.SW - Inches(1.1), Inches(0.32))
        _set(tf.paragraphs[0], self.DISC, size=8, color=GREY)

    def section(self, title, accent=BLUE, tag=None):
        s = self.add()
        self.band(s, accent, Inches(0.86))
        tf = _tb(s, Inches(0.5), Inches(0.12), self.SW - Inches(3.2), Inches(0.64))
        _set(tf.paragraphs[0], title, size=21, bold=True, color=WHITE)
        if tag:
            tt = _tb(s, self.SW - Inches(3.2), Inches(0.2), Inches(2.9), Inches(0.5))
            _set(tt.paragraphs[0], tag, size=11.5, bold=True,
                 color=RGBColor(0xDD, 0xE8, 0xF2), align=2)
        return s

    def takeaway(self, slide, text, y=None):
        y = Inches(6.5) if y is None else y
        shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, EM(Inches(0.35)), EM(y),
                                     EM(self.SW - Inches(0.7)), EM(Inches(0.52)))
        shp.fill.solid(); shp.fill.fore_color.rgb = YELLOW_BG
        shp.line.color.rgb = YELLOW_LN; shp.shadow.inherit = False
        tf = shp.text_frame; tf.word_wrap = True
        tf.margin_top = Pt(2); tf.margin_bottom = Pt(2)
        _set(tf.paragraphs[0], "💡 " + text, size=11.5, bold=True, color=BROWN)

    def box(self, slide, left, top, w, h, text, fill, fg=WHITE, size=12, sub=None,
            sub_size=9.5, line=NAVY):
        shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, EM(left), EM(top), EM(w), EM(h))
        shp.fill.solid(); shp.fill.fore_color.rgb = fill; shp.line.color.rgb = line
        shp.shadow.inherit = False
        tf = shp.text_frame; tf.word_wrap = True
        _set(tf.paragraphs[0], text, size=size, bold=True, color=fg, align=2)
        if sub:
            p = tf.add_paragraph(); _set(p, sub, size=sub_size, color=fg, align=2)
        return shp

    def line_seg(self, slide, x1, y1, x2, y2, color=NAVY, width=2.25, dash=None, arrow_head=False):
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, EM(x1), EM(y1), EM(x2), EM(y2))
        c.line.color.rgb = color; c.line.width = Pt(width)
        if dash is not None:
            c.line.dash_style = dash
        if arrow_head:
            ln = c.line._get_or_add_ln()
            tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
            ln.append(tail)
        return c

    def label(self, slide, x, y, w, h, text, size=10.5, bold=False, color=INK, align=None):
        tf = _tb(slide, x, y, w, h)
        _set(tf.paragraphs[0], text, size=size, bold=bold, color=color, align=align)
        return tf

    def bullets(self, tf, items, size=12.5, gap=4, color=INK, first=True, marker="•  "):
        for it in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            _set(p, (marker + it) if marker else it, size=size, color=color)
            p.space_after = Pt(gap)
        return tf

    def _fill_cell(self, c, text, size=10, bold=False, color=INK, fill=None):
        c.text = text
        if fill is not None:
            c.fill.solid(); c.fill.fore_color.rgb = fill
        for pa in c.text_frame.paragraphs:
            for run in pa.runs:
                _style(run, size, bold, color)

    def make_table(self, slide, headers, data, x, y, colw, row_h=0.42, hdr_size=11,
                   cell_size=10, styler=None):
        n = len(data) + 1
        tbl = slide.shapes.add_table(n, len(headers), EM(x), EM(y), EM(Inches(sum(colw))),
                                     EM(Inches(row_h) * n)).table
        for j, w in enumerate(colw):
            tbl.columns[j].width = EM(Inches(w))
        for j, h in enumerate(headers):
            self._fill_cell(tbl.cell(0, j), h, size=hdr_size, bold=True, color=WHITE, fill=NAVY)
        for i, rowv in enumerate(data, 1):
            for j, v in enumerate(rowv):
                size, bold, color = cell_size, False, INK
                if styler:
                    size, bold, color = styler(i, j, v, cell_size)
                self._fill_cell(tbl.cell(i, j), v, size=size, bold=bold, color=color,
                                fill=LIGHT if i % 2 else WHITE)
        return tbl

    def glossary(self, title, items, tag="用語定義"):
        s = self.section(title, STEEL, tag)
        tf = _tb(s, Inches(0.55), Inches(1.0), self.SW - Inches(1.1), Inches(5.3))
        first = True
        for term, defn in items:
            p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
            p.space_after = Pt(4)
            r = p.add_run(); r.text = f"{term}　"; _style(r, 12.5, True, NAVY)
            r2 = p.add_run(); r2.text = defn; _style(r2, 11.5, False, INK)
        self.footer(s)
        return s

    def concept(self, title, tag, strength, risk, bg, prob, chal, sol, novelty, tw, accent=TEAL):
        s = self.section(title, accent, tag)
        tf = _tb(s, Inches(0.5), Inches(0.94), self.SW - Inches(1.0), Inches(0.4))
        p = tf.paragraphs[0]; p.text = ""
        for txt, col in [("技術エビデンス強度: ", NAVY),
                         (strength + "    ", GREEN if "STRONG" in strength
                          else (GREY if "PROSPECTIVE" in strength else BLUE)),
                         ("先行技術リスク(UNVERIFIED): ", NAVY),
                         (risk, RED if "HIGH" in risk else GREY)]:
            r = p.add_run(); r.text = txt; _style(r, 12, True, col)
        tf = _tb(s, Inches(0.5), Inches(1.36), self.SW - Inches(1.0), Inches(5.0))
        first = True
        for head, body in [("背景", bg), ("問題", prob), ("課題", chal),
                           ("解決法", sol), ("特許性 / 新規性", novelty)]:
            p = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
            _set(p, head, size=13, bold=True, color=NAVY); p.space_before = Pt(4)
            q = tf.add_paragraph(); _set(q, body, size=11.8)
        self.takeaway(s, tw); self.footer(s)
        return s

    def features(self, title, tag, rows, row_h=0.44):
        s = self.section(title, RGBColor(0x2E, 0x5A, 0x88), tag)
        self.make_table(s, ["変数 / 特徴量", "種別", "作成方法（特徴量エンジニアリング）"],
                        rows, Inches(0.4), Inches(1.02), [4.6, 1.5, 6.4], row_h=row_h,
                        styler=lambda i, j, v, b: (
                            b, j == 1,
                            (GREEN if v == "派生" else RED if "NOT" in v else GREY)
                            if j == 1 else INK))
        self.footer(s)
        return s

    def figure(self, title, tag, img, what, axes, claim, interp, tw=None, accent=DGREEN,
               max_w=7.1, max_h=4.95):
        s = self.section(title, accent, tag)
        p = self.FIG / img
        img_bottom = Inches(1.1)
        if p.exists():
            from PIL import Image
            try:
                iw, ih = Image.open(p).size
            except Exception:
                iw, ih = 1600, 1000
            scale = min(Inches(max_w) / iw, Inches(max_h) / ih)
            pic_w, pic_h = EM(iw * scale), EM(ih * scale)
            s.shapes.add_picture(str(p), EM(Inches(0.4)), EM(Inches(1.08)), width=pic_w, height=pic_h)
            img_bottom = Inches(1.08) + pic_h
            cap = _tb(s, Inches(0.4), img_bottom + Inches(0.02), Inches(7.1), Inches(0.3))
            _set(cap.paragraphs[0], f"図: {img}（dpi=300・匿名化済み）", size=8.5, color=GREY)
        tf = _tb(s, Inches(7.7), Inches(1.0), Inches(5.3), Inches(5.45))
        first = True
        for head, body, col in [("【何のグラフか】", what, BLUE),
                                ("【軸・変数の定義】", axes, NAVY),
                                ("【主張（言いたいこと）】", claim, GREEN),
                                ("【読み方・解釈】", interp, ORANGE)]:
            p1 = tf.paragraphs[0] if first else tf.add_paragraph(); first = False
            _set(p1, head, size=12, bold=True, color=col); p1.space_before = Pt(5)
            p2 = tf.add_paragraph(); _set(p2, body, size=11, color=INK)
        if tw:
            self.takeaway(s, tw)
        self.footer(s)
        return s

    def title_slide(self, title, subtitle, bullets_list, size=33):
        s = self.add(); self.band(s, NAVY, self.SH)
        tf = _tb(s, Inches(0.8), Inches(1.2), self.SW - Inches(1.6), Inches(2.2))
        _set(tf.paragraphs[0], title, size=size, bold=True, color=WHITE)
        p = tf.add_paragraph(); _set(p, subtitle, size=18, color=RGBColor(0xCF, 0xDD, 0xEE))
        tf2 = _tb(s, Inches(0.8), Inches(3.5), self.SW - Inches(1.6), Inches(3.4))
        for i, ln in enumerate(bullets_list):
            p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            _set(p, "•  " + ln, size=14, color=WHITE); p.space_after = Pt(5)
        self.footer(s)
        return s

    def notes(self, slide, budget, text):
        ns = slide.notes_slide
        ns.notes_text_frame.text = f"[目安 {budget}]\n{text}"

    def save(self):
        self.prs.save(str(self.OUT))
        n_notes = sum(1 for sl in self.prs.slides if sl.has_notes_slide)
        total = sum(len(sl.notes_slide.notes_text_frame.text.split("\n", 1)[-1])
                    for sl in self.prs.slides if sl.has_notes_slide)
        print(f"saved: {self.OUT}")
        print(f"slides: {len(self.prs.slides._sldIdLst)} / notes: {n_notes} / "
              f"note chars: {total} (~{total/300:.1f} min @300字/分)")
        return len(self.prs.slides._sldIdLst)


def status_styler(hl_cols):
    def f(i, j, v, base):
        bold, color = False, INK
        if j in hl_cols:
            bold = True
            if "STRONG" in v or "SUPPORTED" in v or "✅" in v:
                color = GREEN
            elif v.strip().startswith("HIGH") or "NOT" in v:
                color = RED
            elif "PROSPECTIVE" in v or "WEAK" in v or v == "—":
                color = GREY
            else:
                color = BLUE
        return base, bold, color
    return f
