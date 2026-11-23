import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import approval_flow as af  # noqa: E402
import pm_agent  # noqa: E402
import telegram_io as tg  # noqa: E402
import workbook as wb  # noqa: E402
from test_pm_agent import GOOD_CS, FakeLLM  # noqa: E402  (테스트 클래스는 가져오지 않는다)

TOKEN = "123456789:" + "AbC_dEf-" * 5
CHAT = "555000111"
REPORT = "# 주간 현황 보고 — 테스트 5주차\n\n- 상태: 초안 (PM 승인 전)\n\n## 1. 요약\n전체 RAG: Amber\n"


class ScriptedBot(tg.Bot):
    """네트워크 없이 각본대로 응답한다. batches[0] 은 요청 전 쌓여 있던 입력(버려져야 함), 이후는 폴링 결과."""

    def __init__(self, batches, chat_id=CHAT):
        super().__init__(TOKEN, chat_id)
        self.batches = list(batches)
        self.calls = []

    def _call(self, method, params=None, timeout=30):
        self.calls.append((method, params))
        if method == "getUpdates":
            if params and "offset" in params:  # 확인(소비) 호출. 각본은 소모하지 않는다
                return []
            return self.batches.pop(0) if self.batches else []
        if method == "sendMessage":
            return {"message_id": 100}
        return True

    def methods(self, name):
        return [p for m, p in self.calls if m == name]

    def texts(self):
        return [p["text"] for p in self.methods("sendMessage")]


