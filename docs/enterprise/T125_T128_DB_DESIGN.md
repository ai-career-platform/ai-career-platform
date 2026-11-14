# 기업 공고(T125/T126)·공개 포트폴리오(T128/T129) DB 설계 (PROPOSED)

> 상태: **PROPOSED** — migration 아님. 서비스(`company_postings.py`, `public_portfolio.py`)는 메모리 저장소만 있고 라우터는 503입니다.
> 이 문서와 DDL은 "SQL 저장소를 drop-in 으로 붙일 수 있는 데이터 계약"입니다. 백엔드·프론트 동작 변경 없음.
>
> - DDL: [`database/proposed/T125_company_postings.sql`](../../database/proposed/T125_company_postings.sql), [`database/proposed/T128_public_portfolio.sql`](../../database/proposed/T128_public_portfolio.sql)
> - 시험: `backend/tests/test_t125_t128_proposed_ddl_postgres.py` (`T125_T128_ADMIN_URL` 있을 때만, 일회용 PG에 0001~0003 + T122 + T125 + T128 적용)

## 1. T125 — 별도 표 + 승인 때만 공개 표 반영

**선택: `career.job_postings` 재사용(상태·조직 열 추가) 대신 별도 표 `organization_job_postings`.**

| 비교 | job_postings 재사용 | 별도 표(채택) |
|---|---|---|
| 공개 규칙 | `_is_open`·`VISIBLE_STATUSES`·T99 인덱스·크롤러 동기화가 모두 새 상태(pending_review 등)를 알아야 함. 하나라도 빠지면 초안 노출 | 초안·검수 중·반려 행이 공개 표에 **아예 없음** → 공개 API 수정 불필요 |
| 수정본 | 게시 중 공고와 수정본이 같은 표에 공존 → 공개 질의가 수정본을 걸러야 함 | 수정본은 기업 표에만. 승인 시 원본의 공개 행만 갱신 |
| 상태 수 | job_postings CHECK(draft·published·closed) 변경 필요 | 기존 표 변경 없음. 7개 상태는 기업 표에만 |

공개 노출이 불가능한 이유(DB 수준):

1. 공개 행은 `posting.publish` 때만 만들어집니다(P-INV-3). 게시 전 상태(`draft`·`pending_review`·`rejected`)는 CHECK로 `public_posting_id IS NULL` — 공개 행에 연결될 수 없습니다.
2. 수정본(`revision_of` 있음)은 공개 행을 가질 수 없습니다. 승인되면 원본의 공개 행만 바뀝니다.
3. 제약 트리거(`DEFERRABLE INITIALLY DEFERRED`): 기업 공고가 `published` 가 아닌데 연결된 공개 행이 아직 `published` 이면 **커밋 거부**. 마감·만료·내림 때 공개 행을 닫는 것을 잊을 수 없습니다.

### 표

| 표 | 내용 |
|---|---|
| `organization_job_postings` | `CompanyPosting` 그대로. 상태 CHECK = 상태 기계 JSON 7개, 필수 항목·사유 코드·게시 시각 정합성 CHECK, 같은 조직 원본만 가리키는 수정본 복합 FK |
| `organization_job_posting_events` | 서비스 `repo.audit` 행(`career.audit_events` 에 detail 열이 없어 별도). 갱신·삭제 안 함 |
| `organization_public_companies` | 조직 → 공개용 `career.companies` 행(source `company_direct`). `job_postings.company_id` 가 NOT NULL 이라 필요 |

### 메모리 → 열 매핑

| 메모리 | 열 |
|---|---|
| `CompanyPosting.posting_id·organization_id·status·title·description·employment_type·location_text·apply_url·expires_at·version·reason_code·reason_note·revision_of·public_posting_id·published_at·updated_at` | 같은 이름 |
| `created_by` | `created_by_user_id` (탈퇴 시 SET NULL) |
| `repo.audit[{action_code, actor_user_id, posting_id, organization_id, detail, occurred_at}]` | `organization_job_posting_events` 같은 이름 |
| `MemoryPublicPostings.upsert/close` | `job_postings` INSERT/UPDATE (status published/closed, source `company_direct`) |
| `repo.lock` | 행 잠금(`SELECT … FOR UPDATE`) + `version` 비교 UPDATE |

