# API 계약서 v0.2

- 관련 일감: Redmine #1529 (T06)
- 작성자: 이상재
- 작성일: 2026-11-06
- 상태: 검토 중. 구현 전 계약이며 PM 승인 전입니다.
- 기준 문서: [OpenAPI 3.1 명세](api/openapi.yaml) (이 문서의 표는 명세에서 만들었습니다)
- 입력: [요구사항 정의서](requirements/README.md) (T04, main 반영), [데이터 사전](../database/DATA_DICTIONARY.md) (T05, main 반영), [Backend 골격](../backend/README.md) (T13)
- 요구사항은 바뀔 수 있습니다. 모든 API에 요구사항 ID(`x-requirements`)를 적고, 검사 스크립트가 매번 `docs/requirements`와 대조합니다.

## 1. 공통 규칙

### 1.1 기본

| 항목 | 규칙 |
|---|---|
| 기준 경로 | 외부에서 부르는 주소 기준. 업무 API는 `/api/v1`, 상태 확인은 `/api/health`, `/api/version`. Nginx가 `/api/`를 떼고 FastAPI로 넘기므로 앱 안의 경로는 `/health`, `/version`(T13 구현과 일치) |
| 형식 | JSON (UTF-8). 파일 업로드만 `multipart/form-data` |
| 식별자 | UUID 문자열. 직무·기술은 사람이 읽는 `code`도 함께 제공 |
| 시각 | ISO 8601, UTC로 저장·응답. 화면에서 한국 시간으로 변환 |
| 날짜 | `YYYY-MM-DD` |
| 부분 수정 | `PATCH`는 보낸 필드만 바꾼다. `null`을 보내면 값을 지운다 |
| 전체 교체 | `PUT`은 목록 전체를 보낸 값으로 바꾼다 (보유 기술, 목표 직무) |
| 문서 | FastAPI `/docs`, `/openapi.json`은 Staging에서만 연다 |

### 1.2 인증 — 자체 로그인 (요구사항 D-01)

| 항목 | 규칙 |
|---|---|
| 방식 | 이메일 + 비밀번호. 외부 로그인(IdP)은 1차에 쓰지 않는다 |
| 접근 토큰 | JWT, 15분. `Authorization: Bearer <token>` 헤더로 보낸다. 내용: `sub`(user_id), `sid`(세션), `roles` |
| 갱신 토큰 | 불투명 문자열, 14일. `refresh_token` 쿠키(`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`) |
| 회전 | `POST /auth/refresh`를 부를 때마다 새 갱신 토큰을 주고 이전 것은 즉시 무효. DB에는 해시만 저장 |
| 로그아웃 | 현재 세션 무효화 + 쿠키 삭제. 탈퇴 요청·비밀번호 변경 시 모든 세션 무효화 |
| 이메일 비교 | 가입 중복 검사와 로그인은 **비교용 이메일**로 한다: 앞뒤 공백 제거 → 소문자 → `@` 앞 `+` 이후 제거 → gmail.com·googlemail.com은 `@` 앞 `.` 제거, 도메인 `gmail.com`. 예: `crasnec+box@gmail.com` → `crasnec@gmail.com`. 응답의 `email`은 사용자가 입력한 원래 값 (FR-ACC-001·002) |
| 비밀번호 재설정 | `POST /auth/password-reset-requests`(항상 202) → 메일 링크(30분, 1회) → `POST /auth/password-resets`. 성공 시 모든 세션 종료 (FR-ACC-004) |
| 시도 제한 | 로그인·가입·재설정 요청은 계정·IP 기준으로 횟수를 제한하고 넘으면 429 |

선택 이유: 외부 로그인은 OAuth 앱 등록, 리디렉션 주소, Staging 도메인 설정이 필요해 팀이 로컬에서 바로 개발·테스트하기 어렵습니다. 자체 로그인은 T15 한 일감 안에서 끝낼 수 있고, 데이터 사전의 `auth_identities`(`provider='local'`)·`auth_sessions`로 그대로 저장됩니다. 외부 로그인은 `auth_identities`에 공급자를 추가하는 방식으로 나중에 붙일 수 있습니다.

### 1.3 권한과 소유권

- `/me`로 시작하는 API와 내 리소스 API(문서, 분석 결과, 추천 등)는 **토큰의 `sub`로만** 사용자를 정한다. 경로·본문·쿼리로 `user_id`를 받지 않는다.
- 다른 사람 리소스 ID로 요청하면 **404**로 응답한다. 존재 여부를 알리지 않기 위해 403을 쓰지 않는다.
- `/admin` API는 `admin` 역할이 없으면 **403**.
- 화면의 메뉴 노출(`GET /me/permissions`)과 별개로 서버는 매 요청 권한을 다시 확인한다.

