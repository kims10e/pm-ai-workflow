import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from docx import Document  # noqa: E402

import approval_flow as af  # noqa: E402
import intake  # noqa: E402
import pm_agent  # noqa: E402
import quality_gate as qg  # noqa: E402
import workbook as wb  # noqa: E402
from test_approval_flow import ScriptedBot, cb  # noqa: E402  (테스트 클래스는 가져오지 않는다)

OKR = wb.read_table("okr", ROOT / "tests" / "fixtures" / "workbook")

GOOD_SOW = {
    "extraction": {
        "scope_in": ["데이터 이관", "ETL 전환"],
        "scope_out": ["신규 리포트 개발"],
        "assumptions": ["고객이 2주 안에 소스 DB 읽기 권한 제공"],
        "acceptance_criteria": ["이관 전후 리포트 수치 일치"],
        "phases": [{"phase": "P1", "weeks": 1, "deliverables": ["Charter", "공동 OKR 표"]},
                   {"phase": "P2", "weeks": None, "deliverables": ["마이그레이션 계획서"]}],
        "governance": ["주간 현황 보고(금)"],
        "review_and_change_rules": ["인도품목 검토 10영업일", "변경은 Change Request로 승인"],
        "ambiguities": ["수치 일치의 허용 오차·반올림 기준이 SOW에 없음"],
    },
    "handover_checklist": [
        {"item": f"확인 항목 {i}", "source": "SOW 2항", "check_with": "영업·프리세일즈"} for i in range(1, 7)
    ] + [
        {"item": "반올림 기준 확인", "source": "SOW에 명시 없음(확인 필요)", "check_with": "고객"},
        {"item": "배치 성능 목표 값 확인", "source": "SOW 4항", "check_with": "내부(딜리버리)"},
    ],
    "changeset": {"week": 0, "changes": [
        {"table": "milestones", "op": "add", "reason": "G0 마일스톤이 Workbook에 없음",
         "row": {"id": "M0", "phase": "P0", "milestone": "Handover 완료(영업→딜리버리 인수인계)",
                 "planned_week": "W0", "status": "Planned", "gate": "G0"}},
        {"table": "risks", "op": "add", "reason": "SOW 2항 가정 위반 가능성(추정)",
         "row": {"title": "BI 도구 버전 변경 시 리포트 재연결 범위 증가", "probability": "L", "impact": "M",
                 "owner": "TBD", "mitigation": "버전 고정 확인", "status": "Open"}},
    ]},
    "notes": ["Handover 완료 여부는 입력에 없어 Planned 로 제안. 마쳤다면 PM이 Done 으로 변경"],
}

GOOD_CHARTER = {
    "charter": {
        "purpose": "레거시 DW를 Databricks로 이관한다", "background": "야간 배치 ETL 운영 중인 유통사(가상)",
        "objectives": ["분석 플랫폼 현대화"], "scope_in": ["데이터 이관"], "scope_out": ["신규 리포트 개발"],
        "success_criteria": ["리포트 40종 전환"], "assumptions": ["소스 DB 권한 제공"], "constraints": [],
        "roles": [{"role": "고객 PM", "responsibility": "확인 필요"}, {"role": "공급사 TPM", "responsibility": "프로젝트 관리"}],
        "governance": ["주간 현황 보고"],
        "milestones": [{"id": "M1", "name": "Kickoff 및 OKR 합의", "week": "W1", "gate": "G1"}],
        "approvals": ["고객 PM", "공급사 TPM"],
    },
    "okr": [
        {"objective": r["objective"], "key_result": r["key_result"], "success_metric": f"{r['target']}{r['unit']} 달성",
         "dependency": "없음", "target_date": "W16", "priority": r["priority"]} for r in OKR
    ],
    "notes": ["OKR 목표 일정은 고객과 합의 필요"],
}


class FakeLLM:
    def __init__(self, sow=(GOOD_SOW,), charter=(GOOD_CHARTER,), on_charter=None):
        self.sow, self.charter, self.on_charter = list(sow), list(charter), on_charter
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if "# sow-intake —" in prompt:
            out = self.sow.pop(0)
        elif "# charter-okr —" in prompt:
            if self.on_charter:
                self.on_charter()
            out = self.charter.pop(0)
        else:
            raise AssertionError("알 수 없는 프롬프트")
        return out if isinstance(out, str) else "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"


