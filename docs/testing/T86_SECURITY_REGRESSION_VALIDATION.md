# T86 — 인증·API 보안 회귀 테스트 검증

> 판정: **PARTIAL** — 보안 회귀 게이트와 일회용 PostgreSQL 검증을 추가했습니다. 고위험 권한 누출은 발견되지 않았습니다.
> 접근 로그 Finding F-1(Medium)은 재현했지만 운영 설정 변경은 범위 밖이라 수정하지 않았습니다. T58·T81 실 API는 없어서 HOLD입니다.
> **갱신(T112, 2026-11-11)**: F-1의 uvicorn 접근 로그 쪽은 앱 내 필터(`app.core.observability.StripQueryFilter`)로 완화했습니다. 시험은 "남지 않음" 기준으로 바꿨습니다. Nginx `combined` 로그 쪽은 여전히 미적용입니다(제안 설정 `docs/ops/observability/`, 승인 필요).
> 확인일 2026-11-10 · 기준 main `a24608d` · 브랜치 `task/t86-security-regression-suite`
> Backend 업무 코드 변경 0건 — 시험·문서만 추가했습니다.

## 1. 선행 작업 상태

| 일감 | 상태 | 근거 | T86 처리 |
|---|---|---|---|
| T28 | 완료 — Frontend lint/test/build PR 검사 | PR #133 | CI 게이트 재사용 |
| T31 | 완료 — 동의·탈퇴 요청 API | PR #139 | 인증 게이트에 포함(`/me/consents`, `/me/deletion-request`) |
| T49 | 완료 — 문서 업로드·보관 API·보안 E2E | PR #159 | 기존 시험 재사용 + 빈 곳만 추가 |
| T58 | **미착수** — 작업지시서 NOT_STARTED, PR·경로 없음 | `docs/work-orders/next-30/T58.md` | **HOLD** |
| T81 | 계약만 — 검수 API 경로 없음 (T82 UI는 Mock) | PR #184 | **HOLD** |
| T84 | 완료 — 감사·AI 사용량 API (확정 계약) | PR #185·#186 | 관리자 공통 시나리오 추가 |

T58·T81 경로가 생기면 아래 경로 목록 게이트(§2)에 자동으로 포함됩니다. 인증·admin 403 검사는 자동이고, 경로 변수가 있으면 IDOR 등록이 필요합니다.

## 2. 보안 테스트 대상 API

`tests/security/security_inventory.py`가 **실제 등록된 라우터**에서 경로 목록을 읽습니다: 63개, 비공개 48개, admin 8개. 경로를 손으로 나열하지 않으므로, 새 경로가 생기면 시험에 자동으로 들어갑니다.

| 목록 | 내용 | 바뀌면 |
|---|---|---|
| `PUBLIC_ROUTES` (13) | 토큰 없이 처리: health·version, 가입·로그인, 동의 정책, 기업·공고·직무·기술 조회 | 실제 "401이 아닌 경로" 집합과 다르면 실패. 계약의 `security: []`와도 대조 |
| `COOKIE_AUTH_ROUTES` (2) | refresh·logout (HttpOnly 쿠키 + CSRF 헤더) | 쿠키 없음·위조 시 401, CSRF 헤더 없으면 403 |
| `IDOR_COVERAGE` (16) | 경로 변수가 있는 비공개 경로 → IDOR 시험 위치 | 등록되지 않은 경로, 또는 시험 함수가 없으면 실패 |

## 3. 인증·인가 검증 (DB 없음, T15 메모리 인증 — 실제 `create_app`)