### 1.4 오류

모든 오류는 `application/problem+json` 형식입니다.

```json
{
  "type": "https://docs.ai-career.invalid/problems/validation",
  "title": "Validation failed",
  "status": 422,
  "code": "VALIDATION_FAILED",
  "request_id": "req-9c0d",
  "errors": [{ "field": "items[0].proficiency", "code": "OUT_OF_RANGE" }]
}
```

- `code`: 화면이 분기에 쓰는 고정 코드(대문자). `title`·`detail`은 사람이 읽는 설명
- `request_id`: 오류 화면에 표시하고 감사 기록과 연결 (FR-CMN-004, FR-ADM-004)
- 비밀번호·토큰·이메일·문서 내용·스택트레이스는 넣지 않는다

| 상태 | 쓰는 경우 | 대표 code |
|---|---|---|
| 400 | 요청 형식은 맞지만 업무 규칙상 처리할 수 없음 | `NO_USER_SKILLS`, `NOT_A_TARGET_ROLE`, `INVALID_CURSOR`, `INVALID_RESET_TOKEN` |
| 401 | 토큰 없음·만료·위조, 로그인 실패 | `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS` |
| 403 | 로그인했지만 역할이 없음, 필요한 동의가 없음 | `FORBIDDEN`, `CONSENT_REQUIRED` |
| 404 | 없음, 또는 다른 사람 소유 | `NOT_FOUND` |
| 409 | 중복(비교용 이메일 기준 포함), 현재 상태와 충돌 | `EMAIL_TAKEN`, `DELETION_ALREADY_REQUESTED`, `DOCUMENT_NOT_READY`, `APPROVAL_CLOSED`, `LAST_ADMIN` |
| 413 | 파일 10MB 초과 | `FILE_TOO_LARGE` |
| 415 | PDF·DOCX가 아니거나 내용과 확장자가 다름 | `UNSUPPORTED_FILE_TYPE` |
| 422 | 필드 형식·범위 오류 (FastAPI 기본 422를 이 형식으로 바꿈) | `VALIDATION_FAILED`, `DUPLICATE_SKILL` |
| 429 | 요청 한도 초과. `Retry-After` 헤더 포함 | `RATE_LIMITED` |
| 503 | 계산·AI 의존 서비스 장애. 화면은 해당 영역만 오류 표시 | `DEPENDENCY_UNAVAILABLE` |
| 504 | 외부 AI 응답 시간 초과 | `DEPENDENCY_TIMEOUT` |

### 1.5 목록과 페이지

- 요청: `limit`(1~100, 기본 20), `cursor`(이전 응답의 `next_cursor`를 그대로)
- 응답: `{ "items": [...], "next_cursor": "..." }`. 마지막 페이지면 `next_cursor: null`
- 정렬은 API마다 정한 값만 허용. 같은 조건이면 항상 같은 순서(정렬키 + id)
- cursor를 바꾸거나 오래돼서 해석할 수 없으면 400 `INVALID_CURSOR`

### 1.6 비동기 작업 (202)

오래 걸리는 작업만 202를 쓰고, 나머지는 바로 결과를 돌려줍니다.

| 구분 | API | 응답 |
|---|---|---|
| 동기 | 적합도, Skill Gap, 추천 (1차 규칙 기반, 3초 이내) | 201 + 결과 |
| 동기 | 커리어 Q&A (30초 초과 시 504) | 200 + 답변 |
| 비동기 | 문서 업로드 검사, 문서 분석, 문서 삭제, 탈퇴 요청, AI 작업 | 202 + 리소스(`status` 포함) + `Location` + `Retry-After` |

- 별도 "작업(task)" 리소스를 만들지 않고, **리소스 자체의 `status`**로 진행 상태를 알린다. 클라이언트는 `Location`의 리소스를 `Retry-After` 초 간격으로 조회한다.
- 상태 값은 데이터 사전의 CHECK 값과 같다: 문서 `uploaded → scanning → ready | rejected`, 분석 `queued → running → succeeded | failed`, AI 작업 `queued → running → awaiting_approval → succeeded | failed | rejected | timed_out`.

### 1.7 멱등성

- `PUT`·`DELETE`는 여러 번 보내도 결과가 같다 (예: 공고 저장 `PUT /me/bookmarks/{id}`는 이미 저장돼 있어도 204).
- AI 작업 시작은 `Idempotency-Key` 헤더가 필수. 같은 키로 다시 보내면 새로 실행하지 않고 기존 실행을 200으로 돌려준다.

### 1.8 동의 변경 (FR-ACC-006)

