# Staging `ai_career_poc` Migration 이력 기준선 계획 (0001 기준선 → 0002 → 0003)

> 상태: **계획 (PM 결정 반영, Staging 실행 HOLD)** · 작성 2026-11-10 · 기준 `main` `67df035`
> 이 문서는 읽기 전용 점검과 **로컬 일회용 사본 리허설** 결과다. Staging에는 SELECT만 실행했고, 역할·스키마·이력·Migration은 하나도 만들거나 적용하지 않았다.
> 실행은 [docs/DATABASE.md](../docs/DATABASE.md) 절차(Redmine DB 요청 → PM/JM 리뷰·승인 → 백업 확인 → **PM/JM 실행** → 검증 → 이력 기록)를 따른다.

## 0. PM 결정 요약 (2026-11-10)

| 항목 | 결정 | 상태 |
|---|---|---|
| 0001 기준선 등록 방식 | **A안 채택**: `migrate.py baseline` 명령 추가 (§4.3) | 명령 **미구현** (후속 PR) |
| 기준선 등록 조건 | 0001 구조 검증(카탈로그 일치)과 체크섬 일치 확인 **필수** | 후속 PR에서 구현·테스트 |
| 이력 테이블 초기화 | 별도 절차로 승인·실행 (`DRAFT_00` → `DRAFT_01`, §4.2) | 미실행 |
| `career_migrator` | NOLOGIN 역할로 생성 (§4.1) | 미실행 |
| 테이블 소유권 | **변경하지 않음** (현재 `ai_career_poc` 유지) | — |
| 이번 migration 실행 역할 | 기존 테이블 소유자(`MIGRATE_ROLE=""`) 사용은 **조건부 제안** — 실행 승인 시 함께 승인받아야 함 | 승인 전 |
| SUPERUSER 장기 사용 | 별도 보안 개선 과제 (§4.1) | 후속 |
| 적용 순서 | 0002 → 0003 순차 적용, 단계마다 dry-run·verify (§4.4) | 미실행 |
| 백업·복원 | 기존 Staging 백업 생성·격리 복원 검증 **PASS** (§1) | 완료 |
| Staging 실제 실행 승인 | **미확보** (§5) | — |
| 실제 Migration 실행 | **HOLD** | — |

## 1. 현재 상태 (2026-11-10, 읽기 전용 조회)

| 항목 | 결과 |
|---|---|
| 대상 | `ai_career_poc`, PostgreSQL 18.1 |
| 이력 | `career_migration` 스키마·`schema_migrations` 없음 → `migrate.py status/verify/apply`가 모두 `ledger table ... not found`로 실패 |
| 역할 | `ai_career_poc`(SUPERUSER, LOGIN), `career_reader`(LOGIN, DBeaver 사용 중), `crawler_staging`. `career_admin`·`career_migrator`·`career_app` **없음** |
| 소유자·권한 | `career` 스키마·테이블 51개·인덱스 135개 모두 `ai_career_poc` 소유. 테이블 권한 `ai_career_poc` 전체 + `career_reader` SELECT. 기본 권한은 `public` 스키마에만 있음 |
| 0002 | **미적용** (`account_deletion_requests.scheduled_purge_at` NOT NULL 그대로, 행 0) |
| 0003 | **미적용** (`market_observations`/`market_forecasts`에 `skill_id` 없음, 두 테이블 모두 0행 → 새 CHECK 위반 0건) |
| 백업 | `/home/kant/ai-career-staging-poc/backups/t65-0003-before-20261110T054732Z-75d5cacf/app.dump` (sha256 `9e8c7230…fd3153`), 격리 복원 시 테이블·행·데이터 지문·스키마 일치 |

## 2. 정식 0001과 현행 스키마 비교 — **동등**

로컬 일회용 PostgreSQL 18.6에 빈 `career` 스키마를 만들고 `0001_initial_schema.sql`만 적용한 뒤, Staging과 같은 카탈로그 질의로 비교했다(정렬·시간대 고정).