| 시험 | 범위 | 결과 |
|---|---|---|
| 토큰 없음 → 401 + `WWW-Authenticate: Bearer` | 비공개 48개 전부 | PASS |
| 위조 토큰 4종(다른 키, `alg=none`, 형식 오류, payload 변조) | 48 × 4 | PASS |
| 만료 토큰 → 401 `TOKEN_EXPIRED` | 48 | PASS |
| 서명은 맞지만 서버에 세션 없음(토큰 안 roles=admin) | 48 | PASS |
| 로그아웃한 세션의 토큰 | 48 | PASS |
| 토큰 없이 닿는 경로 = 검토 목록 (게이트) | 전체 63 | PASS |
| 공개 경로 ⊆ 계약 공개 경로, refresh·logout은 계약상 비공개 | — | PASS |
| 일반 사용자 → 403 | admin 8개 전부 | PASS |
| 토큰 안의 `admin` 역할 주장은 무시 | admin 8 | PASS |
| 같은 토큰에서 역할 회수 → 다음 요청부터 403, 재부여 → 다시 허용 | admin 8 | PASS |
| `admin.audit.read` 없는 admin → 감사 목록만 403, 나머지는 역할만 요구 (D1 미승인 확정 동작을 고정) | admin 8 | PASS |
| 비활성 사용자 → 401 | admin 8 | PASS |

**변이 확인(커밋하지 않은 일회성 스크립트)**: 인증 없는 경로, 역할 검사 없는 admin 경로, IDOR 미등록 경로를 임시로 추가하면 게이트 13건이 실패했습니다. 게이트가 실제로 잡는다는 것을 확인했습니다.

## 4. IDOR 검증

| 경로 | 시험 | 환경 | 결과 |
|---|---|---|---|
| 경험·프로젝트 PATCH·DELETE (B → A의 id) | `test_pg_career_history_is_owner_scoped` — 404, A 행 불변 | **PostgreSQL** | PASS |
| 소유자 지정 시도(body `user_id`, query `user_id`) | `test_pg_owner_cannot_be_chosen_by_the_client` | PostgreSQL | PASS |
| 북마크 PUT·DELETE (B의 삭제가 A의 북마크를 지우지 않음) | `test_pg_bookmarks_are_owner_scoped` | PostgreSQL | PASS |
| 세션 폐기(B → A의 세션 id) 404, A 세션 유지 | `test_pg_sessions_and_privacy_are_owner_scoped` | PostgreSQL | PASS |
| 문서·분석·매칭·추천 실행·세션 | 기존 T49·T51·T53·T54·T15 시험(`IDOR_COVERAGE`에 위치 등록, 함수 존재 확인) | 기존 | 기존 CI |
| 등록 게이트 | 경로 변수가 있는 비공개 경로 16개 = 등록 16개 | 단위 | PASS |

## 5. 업로드 검증

기존 T49 시험이 확장자·MIME·시그니처·크기 초과(두 단계)·파일명 경로(`../x.pdf`)·빈 파일·실패 후 잔여 파일·교차 사용자 조회·다운로드·삭제·인증 선행을 다룹니다. live E2E는 symlink·권한·경쟁 상태를 다룹니다. 이 시험들은 **다시 작성하지 않았습니다.**

T86 추가 (`tests/security/test_security_upload.py`, 기존 `docs` fixture 재사용):

| 시험 | 기대 | 로컬(Windows) | Linux CI |
|---|---|---|---|
| 문서 ID 자리의 경로 탐색·비 UUID 7종 × GET·/file·DELETE | 404/422, 파일 내용 미노출, 삭제 없음 | **NOT_RUN** | **PASS** |
| 클라이언트가 소유자를 지정 (form·query의 `owner_user_id`·`user_id`) | 거부(422) 또는 업로드한 사람이 소유자 | NOT_RUN | **PASS** |
| 목록의 `user_id` 질의 | 다른 사람 문서 미노출 | NOT_RUN | **PASS** |
| 잘못된 요청 Content-Type 3종 | 400/415/422, 저장 파일 없음 | NOT_RUN | **PASS** |

로컬에서 실행하지 못한 이유: 문서 저장소가 POSIX 전용입니다(디렉터리 0700 검사, `os.O_DIRECTORY`). 기존 `tests/test_documents.py`도 Windows에서는 같은 이유로 실패합니다. 이 결과를 PASS로 세지 않았습니다.

## 6. SQL Injection 검증 (실제 PostgreSQL)

