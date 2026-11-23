"""해설 대본(docs/DEMO_NARRATION.md)을 읽으면서 녹음하기 좋은 Word 파일로 만든다.

    python scripts/make_narration_docx.py                      # docs/DEMO_NARRATION.docx 생성
    python scripts/make_narration_docx.py 입력.md 출력.docx

마크다운이 원본이다. 대본을 고친 뒤 이 스크립트를 다시 실행하면 Word 파일이 새로 만들어진다.
- 읽을 문장(> 인용): 18pt, 왼쪽 파란 선
- 화면 큐·자막(*기울임*): 작은 회색 기울임체
- [멈춤 N초]: 노란 형광펜
- 참고 상자(> **굵게** 로 시작): 연한 회색 배경
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx import Document  # noqa: E402
from docx.enum.text import WD_COLOR_INDEX  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

import md_to_docx  # noqa: E402  (한글 글꼴 지정 재사용)

FONT = md_to_docx.FONT
BLUE, GRAY, DARK = RGBColor(0x2F, 0x6F, 0xDE), RGBColor(0x6B, 0x72, 0x80), RGBColor(0x1F, 0x2A, 0x44)
_TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`|\*[^*\s][^*]*?\*)")


def _border(paragraph, side: str, color: str = "2F6FDE", size: int = 24, space: int = 8) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    box = ppr.find(qn("w:pBdr"))
    if box is None:
        box = OxmlElement("w:pBdr")
        ppr.append(box)
    el = OxmlElement(f"w:{side}")
    for k, v in (("val", "single"), ("sz", str(size)), ("space", str(space)), ("color", color)):
        el.set(qn(f"w:{k}"), v)
    box.append(el)


def _shade(paragraph, fill: str) -> None:
    shd = OxmlElement("w:shd")
    for k, v in (("val", "clear"), ("color", "auto"), ("fill", fill)):
        shd.set(qn(f"w:{k}"), v)
    paragraph._p.get_or_add_pPr().append(shd)


def _inline(paragraph, text: str, size: float, bold=False, italic=False, color: RGBColor | None = None) -> None:
    """**굵게**, *기울임*, `코드`를 해석한다. 기울임 안의 코드처럼 겹친 표시도 처리한다."""
    for part in _TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            _inline(paragraph, part[2:-2], size, True, italic, color)
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            md_to_docx._set_font(run, size, bold or None)
            run.italic = italic or None
            if part[1:].startswith("[멈춤"):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW  # 아무 말 없이 화면만 보여주는 구간
                run.bold = True
            else:
                run.font.name = "Consolas"
                run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
            if color is not None:
                run.font.color.rgb = color
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            _inline(paragraph, part[1:-1], size, bold, True, color)
        else:
            run = paragraph.add_run(part)
            md_to_docx._set_font(run, size, bold or None)
            run.italic = italic or None
            if color is not None:
                run.font.color.rgb = color


def _is_cue(line: str) -> bool:
    return len(line) > 2 and line.startswith("*") and line.endswith("*") and not line.startswith("**")


def markdown_to_narration_docx(md_text: str, out_path: Path | str) -> Path:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)  # A4
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Cm(2.2))
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    def add(size, *, style=None, before=0, after=4, line=1.15, keep_next=False):
        p = doc.add_paragraph(style=style)
        pf = p.paragraph_format
        pf.space_before, pf.space_after, pf.line_spacing, pf.keep_with_next = Pt(before), Pt(after), line, keep_next
        return p

    for raw in md_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            _inline(add(24, after=6, keep_next=True), line[2:], 24, bold=True, color=DARK)
        elif line.startswith("## "):
            p = add(16, before=16, after=4, keep_next=True)
            _inline(p, line[3:], 16, bold=True, color=BLUE)
            _border(p, "bottom", "2F6FDE", 8, 2)
        elif line.startswith("### "):
            _inline(add(13, before=10, after=2, keep_next=True), line[4:], 13, bold=True, color=DARK)
        elif line == "---":
            continue  # 장면 제목의 밑줄이 구분 역할을 한다
        elif line.startswith(">"):
            text = line[1:].strip()
            if text.startswith("**"):  # 참고 상자
                p = add(10.5, before=4, after=6)
                p.paragraph_format.left_indent = Cm(0.3)
                _shade(p, "F3F4F6")
                _inline(p, text, 10.5, color=GRAY)
            else:  # 소리 내어 읽을 문장
                p = add(18, before=2, after=6, line=1.5)
                p.paragraph_format.left_indent = Cm(0.6)
                _border(p, "left")
                _inline(p, text, 18, color=DARK)
        elif line.startswith("- "):
            _inline(add(11, style="List Bullet", after=2), line[2:], 11)
        elif _is_cue(line):
            _inline(add(10.5, after=3, keep_next=True), line, 10.5, color=GRAY)
        elif line.startswith("`[멈춤"):
            _inline(add(14, before=2, after=6), line, 14)
        else:
            _inline(add(11.5, after=5), line, 11.5)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    src = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "DEMO_NARRATION.md"
    dst = Path(argv[2]) if len(argv) > 2 else src.with_suffix(".docx")
    print(markdown_to_narration_docx(src.read_text(encoding="utf-8-sig"), dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
