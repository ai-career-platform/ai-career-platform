# AI Career Platform — 데이터 사전 v0.2

> **상태:** `DRAFT / PM·DB 리뷰 대기 / DDL 미적용` · 작성일 2026-11-06 · T05 (Redmine #1521) · 작성 이상재(`sangjae-lee97`)
> **입력:** [요구사항 정의서](../docs/requirements/README.md) (T04 기준선) · [S03 v0.1](FULL_DATABASE_MODEL.md) · [S04 API 계약](../docs/API_CONTRACT.md) · [DRAFT_0001](migrations/DRAFT_0001_initial_schema.sql)
> **이 문서가 기준(source of truth)입니다.** [ERD](ERD.md)와 검증용 DDL은 `python3 database/model/check_data_dictionary.py`가 이 문서를 읽어 만듭니다. 표 형식을 바꾸면 스크립트가 실패합니다.
> **주의:** 이 사전으로 Staging에 DDL을 적용하지 않습니다. 실제 Migration SQL은 T08·T09에서 작성합니다.

## 0. 표기 규칙

- **스키마:** 모든 테이블은 `career` 스키마. 아래에서는 스키마 이름을 생략합니다.
- **NULL 열:** `N` = NOT NULL, `Y` = NULL 허용.
- **키·참조 열:** `PK`(여러 컬럼이면 복합 PK) · `UQ`(단일 컬럼 유일) · `FK → 테이블.컬럼 (삭제 동작)`. 삭제 동작은 `RESTRICT` / `CASCADE` / `SET NULL`.
- **제약 / 인덱스:** 표 아래 목록의 백틱 안 SQL 조각을 그대로 검증 DDL에 씁니다. 인덱스는 `(컬럼, ...)` 또는 `UNIQUE (컬럼, ...)` 형식, 부분 인덱스는 뒤에 `WHERE ...`.
- **데이터 등급:**
  - `PUBLIC` 비로그인 공개 가능한 기준 데이터
  - `INTERNAL` 운영·모델 메타데이터 (외부 비공개, 개인 식별 없음)
  - `PERSONAL` 특정 사용자에 연결된 데이터 (본인·권한자만)
  - `SENSITIVE` 인증 비밀값 해시, 문서·질의 원문 참조 등 노출 시 피해가 큰 데이터
- **보존:** 회원 탈퇴는 `account_deletion_requests` 처리로 진행합니다. 제안값(요구사항 D-06, NFR-PRV-002): 요청 즉시 `users.status='disabled'`, 30일 후 `users` 행 삭제 → `CASCADE` 대상 개인 데이터 함께 삭제, 감사·비용 기록은 `SET NULL`로 익명화. **D-06 승인 전까지 가안입니다.**
- **공통 컬럼:** 변경 가능한 행은 `created_at`, `updated_at`(`timestamptz NOT NULL DEFAULT now()`), 추가만 하는 기록 행은 `created_at` 또는 발생 시각 하나만 둡니다. `updated_at` 갱신은 애플리케이션 책임(트리거 미사용, T09에서 재검토).
- **PK:** 엔터티는 `uuid DEFAULT gen_random_uuid()`, 연결 테이블은 복합 PK.
- **상태 코드:** `varchar` + `CHECK (... IN (...))`. PostgreSQL ENUM 타입은 값 추가 시 Migration 부담 때문에 쓰지 않습니다.

---

## A. 계정·인증·권한

### A01 `users`
- 요구사항: FR-ACC-001, FR-ACC-002, FR-ACC-003, FR-ACC-005, FR-ACC-007, FR-CMN-002
- 데이터 등급: PERSONAL · 보존: 탈퇴 처리 완료 시 행 삭제 · DRAFT_0001: 있음 (**`email_canonical` 추가, 유일성 기준 변경**)
- 결정 반영: FR-ACC-001 수용 기준 2~4 — 중복 검사·로그인은 **비교용 이메일**(`email_canonical`)로 한다. 만드는 규칙(애플리케이션): 앞뒤 공백 제거 → 소문자 → `@` 앞부분의 `+` 이후 제거 → `gmail.com`·`googlemail.com`이면 `@` 앞부분의 `.` 제거 후 도메인을 `gmail.com`으로. 사용자가 입력한 `email`은 연락용으로 그대로 둔다.

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | gen_random_uuid() | PK | 내부 식별자. 토큰·권한 검사를 대체하지 않음 |
| email | varchar(254) | N | | | 사용자가 입력한 이메일 (앞뒤 공백만 제거). 연락·표시용 |
| email_canonical | varchar(254) | N | | | 비교용 이메일. 중복 검사·로그인 조회 기준. 예: `crasnec+box@gmail.com` → `crasnec@gmail.com` |
| display_name | varchar(100) | N | | | 화면 표시 이름 |
| status | varchar(20) | N | 'active' | | `active` / `disabled`(탈퇴 요청·관리자 정지) |
| last_login_at | timestamptz | Y | | | 마지막 로그인 시각 |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (status IN ('active', 'disabled'))`
- `CHECK (length(btrim(email)) > 0 AND email = btrim(email))`
- `CHECK (email_canonical = lower(email_canonical) AND position('+' in split_part(email_canonical, '@', 1)) = 0)`

인덱스:
- `UNIQUE (email_canonical)`

### A02 `user_profiles`
- 요구사항: FR-ACC-005, FR-CMN-001, FR-CMN-002
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 있음 (FK 삭제 동작 RESTRICT → CASCADE)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | 1:1 |
| headline | varchar(200) | Y | | | 한 줄 소개 |
| bio | text | Y | | | 자기소개 |
| location_text | varchar(120) | Y | | | 희망·거주 지역 (자유 입력) |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (bio IS NULL OR length(bio) <= 5000)`

### A03 `auth_identities`
- 요구사항: FR-ACC-001, FR-ACC-002, NFR-SEC-001
- 데이터 등급: SENSITIVE · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음 (신규)
- 결정 반영: 자체 로그인(요구사항 D-01). 1차는 `provider='local'` 한 행. 외부 로그인을 붙이면 공급자 행을 추가

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| identity_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| provider | varchar(40) | N | | | `local`, `google` 등 |
| subject | varchar(255) | N | | | 공급자 측 사용자 ID. `local`이면 `users.email_canonical`과 같은 값 |
| password_hash | text | Y | | | `provider='local'`일 때만. 원문 비밀번호 저장 금지 |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (provider = 'local' OR password_hash IS NULL)`

인덱스:
- `UNIQUE (provider, subject)`
- `(user_id)`

### A04 `auth_sessions`
- 요구사항: FR-ACC-002, FR-ACC-003, FR-ACC-007, NFR-SEC-001
- 데이터 등급: SENSITIVE · 보존: 만료·폐기 후 30일 뒤 삭제 (배치) · DRAFT_0001: 없음 (신규)
- 조건: 자체 세션·refresh 토큰을 쓸 때만 필요 (D-01)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| session_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| refresh_token_hash | char(64) | N | | | SHA-256 해시만 저장. 원문 토큰 저장 금지 |
| user_agent | varchar(300) | Y | | | 기기 표시용 |
| created_at | timestamptz | N | now() | | |
| expires_at | timestamptz | N | | | |
| revoked_at | timestamptz | Y | | | 로그아웃·강제 만료 시각 |

제약:
- `CHECK (expires_at > created_at)`

인덱스:
- `UNIQUE (refresh_token_hash)`
- `(user_id) WHERE revoked_at IS NULL`

### A05 `roles`
- 요구사항: FR-ADM-001, FR-ADM-002, FR-CMN-003
- 데이터 등급: INTERNAL · 보존: 영구 (Seed 관리) · DRAFT_0001: 없음 (신규)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| role_id | uuid | N | gen_random_uuid() | PK | |
| code | varchar(64) | N | | UQ | `job_seeker`, `admin` (요구사항 개요 §5). 기업 담당자는 1차 제외 |
| name | varchar(120) | N | | | |
| created_at | timestamptz | N | now() | | |

### A06 `permissions`
- 요구사항: FR-ADM-001, FR-CMN-003
- 데이터 등급: INTERNAL · 보존: 영구 (Seed 관리) · DRAFT_0001: 없음 (신규)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| permission_id | uuid | N | gen_random_uuid() | PK | |
| code | varchar(100) | N | | UQ | 예: `admin.models.read`, `admin.audit.read` |
| description | text | Y | | | |
| created_at | timestamptz | N | now() | | |

### A07 `role_permissions`
- 요구사항: FR-ADM-001, FR-CMN-003
- 데이터 등급: INTERNAL · 보존: 영구 (Seed 관리) · DRAFT_0001: 없음 (신규)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| role_id | uuid | N | | PK; FK → roles.role_id (CASCADE) | |
| permission_id | uuid | N | | PK; FK → permissions.permission_id (CASCADE) | |
| created_at | timestamptz | N | now() | | |

인덱스:
- `(permission_id)`

### A08 `user_roles`
- 요구사항: FR-ACC-001, FR-ADM-001, FR-ADM-002, FR-CMN-003
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제. 부여·회수 이력은 `audit_events`에 기록 · DRAFT_0001: 없음 (신규)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | |
| role_id | uuid | N | | PK; FK → roles.role_id (RESTRICT) | 사용 중인 역할은 삭제 불가 |
| granted_by_user_id | uuid | Y | | FK → users.user_id (SET NULL) | 부여한 관리자. 가입 시 기본 역할은 NULL |
| granted_at | timestamptz | N | now() | | |

인덱스:
- `(role_id)`

### A09 `account_deletion_requests` — **신규 (FR-ACC-007)**
- 요구사항: FR-ACC-007
- 데이터 등급: PERSONAL · 보존: 처리 완료 후 `user_id`가 NULL로 바뀌고 요청 기록만 1년 보존 (D-06 가안) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| request_id | uuid | N | gen_random_uuid() | PK | API 응답의 `request_id` |
| user_id | uuid | Y | | FK → users.user_id (SET NULL) | users 삭제 후 NULL (익명 처리 증빙) |
| status | varchar(20) | N | 'requested' | | `requested` / `cancelled` / `completed` |
| requested_at | timestamptz | N | now() | | |
| scheduled_purge_at | timestamptz | N | | | 실제 삭제 예정 시각 (가안: 요청 + 30일) |
| completed_at | timestamptz | Y | | | |

제약:
- `CHECK (status IN ('requested', 'cancelled', 'completed'))`
- `CHECK (scheduled_purge_at >= requested_at)`
- `CHECK (status <> 'completed' OR completed_at IS NOT NULL)`

인덱스:
- `UNIQUE (user_id) WHERE status = 'requested'`
- `(status, scheduled_purge_at)`

### A10 `password_reset_tokens` — **신규 (FR-ACC-004)**
- 요구사항: FR-ACC-004, NFR-SEC-001
- 데이터 등급: SENSITIVE · 보존: 사용·만료 후 7일 뒤 삭제 (배치) · DRAFT_0001: 없음
- 규칙: 토큰 원문은 메일 링크에만 넣고 DB에는 SHA-256 해시만 저장. 30분 후 만료, 한 번만 사용 (FR-ACC-004 수용 기준 2)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| token_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| token_hash | char(64) | N | | UQ | 재설정 토큰의 SHA-256 |
| created_at | timestamptz | N | now() | | |
| expires_at | timestamptz | N | | | 발급 + 30분 |
| used_at | timestamptz | Y | | | 사용한 시각. NULL이면 미사용 |

제약:
- `CHECK (expires_at > created_at AND expires_at <= created_at + interval '30 minutes')`
- `CHECK (used_at IS NULL OR used_at >= created_at)`

인덱스:
- `(user_id) WHERE used_at IS NULL`

---

## B. 동의·경력·역량·직무

### B09 `consent_policies` — **신규 (FR-ACC-006, FR-CMN-003)**
- 요구사항: FR-ACC-001, FR-ACC-006, FR-CMN-003
- 데이터 등급: PUBLIC · 보존: 영구 (과거 버전도 동의 근거라 삭제 금지) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| policy_code | varchar(80) | N | | PK | `terms`, `privacy`, `llm_processing`, `behavior_tracking` 등 |
| version | varchar(40) | N | | PK | |
| is_required | boolean | N | | | 필수 동의 여부 (철회 불가, 탈퇴로 안내) |
| content_url | text | N | | | 약관 본문 위치 |
| effective_at | timestamptz | N | | | 시행 시각 |
| created_at | timestamptz | N | now() | | |

### B01 `user_consents`
- 요구사항: FR-ACC-001, FR-ACC-006, FR-AI-002
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 변경(v0.1 대비): 정책 코드·버전을 `consent_policies` FK로 고정. 행을 수정하지 않고 **추가만** 해서 이력을 남김
- 결정 반영: FR-ACC-006 — 가입 후 동의·철회 기록은 `consent_policies.is_required = false`인 정책만 추가할 수 있다 (애플리케이션 검사, T31)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| consent_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| policy_code | varchar(80) | N | | | `consent_policies` 복합 FK (제약 참고) |
| policy_version | varchar(40) | N | | | |
| granted | boolean | N | | | true = 동의, false = 철회 |
| recorded_at | timestamptz | N | now() | | |

제약:
- `FOREIGN KEY (policy_code, policy_version) REFERENCES consent_policies (policy_code, version) ON DELETE RESTRICT`

인덱스:
- `(user_id, policy_code, recorded_at DESC)`

### B02 `user_experiences`
- 요구사항: FR-PRF-003
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| experience_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| organization | varchar(200) | N | | | |
| title | varchar(200) | N | | | 직함·역할 |
| start_date | date | Y | | | |
| end_date | date | Y | | | NULL = 재직 중 |
| description | text | Y | | | |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)`

인덱스:
- `(user_id)`

### B03 `user_projects`
- 요구사항: FR-PRF-004
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| project_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| title | varchar(200) | N | | | |
| summary | text | Y | | | |
| start_date | date | Y | | | |
| end_date | date | Y | | | |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)`

인덱스:
- `(user_id)`

### B10 `user_project_skills` — **신규 (FR-PRF-004 사용 기술)**
- 요구사항: FR-ANL-001, FR-PRF-004
- 데이터 등급: PERSONAL · 보존: 프로젝트 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| project_id | uuid | N | | PK; FK → user_projects.project_id (CASCADE) | |
| skill_id | uuid | N | | PK; FK → skills.skill_id (RESTRICT) | |
| created_at | timestamptz | N | now() | | |

인덱스:
- `(skill_id)`

### B04 `job_roles`
- 요구사항: FR-ANL-002, FR-ANL-005, FR-CMN-002, FR-JOB-001, FR-JOB-002, FR-JOB-005, FR-PRF-002
- 데이터 등급: PUBLIC · 보존: 영구. 폐기 시 `is_active=false` (참조 보존) · DRAFT_0001: 있음 (컬럼 추가)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| job_role_id | uuid | N | gen_random_uuid() | PK | |
| code | varchar(64) | N | | UQ | 안정 코드 (D-04 분류 체계) |
| name | varchar(160) | N | | | |
| description | text | Y | | | **추가** — 직무 상세 화면(UI-006) |
| is_active | boolean | N | true | | **추가** — 목록 노출 여부 |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (length(btrim(code)) > 0)`

