"""텔레그램으로 주간 메모를 받아 저장하고, 초안 생성 → 승인 요청까지 이어 간다.

    python src/pm_agent.py listen            # Ctrl+C 로 끝낼 때까지 기다린다
    python src/pm_agent.py listen --once     # 메모 한 건을 처리하면 끝낸다(시연용)

텔레그램에서:
    /memo 8
    - 파일럿 리포트 전환 완료
    - 권한 이슈 해결
(또는 "/memo 8" 만 보낸 뒤 다음 메시지로 메모를 보낸다.)

안전장치
- 등록된 chat id 의 메시지만 처리한다(Bot.accept). 시작할 때 쌓여 있던 메시지는 버린다.
- 이미 있는 메모는 'force' 를 붙이지 않으면 덮어쓰지 않고, 이미 확정된 주차는 받지 않는다.
- 메모는 도구 없는 claude 호출에만 전달된다. 이후는 검증 → 사람 승인(버튼)을 그대로 거친다.
- 텔레그램 서버를 거치므로 가상 데이터만 보내야 한다(도움말에 안내).
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from typing import Callable

import approval_flow
import pm_agent
import telegram_io as tg

MAX_MEMO_CHARS = 3500
MIN_WEEK, MAX_WEEK = 1, 99
PENDING_TTL_SEC = 600  # "/memo 8" 만 보낸 뒤 메모를 기다려 주는 시간

HELP = (
    "PM Workflow 봇 사용법\n\n"
    "/memo 8\n- 이번 주 한 일\n- 이슈·리스크\n(첫 줄에 /memo 주차, 다음 줄부터 메모)\n\n"
    "또는 '/memo 8' 만 보낸 뒤 다음 메시지로 메모를 보내도 됩니다.\n"
    "이미 있는 주차를 덮어쓰려면 '/memo 8 force'.\n\n"
    "메모를 저장하면 보고서 초안을 만들고(약 5분) 승인 요청을 보냅니다.\n"
    "※ 가상 데이터만 보내세요. 실제 고객·기관·금액 정보는 입력하지 마세요."
)


class MemoError(ValueError):
    """사용자에게 그대로 보여줘도 되는 입력 오류."""


# --------------------------------------------------------------------------- 해석·저장

def parse_command(text: str) -> tuple[int, bool, str] | None:
    """'/memo 주차 [force]\\n본문' → (주차, force, 본문). /memo 명령이 아니면 None. 형식 오류는 MemoError."""
    lines = (text or "").strip().splitlines()
    if not lines:
        return None
    head = lines[0].split()
    if not head or head[0].split("@")[0] != "/memo":
        return None
    if len(head) < 2 or not head[1].isdigit():
        raise MemoError("주차를 숫자로 알려주세요. 예: /memo 8")
    week = int(head[1])
    if not MIN_WEEK <= week <= MAX_WEEK:
        raise MemoError(f"주차는 {MIN_WEEK}~{MAX_WEEK} 사이여야 합니다")
    force = any(a.lower() in ("force", "덮어쓰기") for a in head[2:])
    return week, force, "\n".join(lines[1:]).strip()


def normalize_memo(week: int, body: str) -> str:
    """기존 메모 파일 형식(제목 한 줄 + '- ' 글머리)으로 맞춘다."""
    items = []
    for raw in body.splitlines():
        line = re.sub(r"^\s*(?:[-*•·]\s*)?", "", raw).strip()
        if line:
            items.append(f"- {line}")
    if not items:
        raise MemoError("메모 내용이 비어 있습니다")
    return f"# 주간 업데이트 메모 — {week}주차 (가상)\n" + "\n".join(items) + "\n"


def save_memo(paths: pm_agent.Paths, week: int, body: str, force: bool = False) -> Path:
    if len(body) > MAX_MEMO_CHARS:
        raise MemoError(f"메모가 너무 깁니다({len(body)}자). {MAX_MEMO_CHARS}자 이내로 줄여주세요")
    text = normalize_memo(week, body)
    if paths.final_dir(week).exists():
        raise MemoError(f"{week}주차는 이미 확정되어 메모를 받을 수 없습니다")
    target = paths.memo(week)
    if target.exists() and not force:
        raise MemoError(f"{week}주차 메모가 이미 있습니다. 덮어쓰려면 '/memo {week} force'")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:  # BOM 없는 UTF-8
            f.write(text)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return target


# --------------------------------------------------------------------------- 듣기

def listen(
    paths: pm_agent.Paths | None = None,
    bot: tg.Bot | None = None,
    once: bool = False,
    listen_sec: int | None = None,
    wait_sec: int = 1800,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    llm: pm_agent.LLM = pm_agent.call_claude,
) -> int:
    """메모를 받아 처리한 건수를 돌려준다. once 면 한 건 처리 후, listen_sec 가 지나면 끝난다."""
    paths = paths or pm_agent.Paths()
    bot = bot or tg.bot_from_env()
    if not bot.chat_id:
        raise pm_agent.AgentError("텔레그램 chat id 가 등록되지 않음. python src/telegram_io.py setup 을 먼저 실행하세요")

    tg.ack_updates(bot, bot.get_updates())  # 시작 전에 쌓인 메시지는 처리하지 않는다
    bot.send_message("PM Workflow 대기 중입니다. 사용법은 /help")
    log("텔레그램 메모를 기다립니다. 끝내려면 Ctrl+C")

    started = clock()
    pending: tuple[int, bool, float] | None = None  # (주차, force, 시작 시각)
    handled = 0

    while listen_sec is None or clock() - started < listen_sec:
        updates = bot.get_updates(timeout=20)
        tg.ack_updates(bot, updates)
        for u in updates:
            msg = (bot.accept(u) or {}).get("message")
            text = (msg or {}).get("text")
            if not text:
                continue

            week = force = body = None
            try:
                cmd = parse_command(text)
                if cmd:
                    week, force, body = cmd
                    pending = None
                elif text.strip().split()[0].split("@")[0] in ("/help", "/start"):
                    bot.send_message(HELP)
                    continue
                elif pending and clock() - pending[2] <= PENDING_TTL_SEC:
                    week, force, body = pending[0], pending[1], text
                    pending = None
                else:
                    pending = None
                    bot.send_message("메모는 '/memo 주차' 로 시작해 보내주세요. 사용법은 /help")
                    continue

                if not body:  # '/memo 8' 만 온 경우: 다음 메시지를 메모로 받는다
                    pending = (week, force, clock())
                    bot.send_message(f"{week}주차 메모를 보내주세요. (가상 데이터만, {PENDING_TTL_SEC // 60}분 안에)")
                    continue
                path = save_memo(paths, week, body, force)
            except MemoError as e:
                bot.send_message(f"저장하지 않았습니다: {e}")
                continue

            lines = path.read_text(encoding="utf-8").count("\n- ")
            bot.send_message(f"{week}주차 메모를 저장했습니다({lines}줄). 보고서 초안을 만듭니다. 약 5분 걸립니다.")
            log(f"[{week}주차] 메모 저장: {path.name}")
            handled += 1
            _process(week, paths, bot, llm, wait_sec, log, clock)
            if once:
                return handled
    return handled


def _process(week, paths, bot, llm, wait_sec, log, clock) -> None:
    """저장한 메모로 초안을 만들고 승인 요청을 보낸다. 실패는 사용자에게 알리고 듣기를 이어 간다."""
    try:
        pm_agent.run_week(week, paths, llm=llm, force=False, log=log)
    except pm_agent.AgentError as e:
        bot.send_message(f"{week}주차 초안을 만들지 못했습니다.\n사유: {approval_flow._clip(str(e), 300)}")
        log(f"초안 생성 실패: {e}")
        return
    try:
        approval_flow.request_approval(week, paths, bot, wait_sec=wait_sec, log=log, clock=clock)
    except (pm_agent.AgentError, tg.TelegramError) as e:
        bot.send_message(f"{week}주차 승인 요청을 보내지 못했습니다.\n사유: {approval_flow._clip(str(e), 300)}")
        log(f"승인 요청 실패: {e}")
