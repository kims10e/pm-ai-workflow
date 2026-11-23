"""텔레그램 승인 요청: 변경안 요약을 보내고 [승인] [반려] 버튼 입력을 기다린다.

    python src/pm_agent.py run --week 5 --notify       # 초안 생성 후 승인 요청
    python src/pm_agent.py request --week 5            # 이미 만든 초안의 승인 요청만 보내기

사람이 버튼을 직접 눌러야 승인된다(Human-in-the-loop). 안전장치:
- 요청을 보내기 전에 쌓여 있던 입력은 모두 버린다(오래된 버튼 입력 재사용 방지).
- 버튼은 방금 보낸 그 메시지(message_id)와 이 변경안(해시)에 묶여 있다. 다른 주차·오래된 요청의 버튼은 무시한다.
- 등록된 chat id 가 아닌 곳의 입력은 Bot.accept 가 버린다.
- 결정이 나면 버튼을 지우고 바로 끝낸다. 승인은 pm_agent.approve_week 를 그대로 쓰므로
  중복 승인 차단·초안 최신성 검사(Workbook 지문)가 똑같이 적용된다.
- 시간 안에 누르지 않으면 승인되지 않은 채 끝난다(Workbook 불변).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Callable

import pm_agent
import telegram_io as tg
import workbook as wb

TELEGRAM_LIMIT = 3900  # 텔레그램 메시지 한도는 4096자. 여유를 둔다
_CALLBACK = re.compile(r"^(approve|reject):(\d+):([0-9a-f]{8})$")


def _nonce(changeset_text: str) -> str:
    return hashlib.sha256(changeset_text.encode("utf-8")).hexdigest()[:8]


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


ITEM_LIMIT = 420  # 변경 한 건을 보여줄 최대 글자 수. 넘으면 잘린 것이므로 버튼 승인을 하지 않는다


def build_summary(week: int, cs: dict, preview: wb.Result, report_md: str,
                  documents: list[str] | None = None) -> tuple[str, bool]:
    """승인 요청 메시지와 '변경을 하나도 빠뜨리지 않고 보여줬는지'(complete)를 돌려준다.

    complete 가 False(변경이 잘리거나 생략됨)이면 호출한 쪽은 승인 버튼을 붙이면 안 된다.
    확인할 점(notes)이 생략되는 것은 완전성에 영향을 주지 않는다. 변경 목록이 notes 보다 먼저 나온다.
    """
    documents = documents or ["report"]
    head = [f"[PM Workflow] {pm_agent.week_label(week)} 승인 요청"]
    if week > 0:  # 착수 문서(0)에는 RAG가 없다
        rag = re.search(r"전체 RAG:\s*(Green|Amber|Red)", report_md)
        head.append(f"전체 RAG: {rag.group(1) if rag else '확인 필요'}")
    head += [f"변경 {len(preview.applied)}건 (승인 전까지 Workbook은 바뀌지 않습니다)", ""]

    complete, changes, used = True, [], len("\n".join(head))
    budget = TELEGRAM_LIMIT - 900  # 확인할 점·안내 문구를 위한 여유
    for i, a in enumerate(preview.applied):
        line = "• " + " ".join(a.describe().split())
        if len(line) > ITEM_LIMIT:
            complete, line = False, line[: ITEM_LIMIT - 1] + "…"
        if used + len(line) + 1 > budget:
            changes.append(f"• …외 {len(preview.applied) - i}건 생략")
            complete = False
            break
        changes.append(line)
        used += len(line) + 1
    lines = head + changes

    notes = cs.get("notes") or []
    if notes:
        lines += ["", "확인할 점"]
        shown = 0
        for n in notes[:6]:
            line = f"• {_clip(n, 200)}"
            if len("\n".join(lines)) + len(line) > TELEGRAM_LIMIT - 500:
                break
            lines.append(line)
            shown += 1
        if shown < len(notes):
            lines.append(f"• …외 {len(notes) - shown}건 (changeset.json 참고)")

    lines += ["", "※ 신규 리스크의 확률·영향 등 AI 추정이 포함될 수 있습니다.",
              "문서 초안: " + ", ".join(f"outputs/drafts/week{week:02d}/{d}.docx" for d in documents)]
    if complete:
        lines.append("아래 버튼으로 승인 또는 반려하세요.")
    else:
        lines.append("※ 변경이 길어 전부 보여드리지 못했습니다. 보지 못한 변경을 버튼으로 승인할 수는 없어 버튼을 붙이지 않았습니다. "
                     f"터미널에서 전체를 확인하고 승인하세요: python src/pm_agent.py approve --week {week}")
    text = "\n".join(lines)
    if len(text) > TELEGRAM_LIMIT:  # 안전망. 여기까지 오면 완전하지 않은 것으로 본다
        text, complete = text[: TELEGRAM_LIMIT - 1] + "…", False
    return text, complete


def format_summary(week: int, cs: dict, preview: wb.Result, report_md: str, documents: list[str] | None = None) -> str:
    return build_summary(week, cs, preview, report_md, documents)[0]


def request_approval(
    week: int,
    paths: pm_agent.Paths | None = None,
    bot: tg.Bot | None = None,
    wait_sec: int = 1800,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    approve_fn: Callable[..., bool] = pm_agent.approve_week,
    now: datetime | None = None,
) -> str:
    """승인 요청을 보내고 결정을 기다린다. 반환: approved | rejected | timeout | failed | needs_cli(요약이 잘려 버튼 없음)."""
    paths = paths or pm_agent.Paths()
    bot = bot or tg.bot_from_env()
    if not bot.chat_id:
        raise pm_agent.AgentError("텔레그램 chat id 가 등록되지 않음. python src/telegram_io.py setup 을 먼저 실행하세요")

    label = pm_agent.week_label(week)
    redo = "intake" if week == 0 else f"run --week {week}"
    draft = paths.draft_dir(week)
    if not (draft / "meta.json").exists():
        raise pm_agent.AgentError(f"{label} 초안이 없음({draft / 'meta.json'}). 먼저 {redo}")
    meta = json.loads((draft / "meta.json").read_text(encoding="utf-8"))
    docs = meta.get("documents", ["report"])
    for name in ["changeset.json"] + [f"{d}.md" for d in docs]:
        if not (draft / name).exists():
            raise pm_agent.AgentError(f"{label} 초안이 없음({draft / name}). 먼저 {redo}")
    if paths.final_dir(week).exists():
        raise pm_agent.AgentError(f"{label}는 이미 확정됨")
    if meta.get("status") == "rejected":
        raise pm_agent.AgentError(f"{label} 초안은 반려되었음. {redo} 로 다시 만드세요")

    cs_text = (draft / "changeset.json").read_text(encoding="utf-8")
    try:
        cs = json.loads(cs_text)
        preview = wb.apply_changeset(cs, paths.workbook, dry_run=True)
    except (json.JSONDecodeError, wb.WorkbookError) as e:
        raise pm_agent.AgentError(f"변경안이 유효하지 않음: {e}") from e
    nonce = _nonce(cs_text)

    tg.ack_updates(bot, bot.get_updates())  # 이전에 쌓인 입력(오래된 버튼 포함)은 모두 버린다
    text, complete = build_summary(week, cs, preview, (draft / f"{docs[0]}.md").read_text(encoding="utf-8"), docs)
    if not complete:
        # 변경이 잘리거나 생략된 요약으로는 버튼 승인을 받지 않는다. 요약만 보내고 터미널 승인으로 돌린다.
        bot.send_message(text)
        log(f"[{label}] 변경이 길어 텔레그램에 다 표시하지 못해 버튼 승인을 지원하지 않습니다. 터미널에서 approve --week {week} 로 승인하세요.")
        return "needs_cli"
    sent = bot.send_message(
        text,
        reply_markup={"inline_keyboard": [[
            {"text": "승인", "callback_data": f"approve:{week}:{nonce}"},
            {"text": "반려", "callback_data": f"reject:{week}:{nonce}"},
        ]]},
    )
    mid = sent["message_id"]
    log(f"[{label}] 승인 요청을 텔레그램으로 보냈습니다. 버튼을 누를 때까지 최대 {wait_sec // 60}분 기다립니다.")

    deadline = clock() + wait_sec
    while clock() < deadline:
        updates = bot.get_updates(timeout=min(20, max(1, int(deadline - clock()))))
        tg.ack_updates(bot, updates)
        for u in updates:
            cb = (bot.accept(u) or {}).get("callback_query")
            if not cb:
                continue  # 일반 메시지는 무시
            m = _CALLBACK.match(cb.get("data", ""))
            valid = bool(m) and int(m.group(2)) == week and m.group(3) == nonce \
                and cb.get("message", {}).get("message_id") == mid
            if not valid:
                bot.answer_callback_query(cb["id"], "이 요청의 버튼이 아닙니다.")
                continue
            bot.answer_callback_query(cb["id"], "처리 중…")
            bot.remove_buttons(mid)
            return _decide(m.group(1), week, paths, bot, approve_fn, log, now)

    bot.remove_buttons(mid)
    bot.send_message(
        f"{label} 승인 시간이 지났습니다. 승인되지 않았고 Workbook은 바뀌지 않았습니다.\n"
        f"나중에 승인하려면: python src/pm_agent.py request --week {week}"
    )
    log("시간 초과: 승인되지 않았습니다.")
    return "timeout"


def _decide(action: str, week: int, paths: pm_agent.Paths, bot: tg.Bot, approve_fn, log, now) -> str:
    if action == "reject":
        meta_path = paths.draft_dir(week) / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(status="rejected", rejected_at=(now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"))
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        redo = "intake --notify" if week == 0 else f"run --week {week} --notify"
        bot.send_message(
            f"{pm_agent.week_label(week)}를 반려했습니다. Workbook은 바뀌지 않았습니다.\n"
            f"내용을 고친 뒤 python src/pm_agent.py {redo} 로 다시 만드세요."
        )
        log("반려: Workbook은 바뀌지 않았습니다.")
        return "rejected"

    captured: list[str] = []
    try:
        approve_fn(week, paths, confirm=lambda: True, log=captured.append)  # 버튼 누름이 사람의 확인
    except pm_agent.AgentError as e:
        bot.send_message(f"{pm_agent.week_label(week)}를 승인하지 못했습니다(Workbook 변경 없음).\n사유: {_clip(str(e), 300)}")
        log(f"승인 실패: {e}")
        return "failed"
    except Exception:
        bot.send_message("예상하지 못한 오류가 났습니다. 승인되지 않았을 수 있으니 터미널에서 확인하세요.")
        raise

    final_meta = json.loads((paths.final_dir(week) / "meta.json").read_text(encoding="utf-8"))
    names = ", ".join(f"{d}.docx" for d in final_meta.get("documents", ["report"]))
    bot.send_message(
        f"{pm_agent.week_label(week)} 승인 완료: Workbook {final_meta.get('applied', '?')}건 반영, 이력 기록.\n"
        f"확정 문서: outputs/final/week{week:02d}/ ({names})"
    )
    log(f"승인 완료: Workbook {final_meta.get('applied', '?')}건 반영")
    return "approved"