### B05 `skills`
- 요구사항: FR-ANL-002, FR-CMN-002, FR-JOB-002, FR-JOB-003, FR-JOB-006, FR-PRF-001, FR-PRF-004
- 데이터 등급: PUBLIC · 보존: 영구. 폐기 시 `is_active=false` · DRAFT_0001: 있음 (컬럼 추가)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| skill_id | uuid | N | gen_random_uuid() | PK | |
| code | varchar(64) | N | | UQ | |
| name | varchar(160) | N | | | |
| is_active | boolean | N | true | | **추가** |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (length(btrim(code)) > 0)`

인덱스:
- `(lower(name))`

### B06 `job_role_skills`
- 요구사항: FR-ANL-001, FR-ANL-002, FR-JOB-002, FR-JOB-006
- 데이터 등급: PUBLIC · 보존: 영구 · DRAFT_0001: 있음 (**`importance` → `required_level` 이름·의미 변경**)
- 변경 이유: FR-ANL-002 — Skill Gap은 `required_level - user_skills.proficiency`로 계산하므로 같은 1~5 척도여야 함

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| job_role_id | uuid | N | | PK; FK → job_roles.job_role_id (CASCADE) | |
| skill_id | uuid | N | | PK; FK → skills.skill_id (RESTRICT) | |
| required_level | smallint | N | | | 요구 숙련도 1~5 (`user_skills.proficiency`와 같은 척도) |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (required_level BETWEEN 1 AND 5)`

