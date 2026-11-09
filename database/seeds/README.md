# 초기 Seed·Fixture (T10)

> 상태: **DRAFT**. 로컬·일회용 DB 전용입니다. 공유 Staging 적용은 **T12 승인 전 금지**입니다.
> 대상 스키마: **T05 데이터 사전 v0.2** ([`../DATA_DICTIONARY.md`](../DATA_DICTIONARY.md)) 에서 만든 검증용 DDL — `python3 database/model/check_data_dictionary.py --ddl` (`career` 스키마)
> 작업지시서: [T10](../../docs/work-orders/initial-30/T10.md)

## 파일

| 파일 | 내용 |
|---|---|
| `0001_initial_seed.sql` | 멱등 Seed. 트랜잭션 1개로 묶여 있어 실패하면 전부 롤백됩니다 |
| `verify_seed.sql` | 읽기 전용 검산 SQL. 마지막 줄 `SEED_VERIFY \| t` 가 나오면 통과입니다 |
| `../tests/test_seed_idempotency.sh` | 일회용 `postgres:18.1` 컨테이너에 T05 DDL 적용 → Seed 2회 적용 → 검산 → 거부 케이스까지 확인 |

## 데이터 구성 (`SEED_REVISION: 0001`, 15개 테이블)

| 테이블 | 건수 | 규칙 |
|---|---:|---|
| `data_sources` | 1 | `synthetic_seed` (T05 C05, 요구사항 D-05: 1차는 가상 Seed 출처 하나) |
| `job_roles` | 30 | 대문자 스네이크 `code` (예: `BACKEND_ENGINEER`) |
| `skills` | 100 | 대문자 스네이크 `code` (예: `PYTHON`, `POSTGRESQL`) |
| `companies` | 20 | `가상기업 01 (Seed)`, `https://company-01.example.com`, 출처 `synthetic_seed` |
| `users` | 20 | `seed-user-01@example.com` (= `email_canonical`), 1~18 `active`, 19·20 `disabled` |
| `user_profiles` | 18 | active 사용자만 |
| `job_role_skills` | 150 | 직무마다 기술 5개, `required_level` 5→1 |
| `job_postings` | 100 | published 80 / draft 10 (`n%10=0`) / closed 10 (`n%10=9`), 출처 `synthetic_seed`, 고용형태·근무지 포함 |
| `job_posting_skills` | 400 | 공고 직무의 상위 4개 기술, `required_level` 은 직무 기본값과 같게, 4 이상은 필수 |
| `user_skills` | 60 | 사용자 g → 직무 `(g-1)%30` 상위 3개 기술, 숙련도 = 요구 수준 − 1 (Skill Gap 1) |
| `user_job_bookmarks` | 32 | active 사용자 g 가 공고 g, g+20 중 published 만 북마크 |
| `roles` | 2 | `job_seeker`, `admin` (요구사항 개요 §5) |
| `permissions` | 2 | `admin.models.read`, `admin.audit.read` (데이터 사전 A06 예시) |
| `role_permissions` | 2 | admin → 위 2개 |
| `user_roles` | 21 | 모든 Seed 사용자 `job_seeker`, `seed-user-18` 은 `admin` 도 |

건수는 [`docs/DATABASE.md`](../../docs/DATABASE.md)의 "Seed 예시 규모"를 따랐습니다.

## T05 반영 사항

| T05 변경 | Seed 처리 |
|---|---|
| A01 `users.email_canonical` 이 유일 기준 | 값을 함께 넣고 upsert 키를 `email_canonical` 로 변경 |
| C05 `data_sources` 신설, 기업·공고 `source_id` 필수 | `synthetic_seed` 출처를 먼저 넣고 모든 기업·공고가 참조 |
| B06 `importance` → `required_level` (1~5, proficiency 와 같은 척도) | 이름 변경, 사용자 숙련도는 요구 수준보다 1 낮게 |
| C03 `job_posting_skills.required_level` 추가 | 직무 기본값을 그대로 넣음 |
| C02 `employment_type`, `location_text` 추가, published 면 `published_at` 필수 | 값 추가, 기존 규칙 그대로 만족 |
| A05~A08 역할·권한 (Seed 관리) | `roles`·`permissions`·`role_permissions`·`user_roles` 추가 |

## 개인정보·라이선스 원칙

