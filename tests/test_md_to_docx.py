import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx import Document  # noqa: E402

import md_to_docx  # noqa: E402

SAMPLE = """# 주간 현황 보고 — 테스트 5주차

- 상태: 초안 (PM 승인 전)

## 2. RAG 상태
| 영역 | RAG | 근거 |
|---|---|---|
| 일정 | Amber | **권한 지연** (R-001) |
| 범위 | Green | 변동 없음 |

## 7. 다음 주 계획
- 성능 튜닝
1. 에스컬레이션
"""


class MdToDocxTest(unittest.TestCase):
    def convert(self, md):
        out = Path(tempfile.mkdtemp()) / "r.docx"
        md_to_docx.markdown_to_docx(md, out)
        return Document(out)

    def test_structure_and_korean(self):
        doc = self.convert(SAMPLE)
        self.assertEqual(doc.paragraphs[0].text, "주간 현황 보고 — 테스트 5주차")
        self.assertEqual(len(doc.tables), 1)
        t = doc.tables[0]
        self.assertEqual([c.text for c in t.rows[0].cells], ["영역", "RAG", "근거"])
        self.assertEqual(t.cell(1, 2).text, "권한 지연 (R-001)")  # ** 기호 제거

    def test_separator_row_not_in_table(self):
        t = self.convert(SAMPLE).tables[0]
        self.assertEqual(len(t.rows), 3)

    def test_rag_cells_shaded(self):
        t = self.convert(SAMPLE).tables[0]
        fill = lambda c: c._element.tcPr.xpath("w:shd/@w:fill")[0]  # noqa: E731
        self.assertEqual(fill(t.cell(1, 1)), "FFEB9C")
        self.assertEqual(fill(t.cell(2, 1)), "C6EFCE")

    def test_bold_run_and_east_asian_font(self):
        t = self.convert(SAMPLE).tables[0]
        run = t.cell(1, 2).paragraphs[0].runs[0]
        self.assertTrue(run.bold)
        self.assertEqual(run._element.rPr.rFonts.get(md_to_docx.qn("w:eastAsia")), md_to_docx.FONT)

    def test_code_fence_is_stripped(self):
        # 첫 줄이 ```markdown 이어도 펜스로 인식해 벗긴다
        doc = self.convert("```markdown\n# 제목\n```")
        self.assertEqual(doc.paragraphs[0].text, "제목")
        self.assertNotIn("```", "\n".join(p.text for p in doc.paragraphs))

    def test_lists(self):
        doc = self.convert(SAMPLE)
        styles = [p.style.name for p in doc.paragraphs if p.text in ("성능 튜닝", "에스컬레이션")]
        self.assertEqual(styles, ["List Bullet", "List Number"])


if __name__ == "__main__":
    unittest.main()