인덱스:
- `(skill_id)`

### B07 `user_skills`
- 요구사항: FR-AI-002, FR-ANL-001, FR-ANL-002, FR-ANL-003, FR-CMN-001, FR-CMN-002, FR-PRF-001
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 있음 (FK CASCADE, `updated_at` 추가)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | |
| skill_id | uuid | N | | PK; FK → skills.skill_id (RESTRICT) | |
| proficiency | smallint | Y | | | 자기평가 1~5. NULL = 미입력 (Gap 계산 시 0으로 취급) |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (proficiency BETWEEN 1 AND 5)`

인덱스:
- `(skill_id)`

### B08 `user_target_roles`
- 요구사항: FR-ANL-002, FR-ANL-003, FR-CMN-001, FR-CMN-002, FR-PRF-002
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 결정 반영: FR-PRF-002 "최대 3개" → `priority` 1~3 + 사용자별 유일

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | |
| job_role_id | uuid | N | | PK; FK → job_roles.job_role_id (RESTRICT) | |
| priority | smallint | N | | | 1 = 1순위 |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (priority BETWEEN 1 AND 3)`

인덱스:
- `UNIQUE (user_id, priority)`
- `(job_role_id)`

---

## C. 기업·공고·데이터 출처

### C05 `data_sources`
- 요구사항: FR-ANL-005, FR-JOB-004, FR-JOB-005, NFR-OPS-001
- 데이터 등급: INTERNAL · 보존: 영구 (참조 데이터의 출처 근거) · DRAFT_0001: 없음
- 결정 반영: 요구사항 D-05 제안 — 1차는 `synthetic_seed`(가상 Seed) 한 개만 사용

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| source_id | uuid | N | gen_random_uuid() | PK | |
| code | varchar(80) | N | | UQ | 예: `synthetic_seed` |
| name | varchar(160) | N | | | |
| license_ref | text | Y | | | 이용 약관·계약 문서 위치. 외부 출처는 필수 (T61) |
| retention_days | integer | Y | | | 수집 데이터 보존 일수. NULL = 무기한 |
| is_active | boolean | N | true | | |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (retention_days IS NULL OR retention_days > 0)`
- `CHECK (code = 'synthetic_seed' OR license_ref IS NOT NULL)`

### C01 `companies`
- 요구사항: FR-JOB-004, FR-JOB-005, FR-JOB-006, FR-JOB-007
- 데이터 등급: PUBLIC · 보존: 영구. 공고가 남아 있으면 삭제 불가 · DRAFT_0001: 있음 (컬럼 추가)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| company_id | uuid | N | gen_random_uuid() | PK | |
| name | varchar(200) | N | | | 동명 기업이 있어 UNIQUE 아님 |
| website_url | text | Y | | | |
| description | text | Y | | | **추가** — 기업 상세 화면(UI-011) |
| source_id | uuid | N | | FK → data_sources.source_id (RESTRICT) | **추가** — 데이터 출처 |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (length(btrim(name)) > 0)`

