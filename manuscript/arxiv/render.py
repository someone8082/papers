"""Build the bilingual arXiv review PDF from the English and Chinese Markdown."""

import argparse
from html import escape
from pathlib import Path
import re
from urllib.parse import urlsplit

from lxml import html
import mistune
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak, Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
    SimpleDocTemplate, Table, TableStyle,
)


HERE = Path(__file__).resolve().parent
CHINESE = HERE.parent / "2026-11-19-draft-v0.md"
ENGLISH = HERE / "manuscript-en.md"
WIDTH = 160 * mm
MARGIN = 25 * mm
INK = colors.HexColor("#182531")
GRAY = colors.HexColor("#5B626A")
RULE = colors.HexColor("#A9B0B6")
LINK = "#235B82"


class Paper(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        bookmark = getattr(flowable, "bookmark", None)
        if bookmark is not None:
            key, title, level = bookmark
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=level)


def fonts(folder):
    for name, file in (
        ("Latin", "times.ttf"), ("LatinBold", "timesbd.ttf"),
        ("LatinItalic", "timesi.ttf"), ("LatinBoldItalic", "timesbi.ttf"),
        ("Chinese", "msyh.ttc"), ("ChineseBold", "msyhbd.ttc"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(folder / file)))
    pdfmetrics.registerFontFamily("Latin", normal="Latin", bold="LatinBold",
                                  italic="LatinItalic", boldItalic="LatinBoldItalic")
    pdfmetrics.registerFontFamily("Chinese", normal="Chinese", bold="ChineseBold",
                                  italic="Chinese", boldItalic="ChineseBold")


def styles(lang):
    font = "Chinese" if lang == "zh" else "Latin"
    body = ParagraphStyle("Body", fontName=font, textColor=INK,
                          fontSize=10.8, leading=15.7, spaceAfter=6.4,
                          wordWrap="CJK" if lang == "zh" else None,
                          allowWidows=0, allowOrphans=0)
    return {
        "body": body,
        "title": ParagraphStyle("Title", parent=body, fontName=font+"Bold",
                                fontSize=20, leading=25, spaceAfter=9,
                                alignment=TA_CENTER, keepWithNext=True),
        "subtitle": ParagraphStyle("Subtitle", parent=body, fontSize=13,
                                   leading=17, spaceAfter=13, alignment=TA_CENTER,
                                   keepWithNext=True),
        "section": ParagraphStyle("Section", parent=body, fontName=font+"Bold",
                                  fontSize=14, leading=18, spaceBefore=10,
                                  spaceAfter=6, keepWithNext=True),
        "subsection": ParagraphStyle("Subsection", parent=body, fontName=font+"Bold",
                                     fontSize=11.6, leading=15.3, spaceBefore=6.5,
                                     spaceAfter=4.5, keepWithNext=True),
        "caption": ParagraphStyle("Caption", parent=body, fontSize=9.5,
                                  leading=13.5, spaceBefore=4.5, spaceAfter=7),
        "table_caption": ParagraphStyle("TableCaption", parent=body, fontSize=10.2,
                                        leading=14, spaceBefore=4, spaceAfter=4,
                                        keepWithNext=True),
        "cell": ParagraphStyle("Cell", parent=body, fontSize=9.1, leading=12.1,
                               spaceAfter=0, allowWidows=1, allowOrphans=1),
        "equation": ParagraphStyle("Equation", parent=body, fontName="Latin",
                                   fontSize=11.4, leading=15, alignment=TA_CENTER),
    }


