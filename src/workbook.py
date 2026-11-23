"""Project Workbook(CSV) 읽기·쓰기와 변경안(diff) 적용.

- CSV는 UTF-8(BOM 없음), 줄바꿈은 LF로 읽고 쓴다.
- 변경안(changeset)은 JSON이며, 승인 전에는 파일에 쓰지 않는다(Human-in-the-loop).
  apply_changeset(..., dry_run=True)로 미리보기만 만들고, 승인 후 dry_run=False로 반영한다.
- 검증은 전부 메모리에서 먼저 끝낸다. 하나라도 오류면 아무 파일도 쓰지 않는다.

변경안 형식:
{
  "week": 5,
  "changes": [
    {"table": "risks",   "op": "add",    "row": {"title": "...", "probability": "M", "impact": "H", ...}},
    {"table": "actions", "op": "update", "key": "A-002", "fields": {"status": "Done"}}
  ]
}
"""

from __future__ import annotations

import copy
import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "workbook"

# 테이블 정의: 파일명, 컬럼, 기본키, 자동 ID 접두어(없으면 ID 자동 생성 안 함)
TABLES: dict[str, dict] = {
    "actions": {
        "file": "actions.csv",
        "columns": ["id", "title", "owner", "due", "status", "source"],
        "key": "id",
        "prefix": "A",
    },
    "risks": {
        "file": "risks.csv",
        "columns": ["id", "title", "probability", "impact", "score", "owner", "mitigation", "status"],
        "key": "id",
        "prefix": "R",
    },
    "issues": {
        "file": "issues.csv",
        "columns": ["id", "title", "raised", "owner", "priority", "status", "resolution"],
        "key": "id",
        "prefix": "I",
    },
    "changes": {
        "file": "changes.csv",
        "columns": ["id", "title", "requested_by", "impact_scope", "impact_schedule", "impact_cost", "status"],
        "key": "id",
        "prefix": "C",
    },
    "milestones": {
        "file": "milestones.csv",
        "columns": ["id", "phase", "milestone", "planned_week", "status", "gate"],
        "key": "id",
        "prefix": "M",
    },
    # OKR에는 id가 없어 key_result 문구를 기본키로 쓴다. 새 KR 추가는 하지 않고 current 갱신만 허용한다.
    "okr": {
        "file": "okr.csv",
        "columns": ["objective", "key_result", "target", "current", "unit", "priority"],
        "key": "key_result",
        "prefix": None,
        "update_only": True,
    },
}

# 허용 값 목록. 변경안이 쓰는 필드에만 적용한다(AI가 "완료", "done " 같은 임의 값을 만드는 것을 막는다).
ENUMS: dict[str, dict[str, list[str]]] = {
    "actions": {"status": ["Open", "In Progress", "Done", "Cancelled"]},
    "risks": {
        "probability": ["L", "M", "H"],
        "impact": ["L", "M", "H"],
        "status": ["Open", "Mitigating", "Occurred", "Closed"],
    },
    "issues": {
        "priority": ["High", "Medium", "Low"],
        "status": ["Open", "In Progress", "Resolved", "Closed"],
    },
    "changes": {"status": ["Requested", "Approved", "Rejected", "Implemented"]},
    "milestones": {
        "phase": ["P0", "P1", "P2", "P3", "P4", "P5"],
        "status": ["Planned", "In Progress", "Done", "Delayed"],
        # 정확히 이 표기만 허용한다. "G00", "G0 " 같은 변형을 한쪽 검증은 통과시키고 다른 쪽은 G0 로 읽는 일을 막는다.
        "gate": ["G0", "G1", "G2", "G3", "G4", "G5"],
    },
}

# add 할 때 값이 없으면 채우는 기본값
DEFAULTS: dict[str, dict[str, str]] = {
    "actions": {"status": "Open"},
    "risks": {"status": "Open"},
    "issues": {"status": "Open"},
    "changes": {"status": "Requested"},
}