- 가입 때는 모든 정책에 동의를 받는다 (`SignupRequest.consents`).
- 가입 후 `POST /me/consents`는 **선택 항목만** 받는다 (`OptionalConsentInput`: `llm_processing`, `behavior_tracking`). 필수 항목은 응답의 `is_required: true`로 표시해 화면에 변경 버튼을 두지 않는다.

### 1.9 파일 업로드·내려받기 (NFR-SEC-003)

- 파일은 API 서버와 분리된 파일 저장소에 **실행 권한 없이**, 서버가 만든 **무작위 이름**(128비트 이상)으로 저장한다. 사용자가 올린 파일 이름은 화면 표시용으로만 쓴다.
- 응답에는 저장 위치·저장 이름을 넣지 않는다. 내려받기는 `GET /documents/{id}/file`로만 하며, 서버가 소유권을 확인한 뒤 `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`로 보낸다.

### 1.10 분석 결과 표시 (NFR-AIQ-001)

- 점수는 0~100이며 `score_is_probability: false`를 항상 포함한다.
- 모든 분석 결과에 `model_version`(계산 기준)과 계산 시각, 한계(`limitations`)를 포함한다.

## 2. API 목록

인증 열: `없음` 로그인 불필요 · `선택` 로그인하면 추가 정보 · `필요` 로그인 필수 · `관리자` admin 역할 필수.

### 2.1 인증·약관

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/signup` | 이메일 가입 + 필수 약관 동의 | FR-ACC-001, FR-ACC-006 | UI-001 | 없음 | 201 |
| `POST` | `/api/v1/auth/login` | 이메일·비밀번호 로그인 | FR-ACC-002 | UI-001 | 없음 | 200 |
| `POST` | `/api/v1/auth/refresh` | refresh 쿠키로 access token 재발급 (refresh 회전) | FR-ACC-003, NFR-SEC-001 | UI-C01 | refresh 쿠키 | 200 |
| `POST` | `/api/v1/auth/logout` | 현재 세션 폐기 | FR-ACC-003 | UI-002, UI-C02 | refresh 쿠키 | 204 |
| `POST` | `/api/v1/auth/password-reset-requests` | 비밀번호 재설정 메일 요청 | FR-ACC-004 | UI-N03 | 없음 | 202 |
| `POST` | `/api/v1/auth/password-resets` | 메일 링크의 토큰으로 새 비밀번호 설정 (모든 세션 종료) | FR-ACC-004, NFR-SEC-001 | UI-N03 | 없음 | 204 |
| `GET` | `/api/v1/consent-policies` | 현재 시행 중인 약관·처리방침 목록 | FR-ACC-006, FR-CMN-003 | UI-001, UI-005, UI-N04 | 없음 | 200 |

### 2.2 내 계정·역량

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/me` | 내 계정·프로필 | FR-ACC-005 | UI-003, UI-N02, UI-C02 | 필요 | 200 |
| `PATCH` | `/api/v1/me` | 내 프로필 수정 (보낸 필드만 변경, null은 지움) | FR-ACC-005, FR-CMN-002 | UI-003, UI-N02 | 필요 | 200 |
| `GET` | `/api/v1/me/permissions` | 내 역할·권한 (메뉴 노출용. 서버는 매 요청 다시 검사) | FR-ADM-001, FR-CMN-003 | UI-C02, UI-C01 | 필요 | 200 |
| `GET` | `/api/v1/me/sessions` | 로그인된 기기 목록 | FR-ACC-003 | UI-002 | 필요 | 200 |
| `DELETE` | `/api/v1/me/sessions/{session_id}` | 다른 기기 로그아웃 | FR-ACC-003 | UI-002 | 필요 | 204 |
| `GET` | `/api/v1/me/consents` | 정책별 현재 동의 상태와 이력 | FR-ACC-006 | UI-005 | 필요 | 200 |
| `POST` | `/api/v1/me/consents` | 선택 항목 동의·철회 기록 (이력 추가) | FR-ACC-006 | UI-005 | 필요 | 201 |
| `GET` | `/api/v1/me/deletion-request` | 진행 중인 탈퇴 요청 | FR-ACC-007 | UI-005 | 필요 | 200 |
| `POST` | `/api/v1/me/deletion-request` | 탈퇴 요청 (즉시 비활성화, 예정일에 삭제) | FR-ACC-007 | UI-005 | 필요 | 202 |
| `DELETE` | `/api/v1/me/deletion-request` | 탈퇴 요청 취소 (삭제 예정일 전까지) | FR-ACC-007 | UI-005 | 필요 | 204 |
| `GET` | `/api/v1/me/dashboard` | 로그인 후 홈 요약 (FR-CMN-001) | FR-CMN-001 | UI-N01 | 필요 | 200 |
| `GET` | `/api/v1/me/skills` | 내 보유 기술 | FR-PRF-001 | UI-008, UI-N02 | 필요 | 200 |
| `PUT` | `/api/v1/me/skills` | 보유 기술 전체 교체 | FR-PRF-001, FR-CMN-002 | UI-008, UI-N02 | 필요 | 200 |
| `GET` | `/api/v1/me/target-roles` | 내 목표 직무 (최대 3개) | FR-PRF-002 | UI-009, UI-N02, UI-N01 | 필요 | 200 |
| `PUT` | `/api/v1/me/target-roles` | 목표 직무 전체 교체 | FR-PRF-002, FR-CMN-002 | UI-009, UI-006, UI-N02 | 필요 | 200 |
| `GET` | `/api/v1/me/experiences` | 경력 목록 | FR-PRF-003 | UI-010 | 필요 | 200 |
| `POST` | `/api/v1/me/experiences` | 경력 추가 | FR-PRF-003 | UI-010 | 필요 | 201 |
| `PATCH` | `/api/v1/me/experiences/{experience_id}` | 경력 수정 | FR-PRF-003 | UI-010 | 필요 | 200 |
| `DELETE` | `/api/v1/me/experiences/{experience_id}` | 경력 삭제 | FR-PRF-003 | UI-010 | 필요 | 204 |
| `GET` | `/api/v1/me/projects` | 프로젝트 목록 (사용 기술 포함) | FR-PRF-004 | UI-010 | 필요 | 200 |
| `POST` | `/api/v1/me/projects` | 프로젝트 추가 | FR-PRF-004 | UI-010 | 필요 | 201 |
| `PATCH` | `/api/v1/me/projects/{project_id}` | 프로젝트 수정 (skill_ids를 보내면 전체 교체) | FR-PRF-004 | UI-010 | 필요 | 200 |
| `DELETE` | `/api/v1/me/projects/{project_id}` | 프로젝트 삭제 | FR-PRF-004 | UI-010 | 필요 | 204 |
| `GET` | `/api/v1/me/bookmarks` | 저장한 공고 (최근 저장 순) | FR-JOB-007 | UI-013 | 필요 | 200 |
| `PUT` | `/api/v1/me/bookmarks/{job_posting_id}` | 공고 저장 (멱등) | FR-JOB-007 | UI-012, UI-013 | 필요 | 204 |
| `DELETE` | `/api/v1/me/bookmarks/{job_posting_id}` | 저장 해제 (멱등) | FR-JOB-007 | UI-012, UI-013 | 필요 | 204 |