인덱스: 목록 `(organization_id, updated_at DESC)`, 검수 대기열 `(updated_at) WHERE pending_review`, 만료 `(expires_at) WHERE published`, 열린 수정본 하나 `UNIQUE (revision_of) WHERE draft/pending_review/rejected`.

SQL 저장소 구현 시 주의: 메모리는 편집에서 `title=None` 을 받을 수 있지만 열은 NOT NULL(라우터가 막는지 확인). 메모리 공개 행은 `apply_url` 을 복사하지 않습니다 — `job_postings.source_url` 에 넣을지는 결정 필요(D-3).

## 2. T128 — 선택·동의·공유 링크

| 표 | 내용 |
|---|---|
| `public_profile_selections` | `Selection`(fields `text[]`, alias, version, confirmed_version). 행 없음 = 비공개. fields 는 공개 가능 13개 부분집합만(CHECK, NEVER_PUBLIC 불가). 동의는 현재 버전·비어 있지 않은 선택에만 |
| `public_profile_selected_experiences` / `_projects` | 항목별 선택. `(user_id, id)` 복합 FK로 **본인 항목만**, 항목 삭제 시 CASCADE |
| `public_profile_consent_records` | 동의·철회 본문은 기존 `user_consents`(policy `public_profile`), 여기는 `selection_version` 만 |
| `public_profile_links` | `ShareLink`. `token_hash` 64자 hex UNIQUE(원문 저장 없음), TTL ≤ 90일 CHECK, `revoked_at`, `view_count` |

메모리 → 열: `Selection.fields/alias/version/confirmed_version` 같은 이름, `experience_ids/project_ids` → 선택 항목 표, `consents[{user_id, policy_code, policy_version, granted, recorded_at}]` → `user_consents` + `selection_version` → 보조 표, `ShareLink.views` → `view_count`.

- 기존 표 변경(추가만): `user_experiences`·`user_projects` 에 `UNIQUE (user_id, id)` — 복합 FK용. PK가 이미 유일하므로 기존 데이터와 충돌 없음.
- 개인정보: 전부 `ON DELETE CASCADE`(탈퇴 즉시 링크 404). 동의 철회 = 모든 링크 `revoked_at` + 선택 초기화(서비스, 한 트랜잭션).
- `MAX_ACTIVE_LINKS=3` 은 시간 조건이라 CHECK로 못 막음 → 서비스가 선택 행 `FOR UPDATE` 아래에서 셉니다.
- T122 의존 없음(기업 검색·목록 노출 없음, PP-INV-4).

## 3. 번호와 적용 순서

- 지금은 번호를 붙이지 않습니다(`database/proposed/`, runner 무시). 0004·0005·0006(다른 작업에서 이미 예약) 이후 승인 순서대로 번호를 받습니다.
- T125는 T122(organizations) migration 뒤에만 적용 가능. T128은 0001~0003만 필요.
- 사전 seed(승인 후 별도): `data_sources('company_direct', license_ref=조직 게시 약관 버전)`, `consent_policies('public_profile', 승인 약관 버전)`.

## 4. PM 승인 필요

| ID | 항목 | 제안 |
|---|---|---|
| D-1 | T121 역할·T122 조직 표 승인(선행) | T125 DDL은 T122 없이는 적용 불가 |
| D-2 | T125 정책(상태 기계·사유 코드·60일) 승인 | JSON 그대로 CHECK에 고정 |
| D-3 | 지원 링크 공개 여부 | `apply_url` → `job_postings.source_url` 복사(현재 메모리는 미복사) |
| D-4 | 공개 회사 행 | 조직마다 `company_direct` 회사 행 신규(수집 회사 `linked_company_id` 와 섞지 않음) |
| D-5 | `company_direct` 약관(`license_ref`) 작성 | 법무 |
| D-6 | T128 공개 항목·동의 문구(`public_profile` 약관 버전)·TTL 30/90일·링크 3개 | JSON 그대로 |
| D-7 | 보존 | 만료·회수 링크 30일 뒤 삭제(제안), 공고 이벤트는 삭제 안 함 |

검증: PostgreSQL 16.2(로컬 pgserver, 일회용)에서 시험 8개 통과. CI 마이그레이션 시험은 18.1이며 이 시험은 CI에서 skip(환경 변수 없음).