인덱스:
- `(lower(name))`

### C02 `job_postings`
- 요구사항: FR-ANL-003, FR-JOB-004, FR-JOB-005, FR-JOB-006, FR-JOB-007
- 데이터 등급: PUBLIC (status='published'만) · 보존: 마감 후에도 추천·북마크 참조 때문에 행 유지, 출처 `retention_days` 경과 시 배치 삭제 검토 · DRAFT_0001: 있음 (컬럼 추가)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| job_posting_id | uuid | N | gen_random_uuid() | PK | |
| company_id | uuid | N | | FK → companies.company_id (RESTRICT) | |
| job_role_id | uuid | Y | | FK → job_roles.job_role_id (RESTRICT) | 직무 분류 (미분류 허용) |
| source_id | uuid | N | | FK → data_sources.source_id (RESTRICT) | **추가** |
| title | varchar(240) | N | | | |
| description | text | Y | | | |
| employment_type | varchar(24) | Y | | | **추가** — `full_time` / `contract` / `intern` / `part_time` |
| location_text | varchar(120) | Y | | | **추가** — 근무지 |
| source_url | text | Y | | | 원문 공고 링크 |
| status | varchar(20) | N | 'draft' | | `draft` / `published` / `closed` |
| published_at | timestamptz | Y | | | |
| expires_at | timestamptz | Y | | | |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (length(btrim(title)) > 0)`
- `CHECK (status IN ('draft', 'published', 'closed'))`
- `CHECK (employment_type IS NULL OR employment_type IN ('full_time', 'contract', 'intern', 'part_time'))`
- `CHECK (published_at IS NULL OR expires_at IS NULL OR expires_at >= published_at)`
- `CHECK (status <> 'published' OR published_at IS NOT NULL)`

인덱스:
- `(company_id)`
- `(job_role_id)`
- `(status, published_at DESC)`

### C03 `job_posting_skills`
- 요구사항: FR-ANL-001, FR-JOB-006
- 데이터 등급: PUBLIC · 보존: 공고와 함께 · DRAFT_0001: 있음 (`required_level` 추가, FK CASCADE)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| job_posting_id | uuid | N | | PK; FK → job_postings.job_posting_id (CASCADE) | |
| skill_id | uuid | N | | PK; FK → skills.skill_id (RESTRICT) | |
| is_required | boolean | N | true | | 필수/우대 |
| required_level | smallint | Y | | | **추가** — 1~5. NULL이면 직무 기본값(`job_role_skills`) 사용 |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (required_level BETWEEN 1 AND 5)`

인덱스:
- `(skill_id)`

### C04 `user_job_bookmarks`
- 요구사항: FR-JOB-006, FR-JOB-007
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 있음 (FK 동작 변경)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | |
| job_posting_id | uuid | N | | PK; FK → job_postings.job_posting_id (CASCADE) | |
| created_at | timestamptz | N | now() | | |

인덱스:
- `(job_posting_id)`
- `(user_id, created_at DESC)`

### C06 `job_posting_external_refs`
- 요구사항: FR-JOB-005, NFR-OPS-001
- 데이터 등급: INTERNAL · 보존: 공고와 함께 · DRAFT_0001: 없음
- 조건: 외부 수집(T62) 전까지 비어 있음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| source_id | uuid | N | | PK; FK → data_sources.source_id (RESTRICT) | |
| external_id | varchar(240) | N | | PK | 출처 측 공고 ID (중복 판별) |
| job_posting_id | uuid | N | | FK → job_postings.job_posting_id (CASCADE) | |
| first_seen_at | timestamptz | N | now() | | |
| last_seen_at | timestamptz | N | now() | | |

인덱스:
- `(job_posting_id)`

### C07 `ingestion_runs`
- 요구사항: FR-ANL-005, NFR-OPS-001
- 데이터 등급: INTERNAL · 보존: 180일 (가안) · DRAFT_0001: 없음
- 조건: 외부 수집(T62~T64) 전까지 비어 있음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| ingestion_run_id | uuid | N | gen_random_uuid() | PK | |
| source_id | uuid | N | | FK → data_sources.source_id (RESTRICT) | |
| status | varchar(24) | N | 'running' | | `running` / `succeeded` / `failed` |
| started_at | timestamptz | N | now() | | |
| ended_at | timestamptz | Y | | | |
| fetched_count | integer | N | 0 | | |
| error_summary | text | Y | | | 비밀값·원문 응답 저장 금지 |

제약:
- `CHECK (status IN ('running', 'succeeded', 'failed'))`
- `CHECK (fetched_count >= 0)`
- `CHECK (ended_at IS NULL OR ended_at >= started_at)`

