# PM AI Workflow — 프로젝트 규칙

## 목적
PM 표준 딜리버리 프로세스(P0~P5)를 AI 에이전트로 자동화한 포트폴리오. 기준 문서는 `docs/PM_Delivery_Process_Integrated.md`, 설계 개념도는 `docs/diagrams/`(시안 A·B·C, 생성기 `gen_diagrams.py`), 초기안은 `docs/PM_AI_Workflow_Concept_v0.1.html`.
공개 표기: "personal project, built outside the work network".

## 절대 규칙
- 가상 데이터만 사용한다. 실제 고객·기관·회사 정보, 실제 금액·장비 사양을 넣지 않는다.
- `C:\01.Career_Mgmt`, `C:\00.AI Agent` 등 이 폴더 밖의 파일은 읽거나 쓰지 않는다. 필요한 코드는 복사해서 이 폴더 안에서 고친다.
- 이력서에 넣을 문구가 생기면 `outputs/resume_notes.md`(Git 제외)에 문구 후보와 근거(기능, 테스트 결과, 측정값)를 적는다. 커리어 폴더에 직접 쓰거나 커밋되는 위치(docs, README)에 적지 않는다. 반영이 끝나면 해당 항목에 "반영 완료(날짜)"를 표시한다.
- 사내 방법론 명칭을 쓰지 않는다. "PM 표준 딜리버리 프로세스"로 쓴다.
- 비밀값(텔레그램 토큰 등)은 `.env`에만 두고 코드·로그·커밋에 넣지 않는다.
- AI가 만든 Workbook 변경과 보고서는 사람이 승인하기 전에는 확정하지 않는다(Human-in-the-loop).

## 구조
- `data/` 가상 시나리오, 가상 SOW, 주간 업데이트 메모(입력)
- `workbook/` Project Workbook CSV(단일 기준 데이터): actions, risks, issues, changes, okr, milestones
- `src/` 오케스트레이터와 도구 코드(Python)
- `.claude/skills/` 단계별 PM 스킬(status-report, risk-update, sow-intake, charter-okr 등)
- `outputs/drafts/` 승인 전 초안, `outputs/final/` 승인된 확정본
- `PLAN.md` 일자별 작업 목록. 작업을 끝내면 체크한다.

## 작업 방식
- 한 번에 한 흐름씩 만들고, 가상 데이터로 실행해 결과를 확인한 뒤 다음으로 넘어간다.
- Workbook CSV는 UTF-8(BOM 없음)로 읽고 쓴다. 윈도우 경로·한글 처리를 확인한다.
- 산출물 문서는 한국어 기본, 필요 시 영문 병기.
