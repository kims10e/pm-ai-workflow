"""보고서 마크다운 → Word(docx) 변환.

status-report 스킬이 내는 형식(제목 #~###, 글머리 -, 번호 1., 표, **굵게**)만 다룬다.
- 한글 글꼴(맑은 고딕)을 동아시아 글꼴로도 지정해 한글이 깨지거나 다른 글꼴로 보이지 않게 한다.
- 표 칸이 정확히 Green / Amber / Red 이면 칸에 색을 입힌다.
- 모델이 실수로 코드펜스(```)로 감싸 내보내도 벗겨서 처리한다.

사용: python src/md_to_docx.py 입력.md 출력.docx
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

FONT = "맑은 고딕"
RAG_FILL = {"Green": "C6EFCE", "Amber": "FFEB9C", "Red": "FFC7CE"}
HEADER_FILL = "D9D9D9"

_BOLD = re.compile(r"(\*\*.+?\*\*)")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _set_font(run, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def _add_inline(paragraph, text: str, size: float | None = None, force_bold: bool = False) -> None:
    text = text.replace("`", "")
    for part in _BOLD.split(text):
        if not part:
            continue
        is_bold = part.startswith("**") and part.endswith("**") and len(part) > 4
        run = paragraph.add_run(part[2:-2] if is_bold else part)
        _set_font(run, size, True if (is_bold or force_bold) else None)


def _shade(cell, hex_fill: str) -> None:
    tc_pr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _add_table(doc, rows: list[list[str]]) -> None:
    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            text = row[ci] if ci < len(row) else ""
            cell = table.cell(ri, ci)
            para = cell.paragraphs[0]
            _add_inline(para, text, size=9.5, force_bold=(ri == 0))
            if ri == 0:
                _shade(cell, HEADER_FILL)
            elif text in RAG_FILL:
                _shade(cell, RAG_FILL[text])
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()  # 표 뒤 여백


def _strip_fence(md: str) -> str:
    lines = md.strip().splitlines()
    if lines and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return md


def markdown_to_docx(md_text: str, out_path: Path | str) -> Path:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(10.5)

    for level in (1, 2, 3):
        style = doc.styles[f"Heading {level}"]
        style.font.name = FONT
        style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        style.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)

    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_rows
        if table_rows:
            _add_table(doc, table_rows)
            table_rows = []

    for raw in _strip_fence(md_text).splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            if not _SEPARATOR.match(line):
                table_rows.append(_split_row(line))
            continue
        flush_table()

        if not line.strip():
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            p = doc.add_heading(level=len(heading.group(1)))
            _add_inline(p, heading.group(2))
            continue
        bullet = _BULLET.match(line)
        if bullet:
            _add_inline(doc.add_paragraph(style="List Bullet"), bullet.group(1))
            continue
        number = _NUMBER.match(line)
        if number:
            _add_inline(doc.add_paragraph(style="List Number"), number.group(1))
            continue
        _add_inline(doc.add_paragraph(), line)
    flush_table()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("사용: python src/md_to_docx.py 입력.md 출력.docx", file=sys.stderr)
        return 2
    md = Path(argv[1]).read_text(encoding="utf-8-sig")
    print(markdown_to_docx(md, argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
