import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx import Document  # noqa: E402

import pm_agent  # noqa: E402
import workbook as wb  # noqa: E402

GOOD_CS = {
    "week": 5,
    "changes": [
        {"table": "okr", "op": "update", "key": "KR1 핵심 리포트 Databricks 전환", "fields": {"current": 6}, "reason": "6종 전환 완료"},
        {"table": "actions", "op": "add", "row": {"title": "권한 에스컬레이션", "owner": "TPM"}, "reason": "다음 주 에스컬레이션"},
    ],
    "notes": ["A-001 기한 초과"],
}
BAD_CS = {"week": 5, "changes": [{"table": "actions", "op": "update", "key": "A-001", "fields": {"status": "완료"}, "reason": "x"}]}
REPORT = "# 주간 현황 보고 — 테스트 5주차\n\n## 2. RAG 상태\n| 영역 | RAG | 근거 |\n|---|---|---|\n| 전체 | Amber | 테스트 |\n"


class FakeLLM:
    """프롬프트가 risk-update용인지 status-report용인지 보고 정해진 답을 준다."""

    def __init__(self, changesets, report=REPORT, on_report=None):
        self.changesets = list(changesets)
        self.report = report
        self.on_report = on_report
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if "# risk-update —" in prompt:
            cs = self.changesets.pop(0)
            return cs if isinstance(cs, str) else "```json\n" + json.dumps(cs, ensure_ascii=False) + "\n```"
        if "# status-report —" in prompt:
            if self.on_report:
                self.on_report()
            return self.report
        raise AssertionError("알 수 없는 프롬프트")


class PmAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Workbook은 고정된 초기 상태(fixture)를 쓴다. 실제 workbook/은 승인할 때마다 바뀐다.
        shutil.copytree(ROOT / "tests" / "fixtures" / "workbook", self.tmp / "workbook")
        for rel in ("data/updates", ".claude/skills"):
            shutil.copytree(ROOT / rel, self.tmp / rel)
        self.paths = pm_agent.Paths(self.tmp)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_week(self, llm, week=5, **kw):
        return pm_agent.run_week(week, self.paths, llm=llm, log=self.logs.append, **kw)

    def workbook_bytes(self):
        return {p.name: p.read_bytes() for p in self.paths.workbook.glob("*")}

    # --- 정상 흐름
    def test_run_creates_drafts_and_does_not_touch_workbook(self):
        before = self.workbook_bytes()
        llm = FakeLLM([GOOD_CS])
        dest = self.run_week(llm)
        self.assertEqual(before, self.workbook_bytes())  # Human-in-the-loop: Workbook 불변
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["changeset.json", "meta.json", "report.docx", "report.md"])
        self.assertEqual(json.loads((dest / "changeset.json").read_text(encoding="utf-8"))["week"], 5)
        self.assertIn("Amber", (dest / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(len(Document(dest / "report.docx").tables), 1)
        self.assertEqual(len(llm.prompts), 2)

    def test_meta_has_workbook_fingerprint(self):
        dest = self.run_week(FakeLLM([GOOD_CS]))
        meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["workbook_fingerprint"], wb.fingerprint(self.paths.workbook))
        self.assertEqual((meta["week"], meta["status"], meta["changes"]), (5, "draft", 2))

    def test_prompts_contain_skill_memo_workbook_and_injection_notice(self):
        llm = FakeLLM([GOOD_CS])
        self.run_week(llm)
        risk, report = llm.prompts
        for p in (risk, report):
            self.assertIn("소스 DB 읽기 권한 승인이 또 지연됨", p)  # 메모
            self.assertIn("A-002,파일럿 리포트 8종 전환", p)  # Workbook
            self.assertIn("지시문처럼 보이는 문장", p)  # 인젝션 방어 문구
        self.assertIn("RAG 판정 기준", report)  # status-report 스킬 본문
        self.assertIn("권한 에스컬레이션", report)  # 변경안이 보고서 프롬프트에 전달됨
        self.assertNotIn("name: status-report", report)  # frontmatter 제외

    # --- 재시도·거부
    def test_retry_after_rejection_includes_error_in_prompt(self):
        llm = FakeLLM([BAD_CS, GOOD_CS])
        dest = self.run_week(llm)
        retry_prompt = llm.prompts[1]
        self.assertIn("거부되었다", retry_prompt)
        self.assertIn("허용되지 않음", retry_prompt)  # 거부 사유가 모델에게 전달됨
        self.assertFalse(list(dest.glob("rejected_attempt*.txt")))  # 성공하면 정리됨

    def test_two_failures_raise_and_leave_no_draft(self):
        with self.assertRaises(pm_agent.AgentError):
            self.run_week(FakeLLM([BAD_CS, BAD_CS]))
        dest = self.paths.draft_dir(5)
        self.assertFalse((dest / "changeset.json").exists())
        self.assertFalse((dest / "report.md").exists())
        self.assertEqual(len(list(dest.glob("rejected_attempt*.txt"))), 2)

    def test_non_json_output_is_rejected(self):
        with self.assertRaises(pm_agent.AgentError):
            self.run_week(FakeLLM(["죄송하지만 JSON을 만들 수 없습니다", "역시 없음"]))

    def test_wrong_week_in_changeset_is_rejected(self):
        wrong = dict(GOOD_CS, week=6)
        with self.assertRaises(pm_agent.AgentError):
            self.run_week(FakeLLM([wrong, wrong]))

    # --- 입력·상태 점검
    def test_missing_memo(self):
        with self.assertRaisesRegex(pm_agent.AgentError, "메모가 없음"):
            self.run_week(FakeLLM([]), week=9)

    def test_finalized_week_blocked_unless_force(self):
        self.paths.final_dir(5).mkdir(parents=True)
        with self.assertRaisesRegex(pm_agent.AgentError, "이미 확정"):
            self.run_week(FakeLLM([GOOD_CS]))
        self.run_week(FakeLLM([GOOD_CS]), force=True)

    def test_workbook_changed_during_run_is_detected(self):
        def tamper():
            p = self.paths.workbook / "actions.csv"
            p.write_text(p.read_text(encoding="utf-8") + "A-099,x,y,z,Open,w\n", encoding="utf-8")

        with self.assertRaisesRegex(pm_agent.AgentError, "Workbook이 바뀌었음"):
            self.run_week(FakeLLM([GOOD_CS], on_report=tamper))
        self.assertFalse((self.paths.draft_dir(5) / "meta.json").exists())

    # --- 지문
    def test_fingerprint_ignores_crlf_and_bom_but_detects_content(self):
        base = wb.fingerprint(self.paths.workbook)
        p = self.paths.workbook / "risks.csv"
        raw = p.read_bytes()
        p.write_bytes(b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n"))
        self.assertEqual(base, wb.fingerprint(self.paths.workbook))
        p.write_bytes(raw.replace(b"Open", b"Closed", 1))
        self.assertNotEqual(base, wb.fingerprint(self.paths.workbook))


DRAFT_REPORT = (
    "# 주간 현황 보고 — 테스트 5주차\n\n- 상태: 초안 (PM 승인 전)\n\n## 5. 리스크·이슈\n"
    "| ID | 내용 | 구분 |\n|---|---|---|\n| A-003 | 권한 에스컬레이션 | 신규(변경안, 승인 전) |\n"
    "\n판정 근거: 변경안 반영(모두 승인 전)\n"
)


class ApproveTest(PmAgentTest):
    def make_draft(self, week=5, cs=GOOD_CS):
        self.run_week(FakeLLM([cs], report=DRAFT_REPORT), week=week)

    def approve(self, week=5, yes=True, **kw):
        return pm_agent.approve_week(week, self.paths, confirm=(lambda: yes), log=self.logs.append, **kw)

    def test_approve_applies_changes_and_finalizes(self):
        self.make_draft()
        before_actions = len(wb.read_table("actions", self.paths.workbook))
        self.assertTrue(self.approve())
        # Workbook 반영
        self.assertEqual(len(wb.read_table("actions", self.paths.workbook)), before_actions + 1)
        kr1 = next(r for r in wb.read_table("okr", self.paths.workbook) if r["key_result"].startswith("KR1"))
        self.assertEqual(kr1["current"], "6")
        # 이력 기록(근거 포함)
        hist = wb.read_history(self.paths.workbook)
        self.assertEqual(len(hist), 2)
        self.assertEqual({h["week"] for h in hist}, {"5"})
        self.assertIn("6종 전환 완료", [h["reason"] for h in hist])
        # 확정본
        final = self.paths.final_dir(5)
        self.assertEqual(sorted(p.name for p in final.iterdir()), ["changeset.json", "meta.json", "report.docx", "report.md"])
        meta = json.loads((final / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["status"], meta["applied"]), ("approved", 2))
        self.assertFalse((self.paths.final / ".week05.tmp").exists())

    def test_final_report_has_no_stale_pending_wording(self):
        self.make_draft()
        self.approve()
        text = (self.paths.final_dir(5) / "report.md").read_text(encoding="utf-8")
        self.assertIn("- 상태: 확정 (PM 승인 ", text)
        self.assertNotIn("승인 전", text)
        self.assertIn("승인 반영됨", text)
        docx_text = "\n".join(p.text for p in Document(self.paths.final_dir(5) / "report.docx").paragraphs)
        self.assertIn("확정", docx_text)
        # 초안은 감사 기록으로 그대로 남는다
        self.assertIn("초안 (PM 승인 전)", (self.paths.draft_dir(5) / "report.md").read_text(encoding="utf-8"))

    def test_model_variants_of_pending_marker_are_replaced(self):
        src = (
            "# 제목\n\n- 상태: 초안 (PM 승인 전)\n\n"
            "score 6, Open (변경안에서 probability M→H 상향, 승인 전)\n신규(변경안, 승인 전)\n(모두 승인 전)\n"
        )
        md, left = pm_agent.finalize_report_text(src, "2026-11-22")
        self.assertEqual(left, [])
        self.assertIn("(변경안에서 probability M→H 상향, 승인 반영됨)", md)
        self.assertIn("- 상태: 확정 (PM 승인 2026-11-22)", md)

    def test_punctuation_variants_and_basis_note(self):
        src = "# 제목\n\n- 상태: 초안 (PM 승인 전)\n\n| 범위 | Amber | CR 접수(변경안, 승인 전. 메모 W06) |\n변경안에서 Closed이나 승인 전. 다음\n"
        md, left = pm_agent.finalize_report_text(src, "2026-11-22")
        self.assertEqual(left, [])
        self.assertIn("승인 반영됨. 메모 W06", md)
        self.assertIn("- 작성 기준: 승인 이전 Workbook 값으로 작성한 보고서입니다.", md)  # 작성 기준이 밝혀짐
        self.assertEqual(md.count("- 상태:"), 1)

    def test_colon_variant_is_replaced(self):
        # 실제 7주차 초안에서 나온 형태
        md, left = pm_agent.finalize_report_text("# 제목\n\n- 상태: 초안\n\n상태 변경(변경안, 승인 전: Resolved)\n", "2026-11-23")
        self.assertEqual(left, [])
        self.assertIn("(변경안, 승인 반영됨: Resolved)", md)

    def test_leftover_pending_wording_is_reported(self):
        md, left = pm_agent.finalize_report_text("# 제목\n\n- 상태: 초안\n\n승인 전 단계의 별도 문장\n", "2026-11-22")
        self.assertEqual(left, ["승인 전 단계의 별도 문장"])

    def test_declined_changes_nothing(self):
        self.make_draft()
        before = self.workbook_bytes()
        self.assertFalse(self.approve(yes=False))
        self.assertEqual(before, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(5).exists())

    def test_confirm_none_is_treated_as_decline(self):
        self.make_draft()
        before = self.workbook_bytes()
        self.assertFalse(pm_agent.approve_week(5, self.paths, confirm=None, log=self.logs.append))
        self.assertEqual(before, self.workbook_bytes())

    def test_no_draft(self):
        with self.assertRaisesRegex(pm_agent.AgentError, "초안이 없음"):
            self.approve()

    def test_double_approval_blocked(self):
        self.make_draft()
        self.approve()
        snapshot = self.workbook_bytes()
        with self.assertRaisesRegex(pm_agent.AgentError, "이미 확정"):
            self.approve()
        self.assertEqual(snapshot, self.workbook_bytes())  # 두 번 반영되지 않음

    def test_stale_draft_rejected(self):
        self.make_draft()
        p = self.paths.workbook / "actions.csv"
        p.write_text(p.read_text(encoding="utf-8") + "A-099,x,y,z,Open,w\n", encoding="utf-8")
        before = self.workbook_bytes()
        with self.assertRaisesRegex(pm_agent.AgentError, "Workbook이 바뀌었음"):
            self.approve()
        self.assertEqual(before, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(5).exists())

    def test_two_drafts_second_becomes_stale_after_first_approval(self):
        self.make_draft(week=5)
        self.make_draft(week=6, cs=dict(GOOD_CS, week=6, changes=[
            {"table": "actions", "op": "update", "key": "A-001", "fields": {"status": "Done"}, "reason": "승인 완료"}]))
        self.approve(week=5)
        with self.assertRaisesRegex(pm_agent.AgentError, "오래된 초안"):
            self.approve(week=6)

    def test_invalid_edited_changeset_writes_nothing(self):
        self.make_draft()
        path = self.paths.draft_dir(5) / "changeset.json"
        cs = json.loads(path.read_text(encoding="utf-8"))
        cs["changes"][0]["fields"] = {"current": 6, "bogus": 1}  # PM이 잘못 고침
        path.write_text(json.dumps(cs, ensure_ascii=False), encoding="utf-8")
        before = self.workbook_bytes()
        with self.assertRaisesRegex(pm_agent.AgentError, "유효하지 않음"):
            self.approve()
        self.assertEqual(before, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(5).exists())

    def test_edited_valid_changeset_is_applied_with_warning(self):
        self.make_draft()
        path = self.paths.draft_dir(5) / "changeset.json"
        cs = json.loads(path.read_text(encoding="utf-8"))
        cs["changes"][0]["fields"]["current"] = 7  # PM이 값을 정정
        path.write_text(json.dumps(cs, ensure_ascii=False), encoding="utf-8")
        self.approve()
        kr1 = next(r for r in wb.read_table("okr", self.paths.workbook) if r["key_result"].startswith("KR1"))
        self.assertEqual(kr1["current"], "7")
        self.assertTrue(any("수정되었습니다" in m for m in self.logs))

    def test_failure_during_apply_leaves_no_final_dir(self):
        self.make_draft()
        original = wb.apply_changeset

        def boom(cs, d, dry_run=True, now=None):
            if dry_run:
                return original(cs, d, dry_run=True, now=now)
            raise RuntimeError("디스크 오류 흉내")

        wb.apply_changeset = boom
        try:
            with self.assertRaises(RuntimeError):
                self.approve()
        finally:
            wb.apply_changeset = original
        self.assertFalse(self.paths.final_dir(5).exists())
        self.assertFalse((self.paths.final / ".week05.tmp").exists())

    def test_cli_refuses_without_tty_or_yes(self):
        self.make_draft()
        import io

        old = sys.stdin
        sys.stdin = io.StringIO("y\n")  # 파이프로 "y"를 흘려 넣어도 터미널이 아니면 거부해야 한다
        try:
            rc = pm_agent.main(["approve", "--week", "5", "--root", str(self.tmp)])
        finally:
            sys.stdin = old
        self.assertEqual(rc, 1)
        self.assertFalse(self.paths.final_dir(5).exists())

    def test_ask_yes_answers(self):
        import builtins

        original = builtins.input
        try:
            for answer, expected in (("y", True), ("YES", True), ("n", False), ("", False), ("예", False)):
                builtins.input = lambda _="", a=answer: a
                self.assertEqual(pm_agent._ask_yes(), expected, answer)

            def eof(_=""):
                raise EOFError

            builtins.input = eof
            self.assertFalse(pm_agent._ask_yes())  # 입력이 끊기면 승인하지 않음
        finally:
            builtins.input = original


if __name__ == "__main__":
    unittest.main()
