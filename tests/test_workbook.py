import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "workbook"  # 0일차 초기 상태. 실제 workbook/은 승인할 때마다 바뀌므로 쓰지 않는다
sys.path.insert(0, str(ROOT / "src"))

import workbook as wb  # noqa: E402


class WorkbookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dir = self.tmp / "workbook"
        shutil.copytree(FIXTURE, self.dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, name):
        return (self.dir / wb.TABLES[name]["file"]).read_bytes()

    # --- 읽기·쓰기
    def test_roundtrip_is_byte_identical_and_no_bom(self):
        for t in wb.TABLES:
            before = self.raw(t)
            wb.write_table(t, wb.read_table(t, self.dir), self.dir)
            self.assertEqual(before.replace(b"\r\n", b"\n"), self.raw(t), t)
            self.assertFalse(self.raw(t).startswith(b"\xef\xbb\xbf"), t)

    def test_korean_survives(self):
        self.assertEqual(wb.read_table("actions", self.dir)[0]["title"], "소스 DB 읽기 권한 요청")

    # --- dry_run
    def test_dry_run_changes_nothing(self):
        snapshot = {t: self.raw(t) for t in wb.TABLES}
        cs = {"week": 5, "changes": [{"table": "actions", "op": "update", "key": "A-002", "fields": {"status": "Done"}}]}
        res = wb.apply_changeset(cs, self.dir)  # 기본값 dry_run=True
        self.assertTrue(res.dry_run)
        self.assertEqual(len(res.applied), 1)
        self.assertEqual(snapshot, {t: self.raw(t) for t in wb.TABLES})
        self.assertEqual(wb.read_history(self.dir), [])

    # --- add
    def test_add_risk_autogenerates_id_and_score(self):
        cs = {"week": 5, "changes": [{"table": "risks", "op": "add",
              "row": {"title": "신규", "probability": "H", "impact": "H", "owner": "TPM", "status": "Open"}}]}
        wb.apply_changeset(cs, self.dir, dry_run=False)
        row = wb.read_table("risks", self.dir)[-1]
        self.assertEqual((row["id"], row["score"]), ("R-003", "9"))

    def test_add_duplicate_id_rejected(self):
        cs = {"changes": [{"table": "risks", "op": "add", "row": {"id": "R-001", "title": "x", "probability": "L", "impact": "L"}}]}
        with self.assertRaises(wb.WorkbookError):
            wb.apply_changeset(cs, self.dir, dry_run=False)

    def test_add_to_okr_rejected(self):
        cs = {"changes": [{"table": "okr", "op": "add", "row": {"key_result": "KR9"}}]}
        with self.assertRaises(wb.WorkbookError):
            wb.apply_changeset(cs, self.dir)

    # --- update
    def test_update_risk_recomputes_score(self):
        cs = {"changes": [{"table": "risks", "op": "update", "key": "R-002", "fields": {"impact": "H"}}]}
        wb.apply_changeset(cs, self.dir, dry_run=False)
        r = next(r for r in wb.read_table("risks", self.dir) if r["id"] == "R-002")
        self.assertEqual((r["impact"], r["score"]), ("H", "6"))

    def test_update_okr_by_key_result(self):
        kr = "KR1 핵심 리포트 Databricks 전환"
        cs = {"changes": [{"table": "okr", "op": "update", "key": kr, "fields": {"current": 8}}]}
        wb.apply_changeset(cs, self.dir, dry_run=False)
        row = next(r for r in wb.read_table("okr", self.dir) if r["key_result"] == kr)
        self.assertEqual(row["current"], "8")

    def test_update_missing_key_or_pk_change_rejected(self):
        for ch in (
            {"table": "actions", "op": "update", "key": "A-999", "fields": {"status": "Done"}},
            {"table": "actions", "op": "update", "key": "A-001", "fields": {"id": "A-777"}},
            {"table": "actions", "op": "update", "key": "A-001", "fields": {}},
        ):
            with self.assertRaises(wb.WorkbookError, msg=str(ch)):
                wb.apply_changeset({"changes": [ch]}, self.dir)

    # --- 원자성
    def test_one_bad_change_writes_nothing(self):
        snapshot = {t: self.raw(t) for t in wb.TABLES}
        cs = {"week": 5, "changes": [
            {"table": "actions", "op": "update", "key": "A-002", "fields": {"status": "Done"}},  # 정상
            {"table": "risks", "op": "update", "key": "R-404", "fields": {"status": "Closed"}},  # 오류
        ]}
        with self.assertRaises(wb.WorkbookError):
            wb.apply_changeset(cs, self.dir, dry_run=False)
        self.assertEqual(snapshot, {t: self.raw(t) for t in wb.TABLES})
        self.assertEqual(wb.read_history(self.dir), [])

    def test_unknown_table_op_column_rejected(self):
        for ch in (
            {"table": "nope", "op": "add", "row": {}},
            {"table": "actions", "op": "delete", "key": "A-001"},
            {"table": "actions", "op": "update", "key": "A-001", "fields": {"bogus": "x"}},
        ):
            with self.assertRaises(wb.WorkbookError, msg=str(ch)):
                wb.apply_changeset({"changes": [ch]}, self.dir)

    def test_invalid_risk_level_rejected(self):
        cs = {"changes": [{"table": "risks", "op": "add", "row": {"title": "x", "probability": "X", "impact": "H"}}]}
        with self.assertRaises(wb.WorkbookError):
            wb.apply_changeset(cs, self.dir)

    # --- 허용 값·기본값·파싱
    def test_invalid_status_rejected_on_add_and_update(self):
        for ch in (
            {"table": "actions", "op": "add", "row": {"title": "x", "status": "완료"}},
            {"table": "actions", "op": "update", "key": "A-001", "fields": {"status": "done"}},
            {"table": "issues", "op": "add", "row": {"title": "x", "priority": "Urgent"}},
            {"table": "milestones", "op": "update", "key": "M3", "fields": {"status": "Done "}},
        ):
            with self.assertRaises(wb.WorkbookError, msg=str(ch)):
                wb.apply_changeset({"changes": [ch]}, self.dir)

    def test_add_defaults_status(self):
        cs = {"changes": [
            {"table": "issues", "op": "add", "row": {"title": "권한 승인 지연", "priority": "High"}},
            {"table": "changes", "op": "add", "row": {"title": "필터 기본값 변경"}},
        ]}
        wb.apply_changeset(cs, self.dir, dry_run=False)
        self.assertEqual(wb.read_table("issues", self.dir)[-1]["status"], "Open")
        self.assertEqual(wb.read_table("changes", self.dir)[-1]["status"], "Requested")

    def test_existing_workbook_values_are_all_valid(self):
        for table, cols in wb.ENUMS.items():
            for row in wb.read_table(table, self.dir):
                for col, allowed in cols.items():
                    self.assertIn(row[col], allowed, f"{table}.{col}")

    def test_extra_keys_in_changes_are_ignored(self):
        cs = {"week": 5, "notes": ["메모"], "changes": [
            {"table": "actions", "op": "update", "key": "A-002", "fields": {"status": "Done"}, "reason": "메모 2줄"}]}
        wb.apply_changeset(cs, self.dir)

    def test_parse_changeset_strips_fences_and_prose(self):
        text = '설명입니다\n```json\n{"week": 5, "changes": []}\n```\n끝'
        self.assertEqual(wb.parse_changeset(text), {"week": 5, "changes": []})
        for bad in ("JSON 없음", '{"week": 5,'):
            with self.assertRaises(wb.WorkbookError):
                wb.parse_changeset(bad)

    # --- CSV 수식 주입(스프레드시트에서 열 때 수식으로 실행되는 값)
    def test_formula_like_values_are_rejected_on_add_and_update(self):
        for bad in ("=HYPERLINK(\"http://x\",\"y\")", "+cmd|' /C calc'!A0", "-1+2", "@SUM(A1)", "  =1+1", "\t=1", "- 글머리표처럼 시작"):
            with self.assertRaises(wb.WorkbookError, msg=repr(bad)):
                wb.apply_changeset({"changes": [{"table": "actions", "op": "add", "row": {"title": bad}}]}, self.dir)
            with self.assertRaises(wb.WorkbookError, msg=repr(bad)):
                wb.apply_changeset({"changes": [{"table": "actions", "op": "update", "key": "A-001", "fields": {"owner": bad}}]}, self.dir)
        self.assertEqual(wb.read_table("actions", self.dir), wb.read_table("actions", FIXTURE))  # 아무것도 반영되지 않음

    def test_numbers_and_normal_text_are_allowed(self):
        kr = "KR1 핵심 리포트 Databricks 전환"
        for ok_value in ("-1", "+5", "3.8", "8"):
            wb.apply_changeset({"changes": [{"table": "okr", "op": "update", "key": kr, "fields": {"current": ok_value}}]}, self.dir)
        wb.apply_changeset({"changes": [{"table": "actions", "op": "add", "row": {"title": "A=B 비교 (=는 중간에 있음)"}}]}, self.dir)

    def test_history_reason_is_neutralized(self):
        cs = {"week": 5, "changes": [{"table": "actions", "op": "add", "row": {"title": "x"}, "reason": "=1+1"}]}
        wb.apply_changeset(cs, self.dir, dry_run=False)
        self.assertEqual(wb.read_history(self.dir)[0]["reason"], "'=1+1")
        self.assertEqual(wb.csv_safe("정상 문장"), "정상 문장")
        self.assertEqual(wb.csv_safe("8"), "8")

    # --- 게이트·단계 표기는 정확히 허용 값만
    def test_gate_and_phase_must_be_canonical(self):
        row = {"id": "M0", "phase": "P0", "milestone": "Handover", "planned_week": "W0", "status": "Planned", "gate": "G0"}
        for field, bad in (("gate", "G00"), ("gate", "G0 "), ("gate", "g0"), ("gate", "G6"), ("phase", "P9"), ("phase", "p0")):
            with self.assertRaises(wb.WorkbookError, msg=f"{field}={bad!r}"):
                wb.apply_changeset({"changes": [{"table": "milestones", "op": "add", "row": dict(row, **{field: bad})}]}, self.dir)
        wb.apply_changeset({"changes": [{"table": "milestones", "op": "add", "row": row}]}, self.dir)  # 정확한 표기는 통과

    def test_add_description_shows_all_filled_fields(self):
        cs = {"changes": [{"table": "risks", "op": "add", "row": {
            "title": "신규 리스크", "probability": "H", "impact": "M", "owner": "TBD", "mitigation": "대응안", "status": "Open"}}]}
        text = wb.apply_changeset(cs, self.dir).applied[0].describe()
        for expected in ("신규 리스크", "probability=H", "impact=M", "owner=TBD", "mitigation=대응안", "score=6"):
            self.assertIn(expected, text)

    # --- 이력
    def test_history_recorded_and_accumulates(self):
        for week in (5, 6):
            cs = {"week": week, "changes": [
                {"table": "actions", "op": "add", "row": {"title": f"W{week} 액션"}, "reason": f"W{week} 메모 1줄"}]}
            wb.apply_changeset(cs, self.dir, dry_run=False, now=datetime(2026, 11, 22, 9, 0, 0))
        hist = wb.read_history(self.dir)
        self.assertEqual([(h["week"], h["key"], h["op"]) for h in hist], [("5", "A-003", "add"), ("6", "A-004", "add")])
        self.assertEqual(hist[0]["applied_at"], "2026-11-22 09:00:00")
        self.assertIn("W5 액션", hist[0]["after"])  # 한글이 \u 이스케이프 없이 저장
        self.assertEqual([h["reason"] for h in hist], ["W5 메모 1줄", "W6 메모 1줄"])  # 변경 근거가 이력에 남음


if __name__ == "__main__":
    unittest.main()