class Clock:
    """호출할 때마다 5초씩 흐르는 가짜 시계."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 5
        return self.t


def cb(data, chat=CHAT, mid=100, update_id=10):
    return {"update_id": update_id, "callback_query": {
        "id": "cb1", "from": {"is_bot": False}, "data": data, "message": {"chat": {"id": int(chat)}, "message_id": mid}}}


class ApprovalFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tests" / "fixtures" / "workbook", self.tmp / "workbook")
        for rel in ("data/updates", ".claude/skills"):
            shutil.copytree(ROOT / rel, self.tmp / rel)
        self.paths = pm_agent.Paths(self.tmp)
        pm_agent.run_week(5, self.paths, llm=FakeLLM([GOOD_CS], report=REPORT), log=lambda s: None)
        cs_text = (self.paths.draft_dir(5) / "changeset.json").read_text(encoding="utf-8")
        self.nonce = af._nonce(cs_text)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, polls, drain=(), wait_sec=60, **kw):
        bot = ScriptedBot([list(drain)] + [list(p) for p in polls])
        result = af.request_approval(5, self.paths, bot, wait_sec=wait_sec, log=self.logs.append, clock=Clock(), **kw)
        return result, bot

    def workbook_bytes(self):
        return {p.name: p.read_bytes() for p in self.paths.workbook.glob("*")}

    def good(self, action="approve", **kw):
        return cb(f"{action}:5:{self.nonce}", **kw)

    # --- 정상 흐름
    def test_request_message_has_summary_and_buttons(self):
        _, bot = self.request([])
        req = bot.methods("sendMessage")[0]
        self.assertIn("5주차 승인 요청", req["text"])
        self.assertIn("전체 RAG: Amber", req["text"])
        self.assertIn("변경 2건", req["text"])
        self.assertIn("A-001 기한 초과", req["text"])  # notes
        self.assertIn("AI 추정", req["text"])
        buttons = req["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["text"] for b in buttons], ["승인", "반려"])
        self.assertTrue(all(len(b["callback_data"].encode()) <= 64 for b in buttons))  # 텔레그램 한도
        self.assertNotIn(TOKEN, json.dumps(bot.calls[1:], ensure_ascii=False))  # 본문에 토큰 없음

    def test_approve_button_applies_and_finalizes(self):
        result, bot = self.request([[self.good("approve")]])
        self.assertEqual(result, "approved")
        kr1 = next(r for r in wb.read_table("okr", self.paths.workbook) if r["key_result"].startswith("KR1"))
        self.assertEqual(kr1["current"], "6")
        self.assertTrue((self.paths.final_dir(5) / "report.docx").exists())
        self.assertEqual(len(wb.read_history(self.paths.workbook)), 2)
        self.assertEqual(len(bot.methods("answerCallbackQuery")), 1)
        self.assertEqual(bot.methods("editMessageReplyMarkup")[0]["message_id"], 100)  # 버튼 제거
        self.assertIn("승인 완료", bot.texts()[-1])
        self.assertIn("2건", bot.texts()[-1])

    def test_reject_button_changes_nothing_and_blocks_later_approval(self):
        before = self.workbook_bytes()
        result, bot = self.request([[self.good("reject")]])
        self.assertEqual(result, "rejected")
        self.assertEqual(before, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(5).exists())
        meta = json.loads((self.paths.draft_dir(5) / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "rejected")
        self.assertIn("반려", bot.texts()[-1])
        # 반려된 초안은 CLI 승인으로도, 다시 요청으로도 진행할 수 없다
        with self.assertRaisesRegex(pm_agent.AgentError, "반려"):
            pm_agent.approve_week(5, self.paths, confirm=lambda: True, log=lambda s: None)
        with self.assertRaisesRegex(pm_agent.AgentError, "반려"):
            self.request([])

    def test_rerun_after_reject_makes_draft_approvable_again(self):
        self.request([[self.good("reject")]])
        pm_agent.run_week(5, self.paths, llm=FakeLLM([GOOD_CS], report=REPORT), log=lambda s: None)
        self.assertTrue(pm_agent.approve_week(5, self.paths, confirm=lambda: True, log=lambda s: None))

    # --- 시간 초과
    def test_timeout_changes_nothing_and_removes_buttons(self):
        before = self.workbook_bytes()
        result, bot = self.request([], wait_sec=60)
        self.assertEqual(result, "timeout")
        self.assertEqual(before, self.workbook_bytes())
        self.assertTrue(bot.methods("editMessageReplyMarkup"))
        self.assertIn("승인되지 않았", bot.texts()[-1])
        self.assertIn("request --week 5", bot.texts()[-1])

    # --- 거부해야 하는 입력
    def test_other_chat_button_is_ignored(self):
        before = self.workbook_bytes()
        result, bot = self.request([[self.good("approve", chat="999")]])
        self.assertEqual(result, "timeout")
        self.assertEqual(before, self.workbook_bytes())
        self.assertEqual(bot.methods("answerCallbackQuery"), [])  # 낯선 사람에게는 응답조차 하지 않는다

    def test_wrong_week_nonce_or_message_buttons_are_refused(self):
        before = self.workbook_bytes()
        bad = [
            cb(f"approve:6:{self.nonce}"),  # 다른 주차
            cb("approve:5:deadbeef"),  # 다른(오래된) 변경안
            self.good("approve", mid=55),  # 다른 메시지의 버튼
            cb("approve:5"),  # 형식 오류
            cb("rm -rf"),
        ]
        result, bot = self.request([bad])
        self.assertEqual(result, "timeout")
        self.assertEqual(before, self.workbook_bytes())
        self.assertEqual(len(bot.methods("answerCallbackQuery")), len(bad))
        self.assertTrue(all("아닙니다" in p["text"] for p in bot.methods("answerCallbackQuery")))

    def test_text_messages_do_not_approve(self):
        msg = {"update_id": 11, "message": {"chat": {"id": int(CHAT), "type": "private"}, "from": {"is_bot": False}, "text": "승인"}}
        before = self.workbook_bytes()
        result, _ = self.request([[msg]])
        self.assertEqual(result, "timeout")
        self.assertEqual(before, self.workbook_bytes())

    def test_stale_button_press_from_before_request_is_discarded(self):
        before = self.workbook_bytes()
        result, _ = self.request([], drain=[self.good("approve")])  # 요청 전에 쌓여 있던 입력
        self.assertEqual(result, "timeout")
        self.assertEqual(before, self.workbook_bytes())

    # --- 승인 실패
    def test_stale_draft_is_refused_with_reason(self):
        p = self.paths.workbook / "actions.csv"
        p.write_text(p.read_text(encoding="utf-8") + "A-099,x,y,z,Open,w\n", encoding="utf-8")
        tampered = self.workbook_bytes()
        result, bot = self.request([[self.good("approve")]])
        self.assertEqual(result, "failed")
        self.assertEqual(tampered, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(5).exists())
        self.assertIn("Workbook이 바뀌었음", bot.texts()[-1])

    def test_double_press_cannot_apply_twice(self):
        result, bot = self.request([[self.good("approve"), self.good("approve", update_id=11)]])
        self.assertEqual(result, "approved")
        self.assertEqual(len(wb.read_history(self.paths.workbook)), 2)  # 두 번째 입력은 처리되지 않음
        self.assertEqual(len(bot.methods("answerCallbackQuery")), 1)

    # --- 사전 조건
    def test_requires_chat_id_and_existing_draft(self):
        with self.assertRaisesRegex(pm_agent.AgentError, "chat id"):
            af.request_approval(5, self.paths, ScriptedBot([], chat_id=None), log=self.logs.append)
        with self.assertRaisesRegex(pm_agent.AgentError, "초안이 없음"):
            af.request_approval(9, self.paths, ScriptedBot([[]]), log=self.logs.append)

    def test_finalized_week_cannot_be_requested(self):
        self.request([[self.good("approve")]])
        with self.assertRaisesRegex(pm_agent.AgentError, "이미 확정"):
            self.request([])

    # --- 잘린 요약으로는 버튼 승인을 받지 않는다
    @staticmethod
    def _applied(n, size=20):
        return wb.Result(week=5, applied=[
            wb.Applied("actions", "add", f"A-{i:03d}", None, {"id": f"A-{i:03d}", "title": "항목 " + "가" * size, "owner": "TBD"})
            for i in range(n)])

    def test_complete_summary_has_buttons_text(self):
        text, complete = af.build_summary(5, {"changes": []}, self._applied(3), REPORT)
        self.assertTrue(complete)
        self.assertIn("아래 버튼으로 승인 또는 반려", text)
        self.assertIn("owner=TBD", text)  # 신규 항목의 값도 보인다

    def test_too_many_changes_is_incomplete(self):
        text, complete = af.build_summary(5, {"changes": []}, self._applied(80), REPORT)
        self.assertFalse(complete)
        self.assertLessEqual(len(text), 4096)
        self.assertIn("건 생략", text)
        self.assertIn("approve --week 5", text)
        self.assertNotIn("아래 버튼으로 승인 또는 반려", text)

    def test_one_clipped_change_is_incomplete(self):
        text, complete = af.build_summary(5, {"changes": []}, self._applied(1, size=af.ITEM_LIMIT), REPORT)
        self.assertFalse(complete)
        self.assertIn("…", text)

    def test_many_notes_do_not_make_summary_incomplete(self):
        cs = {"changes": [], "notes": ["긴 메모 " * 200] * 20}
        text, complete = af.build_summary(5, cs, self._applied(2), REPORT)
        self.assertTrue(complete)  # notes 생략은 변경 완전성과 무관(변경 목록이 먼저 나온다)
        self.assertLessEqual(len(text), 4096)

    def test_request_without_buttons_when_summary_incomplete(self):
        from unittest import mock

        before = self.workbook_bytes()
        with mock.patch.object(af, "ITEM_LIMIT", 10):
            result, bot = self.request([[self.good("approve")]])  # 버튼이 없으니 이 입력은 처리되지 않아야 한다
        self.assertEqual(result, "needs_cli")
        self.assertEqual(before, self.workbook_bytes())
        sent = bot.methods("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertNotIn("reply_markup", sent[0])
        self.assertIn("approve --week 5", sent[0]["text"])
        self.assertEqual(bot.methods("answerCallbackQuery"), [])
        self.assertFalse(self.paths.final_dir(5).exists())

    # --- 메시지 형식
    def test_summary_is_capped_below_telegram_limit(self):
        cs = {"week": 5, "changes": [], "notes": ["긴 메모 " * 200] * 20}
        text = af.format_summary(5, cs, wb.Result(week=5), REPORT)
        self.assertLessEqual(len(text), 4096)
        self.assertIn("외 14건", text)  # 6건까지만 보여주고 나머지는 건수로 표시

    def test_summary_without_rag_line(self):
        text = af.format_summary(5, {"changes": []}, wb.Result(week=5), "# 제목\n")
        self.assertIn("확인 필요", text)


if __name__ == "__main__":
    unittest.main()