### 2.3 직무·기술·기업·공고

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/job-roles` | 직무 목록·검색 | FR-JOB-001 | UI-006, UI-009 | 선택 | 200 |
| `GET` | `/api/v1/job-roles/{job_role_id}` | 직무 상세 (요구 기술 포함) | FR-JOB-002 | UI-006, UI-016 | 선택 | 200 |
| `GET` | `/api/v1/skills` | 기술 검색·자동완성 (2글자 이상) | FR-JOB-003 | UI-007, UI-008, UI-010 | 선택 | 200 |
| `GET` | `/api/v1/companies` | 기업 목록·검색 | FR-JOB-004 | UI-011 | 선택 | 200 |
| `GET` | `/api/v1/companies/{company_id}` | 기업 상세 (진행 중 공고 수 포함) | FR-JOB-004 | UI-011 | 선택 | 200 |
| `GET` | `/api/v1/job-postings` | 채용공고 목록·필터 (기본은 게시 중인 공고만) | FR-JOB-005 | UI-012, UI-011 | 선택 | 200 |
| `GET` | `/api/v1/job-postings/{job_posting_id}` | 공고 상세 (요구 기술, 로그인 시 내 저장 여부) | FR-JOB-006 | UI-012, UI-015 | 선택 | 200 |

### 2.4 분석·추천

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/matches` | 공고 또는 직무 하나에 대한 적합도 계산 (규칙 기반, 동기) | FR-ANL-001 | UI-015, UI-012 | 필요 | 201 |
| `GET` | `/api/v1/matches/{match_id}` | 적합도 결과 조회 | FR-ANL-001 | UI-015 | 필요 | 200 |
| `GET` | `/api/v1/skill-gaps` | 내 Skill Gap 이력 (최신 순) | FR-ANL-002 | UI-016, UI-N01 | 필요 | 200 |
| `POST` | `/api/v1/skill-gaps` | 목표 직무 기준 Skill Gap 계산 (규칙 기반, 동기) | FR-ANL-002 | UI-016 | 필요 | 201 |
| `GET` | `/api/v1/skill-gaps/{assessment_id}` | Skill Gap 결과 (is_stale=true면 이후 기술·목표가 바뀜) | FR-ANL-002 | UI-016 | 필요 | 200 |
| `POST` | `/api/v1/recommendation-runs` | 맞춤 공고 추천 생성 (규칙 기반, 동기. 실패 시 최신 공고로 대체) | FR-ANL-003 | UI-017 | 필요 | 201 |
| `GET` | `/api/v1/recommendation-runs/latest` | 가장 최근 추천 (없으면 404 → 화면에서 생성 버튼) | FR-ANL-003 | UI-017, UI-N01 | 필요 | 200 |
| `GET` | `/api/v1/recommendation-runs/{recommendation_run_id}` | 추천 결과 조회 | FR-ANL-003, FR-ANL-004 | UI-017 | 필요 | 200 |
| `POST` | `/api/v1/recommendation-feedback` | 추천 공고 피드백 (이력 추가) | FR-ANL-004 | UI-017 | 필요 | 201 |
| `GET` | `/api/v1/market-trends` | 채용시장 지표 관측값 + 예측값 | FR-ANL-005 | UI-024 | 필요 | 200 |

