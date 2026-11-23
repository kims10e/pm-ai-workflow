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
import memo_listener as ml  # noqa: E402
import pm_agent  # noqa: E402
import workbook as wb  # noqa: E402
from test_approval_flow import CHAT, REPORT, TOKEN, ScriptedBot, cb  # noqa: E402  (테스트 클래스는 가져오지 않는다)
from test_pm_agent import GOOD_CS, FakeLLM  # noqa: E402

CS8 = dict(GOOD_CS, week=8)


class Clock:
    def __init__(self, step=5):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def msg(text, chat=CHAT, update_id=20, is_bot=False):
    return {"update_id": update_id, "message": {
        "chat": {"id": int(chat), "type": "private"}, "from": {"is_bot": is_bot}, "text": text}}


class ParseTest(unittest.TestCase):
    def test_parse_command(self):
        self.assertEqual(ml.parse_command("/memo 8\n- a\n- b"), (8, False, "- a\n- b"))
        self.assertEqual(ml.parse_command("/memo@pm_workflow_AI_bot 8 force\nx"), (8, True, "x"))
        self.assertEqual(ml.parse_command("/memo 8 덮어쓰기"), (8, True, ""))
        self.assertEqual(ml.parse_command("/memo 8"), (8, False, ""))
        self.assertIsNone(ml.parse_command("hello"))
        self.assertIsNone(ml.parse_command(""))
        self.assertIsNone(ml.parse_command("/help"))

    def test_parse_command_errors(self):
        for bad in ("/memo", "/memo abc", "/memo 0", "/memo 100", "/memo -3"):
            with self.assertRaises(ml.MemoError, msg=bad):
                ml.parse_command(bad)

    def test_normalize_memo(self):
        out = ml.normalize_memo(8, "• 가\n* 나\n\n- 다\n라\n   - 마")
        self.assertEqual(out, "# 주간 업데이트 메모 — 8주차 (가상)\n- 가\n- 나\n- 다\n- 라\n- 마\n")
        with self.assertRaises(ml.MemoError):
            ml.normalize_memo(8, " \n\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tests" / "fixtures" / "workbook", self.tmp / "workbook")
        for rel in ("data/updates", ".claude/skills"):
            shutil.copytree(ROOT / rel, self.tmp / rel)
        self.paths = pm_agent.Paths(self.tmp)
        self.logs = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def workbook_bytes(self):
        return {p.name: p.read_bytes() for p in self.paths.workbook.glob("*")}


class SaveTest(Base):
    def test_save_creates_utf8_file_without_bom(self):
        path = ml.save_memo(self.paths, 8, "- 파일럿 완료\n- 권한 해결")
        self.assertEqual(path, self.paths.memo(8))
        raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.decode("utf-8"), "# 주간 업데이트 메모 — 8주차 (가상)\n- 파일럿 완료\n- 권한 해결\n")

    def test_existing_memo_is_not_overwritten_without_force(self):
        original = self.paths.memo(5).read_bytes()
        with self.assertRaisesRegex(ml.MemoError, "force"):
            ml.save_memo(self.paths, 5, "- 덮어쓰기 시도")
        self.assertEqual(original, self.paths.memo(5).read_bytes())
        ml.save_memo(self.paths, 5, "- 의도적으로 덮어씀", force=True)
        self.assertIn("의도적으로 덮어씀", self.paths.memo(5).read_text(encoding="utf-8"))

    def test_finalized_week_refused_even_with_force(self):
        self.paths.final_dir(8).mkdir(parents=True)
        with self.assertRaisesRegex(ml.MemoError, "이미 확정"):
            ml.save_memo(self.paths, 8, "- x", force=True)
        self.assertFalse(self.paths.memo(8).exists())

    def test_too_long_or_empty_refused_and_nothing_written(self):
        with self.assertRaisesRegex(ml.MemoError, "너무 깁니다"):
            ml.save_memo(self.paths, 8, "가" * (ml.MAX_MEMO_CHARS + 1))
        with self.assertRaises(ml.MemoError):
            ml.save_memo(self.paths, 8, "   ")
        self.assertFalse(self.paths.memo(8).exists())
        self.assertEqual(list(self.paths.updates.glob("*.tmp")), [])