| 비교 항목 | 0001 | Staging | 결과 |
|---|---|---|---|
| 테이블 (`career`·`public`·`career_migration`) | 51 | 51 | 같음 |
| 컬럼 (순서·타입·길이·정밀도·NULL·기본값·identity) | 329 | 329 | 같음 |
| 제약 (PK·UNIQUE·CHECK·FK, `pg_get_constraintdef` 정의·ON DELETE 포함) | 197 | 197 | 같음 (FK 76) |
| 인덱스 정의 | 135 | 135 | 같음 |
| 주석·뷰·시퀀스·함수·트리거·사용자 타입 | 0 | 0 | 같음 (추가 객체 없음) |
| 확장 | plpgsql | plpgsql | 같음 |

카탈로그 715줄이 한 줄도 다르지 않다. **현행 51개 테이블은 정식 0001과 구조가 같고, migration이 관리하지 않는 추가 객체는 없다.**
다른 점은 소유자·권한뿐이다. 0001 설계(README §1)는 `career_migrator` 소유 + `career_app` CRUD + `career_reader` SELECT이고, Staging은 `ai_career_poc` 소유 + `career_reader` SELECT다(→ §4).

0001 체크섬(러너 규칙: CRLF→LF 후 SHA-256): `bf592121befe1cfca9010d601e2f5af33af654461fba0bf930a3fb7249bc9d38`
(0002 `868001f8261d35ba28495d9dd513cd0462244a0139fa2fca174af67dc5caff62`, 0003 `dfdf43e75910688b6b8a3322ff865c40844aa68c4bb2ec04383badcd352917c5`)

## 3. 리허설 (백업 사본, 로컬 일회용 DB에서만)

백업 `app.dump`를 로컬 일회용 클러스터에 `ai_career_poc` 이름으로 복원하고 아래 순서를 실행했다. 끝난 뒤 클러스터는 삭제했다.

| 단계 | 결과 |
|---|---|
| `DRAFT_00_create_roles_schema.sql` | 성공. `career_admin/migrator/app` NOLOGIN 생성, `career` 스키마에 migrator `UC`·app `U` 권한 추가, 스키마 소유자는 `ai_career_poc` 유지 |
| `DRAFT_01_migration_history.sql` | 성공. `career_migration.schema_migrations` 생성(소유 `career_migrator`, reader SELECT) |
| 기준선 전 `status` | `0001/0002/0003 pending` |
| 0001 기준선 등록(리허설 사본에서만) | `status` 0001 applied, `verify` PASS, dry-run `0002, 0003` |
| `apply` 기본 역할(`SET ROLE career_migrator`) | **실패**: `must be owner of table account_deletion_requests` → 0002 롤백, 이력 변화 없음 |
| `apply` 소유자로(`MIGRATE_ROLE=""`, `ai_career_poc`) | 0002·0003 적용, `verify` PASS applied=3, 재실행 no-op |
| 적용 후 | `skill_id` 2개(NULL 허용), CHECK 3개 검증됨, 인덱스 `ix_market_observations_1`(부분)·`_3`·`_4`·`ix_market_forecasts_3`, `scheduled_purge_at` NULL 허용, 기존 51개 테이블 행 수 동일 |

## 4. 결정이 필요한 사항과 제안

### 4.1 `career_migrator` 역할 — NOLOGIN 생성 (결정), 이번 실행 주체로는 쓸 수 없음