인덱스:
- `(source_id, started_at DESC)`

---

## D. 매칭·Skill Gap·추천·모델

### D01 `model_versions`
- 요구사항: FR-ADM-003, FR-ADM-005, FR-ADM-006, FR-AI-002, FR-AI-003, FR-ANL-001, FR-ANL-002, FR-ANL-003, FR-ANL-005
- 데이터 등급: INTERNAL · 보존: 영구 (결과 재현성. 참조 중이면 삭제 불가) · DRAFT_0001: 없음
- 결정 반영: 1차 규칙 기반 계산(T26·T27)도 `kind='rule'` 버전으로 등록해 결과와 같은 ID 체계 사용 (FR-ADM-003 수용 기준 1)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| model_version_id | uuid | N | gen_random_uuid() | PK | |
| model_code | varchar(100) | N | | | 예: `match_rule`, `skill_gap_rule`, `resume_llm` |
| version | varchar(80) | N | | | |
| kind | varchar(20) | N | | | `rule` / `ml` / `llm` |
| artifact_ref | text | Y | | | 모델 파일·프롬프트 버전 위치 |
| description | text | Y | | | 점수 의미·한계 (UI 한계 문구 근거) |
| approved_at | timestamptz | Y | | | NULL = 미승인 (서비스 사용 금지) |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (kind IN ('rule', 'ml', 'llm'))`

인덱스:
- `UNIQUE (model_code, version)`

### D02 `match_evaluations`
- 요구사항: FR-ANL-001
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| match_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| job_posting_id | uuid | Y | | FK → job_postings.job_posting_id (CASCADE) | 공고 또는 직무 중 정확히 하나 |
| job_role_id | uuid | Y | | FK → job_roles.job_role_id (RESTRICT) | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | 계산 기준 (필수 — FR-ANL-001 수용 기준 3) |
| status | varchar(20) | N | 'completed' | | `pending` / `completed` / `failed` |
| score | numeric(5,2) | Y | | | 0~100. **확률 아님** |
| matched_skill_count | smallint | Y | | | |
| missing_skill_count | smallint | Y | | | |
| limitations | text | Y | | | 화면 표시용 한계 설명 |
| evaluated_at | timestamptz | N | now() | | |

제약:
- `CHECK (num_nonnulls(job_posting_id, job_role_id) = 1)`
- `CHECK (status IN ('pending', 'completed', 'failed'))`
- `CHECK (score IS NULL OR score BETWEEN 0 AND 100)`
- `CHECK (status <> 'completed' OR score IS NOT NULL)`

인덱스:
- `(user_id, evaluated_at DESC)`
- `(job_posting_id)`
- `(job_role_id)`
- `(model_version_id)`

### D03 `skill_gap_assessments`
- 요구사항: FR-ANL-002, FR-CMN-001
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| assessment_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| job_role_id | uuid | N | | FK → job_roles.job_role_id (RESTRICT) | 기준 목표 직무 |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | 계산 규칙 버전 |
| evaluated_at | timestamptz | N | now() | | "이전 기준" 판단에 사용 (FR-ANL-002 수용 기준 3) |

인덱스:
- `(user_id, evaluated_at DESC)`
- `(job_role_id)`
- `(model_version_id)`

### D04 `skill_gap_items`
- 요구사항: FR-ANL-002
- 데이터 등급: PERSONAL · 보존: 평가와 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| assessment_id | uuid | N | | PK; FK → skill_gap_assessments.assessment_id (CASCADE) | |
| skill_id | uuid | N | | PK; FK → skills.skill_id (RESTRICT) | |
| required_level | smallint | N | | | 계산 시점 값 복사 (이후 기준 변경과 무관하게 재현) |
| observed_level | smallint | N | | | 계산 시점 사용자 숙련도 (미입력 0) |
| gap | smallint | N | | | `max(required - observed, 0)` (FR-ANL-002 수용 기준 1) |

제약:
- `CHECK (required_level BETWEEN 1 AND 5)`
- `CHECK (observed_level BETWEEN 0 AND 5)`
- `CHECK (gap = greatest(required_level - observed_level, 0))`

인덱스:
- `(skill_id)`

### D05 `recommendation_runs`
- 요구사항: FR-ANL-003, FR-ANL-004, FR-CMN-001
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| recommendation_run_id | uuid | N | gen_random_uuid() | PK | API의 `run_id` |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | |
| status | varchar(20) | N | 'completed' | | `pending` / `completed` / `failed` / `fallback` |
| generated_at | timestamptz | N | now() | | |

제약:
- `CHECK (status IN ('pending', 'completed', 'failed', 'fallback'))`

인덱스:
- `(user_id, generated_at DESC)`
- `(model_version_id)`

### D06 `recommendation_items`
- 요구사항: FR-ANL-003, FR-ANL-004, FR-CMN-001
- 데이터 등급: PERSONAL · 보존: 실행과 함께 · DRAFT_0001: 없음
- 변경(v0.1 대비): `feedback` 단일 컬럼 **삭제** → `recommendation_feedback` 이력 테이블로 이동 (FR-ANL-004)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| recommendation_run_id | uuid | N | | PK; FK → recommendation_runs.recommendation_run_id (CASCADE) | |
| job_posting_id | uuid | N | | PK; FK → job_postings.job_posting_id (CASCADE) | |
| rank | integer | N | | | 1부터 |
| score | numeric(5,2) | Y | | | 0~100, 확률 아님 |
| reason | text | N | | | 추천 이유 (1개 이상 필수 — FR-ANL-003 수용 기준 2) |

제약:
- `CHECK (rank >= 1)`
- `CHECK (score IS NULL OR score BETWEEN 0 AND 100)`
- `CHECK (length(btrim(reason)) > 0)`

인덱스:
- `UNIQUE (recommendation_run_id, rank)`
- `(job_posting_id)`

### D07 `recommendation_feedback` — **신규 (FR-ANL-004)**
- 요구사항: FR-ANL-003, FR-ANL-004
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 규칙: 추가만 함. 공고별 최신 행이 현재 피드백. `not_interested` 최신 상태인 공고는 다음 추천에서 제외 (FR-ANL-004 수용 기준 3)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| feedback_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| recommendation_run_id | uuid | Y | | FK → recommendation_runs.recommendation_run_id (SET NULL) | 어떤 추천에서 남겼는지 |
| job_posting_id | uuid | N | | FK → job_postings.job_posting_id (CASCADE) | |
| feedback | varchar(24) | N | | | `liked` / `not_interested` / `cleared` |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (feedback IN ('liked', 'not_interested', 'cleared'))`