def mutated(base, fn):
    obj = copy.deepcopy(base)
    fn(obj)
    return obj


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tests" / "fixtures" / "workbook", self.tmp / "workbook")
        for rel in ("data", ".claude/skills"):
            shutil.copytree(ROOT / rel, self.tmp / rel)
        self.paths = pm_agent.Paths(self.tmp)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def intake(self, llm=None, **kw):
        llm = llm or FakeLLM()
        return intake.run_intake(self.paths, llm=llm, log=self.logs.append, **kw), llm

    def workbook_bytes(self):
        return {p.name: p.read_bytes() for p in self.paths.workbook.glob("*")}


class RunIntakeTest(Base):
    def test_creates_documents_and_leaves_workbook_untouched(self):
        before = self.workbook_bytes()
        dest, llm = self.intake()
        self.assertEqual(before, self.workbook_bytes())
        names = sorted(p.name for p in dest.iterdir())
        self.assertEqual(names, ["changeset.json", "charter.docx", "charter.md", "extraction.json", "handover.docx",
                                 "handover.md", "meta.json", "okr.docx", "okr.md"])
        meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["week"], meta["status"], meta["documents"], meta["changes"]), (0, "draft", intake.DOCUMENTS, 2))
        self.assertEqual(meta["workbook_fingerprint"], wb.fingerprint(self.paths.workbook))
        cs = json.loads((dest / "changeset.json").read_text(encoding="utf-8"))
        self.assertEqual(cs["week"], 0)
        self.assertEqual(len(llm.prompts), 2)

    def test_rendered_documents(self):
        dest, _ = self.intake()
        handover = (dest / "handover.md").read_text(encoding="utf-8")
        self.assertIn("# Handover 체크리스트 — Aster Retail(가상) 레거시 DW → Databricks 마이그레이션", handover)
        self.assertIn("- 상태: 초안 (PM 승인 전)", handover)
        self.assertEqual(handover.count("| 미확인 |"), 8)  # 확인 항목 8개
        self.assertIn("SOW에 명시 없음(확인 필요)", handover)
        self.assertIn("M0 Handover 완료", handover)
        self.assertIn("Done으로 바꾸세요", handover)
        self.assertIn("| BI 도구 버전 변경 시 리포트 재연결 범위 증가 | L | M | 2 |", handover)  # 점수 = 확률×영향
        charter = (dest / "charter.md").read_text(encoding="utf-8")
        self.assertIn("## 9. 합의·서명", charter)
        self.assertIn("| 고객 PM |  |  |", charter)
        okr = (dest / "okr.md").read_text(encoding="utf-8")
        for r in OKR:
            self.assertIn(r["key_result"], okr)
        self.assertEqual(len(Document(dest / "okr.docx").tables), 1)

    def test_prompts_carry_inputs_and_notice(self):
        _, llm = self.intake()
        sow_prompt, charter_prompt = llm.prompts
        self.assertIn("소스 DB 읽기 권한", sow_prompt)  # SOW 원문
        self.assertIn("지시문처럼 보이는 문장", sow_prompt)
        self.assertIn("A-001,소스 DB 읽기 권한 요청", sow_prompt)  # Workbook
        self.assertIn("수치 일치의 허용 오차", charter_prompt)  # sow-intake 결과가 charter 프롬프트로 전달됨
        self.assertIn("KR1 핵심 리포트 Databricks 전환", charter_prompt)

    def test_blocked_when_finalized_unless_force(self):
        self.paths.final_dir(0).mkdir(parents=True)
        with self.assertRaisesRegex(pm_agent.AgentError, "이미 확정"):
            self.intake()
        self.intake(force=True)

    def test_missing_input_documents(self):
        (self.paths.data / "sow_sample.md").unlink()
        with self.assertRaisesRegex(pm_agent.AgentError, "입력 문서가 없음"):
            self.intake()

    def test_workbook_changed_during_run_is_detected(self):
        def tamper():
            p = self.paths.workbook / "actions.csv"
            p.write_text(p.read_text(encoding="utf-8") + "A-099,x,y,z,Open,w\n", encoding="utf-8")

        with self.assertRaisesRegex(pm_agent.AgentError, "Workbook이 바뀌었음"):
            self.intake(FakeLLM(on_charter=tamper))
        self.assertFalse((self.paths.draft_dir(0) / "meta.json").exists())

    def test_project_name(self):
        self.assertEqual(intake._project_name("# 가상 시나리오: Aster Retail(가상) 이관\n- x"), "Aster Retail(가상) 이관")
        self.assertEqual(intake._project_name(""), "프로젝트(가상)")

    def test_pipe_in_text_does_not_break_tables(self):
        sow = mutated(GOOD_SOW, lambda o: o["handover_checklist"][0].update(item="A | B 확인"))
        dest, _ = self.intake(FakeLLM(sow=(sow,)))
        self.assertIn("A / B 확인", (dest / "handover.md").read_text(encoding="utf-8"))