합성 페이로드 11종을 썼습니다: `' OR '1'='1`, `'; DROP TABLE career.skills; --`, `UNION SELECT email …`, `pg_sleep(5)`, `%`, `_`, `\` 등.

| 시험 | 대상 | 결과 |
|---|---|---|
| 검색어가 글자 그대로 처리됨, 결과 행은 페이로드를 실제로 포함한 것만, 이메일 미노출, 지연 없음(<3초), **모든 표 행 수 전후 동일** | 직무·기술·기업·공고 검색 `q` | PASS |
| LIKE 와일드카드(`%%`, `__`, `_%`, `%_`)가 전체를 돌려주지 않음 | 기술 검색 | PASS |
| 관리자 필터: `action_code` 바인딩(빈 결과), `actor_user_id`·`group_by` 422, 행 수 불변 | T84 두 API | PASS |
| cursor·경로 변수 주입 → 400 / 404·422 | 공고·기업 | PASS |

## 7. CORS 검증

| 시험 | 결과 |
|---|---|
| 앱에 CORS 미들웨어 없음, Nginx 설정에 `Access-Control-*` 없음 (추가하면 시험 실패 → 검토) | PASS |
| 외부 Origin: 토큰 없으면 401·ACAO 없음, 토큰 있어도 ACAO 없음, preflight 거부 | PASS |
| **CORS를 넓게 열어도**(시험용 앱에 `CORSMiddleware(allow_origins=[evil])`) preflight는 통과하지만 토큰 없음 401, 일반 사용자 403 | PASS |
| 브라우저 자동 쿠키(refresh)만으로는 API 인증 불가 → 401 | PASS |
| 쿠키 인증 경로(refresh·logout)는 CSRF 헤더 없으면 403 | PASS |

## 8. 감사·비용 API 보안 (T84 보완, 중복 제외)

| 시험 | 결과 |
|---|---|
| 악성 필터 10종: 관리자 → 200 빈 결과 또는 422(입력 미반사), 일반 사용자 → 403 (인가가 입력 검증보다 먼저) | PASS |
| 사용량 악성 파라미터 4종 → 422, 비용 헤더 없음 | PASS |
| cursor는 자격 증명이 아님: 일반 사용자 재사용 403, 토큰 없음 401 | PASS |
| 다른 관리자의 cursor 재사용 → 200 (사용자에 묶이지 않음 — F-2, 같은 권한) | 동작 기록 |
| 오류(401·503) 응답에 비용 헤더 없음, 내부 정보 없음 / 성공 시 `unverified` | PASS |
| 응답 필드는 확정 7개, 이메일 없음 | PASS |

## 9. 로그 개인정보 검사

| 시험 | 결과 |
|---|---|
| 가입·로그인(성공·실패)·refresh·조회·위조 토큰·관리자 필터 흐름 전체에서, 서버 애플리케이션 로그(`app.*` 등)에 비밀번호·access token·refresh token·이메일·필터 사용자 ID 없음 | PASS |
| 422 검증 오류가 비밀번호를 되돌려주지 않음 (3종) | PASS |
| SQL 오류 로그에 파라미터 미노출 (`hide_parameters=True`) | PASS (T84 PG 시험) |
| **접근 로그** — 실제 uvicorn 서버(루프백 임시 포트, 기본 `access_log=True`)에 합성 요청 | **F-1 재현** (§11) |
| 개선안 프로토타입(쿼리 제거 로그 필터)을 붙이면 사용자 ID가 사라짐 | PASS (시험 코드 안의 프로토타입, 운영 미적용) |

## 10. PostgreSQL 통합 검증

- 환경: 로컬 PostgreSQL 18 일회용 클러스터(스크래치 디렉터리, 127.0.0.1 전용 포트, DB `t16_profile_test`). 시험 후 삭제했습니다.
- T16 가드(`T16_ISOLATED_DB_TEST=YES`, loopback, DB 이름)를 그대로 씁니다. 0001 Migration + 0001 Seed에 합성 A·B·관리자(`@example.invalid`)를 더했습니다.
- 앱은 **최소 권한 역할**로 접속합니다. 전체 표는 SELECT, 쓰기는 `user_experiences`·`user_projects`·`user_project_skills`·`user_job_bookmarks`에만 주고 `auth_sessions`는 UPDATE만 줍니다. SUPERUSER가 아닙니다.
- 실제 FastAPI `TestClient` → SQLAlchemy → PostgreSQL 경로를 썼습니다.

| 범위 | 결과 |
|---|---|
| `tests/security` 중 PG 시험 (IDOR 4, SQLi·입력 7) | PASS |
| DB 없는 시험(Mock·메모리)과 구분 | §3·§7·§8·§9는 DB 없음, §4(PG 부분)·§6은 PostgreSQL |

## 11. 발견된 취약점

| ID | 심각도 | 내용 | 재현 | 수정 필요 |
|---|---|---|---|---|
| **F-1** | **Medium** | 감사 API의 `actor_user_id`(원문 사용자 UUID)가 GET 쿼리 문자열이라, **uvicorn 기본 접근 로그와 Nginx 기본 `combined` 로그에 원문으로 남습니다.** 인증 실패(401) 요청도 남습니다. 애플리케이션 로그에는 남지 않습니다. 근거: Dockerfile의 `uvicorn main:app`(접근 로그 옵션 없음), `nginx.conf`(`log_format`·`access_log` 지정 없음) | `test_finding_f1_uvicorn_access_log_records_the_query_string` (실제 서버), `test_finding_f1_deployment_config_still_logs_full_request_lines` (설정) | **예 — 별도 PR**(배포 설정, 승인 필요). 아래 개선안 |
| F-2 | Low | 감사 목록 cursor가 발급받은 관리자에 묶이지 않아, 다른 관리자가 이어서 볼 수 있습니다. 같은 권한이라 권한 상승은 없습니다. 일반 사용자·비로그인은 403·401 | `test_cursor_is_not_a_bearer_credential` | 선택 — cursor params에 사용자 ID 포함 검토(T84 후속) |
| F-3 | Low | `/health/db`가 공개라 DB 가용 여부(200/503)가 외부에 보입니다 | 경로 목록 `PUBLIC_ROUTES` | 선택 — Nginx에서 내부망 한정 검토 |
| (참고) | Info | admin 크롤러 경로·AI 사용량은 역할(admin)만 요구하고 권한 코드는 요구하지 않습니다. 확정 계약대로이며, 시험으로 현재 동작을 고정했습니다 | `test_admin_without_audit_permission_is_403_on_audit_events_only` | T84 D1 결정 대기 |

Critical 0, High 0, Medium 1, Low 2입니다. 고위험 권한 누출(인증 우회·관리자 데이터 노출·IDOR)은 0건입니다.

**F-1 개선안 (운영 미적용, 승인 후 별도 PR)**:
1. **uvicorn**: 접근 로그 필터로 쿼리 문자열을 지웁니다(`StripQueryFromAccessLog` 프로토타입 — 시험에서 동작 확인). 또는 `--no-access-log`로 끄고, 앱 쪽에서 경로·상태·`request_id`만 남기는 요청 로그를 씁니다.
2. **Nginx**: `log_format`에 `$request` 대신 `$request_method $uri $status`를 쓰고(`$args` 제외), `/api/v1/admin/` 위치에 그 형식을 적용합니다.
3. **계약 대안**: 사용자 ID 검색을 POST 본문으로 옮깁니다(T06·T84 결정).
4. **개선 후 회귀 시험**: `test_finding_f1_uvicorn_access_log_records_the_query_string`의 단정을 "포함하지 않음"으로 뒤집고, 설정 정적 검사를 "쿼리 제거 설정 있음"으로 바꿉니다. 이 시험은 그때까지 **현재 동작을 고정한 기록**이며, 수정되면 실패해서 갱신을 강제합니다.

T84 PR #186 보고서 §8에 기록된 같은 이슈입니다. 이번에는 재현 시험만 추가하고 중복 수정은 하지 않았습니다.

## 12. 심각도·재현 방법

```bash
cd backend
APP_ENV=test python -m pytest -q tests/security                               # DB 없는 시험 + F-1 재현
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/t16_profile_test \
  APP_ENV=test python -m pytest -q tests/security                             # PostgreSQL 포함