인덱스:
- `(user_id, job_posting_id, created_at DESC)`
- `(recommendation_run_id)`
- `(job_posting_id)`

### F04 `model_evaluations`
- 요구사항: FR-ADM-003
- 데이터 등급: INTERNAL · 보존: 영구 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| model_evaluation_id | uuid | N | gen_random_uuid() | PK | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (CASCADE) | |
| dataset_ref | text | N | | | 평가 데이터셋 위치·버전 |
| metric_code | varchar(80) | N | | | 예: `ndcg_at_10` |
| metric_value | numeric | N | | | |
| leakage_checked | boolean | N | false | | 학습/평가 누수 점검 여부 (E2) |
| evaluated_at | timestamptz | N | now() | | |

인덱스:
- `(model_version_id, metric_code)`

---

## E. 문서·RAG

### E01 `user_documents`
- 요구사항: FR-AI-001, FR-AI-002, FR-AI-003, NFR-SEC-003
- 데이터 등급: SENSITIVE · 보존: users 삭제 시 함께 삭제. **객체 저장소 파일·검색 색인 삭제는 애플리케이션 책임** (FR-AI-001 수용 기준 3) · DRAFT_0001: 없음
- 결정 반영: NFR-SEC-003 — 파일 본문은 DB·API 서버에 두지 않고 **분리된 파일 저장소**(별도 컨테이너 또는 객체 저장소, 실행 권한 없음)에 `storage_key` 이름으로 저장. 이 테이블은 메타데이터만 가진다.
- 결정 반영: 요구사항 D-08 제안 — `visibility='shared'`는 관리자가 올린 공용 커리어 자료(RAG 대상), 일반 사용자 문서는 `private`

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| document_id | uuid | N | gen_random_uuid() | PK | |
| owner_user_id | uuid | N | | FK → users.user_id (CASCADE) | 올린 사람 |
| kind | varchar(40) | N | | | `resume` / `portfolio` / `career_guide` |
| original_filename | varchar(255) | N | | | 화면 표시용. 저장 경로로 쓰지 않음 |
| mime_type | varchar(100) | N | | | 실제 시그니처 검사 결과 |
| size_bytes | bigint | N | | | |
| storage_key | varchar(64) | N | | | 파일 저장소의 저장 이름. 서버가 만든 128비트 이상 무작위 값(16진수). 원래 파일 이름·사용자 ID를 넣지 않음. API 응답에 노출 금지 |
| checksum_sha256 | char(64) | N | | | |
| visibility | varchar(24) | N | 'private' | | `private` / `shared` |
| status | varchar(20) | N | 'uploaded' | | `uploaded` / `scanning` / `ready` / `rejected` / `deleting` |
| created_at | timestamptz | N | now() | | |
| updated_at | timestamptz | N | now() | | |

제약:
- `CHECK (kind IN ('resume', 'portfolio', 'career_guide'))`
- `CHECK (visibility IN ('private', 'shared'))`
- `CHECK (status IN ('uploaded', 'scanning', 'ready', 'rejected', 'deleting'))`
- `CHECK (size_bytes > 0)`
- `CHECK (storage_key ~ '^[0-9a-f]{32,64}$')`

인덱스:
- `UNIQUE (storage_key)`
- `(owner_user_id, created_at DESC)`
- `(visibility) WHERE visibility = 'shared'`

### E02 `document_analyses`
- 요구사항: FR-AI-001, FR-AI-002
- 데이터 등급: SENSITIVE · 보존: 문서와 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| analysis_id | uuid | N | gen_random_uuid() | PK | |
| document_id | uuid | N | | FK → user_documents.document_id (CASCADE) | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | 사용 모델 (FR-AI-002 수용 기준 2) |
| analysis_type | varchar(40) | N | | | `skill_extraction` / `summary` |
| status | varchar(20) | N | 'queued' | | `queued` / `running` / `succeeded` / `failed` |
| result | jsonb | Y | | | 추출 기술·경력 후보. 사용자 확인 전 프로필 자동 반영 금지 (FR-AI-002 수용 기준 1) |
| error_code | varchar(60) | Y | | | 원문 오류 메시지 저장 금지 |
| requested_at | timestamptz | N | now() | | |
| completed_at | timestamptz | Y | | | |

제약:
- `CHECK (analysis_type IN ('skill_extraction', 'summary'))`
- `CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))`
- `CHECK (status <> 'succeeded' OR result IS NOT NULL)`

인덱스:
- `(document_id, requested_at DESC)`
- `(model_version_id)`

