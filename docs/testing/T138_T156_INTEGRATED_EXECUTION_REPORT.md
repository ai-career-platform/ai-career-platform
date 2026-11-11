# T138~T156 통합 실행 보고서 (T147 제외 18개)

> 실행: SORNET(Claude Code) · 코디네이터: GPT-Web · PM: 문길래 · 2026-11-11
> - 기준 main: `822fa16`. 실행 중 main 은 바뀌지 않았습니다(최종 main 도 `822fa16`).
> - **PR 생성·검증까지만** 했습니다. 병합 0건이고 Staging·운영·공유 DB·Secret 변경도 0건입니다.
> - STEP 00 기준선은 `T138_T156_BASELINE_AUDIT.md` 에 있습니다.

## 1. 18개 일감 현황

| Task | 결과 | PR | 브랜치(base) | HEAD | CI(최신 HEAD) | 비고 |
|---|---|---|---|---|---|---|
| T138 | **담당자 PR 재사용** | #154 (kyeju) | `task/t138-code-cleanup-pipeline` | `57b69f2` | success 6 | 새 PR 없음. 로컬 재검증 49 PASS(HEAD·main 병합·#129 mock), PR 댓글 |
| T139 | 신규 | **#238** | `task/t139-skill-autocomplete-api` (main) | `dc69ed5` | success 8 | 플래그 꺼짐. 실제 DB 동의어 HOLD |
| T140 | 신규(담당자 보완 제안) | **#239** | `task/t140-skill-autocomplete-ui` (**#238 위 스택**) | `d53fa1f` | success(PR 자동 1 + 수동 실행 Frontend CI·CI) | 담당 조영우. #33 은 닫힘·브랜치 미변경 |
| T141 | 신규(PROPOSED) | **#230** | `task/t141-data-access-policy` (main) | `edb5002` | success 5 | 정책 문서·JSON |
| T142 | 신규 | **#235** | `task/t142-personal-data-request-api` (main, #230 커밋 포함) | `353090f` | success 8 | 플래그 꺼짐, 저장소 없음 |
| T143 | 신규(Mock) | **#237** | `task/t143-personal-data-request-ui` (main, #230·#235 커밋 포함) | `000c28a` | success 9 | Mock 전용 |
| T144 | 신규 | **#232** | `task/t144-document-storage-security` (main) | `7caf37c` | success 5 | **평문 저장 F-1(High)** 기록 |
| T145 | 신규 | **#234** | `task/t145-background-job-contract` (main) | `b485262` | success 8 | 제안 DDL, Worker 꺼짐 |
| T146 | 신규 | **#231** | `task/t146-i18n-accessibility` (main) | `9ea8926` | success 4 | 날짜 시간대 버그 4곳 수정 |
| T148 | 신규 | **#241** | `task/t148-multi-role-security-e2e` (main) | `102c13d` | success 5 | 필수 10개 시나리오 + **F-2 수정** |
| T149 | 신규 | **#236** | `task/t149-cost-capacity-plan` (main) | `2d5aa14` | success 5 | 실측·추정 분리 |
| T150 | 신규 | **#243** | `task/t150-expansion-release-gate` (main) | (댓글) | (댓글) | **NO_GO**, 통합 보고서 포함 |
| T151 | **이미 구현** | #90~#97 병합 | — | — | main success | 변경 없음 |
| T152 | 이미 구현 + **누락분 보완** | 기존 #98~#100, 신규 **#242** | `task/t152-raw-artifact-audit` (main) | `fb38c84` | success 3(Crawler PG 시험 포함) | 고아 파일 탐지·보존 검토, 삭제 없음 |
| T153 | **이미 구현** | #101~#103, #118(Fixture QA PASS) | — | — | main success | Live HOLD |
| T154 | **이미 구현** | #104~#115 병합 | — | — | main success | Fixture 범위 완료, Live HOLD |
| T155 | 기존 읽기 API + **쓰기 API 보완** | 기존 #119·#120·#124, 신규 **#233** | `task/t155-crawler-admin-write-api` (main) | `a92b916` | success 5 | 플래그 꺼짐, 크롤러 migration 0011(PR) |
| T156 | 신규 | **#240** | `task/t156-crawler-admin-ui` (**#233 위 스택**) | `645eb7b` | success(PR 자동 1 + 수동 실행 Frontend CI·CI) | 플래그 꺼짐 |

