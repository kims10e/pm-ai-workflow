import importlib.util
import tempfile
import unittest
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_narration_docx", ROOT / "scripts" / "make_narration_docx.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SAMPLE = """# 대본 제목

## 장면 1 · 테스트 (0:00 ~ 0:10)
*화면: 터미널, `python src/pm_agent.py quality`*

> 첫 번째 읽을 문장입니다.
> 두 번째 문장은 **굵게** 읽습니다.

*자막 EN: Rule-based check.*

`[멈춤 3초]` *← 화면만 보여줍니다.*

> **이 장면은 실제 결과에 맞춰 읽으세요.** 참고 상자입니다.

- 읽는 요령 한 줄

---
"""


def build(text=SAMPLE):
    out = Path(tempfile.mkdtemp()) / "n.docx"
    mod.markdown_to_narration_docx(text, out)
    return Document(out)


def size(p):
    return p.runs[0].font.size.pt if p.runs and p.runs[0].font.size else None


class NarrationDocxTest(unittest.TestCase):
    def test_narration_lines_are_large_and_cues_are_small_gray_italic(self):
        d = build()
        narration = [p for p in d.paragraphs if size(p) == 18]
        self.assertEqual([p.text for p in narration], ["첫 번째 읽을 문장입니다.", "두 번째 문장은 굵게 읽습니다."])
        cue = next(p for p in d.paragraphs if p.text.startswith("화면:"))
        self.assertEqual(size(cue), 10.5)
        self.assertTrue(cue.runs[0].italic)
        self.assertIn("python src/pm_agent.py quality", cue.text)  # 기울임 안의 코드도 살아 있다

    def test_pause_marker_is_highlighted_and_note_box_is_shaded(self):
        d = build()
        marks = [r for p in d.paragraphs for r in p.runs if r.font.highlight_color is not None]
        self.assertEqual([r.text for r in marks], ["[멈춤 3초]"])
        note = next(p for p in d.paragraphs if "참고 상자" in p.text)
        self.assertIsNotNone(note._p.pPr.find(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"))

    def test_no_markdown_symbols_remain_and_bold_is_applied(self):
        d = build()
        for p in d.paragraphs:
            self.assertNotIn("**", p.text)
            self.assertNotIn("`", p.text)
        bold = [r.text for p in d.paragraphs for r in p.runs if r.bold and size(p) == 18]
        self.assertEqual(bold, ["굵게"])

    def test_page_is_a4_and_scene_heading_is_kept_with_next(self):
        d = build()
        self.assertEqual((round(d.sections[0].page_width.cm, 1), round(d.sections[0].page_height.cm, 1)), (21.0, 29.7))
        heading = next(p for p in d.paragraphs if p.text.startswith("장면 1"))
        self.assertTrue(heading.paragraph_format.keep_with_next)

    def test_real_narration_file_converts(self):
        text = (ROOT / "docs" / "DEMO_NARRATION.md").read_text(encoding="utf-8")
        d = build(text)
        self.assertGreaterEqual(len([p for p in d.paragraphs if size(p) == 18]), 20)


if __name__ == "__main__":
    unittest.main()