- **결정:** `DRAFT_01`이 `career_migration` 스키마를 `career_migrator` 소유로 만들므로 `DRAFT_00`으로 NOLOGIN 역할(비밀번호 없음)을 만든다.
- **결정: 현재 테이블 소유권은 변경하지 않는다.** 기존 테이블 소유자가 `ai_career_poc`라 `career_migrator`로는 `ALTER TABLE`이 불가하다(리허설 확인).
- **조건부 제안:** 이번 0002·0003 실행은 기존 테이블 소유자 `ai_career_poc`로 한다(`MIGRATE_ROLE=""`). 소유권·앱 접속 계정이 그대로라 서비스 영향이 없다. 이 실행 방식은 Staging 실행 승인 시 **함께 명시적으로 승인**받아야 하며, 승인되지 않으면 실행하지 않는다.
- **별도 보안 과제:** SUPERUSER 계정(`ai_career_poc`)을 앱 접속·migration에 계속 쓰는 것, 테이블 소유권의 `career_migrator` 이전, `career_app` LOGIN 매핑은 T07 권한 모델에 맞춰 별도 일감으로 다룬다.
- `DRAFT_00`의 부수 효과(NOLOGIN 역할 3개 생성, `career` 스키마 권한 추가, `career_migrator` 기본 권한)도 승인 범위에 포함해야 한다.

### 4.2 이력 테이블 초기화 — 별도 절차

`DRAFT_00` → `DRAFT_01`을 그대로 실행한다(각각 한 트랜잭션, 재실행 안전, 비밀번호·LOGIN 없음). 파일명이 `DRAFT_`이므로 migration 적용과 분리된 **별도 절차**로 승인·실행·기록한다. 이 단계만으로는 이력이 비어 있고 `status`는 0001~0003 모두 pending이다.

### 4.3 0001 기준선 등록 — A안 `migrate.py baseline` (결정, 미구현)

이력 행을 손으로 INSERT하지 않는다. **PM 결정으로 A안을 채택**했고, 명령은 **아직 구현되지 않았다**(후속 일감 `MIGRATION_BASELINE_COMMAND_IMPLEMENTATION`). 구현 요구사항:

- 형태: `migrate.py baseline --version 0001 --target staging --approval <승인번호> --confirm-db ai_career_poc [--dry-run]`
- 기존 `guard_target` 안전장치(CI 거부, 승인번호 형식, `--confirm-db` 일치) 재사용
- **0001 구조 검증 필수:** 같은 트랜잭션 안에서 대상 DB 카탈로그(§2 질의: 테이블·컬럼·제약 정의·인덱스·추가 객체)를 0001 기준과 비교해 한 줄이라도 다르면 기록하지 않고 실패
- **체크섬 일치 필수:** 기록할 체크섬은 저장소 0001 파일에서 러너 규칙(CRLF→LF, SHA-256)으로 계산하며, 승인 문서에 적힌 값(`bf592121…bc9d38`)과 같아야 진행
- 이력이 비어 있을 때만 0001 한 행만 기록(`approval_ref` 필수, `execution_ms=0`), 그 외 버전은 거부
- advisory lock·한 트랜잭션, `--dry-run`은 비교 결과만 출력
- 단위 테스트 + 일회용 PostgreSQL 통합 테스트(일치 시 기록, 컬럼 하나 다르면 거부, 이력 있으면 거부, 체크섬 불일치 거부) 후 리뷰

실행 시 승인 기록 번호를 `approval_ref`에 남기고, 기준선 행임을 Redmine 이력에 적는다. (B안 — 리뷰된 1회용 SQL — 은 채택하지 않음)

### 4.4 적용 순서 (`baseline` 구현·병합과 실행 승인 후, PM/JM 실행)

