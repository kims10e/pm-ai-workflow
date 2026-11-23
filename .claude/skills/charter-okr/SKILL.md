---
name: charter-okr
description: sow-intake 결과와 시나리오·Workbook을 바탕으로 Project Charter 내용과 공동 OKR 표(목표·핵심 결과·성공 지표·의존성·목표 일정·우선순위)를 JSON으로 만든다. 사용자가 "Charter", "프로젝트 헌장", "공동 OKR", "OKR 표"를 말하면 쓴다.
---

# charter-okr — Charter·공동 OKR 표 초안 (P1)

PM 표준 딜리버리 프로세스 P1(착수)의 산출물인 Charter와 공동 OKR 표의 **내용**을 만든다. 문서 형식(제목·표)은 시스템이 정해진 양식으로 만들므로, 여기서는 내용만 JSON으로 낸다. 결과는 초안이며 PM이 승인하고 고객과 합의(G1)해야 확정된다.

## 입력
1. `sow-intake`의 extraction(범위·가정·인수 조건·단계·모호한 점)
2. 시나리오 문서(고객·목표·조직·기간·거버넌스)
3. Workbook 현재값: okr, milestones, risks. **OKR의 단일 기준은 Workbook의 okr이다.**

## 지켜야 할 규칙
- **입력에 없는 사실을 만들지 않는다.** 숫자·날짜·담당자·책임은 입력에서만 가져온다. 모르면 `확인 필요`라고 쓴다.
- **공동 OKR 표의 핵심 결과(`key_result`)는 Workbook okr의 `key_result` 문구를 한 글자도 바꾸지 않고 그대로 쓴다.** 행의 수도 같아야 한다(새 KR을 만들거나 빼지 않는다). `priority`도 Workbook 값 그대로다. 정합성이 맞지 않으면 시스템이 거부한다.
- 가상 데이터 프로젝트다. 실제 회사·인물·금액·장비 사양을 덧붙이지 않는다. 프로젝트명의 "(가상)" 표기를 남긴다.
- 사내 방법론 명칭은 쓰지 않는다. "PM 표준 딜리버리 프로세스"라고 쓴다.
- **출력은 JSON 객체 하나만** 낸다. 앞뒤 설명, 코드펜스(```), 주석을 붙이지 않는다.

## 출력 형식

```
{
  "charter": {
    "purpose": "프로젝트 목적 한두 문장",
    "background": "배경 한두 문장(시나리오 근거)",
    "objectives": ["목표"],
    "scope_in": ["포함 범위"],
    "scope_out": ["제외 범위"],
    "success_criteria": ["성공 기준(인수 조건·OKR과 일치)"],
    "assumptions": ["가정"],
    "constraints": ["제약(기간, 변경 불가 조건 등)"],
    "roles": [{"role": "고객 PM", "responsibility": "역할 설명 또는 확인 필요"}],
    "governance": ["보고·회의·리뷰 주기"],
    "milestones": [{"id": "M1", "name": "마일스톤 이름", "week": "W1", "gate": "G1"}],
    "approvals": ["합의·서명이 필요한 주체"]
  },
  "okr": [
    {
      "objective": "O1 ...",
      "key_result": "Workbook의 key_result 그대로",
      "success_metric": "측정 방법과 목표값",
      "dependency": "선행 조건·의존성",
      "target_date": "목표 시점",
      "priority": "P0"
    }
  ],
  "notes": ["PM이 알아야 할 것"]
}
```

### charter
- `scope_in`, `scope_out`, `assumptions`는 extraction의 내용과 모순되지 않게 쓴다.
- `roles`는 시나리오의 조직 정보에서 가져온다. 책임이 입력에 없으면 `확인 필요`.
- `milestones`는 Workbook의 milestones를 그대로 옮긴다(id, 이름, 계획 주차, 게이트).
- `approvals`는 합의·서명이 필요한 주체를 입력(시나리오의 조직·거버넌스)에서 고른다.

### okr
- `success_metric`, `target_date`는 Workbook의 target·unit과 milestones에서 근거를 찾아 쓴다. 예: KR의 target이 40이고 unit이 종이면 "40종 전환 완료". 날짜는 해당하는 마일스톤의 계획 주차를 인용한다. 근거가 없으면 `확인 필요`.
- `dependency`는 SOW 가정이나 extraction에서 직접 이어지는 것만 쓴다. 없으면 `없음`.
- `priority`는 `P0`, `P1`, `P2` 중 Workbook 값 그대로다.

## 제출 전 점검
1. JSON 외의 글이 섞이지 않았는가.
2. okr의 `key_result`와 `priority`가 Workbook okr과 정확히 같은가. 행 수가 같은가.
3. 입력에 없는 숫자·날짜·담당자를 쓰지 않았는가.
4. charter의 필수 항목(purpose, background, objectives, scope_in, scope_out, success_criteria, assumptions, governance, milestones, roles, approvals)이 모두 비어 있지 않은가.
