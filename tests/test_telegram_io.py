import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import telegram_io as tg  # noqa: E402

TOKEN = "123456789:" + "AbC_dEf-" * 5  # 가짜 토큰(형식만 같음)
CHAT = "555000111"


class FakeResp:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """urlopen 대용. 요청을 기록하고 정해진 응답을 돌려준다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(r)


def ok(result):
    return {"ok": True, "result": result}


CODE = "a1b2c3d4"


def private_msg(chat_id, text="/start", is_bot=False, chat_type="private", update_id=1):
    return {"update_id": update_id, "message": {"chat": {"id": int(chat_id), "type": chat_type}, "from": {"is_bot": is_bot}, "text": text}}


class EnvTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = self.dir / ".env"

    def test_load_env_parsing(self):
        self.env.write_text('﻿# 주석\n\nTELEGRAM_BOT_TOKEN = "abc:def"\nTELEGRAM_CHAT_ID=\nNOEQ\n', encoding="utf-8")
        self.assertEqual(tg.load_env(self.env), {"TELEGRAM_BOT_TOKEN": "abc:def", "TELEGRAM_CHAT_ID": ""})
        self.assertEqual(tg.load_env(self.dir / "없음"), {})

    def test_update_env_value_changes_only_that_key(self):
        self.env.write_text(f"# 메모\nTELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=\nTELEGRAM_CHAT_ID_X=keep\n", encoding="utf-8")
        tg.update_env_value(self.env, "TELEGRAM_CHAT_ID", CHAT)
        lines = self.env.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["# 메모", f"TELEGRAM_BOT_TOKEN={TOKEN}", f"TELEGRAM_CHAT_ID={CHAT}", "TELEGRAM_CHAT_ID_X=keep"])
        self.assertFalse(self.env.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_update_env_value_appends_when_missing(self):
        self.env.write_text("A=1\n", encoding="utf-8")
        tg.update_env_value(self.env, "TELEGRAM_CHAT_ID", CHAT)
        self.assertEqual(tg.load_env(self.env), {"A": "1", "TELEGRAM_CHAT_ID": CHAT})


class BotTest(unittest.TestCase):
    def test_bad_token_formats_rejected_without_echo(self):
        for bad in ("", "토큰아님", "123:short", f" {TOKEN}", f'"{TOKEN}"', TOKEN + " "):
            with self.assertRaises(tg.TelegramError) as cm:
                tg.Bot(bad)
            self.assertNotIn(bad.strip() or "x" * 99, str(cm.exception))

    def test_get_me_calls_expected_url(self):
        net = FakeNet(ok({"first_name": "PM Workflow", "username": "pm_demo_bot"}))
        me = tg.Bot(TOKEN, opener=net).get_me()
        self.assertEqual(me["username"], "pm_demo_bot")
        self.assertEqual(net.requests[0].full_url, f"https://api.telegram.org/bot{TOKEN}/getMe")

    def test_api_error_is_redacted(self):
        body = json.dumps({"ok": False, "error_code": 401, "description": f"Unauthorized {TOKEN}"}).encode()
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(body))
        with self.assertRaises(tg.TelegramError) as cm:
            tg.Bot(TOKEN, opener=FakeNet(err)).get_me()
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertIn("401", str(cm.exception))

    def test_network_error_message_has_no_url_or_token(self):
        err = urllib.error.URLError(f"failed https://api.telegram.org/bot{TOKEN}/getMe")
        with self.assertRaises(tg.TelegramError) as cm:
            tg.Bot(TOKEN, opener=FakeNet(err)).get_me()
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertIn("URLError", str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)  # 원본 예외(토큰 포함 가능)를 연결하지 않음

    def test_send_message_needs_chat_id(self):
        with self.assertRaises(tg.TelegramError):
            tg.Bot(TOKEN, opener=FakeNet()).send_message("hi")
        net = FakeNet(ok({"message_id": 1}))
        tg.Bot(TOKEN, CHAT, net).send_message("안녕")
        sent = json.loads(net.requests[0].data.decode("utf-8"))
        self.assertEqual((sent["chat_id"], sent["text"]), (CHAT, "안녕"))

    def test_accept_only_registered_chat(self):
        bot = tg.Bot(TOKEN, CHAT, FakeNet())
        self.assertIsNotNone(bot.accept(private_msg(CHAT)))
        self.assertIsNone(bot.accept(private_msg(999)))  # 다른 사람
        self.assertIsNone(bot.accept(private_msg(CHAT, is_bot=True)))
        cb_ok = {"callback_query": {"from": {"is_bot": False}, "message": {"chat": {"id": int(CHAT)}}, "data": "approve:5"}}
        cb_bad = {"callback_query": {"from": {"is_bot": False}, "message": {"chat": {"id": 1}}, "data": "approve:5"}}
        self.assertIsNotNone(bot.accept(cb_ok))
        self.assertIsNone(bot.accept(cb_bad))
        self.assertIsNone(tg.Bot(TOKEN, None, FakeNet()).accept(private_msg(CHAT)))  # chat id 미등록이면 아무도 허용 안 함


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = self.dir / ".env"
        self.env.write_text(f"# 견본\nTELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")
        self.out = []

    def say(self, s):
        self.out.append(s)

    def test_non_ascii_messages_do_not_crash_registration(self):
        # 회귀: compare_digest 가 비ASCII 문자열에서 TypeError 를 내 낯선 사람이 등록 절차를 멈출 수 있었다
        for text in ("/start 한글코드", "/start ｃｏｄｅ１２３４", "/start a1b2c3dé", "/start ‮a1b2c3d4"):
            self.assertIsNone(tg.match_setup_code([private_msg(777, text)], CODE), text)
        # 비ASCII 메시지가 앞에 있어도 올바른 코드를 가진 사람은 등록된다
        self.assertEqual(tg.match_setup_code([private_msg(777, "/start 한글"), private_msg(CHAT, f"/start {CODE}")], CODE), CHAT)

    def test_setup_survives_non_ascii_stranger_then_registers_owner(self):
        me = ok({"first_name": "PM Workflow", "username": "pm_demo_bot"})
        net = FakeNet(
            me, ok([]),
            ok([private_msg(777, "/start 한글", update_id=3), private_msg(CHAT, f"/start {CODE}", update_id=4)]),
            ok([]), ok({"message_id": 1}),
        )
        self.assertEqual(self.setup(net), 0)
        self.assertEqual(tg.load_env(self.env)["TELEGRAM_CHAT_ID"], CHAT)

    def test_match_setup_code_accepts_only_the_code_holder(self):
        good = private_msg(CHAT, f"/start {CODE}")
        self.assertEqual(tg.match_setup_code([good], CODE), CHAT)
        self.assertEqual(tg.match_setup_code([private_msg(CHAT, f"/start@pm_workflow_AI_bot {CODE}")], CODE), CHAT)
        # 코드를 모르는 사람의 /start, 틀린 코드, 코드 뒤 군더더기, 코드만 있는 메시지는 모두 거부
        for bad in ("/start", "/start wrong000", f"/start {CODE} extra", CODE, f"hello /start {CODE}"):
            self.assertIsNone(tg.match_setup_code([private_msg(777, bad)], CODE), bad)
        # 봇·그룹에서 온 것은 코드가 맞아도 거부
        self.assertIsNone(tg.match_setup_code([private_msg(1, f"/start {CODE}", is_bot=True)], CODE))
        self.assertIsNone(tg.match_setup_code([private_msg(2, f"/start {CODE}", chat_type="group")], CODE))
        # 낯선 사람 메시지가 앞에 있어도 코드 맞는 쪽을 고른다
        self.assertEqual(tg.match_setup_code([private_msg(777, "/start"), good], CODE), CHAT)

    def test_check_prints_no_secrets(self):
        net = FakeNet(ok({"first_name": "PM Workflow", "username": "pm_demo_bot"}))
        self.assertEqual(tg.cmd_check(self.env, net, self.say), 0)
        text = "\n".join(self.out)
        self.assertIn("입력됨", text)
        self.assertIn("봇 연결: 성공", text)
        self.assertNotIn(TOKEN, text)

    def test_check_reports_missing_env_and_empty_token(self):
        with self.assertRaisesRegex(tg.TelegramError, ".env 파일이 없음"):
            tg.cmd_check(self.dir / "nope", FakeNet(), self.say)
        self.env.write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
        with self.assertRaisesRegex(tg.TelegramError, "비어 있음"):
            tg.cmd_check(self.env, FakeNet(), self.say)

    def setup(self, net, **kw):
        return tg.cmd_setup(self.env, net, self.say, code_fn=lambda: CODE, **kw)

    def test_setup_binds_only_the_code_holder_and_consumes_updates(self):
        me = ok({"first_name": "PM Workflow", "username": "pm_demo_bot"})
        stale = private_msg(777, "/start", update_id=5)  # 이전에 쌓여 있던 낯선 사람의 메시지
        net = FakeNet(
            me,
            ok([stale]), ok([]),  # 1) 오래된 메시지를 읽고 소비(offset 6)
            ok([private_msg(777, "/start wrong000", update_id=7), private_msg(CHAT, f"/start {CODE}", update_id=8)]),
            ok([]),  # 2) 처리한 메시지 소비(offset 9)
            ok({"message_id": 1}),  # 3) 등록 완료 안내
        )
        self.assertEqual(self.setup(net), 0)
        env = tg.load_env(self.env)
        self.assertEqual(env["TELEGRAM_CHAT_ID"], CHAT)  # 낯선 사람(777)이 아니라 코드를 아는 사람
        self.assertEqual(env["TELEGRAM_BOT_TOKEN"], TOKEN)
        self.assertIn("# 견본", self.env.read_text(encoding="utf-8"))
        text = "\n".join(self.out)
        self.assertNotIn(CHAT, text)
        self.assertNotIn(TOKEN, text)
        self.assertIn(f"t.me/pm_demo_bot?start={CODE}", text)  # 링크는 공개 정보인 봇 username 만 사용
        bodies = [json.loads(r.data.decode("utf-8")) for r in net.requests]
        self.assertEqual(bodies[2]["offset"], 6)
        self.assertEqual(bodies[4]["offset"], 9)
        self.assertEqual(bodies[5]["chat_id"], CHAT)

    def test_setup_times_out_without_correct_code(self):
        me = ok({"first_name": "PM Workflow", "username": "pm_demo_bot"})
        with self.assertRaises(tg.TelegramError):
            self.setup(FakeNet(me, ok([])), max_wait=0)
        self.assertEqual(tg.load_env(self.env)["TELEGRAM_CHAT_ID"], "")

    def test_setup_refuses_to_overwrite_registered_chat_without_force(self):
        tg.update_env_value(self.env, "TELEGRAM_CHAT_ID", CHAT)
        net = FakeNet()  # 네트워크를 쓰기 전에 거부해야 한다
        with self.assertRaisesRegex(tg.TelegramError, "--force"):
            self.setup(net)
        self.assertEqual(net.requests, [])
        self.assertEqual(tg.load_env(self.env)["TELEGRAM_CHAT_ID"], CHAT)

    def test_ping_sends_message(self):
        tg.update_env_value(self.env, "TELEGRAM_CHAT_ID", CHAT)
        net = FakeNet(ok({"message_id": 1}))
        self.assertEqual(tg.cmd_ping(self.env, net, self.say), 0)
        self.assertIn("연결 확인", json.loads(net.requests[0].data.decode("utf-8"))["text"])

    def test_main_usage_and_error_exit_codes(self):
        self.assertEqual(tg.main([]), 2)
        self.assertEqual(tg.main(["bogus"]), 2)
        self.assertEqual(tg.main(["check", "--force"]), 2)  # --force 는 setup 에만
        self.assertEqual(tg.main(["setup", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