0. 선행: `baseline` 명령 PR 병합, Staging 실행 승인(역할 방식 포함) 기록
1. 직전 상태 확인: 행 수가 2026-11-10 백업과 같은지 확인. 다르면 새 백업 + 체크섬 확인
2. `career_reader` 등 장시간 열린 트랜잭션이 없는지 확인 (ALTER TABLE은 ACCESS EXCLUSIVE 잠금, 러너 `lock_timeout` 10초)
3. 이력 테이블 초기화 별도 절차: `DRAFT_00` → `DRAFT_01`
4. `baseline --dry-run`(구조·체크섬 일치 확인) → `baseline` → `status`(0001 applied, 0002·0003 pending) → `verify` PASS
5. `apply --target staging --to 0002 --approval <번호> --confirm-db ai_career_poc --dry-run` → 동일 명령 실행 → `verify`
6. `apply ... --to 0003 --dry-run` → 실행 → `verify` PASS applied=3
7. 적용 후 검증: `skill_id` 2개, CHECK 3개, 인덱스 4개, 51개 테이블 행 수 동일, `/api/health/db` 200, `/api/v1/market-trends` 로그인 조회 200(빈 관측) — T67 배포 이후

러너는 `CI`/`GITHUB_ACTIONS` 환경에서 Staging 실행을 거부한다. Windows 한국어 로캘에서는 psql 오류 문구 디코딩 경고가 날 수 있으니 `PGCLIENTENCODING=UTF8`·`LC_MESSAGES=C`로 실행하거나 Linux에서 실행한다.

### 4.5 중단·롤백

| 시점 | 처리 |
|---|---|
| `DRAFT_00/01` 실패 | 각 파일이 한 트랜잭션이라 자동 롤백. 원인 확인 후 재실행(멱등) |
| `DRAFT_00/01` 커밋 후 철회 | 승인 후 `career_migration` 스키마 삭제, 추가된 스키마 권한 REVOKE, 객체 없는 NOLOGIN 역할 삭제 |
| 기준선 비교 불일치 | 기록하지 않고 중단(HOLD) |
| 0002/0003 실패 | 러너가 SQL과 이력 행을 함께 롤백하고 뒤 파일은 실행하지 않음 |
| 0002/0003 커밋 후 문제 | forward-only: 수정 migration 추가(0003 헤더 Recovery 참조). 데이터 손상 시 위 백업을 별도 DB에 복원해 비교·복구 (백업 이후 변경분은 유실되므로 최후 수단) |
| 잠금 대기 10초 초과 | 자동 롤백. 세션 정리 후 재시도 |

## 5. 승인 상태

Redmine [#1597](https://sulfite-footbath-next.ngrok-free.dev/issues/1597) (2026-11-10 조회): T65 계약 일감, `In Progress` 90%, 저널 2건(착수, PR #171 리뷰 요청). **Staging DB 변경 승인 기록 없음.** 본문 비범위에 "승인 없는 Staging DB Schema/Seed 변경", Staging 검증 결과에 "Staging 적용 범위는 PM/JM 판정"이 적혀 있다.
0003 파일 머리말의 승인(2026-11-09 Slack, "DB 명세 migration으로 변경 가능")은 스키마 변경 승인이며 Staging 실행 승인이 아니다.

필요한 승인: Redmine DB 요청(또는 #1597 저널)에 §4.1 실행 역할(기존 소유자 사용), §4.2 이력 초기화, §4.3 `baseline` 실행, §4.4 순서, 실행자·시각을 적고 PM/JM 승인.

**현재 판정: Staging 실제 실행 승인 미확보 → 실제 Migration 실행 HOLD.** 이 문서의 병합은 계획 승인이며 Staging 실행 승인이 아니다.

## 6. 후속 일감

| 일감 | 내용 | 선행 |
|---|---|---|
| `MIGRATION_BASELINE_COMMAND_IMPLEMENTATION` | §4.3 `migrate.py baseline` 구현·테스트 PR | 이 문서 병합 |
| Staging 실행 승인 | Redmine DB 요청에 §5 항목 기록, PM/JM 승인 | baseline PR 병합 |
| Staging 실행 | §4.4 순서대로 PM/JM 실행, 결과를 이 문서 또는 증적 문서에 기록 | 실행 승인 |
| 보안 개선 | SUPERUSER 사용 축소, 소유권 `career_migrator` 이전, `career_app` LOGIN 매핑 (T07) | 별도 |