```

심각도 기준: Critical = 인증 우회·대량 개인정보 유출, High = 권한 상승·IDOR, Medium = 제한된 개인정보 노출(로그·내부 접근자), Low = 정보 노출·하드닝.

## 13. 수정 필요 여부

- 이번 PR: **Backend 업무 코드 수정 없음**(시험·문서만). 고위험 결함이 없어 수정 PR을 만들지 않았습니다.
- 후속 제안: F-1 배포 로그 설정 PR(승인 필요), F-2·F-3은 선택 사항입니다.

## 14. CI 적용 상태

- 새 Workflow는 만들지 않았습니다. 기존 Workflow가 `backend/tests/security`를 자동으로 수집합니다(`pytest.ini`의 `testpaths = tests`).
  - `ci.yml` "Backend pytest": DB 없는 시험. PG 시험은 skip(환경변수 없음).
  - `backend-tests.yml` "backend": postgres:18.1 서비스 + T16 가드 환경변수라 PG 시험까지 실행합니다.
- 보안 시험이 실패하면 해당 job이 실패합니다. merge 차단은 저장소 보호 규칙의 필수 검사 설정에 따릅니다. **제안: `backend`·`Backend pytest`를 필수 검사로 지정.**
- **CI 실행 증빙 (HEAD `4a10dd7`, PR #188)** — 5개 검사 모두 PASS:

| Job | 결과 | 해석 |
|---|---|---|
| `backend` (backend-tests.yml, postgres:18.1) | **1236 passed, 53 skipped** | 기준(T84 시점 812 passed / 53 skipped) 대비 +424 = `tests/security` 수집 424건 전부 실행·통과. skip 수가 같으므로 PG·업로드 보안 시험 skip 0 |
| `Backend pytest` (ci.yml, DB 없음) | 1063 passed, 226 skipped | +413 passed. +11 skipped = PG 시험 11개(DB 없는 job 에서 T16 가드로 skip — PG job 에서 실행) |
| `upload-e2e`, `offline-tests`, `CI Smoke Test` | PASS | 기존 |

- 첫 실행(`64a82de`)에서 업로드 시험 7건이 **실패**했습니다. 원인은 시험의 기대값(업로드 응답 201)이 T49 계약(202 Accepted, 검사 대기)과 달랐던 것입니다. 기대값만 고쳤고(`4a10dd7`), 보안 단정(404/422, 내용 미노출, 삭제 없음)은 그대로 두었습니다. 보안 결함이 아니었고, skip 처리하지 않았습니다.
- Skip으로 바꾼 보안 시험은 없습니다. PG·POSIX 의존 시험의 조건부 skip은 기존 T16 가드와 같습니다.

## 15. 시험에서 제외된 미구현 기능 (HOLD)

| 기능 | 이유 |
|---|---|
| T58 Agent 승인·실행·감사 API | 미착수 — 경로 없음 |
| T81 콘텐츠 검수 API | 계약만 — 경로 없음 (UI는 Mock) |
| 비밀번호 재설정 API | 계약에만 있고 구현되지 않음 |
| 운영 Nginx·uvicorn 로그 설정 검증 | 운영 설정 변경 금지 — 정적 확인·로컬 재현만 |
| Staging·운영 대상 침투 시험 | 금지 |

## 로컬 실행 결과 (Windows)

| 범위 | 결과 |
|---|---|
| `tests/security` (일회용 PG 포함) | **412 passed**, 12 errors = `test_security_upload.py`(POSIX 전용 저장소, 위 §5) — 이 12건은 Linux CI 에서 실행·PASS (§14) |
| 전체 Backend (일회용 PG, CI 환경변수) | 1206 passed, 53 skipped, 1 failed + 31 errors — 모두 문서 저장소 POSIX 의존(기존 20 + 신규 12). PASS로 세지 않음 |
| 게이트 변이 확인 | 누락 경로 추가 시 13건 실패 (확인 후 되돌림) |
