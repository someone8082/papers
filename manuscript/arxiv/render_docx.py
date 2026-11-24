"""Export the English and Chinese manuscript sources to an editable Word document."""

import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from lxml import html
import mistune


HERE = Path(__file__).resolve().parent
ENGLISH = HERE / "manuscript-en.md"
CHINESE = HERE.parent / "2026-11-19-draft-v0.md"
OUTPUT = HERE / "aebad-grouped-splits-bilingual.docx"
WIDTH_MM = 160
INK = "172531"
MUTED = "4C5963"
LINK = "235B82"


def configure(document):
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(25)
    section.top_margin, section.bottom_margin = Mm(20), Mm(19)
    section.footer_distance = Mm(8)

    styles = document.styles
    for name in ("Figure", "Table Caption", "Table Cell", "Table Header", "Equation"):
        if name not in styles:
            styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        styles[name].base_style = styles["Normal"]

    # Sizes are in points at the final A4 print size.
    settings = {
        "Normal": (10.75, 14.5, 0, 5.5, False),
        "Title": (20, 24, 0, 9, True),
        "Subtitle": (12, 16, 0, 12, True),
        "Heading 1": (14, 18, 10, 5, True),
        "Heading 2": (11.75, 16, 8, 4, True),
        "List Bullet": (10.75, 14.5, 0, 4, False),
        "List Number": (10.75, 14.5, 0, 4, False),
        "Figure": (10, None, 4, 4, True),
        "Caption": (9.5, 13, 0, 8, False),
        "Table Caption": (10, 13.5, 4, 4, True),
        "Table Cell": (9.25, 12.5, 0, 0, False),
        "Table Header": (9.25, 12.5, 0, 0, True),
        "Equation": (11, None, 4, 7, False),
        "Footer": (9, 12, 0, 0, False),
    }
    for name, (size, leading, before, after, keep_next) in settings.items():
        style = styles[name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(
            MUTED if name in ("Caption", "Footer") else INK
        )
        style.font.bold = name in ("Title", "Heading 1", "Heading 2", "Table Header")
        style.font.italic = False
        fonts = style.element.get_or_add_rPr().rFonts
        for key in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn(f"w:{key}"), None)
        fonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style_properties = style.element.get_or_add_pPr()
        for border in style_properties.findall(qn("w:pBdr")):
            style_properties.remove(border)
        fmt = style.paragraph_format
        fmt.space_before, fmt.space_after = Pt(before), Pt(after)
        fmt.line_spacing = Pt(leading) if leading is not None else 1.0
        fmt.keep_with_next = keep_next
        fmt.keep_together = name in ("Title", "Subtitle", "Caption", "Table Caption")
        fmt.widow_control = True
        if name in ("Title", "Subtitle", "Figure", "Equation", "Footer"):
            fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER

    footer = section.footer.paragraphs[0]
    footer.style = "Footer"
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.settings.element.append(OxmlElement("w:doNotAutoCompressPictures"))


def add_inline(paragraph, node):
    """Retain styled runs and public hyperlinks from the Markdown HTML tree."""
    def walk(item, bold=False, italic=False, link=None):
        bold = bold or item.tag in ("strong", "b")
        italic = italic or item.tag in ("em", "i")
        if item.tag == "a" and urlsplit(item.get("href", "")).scheme in {"http", "https"}:
            link = OxmlElement("w:hyperlink")
            link.set(
                qn("r:id"),
                paragraph.part.relate_to(
                    item.get("href"), RELATIONSHIP_TYPE.HYPERLINK, is_external=True
                ),
            )
            paragraph._p.append(link)

        def write(text, line_break=False):
            if not text and not line_break:
                return
            run = paragraph.add_run(text)
            if bold:
                run.bold = True
            if italic:
                run.italic = True
            if line_break:
                run.add_break()
            if link is not None:
                run.font.color.rgb, run.underline = RGBColor.from_string(LINK), True
                link.append(run._r)

        write(item.text)
        if item.tag == "br":
            write("", line_break=True)
        for child in item:
            walk(child, bold, italic, link)
            write(child.tail)

    walk(node)
    return paragraph


