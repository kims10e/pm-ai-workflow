"""Quality Gate: 4대 체크 이벤트와 정기 점검 누락 점검 (규칙 기반, AI 호출 없음).

    python src/pm_agent.py quality --week 7            # 7주차 기준으로 점검, outputs/quality/ 에 저장
    python src/pm_agent.py quality --week 7 --notify   # 요약을 텔레그램으로도 보낸다

같은 입력에는 항상 같은 결과가 나오고, 모든 판정에 근거 항목이 붙는다.
판정: FAIL(체크 이벤트·게이트 위반) > WARN(정기 점검 주의) > UNKNOWN(판단할 데이터 없음) > PASS > N/A(해당 단계 아님)
데이터가 없는 것을 PASS로 처리하지 않는다.

체크 이벤트 (docs/PM_Delivery_Process_Integrated.md)
  E1 Handover(G0)  E2 범위·OKR 합의 → 계획 승인 → 수행 순서(G1→G2→G3)
  E3 Workbook 기반 수행(주간 메모→승인·반영 기록의 연속성)  E4 고객 협의 종료(G4→G5)
정기 점검
  R1 액션 기한  R2 담당자 지정  R3 리스크 담당자  R4 리스크↔이슈 연결
  R5 High 이슈 장기 미해결  R6 변경 요청 장기 대기  R7 마일스톤 계획 주차 경과(고객 리뷰 누락 포함)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pm_agent
import telegram_io as tg
import workbook as wb

LEVELS = ["FAIL", "WARN", "UNKNOWN", "PASS", "N/A"]
_ORDER = {lv: i for i, lv in enumerate(LEVELS)}
ACTION_ACTIVE = {"Open", "In Progress"}
RISK_ACTIVE = {"Open", "Mitigating", "Occurred"}
ISSUE_ACTIVE = {"Open", "In Progress"}
STALE_WEEKS = 2  # 이슈·변경 요청이 이 주 수 이상 열려 있으면 장기 미해결로 본다


@dataclass
class Finding:
    key: str
    group: str  # "체크 이벤트" | "정기 점검"
    title: str
    level: str
    detail: str = ""
    items: list[str] = field(default_factory=list)
    action: str = ""


def _wk(text: str | None) -> int | None:
    m = re.search(r"W(\d+)", text or "", re.I)
    return int(m.group(1)) if m else None


def _wk_or_far(text: str | None) -> int:
    """주차를 못 읽으면 아주 먼 미래로 본다(기한 초과로 판정하지 않는다). 주차 0(W0)은 유효한 값이다."""
    w = _wk(text)
    return 99 if w is None else w


def _tbd(owner: str | None) -> bool:
    return (owner or "").strip().upper() in ("", "TBD")


def _gate_no(m: dict) -> int | None:
    g = re.fullmatch(r"G(\d+)", (m.get("gate") or "").strip())
    return int(g.group(1)) if g else None


def _added_weeks(history: list[dict]) -> dict[tuple[str, str], int]:
    """이력에서 항목이 처음 추가된 주차. (테이블, 키) -> 주차. 초기 기준선 항목은 알 수 없다."""
    out: dict[tuple[str, str], int] = {}
    for h in history:
        if h.get("op") == "add" and (h.get("week") or "").isdigit():
            out.setdefault((h["table"], h["key"]), int(h["week"]))
    return out


# --------------------------------------------------------------------------- 체크 이벤트

def _e1(data: wb.Data, week: int) -> Finding:
    ms = [m for m in data["milestones"] if _gate_no(m) == 0]
    f = Finding("E1", "체크 이벤트", "Handover 완료(G0)", "UNKNOWN")
    if not ms:
        f.detail = "Workbook에 G0(Handover) 마일스톤이 없어 확인할 수 없음"
        f.action = "milestones에 Handover(G0) 마일스톤을 추가하거나 Handover 체크리스트 기록을 남기세요"
        return f
    not_done = [m for m in ms if m["status"] != "Done"]
    if not not_done:
        f.level, f.detail = "PASS", "G0 마일스톤이 모두 완료됨"
    elif any(_wk_or_far(m["planned_week"]) < week for m in not_done):
        f.level, f.detail = "FAIL", "계획 주차가 지났는데 Handover가 완료되지 않음"
        f.items = [f"{m['id']} {m['milestone']} ({m['status']}, 계획 {m['planned_week']})" for m in not_done]
        f.action = "Handover를 완료하거나 일정을 조정하세요"
    else:
        f.level, f.detail = "N/A", "Handover 계획 주차 전"
    return f


def _e2(data: wb.Data, week: int) -> Finding:
    ms = [(m, k) for m in data["milestones"] if (k := _gate_no(m)) is not None]
    f = Finding("E2", "체크 이벤트", "합의→계획 승인→수행 순서(G1→G2→G3)", "PASS")
    if not ms:
        f.level, f.detail = "UNKNOWN", "게이트가 지정된 마일스톤이 없음"
        return f
    for m, k in ms:
        if m["status"] in ("In Progress", "Done"):
            behind = [(x, j) for x, j in ms if j < k and x["status"] != "Done"]
            if behind:
                f.items.append(
                    f"{m['id']}(G{k}) {m['status']} ← 선행 " + ", ".join(f"{x['id']}(G{j}) {x['status']}" for x, j in behind)
                )
    if f.items:
        f.level, f.detail = "FAIL", "선행 게이트가 끝나기 전에 다음 단계가 진행됨"
        f.action = "선행 게이트(범위·OKR 합의, 계획 승인)의 완료 기록을 확인하세요"
    else:
        f.detail = "선행 게이트가 완료된 뒤에 다음 단계가 진행됨"
    return f


def _e3(memo_weeks: set[int], approved_weeks: set[int], week: int) -> Finding:
    f = Finding("E3", "체크 이벤트", "Workbook 기반 수행(주간 메모→승인·반영)", "PASS")
    if not memo_weeks:
        f.level, f.detail = "UNKNOWN", "주간 업데이트 메모가 없어 확인할 수 없음"
        return f
    start = min(memo_weeks)
    if week < start:
        f.level, f.detail = "N/A", f"수행 기록 시작({start}주차) 전"
        return f
    unreflected = [w for w in range(start, week + 1) if w in memo_weeks and w not in approved_weeks]
    missing = [w for w in range(start, week + 1) if w not in memo_weeks]
    f.items = [f"{w}주차: 메모는 있으나 승인·반영 기록 없음" for w in unreflected] + \
              [f"{w}주차: 주간 업데이트 메모 없음" for w in missing]
    if unreflected:
        f.level, f.detail = "FAIL", "Workbook에 반영되지 않은 주차가 있음"
        f.action = "pm_agent approve 로 승인하거나 run 으로 초안을 만드세요"
    elif missing:
        f.level, f.detail = "WARN", "주간 업데이트가 빠진 주차가 있음"
        f.action = "빠진 주차의 메모를 입력하세요(/memo 주차)"
    else:
        f.detail = f"{start}~{week}주차 모두 메모와 승인·반영 기록이 있음"
    return f


def _e4(data: wb.Data, week: int) -> Finding:
    g4 = [m for m in data["milestones"] if _gate_no(m) == 4]
    g5 = [m for m in data["milestones"] if _gate_no(m) == 5]
    f = Finding("E4", "체크 이벤트", "고객 협의 종료(G4 인수→G5 종료)", "N/A", "종료 단계 전")
    if not g5:
        f.level, f.detail = "UNKNOWN", "G5(종료) 마일스톤이 없음"
        return f
    closing_started = [m for m in g5 if m["status"] in ("In Progress", "Done")]
    g4_open = [m for m in g4 if m["status"] != "Done"]
    if closing_started and g4_open:
        f.level, f.detail = "FAIL", "고객 인수(G4) 전에 종료가 진행됨"
        f.items = [f"{m['id']} {m['milestone']} ({m['status']})" for m in g4_open]
        f.action = "고객 인수 서명을 먼저 완료하세요"
    elif any(_wk_or_far(m["planned_week"]) < week and m["status"] != "Done" for m in g5):
        f.level, f.detail = "WARN", "종료 마일스톤의 계획 주차가 지났음"
    elif g5 and all(m["status"] == "Done" for m in g5):
        f.level, f.detail = "PASS", "고객 인수(G4) 후 종료(G5)가 완료됨"
    return f


# --------------------------------------------------------------------------- 정기 점검

def _r1(data: wb.Data, week: int) -> Finding:
    f = Finding("R1", "정기 점검", "액션 기한", "PASS", "기한을 넘긴 진행 중 액션이 없음")
    f.items = [
        f"{a['id']} {a['title']} (기한 W{_wk(a['due'])}, {a['status']})"
        for a in data["actions"] if a["status"] in ACTION_ACTIVE and _wk_or_far(a["due"]) < week
    ]
    if f.items:
        f.level, f.detail = "WARN", "기한을 넘긴 진행 중 액션이 있음"
        f.action = "완료 처리하거나 기한·담당자를 갱신하세요"
    return f


def _r2(data: wb.Data, week: int) -> Finding:
    f = Finding("R2", "정기 점검", "담당자 지정(액션·이슈)", "PASS", "열려 있는 액션·이슈의 담당자가 모두 지정됨")
    f.items = [f"액션 {a['id']} {a['title']}" for a in data["actions"] if a["status"] in ACTION_ACTIVE and _tbd(a["owner"])]
    f.items += [f"이슈 {i['id']} {i['title']}" for i in data["issues"] if i["status"] in ISSUE_ACTIVE and _tbd(i["owner"])]
    if f.items:
        f.level, f.detail = "WARN", "담당자가 TBD인 열린 항목이 있음"
        f.action = "담당자를 지정하세요"
    return f


def _r3(data: wb.Data, week: int) -> Finding:
    f = Finding("R3", "정기 점검", "리스크 담당자", "PASS", "열려 있는 리스크의 담당자가 모두 지정됨")
    f.items = [
        f"{r['id']} {r['title']} (점수 {r['score']})"
        for r in data["risks"] if r["status"] in RISK_ACTIVE and _tbd(r["owner"])
    ]
    if f.items:
        high = [r for r in data["risks"] if r["status"] in RISK_ACTIVE and _tbd(r["owner"]) and int(r["score"] or 0) >= 6]
        f.level = "WARN"
        f.detail = "담당자가 TBD인 열린 리스크가 있음" + (f" (점수 6 이상 {len(high)}건)" if high else "")
        f.action = "리스크 담당자를 지정하세요"
    return f


def _r4(data: wb.Data, week: int) -> Finding:
    f = Finding("R4", "정기 점검", "리스크↔이슈 연결", "PASS", "발생한 리스크와 이슈가 서로 맞음")
    for r in data["risks"]:
        linked = [i for i in data["issues"] if re.search(rf"\b{re.escape(r['id'])}\b", i["title"])]
        if r["status"] == "Occurred" and not linked:
            f.items.append(f"{r['id']} {r['title']}: 발생(Occurred) 상태인데 연결된 이슈 없음")
        if r["status"] == "Closed" and any(i["status"] in ISSUE_ACTIVE for i in linked):
            f.items.append(f"{r['id']} {r['title']}: 종료(Closed)인데 연결 이슈가 아직 열려 있음")
    if f.items:
        f.level, f.detail = "WARN", "리스크 상태와 이슈가 맞지 않음"
        f.action = "발생한 리스크는 이슈로 등록하고, 이슈가 끝난 뒤 리스크를 닫으세요"
    return f


def _r5(data: wb.Data, week: int) -> Finding:
    f = Finding("R5", "정기 점검", f"High 이슈 장기 미해결({STALE_WEEKS}주 이상)", "PASS", "오래 열려 있는 High 이슈가 없음")
    for i in data["issues"]:
        raised = _wk(i["raised"])
        if i["priority"] == "High" and i["status"] in ISSUE_ACTIVE and raised is not None and week - raised >= STALE_WEEKS:
            f.items.append(f"{i['id']} {i['title']} (W{raised} 등록, {week - raised}주째 {i['status']})")
    if f.items:
        f.level, f.detail = "WARN", "High 이슈가 오래 열려 있음"
        f.action = "에스컬레이션하거나 해결 계획을 세우세요"
    return f


def _r6(data: wb.Data, history: list[dict], week: int) -> Finding:
    f = Finding("R6", "정기 점검", f"변경 요청 장기 대기({STALE_WEEKS}주 이상)", "PASS", "오래 대기 중인 변경 요청이 없음")
    added = _added_weeks(history)
    for c in data["changes"]:
        w = added.get(("changes", c["id"]))
        if c["status"] == "Requested" and w is not None and week - w >= STALE_WEEKS:
            f.items.append(f"{c['id']} {c['title']} (W{w} 접수, {week - w}주째 승인 대기)")
    if f.items:
        f.level, f.detail = "WARN", "승인·기각이 정해지지 않은 변경 요청이 있음"
        f.action = "고객과 승인 여부를 확정하세요"
    return f


def _r7(data: wb.Data, week: int) -> Finding:
    f = Finding("R7", "정기 점검", "마일스톤 계획 주차 경과(고객 리뷰 누락)", "PASS", "계획 주차를 넘긴 미완료 마일스톤이 없음")
    review_missed = False
    for m in data["milestones"]:
        planned = _wk(m["planned_week"])
        if planned is None or planned >= week or m["status"] in ("Done", "Delayed"):
            continue
        is_review = _gate_no(m) == 3 and m["status"] == "Planned"
        review_missed = review_missed or is_review
        f.items.append(f"{m['id']} {m['milestone']} (계획 W{planned}, {m['status']}" + (", 고객 리뷰 누락 의심)" if is_review else ")"))
    if f.items:
        f.level = "FAIL" if review_missed else "WARN"
        f.detail = "Key Milestone 고객 리뷰가 시작되지 않음" if review_missed else "계획 주차를 넘겼는데 완료·지연으로 표시되지 않음"
        f.action = "완료 처리하거나 Delayed 로 표시하고 일정을 조정하세요"
    return f


# --------------------------------------------------------------------------- 실행·출력

def check(data: wb.Data, history: list[dict], memo_weeks: set[int], approved_weeks: set[int], week: int) -> list[Finding]:
    findings = [
        _e1(data, week), _e2(data, week), _e3(memo_weeks, approved_weeks, week), _e4(data, week),
        _r1(data, week), _r2(data, week), _r3(data, week), _r4(data, week),
        _r5(data, week), _r6(data, history, week), _r7(data, week),
    ]
    return sorted(findings, key=lambda x: (_ORDER[x.level], x.key))


def counts(findings: list[Finding]) -> dict[str, int]:
    return {lv: sum(1 for f in findings if f.level == lv) for lv in LEVELS}


def collect_context(paths: pm_agent.Paths) -> tuple[wb.Data, list[dict], set[int], set[int]]:
    data = wb.load_all(paths.workbook)
    history = wb.read_history(paths.workbook)
    weeks_of = lambda files: {int(m.group(1)) for p in files if (m := re.fullmatch(r"week(\d+)(?:\.md)?", p.name))}  # noqa: E731
    memo_weeks = weeks_of(paths.updates.glob("week*.md")) if paths.updates.exists() else set()
    approved = {int(h["week"]) for h in history if (h.get("week") or "").isdigit()}
    if paths.final.exists():
        approved |= weeks_of(p for p in paths.final.iterdir() if p.is_dir())
    return data, history, memo_weeks, approved


def render_markdown(findings: list[Finding], week: int) -> str:
    c = counts(findings)
    lines = [
        f"# Quality Gate 점검 — {week}주차 기준", "",
        "- 방식: 규칙 기반 점검(AI 호출 없음). 데이터가 없는 항목은 통과가 아니라 UNKNOWN으로 표시",
        "- 요약: " + " · ".join(f"{lv} {c[lv]}" for lv in LEVELS), "",
    ]
    for group in ("체크 이벤트", "정기 점검"):
        lines += [f"## {group}", "| 구분 | 점검 항목 | 판정 | 내용 | 조치 |", "|---|---|---|---|---|"]
        for f in (x for x in findings if x.group == group):
            lines.append(f"| {f.key} | {f.title} | {f.level} | {f.detail} | {f.action or '-'} |")
        lines.append("")
    detail = [f for f in findings if f.items]
    if detail:
        lines.append("## 근거 항목")
        for f in detail:
            lines.append(f"### {f.key} {f.title} — {f.level}")
            lines += [f"- {it}" for it in f.items]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_telegram(findings: list[Finding], week: int) -> str:
    c = counts(findings)
    lines = [f"[PM Workflow] {week}주차 Quality Gate", " · ".join(f"{lv} {c[lv]}" for lv in LEVELS if c[lv])]
    for f in findings:
        if f.level in ("FAIL", "WARN", "UNKNOWN"):
            lines.append(f"• {f.level} {f.key} {f.title}: {f.detail}")
    lines.append("전체 보고서: outputs/quality/")
    return "\n".join(lines)[:3900]


def run_quality(week: int, paths: pm_agent.Paths | None = None, notify: bool = False, bot: tg.Bot | None = None,
                log: Callable[[str], None] = print) -> int:
    """점검하고 outputs/quality/weekNN.md 에 저장한다. 반환: FAIL 이 있으면 1, 없으면 0."""
    paths = paths or pm_agent.Paths()
    findings = check(*collect_context(paths), week)
    out = paths.root / "outputs" / "quality" / f"week{week:02d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(findings, week), encoding="utf-8")

    c = counts(findings)
    log(f"[{week}주차] Quality Gate: " + " · ".join(f"{lv} {c[lv]}" for lv in LEVELS))
    for f in findings:
        if f.level in ("FAIL", "WARN", "UNKNOWN"):
            log(f"  {f.level:7} {f.key} {f.title} — {f.detail}")
            for it in f.items:
                log(f"            · {it}")
    log(f"저장: {out}")
    if notify:
        (bot or tg.bot_from_env()).send_message(format_telegram(findings, week))
        log("요약을 텔레그램으로 보냈습니다.")
    return 1 if c["FAIL"] else 0