HISTORY_FILE = "history.csv"
HISTORY_COLUMNS = ["applied_at", "week", "table", "op", "key", "before", "after", "reason"]

LEVEL = {"L": 1, "M": 2, "H": 3}


class WorkbookError(ValueError):
    """변경안이 Workbook 규칙에 맞지 않을 때 발생. 이때는 아무 파일도 바뀌지 않는다."""


Row = dict[str, str]
Data = dict[str, list[Row]]


# --------------------------------------------------------------------------- 읽기·쓰기

def _spec(table: str) -> dict:
    if table not in TABLES:
        raise WorkbookError(f"알 수 없는 테이블: {table!r} (가능: {', '.join(TABLES)})")
    return TABLES[table]


def read_table(table: str, workbook_dir: Path = DEFAULT_DIR) -> list[Row]:
    spec = _spec(table)
    path = Path(workbook_dir) / spec["file"]
    # utf-8-sig: 엑셀 등이 BOM을 붙여 저장해도 읽을 수 있게 한다. 쓸 때는 BOM을 붙이지 않는다.
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != spec["columns"]:
            raise WorkbookError(f"{spec['file']} 컬럼이 정의와 다름: {reader.fieldnames} != {spec['columns']}")
        return [dict(r) for r in reader]


def _atomic_write(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 교체한다. 쓰는 도중 중단돼도 원본이 깨지지 않는다."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _to_csv_text(columns: list[str], rows: list[Row]) -> str:
    import io

    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def write_table(table: str, rows: list[Row], workbook_dir: Path = DEFAULT_DIR) -> None:
    spec = _spec(table)
    _atomic_write(Path(workbook_dir) / spec["file"], _to_csv_text(spec["columns"], rows))


def load_all(workbook_dir: Path = DEFAULT_DIR) -> Data:
    return {t: read_table(t, workbook_dir) for t in TABLES}


def fingerprint(workbook_dir: Path = DEFAULT_DIR) -> str:
    """Workbook 내용의 지문(sha256). 초안을 만든 뒤 Workbook이 바뀌었는지 승인 때 확인하는 데 쓴다.

    줄바꿈 차이(CRLF/LF)와 BOM은 무시한다. 이력(history.csv)은 포함하지 않는다.
    """
    import hashlib

    h = hashlib.sha256()
    for t in TABLES:
        raw = (Path(workbook_dir) / TABLES[t]["file"]).read_bytes()
        raw = raw.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
        h.update(t.encode() + b"\0" + raw + b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------- 변경안 적용

@dataclass
class Applied:
    """변경안 한 건을 적용한 결과(미리보기·이력 공용)."""

    table: str
    op: str
    key: str
    before: Row | None
    after: Row
    reason: str = ""

    def describe(self) -> str:
        if self.op == "add":
            label = self.after.get("title") or self.after.get("milestone") or self.after.get("key_result", "")
            # 승인하는 사람이 새 항목의 값(확률·담당자·상태 등)을 모두 볼 수 있게 비어 있지 않은 칸을 전부 보여준다
            skip = {TABLES[self.table]["key"], "title", "milestone"}
            extras = ", ".join(f"{c}={v}" for c, v in self.after.items() if c not in skip and v != "")
            return f"[{self.table}] 추가 {self.key}: {label}" + (f" ({extras})" if extras else "")
        diffs = [
            f"{c}: {self.before.get(c, '')!r} → {v!r}"
            for c, v in self.after.items()
            if self.before is not None and self.before.get(c) != v
        ]
        return f"[{self.table}] 수정 {self.key}: " + ("; ".join(diffs) if diffs else "(변경 없음)")


@dataclass
class Result:
    week: int | None
    applied: list[Applied] = field(default_factory=list)
    dry_run: bool = True

    def summary(self) -> str:
        head = "미리보기(파일 변경 없음)" if self.dry_run else "반영 완료"
        lines = [f"{head}: {len(self.applied)}건"]
        lines += [f"  - {a.describe()}" for a in self.applied]
        return "\n".join(lines)


def next_id(table: str, rows: list[Row]) -> str:
    spec = _spec(table)
    prefix = spec["prefix"]
    if not prefix:
        raise WorkbookError(f"{table}는 ID 자동 생성을 지원하지 않는다")
    width = 3
    nums = []
    for r in rows:
        k = r[spec["key"]]
        if k.startswith(prefix + "-") and k[len(prefix) + 1:].isdigit():
            nums.append(int(k[len(prefix) + 1:]))
    return f"{prefix}-{(max(nums) + 1 if nums else 1):0{width}d}"


_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")


def _formula_like(value: str) -> bool:
    """스프레드시트가 수식으로 실행할 수 있는 값인지. 앞의 공백을 건너뛴 첫 글자가 = + - @ 탭 CR 이면 그렇다(숫자는 제외)."""
    s = value.lstrip(" ")
    return bool(s) and s[0] in "=+-@\t\r" and not _NUMBER.fullmatch(s.strip())


def _check_cells(values: Row, where: str) -> None:
    """CSV 를 Excel 등으로 열 때 수식이 실행되는 것(CSV injection)을 막는다. 거부하면 AI 가 앞의 기호를 빼고 다시 쓴다."""
    for col, v in values.items():
        if _formula_like(v):
            raise WorkbookError(
                f"{where}: {col} 값이 '{v.lstrip(' ')[0]}' 기호로 시작함. 스프레드시트에서 수식으로 실행될 수 있어 "
                "허용하지 않음. 앞의 기호를 빼고 쓰세요"
            )


def csv_safe(text: str) -> str:
    """이력처럼 사람이 읽는 자유 문장을 CSV 에 쓸 때 수식으로 실행되지 않게 앞에 작은따옴표를 붙인다."""
    return "'" + text if _formula_like(text) else text


def _stringify(row: dict) -> Row:
    return {k: "" if v is None else str(v) for k, v in row.items()}


def _check_columns(table: str, cols, where: str) -> None:
    allowed = set(_spec(table)["columns"])
    unknown = [c for c in cols if c not in allowed]
    if unknown:
        raise WorkbookError(f"{where}: {table}에 없는 컬럼 {unknown} (가능: {sorted(allowed)})")


def _check_enums(table: str, values: Row, where: str) -> None:
    for col, allowed in ENUMS.get(table, {}).items():
        v = values.get(col)
        if v not in (None, "") and v not in allowed:
            raise WorkbookError(f"{where}: {table}.{col} 값 {v!r}은 허용되지 않음 (가능: {', '.join(allowed)})")


def _fill_score(table: str, row: Row) -> None:
    """리스크 점수 = 확률 × 영향 (L=1, M=2, H=3). 확률·영향이 바뀌면 항상 다시 계산한다."""
    if table != "risks":
        return
    p, i = row.get("probability", ""), row.get("impact", "")
    if p not in LEVEL or i not in LEVEL:
        raise WorkbookError(f"risks: probability/impact는 L·M·H 중 하나여야 함 (받은 값: {p!r}, {i!r})")
    row["score"] = str(LEVEL[p] * LEVEL[i])


def _apply_one(data: Data, ch: dict, idx: int) -> Applied:
    where = f"changes[{idx}]"
    if not isinstance(ch, dict):
        raise WorkbookError(f"{where}: 객체여야 함")
    table, op = ch.get("table"), ch.get("op")
    spec = _spec(table)
    rows = data[table]
    key_col = spec["key"]

    if op == "add":
        if spec.get("update_only"):
            raise WorkbookError(f"{where}: {table}는 추가할 수 없고 갱신만 가능")
        raw = ch.get("row")
        if not isinstance(raw, dict):
            raise WorkbookError(f"{where}: add에는 row 객체가 필요")
        _check_columns(table, raw, where)
        row = {c: "" for c in spec["columns"]}
        row.update(DEFAULTS.get(table, {}))
        row.update(_stringify(raw))
        _check_enums(table, row, where)
        _check_cells(_stringify(raw), where)
        if not row[key_col]:
            row[key_col] = next_id(table, rows)
        if any(r[key_col] == row[key_col] for r in rows):
            raise WorkbookError(f"{where}: {table}에 이미 있는 {key_col} {row[key_col]!r}")
        _fill_score(table, row)
        rows.append(row)
        return Applied(table, op, row[key_col], None, copy.deepcopy(row), str(ch.get("reason", "")))

    if op == "update":
        key = ch.get("key")
        fields = ch.get("fields")
        if not key or not isinstance(fields, dict) or not fields:
            raise WorkbookError(f"{where}: update에는 key와 비어 있지 않은 fields가 필요")
        _check_columns(table, fields, where)
        if key_col in fields and str(fields[key_col]) != key:
            raise WorkbookError(f"{where}: 기본키({key_col})는 바꿀 수 없음")
        target = next((r for r in rows if r[key_col] == key), None)
        if target is None:
            raise WorkbookError(f"{where}: {table}에서 {key_col}={key!r}를 찾을 수 없음")
        _check_enums(table, _stringify(fields), where)
        _check_cells(_stringify(fields), where)
        before = copy.deepcopy(target)
        target.update(_stringify(fields))
        _fill_score(table, target)
        return Applied(table, op, key, before, copy.deepcopy(target), str(ch.get("reason", "")))

    raise WorkbookError(f"{where}: op는 add 또는 update여야 함 (받은 값: {op!r})")


def apply_changeset(
    changeset: dict,
    workbook_dir: Path = DEFAULT_DIR,
    dry_run: bool = True,
    now: datetime | None = None,
) -> Result:
    """변경안을 적용한다. dry_run=True(기본)면 파일을 건드리지 않고 결과만 돌려준다."""
    if not isinstance(changeset, dict) or not isinstance(changeset.get("changes"), list):
        raise WorkbookError("변경안에는 changes 배열이 필요")
    week = changeset.get("week")

    data = load_all(workbook_dir)  # 메모리 복사본에서만 적용한다
    result = Result(week=week, dry_run=dry_run)
    for idx, ch in enumerate(changeset["changes"]):
        result.applied.append(_apply_one(data, ch, idx))

    if dry_run:
        return result

    touched = sorted({a.table for a in result.applied})
    for t in touched:
        write_table(t, data[t], workbook_dir)
    _append_history(result, workbook_dir, now or datetime.now())
    return result


def load_changeset(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def parse_changeset(text: str) -> dict:
    """모델 출력에서 변경안 JSON을 꺼낸다. 앞뒤 설명이나 ``` 펜스가 붙어 있어도 첫 JSON 객체를 읽는다."""
    start = text.find("{")
    if start < 0:
        raise WorkbookError("출력에서 JSON 객체를 찾을 수 없음")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise WorkbookError(f"JSON 파싱 실패: {e}") from e
    if not isinstance(obj, dict):
        raise WorkbookError("변경안은 JSON 객체여야 함")
    return obj


# --------------------------------------------------------------------------- 변경 이력

def _append_history(result: Result, workbook_dir: Path, now: datetime) -> None:
    path = Path(workbook_dir) / HISTORY_FILE
    old = read_history(workbook_dir)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    for a in result.applied:
        old.append(
            {
                "applied_at": stamp,
                "week": "" if result.week is None else str(result.week),
                "table": a.table,
                "op": a.op,
                "key": a.key,
                "before": "" if a.before is None else json.dumps(a.before, ensure_ascii=False),
                "after": json.dumps(a.after, ensure_ascii=False),
                "reason": csv_safe(a.reason),
            }
        )
    _atomic_write(path, _to_csv_text(HISTORY_COLUMNS, old))


def read_history(workbook_dir: Path = DEFAULT_DIR) -> list[Row]:
    path = Path(workbook_dir) / HISTORY_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]
