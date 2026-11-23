import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "workbook"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pm_agent  # noqa: E402
import quality_gate as qg  # noqa: E402
import workbook as wb  # noqa: E402
from test_approval_flow import ScriptedBot  # noqa: E402  (테스트 클래스는 가져오지 않는다)

BASE = wb.load_all(FIXTURE)  # 0일차 초기 상태


def data():
    return copy.deepcopy(BASE)


def row(d, table, key, **fields):
    key_col = wb.TABLES[table]["key"]
    r = next(r for r in d[table] if r[key_col] == key)
    r.update(fields)
    return r


def check(d=None, week=5, history=(), memo=(5,), approved=(5,)):
    return qg.check(d or data(), list(history), set(memo), set(approved), week)


def get(findings, key):
    return next(f for f in findings if f.key == key)


class EventTest(unittest.TestCase):
    def test_baseline_week5(self):
        f = check()
        levels = {x.key: x.level for x in f}
        self.assertEqual(
            levels,
            {"E1": "UNKNOWN", "E2": "PASS", "E3": "PASS", "E4": "N/A",
             "R1": "WARN", "R2": "PASS", "R3": "PASS", "R4": "PASS", "R5": "PASS", "R6": "PASS", "R7": "PASS"},
        )

    def test_e1_handover(self):
        ms = {"id": "M0", "phase": "P0", "milestone": "Handover", "planned_week": "W3", "status": "Done", "gate": "G0"}
        d = data()
        d["milestones"].insert(0, dict(ms))
        self.assertEqual(get(check(d), "E1").level, "PASS")
        row(d, "milestones", "M0", status="Planned")
        self.assertEqual(get(check(d, week=5), "E1").level, "FAIL")
        row(d, "milestones", "M0", planned_week="W9")
        self.assertEqual(get(check(d, week=5), "E1").level, "N/A")

    def test_week_zero_is_a_valid_planned_week(self):
        # 회귀: W0 을 '주차 없음'으로 취급해 미완료 Handover 를 놓치던 문제
        d = data()
        d["milestones"].insert(0, {"id": "M0", "phase": "P0", "milestone": "Handover", "planned_week": "W0",
                                   "status": "Planned", "gate": "G0"})
        self.assertEqual(get(check(d, week=7), "E1").level, "FAIL")
        row(d, "actions", "A-001", due="2026-W00")
        self.assertIn("A-001", " ".join(get(check(d, week=7), "R1").items))

    def test_e1_unknown_is_not_pass(self):
        f = get(check(), "E1")
        self.assertEqual(f.level, "UNKNOWN")
        self.assertIn("확인할 수 없음", f.detail)

    def test_e2_gate_order(self):
        d = data()
        row(d, "milestones", "M2", status="Planned")
        row(d, "milestones", "M3", status="In Progress")
        f = get(check(d), "E2")
        self.assertEqual(f.level, "FAIL")
        self.assertIn("M3(G3)", f.items[0])
        self.assertIn("M2(G2)", f.items[0])

    def test_e2_same_gate_does_not_block(self):
        d = data()
        row(d, "milestones", "M4", status="In Progress")  # M3(G3) 미완료여도 같은 G3 안의 진행은 위반 아님
        self.assertEqual(get(check(d), "E2").level, "PASS")

    def test_e3_continuity(self):
        self.assertEqual(get(check(week=7, memo=(5, 6, 7), approved=(5, 6, 7)), "E3").level, "PASS")
        f = get(check(week=7, memo=(5, 6, 7), approved=(5, 6)), "E3")
        self.assertEqual(f.level, "FAIL")
        self.assertIn("7주차: 메모는 있으나", f.items[0])
        f = get(check(week=7, memo=(5, 7), approved=(5, 7)), "E3")
        self.assertEqual((f.level, f.items), ("WARN", ["6주차: 주간 업데이트 메모 없음"]))
        self.assertEqual(get(check(week=4, memo=(5,), approved=()), "E3").level, "N/A")
        self.assertEqual(get(check(memo=(), approved=()), "E3").level, "UNKNOWN")
        self.assertEqual(get(check(week=8, memo=(5, 6, 7), approved=(5, 6, 7)), "E3").level, "WARN")  # 8주차 메모 누락

    def test_e4_closing(self):
        d = data()
        self.assertEqual(get(check(d), "E4").level, "N/A")
        row(d, "milestones", "M7", status="In Progress")
        f = get(check(d), "E4")
        self.assertEqual(f.level, "FAIL")
        self.assertIn("M6", f.items[0])
        row(d, "milestones", "M6", status="Done")
        row(d, "milestones", "M7", status="Done")
        self.assertEqual(get(check(d), "E4").level, "PASS")
        d = data()
        self.assertEqual(get(check(d, week=17), "E4").level, "WARN")  # 종료 계획 주차(W16)가 지남