### 2.5 문서·AI

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/documents` | 내 문서 목록 | FR-AI-001 | UI-019 | 필요 | 200 |
| `POST` | `/api/v1/documents` | 문서 업로드 (검사는 비동기) | FR-AI-001, NFR-SEC-003 | UI-019 | 필요 | 202 |
| `GET` | `/api/v1/documents/{document_id}` | 문서 상태 (업로드 검사 폴링 대상) | FR-AI-001 | UI-019, UI-020 | 필요 | 200 |
| `DELETE` | `/api/v1/documents/{document_id}` | 문서 삭제 (원본·분석·검색 색인까지, 비동기) | FR-AI-001 | UI-019 | 필요 | 202 |
| `GET` | `/api/v1/documents/{document_id}/file` | 원본 파일 내려받기 (서버가 소유권 확인 후 저장소에서 읽어 전달) | FR-AI-001, NFR-SEC-003 | UI-019 | 필요 | 200 |
| `POST` | `/api/v1/documents/{document_id}/analyses` | LLM 문서 분석 요청 (비동기, llm_processing 동의 필요) | FR-AI-002 | UI-020 | 필요 | 202 |
| `GET` | `/api/v1/document-analyses/{analysis_id}` | 분석 상태·결과 (폴링) | FR-AI-002 | UI-020 | 필요 | 200 |
| `POST` | `/api/v1/document-analyses/{analysis_id}/apply` | 분석 결과 중 사용자가 고른 기술만 내 기술에 반영 (자동 반영 금지) | FR-AI-002 | UI-020 | 필요 | 200 |
| `POST` | `/api/v1/knowledge/answers` | 근거 기반 커리어 Q&A (내 문서 + 공용 자료, 동기) | FR-AI-003 | UI-022 | 필요 | 200 |

### 2.6 AI 작업

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/agent-runs` | 내 Agent 실행 내역 | FR-AI-004 | UI-023 | 필요 | 200 |
| `POST` | `/api/v1/agent-runs` | Agent 작업 시작 (비동기, Idempotency-Key 필수) | FR-AI-004 | UI-023 | 필요 | 202,200 |
| `GET` | `/api/v1/agent-runs/{agent_run_id}` | 실행 상태·승인 요청·도구 호출 요약 (폴링) | FR-AI-004 | UI-023 | 필요 | 200 |
| `POST` | `/api/v1/agent-runs/{agent_run_id}/approvals/{approval_id}` | 도구 실행 승인·거절 (실행 소유자만) | FR-AI-004 | UI-023 | 필요 | 200 |

### 2.7 운영 관리

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `PUT` | `/api/v1/admin/users/{user_id}/roles/{role_code}` | 역할 부여 (멱등, 감사 기록) | FR-ADM-002 | UI-028 | 관리자 | 204 |
| `DELETE` | `/api/v1/admin/users/{user_id}/roles/{role_code}` | 역할 회수 (즉시 반영, 감사 기록) | FR-ADM-002 | UI-028 | 관리자 | 204 |
| `GET` | `/api/v1/admin/segments` | 사용자 세그먼트 집계 (개인 식별 없음) | FR-ADM-006 | UI-025 | 관리자 | 200 |
| `GET` | `/api/v1/admin/anomalies` | 이상 이벤트 목록 | FR-ADM-006 | UI-025 | 관리자 | 200 |
| `PATCH` | `/api/v1/admin/anomalies/{anomaly_id}` | 이상 이벤트 상태 변경 (오탐·해결) | FR-ADM-006 | UI-025 | 관리자 | 200 |
| `GET` | `/api/v1/admin/models` | 규칙·모델 버전 목록 | FR-ADM-003 | UI-026 | 관리자 | 200 |
| `GET` | `/api/v1/admin/models/{model_version_id}/evaluations` | 버전별 평가 지표 | FR-ADM-003 | UI-026 | 관리자 | 200 |
| `GET` | `/api/v1/admin/audit-events` | 감사 기록 조회 (읽기 전용) | FR-ADM-004 | UI-028 | 관리자 | 200 |
| `GET` | `/api/v1/admin/ai-usage` | AI 사용량·추정 비용 합계 | FR-ADM-005 | UI-028 | 관리자 | 200 |