- 전부 **합성 데이터**입니다. 실제 사람, 기업, 채용공고, 기밀정보를 쓰지 않습니다.
- 이메일·URL은 예약 도메인 `example.com` 만 씁니다 (RFC 2606). `source_url` 은 모두 `NULL` 입니다.
- 직무·기술 이름은 일반 명사·공개 기술명만 씁니다. 외부 분류체계(예: 공공 직무코드)를 복제하지 않았습니다.
- 비밀번호·토큰·인증 식별자(`auth_identities`, `password_reset_tokens`)는 Seed 에 넣지 않습니다.

## 멱등 규칙 (두 번 실행해도 결과가 같음)

| 대상 | upsert 키 |
|---|---|
| `data_sources`, `job_roles`, `skills`, `roles`, `permissions` | `code` |
| `users` | `email_canonical` |
| `companies`, `job_postings` | 고정 UUID `md5('seed:<종류>:<번호>')::uuid` |
| 연결 테이블 | 복합 PK |

- 값이 바뀐 행만 `UPDATE` 되고 `updated_at` 이 갱신됩니다. 같은 값이면 아무것도 바꾸지 않습니다.
- 시각은 `now()` 대신 고정값(`2026-11-06 00:00:00+00` 등)을 써서 재실행해도 행 내용이 같습니다.
- Seed 파일은 Seed 가 만든 행을 **지우지 않습니다**. 다른 개발자가 넣은 행도 건드리지 않습니다.
- `verify_seed.sql` 은 Seed 가 만든 행만 셉니다. 그래서 T147 합성 데이터 공장 등 다른 데이터가 같은 DB 에 있어도 통과합니다. 출처(`synthetic_seed`)는 ID 가 아니라 코드로 참조해 어느 쪽을 먼저 넣어도 됩니다.

## 삽입 순서 (부모 → 자식)

0. `data_sources`
1. `job_roles`, `skills`, `companies`, `users`
2. `job_role_skills`, `user_profiles`
3. `job_postings`
4. `job_posting_skills`, `user_skills`, `user_job_bookmarks`
5. `roles`, `permissions` → `role_permissions`, `user_roles`

## 실행 방법

### 자동 테스트 (권장, Docker 필요)

```bash
D1_TEST_ONLY=YES bash database/tests/test_seed_idempotency.sh
```

마지막 줄이 `T10_SEED_TEST=PASS` 이면 통과입니다. 컨테이너는 끝나면 자동 삭제됩니다.

### 이미 띄운 로컬 DB 에 직접 적용

`career` 스키마에 T05 검증용 DDL 을 적용한 **본인 로컬 DB** 에서만 실행합니다.

```bash
python3 database/model/check_data_dictionary.py --ddl > /tmp/t05_ddl.sql
psql -X -v ON_ERROR_STOP=1 -d <로컬DB> -c "CREATE SCHEMA career" -f /tmp/t05_ddl.sql
psql -X -v ON_ERROR_STOP=1 -d <로컬DB> -f database/seeds/0001_initial_seed.sql
psql -X -v ON_ERROR_STOP=1 -d <로컬DB> -f database/seeds/verify_seed.sql
```

## Revision 관리

- Seed 적용 이력 테이블은 아직 없습니다 (T08 Migration 체계에서 결정).
- 그래서 revision 은 파일 이름(`0001_...`)과 파일 머리말의 `SEED_REVISION` 으로 표시합니다.
- 데이터를 바꿀 때는 `0001` 을 고치지 말고 `0002_<설명>.sql` 을 추가하고, 이 표와 `verify_seed.sql` 기대 건수를 함께 바꿉니다.

## 미확정·후속 확인 항목

- T09(실제 Schema Migration SQL)가 데이터 사전과 다르게 나오면 이 Seed 를 맞춰 고쳐야 합니다. 지금은 T05 검증용 DDL 기준입니다.
- 권한(`permissions`) 전체 목록은 아직 정해지지 않아 데이터 사전에 나온 예시 2개만 넣었습니다.
- `consent_policies`(약관 본문 위치·시행일)와 `model_versions` 등 운영 기준 데이터는 담당 일감(T31, T60)에서 정하므로 이번 Seed 에서 제외했습니다.
- Seed 적용 이력(ledger) 테이블 필요 여부는 T08 에서 결정이 필요합니다.
- CI 워크플로(`d1-postgres-sql-test.yml`)에 이 테스트를 넣는 일은 다른 일감과 같은 파일을 고치게 되어, 충돌을 피하려고 이번 PR 에서는 하지 않았습니다. 리뷰어 판단에 따라 추가합니다.