def inline(node):
    result = escape(node.text or "")
    for child in node:
        content = inline(child)
        if child.tag in ("strong", "b"):
            content = f"<b>{content}</b>"
        elif child.tag in ("em", "i"):
            content = f"<i>{content}</i>"
        elif child.tag == "br":
            content = "<br/>"
        elif child.tag == "a" and urlsplit(child.get("href", "")).scheme in {"https", "http"}:
            content = f'<link href="{escape(child.get("href"), quote=True)}" color="{LINK}">{content}</link>'
        result += content + escape(child.tail or "")
    superscript = str.maketrans("⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "−0123456789")
    return re.sub(r"⁻[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
                  lambda match: f"<super>{match[0].translate(superscript)}</super>",
                  result)


def make_table(node, style):
    def cell(item):
        text = inline(item)
        text = re.sub(r"(\d{14,})", r"<nobr>\1</nobr>", text)
        if item.tag == "th":
            text = f"<b>{text}</b>"
        return Paragraph(text, style)

    rows = [[cell(item) for item in row] for row in node.xpath(".//tr")]
    columns = len(rows[0])
    weights = {
        2: (.35, .65),
        3: (.29, .34, .37),
        4: (.33, .223, .223, .224),
        5: (.16, .17, .115, .155, .4),
        7: (.114, .136, .114, .146, .184, .148, .158),
    }[columns]
    header = node.xpath(".//tr[1]/th[1]")[0].text_content()
    if header in {"Images in multi-image groups", "固定多图组容量"}:
        weights = (.253, .115, .488, .144)
    table = Table(rows, colWidths=[WIDTH * w for w in weights], repeatRows=1,
                  hAlign="LEFT", spaceAfter=9)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), style.fontName),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 0), (-1, 0), .65, INK),
        ("LINEBELOW", (0, 0), (-1, 0), .4, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), .6, INK),
    ]))
    return table


def display_equation(text, style):
    expected = "P(both) = [x^30] ∏_{g≠a,b} (1 + x^{s_g}) / [x^32] ∏_g (1 + x^{s_g})"
    if text.strip() != expected:
        raise ValueError("Unexpected display equation")
    numerator = Paragraph("[<i>x</i><super>30</super>] ∏<sub>g ≠ a,b</sub>"
                          " (1 + <i>x</i><super>s<sub>g</sub></super>)", style)
    denominator = Paragraph("[<i>x</i><super>32</super>] ∏<sub>g</sub>"
                            " (1 + <i>x</i><super>s<sub>g</sub></super>)", style)
    fraction = Table([[numerator], [denominator]], colWidths=[153],
                     style=[("FONTNAME", (0, 0), (-1, -1), style.fontName),
                            ("LINEBELOW", (0, 0), (0, 0), .6, INK)])
    return Table([[Paragraph("<i>P</i>(both) =", style), fraction]],
                 colWidths=[63, 153], hAlign="CENTER", spaceBefore=4, spaceAfter=8,
                 style=[("FONTNAME", (0, 0), (-1, -1), style.fontName),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])


def document_flow(markdown, lang, folder, authors, affiliations):
    nodes = list(html.fragment_fromstring(mistune.markdown(markdown), create_parent=True))
    style = styles(lang)
    flow = []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        raw = node.text_content().strip()
        if node.tag in {"h1", "h2", "h3"}:
            role, level = {"h1": ("title", 0), "h2": ("section", 1),
                           "h3": ("subsection", 2)}[node.tag]
            heading = Paragraph(inline(node), style[role])
            heading.bookmark = (f"{lang}-{index}", raw, level)
            if index + 1 < len(nodes) and nodes[index + 1].tag in {"ol", "ul"}:
                flow.append(CondPageBreak(75))
            flow.append(heading)
            if node.tag == "h1":
                if lang == "en":
                    index += 1
                    flow.append(Paragraph(inline(nodes[index]), style["subtitle"]))
                for text in (authors, affiliations):
                    if text:
                        flow.append(Paragraph(escape(text), style["subtitle"]))
        elif node.tag == "p":
            image = node.find("img")
            if image is not None:
                path = (folder / image.get("src")).with_suffix(".png")
                figure = Image(str(path))
                scale = WIDTH / figure.imageWidth
                figure.drawWidth = WIDTH
                figure.drawHeight = figure.imageHeight * scale
                index += 1
                caption = Paragraph(inline(nodes[index]), style["caption"])
                flow.append(KeepTogether([figure, caption]))
            else:
                kind = "table_caption" if re.match(r"^(Table|表) \d+", raw) else "body"
                flow.append(Paragraph(inline(node), style[kind]))
        elif node.tag == "table":
            flow.append(make_table(node, style["cell"]))
        elif node.tag in {"ol", "ul"}:
            items = [ListItem(Paragraph(inline(i), style["body"]), leftIndent=2) for i in node]
            flow.append(ListFlowable(items, bulletType="1" if node.tag == "ol" else "bullet",
                                     bulletFontName=style["body"].fontName,
                                     bulletFontSize=9.2, bulletOffsetY=1, leftIndent=15))
        elif node.tag == "pre":
            flow.append(display_equation(raw, style["equation"]))
        elif node.tag != "hr":
            raise ValueError(f"Unhandled Markdown block {node.tag}")
        index += 1
    return flow