- **이미 구현(신규 PR 없음)**: T151, T153, T154
- **담당자 PR 재사용**: T138(#154)
- **누락분만 보완**: T152(#242), T155(#233)
- **신규 PR**: 14개(#230~#243)

## 2. 테스트 결과 (실행한 것만)

| 영역 | 결과 | 구분 |
|---|---|---|
| Backend 일감별 | T139 37 · T141 16 · T142 25(+제안 DDL PG 5) · T144 42(+1 Windows skip) · T145 35 · T148 14 · T149 21 · T150 5 | 로컬 |
| Backend 전체(Windows) | T139 1676 · T142 1686 · T144 1682 · T145 1675 · T148 1654 passed. 모두 기존 Windows 0700 실패 1 failed + 31 errors(main 과 같음) | 로컬 |
| Backend 전체(Linux CI) | 모든 PR 의 Backend pytest·Backend tests success | CI |
| Frontend | T140 527 · T143 532 · T146 544 · T156 534 passed(각 22 skipped, 새 skip 없음). lint·tsc·build 통과 | 로컬 + CI |
| PostgreSQL | T139(실제 스키마·최소 권한) · T142 제안 DDL · T145 SKIP LOCKED 경쟁 · T148 역할·세션 회수·IDOR · T149 실측·복원 3회 · T152 READ ONLY 대조 · T155 0011 쓰기 · T138 재검증 49 | 로컬 일회용 PG 18.6, 크롤러는 CI 서비스도 |
| 브라우저(헤드리스 Chrome) | T140 Mock 12/12 · 로컬 실제 API 14/14 / T143 데스크톱·모바일(Mock) / T146 30/30(Mock, 320·1280px) / T156 Mock + 로컬 실제 API(원본 저장→파싱→조회) | 로컬 |
| 크롤러 | T152 오프라인 411 OK(CI 도 411) + PG 2 / T155 407 OK + CI DB 6 | 로컬 + CI |
| Staging | **NOT_RUN** (모든 일감) | — |

Mock PASS 를 실제 API PASS 로 보고하지 않았습니다.
- 실제 API 검증은 **로컬 격리 환경**에서만 했습니다: T139, T140, T156
- Mock 만 있는 것: T143, T146

## 3. CI 상태

최신 HEAD 기준입니다(T150 제외).
- **success**: 13개(#230~#242)
- **failure**: 0
- **pending**: 0

스택 PR(#239·#240)은 main 대상 워크플로가 자동으로 돌지 않아 같은 HEAD 에서 `workflow_dispatch` 로 실행했습니다. 각 PR 에 CI 결과 댓글을 남겼습니다.

## 4. 발견 사항·수정

| ID | 일감 | 내용 | 조치 |
|---|---|---|---|
| T144 F-1 | 문서 저장소 | **문서가 디스크에 평문 저장**(High) | 시험으로 고정, 암호화 계약만(미연결). T150 F6 FAIL |
| T148 F-1 | 기업 관리자 경로 | 서비스 안 역할 확인 → 형식 오류 본문이면 비관리자에게 422 (Low) | 기록, 결정 필요 |
| T148 F-2 | T126 결정·내림 | 공고 존재 여부를 역할보다 먼저 확인 → id 존재 여부 노출 (Low) | **수정**(#241) |
| T146 | 날짜 표시 | 시간대 미지정 4곳(문서 등록일 등) → 접속 PC 시간대에 따라 날짜가 달라짐 | **수정**(#231) |
| T139 | 동의어 | 실제 DB 에 T137 별칭 표 없음 → 실제 동의어 변환 불가 | HOLD(시험으로 빈 결과 고정) |
| T143 | 실제 API | 공용 `HttpClient` 가 요청별 헤더를 못 보냄 → 재인증 토큰 전달 불가 | Mock 전용. T156(#240)이 `http.ts` 에 요청별 헤더를 추가했으므로 병합 후 연결 가능 |

## 5. 미완료 선행조건

T110, T136, T53, T104~T109 는 NOT_STARTED 입니다. T137 별칭 표 migration 은 승인되지 않았습니다. T138 #154 는 미병합입니다. T120 의 P0(E5·E6)는 미해결입니다.

## 6. 신규 DB Migration 필요 여부

| 필요 | 위치 | 상태 |
|---|---|---|
| T139 skills 부분 인덱스 | `database/proposed/T139_skill_suggest_index.sql` | 제안(현재 불필요) |
| T142 개인정보 요청 표 | `database/proposed/T142_personal_data_requests.sql` | 제안 |
| T145 작업 표 | `database/proposed/T145_background_jobs.sql` | 제안 |
| T155 관리자 명령 원장 | `crawler/storage/migrations/0011_admin_commands.sql` | **PR(#233)**, Staging 미적용 |
| T137 별칭·상태 표 | (T137·T138 결정) | 미승인 |

앱 DB(`database/migrations/`)의 정식 migration 추가는 0건입니다.

## 7. 실제 운영 변경 여부

```text
STAGING_CHANGED=NO
PRODUCTION_CHANGED=NO
SHARED_DB_CHANGED=NO
SECRETS_ROTATED=NO
UNAPPROVED_FEATURES_ENABLED=NO   (새 서버·화면 플래그 6개 모두 기본 false)
TIMERS_OR_WORKERS_ENABLED=NO
LIVE_COLLECTION=HOLD
```

## 8. 권장 병합 순서

공유 파일 충돌을 줄이는 순서입니다. 아래 설정 파일들은 PR 마다 한 줄씩 추가하는 수준이라 충돌이 나더라도 단순합니다.
- Backend 설정: `config.py`, `main.py`, `env_contract.py`, `.env.example`, `ENVIRONMENT_MATRIX.md` — #235·#238·#233 이 수정
- Frontend 설정: `env.ts`, `routes.tsx`, `AppLayout.tsx` — #237·#239·#240 이 수정

| 단계 | PR | 비고 |
|---|---|---|
| 1. 문서·시험 위주(독립) | #230(T141) → #231(T146) → #232(T144) → #234(T145) → #236(T149) | |
| 2. 권한 회귀 | #241(T148) | T126 서비스를 수정하므로 T126 관련 PR 과 충돌 확인 |
| 3. 개인정보 체인 | #235(T142) → #237(T143) | |
| 4. 기술 코드 체인 | **#154(T138, 담당자)** → #238(T139) → #239(T140, base 를 main 으로 바꾼 뒤 CI 재확인, 담당자 확인) | |
| 5. 크롤러 | #242(T152) → #233(T155) → #240(T156, base 를 main 으로 바꾼 뒤 CI 재확인) | #242·#233 은 워크플로의 다른 줄을 수정 |
| 6. 최종 | #243(T150) | 병합 후 Gate 재판정은 PM 승인 사항 |

## 9. 잔여 Blocker (PM·담당자 결정)

1. **릴리스 NO_GO(T150)**: P0 F4·F5·F6·F11 FAIL, F2·F7·F9 PARTIAL, T136 미착수
2. T137 별칭 표 migration (T138·T139 공통)
3. T141 정책 6개 결정, T142 저장소·Worker·암호화 저장소 연결
4. T144: AES-256-GCM 의존성·키 보관 위치·평문 문서 이행
5. T145 제안 표 승인 여부, dead-letter 보존
6. T146 영어 화면 제공·시간대 고정 정책
7. T149 RTO/RPO·보존 기간·AI 예산
8. T155·T156: 0011 적용과 Staging 이미지 구성. 삭제된 검색어 이름 재사용(409) 정책
9. T148 F-1 처리, 기업·포트폴리오 DB 저장소
10. 담당자 확인: T138(김예주 #154), T140(조영우 — #239 이어받기 여부)

## 10. 다음 진행 계획

1. GPT-Web 검토 → 권장 순서로 병합(스택 PR 은 base 변경 후 CI 재확인)
2. PM 결정 1~10 반영 후 후속 PR
   - 정식 migration
   - 실제 DB 저장소
   - 암호화 적용
   - T143 실제 API 연결
3. Staging 읽기 전용 점검 승인 시
   - 경로 전수 401
   - 실행 digest
   - 원본 디렉터리 대조(T152)
   - 실측 용량(T149)
4. T136 착수 후 T150 재판정
