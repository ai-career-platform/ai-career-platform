# 전체 시스템 E2E 검증 보고서 (2026-11-14)

> 합성 데이터만 사용. 운영·Staging·GCP·Cloud SQL·외부 메일·Google OAuth 사용 없음. 아래 PASS 는 모두 CI 실행 증거가 있는 단계만이다.

## 1. 환경

| 항목 | 값 |
|---|---|
| 브랜치 / PR | `test/full-system-e2e` / #361 (Draft) |
| 검증 커밋 | head `f506fa8` (CI 병합 ref `adb81942`) |
| 포함 스택 | `85ab49d`(0001–0010, #348 #350 #351 #352 #354 #355 #357, #359@35fe589) + `origin/feat/t81-moderation-cases-sql`@`a93d8ae` 병합(`d0ae0a5`, 최종 지시) |
| PostgreSQL | **18.3** (`SHOW server_version` = `18.3 (Debian 18.3-1.pgdg13+1)`, E2E job `postgres:18.3`). 백엔드 회귀 job 은 기존 `postgres:18.1` |
| 브라우저 | Playwright(playwright-core 1.49.1) Chromium 131.0.6778.33, headless |
| 런타임 | Python 3.12, Node 24, ubuntu-24.04 |
| CI 실행 | E2E run 43604942164, Backend tests 43604942125, CI 43604942103, Frontend 43604942354, offline-tests 43604942332 |
| 증거 artifact | `full-system-e2e` (results.json, summary.md, migrate.log, api.log, web.log, browser/network.jsonl, browser/console-errors.jsonl, trace-*.zip, 실패 스크린샷) |

로컬(Windows, pgserver PG16)은 하네스 개발용 **참고 실행**만 했고 PG18 증거로 쓰지 않았다. 로컬에서는 문서 저장 폴더 권한 검사(0o700)가 Windows 에서 성립하지 않아 문서 단계가 503 이었고, Linux CI 에서는 PASS.

## 2. 하네스 구성

- `tests/e2e_full/run_full_e2e.py`: loopback·`E2E_ALLOW_RESET=YES` 일 때만 일회용 DB `e2e_full_system` 재생성 → `DRAFT_00`(역할·스키마)·`DRAFT_01`(원장) → **`database/migrate.py` 러너를 subprocess 로** `lint / apply --target ci / verify / status` → 0001 seed + `fixtures_e2e_only.sql`(시험 전용) → `career_app` 구성원 로그인 역할(최소 권한)로 uvicorn → 합성 계정 6개(실제 가입 API, 관리자 역할만 SQL) → API 검사 → vite preview(빌드 산출물, `/api` proxy) → Playwright → SQL 정합성 검사 → 보고서.
- 기능 플래그: API 프로세스 env(`JOB_APPLICATIONS_API` `NOTIFICATIONS_API` `COMPANY_ACCOUNTS_API` `COMPANY_POSTINGS_API` `PUBLIC_PORTFOLIO_API` `PERSONAL_DATA_REQUESTS_API` `ADMIN_MODERATION_API`)와 E2E job 의 Vite 빌드 env 에서만 켰다. 기본값·`.env.example`·Dockerfile·배포 파일은 바꾸지 않았다.
- T115 G7: 워크플로에 `migrate.py … apply` 줄 없음(로컬 `check_auto_apply()` = `[]`, G6 = `[]`).
- worker(`app.document_worker`, `app.personal_data_worker`)는 시나리오 중간에 1회씩 실제 실행했다.

## 3. Migration 확인 (PG 18.3)

`LINT=PASS files=10` → `APPLIED 0001…0010` → `APPLY=PASS count=10` → `VERIFY=PASS applied=10 pending=0` → status 10/10 applied (artifact `migrate.log`). 원장 순서는 파일 목록과 같다.

## 4. 회귀 (CI, PR #361)

| 검사 | 결과 | 기준선 대비 |
|---|---|---|
| Backend tests (PG 18.1, `pytest -q`) | **2148 passed / 0 failed / 82 skipped** | 기준 2147/0/82 → +1 = FSE-001 회귀 시험 추가분. skip 변화 없음 |
| CI / Backend pytest (DB 없음) | 1854 passed / 376 skipped | DB 시험은 이 job 에서 skip(기존과 같은 구조) |
| Frontend (lint, check:api, vitest, build+tsc) | PASS — vitest 680 passed / 22 skipped (파일 60 passed / 3 skipped) | 실패 0 |
| offline-tests | PASS (crawler 515, training 21, PG 연동 9·2·1·14·1·16·10·3·2·1·6·7 tests, 모두 OK) | 실패 0 |
| Migration runner·T115 gate·T05·T10 seed·isolated migration·upload-e2e | PASS | 같음 |
| **Full-system E2E (신규)** | **PASS — 87 PASS / 0 FAIL / 3 NOT_RUN** | 신규 |

CI 11개 check 모두 PASS.

## 5. 기능별 결과 (E2E, PG 18.3)

`source`: browser = Playwright 화면 조작, harness = 실제 HTTP(API)·SQL. 단계 이름은 artifact `results.json` 과 같다.

### USER (구직자)
| 단계 | 결과 |
|---|---|
| 로컬 계정 로그인(이메일·비밀번호) → /account, 새로고침 후 세션 유지(refresh 쿠키) | PASS (browser) |
| 프로필 보기(이름·이메일·역할) | PASS (browser) |
| 프로필 수정 | API PASS(`PATCH /me`), **화면 NOT_RUN — 수정 화면 없음(FSE-002)** |
| 경력 추가·프로젝트 추가/삭제, 새로고침 후 유지 | PASS (browser) |
| 경력 수정 | API PASS(+남의 경력 404), **화면 NOT_RUN — 수정 버튼 없음(FSE-003)** |
| 기술 검색·추가·저장·새로고침 유지·삭제 | PASS (browser) |
| 내 데이터 내보내기: 비밀번호 재확인 → 요청 → worker → 완료 → 1회 다운로드(본인 데이터만) | PASS (browser + harness: 틀린 비밀번호·재확인 없음 거부, 남의 요청 404, 2번째 다운로드 거부) |

### PUBLIC_POSTINGS (공개 공고)
| 단계 | 결과 |
|---|---|
| 공고 검색 → 상세 패널 | PASS (browser) |
| 익명 목록 200, draft 행 없음, seed draft 상세 404, 공개 공고 상세 200 | PASS (harness) |
| 기업 draft·검수 대기·반려 공고 비노출(익명·로그인) | PASS (browser + harness) |
| 잡코리아 모양 수집 draft fixture 검색 0건·상세 404, 모든 흐름 후에도 draft | PASS (browser + harness + SQL) |
| 승인된 기업 공고만 공개 목록에 나옴(company_direct 출처) | PASS (browser + harness + SQL) |
| 익명 보호 화면 → 로그인으로 이동 | PASS (browser) |

### COMPANY (기업)
| 단계 | 결과 |
|---|---|
| 조직 등록(화면) → 기업 관리자·운영 확인 대기, 멤버 표 '기업 관리자' | PASS (browser) |
| 조직 승인 | PASS — **관리자 화면이 없어 실제 API 로 수행(FSE-006)**, 일반 사용자 승인 403 |
| 초안 작성 → 필수 항목 편집·저장 → 검수 요청 → '검수 대기' (2건) | PASS (browser) |
| 비멤버 목록·작성·조회 404, 익명 401 | PASS (harness) |
| 승인 결과 '게시 중', 반려 결과 '반려' + 사유 표시 | PASS (browser, 사유 "반려 사유: 사실과 다른 조건") |
| 초대 메일 | NOT_RUN — 메일 공급자 미연결(설계상 503), 범위 밖 |

### MODERATION (운영 검수, #359 a93d8ae 정책)
| 단계 | 결과 |
|---|---|
| P1 검수 요청 → 검수 건 정확히 1건(API 2건 + 화면 2건) | PASS |
| P2 실패한 검수 요청(필수 누락 422, 오래된 version 409) → 검수 건 없음·공고 그대로 | PASS |
| P3 동시 검수 요청 4건 → 200 1건, 열린 검수 건 1건 | PASS |
| P4 검수 건 승인 → APPROVED(닫힘), 공고·공개 행 published, 재결정 거부 | PASS (API + 화면) |
| P5 실패한 승인(담당 전, 오래된 version) → 공고·공개 행 변화 없음 | PASS |
| P6 검수 건 반려 → 공고 rejected·사유 표시·비공개 | PASS (API + 화면) |
| P7 `/admin/company-postings/{id}/decision` → 관리자 409, 구직자·기업 담당자 403, 게시 없음 | PASS |
| P8 비관리자(구직자·조직 owner) 검수 API 403, 익명 401, 구직자 화면 '접근 권한이 없습니다' | PASS |
| P9 잡코리아 draft 비공개 유지 | PASS |
| 관리자 로그인 → 검수 큐 → 상세 → 담당 시작 → 승인/반려(사유·메모) → 상태 필터 | PASS (browser) |
| 감사 기록: 검수 열람 `admin.content.review` 기록 존재 | PASS (실제 API `GET /admin/audit-events`) |
| 감사 기록 화면 | **NOT_RUN — 실제 API 모드 화면 없음(Mock 전용, FSE-005)** |

미검증: 관리자에게 `admin.content.review` 권한만 없는 경우(역할은 admin) — 합성 역할 구성이 필요해 이번 E2E 에서 하지 않음(#359 PG 시험이 다룸). 제출 중 서버 내부 오류에 의한 롤백(훅 실패 주입)은 HTTP 로 주입할 수 없어 422/409 실패 경로로만 확인.

### DOCUMENT (문서)
| 단계 | 결과 |
|---|---|
| PDF 업로드(화면) → 확인 대기 → worker → '다운로드 가능' → 다운로드 바이트 동일 → 삭제 확인 → worker → 목록에서 사라짐 | PASS (browser) |
| API 같은 수명주기 + 남의 문서 404 | PASS (harness) |

### NOTIFICATION (알림)
| 단계 | 결과 |
|---|---|
| 본인 지원 단계 변경 → 알림 행 0, 알림함 '받은 알림이 없습니다' | PASS (browser + API + SQL) |
| 지원 기록 중복 409, 오래된 version 409, 남의 기록 404 | PASS (harness) |
| 알림 수신(다른 행위자가 만든 알림) | NOT_RUN — 이 스택에서 알림을 만드는 흐름이 없음 |

### PORTFOLIO (공개 포트폴리오)
| 단계 | 결과 |
|---|---|
| 항목·경력 선택 → 저장 → 공개 확정(동의) → 7일 링크 생성 | PASS (browser) |
| 익명 링크 열람 → 선택 항목만 표시, 이메일 비노출 | PASS (browser + harness: 미선택 지역 비노출, `Cache-Control`·`X-Robots-Tag`) |
| 링크 회수 → 익명 '볼 수 없는 링크입니다' | PASS (browser) |
| 동의 철회 → 새 링크도 차단, 동의 없는 사용자 링크 생성 거부, 잘못된 토큰 404 | PASS (browser + harness) |

### SQL 정합성 (모든 흐름 후)
NOT VALID 제약 0, 비활성 트리거 0, 게시 전 기업 공고의 공개 행 0, published 기업 공고 ↔ company_direct 공개 행 일치, 고아 company_direct 공개 행 0, 이벤트 조직 일치, 모든 조직 owner ≥1, 대상별 열린 검수 건 ≤1, APPROVED→published / REJECTED→비공개, 결정 이벤트 존재, 자기 알림 0, 지원 (사용자,공고) 중복 0, 동의 없는 활성 링크 0, 삭제 대기 문서 0 — 모두 PASS.

## 6. 기능별 판정

| 기능 | 판정 | 근거 |
|---|---|---|
| USER | **조건부 PASS** | 핵심 흐름 PASS. 프로필·경력 수정 화면 없음(FSE-002·003) |
| COMPANY | **조건부 PASS** | 작성·검수 요청·결과 확인 PASS. 조직 승인 관리자 화면 없음(FSE-006), 초대 메일 미검증 |
| MODERATION | **PASS** | #359 정책 9개 + 화면 흐름 PASS. 감사 화면은 Mock 전용(FSE-005) |
| PUBLIC_POSTINGS | **PASS** | 비공개 공고 노출 0, 승인 공고만 공개 |
| DOCUMENT | **PASS** | 화면·API 수명주기 PASS |
| NOTIFICATION | **PASS(범위 한정)** | 자기 알림 없음 확인. 알림 수신 경로는 생성 흐름이 없어 NOT_RUN |
| PORTFOLIO | **PASS** | 동의·링크·회수·철회 차단 PASS. FSE-001(가입 약관 500)은 이 PR 에서 수정 |

## 7. 실행 방법

```
E2E_ALLOW_RESET=YES PLAYWRIGHT_CORE=<playwright-core 경로> \
python tests/e2e_full/run_full_e2e.py --admin-url postgresql://<user>:<pw>@127.0.0.1:5432/postgres --out e2e-out
```
(먼저 E2E 용 플래그로 `frontend` 를 빌드. 워크플로 `.github/workflows/full-system-e2e.yml` 참고.)