### 2.8 상태 확인

| 메서드 | 경로 | 설명 | 요구사항 | 화면 | 인증 | 성공 |
|---|---|---|---|---|---|---|
| `GET` | `/api/health` | 상태 확인. 실제 경로는 `/api/health` (servers의 /api/v1 미적용) | NFR-AVL-002 | — | 없음 | 200 |
| `GET` | `/api/version` | 배포 버전. 실제 경로는 `/api/version` | NFR-AVL-002 | — | 없음 | 200 |

## 3. DTO 목록

요청·응답 스키마 전체입니다. 필드별 타입·범위는 [openapi.yaml](api/openapi.yaml)의 `components.schemas`를 보세요.

| DTO | 타입 | 필수 필드 | 설명 |
|---|---|---|---|
| `Problem` | object | type, title, status, code, request_id | RFC 9457 problem details + code/request_id. 이메일·토큰·스택트레이스·프롬프트는 넣지 않음 |
| `Uuid` | string | — |  |
| `Timestamp` | string | — |  |
| `NextCursor` | ['string', 'null'] | — | null이면 마지막 페이지 |
| `Password` | string | — | 10자 이상. 서버는 해시(Argon2id 권장, T15)만 저장 |
| `SignupRequest` | object | email, password, display_name, consents |  |
| `LoginRequest` | object | email, password |  |
| `TokenResponse` | object | access_token, token_type, expires_in |  |
| `Session` | object | session_id, created_at, expires_at, is_current |  |
| `Profile` | object | headline, bio, location_text |  |
| `Me` | object | user_id, email, display_name, status, profile, created_at |  |
| `MePatch` | object | — | 보낸 필드만 변경. null을 보내면 값을 지움 (display_name은 null 불가). 이메일 변경은 1차 범위 밖 |
| `Permissions` | object | roles, permissions |  |
| `ConsentPolicy` | object | policy_code, version, is_required, content_url, effective_at |  |
| `ConsentInput` | object | policy_code, policy_version, granted |  |
| `OptionalConsentInput` | object | policy_code, policy_version, granted | 가입 후 바꿀 수 있는 선택 항목만 (FR-ACC-006) |
| `PasswordResetRequest` | object | email |  |
| `PasswordReset` | object | token, new_password |  |
| `Consent` | object | consent_id, is_required, policy_code, policy_version, granted, recorded_at |  |
| `DeletionRequestInput` | object | confirmation |  |
| `DeletionRequest` | object | request_id, status, requested_at, scheduled_purge_at, completed_at |  |
| `Dashboard` | object | profile_completeness, next_actions, target_roles, latest_skill_gap, top_recommendations |  |
| `Skill` | object | skill_id, code, name |  |
| `Level` | integer | — | 1 입문 · 2 기초 · 3 실무 가능 · 4 능숙 · 5 전문가 (T05 공통 척도, 화면에 단계 설명 표시) |
| `JobRoleRef` | object | job_role_id, code, name |  |
| `JobRolePage` | object | items, next_cursor |  |
| `RequiredSkill` | object | skill, required_level |  |
| `JobRoleDetail` | object | job_role_id, code, name, description, required_skills |  |
| `CompanyRef` | object | company_id, name |  |
| `CompanyPage` | object | items, next_cursor |  |
| `CompanyDetail` | object | company_id, name, website_url, description, open_posting_count, source |  |
| `JobPostingSummary` | object | job_posting_id, title, status, company, job_role, employment_type, location_text, published_at, expires_at |  |
| `JobPostingPage` | object | items, next_cursor |  |
| `JobPostingDetail` | allOf | — |  |
| `UserSkill` | object | skill, proficiency |  |
| `UserSkillsReplace` | object | items |  |
| `TargetRole` | object | job_role, priority |  |
| `TargetRolesReplace` | object | items |  |
| `ExperienceInput` | object | organization, title |  |
| `ExperiencePatch` | object | — |  |
| `Experience` | object | experience_id, organization, title, start_date, end_date, description, updated_at |  |
| `ProjectInput` | object | title |  |
| `ProjectPatch` | object | — |  |
| `Project` | object | project_id, title, summary, start_date, end_date, skills, updated_at |  |
| `ModelVersionRef` | object | model_code, version, kind | 결과 계산 기준. 화면에 "계산 기준" 으로 표시 |
| `Score` | number | — | 0~100 적합 점수. **확률이 아니며** 화면에 확률로 표시하지 않음 (E2) |
| `MatchRequest` | object | — | job_posting_id와 job_role_id 중 정확히 하나 |
| `Match` | object | match_id, target, status, score, score_is_probability, matched_skill_count, missing_skill_count, model_version, limitations, evaluated_at |  |
| `SkillGapRequest` | object | job_role_id |  |
| `SkillGapItem` | object | skill, required_level, observed_level, gap |  |
| `SkillGap` | object | assessment_id, job_role, model_version, is_stale, evaluated_at, items |  |
| `SkillGapSummary` | object | assessment_id, job_role, missing_skill_count, total_gap, is_stale, evaluated_at |  |
| `SkillGapSummaryPage` | object | items, next_cursor |  |
| `RecommendationRunRequest` | object | — |  |
| `RecommendationItem` | object | rank, score, reason, feedback, job_posting |  |
| `RecommendationRun` | object | recommendation_run_id, status, model_version, generated_at, items |  |
| `RecommendationFeedbackInput` | object | job_posting_id, feedback |  |
| `RecommendationFeedback` | object | feedback_id, job_posting_id, feedback, created_at |  |
| `DocumentUpload` | object | file, kind |  |
| `Document` | object | document_id, kind, original_filename, mime_type, size_bytes, status, created_at | storage_key·checksum은 응답에 넣지 않음 |
| `DocumentPage` | object | items, next_cursor |  |
| `AnalysisRequest` | object | analysis_type |  |
| `AnalysisResult` | object | — |  |
| `Analysis` | object | analysis_id, document_id, analysis_type, status, result, error_code, model_version, requested_at, completed_at |  |
| `AnalysisApply` | object | skills |  |
| `KnowledgeQuestion` | object | question |  |
| `Citation` | object | rank, document_id, document_title, chunk_index, score |  |
| `KnowledgeAnswer` | object | retrieval_run_id, status, answer, citations, limitations |  |
| `AgentRunRequest` | object | workflow_code |  |
| `Approval` | object | approval_id, tool_code, decision, expires_at |  |
| `ApprovalDecision` | object | decision |  |
| `ToolCall` | object | tool_code, status, started_at |  |
| `AgentRun` | object | agent_run_id, workflow_code, status, started_at, ended_at, approvals, tool_calls |  |
| `AgentRunPage` | object | items, next_cursor |  |
| `MarketPoint` | object | date, value |  |
| `MarketTrend` | object | metric_code, period, source, observations, forecasts, forecast_model |  |
| `SegmentAggregate` | object | segment_code, label, user_count, model_version |  |
| `Anomaly` | object | anomaly_id, score, status, detected_at, model_version |  |
| `AnomalyPage` | object | items, next_cursor |  |
| `ModelVersion` | object | model_version_id, model_code, version, kind, description, approved_at, created_at |  |
| `ModelVersionPage` | object | items, next_cursor |  |
| `ModelEvaluation` | object | model_evaluation_id, dataset_ref, metric_code, metric_value, leakage_checked, evaluated_at |  |
| `AuditEvent` | object | audit_event_id, actor_user_id, action_code, resource_type, resource_id, request_id, occurred_at |  |
| `AuditEventPage` | object | items, next_cursor |  |
| `AiUsageBucket` | object | key, input_tokens, output_tokens, estimated_cost_usd, request_count |  |

