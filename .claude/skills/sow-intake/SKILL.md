---
name: sow-intake
description: SOW와 시나리오 문서에서 범위·제외 범위·가정·인수 조건·단계별 산출물·모호한 점을 구조화하고, Handover 확인 항목과 초기 리스크 변경안(JSON)을 만든다. 사용자가 "SOW 분석", "Handover 체크리스트", "인수인계", "초기 리스크"를 말하면 쓴다.
---

# sow-intake — SOW에서 범위·가정·리스크 추출, Handover 확인 항목 (P0)

PM 표준 딜리버리 프로세스 P0(수주·인수인계)의 게이트 G0(Handover 완료)를 위한 입력을 만든다. 영업·프리세일즈가 넘긴 SOW를 딜리버리 팀이 정확히 넘겨받았는지 확인할 **질문 목록**과, SOW에서 보이는 **초기 리스크**를 뽑는다. 결과는 초안이며 PM이 승인하기 전에는 Workbook에 반영되지 않는다.

## 입력
1. SOW 요약 문서(번호가 붙은 항목)
2. 시나리오 문서(고객·목표·조직·거버넌스)
3. Workbook 현재값(milestones, risks 등). 이미 있는 것을 중복 등록하지 않기 위해 준다.

## 지켜야 할 규칙
- **입력에 없는 사실을 만들지 않는다.** 숫자·기간·담당자·고객 요구는 SOW와 시나리오에서만 가져온다. SOW가 말하지 않은 것은 사실로 쓰지 않고 `ambiguities`와 Handover 확인 항목으로 돌린다.
- 모든 Handover 확인 항목에는 `source`(근거)를 쓴다. 예: `SOW 2항`, `SOW 4항`, `시나리오 거버넌스`. SOW가 정하지 않아서 확인해야 하는 항목은 `SOW에 명시 없음(확인 필요)`라고 쓴다.
- 가상 데이터 프로젝트다. 실제 회사·인물·금액·장비 사양을 덧붙이지 않는다. 프로젝트명의 "(가상)" 표기를 남긴다.
- 사내 방법론 명칭은 쓰지 않는다. "PM 표준 딜리버리 프로세스"라고 쓴다.
- **출력은 JSON 객체 하나만** 낸다. 앞뒤 설명, 코드펜스(```), 주석을 붙이지 않는다.

## 출력 형식

```
{
  "extraction": {
    "scope_in": ["포함 범위 (시나리오·SOW 근거)"],
    "scope_out": ["제외 범위"],
    "assumptions": ["가정 (예: 고객이 N주 안에 무엇을 제공)"],
    "acceptance_criteria": ["인수 조건"],
    "phases": [{"phase": "P1", "weeks": 1, "deliverables": ["산출물"]}],
    "governance": ["보고·회의·리뷰 주기"],
    "review_and_change_rules": ["인도품목 검토 기한, 변경 관리 규칙"],
    "ambiguities": ["SOW가 정하지 않았거나 해석이 갈리는 점. 각각 한 문장으로"]
  },
  "handover_checklist": [
    {"item": "Handover 때 확인할 질문·항목", "source": "SOW 3항", "check_with": "영업·프리세일즈"}
  ],
  "changeset": {
    "week": 0,
    "changes": [
      {"table": "milestones", "op": "add", "row": {...}, "reason": "근거"},
      {"table": "risks", "op": "add", "row": {...}, "reason": "근거(SOW 항)"}
    ]
  },
  "notes": ["PM이 알아야 할 것"]
}
```

### extraction
- `phases`는 SOW의 단계·기간·산출물을 그대로 옮긴다. `weeks`는 숫자다. 기간이 없으면 `null`.
- `ambiguities`에는 수치·기준·책임이 정해지지 않은 곳을 찾아 쓴다. 예: 수치 일치의 허용 오차나 반올림 기준이 없음, 성능 목표 값이 SOW에 없음, 고객이 제공해야 할 환경의 범위가 불명확함. SOW 문구에서 실제로 보이는 것만 쓴다.

### handover_checklist
- 항목 수는 8~14개. 범위·제외 범위 확인, 가정이 고객과 합의되었는지, 인수 조건의 세부 기준, 검토 기한, 변경 관리, 거버넌스, 조직·역할, 고객 환경 정보 등을 다룬다.
- `check_with`는 정확히 `영업·프리세일즈`, `고객`, `내부(딜리버리)` 중 하나다.
- 서로 다른 질문을 쓴다. 같은 내용을 말만 바꿔 반복하지 않는다.

### changeset
- `week`는 0이다. `op`는 `add`만 쓴다.
- **마일스톤 M0 1건**: `{"id": "M0", "phase": "P0", "milestone": "Handover 완료(영업→딜리버리 인수인계)", "planned_week": "W0", "status": "Planned", "gate": "G0"}`. Workbook에 G0 마일스톤이 이미 있으면 추가하지 않는다.
  - **status는 반드시 `Planned`로 둔다.** Handover를 실제로 마쳤는지는 입력에 없다. 마쳤다면 PM이 승인하기 전에 `Done`으로 바꾼다. `notes`에 이 점을 적는다.
  - `notes`와 `reason`에는 "승인 전"이라는 표현을 쓰지 않는다(확정 문서에 낡은 표현으로 남는다). "승인하기 전" 또는 "승인 시"로 쓴다.
- **초기 리스크 0~4건**: SOW의 가정·제외 범위·인수 조건에서 **직접 근거가 보이는 것만** 등록한다. 형식: `{"title", "probability", "impact", "owner": "TBD", "mitigation", "status": "Open"}`. `id`와 `score`는 쓰지 않는다(자동). 값은 L, M, H 중 하나다.
  - 확률·영향은 AI 추정이다. `reason`에 SOW 항과 "추정"을 함께 쓴다.
  - Workbook에 이미 같은 내용의 리스크가 있으면 새로 만들지 않는다(의미로 비교). 같은지 확실하지 않으면 만들지 말고 `notes`에 쓴다.
- 허용 값 밖의 상태·우선순위는 시스템이 거부한다. 위 예시의 표기를 그대로 쓴다.

## 제출 전 점검
1. JSON 외의 글이 섞이지 않았는가. 문자열 안의 큰따옴표는 이스케이프했는가.
2. 모든 `handover_checklist` 항목에 `source`와 올바른 `check_with`가 있는가.
3. 입력에 없는 숫자·기간·담당자를 쓰지 않았는가.
4. M0의 status가 `Planned`인가. 리스크가 Workbook 기존 항목과 겹치지 않는가.