def add_table(document, node):
    rows = node.xpath(".//tr")
    ncol = len(rows[0])
    weights = {
        2: (.35, .65),
        3: (.30, .35, .35),
        4: (.34, .22, .22, .22),
        5: (.16, .17, .11, .16, .40),
        7: (.12, .13, .10, .165, .18, .14, .165),
    }[ncol]
    headers = tuple(cell.text_content() for cell in rows[0])
    if headers[0] in {"Images in multi-image groups", "固定多图组容量"}:
        weights = (.25, .12, .48, .15)
    notation = headers[0] in {"Symbol", "符号"}
    appendix = notation or headers[-1] in {"Project-relative record", "来源"}
    table = document.add_table(rows=len(rows), cols=ncol)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for column, weight in zip(table.columns, weights):
        column.width = Mm(WIDTH_MM * weight)

    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom", "insideH"):
        border = OxmlElement(f"w:{edge}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "6" if edge != "insideH" else "2")
        border.set(qn("w:color"), INK if edge != "insideH" else "D8DEE3")
        borders.append(border)
    table._tbl.tblPr.append(borders)
    margins = OxmlElement("w:tblCellMar")
    vertical_padding = 30 if appendix else 56
    for edge, twips in (("top", vertical_padding), ("bottom", vertical_padding),
                        ("left", 86), ("right", 86)):
        margin = OxmlElement(f"w:{edge}")
        margin.set(qn("w:w"), str(twips))
        margin.set(qn("w:type"), "dxa")
        margins.append(margin)
    table._tbl.tblPr.append(margins)

    for i, (row, source) in enumerate(zip(table.rows, rows)):
        if len(source) != ncol:
            raise ValueError("Inconsistent Markdown table width")
        properties = row._tr.get_or_add_trPr()
        properties.append(OxmlElement("w:cantSplit"))
        if i == 0:
            properties.append(OxmlElement("w:tblHeader"))
        for cell, source_cell, column in zip(row.cells, source, table.columns):
            cell.width = column.width
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            paragraph = cell.paragraphs[0]
            paragraph.style = "Table Cell" if i else "Table Header"
            if len(rows) <= 5 or notation:
                paragraph.paragraph_format.keep_with_next = i < len(rows) - 1
            if notation:
                paragraph.paragraph_format.line_spacing = Pt(11.75)
            add_inline(paragraph, source_cell)
            if i == 0:
                shading = OxmlElement("w:shd")
                shading.set(qn("w:fill"), "EDF1F4")
                cell._tc.get_or_add_tcPr().append(shading)


def math_node(tag, *children):
    element = OxmlElement(f"m:{tag}")
    for child in children:
        element.append(child)
    return element


def math_run(text, plain=False):
    content = math_node("t")
    content.text = text
    if plain:
        style = math_node("sty")
        style.set(qn("m:val"), "p")
        return math_node("r", math_node("rPr", style), content)
    return math_node("r", content)


def allocation_coefficient(degree, excluded):
    subscript = math_node(
        "sSub", math_node("e", math_run("s")), math_node("sub", math_run("g"))
    )
    power = math_node("sSup", math_node("e", math_run("x")), math_node("sup", subscript))
    operator, limit, hide_sup = (math_node(tag) for tag in ("chr", "limLoc", "supHide"))
    for element, value in ((operator, "∏"), (limit, "subSup"), (hide_sup, "on")):
        element.set(qn("m:val"), value)
    product = math_node(
        "nary", math_node("naryPr", operator, limit, hide_sup),
        math_node("sub", math_run("g≠a,b" if excluded else "g")),
        math_node("sup"), math_node("e", math_run("(1+"), power, math_run(")")),
    )
    degree = math_node(
        "sSup", math_node("e", math_run("x")), math_node("sup", math_run(str(degree)))
    )
    return [math_run("["), degree, math_run("]"), product]


def add_equation(document, expression):
    paragraph = document.add_paragraph(style="Equation")
    expected = "P(both) = [x^30] ∏_{g≠a,b} (1 + x^{s_g}) / [x^32] ∏_g (1 + x^{s_g})"
    if expression != expected:
        raise ValueError(f"Unexpected manuscript equation: {expression}")
    fraction = math_node(
        "f", math_node("num", *allocation_coefficient(30, excluded=True)),
        math_node("den", *allocation_coefficient(32, excluded=False)),
    )
    paragraph._p.append(math_node("oMath", math_run("P"), math_run("(both)=", True), fraction))


def append_source(document, source, chinese, authors, affiliations):
    text = source.read_text(encoding="utf-8")
    if chinese:
        text = text.split("\n## 待补项", 1)[0]
        text = re.sub(r"^\*\*初稿 v0\*\*[^\n]*\n", "", text, count=1, flags=re.M)
        text = re.sub(r"\n## Abstract\n.*?(?=\n## 1 引言\n)", "\n", text, count=1, flags=re.S)
    # Mistune 0.x includes table support by default. Modern Mistune requires the plugin.
    markdown = (
        mistune.markdown if mistune.__version__.startswith("0.")
        else mistune.create_markdown(plugins=["table"])
    )
    nodes = iter(html.fragment_fromstring(markdown(text), create_parent=True))
    for node in nodes:
        raw = node.text_content().strip()
        if node.tag == "h1":
            title = document.add_paragraph(style="Title")
            split = raw.find("：") + 1 if chinese else raw.rfind(" in ")
            if split > 0:
                title.add_run(raw[:split]).add_break()
                title.add_run(raw[split:].strip())
            else:
                add_inline(title, node)
            if not chinese:
                add_inline(document.add_paragraph(style="Subtitle"), next(nodes))
            for line in (authors, affiliations):
                if line:
                    document.add_paragraph(line, "Subtitle")
        elif node.tag in ("h2", "h3"):
            style = {"h2": "Heading 1", "h3": "Heading 2"}[node.tag]
            add_inline(document.add_paragraph(style=style), node)
        elif node.tag == "p":
            image = node.find("img")
            if image is None:
                style = "Normal"
                if re.match(r"^(?:Table|表) \d+\b|^B\.1\b", raw):
                    marker = node.find("strong")
                    if marker is not None and not node.text:
                        style = "Table Caption"
                add_inline(document.add_paragraph(style=style), node)
                continue
            path = (source.parent / image.get("src")).with_suffix(".png")
            shape = document.add_paragraph(style="Figure").add_run().add_picture(
                str(path), width=Mm(WIDTH_MM)
            )
            shape._inline.docPr.set("descr", image.get("alt", ""))
            caption = next(nodes)
            if caption.tag != "p" or not re.match(r"^(?:Figure|图) \d+\b", caption.text_content()):
                raise ValueError(f"Missing caption after {path}")
            add_inline(document.add_paragraph(style="Caption"), caption)
        elif node.tag == "table":
            add_table(document, node)
        elif node.tag in ("ol", "ul"):
            style = "List Number" if node.tag == "ol" else "List Bullet"
            for item in node:
                add_inline(document.add_paragraph(style=style), item)
        elif node.tag == "pre":
            add_equation(document, raw)
        elif node.tag != "hr":
            raise ValueError(f"Unsupported Markdown block: {node.tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--authors", default="")
    parser.add_argument("--affiliations", default="")
    args = parser.parse_args()

    document = Document()
    configure(document)
    document.core_properties.title = ENGLISH.read_text(encoding="utf-8").splitlines()[0][2:]
    document.core_properties.subject = "Few-shot anomaly detection and exact counting"
    document.core_properties.author = args.authors
    document.core_properties.comments = ""
    append_source(document, ENGLISH, False, args.authors, args.affiliations)
    document.add_page_break()
    append_source(document, CHINESE, True, args.authors, args.affiliations)
    document.save(args.output)
    print(f"{args.output}: {len(document.tables)} editable tables, "
          f"{len(document.inline_shapes)} inline figures")


if __name__ == "__main__":
    main()