class ValidationTest(Base):
    def assert_rejected_twice(self, sow=None, charter=None):
        llm = FakeLLM(sow=(sow, sow) if sow else (GOOD_SOW,), charter=(charter, charter) if charter else (GOOD_CHARTER,))
        with self.assertRaises(pm_agent.AgentError):
            self.intake(llm)
        self.assertFalse((self.paths.draft_dir(0) / "meta.json").exists())
        return llm

    def test_bad_sow_outputs_are_rejected(self):
        cases = {
            "근거 없음": lambda o: o["handover_checklist"][0].update(source=""),
            "check_with 값 오류": lambda o: o["handover_checklist"][0].update(check_with="아무나"),
            "중복 항목": lambda o: o["handover_checklist"][1].update(item=o["handover_checklist"][0]["item"]),
            "항목 부족": lambda o: o.update(handover_checklist=o["handover_checklist"][:3]),
            "M0를 Done으로": lambda o: o["changeset"]["changes"][0]["row"].update(status="Done"),
            "게이트 변형 G00 으로 Done": lambda o: o["changeset"]["changes"][0]["row"].update(gate="G00", status="Done"),
            "게이트 변형 ' g0 ' 으로 Done": lambda o: o["changeset"]["changes"][0]["row"].update(gate=" g0 ", status="Done"),
            "수식으로 시작하는 리스크 제목": lambda o: o["changeset"]["changes"][1]["row"].update(title="=1+1"),
            "week 가 0 아님": lambda o: o["changeset"].update(week=5),
            "update 연산": lambda o: o["changeset"]["changes"][1].update(op="update"),
            "허용되지 않은 테이블": lambda o: o["changeset"]["changes"][1].update(table="actions"),
            "reason 없음": lambda o: o["changeset"]["changes"][1].pop("reason"),
            "기존 ID 중복": lambda o: o["changeset"]["changes"][1]["row"].update(id="R-001"),
            "리스크 허용 값 오류": lambda o: o["changeset"]["changes"][1]["row"].update(probability="높음"),
            "단계 이름 오류": lambda o: o["extraction"]["phases"][0].update(phase="P9"),
            "weeks 가 문자열": lambda o: o["extraction"]["phases"][0].update(weeks="1"),
            "필수 목록 누락": lambda o: o["extraction"].pop("scope_out"),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.setUp()
                self.assert_rejected_twice(sow=mutated(GOOD_SOW, fn))

    def test_bad_charter_outputs_are_rejected(self):
        cases = {
            "KR 문구 변경": lambda o: o["okr"][0].update(key_result="KR1 전환 리포트(문구 변경)"),
            "KR 누락": lambda o: o.update(okr=o["okr"][:2]),
            "KR 추가": lambda o: o["okr"].append(dict(o["okr"][0], key_result="KR9 새 핵심 결과")),
            "KR 중복": lambda o: o["okr"].append(dict(o["okr"][0])),
            "우선순위 불일치": lambda o: o["okr"][0].update(priority="P2"),
            "우선순위 형식": lambda o: o["okr"][0].update(priority="높음"),
            "빈 칸": lambda o: o["okr"][0].update(success_metric=""),
            "charter 필드 누락": lambda o: o["charter"].pop("purpose"),
            "roles 비어 있음": lambda o: o["charter"].update(roles=[]),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.setUp()
                self.assert_rejected_twice(charter=mutated(GOOD_CHARTER, fn))

    def test_retry_includes_reason_and_then_succeeds(self):
        bad = mutated(GOOD_SOW, lambda o: o["handover_checklist"][0].update(source=""))
        dest, llm = self.intake(FakeLLM(sow=(bad, GOOD_SOW)))
        retry = llm.prompts[1]
        self.assertIn("거부되었다", retry)
        self.assertIn("source", retry)
        self.assertEqual(sorted(p.name for p in dest.glob("rejected_*")), [])  # 성공하면 정리됨

    def test_non_json_output_is_rejected(self):
        with self.assertRaises(pm_agent.AgentError):
            self.intake(FakeLLM(sow=("JSON을 만들 수 없습니다", "역시 안 됩니다")))

    def test_rejected_attempts_are_saved_for_review(self):
        bad = mutated(GOOD_SOW, lambda o: o["handover_checklist"][0].update(source=""))
        self.assert_rejected_twice(sow=bad)
        saved = list(self.paths.draft_dir(0).glob("rejected_*.txt"))
        self.assertEqual(len(saved), 2)
        self.assertIn("거부 사유", saved[0].read_text(encoding="utf-8"))

    def test_missing_notes_default_to_empty(self):
        sow = mutated(GOOD_SOW, lambda o: o.pop("notes"))
        charter = mutated(GOOD_CHARTER, lambda o: o.pop("notes"))
        dest, _ = self.intake(FakeLLM(sow=(sow,), charter=(charter,)))
        self.assertTrue((dest / "handover.md").exists())


class ApproveIntakeTest(Base):
    def approve(self, **kw):
        return pm_agent.approve_week(0, self.paths, confirm=lambda: True, log=self.logs.append, **kw)

    def test_approval_applies_changes_and_finalizes_all_documents(self):
        self.intake()
        self.assertTrue(self.approve())
        self.assertTrue(any(m["id"] == "M0" for m in wb.read_table("milestones", self.paths.workbook)))
        self.assertTrue(any("BI 도구" in r["title"] for r in wb.read_table("risks", self.paths.workbook)))
        final = self.paths.final_dir(0)
        self.assertEqual(sorted(p.name for p in final.iterdir()),
                         ["changeset.json", "charter.docx", "charter.md", "handover.docx", "handover.md", "meta.json",
                          "okr.docx", "okr.md"])
        for name in intake.DOCUMENTS:
            text = (final / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("- 상태: 확정 (PM 승인 ", text, name)
            self.assertNotIn("승인 전)", text, name)
            self.assertNotIn("작성 기준: 승인 이전 Workbook", text, name)  # 주간 보고서용 안내는 착수 문서에 넣지 않는다
        meta = json.loads((final / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["status"], meta["applied"]), ("approved", 2))
        self.assertEqual({h["week"] for h in wb.read_history(self.paths.workbook)}, {"0"})

    def test_pm_can_mark_handover_done_before_approving_and_quality_gate_passes(self):
        self.intake()
        e1_before = next(f for f in qg.check(*qg.collect_context(self.paths), 7) if f.key == "E1")
        self.assertEqual(e1_before.level, "UNKNOWN")
        path = self.paths.draft_dir(0) / "changeset.json"
        cs = json.loads(path.read_text(encoding="utf-8"))
        cs["changes"][0]["row"]["status"] = "Done"  # PM이 Handover를 마쳤다고 판단
        path.write_text(json.dumps(cs, ensure_ascii=False), encoding="utf-8")
        self.approve()
        self.assertTrue(any("수정되었습니다" in m for m in self.logs))
        e1_after = next(f for f in qg.check(*qg.collect_context(self.paths), 7) if f.key == "E1")
        self.assertEqual(e1_after.level, "PASS")

    def test_planned_handover_after_approval_is_flagged_by_quality_gate(self):
        self.intake()
        self.approve()  # M0 는 Planned 그대로(계획 W0)
        e1 = next(f for f in qg.check(*qg.collect_context(self.paths), 7) if f.key == "E1")
        self.assertEqual(e1.level, "FAIL")  # 계획 주차가 지났는데 Handover 가 완료되지 않음

    def test_double_approval_blocked(self):
        self.intake()
        self.approve()
        with self.assertRaisesRegex(pm_agent.AgentError, "이미 확정"):
            self.approve()

    def test_weekly_flow_is_unaffected_for_default_documents(self):
        # documents 가 없는 기존 초안(주간 보고서)은 report 하나로 확정된다
        self.assertEqual(
            pm_agent.finalize_report_text("# t\n\n- 상태: 초안 (PM 승인 전)\n", "2026-11-23", basis_note=False)[0],
            "# t\n\n- 상태: 확정 (PM 승인 2026-11-23)\n")


class TelegramIntakeTest(Base):
    def test_approval_request_for_intake(self):
        self.intake()
        cs_text = (self.paths.draft_dir(0) / "changeset.json").read_text(encoding="utf-8")
        nonce = af._nonce(cs_text)
        from test_approval_flow import Clock  # noqa: PLC0415

        bot = ScriptedBot([[], [cb(f"approve:0:{nonce}")]])
        result = af.request_approval(0, self.paths, bot, wait_sec=60, log=self.logs.append, clock=Clock())
        self.assertEqual(result, "approved")
        req = bot.texts()[0]
        self.assertIn("착수(P0→P1) 승인 요청", req)
        self.assertNotIn("전체 RAG", req)
        for name in intake.DOCUMENTS:
            self.assertIn(f"{name}.docx", req)
        self.assertIn("착수(P0→P1) 승인 완료", bot.texts()[-1])
        self.assertTrue(self.paths.final_dir(0).exists())


if __name__ == "__main__":
    unittest.main()