class RegularTest(unittest.TestCase):
    def test_r1_overdue_actions(self):
        self.assertEqual(get(check(week=4), "R1").level, "PASS")  # 기한(W4)과 같은 주는 아직 초과 아님
        f = get(check(week=5), "R1")
        self.assertEqual(f.level, "WARN")
        self.assertEqual(len(f.items), 1)
        self.assertIn("A-001", f.items[0])
        self.assertEqual(len(get(check(week=7), "R1").items), 2)
        d = data()
        row(d, "actions", "A-001", status="Done")
        self.assertEqual(get(check(d, week=5), "R1").level, "PASS")

    def test_r2_owner_tbd_only_for_open_items(self):
        d = data()
        row(d, "actions", "A-002", owner="TBD")
        row(d, "actions", "A-001", owner="", status="Done")  # 끝난 항목은 제외
        d["issues"].append({"id": "I-001", "title": "x", "raised": "2026-W05", "owner": "TBD", "priority": "Low",
                            "status": "Open", "resolution": ""})
        f = get(check(d), "R2")
        self.assertEqual(f.level, "WARN")
        self.assertEqual(len(f.items), 2)
        self.assertTrue(any("A-002" in i for i in f.items) and any("I-001" in i for i in f.items))

    def test_r3_risk_owner(self):
        d = data()
        row(d, "risks", "R-001", owner="TBD")
        f = get(check(d), "R3")
        self.assertEqual(f.level, "WARN")
        self.assertIn("점수 6 이상 1건", f.detail)
        row(d, "risks", "R-001", status="Closed")
        self.assertEqual(get(check(d), "R3").level, "PASS")

    def test_r4_risk_issue_link(self):
        d = data()
        row(d, "risks", "R-002", status="Occurred")
        self.assertEqual(get(check(d), "R4").level, "WARN")  # 연결된 이슈 없음
        issue = {"id": "I-001", "title": "[R-002] 야간 배치 성능 목표 미달", "raised": "2026-W05", "owner": "RSA",
                 "priority": "High", "status": "Open", "resolution": ""}
        d["issues"].append(dict(issue))
        self.assertEqual(get(check(d), "R4").level, "PASS")
        # R-0021 같은 다른 번호를 R-002 와 혼동하지 않는다
        d["issues"][0]["title"] = "[R-0021] 다른 리스크"
        self.assertEqual(get(check(d), "R4").level, "WARN")
        # 닫힌 리스크에 열린 이슈가 남아 있으면 경고
        d2 = data()
        row(d2, "risks", "R-001", status="Closed")
        d2["issues"].append(dict(issue, title="[R-001] 권한 지연"))
        f = get(check(d2), "R4")
        self.assertEqual(f.level, "WARN")
        self.assertIn("Closed", f.items[0])

    def test_r5_stale_high_issue(self):
        d = data()
        d["issues"].append({"id": "I-001", "title": "x", "raised": "2026-W05", "owner": "RSA", "priority": "High",
                            "status": "In Progress", "resolution": ""})
        self.assertEqual(get(check(d, week=6), "R5").level, "PASS")
        f = get(check(d, week=7), "R5")
        self.assertEqual(f.level, "WARN")
        self.assertIn("2주째", f.items[0])
        row(d, "issues", "I-001", priority="Medium")
        self.assertEqual(get(check(d, week=7), "R5").level, "PASS")
        row(d, "issues", "I-001", priority="High", status="Resolved")
        self.assertEqual(get(check(d, week=7), "R5").level, "PASS")

    def test_r6_stale_change_request(self):
        d = data()
        d["changes"].append({"id": "C-001", "title": "필터 변경", "requested_by": "BI팀", "impact_scope": "",
                             "impact_schedule": "", "impact_cost": "", "status": "Requested"})
        hist = [{"week": "5", "table": "changes", "op": "add", "key": "C-001"}]
        self.assertEqual(get(check(d, week=6, history=hist), "R6").level, "PASS")
        f = get(check(d, week=7, history=hist), "R6")
        self.assertEqual(f.level, "WARN")
        self.assertIn("W5 접수", f.items[0])
        self.assertEqual(get(check(d, week=7), "R6").level, "PASS")  # 접수 시점을 모르면 판단하지 않는다
        row(d, "changes", "C-001", status="Approved")
        self.assertEqual(get(check(d, week=7, history=hist), "R6").level, "PASS")

    def test_r7_milestone_overdue(self):
        f = get(check(week=7), "R7")
        self.assertEqual(f.level, "FAIL")  # M3(G3, 계획 W6)가 Planned 그대로 = 고객 리뷰 누락 의심
        self.assertIn("고객 리뷰 누락 의심", f.items[0])
        self.assertEqual(get(check(week=6), "R7").level, "PASS")  # 계획 주차와 같은 주는 아직 아님
        d = data()
        row(d, "milestones", "M3", status="In Progress")
        self.assertEqual(get(check(d, week=7), "R7").level, "WARN")
        row(d, "milestones", "M3", status="Done")
        self.assertEqual(get(check(d, week=7), "R7").level, "PASS")
        row(d, "milestones", "M3", status="Delayed")
        self.assertEqual(get(check(d, week=7), "R7").level, "PASS")  # 지연으로 표시했으면 누락이 아님


