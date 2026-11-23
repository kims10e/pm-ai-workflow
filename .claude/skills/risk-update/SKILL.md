---
name: risk-update
description: 주간 업데이트 메모와 Project Workbook 현재값을 비교해 신규 리스크·이슈·액션·변경 요청과 기존 항목의 상태 변경, OKR 현재값을 뽑아 JSON 변경안으로 만든다. 사용자가 "리스크 갱신", "변경안", "Workbook 업데이트", "메모에서 리스크 추출"을 말하면 쓴다.
---

# risk-update — 주간 메모에서 Workbook 변경안 추출 (P3)

주간 메모를 읽고 Workbook에 무엇이 바뀌어야 하는지를 **JSON 변경안**으로 만든다. 변경안은 PM이 승인하기 전에는 Workbook에 반영되지 않는다. 그러므로 확실하지 않은 것은 넣지 말고 `notes`에 적어 PM이 판단하게 한다.

## 입력
1. 주간 업데이트 메모(몇 주차인지 포함)
2. Workbook 현재값: actions, risks, issues, changes, milestones, okr

## 출력
**JSON 객체 하나만** 낸다. 앞뒤 설명, 코드펜스(```), 주석을 붙이지 않는다.

```
{
  "week": 5,
  "changes": [
    {"table": "risks", "op": "add", "row": {...}, "reason": "근거가 된 메모 문장"},
    {"table": "actions", "op": "update", "key": "A-002", "fields": {...}, "reason": "..."}
  ],
  "notes": ["변경안에 넣지 않았지만 PM이 알아야 할 것"]
}
```

- `op`는 `add`(신규)와 `update`(기존 항목 수정) 두 가지뿐이다. **삭제는 없다.** 끝난 것은 상태를 바꾼다.
- 모든 변경에 `reason`을 쓴다. 메모의 문장을 그대로 또는 짧게 인용한다. 메모에 근거가 없으면 그 변경은 만들지 않는다.
- `update`의 `key`는 Workbook에 있는 값을 **정확히** 복사한다. 테이블별 기본키는 아래와 같다.
- 바뀌는 필드만 `fields`에 쓴다. 기본키는 바꾸지 않는다.
- 변경이 없으면 `"changes": []`로 두고 이유를 `notes`에 쓴다.

## 테이블별 규칙

| 테이블 | 기본키 | 허용 값 |
|---|---|---|
| actions | id | status: Open, In Progress, Done, Cancelled |
| risks | id | probability·impact: L, M, H / status: Open, Mitigating, Occurred, Closed |
| issues | id | priority: High, Medium, Low / status: Open, In Progress, Resolved, Closed |
| changes | id | status: Requested, Approved, Rejected, Implemented |
| milestones | id | status: Planned, In Progress, Done, Delayed |
| okr | key_result | `current`만 수정 가능(추가 불가) |

허용 값 밖의 값(한글 "완료", 소문자 "done" 등)은 시스템이 거부한다. 정확히 위 표기를 쓴다.

- **신규(`add`)**: `id`는 쓰지 않는다(자동 부여). 리스크의 `score`도 쓰지 않는다(확률×영향으로 자동 계산).
- 날짜·주차 형식은 같은 테이블의 기존 행을 따른다(예: actions의 `due`는 `2026-W06`).
- 메모에 없는 담당자는 지어내지 않고 `owner`를 `TBD`로 쓴다.
- 이미 Workbook에 있는 것과 같은 내용을 새로 만들지 않는다(중복 금지). 먼저 기존 항목과 같은 것인지 의미로 비교한다. 같은 항목인지 **확실하지 않으면** 새로 만들지 말고 `notes`에 적는다.

## 구분 기준

**리스크 vs 이슈**
- 리스크 = 아직 일어나지 않은 불확실한 일. `probability`와 `impact`를 L/M/H로 추정한다.
  - 확률: H 곧 일어날 징후가 있음, M 가능성이 있음, L 낮음
  - 영향: H 마일스톤·핵심 KR에 직접 영향, M 일부 지연·공수 증가, L 미미
- 이슈 = 이미 일어나서 대응이 필요한 일.
- **리스크가 현실화되면**: 그 리스크의 status를 `Occurred`로 바꾸고, 이슈를 새로 등록한다(제목에 `R-xxx` 병기). 이슈가 해결되면 이슈를 `Resolved`로 하고 `resolution`을 쓰며, 연결된 리스크는 `Closed`로 한다.
- 신규 리스크의 확률·영향은 AI의 추정이다. `reason`에 "추정"이라고 밝힌다.

**액션**: 누가 무엇을 해야 하는지가 메모에 나온 것. 기존 액션이 끝났으면 `Done`, 진행 중이면 `In Progress`로 바꾼다. 기한이 지난 `Open` 액션은 `notes`에 알린다.

**변경 요청(changes)**: 메모에 **Change Request로 접수·승인·기각된 것**만 넣는다. "범위 밖일 수 있다"는 단계는 변경 요청이 아니라 `notes`와 액션(범위 판단)으로 다룬다. 메모가 "CR-01" 같은 별칭을 쓰면 제목에 그대로 병기한다(예: `CR-01 리포트 필터 기본값 변경`). 다음 주 메모가 그 별칭으로 부를 때 기존 항목을 찾기 위해서다. 영향(`impact_scope`, `impact_schedule`, `impact_cost`)은 메모에 있는 것만 쓴다.

**마일스톤**: 메모가 완료·지연을 분명히 말할 때만 상태를 바꾼다. 지연 "가능성"만 있으면 `Delayed`로 바꾸지 않고 `notes`에 쓴다.

**OKR(`current`)**
- **완료된 것만** 센다. "진척 25%", "착수", "진행 중"은 완료가 아니므로 KR 값에 넣지 않는다.
- KR 문구와 연결되는 실측값이 메모에 있을 때만 갱신한다(예: 전환 완료 리포트 수, 측정한 배치 시간).
- 전환 리포트 수(KR1)는 누적 완료 수다. 이번 주 새로 끝난 수가 아니라 지금까지 합계를 쓴다. 합계를 계산할 수 없으면 갱신하지 말고 `notes`에 쓴다.
- 한 번 갱신한 값이 메모와 다르게 보이면(예: 이전 값이 이미 높음) 메모를 우선하되 `notes`에 알린다.

## 쓰지 말아야 할 것
- 메모에 없는 사실(숫자, 날짜, 담당자, 원인)
- 실제 회사·인물·금액·장비 사양. 가상 데이터만 쓴다.
- 사내 방법론 명칭. "PM 표준 딜리버리 프로세스"라고 쓴다.

## 제출 전 점검
1. JSON 외의 글이 섞이지 않았는가. 문자열 안의 큰따옴표는 이스케이프했는가.
2. 모든 `update`의 `key`가 입력 Workbook에 실제로 있는가.
3. 모든 status·priority·probability·impact가 허용 값인가.
4. 같은 내용을 중복 등록하지 않았는가.
5. 모든 변경에 메모 근거(`reason`)가 있는가.