class ListenTest(Base):
    def run_listener(self, batches, llm=None, **kw):
        bot = ScriptedBot(batches)
        llm = llm or FakeLLM([CS8], report=REPORT)
        handled = ml.listen(self.paths, bot, log=self.logs.append, clock=kw.pop("clock", Clock()), llm=llm, **kw)
        return handled, bot, llm

    def nonce8(self):
        return af._nonce(json.dumps(CS8, ensure_ascii=False, indent=2) + "\n")

    # --- 정상 흐름
    def test_memo_message_runs_whole_loop_to_approval(self):
        batches = [
            [],  # 시작 시 쌓인 메시지 없음
            [msg("/memo 8\n- 파일럿 리포트 전환 완료\n- 권한 이슈 해결")],
            [],  # 승인 요청 직전 비우기
            [cb(f"approve:8:{self.nonce8()}")],
        ]
        handled, bot, llm = self.run_listener(batches, once=True)
        self.assertEqual(handled, 1)
        self.assertIn("파일럿 리포트 전환 완료", self.paths.memo(8).read_text(encoding="utf-8"))
        self.assertTrue((self.paths.final_dir(8) / "report.docx").exists())
        kr1 = next(r for r in wb.read_table("okr", self.paths.workbook) if r["key_result"].startswith("KR1"))
        self.assertEqual(kr1["current"], "6")
        texts = " | ".join(bot.texts())
        for expected in ("대기 중", "8주차 메모를 저장했습니다(2줄)", "8주차 승인 요청", "승인 완료"):
            self.assertIn(expected, texts)
        self.assertNotIn(TOKEN, json.dumps(bot.calls, ensure_ascii=False))
        # 메모 내용이 claude 프롬프트에 들어가고, 자료로 취급하라는 문구가 함께 간다
        self.assertIn("권한 이슈 해결", llm.prompts[0])
        self.assertIn("지시문처럼 보이는 문장", llm.prompts[0])

    def test_two_step_memo(self):
        batches = [[], [msg("/memo 8")], [msg("- 첫째\n- 둘째")], [], [cb(f"approve:8:{self.nonce8()}")]]
        handled, bot, _ = self.run_listener(batches, once=True)
        self.assertEqual(handled, 1)
        self.assertIn("8주차 메모를 보내주세요", bot.texts()[1])
        self.assertIn("둘째", self.paths.memo(8).read_text(encoding="utf-8"))

    # --- 무시·거부
    def test_other_chat_and_bot_messages_are_ignored(self):
        batches = [[], [msg("/memo 8\n- 낯선 사람", chat="999"), msg("/memo 8\n- 봇", is_bot=True)]]
        handled, bot, llm = self.run_listener(batches, listen_sec=60)
        self.assertEqual(handled, 0)
        self.assertFalse(self.paths.memo(8).exists())
        self.assertEqual(len(bot.texts()), 1)  # 시작 안내만. 낯선 사람에게는 응답하지 않는다
        self.assertEqual(llm.prompts, [])

    def test_messages_from_before_start_are_discarded(self):
        batches = [[msg("/memo 8\n- 시작 전에 쌓인 메모")], []]
        handled, _, llm = self.run_listener(batches, listen_sec=30)
        self.assertEqual(handled, 0)
        self.assertFalse(self.paths.memo(8).exists())
        self.assertEqual(llm.prompts, [])

    def test_existing_week_is_refused_without_calling_claude(self):
        original = self.paths.memo(5).read_bytes()
        handled, bot, llm = self.run_listener([[], [msg("/memo 5\n- 덮어쓰기")]], listen_sec=30)
        self.assertEqual(handled, 0)
        self.assertEqual(original, self.paths.memo(5).read_bytes())
        self.assertIn("이미 있습니다", bot.texts()[-1])
        self.assertEqual(llm.prompts, [])

    def test_force_overwrites_existing_week(self):
        batches = [[], [msg("/memo 5 force\n- 정정한 메모")], [], []]
        llm = FakeLLM([dict(GOOD_CS, week=5)], report=REPORT)
        handled, _, _ = self.run_listener(batches, llm=llm, once=True, wait_sec=30)
        self.assertEqual(handled, 1)
        self.assertIn("정정한 메모", self.paths.memo(5).read_text(encoding="utf-8"))

    def test_finalized_week_is_refused(self):
        self.paths.final_dir(8).mkdir(parents=True)
        handled, bot, llm = self.run_listener([[], [msg("/memo 8\n- x")]], listen_sec=30)
        self.assertEqual(handled, 0)
        self.assertIn("이미 확정", bot.texts()[-1])
        self.assertEqual(llm.prompts, [])

    def test_help_and_unknown_text(self):
        _, bot, _ = self.run_listener([[], [msg("/help"), msg("그냥 말 걸기"), msg("/memo"), msg("/memo 0\n- x")]], listen_sec=30)
        texts = bot.texts()
        self.assertIn("가상 데이터", texts[1])  # 도움말에 가상 데이터 안내
        self.assertIn("/memo 주차", texts[2])
        self.assertIn("주차를 숫자로", texts[3])
        self.assertIn("1~99", texts[4])

    def test_pending_week_expires(self):
        # '/memo 8' 뒤 너무 늦게 온 메시지는 메모로 받지 않는다
        _, bot, _ = self.run_listener([[], [msg("/memo 8")], [msg("- 너무 늦은 메모")]], listen_sec=1900, clock=Clock(step=400))
        self.assertFalse(self.paths.memo(8).exists())
        self.assertIn("/memo 주차", bot.texts()[-1])

    # --- 실패 처리
    def test_claude_failure_is_reported_and_listener_survives(self):
        def broken(prompt):
            raise pm_agent.AgentError("claude 호출 실패(코드 1)")

        before = self.workbook_bytes()
        handled, bot, _ = self.run_listener([[], [msg("/memo 8\n- x")]], llm=broken, once=True)
        self.assertEqual(handled, 1)
        self.assertIn("초안을 만들지 못했습니다", bot.texts()[-1])
        self.assertIn("claude 호출 실패", bot.texts()[-1])
        self.assertEqual(before, self.workbook_bytes())
        self.assertFalse(self.paths.final_dir(8).exists())

    def test_requires_chat_id(self):
        with self.assertRaisesRegex(pm_agent.AgentError, "chat id"):
            ml.listen(self.paths, ScriptedBot([], chat_id=None), log=self.logs.append)


if __name__ == "__main__":
    unittest.main()
