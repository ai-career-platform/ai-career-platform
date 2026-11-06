# T16 인수인계 (HANDOFF) — 사용자 프로필 CRUD API

> 최종 갱신: 2026-11-06 · 담당 후보: 김여름 (GitHub `kyrdufmal-summer`, Redmine 표시명 Yeoreum Kim) · Claude Code 보조
> **새 대화를 시작하면 이 파일과 4절의 원본 문서를 먼저 읽는다. 이 파일과 원본이 다르면 원본 계약 문서가 우선이다.**

## 0. 운영 규칙

- 추측을 완료로 기록하지 않는다. 항목마다 `확인됨(증거)` / `미확인` / `HOLD`로 구분한다.
- 실행 명령과 결과(검증 증거)를 함께 남긴다.
- 작업할 때마다 이 파일을 갱신한다(최종 갱신일, 7·8·9절).
- 팀 공용 저장소이므로 파일 생성과 커밋 전에 변경 범위를 담당자(본인)에게 확인받는다.
- 담당 확정(PM 승인) 전, 그리고 선행 일감이 끝나기 전에는 **설계·mock 범위**까지만 구현한다(Redmine #1556 선행조건). 실제 인증·DB 연동은 HOLD.
- 공용 Staging DB는 읽기 전용이다. INSERT/UPDATE/DELETE/DDL/Migration/Seed는 승인 없이 하지 않는다.

## 1. 프로젝트

- AI Career Platform — https://github.com/ai-career-platform/ai-career-platform
- 로컬 경로: `C:\dev\ai-career-platform`
- 작업 브랜치: `task/t16-user-profile-api` (2026-11-06 main `d1fae3a`에서 생성)
- PR: [#42](https://github.com/ai-career-platform/ai-career-platform/pull/42) (ready for review, `[PARTIAL]`, Auto-fix 켜짐)

## 2. 일감

- **T16 — 사용자 프로필 CRUD API** (Backend, P1)
- 범위: 로그인한 사용자의 `GET /api/v1/me`(조회), `PATCH /api/v1/me`(부분 수정)와 유효성 검사
- 산출물: router / service / repository / schema, pytest, Swagger 증빙
- 완료 기준: 조회·수정·404·422·타인 프로필 접근 차단 PASS. mock·격리 환경만 검증했으면 `PARTIAL`.

## 3. 신청·배정 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| Google Sheets | 확인됨: 진행 상태 `신청`, GitHub ID `kyrdufmal-summer` | 2026-11-06 시트 CSV 조회 |
| Redmine | 확인됨: [#1556](https://sulfite-footbath-next.ngrok-free.dev/issues/1556) Feature/**In Progress**/High, 담당자 Yeoreum Kim, 2026-11-16~2026-11-20, 진척 10% | 2026-11-06 이슈 JSON 조회 |
| PM 담당 확정 | 일정을 PM(문길래)이 직접 입력 → 확정으로 보고 진행 | Redmine 이력. PM·PL에게 따로 묻지 않기로 함 (리뷰는 PR에서) |

## 4. 원본 문서 (작업 전 반드시 확인)

| 문서 | 위치 | 상태 |
|---|---|---|
| T16 작업지시서 | `docs/work-orders/initial-30/T16.md` | main 반영 |
| Redmine #1556 | 위 링크 | 작업지시서와 같은 내용 + 선행 미완료 시 mock 범위 제한 |
| Backend 골격 | `backend/README.md`, `backend/app/` | T13 병합 |
| API 계약 | `docs/API_CONTRACT.md` §1.1~1.4(공통 규칙·인증·소유권·오류), `/me` 행, `Me`/`MePatch` DTO | v0.2 "검토 중, PM 승인 전" |
| OpenAPI | `docs/api/openapi.yaml` 경로 `/me`, 스키마 `Me`·`MePatch`·`Profile`·`Problem` | 위와 같음 |
| 데이터 사전 | `database/DATA_DICTIONARY.md` A01 `users`, A02 `user_profiles` | T05 병합 |
| 요구사항 | `docs/requirements/functional/ACCOUNT.md` FR-ACC-005 | T04 초안 |
| Backend 환경 가이드 | `docs/development/BACKEND_DEVELOPMENT_SETUP.md` | |

### 계약 요약 (2026-11-06 main `d1fae3a` 기준 — 원본 재확인 필요)

- `GET /api/v1/me` → `Me` 200 / 401
- `PATCH /api/v1/me` ← `MePatch` → `Me` 200 / 401 / 422
- `Me`: `user_id, email, display_name, status(active|disabled), profile{headline, bio, location_text}, created_at` — 추가 필드 금지
- `MePatch`: 필드 1개 이상, 추가 필드 금지
  - `display_name`: 문자열 1~100자, **null 불가**
  - `headline` ≤200, `bio` ≤5000, `location_text` ≤120: 문자열 또는 null(null이면 값 삭제)
  - 보내지 않은 필드는 그대로 유지. 이메일 변경은 1차 범위 밖
- 사용자 식별: **토큰 `sub`로만**. 경로·본문·쿼리로 `user_id`를 받지 않음. 타인 리소스는 404(403 아님)
- 인증: 자체 로그인, JWT 15분, `Authorization: Bearer` (T15 구현 예정)
- 오류: `application/problem+json` (`type, title, status, code, request_id`), 422 code `VALIDATION_FAILED`, 401 `UNAUTHENTICATED`/`TOKEN_EXPIRED`
- DB `users`: `user_id uuid PK, email, email_canonical(UNIQUE), display_name varchar(100) NOT NULL, status, last_login_at, created_at, updated_at`
- DB `user_profiles`: `user_id PK·FK(CASCADE) 1:1, headline varchar(200)?, bio text? (CHECK ≤5000), location_text varchar(120)?, created_at, updated_at`

## 5. 선행조건 (2026-11-06 확인)

| 일감 | T16에 필요한 것 | 실제 상태 | 증거 |
|---|---|---|---|
| T05 ERD | users·user_profiles 확정 | **병합됨** | PR #17, `database/DATA_DICTIONARY.md` |
| T06 API 계약 | /me 계약·오류 규칙 | **병합됨, 단 PM 승인 전·`T06_STATUS=PARTIAL`** | PR #29, `docs/API_CONTRACT.md` 머리말 |
| T13 Backend 골격 | `backend/app` 구조 | **병합됨**, smoke 7 passed (아래 6절) | PR #14 |
| T14 DB 세션 | `get_db`, 연결 풀 | **병합됨** (#25, main `0874dcd`): SQLAlchemy 2.0 `Session`, 쓰기는 호출자가 `commit`. ORM 모델은 T09 확정 후 추가 예정 | `backend/app/db.py`, `backend/README.md` |
| T15 인증 | 현재 사용자(`sub`) 추출 | **진행 중**: Redmine #1499 In Progress 10%, 2026-11-11~2026-11-17. PR·원격 브랜치는 아직 없음 | Redmine 조회 (2026-11-06) |
| T06 공통 에러 | 오류 응답 형식 | **병합됨**: #41 `{code, status, message}`, `AppError(ErrorCode)` | T16 브랜치에 병합(`2dff633`) |

판정: `T16_STATUS=PARTIAL`. 코드·테스트·로컬 일회용 DB 검증 완료, **DB 연동(T14) 완료**. T15 병합 후 `get_token_verifier` 연결만 남음.

## 6. 개발환경 (본인 Windows 11 PC)

| 항목 | 값 | 확인 방법 |
|---|---|---|
| Git | 2.55.0.windows.3 | `git --version` |
| VS Code | 1.144.0 + ms-python.python, pylance | `code --list-extensions` |
| 시스템 Python | 3.13.7 (기본, 유지) | `python --version` |
| Python 3.12 | 3.12.13 (uv 설치). `py -0p`에 `Astral/CPython3.12.13`로 표시되어 `py -3.12`로는 선택되지 않음 | `py -0p` |
| 가상환경 | `poc\staging\backend\.venv` (git 무시): fastapi 0.115.12 / uvicorn 0.34.2 / psycopg 3.2.9 / pytest 8.3.5 / httpx 0.28.1 | import 버전 출력 |
| `backend\.venv` | Python 3.12.13, `requirements-dev.txt` 설치 (SQLAlchemy 2.0.57, pydantic 2.14.3, psycopg 3.3.4, pytest, httpx, PyYAML, openapi-spec-validator) | 2026-11-06 생성, T14 병합 후 재설치. 백엔드 테스트는 이 venv로 실행 |
| 일회용 테스트 DB | 로컬 PostgreSQL 18.4 바이너리로 `initdb`(trust, 포트 55416, 임시 폴더). 테스트 후 중지 | 기존 `postgresql-x64-18` 서비스와 별개 |
| 공용 Staging DB 접속 정보 | 사용자가 교수님께 받음 (2026-11-06). **이 파일·채팅에 기록하지 않음** | T16은 공용 DB 쓰기 불필요 |
| GitHub CLI | `kyrdufmal-summer` 로그인 | `gh auth status` |
| 로컬 PostgreSQL | 서비스 `postgresql-x64-18` 실행 중, `C:\Program Files\PostgreSQL\18\bin\psql.exe` (PATH 미등록). T16 전용 DB **없음** | `Get-Service postgresql*` |
| Docker Desktop | 29.7.2 / Compose v5.4.0 설치, **엔진 시작 실패** (8절) | Backend 작업에는 불필요 |

### 검증 결과

| 날짜 | 검증 | 결과 |
|---|---|---|
| 2026-11-06 | PoC 서버 `uvicorn main:app` + `/health`, `/version`, OpenAPI 3경로, Swagger | PASS |
| 2026-11-06 | PoC `/health/db` | HOLD: 503 (DB 비밀번호 미입력 상태로 실행) |
| 2026-11-06 | Staging TCP `10.2.10.104:15432` | PASS (`TcpTestSucceeded=True`, 인증·TLS 성공 의미 아님) |
| 2026-11-06 | PoC `pytest -q tests` (main `6cf271b`) | PASS: 6 passed |
| 2026-11-06 | `backend` `pytest -q` (main `d1fae3a`, PoC venv 사용) | PASS: 7 passed, 1 warning |
| 2026-11-06 | T16 mock 구현 후 `backend` `pytest -q` (브랜치 `task/t16-user-profile-api`, 커밋 전) | PASS: 44 passed, 1 warning (`test_me.py` 37 + smoke 7) |
| 2026-11-06 | `uvicorn app.main:app --port 8016` 실제 기동: `GET /api/v1/me` 토큰 없음 / 임의 토큰 | 둘 다 401 (T15 전 기본 검증기가 모든 토큰 거부 — 의도대로) |
| 2026-11-06 | Swagger `/docs` | PASS: `me` 태그에 GET·PATCH `/api/v1/me`, Authorize(Bearer) 표시 |
| 2026-11-06 | main 병합(공통 에러 계약) 후 `backend` `pytest -q` | PASS: 89 passed (DB 테스트 13 skipped) |
| 2026-11-06 | 일회용 PostgreSQL 18.4 + 데이터 사전 DDL로 `tests/test_me_postgres.py` | PASS: 13 passed. 전체 102 passed |
| 2026-11-06 | main(T14 #25) 병합 후, 저장소를 SQLAlchemy Session으로 바꾸고 `get_db` 연결 | DB 없이 98 passed, 15 skipped / 일회용 DB로 **113 passed** (실제 `get_db` 경로 API 테스트 4개 포함) |
| — | 본인 PowerShell에서 직접 재확인 | **미확인** |

재현 (Windows PowerShell):

```powershell
Set-Location C:\dev\ai-career-platform\backend
.\.venv\Scripts\python.exe -m pytest -q          # DB 테스트는 skip

# 일회용 DB로 저장소까지 (버려도 되는 DB만! Staging 금지)
$pg = "C:\Program Files\PostgreSQL\18\bin"; $data = "$env:TEMP\t16pg"
& "$pg\initdb.exe" -D $data -U t16 -A trust -E UTF8 --locale=C
& "$pg\pg_ctl.exe" -D $data -l "$data.log" -o "-p 55416 -c listen_addresses=localhost" start
& "$pg\psql.exe" -h localhost -p 55416 -U t16 -d postgres -c "CREATE DATABASE t16_test"
$env:T16_TEST_ONLY = "YES"; $env:T16_TEST_DATABASE_URL = "postgresql://t16@localhost:55416/t16_test"
.\.venv\Scripts\python.exe -m pytest -q
& "$pg\pg_ctl.exe" -D $data stop -m fast
```

### 개발환경 설정 완료 증빙 (2026-11-06, 교수님 지시로 T16 개발 일시 중지 후 수행)

기준: `docs/development/BACKEND_DEVELOPMENT_SETUP.md` (main, STEP 01~11). 모든 항목은 실제 명령 실행 결과다.

| 가이드 단계 | 확인 내용 | 결과 | 증거 (실행 결과 요약) |
|---|---|---|---|
| STEP 01 도구 | Git / VS Code / Python 확장 / gh | PASS | `git version 2.55.0.windows.3`, `code 1.144.0`, ms-python.python·pylance, `gh 2.103.0` (`kyrdufmal-summer` 로그인) |
| STEP 01 Python | Python 3.12 | PASS (명령 차이) | 3.12.13 (uv 설치, 런처 이름 `Astral/CPython3.12.13`). **`py -3.12`는 "No suitable Python runtime"** → `py -V:Astral/CPython3.12.13` 또는 venv의 python 사용. python.org판 중복 설치 안 함 |
| STEP 02 Clone | 저장소·브랜치 | PASS | `C:\dev\ai-career-platform`, origin `ai-career-platform/ai-career-platform`, 브랜치 `task/t16-user-profile-api`, 작업 트리 깨끗 |
| STEP 03 venv | 가상환경·의존성 | PASS | `poc\staging\backend\.venv`, `backend\.venv` 모두 3.12.13 + fastapi 0.115.12 + uvicorn 0.34.2. `.venv`는 git 무시됨 |
| 로컬 PostgreSQL | 로그인 | PASS | 사용자가 직접 `psql -h localhost -p 5432 -U postgres` 실행: `postgres \| PostgreSQL 18.4 on x86_64-windows, compiled by msvc-19.44.35227, 64-bit (1개 행)`. 서비스 `postgresql-x64-18` Running/Automatic |
| STEP 04 DB 환경변수 | 비밀값 처리 | PASS | 사용자가 `Read-Host -AsSecureString`으로 입력, 세션 환경변수로만 사용. 파일·채팅에 비밀번호 없음 |
| STEP 05 서버 | `uvicorn main:app` 127.0.0.1:8000 | PASS | `Application startup complete.` / `Uvicorn running on http://127.0.0.1:8000` |
| STEP 06 API | `/health`, `/version`, OpenAPI, Swagger | PASS | 17:44·17:49 `/health` 200 `{"status":"ok"}`, `/version` 200 `local-dev`, 경로 `/health`·`/version`·`/health/db`, `/docs` 200 (내장 브라우저에서 3개 API 확인. Servers `/api` 선택은 #18 설정, 로컬에서도 `/api/health` 200) |
| STEP 07 공용 DB | `/health/db` (`ai_career_poc` DB, `career_reader` 계정, 10.2.10.104:15432) | **PASS** | 17:49:44 `200 {"status":"ok","service":"ai-career-database"}` (0.04초). 서버 로그에도 `GET /health`·`/version`·`/health/db` 각각 `200 OK` (사용자 화면 캡처). `SELECT 1`만 수행, 쓰기 없음 |
| STEP 09 pytest | PoC / backend | PASS | PoC 6 passed, backend 102 passed (일회용 DB 포함) — 6절 위 표 |
| DBeaver (DB 가이드) | 설치 여부 | 설치됨 | 26.1.4, `%LOCALAPPDATA%\DBeaver` (처음 진단에서 Program Files만 보고 "없음"으로 잘못 판단 → 정정) |

#### 환경설정 미해결 항목

| 항목 | 상태 | 영향 / 조치 |
|---|---|---|
| `py -3.12` 명령 | 가이드 명령 그대로는 실패 | 실사용 영향 없음(venv 사용). 필요하면 가이드 명령만 `py -V:Astral/CPython3.12.13`으로 바꿔 실행 |
| psql PATH 미등록 | 전체 경로로 실행 | `C:\Program Files\PostgreSQL\18\bin\psql.exe` |
| DBeaver 연결 `postgres 2` (10.2.16.91:5432) | 이 PC에서 TCP 접속 불가 | 가이드의 공용 DB(10.2.10.104:15432)와 다른 주소. 용도 확인 필요 |
| 로컬 PostgreSQL이 모든 주소(0.0.0.0:5432)에서 대기 | 확인됨 | 같은 네트워크에서 접근 가능. 필요하면 `listen_addresses`를 localhost로 (설정 변경은 별도 판단) |
| Docker Desktop | 엔진 시작 실패 (`docker-secrets-engine\engine.sock`) | Backend 가이드에는 불필요. 8절 참조 |
| `career_reader` 권한 범위 | 읽기 전용 여부 미검증 | T07(#46) 병합으로 팀 차원 검증 진행. 개인은 쓰기 시도하지 않음 |
| 브랜치가 main보다 뒤처짐 | main에 T14(#25)·T07·T10·SQLAlchemy 고정(#44) 병합 | PR #42에 `backend/tests/test_smoke.py` 1줄 충돌. **승인 전이라 병합 안 함** |

## 7. 작업 기록

| 날짜 | 작업 | 결과 |
|---|---|---|
| 2026-11-06 | Python 3.12 설치, 저장소 clone, venv·의존성 설치, PoC 검증 | 6절 |
| 2026-11-06 | Docker 시작 실패 조사: `%LOCALAPPDATA%\Docker\run`을 `run.stale-20261106`으로 이름 변경(삭제 안 함) | 1차 오류 해소, 2차 오류로 재실패 |
| 2026-11-06 | Redmine #1556 확인, main fast-forward(`6cf271b`→`d1fae3a`), 브랜치 `task/t16-user-profile-api` 생성 | 3·5절 |
| 2026-11-06 | T05/T06/T13/T14 결과와 계약 문서 검토, 미확정 사항 기록 | 4·5·8절 |
| 2026-11-06 | 이 HANDOFF 파일 생성 | 커밋 안 함 |
| 2026-11-06 | mock 범위 구현 (담당자 승인 후). 아래 "구현 내용" | pytest 44 passed, 커밋 `a6cbd59` |
| 2026-11-06 | PR #42 생성, Auto-fix 켬 | |
| 2026-11-06 | main 충돌 해결: 공통 에러 계약(#41) 병합, T16 오류를 `AppError`로 변경 | 89 passed, 커밋 `2dff633` |
| 2026-11-06 | PostgreSQL 저장소 `user_profile_postgres.py` + 일회용 DB 테스트 13개 | 102 passed, 커밋 `73c1bf9` |
| 2026-11-06 | 교수님 지시로 T16 개발 일시 중지, Backend 개발환경 전체 점검·검증 | 6절 "개발환경 설정 완료 증빙" — 공용 DB `/health/db` 200 포함 전 단계 PASS |
| 2026-11-06 | T14(#25) main 병합 확인 → PR #42에 `test_smoke.py` 충돌 | 승인 전이라 미처리 |

### 구현 내용 (2026-11-06, 커밋 전)

| 파일 | 내용 |
|---|---|
| `backend/app/schemas/me.py` (신규) | `Profile`, `Me`, `MePatch`. 길이 제한, `extra="forbid"`, `display_name` null·공백 거부, 빈 본문 거부, `changes()`는 보낸 필드만 반환 |
| `backend/app/repositories/user_profile.py` (신규) | `UserProfileRepository` 인터페이스 + `InMemoryUserProfileRepository`(테스트용). PostgreSQL 구현 없음 |
| `backend/app/services/me.py` (신규) | `get_me`, `update_me`, `UserNotFoundError` |
| `backend/app/core/auth.py` (신규) | `get_current_user_id`(Bearer 헤더 → 검증기 → user_id). 기본 검증기 `get_token_verifier`는 **모든 토큰 거부(401)** — T15가 교체 |
| `backend/app/routers/me.py` (신규) | `GET`·`PATCH /api/v1/me`. 기본 저장소 `get_user_profile_repository`는 **503** — T14 후 교체 |
| `backend/app/routers/api_v1.py` (수정) | `me.router` 연결 1줄 |
| `backend/tests/test_me.py` (신규) | 37개: 조회·부분수정·null 삭제·프로필 행 없음·최대 길이·404·401(8)·소유권(본문/쿼리 user_id, 타인 미변경)·422(13)·OpenAPI |
| `backend/tests/test_smoke.py` (수정) | T13 테스트 2개가 "`/api/v1/me`는 404", "경로는 `/health`·`/version`뿐"을 검사해 T16과 충돌 → 미구현 경로를 `/api/v1/not-implemented`로, 경로 검사를 포함 관계로 변경 |

구현 중 정한 것 (8절 미확정 사항에 대한 임시 선택 — 리뷰에서 확인 필요):
- 404: 토큰은 유효하나 사용자 행이 없을 때만 (8절 2번)
- `display_name` 공백만 → 422, 다른 필드의 빈 문자열 `""` → 그대로 저장 (8절 5번)
- 프로필 행이 없으면 GET은 프로필 필드 null, PATCH는 값 저장 (8절 4번)
- `status=disabled` 사용자도 현재는 조회·수정 가능 (8절 3번, T15 토큰 정책 대기)
- ~~오류 형식은 FastAPI 기본~~ → main의 공통 에러 계약(#41)으로 해결: 401 `UNAUTHENTICATED`, 404 `NOT_FOUND`, 422 `VALIDATION_FAILED`, 503 `DEPENDENCY_UNAVAILABLE`
- OpenAPI에 `MePatch.minProperties: 1`은 표시되지 않음(실행 시 검사는 함)
- `updated_at`은 앱 SQL에서 `now()`로 갱신 (8절 7번 — DB 트리거로 정해지면 제거)

PostgreSQL 저장소 (`backend/app/repositories/user_profile_postgres.py`, 2026-11-06):
- T14 `get_db`의 SQLAlchemy `Session`을 받음 (처음엔 Draft의 psycopg `Connection` 기준으로 만들었다가 병합본에 맞춰 변경). `update` 성공 시 `commit`, 실패 시 `rollback` (T14: 커밋은 호출자 책임)
- ORM 모델은 T09 확정 후 추가 예정이라 `text()` SQL로 쿼리. 모델이 생기면 이 파일만 교체
- `users` 행을 `FOR UPDATE`로 잠근 뒤 `user_profiles`는 `INSERT ... ON CONFLICT DO UPDATE`로 보낸 컬럼만 반영
- 컬럼 이름은 허용 목록만 `sql.Identifier`로. 값은 모두 바인딩
- psycopg·SQLAlchemy는 T14/#44가 `requirements.txt`에 넣음 → T16이 `requirements-dev.txt`에 넣었던 중복 줄 제거
- **앱 연결 완료**: `get_user_profile_repository`가 `get_db` Session으로 `PostgresUserProfileRepository`를 돌려줌. `DATABASE_URL`이 없으면 `get_db`가 503 `DEPENDENCY_UNAVAILABLE`

## 8. 미해결 문제

### 계약상 미확정·불일치 (T16 작업지시서 1번 지시: 기록 대상)

1. **PATCH에 409가 있는가**: 작업지시서·옛 API 초안은 200/409/422, 현재 OpenAPI는 200/401/422. 이메일 변경이 1차 범위 밖이라 409가 날 경우가 없어 보임 → OpenAPI(409 없음)를 따를 예정, 확인 필요.
2. **작업지시서의 404·"공개범위"**: `/me`는 경로에 ID가 없어 타인 프로필을 지정할 방법 자체가 없음. 현재 OpenAPI의 `/me`에는 404가 없음. FR-ACC-005는 "프로필은 본인만 볼 수 있다"로 공개범위 기능 없음. → 404는 "토큰은 유효하나 사용자 행이 없음(탈퇴 처리 완료 등)"에만 쓸지 결정 필요.
3. **`status=disabled` 사용자의 /me**: 탈퇴 요청 시 즉시 비활성화(FR-ACC-007). 이 사용자가 /me를 조회·수정할 수 있는지 계약에 없음 (T15 토큰 정책과 연결).
4. **`user_profiles` 행이 없을 때**: 가입 시 함께 만드는지(T15) 계약에 없음. 없으면 GET은 `profile` 필드를 모두 null로, PATCH는 행을 만드는(upsert) 방식이 자연스러움 → 확인 필요.
5. **빈 문자열 처리**: FR-ACC-005 수용 기준 2 "항목을 비우면 빈 값으로 저장". `""`를 그대로 저장할지, null로 바꿀지 미정. `display_name`의 공백만 있는 값(`"  "`)은 1~100자 규칙상 통과됨 → 거부할지 결정 필요.
6. ~~Problem 응답·422 변환기~~ → **해결**: T06 #41 공통 에러 계약 병합.
7. **`updated_at` 갱신**: 앱에서 넣을지 DB 트리거로 할지 미정 (T08/T09). 현재 앱 SQL에서 `now()`.
8. **경로 접두사(T06-4)**: 앱의 `/api/v1`과 Staging Nginx의 `/api/` 제거가 충돌. T13·T30 결정 대기. T16 코드는 `API_V1_PREFIX`만 따르면 영향 없음.

### 오류

- **Docker Desktop 시작 실패**: 지난 실행의 소켓 파일을 지울 수 없어 backend가 멈춤. 1차 `Docker\run\sailor-ingest.sock`(폴더 이름 변경으로 해소), 2차 `%LOCALAPPDATA%\docker-secrets-engine\engine.sock`(**미해결**). "Reset to factory defaults"는 이미지·볼륨이 지워지므로 쓰지 말 것.

### 결정 대기

- 위 미확정 1~5·7번 → PR #42 리뷰에서 확인 (PM·PL에게 따로 묻지 않음)

### 위험 요소

- 공용 Staging DB 쓰기·스키마 변경 금지. 쓰기 테스트는 로컬 PostgreSQL의 T16 전용 DB에서만.
- `ai_career_poc`은 SUPERUSER이므로 사용하지 않음.
- 비밀번호·토큰은 PowerShell 세션 변수로만. `.env`·코드·로그·캡처·커밋 금지.
- PoC 운영 파일(`poc/staging/compose.yaml`, `automation/config.json`)과 `poc/staging/backend`는 수정하지 않음 (Staging 자동 배포 대상).
- T15가 정할 인증 의존성 이름·형태와 T16의 임시 인증 주입이 어긋날 수 있음 → 인증은 의존성 하나로 격리해 T15 병합 시 교체.

## 9. 다음 작업 (한 단계)

**T15(인증) 병합을 기다린다** (Redmine #1499, 2026-11-11~17). T14 연동과 PR #42 충돌 해결은 끝났다 (2026-11-06).

T15가 병합되면 `app/core/auth.py`의 `get_token_verifier`를 T15의 JWT 검증(`sub` → user_id)으로 바꾸고, 토큰 발급부터 `/api/v1/me`까지 일회용 DB로 끝까지 검증한 뒤 `PARTIAL` → `PASS` 여부를 판단한다.
그 사이 PR #42 리뷰 댓글·충돌은 Auto-fix로 처리한다.

## 10. 보안

- 이 파일에 비밀번호, Token, API Key, `.env` 실제 값, DB 접속 비밀값을 절대 기록하지 않는다.
- 접속 정보는 가이드에 공개된 범위(호스트, 포트, DB명, 계정명)까지만 적는다.
- 다른 팀원의 이메일 등 개인정보는 기록하지 않는다(GitHub ID만).