## 4. 추적 결과

`python3 docs/api/check_openapi.py` 결과 (2026-11-06, main의 T04·T05 기준):

| 대상 | 연결 | 연결하지 않은 항목과 이유 |
|---|---|---|
| 기능 요구사항 | 36/37 | FR-CMN-004 공통 상태 화면: 별도 API 없이 모든 API의 공통 오류 형식으로 충족 |
| 화면 | 29/29 | — |
| 테이블 | 48/51 | `job_posting_external_refs`, `ingestion_runs`: 외부 공고 수집 배치 전용 (T62~T64) · `behavior_events`: 수집 API는 이벤트 계약 후 추가 (T71·T72) |

위 예외 목록은 검사 스크립트에 이유와 함께 들어 있으며, 예외가 아닌 항목이 빠지거나 요구사항 문서에 없는 ID를 쓰면 검사가 실패합니다.

## 5. v0.1 대비 변경

| v0.1 | v0.2 | 이유 |
|---|---|---|
| `POST /auth/login` + `GET /auth/callback` (방식 미정) | `POST /auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/logout` | 자체 로그인으로 결정 (D-01) |
| `POST /me/deletion-requests` | `GET·POST·DELETE /me/deletion-request` | 사용자당 진행 중 요청은 1개. 취소 기능 추가 |
| `POST /matches/evaluate` | `POST /matches` | 결과 리소스를 만들고 `GET /matches/{id}`로 다시 조회 |
| `POST /skill-gaps/analyze` | `POST /skill-gaps`, `GET /skill-gaps` | 같은 이유 + 이력 조회 |
| `GET /recommendations/jobs` | `POST /recommendation-runs`, `GET /recommendation-runs/latest` | 조회(GET)가 계산을 일으키지 않게 분리 |
| `POST /recommendations/{run_id}/feedback` | `POST /recommendation-feedback` | 피드백 이력 테이블(T05)과 맞춤 |
| `POST /knowledge/search` (공개) | 내부 기능 | FR-AI-003: 검색과 답변을 한 기능으로 |
| `POST /knowledge/answer` | `POST /knowledge/answers` | 리소스 이름 복수형 통일 |
| `POST /document-analyses` | `POST /documents/{id}/analyses` + `POST /document-analyses/{id}/apply` | 문서 소유 확인을 경로에서, 사용자 선택 반영 추가 |
| `GET /insights` | `GET /admin/segments`, `/admin/anomalies` | 관리자 전용 (FR-ADM-006) |
| `GET·POST /admin/reviews` | 삭제 | 운영 콘텐츠 검수 1차 제외 |
| (없음) | `/me/sessions`, `/me/dashboard`, `/consent-policies`, `/me/projects/{id}`, `/admin/users/{id}/roles/{code}`, `/auth/password-reset-requests`, `/auth/password-resets`, `/documents/{id}/file` | 새 요구사항(FR-ACC-003·004, FR-CMN-001, FR-CMN-003, FR-PRF-004, FR-ADM-002, NFR-SEC-003) |