### E03 `document_chunks`
- 요구사항: FR-AI-001, FR-AI-003
- 데이터 등급: SENSITIVE · 보존: 문서와 함께 (벡터 색인도 동기 삭제) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| chunk_id | uuid | N | gen_random_uuid() | PK | |
| document_id | uuid | N | | FK → user_documents.document_id (CASCADE) | 접근 권한은 문서에서 상속 |
| chunk_index | integer | N | | | |
| content_hash | char(64) | N | | | |
| index_ref | text | Y | | | 벡터 색인 위치 (저장소 미결정) |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (chunk_index >= 0)`

인덱스:
- `UNIQUE (document_id, chunk_index)`

### E04 `retrieval_runs`
- 요구사항: FR-AI-003
- 데이터 등급: SENSITIVE · 보존: 90일 (가안) 후 삭제, users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 규칙: 질문 원문은 저장하지 않고 해시만 저장 (E8)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| retrieval_run_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| model_version_id | uuid | Y | | FK → model_versions.model_version_id (RESTRICT) | 답변 생성 모델 (검색만이면 NULL) |
| query_hash | char(64) | N | | | |
| status | varchar(24) | N | 'running' | | `running` / `answered` / `no_evidence` / `failed` |
| started_at | timestamptz | N | now() | | |
| ended_at | timestamptz | Y | | | |

제약:
- `CHECK (status IN ('running', 'answered', 'no_evidence', 'failed'))`

인덱스:
- `(user_id, started_at DESC)`
- `(model_version_id)`

### E05 `retrieval_citations`
- 요구사항: FR-AI-003
- 데이터 등급: SENSITIVE · 보존: 검색 실행과 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| retrieval_run_id | uuid | N | | PK; FK → retrieval_runs.retrieval_run_id (CASCADE) | |
| chunk_id | uuid | N | | PK; FK → document_chunks.chunk_id (CASCADE) | 권한 검증된 청크만 |
| rank | integer | N | | | |
| score | numeric(8,5) | Y | | | 검색 유사도 |

제약:
- `CHECK (rank >= 1)`

인덱스:
- `UNIQUE (retrieval_run_id, rank)`
- `(chunk_id)`

---

## F. Agent·시장·행동 분석·운영

### F01 `agent_runs`
- 요구사항: FR-AI-004
- 데이터 등급: PERSONAL · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 조건: 요구사항 D-09 — 1차 작업 목록이 확정되지 않으면 테이블 생성 보류

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| agent_run_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| workflow_code | varchar(80) | N | | | 허용 목록의 작업 종류 |
| idempotency_key | varchar(100) | Y | | | 중복 실행 방지 |
| status | varchar(24) | N | 'queued' | | `queued` / `running` / `awaiting_approval` / `succeeded` / `failed` / `rejected` / `timed_out` |
| started_at | timestamptz | N | now() | | |
| ended_at | timestamptz | Y | | | |

제약:
- `CHECK (status IN ('queued', 'running', 'awaiting_approval', 'succeeded', 'failed', 'rejected', 'timed_out'))`

인덱스:
- `UNIQUE (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL`
- `(user_id, started_at DESC)`

### F02 `agent_tool_approvals`
- 요구사항: FR-AI-004
- 데이터 등급: PERSONAL · 보존: 실행과 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| approval_id | uuid | N | gen_random_uuid() | PK | |
| agent_run_id | uuid | N | | FK → agent_runs.agent_run_id (CASCADE) | |
| tool_code | varchar(100) | N | | | |
| decision | varchar(24) | N | 'pending' | | `pending` / `approved` / `rejected` / `expired` |
| approver_user_id | uuid | Y | | FK → users.user_id (SET NULL) | 1차는 실행 소유자 본인 |
| reason | text | Y | | | |
| requested_at | timestamptz | N | now() | | |
| decided_at | timestamptz | Y | | | |
| expires_at | timestamptz | N | | | 승인 유효 기한 |

제약:
- `CHECK (decision IN ('pending', 'approved', 'rejected', 'expired'))`
- `CHECK (decision = 'pending' OR decided_at IS NOT NULL)`

인덱스:
- `(agent_run_id)`
- `(approver_user_id)`

### F03 `agent_tool_calls`
- 요구사항: FR-AI-004
- 데이터 등급: PERSONAL · 보존: 실행과 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| tool_call_id | uuid | N | gen_random_uuid() | PK | |
| agent_run_id | uuid | N | | FK → agent_runs.agent_run_id (CASCADE) | |
| approval_id | uuid | Y | | FK → agent_tool_approvals.approval_id (RESTRICT) | 외부 부작용 도구는 필수 (애플리케이션 검사) |
| tool_code | varchar(100) | N | | | |
| status | varchar(24) | N | 'running' | | `running` / `succeeded` / `failed` |
| started_at | timestamptz | N | now() | | |
| ended_at | timestamptz | Y | | | |

제약:
- `CHECK (status IN ('running', 'succeeded', 'failed'))`

인덱스:
- `(agent_run_id)`
- `(approval_id)`

### F05 `market_observations`
- 요구사항: FR-ANL-005
- 데이터 등급: INTERNAL (집계 결과는 화면 공개) · 보존: 출처 `retention_days` · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| observation_id | uuid | N | gen_random_uuid() | PK | |
| source_id | uuid | N | | FK → data_sources.source_id (RESTRICT) | 출처 표시 (FR-ANL-005 수용 기준 2) |
| job_role_id | uuid | Y | | FK → job_roles.job_role_id (RESTRICT) | NULL = 전체 시장 |
| skill_id | uuid | Y | | FK → skills.skill_id (RESTRICT) | `skill_demand_share` 전용 기술 차원, 다른 지표는 NULL (T65, migration 0003) |
| observed_on | date | N | | | 집계 구간 시작일 (KST, 주=월요일, 월=1일) |
| period | varchar(10) | N | | | `day` / `week` / `month` |
| metric_code | varchar(80) | N | | | `posting_count` / `skill_demand_share` ([T65 계약](../docs/data/MARKET_METRICS_CONTRACT.md)) |
| metric_value | numeric | N | | | 단위는 지표별 계약 (건 / 0~1 비율) |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (period IN ('day', 'week', 'month'))`
- `CHECK ((metric_code = 'skill_demand_share') = (skill_id IS NOT NULL))`
- `CHECK ((metric_code <> 'posting_count' OR (metric_value >= 0 AND metric_value = trunc(metric_value))) AND (metric_code <> 'skill_demand_share' OR metric_value BETWEEN 0 AND 1))`

인덱스:
- `UNIQUE (source_id, job_role_id, metric_code, period, observed_on) WHERE skill_id IS NULL`
- `(job_role_id, metric_code, observed_on)`
- `UNIQUE (source_id, job_role_id, skill_id, metric_code, period, observed_on) WHERE skill_id IS NOT NULL`
- `(skill_id, metric_code, observed_on)`

### F06 `market_forecasts`
- 요구사항: FR-ANL-005
- 데이터 등급: INTERNAL · 보존: 모델 버전과 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| forecast_id | uuid | N | gen_random_uuid() | PK | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | |
| job_role_id | uuid | Y | | FK → job_roles.job_role_id (RESTRICT) | |
| skill_id | uuid | Y | | FK → skills.skill_id (RESTRICT) | `skill_demand_share` 예측 전용, 다른 지표는 NULL (T65, migration 0003) |
| forecast_for | date | N | | | |
| metric_code | varchar(80) | N | | | |
| predicted_value | numeric | N | | | |
| lower_bound | numeric | Y | | | 불확실성 범위 (FR-ANL-005 수용 기준 1) |
| upper_bound | numeric | Y | | | |
| created_at | timestamptz | N | now() | | |

제약:
- `CHECK (lower_bound IS NULL OR upper_bound IS NULL OR lower_bound <= upper_bound)`
- `CHECK ((metric_code = 'skill_demand_share') = (skill_id IS NOT NULL))`

인덱스:
- `(model_version_id)`
- `(job_role_id, metric_code, forecast_for)`
- `(skill_id, metric_code, forecast_for)`

### F07 `behavior_events`
- 요구사항: FR-ADM-006, NFR-PRV-001, NFR-PRV-002
- 데이터 등급: PERSONAL · 보존: 180일 (가안) 후 삭제, users 삭제 시 함께 삭제 · DRAFT_0001: 없음
- 규칙: `behavior_tracking` 동의(`user_consents`)가 최신 true인 사용자만 기록 (애플리케이션 검사)

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| event_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | N | | FK → users.user_id (CASCADE) | |
| event_code | varchar(80) | N | | | 허용 목록 (T71) |
| event_at | timestamptz | N | now() | | |
| metadata | jsonb | Y | | | 개인정보·자유 입력 금지 |

인덱스:
- `(user_id, event_at DESC)`
- `(event_code, event_at)`

### F08 `user_segments`
- 요구사항: FR-ADM-006
- 데이터 등급: INTERNAL · 보존: 모델 버전과 함께 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| segment_id | uuid | N | gen_random_uuid() | PK | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | |
| segment_code | varchar(80) | N | | | |
| label | varchar(160) | N | | | |
| created_at | timestamptz | N | now() | | |

인덱스:
- `UNIQUE (model_version_id, segment_code)`

### F09 `user_segment_assignments`
- 요구사항: FR-ADM-006
- 데이터 등급: PERSONAL (관리자 화면은 집계만, FR-ADM-006 수용 기준 1) · 보존: users 삭제 시 함께 삭제 · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| user_id | uuid | N | | PK; FK → users.user_id (CASCADE) | |
| segment_id | uuid | N | | PK; FK → user_segments.segment_id (CASCADE) | |
| assigned_at | timestamptz | N | now() | | |

인덱스:
- `(segment_id)`

### F10 `anomaly_events`
- 요구사항: FR-ADM-006
- 데이터 등급: INTERNAL · 보존: 180일 (가안) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| anomaly_id | uuid | N | gen_random_uuid() | PK | |
| model_version_id | uuid | N | | FK → model_versions.model_version_id (RESTRICT) | |
| event_id | uuid | Y | | FK → behavior_events.event_id (SET NULL) | 원 이벤트 삭제 후에도 탐지 기록 유지 |
| score | numeric | Y | | | |
| status | varchar(20) | N | 'open' | | `open` / `false_positive` / `resolved` |
| detected_at | timestamptz | N | now() | | |

제약:
- `CHECK (status IN ('open', 'false_positive', 'resolved'))`

인덱스:
- `(status, detected_at DESC)`
- `(model_version_id)`
- `(event_id)`

### F11 `audit_events`
- 요구사항: FR-ACC-007, FR-ADM-002, FR-ADM-004, FR-AI-004
- 데이터 등급: INTERNAL · 보존: 1년 (가안). **수정·삭제 금지** — `career_app`에 INSERT·SELECT만 부여 (T07·T09) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| audit_event_id | uuid | N | gen_random_uuid() | PK | |
| actor_user_id | uuid | Y | | FK → users.user_id (SET NULL) | 시스템 작업·탈퇴 후 NULL |
| action_code | varchar(100) | N | | | 예: `role.grant`, `account.deletion_requested` |
| resource_type | varchar(80) | N | | | |
| resource_id | uuid | Y | | | |
| request_id | varchar(64) | Y | | | API 오류 응답의 `request_id`와 연결 |
| occurred_at | timestamptz | N | now() | | |

인덱스:
- `(occurred_at DESC)`
- `(actor_user_id, occurred_at DESC)`
- `(action_code, occurred_at DESC)`

### F12 `ai_usage_records`
- 요구사항: FR-ADM-005, FR-AI-002, FR-AI-003, FR-AI-004, NFR-PRV-003
- 데이터 등급: INTERNAL · 보존: 1년 (가안). 원문 프롬프트·응답 저장 금지 (E2·E8) · DRAFT_0001: 없음

| 컬럼 | 타입 | NULL | 기본값 | 키·참조 | 설명 |
|---|---|---|---|---|---|
| usage_id | uuid | N | gen_random_uuid() | PK | |
| user_id | uuid | Y | | FK → users.user_id (SET NULL) | 탈퇴 후 익명 집계 |
| model_version_id | uuid | Y | | FK → model_versions.model_version_id (RESTRICT) | |
| provider_model | varchar(100) | N | | | 공급자 모델 ID |
| feature_code | varchar(40) | N | | | `document_analysis` / `rag_answer` / `agent` |
| input_tokens | integer | N | 0 | | |
| output_tokens | integer | N | 0 | | |
| estimated_cost_usd | numeric(18,6) | N | 0 | | 추정치 (청구 금액 아님) |
| latency_ms | integer | Y | | | |
| occurred_at | timestamptz | N | now() | | |

제약:
- `CHECK (feature_code IN ('document_analysis', 'rag_answer', 'agent'))`
- `CHECK (input_tokens >= 0 AND output_tokens >= 0 AND estimated_cost_usd >= 0)`
- `CHECK (latency_ms IS NULL OR latency_ms >= 0)`

인덱스:
- `(occurred_at DESC)`
- `(user_id, occurred_at DESC)`
- `(model_version_id)`
