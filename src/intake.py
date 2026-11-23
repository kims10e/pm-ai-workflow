"""P0→P1: SOW에서 Handover 체크리스트·초기 리스크를 뽑고 Charter·공동 OKR 표를 만든다.

    python src/pm_agent.py intake [--notify]     # 초안 생성(Workbook 불변). --notify 면 텔레그램 승인 요청까지
    python src/pm_agent.py approve --week 0      # 승인하면 Workbook 반영 + 문서 3종 확정

AI(claude -p)는 JSON(내용)만 만들고, 이 모듈이 검증한 뒤 문서를 정해진 양식으로 렌더링한다.
- sow-intake  : 범위·가정·인수 조건·모호한 점 → Handover 확인 항목, 초기 리스크·M0 변경안
- charter-okr : Charter 내용과 공동 OKR 표. OKR은 Workbook okr 과 정확히 일치해야 한다(단일 기준 데이터).

Workbook에 들어갈 것(M0, 초기 리스크)은 변경안(week 0)으로 만들어 기존 approve 경로로 승인한다.
outputs/drafts/week00/  changeset.json, extraction.json, handover.md·docx, charter.md·docx, okr.md·docx, meta.json
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import md_to_docx
import pm_agent
import workbook as wb

CHECK_WITH = ["영업·프리세일즈", "고객", "내부(딜리버리)"]
PRIORITIES = ["P0", "P1", "P2"]
MAX_ATTEMPTS = 2
DOCUMENTS = ["handover", "charter", "okr"]


class IntakeError(ValueError):
    """AI 출력이 규칙에 맞지 않을 때. 사유를 알려주고 다시 시킨다."""


# --------------------------------------------------------------------------- 검증

def _strings(obj: Any, key: str, where: str, min_len: int = 1) -> list[str]:
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
        raise IntakeError(f"{where}.{key} 는 비어 있지 않은 문자열의 배열이어야 함")
    if len(v) < min_len:
        raise IntakeError(f"{where}.{key} 는 최소 {min_len}개가 필요함")
    return v


def _text(obj: Any, key: str, where: str) -> str:
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, str) or not v.strip():
        raise IntakeError(f"{where}.{key} 는 비어 있지 않은 문자열이어야 함")
    return v


def validate_sow(obj: dict, paths: pm_agent.Paths) -> dict:
    ext = obj.get("extraction")
    if not isinstance(ext, dict):
        raise IntakeError("extraction 객체가 없음")
    for key in ("scope_in", "scope_out", "assumptions", "acceptance_criteria", "governance", "review_and_change_rules"):
        _strings(ext, key, "extraction")
    _strings(ext, "ambiguities", "extraction", min_len=0)
    phases = ext.get("phases")
    if not isinstance(phases, list) or not phases:
        raise IntakeError("extraction.phases 는 비어 있지 않은 배열이어야 함")
    for i, p in enumerate(phases):
        if not isinstance(p, dict) or not re.fullmatch(r"P[1-5]", str(p.get("phase", ""))):
            raise IntakeError(f"extraction.phases[{i}].phase 는 P1~P5 중 하나여야 함")
        if p.get("weeks") is not None and not (isinstance(p["weeks"], int) and not isinstance(p["weeks"], bool)):
            raise IntakeError(f"extraction.phases[{i}].weeks 는 숫자 또는 null 이어야 함")
        _strings(p, "deliverables", f"extraction.phases[{i}]")

    items = obj.get("handover_checklist")
    if not isinstance(items, list) or not 5 <= len(items) <= 20:
        raise IntakeError("handover_checklist 는 5~20개의 배열이어야 함")
    seen = set()
    for i, it in enumerate(items):
        where = f"handover_checklist[{i}]"
        text = _text(it, "item", where)
        _text(it, "source", where)  # 근거 없는 항목은 받지 않는다
        if it.get("check_with") not in CHECK_WITH:
            raise IntakeError(f"{where}.check_with 는 {' / '.join(CHECK_WITH)} 중 하나여야 함 (받은 값: {it.get('check_with')!r})")
        if text.strip() in seen:
            raise IntakeError(f"{where}: 같은 항목이 중복됨")
        seen.add(text.strip())

    cs = obj.get("changeset")
    if not isinstance(cs, dict) or cs.get("week") != 0 or not isinstance(cs.get("changes"), list):
        raise IntakeError("changeset 은 week 가 0 이고 changes 배열을 가져야 함")
    for i, ch in enumerate(cs["changes"]):
        where = f"changeset.changes[{i}]"
        if not isinstance(ch, dict) or ch.get("op") != "add" or ch.get("table") not in ("milestones", "risks"):
            raise IntakeError(f"{where}: milestones 또는 risks 에 대한 add 만 허용")
        _text(ch, "reason", where)
        row = ch.get("row")
        if not isinstance(row, dict):
            raise IntakeError(f"{where}.row 는 객체여야 함")
        # 정규화한 값으로 판단한다("G00", " g0 " 같은 변형도 G0 로 본다). Workbook 의 허용 값 검증도 변형을 거부한다.
        if ch["table"] == "milestones" and re.fullmatch(r"G0+", str(row.get("gate", "")).strip().upper()) \
                and row.get("status") != "Planned":
            raise IntakeError(f"{where}: Handover(G0) 마일스톤의 status 는 Planned 여야 함. 완료 여부는 PM 이 정한다")
    try:
        wb.apply_changeset(cs, paths.workbook, dry_run=True)  # Workbook 규칙(허용 값·중복 ID 등) 검증
    except wb.WorkbookError as e:
        raise IntakeError(f"changeset 이 Workbook 규칙에 맞지 않음: {e}") from e
    _default_notes(obj)
    return obj


def _default_notes(obj: dict) -> None:
    """notes 는 선택 항목. 있으면 문자열 배열이어야 하고, 없으면 빈 배열로 채운다."""
    if "notes" in obj:
        _strings(obj, "notes", "(최상위)", min_len=0)
    else:
        obj["notes"] = []


def validate_charter(obj: dict, okr_rows: list[dict]) -> dict:
    ch = obj.get("charter")
    if not isinstance(ch, dict):
        raise IntakeError("charter 객체가 없음")
    for key in ("purpose", "background"):
        _text(ch, key, "charter")
    for key in ("objectives", "scope_in", "scope_out", "success_criteria", "assumptions", "governance", "approvals"):
        _strings(ch, key, "charter")
    _strings(ch, "constraints", "charter", min_len=0)
    for key, fields in (("roles", ("role", "responsibility")), ("milestones", ("id", "name", "week", "gate"))):
        rows = ch.get(key)
        if not isinstance(rows, list) or not rows:
            raise IntakeError(f"charter.{key} 는 비어 있지 않은 배열이어야 함")
        for i, r in enumerate(rows):
            for f in fields:
                _text(r, f, f"charter.{key}[{i}]")

    okr = obj.get("okr")
    if not isinstance(okr, list) or not okr:
        raise IntakeError("okr 는 비어 있지 않은 배열이어야 함")
    base = {r["key_result"]: r for r in okr_rows}
    got = [r.get("key_result") if isinstance(r, dict) else None for r in okr]
    if len(set(got)) != len(got) or set(got) != set(base):
        raise IntakeError(
            "okr 의 key_result 가 Workbook okr 과 정확히 같아야 함(문구·개수 동일). "
            f"Workbook: {sorted(base)} / 받은 값: {got}"
        )
    for i, r in enumerate(okr):
        for f in ("objective", "key_result", "success_metric", "dependency", "target_date", "priority"):
            _text(r, f, f"okr[{i}]")
        if r["priority"] not in PRIORITIES:
            raise IntakeError(f"okr[{i}].priority 는 {'/'.join(PRIORITIES)} 중 하나여야 함")
        if r["priority"] != base[r["key_result"]]["priority"]:
            raise IntakeError(f"okr[{i}].priority 는 Workbook 값({base[r['key_result']]['priority']})과 같아야 함")
    _default_notes(obj)
    return obj


# --------------------------------------------------------------------------- 프롬프트

def _project_name(scenario: str) -> str:
    first = scenario.strip().splitlines()[0] if scenario.strip() else ""
    return re.sub(r"^#\s*(가상 시나리오:\s*)?", "", first).strip() or "프로젝트(가상)"


def _retry_block(error: str | None, previous: str | None) -> str:
    if not error:
        return ""
    return (f"\n\n---\n직전에 낸 출력이 시스템 검증에서 거부되었다.\n거부 사유: {error}\n직전 출력:\n{previous}\n\n"
            "사유를 고쳐서 JSON 하나만 다시 출력해라.")


def build_sow_prompt(paths: pm_agent.Paths, sow: str, scenario: str, error=None, previous=None) -> str:
    return (
        f"{pm_agent.load_skill(paths, 'sow-intake')}\n\n---\n# 이번 입력\n\n{pm_agent._DATA_NOTICE}\n\n"
        f"## SOW 요약\n{sow}\n\n## 시나리오\n{scenario}\n\n{pm_agent._workbook_block(paths)}\n\n"
        f"위 지침대로 JSON 하나만 출력해라.{_retry_block(error, previous)}"
    )


def build_charter_prompt(paths: pm_agent.Paths, scenario: str, extraction: dict, error=None, previous=None) -> str:
    return (
        f"{pm_agent.load_skill(paths, 'charter-okr')}\n\n---\n# 이번 입력\n\n{pm_agent._DATA_NOTICE}\n\n"
        f"## sow-intake extraction\n```json\n{json.dumps(extraction, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 시나리오\n{scenario}\n\n{pm_agent._workbook_block(paths)}\n\n"
        f"위 지침대로 JSON 하나만 출력해라.{_retry_block(error, previous)}"
    )


# --------------------------------------------------------------------------- 문서 렌더링

def _cell(x: Any) -> str:
    return " ".join(str(x).replace("|", "/").split())


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- 없음"


_HEADER = "- 상태: 초안 (PM 승인 전)\n- 근거: SOW 요약(data/sow_sample.md)과 시나리오(data/scenario.md). 모두 가상 데이터"


def render_handover(project: str, sow: dict) -> str:
    ext, cs = sow["extraction"], sow["changeset"]
    phases = [[p["phase"], p["weeks"] if p["weeks"] is not None else "확인 필요", ", ".join(p["deliverables"])] for p in ext["phases"]]
    checklist = [[i, it["item"], it["source"], it["check_with"], "미확인"] for i, it in enumerate(sow["handover_checklist"], 1)]
    risks = [
        [ch["row"].get("title", ""), ch["row"].get("probability", ""), ch["row"].get("impact", ""),
         str(wb.LEVEL.get(ch["row"].get("probability"), 0) * wb.LEVEL.get(ch["row"].get("impact"), 0)), ch["reason"]]
        for ch in cs["changes"] if ch["table"] == "risks"
    ]
    m0 = [ch["row"] for ch in cs["changes"] if ch["table"] == "milestones"]
    lines = [
        f"# Handover 체크리스트 — {project}", "", _HEADER, "",
        "## 1. 범위 요약", "### 포함 범위", _bullets(ext["scope_in"]), "", "### 제외 범위", _bullets(ext["scope_out"]), "",
        "## 2. 단계와 산출물", _table(["단계", "기간(주)", "산출물"], phases), "",
        "## 3. 가정·인수 조건·운영 규칙",
        "### 가정", _bullets(ext["assumptions"]), "", "### 인수 조건", _bullets(ext["acceptance_criteria"]), "",
        "### 거버넌스", _bullets(ext["governance"]), "", "### 검토·변경 규칙", _bullets(ext["review_and_change_rules"]), "",
        "## 4. Handover 확인 항목", "영업·프리세일즈에서 딜리버리로 범위를 정확히 넘겨받았는지 확인합니다. 확인 결과는 회의 후 직접 기록하세요.",
        _table(["번호", "확인 항목", "근거", "확인 대상", "확인 결과"], checklist), "",
        "## 5. 초기 리스크 제안", "Workbook 반영은 승인할 때 일어납니다. 확률·영향은 AI 추정입니다.",
        _table(["리스크", "확률", "영향", "점수", "근거"], risks) if risks else "- 제안 없음", "",
        "## 6. SOW가 정하지 않았거나 해석이 갈리는 점", _bullets(ext["ambiguities"]), "",
        "## 7. Handover 마일스톤",
    ]
    if m0:
        r = m0[0]
        lines.append(f"- {r.get('id', 'M0')} {r.get('milestone', '')} (계획 {r.get('planned_week', '')}, 게이트 {r.get('gate', '')})는 "
                     f"{r.get('status', 'Planned')} 상태로 제안합니다. Handover를 이미 마쳤다면 승인하기 전에 changeset.json에서 Done으로 바꾸세요.")
    else:
        lines.append("- 제안 없음(Workbook에 이미 Handover 마일스톤이 있음)")
    lines += ["", "## 8. PM 확인 사항", _bullets(sow["notes"])]
    return "\n".join(lines) + "\n"


def render_charter(project: str, ch: dict, notes: list[str]) -> str:
    lines = [
        f"# Project Charter — {project}", "", _HEADER, "",
        "## 1. 목적과 배경", f"- 목적: {ch['purpose']}", f"- 배경: {ch['background']}", "",
        "## 2. 목표", _bullets(ch["objectives"]), "",
        "## 3. 범위", "### 포함", _bullets(ch["scope_in"]), "", "### 제외", _bullets(ch["scope_out"]), "",
        "## 4. 성공 기준", _bullets(ch["success_criteria"]), "",
        "## 5. 가정과 제약", "### 가정", _bullets(ch["assumptions"]), "", "### 제약", _bullets(ch["constraints"]), "",
        "## 6. 조직과 역할", _table(["역할", "책임"], [[r["role"], r["responsibility"]] for r in ch["roles"]]), "",
        "## 7. 거버넌스", _bullets(ch["governance"]), "",
        "## 8. 마일스톤", _table(["ID", "마일스톤", "계획 주차", "게이트"], [[m["id"], m["name"], m["week"], m["gate"]] for m in ch["milestones"]]), "",
        "## 9. 합의·서명", _table(["주체", "서명", "일자"], [[a, "", ""] for a in ch["approvals"]]), "",
        "## 10. PM 확인 사항", _bullets(notes),
    ]
    return "\n".join(lines) + "\n"


def render_okr(project: str, okr: list[dict]) -> str:
    rows = [[r["objective"], r["key_result"], r["success_metric"], r["dependency"], r["target_date"], r["priority"]] for r in okr]
    return "\n".join([
        f"# 공동 OKR 표 — {project}", "", _HEADER,
        "- 기준: 핵심 결과와 우선순위는 Workbook(okr.csv)과 같습니다. 고객과 합의(G1)하면 확정됩니다.", "",
        "## 공동 OKR", _table(["목표", "핵심 결과", "성공 지표", "의존성", "목표 일정", "우선순위"], rows), "",
    ])


# --------------------------------------------------------------------------- 실행

def _ask(llm: pm_agent.LLM, make_prompt: Callable[..., str], validate: Callable[[dict], dict], stage: str,
         dest: Path, log: Callable[[str], None]) -> dict:
    error = previous = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"  {stage} 중… (시도 {attempt}/{MAX_ATTEMPTS})")
        raw = llm(make_prompt(error, previous))
        try:
            return validate(wb.parse_changeset(raw))  # 앞뒤 설명·코드펜스가 있어도 첫 JSON 객체를 읽는다
        except (wb.WorkbookError, IntakeError) as e:
            error, previous = str(e), raw
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"rejected_{stage.split()[0]}_attempt{attempt}.txt").write_text(f"# 거부 사유: {e}\n\n{raw}", encoding="utf-8")
            log(f"  검증 거부: {e}")
    raise pm_agent.AgentError(f"{stage} 결과가 {MAX_ATTEMPTS}번 모두 검증을 통과하지 못함. {dest} 의 rejected_*.txt 확인")


def run_intake(paths: pm_agent.Paths | None = None, llm: pm_agent.LLM = pm_agent.call_claude, force: bool = False,
               log: Callable[[str], None] = print, now: datetime | None = None) -> Path:
    paths = paths or pm_agent.Paths()
    sow_path, scenario_path = paths.data / "sow_sample.md", paths.data / "scenario.md"
    for p in (sow_path, scenario_path):
        if not p.exists():
            raise pm_agent.AgentError(f"입력 문서가 없음: {p}")
    if paths.final_dir(0).exists() and not force:
        raise pm_agent.AgentError(f"착수 문서는 이미 확정됨({paths.final_dir(0)}). 다시 만들려면 --force")

    sow, scenario = sow_path.read_text(encoding="utf-8-sig"), scenario_path.read_text(encoding="utf-8-sig")
    project = _project_name(scenario)
    dest = paths.draft_dir(0)
    start_fp = wb.fingerprint(paths.workbook)
    okr_rows = wb.read_table("okr", paths.workbook)
    log(f"[착수] SOW·시나리오 읽음: {project}")

    sow_obj = _ask(llm, lambda e, p: build_sow_prompt(paths, sow, scenario, e, p), lambda o: validate_sow(o, paths),
                   "SOW 분석", dest, log)
    charter_obj = _ask(llm, lambda e, p: build_charter_prompt(paths, scenario, sow_obj["extraction"], e, p),
                       lambda o: validate_charter(o, okr_rows), "Charter·OKR 작성", dest, log)

    if wb.fingerprint(paths.workbook) != start_fp:
        raise pm_agent.AgentError("초안을 만드는 동안 Workbook이 바뀌었음. 다시 실행하세요.")

    texts = {
        "handover": render_handover(project, sow_obj),
        "charter": render_charter(project, charter_obj["charter"], charter_obj["notes"]),
        "okr": render_okr(project, charter_obj["okr"]),
    }
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("rejected_*.txt"):
        stale.unlink()
    for name, md in texts.items():
        (dest / f"{name}.md").write_text(md, encoding="utf-8")
        md_to_docx.markdown_to_docx(md, dest / f"{name}.docx")
    changeset_text = json.dumps(sow_obj["changeset"] | {"notes": sow_obj["notes"]}, ensure_ascii=False, indent=2) + "\n"
    (dest / "changeset.json").write_text(changeset_text, encoding="utf-8")
    (dest / "extraction.json").write_text(
        json.dumps({"sow_intake": sow_obj["extraction"], "charter_okr": charter_obj}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (dest / "meta.json").write_text(json.dumps({
        "week": 0, "status": "draft", "kind": "intake",
        "created_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "workbook_fingerprint": start_fp,
        "changeset_sha256": pm_agent._sha256(changeset_text),
        "changes": len(sow_obj["changeset"]["changes"]),
        "documents": DOCUMENTS,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    preview = wb.apply_changeset(json.loads(changeset_text), paths.workbook, dry_run=True)
    log("")
    log(f"Handover 확인 항목 {len(sow_obj['handover_checklist'])}개, OKR {len(charter_obj['okr'])}개 핵심 결과, "
        f"모호한 점 {len(sow_obj['extraction']['ambiguities'])}건")
    log(preview.summary())
    for n in sow_obj["notes"] + charter_obj["notes"]:
        log(f"  메모: {n}")
    log(f"\n초안 저장: {dest}")
    log("Workbook은 아직 바뀌지 않았습니다. 문서를 확인한 뒤 승인하세요(approve --week 0).")
    return dest
