"""실제 workbook/ (전)과 시연 복사본(후)을 비교해 바뀐 칸만 보여준다.  [-전-]{+후+}

    python scripts/show_changes.py                 # 기본: demo_run/workbook
    python scripts/show_changes.py 다른폴더         # 비교할 프로젝트 루트

쉘(PowerShell 5/7)에 의존하지 않도록 Python 으로 만들었다. 읽기 전용이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import workbook as wb  # noqa: E402

RED, GREEN, CYAN, DIM, RESET = "\033[31m", "\033[32m", "\033[36m", "\033[2m", "\033[0m"


def _fmt_change(old: str, new: str, color: bool) -> str:
    if color:
        return f"{RED}[-{old}-]{RESET}{GREEN}{{+{new}+}}{RESET}"
    return f"[-{old}-]{{+{new}+}}"


def compare(before_dir: Path, after_dir: Path, color: bool = False) -> list[str]:
    """테이블별로 추가·수정된 행을 사람이 읽기 쉽게 정리한다. 삭제는 없는 구조라 따로 다루지 않는다."""
    out: list[str] = []
    for table, spec in wb.TABLES.items():
        key = spec["key"]
        old = {r[key]: r for r in wb.read_table(table, before_dir)}
        new = wb.read_table(table, after_dir)
        lines = []
        for row in new:
            k = row[key]
            if k not in old:
                label = row.get("title") or row.get("milestone") or k
                extras = ", ".join(f"{c}={v}" for c, v in row.items() if c not in (key, "title", "milestone") and v != "")
                lines.append(f"  {GREEN if color else ''}+ 추가{RESET if color else ''} {k}  {label}" + (f"  ({extras})" if extras else ""))
            elif row != old[k]:
                cells = " | ".join(f"{c}: {_fmt_change(old[k][c], row[c], color)}" for c in row if row[c] != old[k][c])
                lines.append(f"  {k}  {cells}")
        if lines:
            out.append(f"{CYAN if color else ''}== {spec['file']}{RESET if color else ''}")
            out += lines
    return out


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "demo_run"
    target = target if target.is_absolute() else ROOT / target
    if not (target / "workbook").exists():
        print(f"비교할 폴더가 없음: {target / 'workbook'}", file=sys.stderr)
        return 2
    lines = compare(ROOT / "workbook", target / "workbook", color=sys.stdout.isatty())
    print("\n".join(lines) if lines else "차이 없음: 시연 복사본이 아직 승인되지 않았거나 실제 workbook/ 과 같은 상태입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