def english_abstract(markdown):
    section = markdown.split("## Abstract\n\n", 1)[1].split("**Keywords**", 1)[0]
    return " ".join(section.replace("`", "").replace("−", "-").split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", default="C:/Windows/Fonts", type=Path)
    parser.add_argument("--authors", default="")
    parser.add_argument("--affiliations", default="")
    args = parser.parse_args()
    fonts(args.font_dir)

    en = ENGLISH.read_text(encoding="utf-8")
    cn = CHINESE.read_text(encoding="utf-8").split("\n## 待补项", 1)[0]
    cn = re.sub(r"^\*\*初稿 v0\*\*[^\n]*\n", "", cn, count=1, flags=re.M)
    cn = re.sub(r"\n## Abstract\n.*?(?=\n## 1 引言\n)", "\n", cn, count=1, flags=re.S)
    title_line, _, subtitle, *_ = en.splitlines()
    title = f"{title_line[2:]}: {subtitle[0].lower() + subtitle[1:]}"
    abstract = english_abstract(en)
    assert abstract.isascii() and len(abstract) <= 1920
    figure_count = len(re.findall(r"^!\[", en, re.M))
    if figure_count != len(re.findall(r"^!\[", cn, re.M)):
        raise ValueError("The English and Chinese versions have different figure counts")

    def page_number(canvas, doc):
        canvas.setFillColor(GRAY)
        canvas.setFont("Latin", 9)
        canvas.drawCentredString(A4[0] / 2, 13 * mm, str(doc.page))

    output = HERE / "aebad-grouped-splits-bilingual.pdf"
    doc = Paper(str(output), pagesize=A4, title=title, author=args.authors,
                subject="Few-shot anomaly detection and exact counting",
                initialFontName="Latin",
                leftMargin=MARGIN-6, rightMargin=MARGIN-6,
                topMargin=19*mm, bottomMargin=20*mm)
    en_flow = document_flow(en, "en", HERE, args.authors, args.affiliations)
    cn_flow = document_flow(cn, "zh", CHINESE.parent, args.authors, args.affiliations)
    doc.build(en_flow + [PageBreak()] + cn_flow,
              onFirstPage=page_number, onLaterPages=page_number)
    authors = args.authors or "[To be confirmed by the submitting author]"
    if args.affiliations:
        authors += f" ({args.affiliations})"
    (HERE / "arxiv-metadata.txt").write_text(
        f"Title: {title}\n"
        f"Authors: {authors}\n"
        "Primary category (proposed): cs.CV\n"
        f"Comments: {doc.page} pages, {figure_count} figures per language version. In English and Chinese.\n"
        "Distribution license: [To be selected by the submitting author]\n\n"
        f"Abstract ({len(abstract)} characters, copy the text below):\n{abstract}\n",
        encoding="utf-8",
    )
    print(f"{output.name}: {doc.page} pages, {len(abstract)} metadata abstract characters")


if __name__ == "__main__":
    main()
