# T138~T156 기준선 감사 (STEP 00)

> 실행: SORNET(Claude Code) · 코디네이터: GPT-Web · PM: 문길래 · 2026-11-11
> 범위: T138~T156 중 T147 제외 18개. T147은 T148의 선행 조건으로만 확인했습니다.
> 이 문서는 **작업 시작 시점**의 상태입니다. 최종 결과는 `T138_T156_INTEGRATED_EXECUTION_REPORT.md` 에 있습니다.

## 1. 기준

| 항목 | 값 |
|---|---|
| BASE_MAIN_SHA | `822fa16660afdaa5ad099f059b244216332becf1` (T120 #227 병합) |
| 직전 실행(T111~T130) | PR 20개(#207~#222, #224~#227) **모두 병합됨** |
| main CI | CI·Backend tests·T49 upload E2E·Crawler MVP 모두 success. Frontend CI 는 843cac9 에서 success |
| 로컬 기준 회귀(Windows) | Backend 1640 passed, 101 skipped, **1 failed + 31 errors**. 모두 `test_documents.py`·`test_security_upload.py` 의 `DOCUMENT_STORAGE_ROOT must have mode 0700`(Windows POSIX 권한). Linux CI 는 통과 |
| 크롤러 오프라인(Windows) | 401 OK, skipped 3 |
| gh 인증 | GilbertMoon, 저장소 쓰기 가능 |
| 보호 | 주 작업 폴더의 `outputs/`(미추적)와 기존 worktree 는 건드리지 않음. 작업은 새 worktree 에서만 진행 |

## 2. 열린 PR 중 이번 범위와 관련된 것

| PR | 작성자 | 내용 | 이번 범위 영향 |
|---|---|---|---|
| **#154** | kyeju(김예주) | T138 코드 정제 파이프라인 mock(실제 0001 스키마·T10 seed) | **T138 그 자체**. 새 PR 을 만들지 않고 검토만 |
| #129 | apll970502 | T83/T71/T137/T147 리뷰 수정 | T137 mock 변경. T138 시험을 이 mock 으로도 확인 |
| #178 | GilbertMoon | Staging migration 기준선 | T150 F4(P0) 근거 |
| 그 외(#223, #183, #176, #175, #173, #169, #167, #162, #160, #151, #149, #12) | 다른 담당자 | 범위 밖 | 건드리지 않음 |

## 3. 일감별 기존 구현·담당·선행·필요 범위

| Task | 기존 구현·PR | 담당 | 선행 상태 | 변경 필요 범위 | 실제 시험 가능 | 신규 PR |
|---|---|---|---|---|---|---|
| T138 | **#154 OPEN** (CI 6개 success, Crasnec COMMENTED) | **김예주** | T10 병합, T137 병합(#129 수정 중) | 없음(담당자 PR) | 격리 PG | **아니오** — 검토만 |
| T139 | T17 `/skills` 이름 검색(#117) | 미배정 | T17·T98·T137 병합, **T138 #154 OPEN** | 동의어·표준 코드 자동완성 API(플래그) | 격리 PG(실제 스키마). 동의어 표는 없음 | 예 |
| T140 | T34 기술 화면(#146, combobox 있음). **#33 CLOSED·미병합**(PoC, 브랜치 남음) | **조영우** | T20·T23·T34 병합, T139 없음 | T34 화면에 T139 연결(플래그) | Mock + 로컬 실제 API | 예(담당자 보완 제안, #33 브랜치 미변경) |
| T141 | T31 동의·탈퇴 API(#139), T83 감사 계약, T128 정책 | 미배정 | 병합 | 정책 문서·JSON(PROPOSED) | 문서·JSON 시험 | 예 |
| T142 | T31 탈퇴 요청 | 미배정 | T49 병합, T141 없음 | 반출 요청 API(플래그, 저장소 없음) | 메모리 + 제안 DDL 격리 PG | 예 |
| T143 | T32 개인정보 설정 UI | 미배정 | T142 없음 | Mock UI(플래그) | Mock | 예 |
| T144 | T49 문서 API(#159) | 미배정 | T49·T111 병합, **T53 NOT_STARTED**, T141 없음 | 저장소 보안 회귀·키 관리 계약 | 로컬 | 예 |
| T145 | T64 실행 상태·claim, T96 outbox, T112 request_id | 미배정 | T64·T96·T112 병합, **T110 NOT_STARTED** | 공통 작업 계약·라이브러리 | 메모리 + 격리 PG | 예 |
| T146 | T89 a11y 회귀(#191), T92 여정(#194) | 미배정 | 병합 | 날짜·숫자 표준, 접근성 | Vitest + Chrome | 예 |
| T148 | T123·T126·T129(플래그·메모리), T86 보안 PG 도구 | 미배정 | T123·T126·T129·T147 병합, T141 없음 | 다중 역할 E2E 시험 | 라우터 + 메모리, 격리 PG | 예 |
| T149 | T114 백업, T119 점검표, T112 지표 | 미배정 | T112·T114·T119 병합, **T110 NOT_STARTED** | 용량·비용·복구 계획 | 격리 PG 실측 | 예 |
| T150 | T120 Gate(NO_GO) | 미배정 | **T136 NOT_STARTED**, T143·T144·T148·T149 없음 | 최종 Gate(마지막) | 문서·판정 시험 | 예(통합 보고서 포함) |
| T151 | #90~#97 병합(keyword CRUD·감사·job 메타데이터, migration 0003·0004) | **문길래** | 병합 | 없음 | — | **아니오**(완료) |
| T152 | #98~#100 병합(원본 저장·해시·크기·형식) | **문길래** | 병합 | **고아 파일 탐지·보존 기한 없음**(T152.md 2-4) | 격리 PG | 예(누락분만) |
| T153 | #101~#103, #118 Fixture 최종 QA PASS | **문길래** | 병합 | 없음 | — | **아니오**(완료, Live HOLD) |
| T154 | #104~#115 병합(증분·checkpoint·재시도·야간 창) | **문길래** | 병합 | 없음 | — | **아니오**(Fixture 범위 완료, Live HOLD) |
| T155 | #119·#120·#124 병합(관리자 **읽기** API 6개, T15 인증) | **문길래** | T15 병합 | **쓰기 API**(검색어 CRUD·설정·명령) 없음 | 격리 PG | 예(누락분만) |
| T156 | 기획 문서만 | **문길래** | T155 쓰기 없음 | 관리자 UI | Mock + 로컬 실제 API | 예 |

## 4. 범위 밖 선행 일감 확인

| 일감 | 상태 | 영향 |
|---|---|---|
| T110 (LLM 비동기) | NOT_STARTED | T145 의 LLM 작업 유형은 계약만, T149 AI 비용은 추정 |
| T136 (학습 진도) | NOT_STARTED | T150 선행 미충족 |
| T137 (코드 정책) | 병합(#37), 리뷰 수정 #129 OPEN | 별칭 표 migration 없음 → T139 실제 DB 동의어 HOLD |
| T147 (합성 데이터 공장) | 병합(#38) | T148 선행 충족 |
| T53 (RAG 색인) | NOT_STARTED | T144 파생물 보안 확인 불가 |
| T104~T109 | NOT_STARTED | T150 범위 밖으로 기록 |

## 5. 공통 설계 문서 대조

`docs/FULL_SCOPE_TRACEABILITY.md`, `docs/API_CONTRACT.md`, `database/FULL_DATABASE_MODEL.md` 에 T138~T150 확장 기능은 **확정 계약으로 들어 있지 않습니다**(작업지시서 모두 "PROPOSED / NOT_STARTED"). 그래서 새 API 는 모두 기본 꺼짐 플래그 뒤에 두었고, `openapi.yaml` 은 바꾸지 않았으며, 새 표는 `database/proposed/` 제안 DDL 로만 냈습니다.

## 6. 실행 환경 결정

- 일회용 PostgreSQL 18.6
  - 공용 클러스터(loopback): T86 `disposable_pg` 가 DB 하나(`t16_profile_test`)의 스키마를 지웠다 다시 만들기 때문에, 병렬 작업은 **mkdir 잠금**으로 차례대로 실행했습니다.
  - T138·크롤러 검증용 별도 클러스터: 전역 역할을 만들기 때문에 공용 클러스터와 분리했습니다.
- Frontend 는 같은 `package.json` 의 공용 `node_modules` 를 junction 으로 공유했습니다.
- 독립 일감 묶음(T141→T142→T143, T144+T145, T146+T149, T155→T156)은 병렬로 진행했습니다. 각 묶음은 별도 worktree·브랜치·DB 이름을 썼습니다.
