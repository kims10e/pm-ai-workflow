# PLAN — PM AI Workflow (5일)

## 0일차 뼈대 (완료 2026-11-22)
- [x] CLAUDE.md, settings, .gitignore
- [x] docs: 통합 프로세스, 설계 개념도
- [x] 가상 시나리오·SOW·주간 메모(5~7주차), Workbook CSV 초기값

## 1일차 — P3 주간 루프 (명령줄, 6~8h)
- [x] 환경 점검: Python, git, `claude` CLI 로그인, python-docx 설치 (2026-11-22: Python 3.14.10, git 2.56.0, claude 2.1.183, python-docx 1.2.0)
- [x] `src/workbook.py`: CSV 읽기·쓰기, 변경안(diff) 적용 (테스트 13건 통과: `python -m unittest tests.test_workbook`)
- [x] 스킬 `status-report`: 주간 메모 + Workbook → 주간 보고서 초안(md→docx), RAG 상태, OKR 진척 (5주차 메모로 시험 호출 확인, `src/md_to_docx.py` 테스트 6건)
- [x] 스킬 `risk-update`: 메모에서 신규 리스크·이슈·액션·변경 추출 → JSON 변경안 (임시 Workbook 복사본에서 5→6→7주차 시험 통과, 허용 값 검증·변경 근거(reason) 이력 추가)
- [x] `src/pm_agent.py run --week 5`: 메모 읽기 → claude -p 호출 → 변경안·초안을 outputs/drafts에 저장 (가짜 LLM 테스트 11건 + 실제 호출 확인, Workbook 불변 확인)
- [x] `src/pm_agent.py approve --week 5`: 승인 시 Workbook 반영, 보고서 outputs/final로 확정, 변경 이력 기록 (테스트 26건 추가, 연습 복사본에서 실제 5주차 초안으로 확인. 실제 workbook/은 승인 전 상태 유지)
- [x] 5→6→7주차 순서로 실행해 Workbook이 누적 갱신되는지 확인 (연습 복사본에서 정식 run→approve로 확인: 이력 9+15+6=30건 모두 근거 포함, KR1 8·KR2 3.1·M3 Done·C-001 Approved. `run` 1회 약 4.5분. 이후 실제 workbook/에도 5·6·7주차 승인 반영 완료: 이력 8+14+7=29건)

## 2일차 — 연동·확장
- [x] 텔레그램 입력·승인 요청(전용 봇, .env 토큰) — 실제 텔레그램으로 메모 입력→초안→승인 버튼까지 연습 복사본에서 확인
  - [x] 봇 연결·본인 확인(`src/telegram_io.py`: check·setup·ping, 일회용 코드로 chat id 등록)
  - [x] 승인 요청(`src/approval_flow.py`: `run --notify`·`request`, [승인][반려] 버튼, 테스트 15건)
  - [x] 메모 입력(`src/memo_listener.py`: `listen --once`, `/memo 주차` → `data/updates/weekNN.md`, 테스트 18건)
- [x] Quality Gate: 4대 체크 이벤트·누락 점검(예: Kickoff 전 범위 합의 여부, 마일스톤 리뷰 누락) — `src/quality_gate.py`, `pm_agent quality --week N [--notify]`, 규칙 기반 11개 점검(체크 이벤트 4 + 정기 7), 테스트 20건. 실제 Workbook 7주차 기준: FAIL 0·WARN 3·UNKNOWN 1
- [x] P0→P1: 가상 SOW → Handover 체크리스트·Charter·OKR 초안(sow-intake, charter-okr) — `src/intake.py`, `pm_agent intake [--notify]`, 문서 3종(md·docx)+M0·초기 리스크 변경안, 테스트 21건. 실제 SOW로 초안 생성 확인(Handover 항목 13개·모호한 점 5건). 실제 Workbook 승인(`approve --week 0`)은 PM 판단 대기

## 3일차 — 시연 자료
- [ ] 2~3분 시연 영상(5→7주차 루프, 승인 흐름)
- [x] README: 문제·설계·실행 방법·결과물 샘플·한계 — `README.md`, `requirements.txt`, `docs/samples/`(확정본 샘플 7개)
- [ ] 이력서·포트폴리오용 한 줄 요약

## 4~5일차 — 여유·보완