class OutputTest(unittest.TestCase):
    def test_sorted_by_severity_and_counts(self):
        f = check(week=7, memo=(5, 6, 7), approved=(5, 6))
        self.assertEqual([x.level for x in f], sorted((x.level for x in f), key=lambda lv: qg.LEVELS.index(lv)))
        c = qg.counts(f)
        self.assertEqual(sum(c.values()), 11)
        self.assertGreaterEqual(c["FAIL"], 2)  # E3, R7

    def test_markdown_and_telegram(self):
        f = check(week=7, memo=(5, 6, 7), approved=(5, 6))
        md = qg.render_markdown(f, 7)
        for expected in ("# Quality Gate 점검 — 7주차 기준", "## 체크 이벤트", "## 정기 점검", "## 근거 항목",
                         "UNKNOWN", "AI 호출 없음"):
            self.assertIn(expected, md)
        text = qg.format_telegram(f, 7)
        self.assertLessEqual(len(text), 3900)
        self.assertIn("FAIL", text)
        self.assertIn("E3", text)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIXTURE, self.tmp / "workbook")
        shutil.copytree(ROOT / "data" / "updates", self.tmp / "data" / "updates")
        self.paths = pm_agent.Paths(self.tmp)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_saves_report_and_returns_1_on_fail(self):
        rc = qg.run_quality(7, self.paths, log=self.logs.append)
        self.assertEqual(rc, 1)  # 메모 5~7은 있으나 승인·반영 기록이 없으므로 E3 FAIL
        out = self.tmp / "outputs" / "quality" / "week07.md"
        self.assertTrue(out.exists())
        self.assertIn("E3", out.read_text(encoding="utf-8"))
        self.assertTrue(any("FAIL" in line for line in self.logs))

    def test_collect_context_reads_history_and_final_dirs(self):
        (self.tmp / "workbook" / wb.HISTORY_FILE).write_text(
            "applied_at,week,table,op,key,before,after,reason\n2026-11-22 09:00:00,5,actions,add,A-003,,{},r\n",
            encoding="utf-8")
        (self.tmp / "outputs" / "final" / "week06").mkdir(parents=True)
        _, history, memo, approved = qg.collect_context(self.paths)
        self.assertEqual(memo, {5, 6, 7})
        self.assertEqual(approved, {5, 6})  # 5=이력, 6=확정 폴더
        self.assertEqual(len(history), 1)

    def test_notify_sends_one_message(self):
        bot = ScriptedBot([])
        qg.run_quality(7, self.paths, notify=True, bot=bot, log=self.logs.append)
        self.assertEqual(len(bot.texts()), 1)
        self.assertIn("Quality Gate", bot.texts()[0])

    def test_run_does_not_modify_workbook(self):
        before = {p.name: p.read_bytes() for p in (self.tmp / "workbook").glob("*")}
        qg.run_quality(7, self.paths, log=self.logs.append)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.tmp / "workbook").glob("*")})


if __name__ == "__main__":
    unittest.main()
