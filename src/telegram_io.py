"""텔레그램 봇 입출력 (표준 라이브러리만 사용).

    python src/telegram_io.py check   # .env 설정과 봇 연결 점검 (토큰은 출력하지 않음)
    python src/telegram_io.py setup   # 화면의 일회용 코드로 본인 확인 후 chat id 를 .env 에 저장 (--force: 다시 등록)
    python src/telegram_io.py ping    # 연결 확인 메시지 한 통 보내기

비밀값 규칙
- 토큰은 .env 에서만 읽는다. 출력·로그·예외 메시지에 토큰이 나오지 않게 한다(_redact).
- chat id 도 화면에 찍지 않고 .env 에 바로 저장한다. 등록은 일회용 코드를 아는 사람만 할 수 있다(setup).
- 봇은 누구나 메시지를 보낼 수 있으므로, 받는 쪽은 등록된 chat id 의 메시지만 처리해야 한다(Bot.accept).
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
API = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")


class TelegramError(RuntimeError):
    """사용자에게 그대로 보여줘도 되는 오류(토큰 제거됨)."""


# --------------------------------------------------------------------------- .env

def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    """KEY=VALUE 줄을 읽는다. 주석(#)과 빈 줄은 무시하고, 값 양쪽의 공백·따옴표는 벗긴다."""
    values: dict[str, str] = {}
    if not Path(path).exists():
        return values
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def update_env_value(path: Path, key: str, value: str) -> None:
    """.env 의 한 키만 바꾼다. 다른 줄(주석·토큰 등)은 그대로 둔다. 키가 없으면 끝에 추가한다."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(key) and line.partition("=")[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------- API 클라이언트

class Bot:
    def __init__(self, token: str, chat_id: str | int | None = None, opener: Callable[..., Any] = urllib.request.urlopen):
        if not TOKEN_RE.match(token or ""):
            # 토큰 값을 메시지에 넣지 않는다. 흔한 원인만 알려준다.
            raise TelegramError("토큰 형식이 올바르지 않음. '숫자:영문숫자' 형태여야 하며 앞뒤에 공백·따옴표가 없어야 함")
        self._token = token
        self.chat_id = str(chat_id) if chat_id not in (None, "") else None
        self._opener = opener

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***")

    def _call(self, method: str, params: dict | None = None, timeout: int = 30) -> Any:
        req = urllib.request.Request(
            f"{API}/bot{self._token}/{method}",
            data=json.dumps(params or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:  # 텔레그램은 오류도 JSON 본문으로 설명한다
            body = e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TelegramError(f"네트워크 오류: {type(e).__name__}") from None
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TelegramError("텔레그램 응답을 해석할 수 없음") from None
        if not data.get("ok"):
            raise TelegramError(self._redact(f"텔레그램 오류 {data.get('error_code', '')}: {data.get('description', '')}"))
        return data["result"]

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        params: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", params, timeout=timeout + 15)

    def send_message(self, text: str, reply_markup: dict | None = None) -> dict:
        if not self.chat_id:
            raise TelegramError("chat id 가 없음. 먼저 setup 을 실행하세요")
        params: dict = {"chat_id": self.chat_id, "text": text}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendMessage", params)

    def answer_callback_query(self, callback_id: str, text: str = "") -> None:
        """버튼을 눌렀을 때 뜨는 로딩 표시를 끈다."""
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})

    def remove_buttons(self, message_id: int) -> None:
        """메시지 아래 버튼을 지운다(같은 버튼을 다시 누르지 못하게). 실패해도 흐름을 막지 않는다."""
        try:
            self._call("editMessageReplyMarkup", {
                "chat_id": self.chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []},
            })
        except TelegramError:
            pass

    def accept(self, update: dict) -> dict | None:
        """등록된 chat id 에서 온 메시지·버튼 입력만 돌려준다. 다른 사람이 보낸 것은 버린다."""
        if not self.chat_id:
            return None
        msg = update.get("message") or (update.get("callback_query") or {}).get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != self.chat_id:
            return None
        sender = (update.get("callback_query") or update.get("message") or {}).get("from", {})
        if sender.get("is_bot"):
            return None
        return update


def bot_from_env(path: Path = ENV_PATH, opener: Callable[..., Any] = urllib.request.urlopen) -> Bot:
    env = load_env(path)
    if not Path(path).exists():
        raise TelegramError(".env 파일이 없음. 'Copy-Item env.example .env' 로 만들고 토큰을 넣으세요")
    if not env.get("TELEGRAM_BOT_TOKEN"):
        raise TelegramError(".env 에 TELEGRAM_BOT_TOKEN 값이 비어 있음")
    return Bot(env["TELEGRAM_BOT_TOKEN"], env.get("TELEGRAM_CHAT_ID"), opener)


# --------------------------------------------------------------------------- 명령

def match_setup_code(updates: list[dict], code: str) -> str | None:
    """'/start <일회용 코드>' 를 개인 대화로 보낸 사람(봇 아님)의 chat id. 코드가 다르면 None.

    봇은 누구나 찾을 수 있으므로 '메시지를 보낸 사람'이 아니라 '코드를 아는 사람'만 본인으로 인정한다.
    """
    for u in updates:
        m = u.get("message") or {}
        if m.get("chat", {}).get("type") != "private" or m.get("from", {}).get("is_bot"):
            continue
        parts = (m.get("text") or "").split()
        # compare_digest 는 비ASCII 문자열을 받으면 예외를 낸다. 낯선 사람이 한글 등을 보내도 등록 절차가
        # 멈추지 않도록, ASCII 가 아닌 토큰은 불일치로 처리하고 바이트로 비교한다.
        if (len(parts) == 2 and parts[0].split("@")[0] == "/start" and parts[1].isascii()
                and hmac.compare_digest(parts[1].encode("ascii"), code.encode("ascii"))):
            return str(m["chat"]["id"])
    return None


def ack_updates(bot: Bot, updates: list[dict]) -> None:
    """처리한 업데이트를 텔레그램에 확인시켜 다시 받지 않게 한다(오래된 메시지를 소비)."""
    if updates:
        bot.get_updates(offset=max(u["update_id"] for u in updates) + 1)


def cmd_check(path: Path = ENV_PATH, opener=urllib.request.urlopen, out=print) -> int:
    env = load_env(path)
    out(f".env 파일: {'있음' if Path(path).exists() else '없음'}")
    out(f"TELEGRAM_BOT_TOKEN: {'입력됨' if env.get('TELEGRAM_BOT_TOKEN') else '비어 있음'}")
    out(f"TELEGRAM_CHAT_ID: {'입력됨' if env.get('TELEGRAM_CHAT_ID') else '비어 있음 (setup 으로 채움)'}")
    bot = bot_from_env(path, opener)
    me = bot.get_me()
    out(f"봇 연결: 성공 (이름 {me.get('first_name')!r}, @{me.get('username')})")
    return 0


def cmd_setup(path: Path = ENV_PATH, opener=urllib.request.urlopen, out=print, force: bool = False,
              code_fn: Callable[[], str] = lambda: secrets.token_hex(4), max_wait: int = 120) -> int:
    """본인 증명 후 chat id 등록. 화면에 나온 일회용 코드를 아는 사람의 '/start 코드'만 인정한다."""
    bot = bot_from_env(path, opener)
    if bot.chat_id and not force:
        raise TelegramError("이미 chat id 가 등록되어 있음. 바꾸려면 --force")
    me = bot.get_me()
    ack_updates(bot, bot.get_updates())  # 이전에 쌓인 메시지는 모두 버린다(오래된 낯선 메시지가 섞이지 않게)

    code = code_fn()
    out("본인 확인: 텔레그램에서 아래 중 하나를 하세요.")
    out(f"  1) 링크 열기: https://t.me/{me.get('username')}?start={code}  → START 버튼")
    out(f"  2) 봇 대화창에 직접 입력: /start {code}")
    out(f"(최대 {max_wait}초 기다립니다. 이 코드는 한 번만 유효합니다.)")

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        updates = bot.get_updates(timeout=min(20, max(1, int(deadline - time.monotonic()))))
        chat_id = match_setup_code(updates, code)
        ack_updates(bot, updates)
        if chat_id:
            update_env_value(path, "TELEGRAM_CHAT_ID", chat_id)
            bot.chat_id = chat_id
            bot.send_message("본인 확인 완료: 이 대화가 PM Workflow 승인 대화로 등록되었습니다.")
            out("TELEGRAM_CHAT_ID 를 .env 에 저장했습니다(값은 화면에 표시하지 않습니다).")
            return 0
    raise TelegramError("시간 안에 올바른 코드를 받지 못함. 다시 실행하세요")


def cmd_ping(path: Path = ENV_PATH, opener=urllib.request.urlopen, out=print) -> int:
    bot_from_env(path, opener).send_message("PM Workflow 봇 연결 확인: 이 메시지가 보이면 연결이 정상입니다.")
    out("연결 확인 메시지를 보냈습니다. 텔레그램에서 확인하세요.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cmds = {"check": cmd_check, "setup": cmd_setup, "ping": cmd_ping}
    args = argv if argv is not None else sys.argv[1:]
    force = args[1:] == ["--force"] and args[0] == "setup"
    if not args or args[0] not in cmds or (len(args) != 1 and not force):
        print("사용: python src/telegram_io.py check|ping|setup [--force]", file=sys.stderr)
        return 2
    try:
        return cmd_setup(force=True) if force else cmds[args[0]]()
    except TelegramError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
