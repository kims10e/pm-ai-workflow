import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "workbook"
sys.path.insert(0, str(ROOT / "src"))

import workbook as wb  # noqa: E402

spec = importlib.util.spec_from_file_location("show_changes", ROOT / "scripts" / "show_changes.py")
show_changes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(show_changes)


class ShowChangesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.before, self.after = self.tmp / "before", self.tmp / "after"
        shutil.copytree(FIXTURE, self.before)
        shutil.copytree(FIXTURE, self.after)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_difference(self):
        self.assertEqual(show_changes.compare(self.before, self.after), [])

    def test_shows_changed_cells_and_added_rows(self):
        wb.apply_changeset({"week": 8, "changes": [
            {"table": "okr", "op": "update", "key": "KR1 핵심 리포트 Databricks 전환", "fields": {"current": 17}},
            {"table": "risks", "op": "update", "key": "R-002", "fields": {"status": "Closed", "owner": "RSA"}},
            {"table": "actions", "op": "add", "row": {"title": "신규 액션", "owner": "TBD"}},
        ]}, self.after, dry_run=False)
        text = "\n".join(show_changes.compare(self.before, self.after))
        self.assertIn("current: [-0-]{+17+}", text)
        self.assertIn("status: [-Open-]{+Closed+}", text)
        self.assertIn("+ 추가 A-003  신규 액션", text)
        self.assertNotIn("R-001", text)  # 바뀌지 않은 행은 보이지 않는다
        self.assertNotIn("\033", text)  # color=False 면 색상 코드가 없다

    def test_color_codes_only_when_requested(self):
        wb.apply_changeset({"changes": [{"table": "risks", "op": "update", "key": "R-002", "fields": {"status": "Closed"}}]},
                           self.after, dry_run=False)
        self.assertIn("\033[31m", "\n".join(show_changes.compare(self.before, self.after, color=True)))

    def test_compare_is_read_only(self):
        snapshot = {p.name: p.read_bytes() for p in self.after.glob("*")}
        show_changes.compare(self.before, self.after)
        self.assertEqual(snapshot, {p.name: p.read_bytes() for p in self.after.glob("*")})


if __name__ == "__main__":
    unittest.main()