## 6. 검증 방법

```bash
pip install openapi-spec-validator jsonschema pyyaml
python3 docs/api/check_openapi.py                    # 문법·참조·예시·규칙·추적 검사 (docs/requirements 필요)
python3 -B -m unittest docs/api/test_check_openapi.py -v   # 검사 스크립트 자체 테스트 (오류 탐지 7건)
```

| 검사 | 결과 |
|---|---|
| OpenAPI 3.1 문법·$ref | PASS (operation 74개, 스키마 85개) |
| 예시(mock) ↔ 스키마 | 173개 모두 PASS |
| 공통 규칙 | 오류 응답 problem+json, 로그인 필요 API의 401, 관리자 API의 403, `/me`의 user_id 금지, 경로 변수 선언 — 모두 PASS |
| 추적 | 요구사항 36/37, 화면 29/29, 테이블 48/51 (예외 이유 §4) |
| 단위 테스트 | 8개 OK (정상 1 + 오류 탐지 7) |

현재 CI(`ci.yml`)는 이 검사를 실행하지 않습니다 → `T06_STATUS=PARTIAL`.

## 7. 미결정 사항

| ID | 내용 | 영향 |
|---|---|---|
| D-03 | 비로그인 조회 범위 | 직무·기술·기업·공고 API의 인증 `선택` |
| D-09 | 1차 AI 작업 목록 (`summarize_target_postings` 1종 제안) | `AgentRunRequest.workflow_code` |
| D-10 | 메일 발송 수단 | 재설정 메일 발송 구현 (API 계약은 확정) |
| T06-1 | JWT 서명 방식 (HS256 / RS256) | T15 |
| T06-2 | 요청 한도 수치 (로그인·AI) | T15, T110 |
| T06-3 | 로그인 상태에서 공고 목록에 저장 여부 포함할지 | `JobPostingSummary` |
| T06-4 | **경로 접두사 불일치**: T13 골격은 앱 안에서 `API_V1_PREFIX="/api/v1"`을 쓰지만, Staging Nginx는 `/api/`를 떼고 넘긴다. 그대로 배포하면 외부 `/api/v1/auth/login`이 앱에 `/v1/auth/login`으로 도착해 404 | T13·T30 담당과 결정: 앱 접두사를 `/v1`로 바꾸거나 Nginx가 `/api/v1`은 그대로 넘기도록 변경. 외부 주소(이 계약)는 바뀌지 않음 |
