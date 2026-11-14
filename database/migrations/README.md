# DB Migration 실행 가이드 (T08)

> 상태: **DRAFT / PM 검토 필요**. 이 문서와 `database/migrate.py`는 공유 Staging DB를 변경하지 않습니다.
> 기존 `DRAFT_0001_initial_schema.sql`은 검증용으로 그대로 두며, 러너가 적용하지 않습니다.

## 1. 결정 요약 (리뷰 대상)

| 항목 | 제안 | 이유 |
|---|---|---|
| 도구 | 순수 SQL 파일 + `database/migrate.py` (Python 표준 라이브러리, `psql` 사용) | 기존 DRAFT·CI·T05 데이터 사전이 SQL 기반이고 리뷰어가 DDL을 그대로 읽을 수 있음. 드라이버 설치 불필요. SQLAlchemy 도입(#44) 후에도 스키마의 단일 기준은 SQL migration (§7 참고) |
| 방향 | **Forward-only** (down 스크립트 없음) | 운영 DB의 down은 데이터 손실 위험. 되돌릴 때는 "수정 migration" 또는 백업 복원 |
| 이력 | `career_migration.schema_migrations` | 앱 역할(`career_app`)은 `career` 스키마 테이블에 기본 CRUD를 받으므로, 이력은 앱이 접근할 수 없는 별도 스키마에 둠 |
| 원자성 | migration 1개 = 트랜잭션 1개 (SQL + 이력 기록 함께 커밋) | 실패하면 둘 다 롤백, 다음 파일은 실행하지 않음 |
| 변경 감지 | SHA-256 체크섬 (CRLF→LF 정규화) | 적용 후 파일을 고치면 `DRIFT`로 차단. Windows/Linux 체크아웃 결과 동일 |
| 소유자 | 실행 시 `SET ROLE career_migrator` | 테이블 소유자가 migrator가 되어 DRAFT_00의 기본 권한(app CRUD, reader SELECT)이 적용됨 |
| Staging | 수동 실행만, 승인번호·DB 이름 확인 필수, CI에서 실행 거부 | 자동 배포와 Migration 연결 금지 정책(docs/DATABASE.md) |

## 2. 파일 규칙

```
database/
  migrate.py                         # 러너
  migrations/
    DRAFT_0001_initial_schema.sql    # 검증용 초안 (러너 대상 아님)
    0001_initial_schema.sql          # ← T09가 승인 후 작성할 첫 번째 정식 migration
    0002_....sql
  security/
    DRAFT_00_create_roles_schema.sql # 관리자: 역할·career 스키마
    DRAFT_01_migration_history.sql   # 관리자: 이력 스키마·테이블 (T08)
```

- 이름: `NNNN_snake_case.sql` (4자리, 0001부터, 중복 금지). 다른 이름은 lint 실패.
- 상단 20줄 안에 필수 헤더:
  ```sql
  -- Purpose: 무엇을 왜 바꾸는지 (Redmine #번호)
  -- Recovery: 실패/문제 시 복구 방법 (예: 0005에서 컬럼 제거, 또는 백업 복원)
  ```
- `DROP TABLE/COLUMN/SCHEMA`, `TRUNCATE` 등 파괴적 SQL은 `-- Destructive-Approval: <PM 승인번호>` 헤더 필요.
- 금지: `BEGIN/COMMIT/ROLLBACK`(러너가 감쌈), `\` psql 메타명령, `CONCURRENTLY`, `SET ROLE`, `PASSWORD`, `CREATE/DROP DATABASE`.
- **이미 적용된 파일은 수정하지 않습니다.** 고칠 내용은 새 번호 파일로 추가합니다.
- 가장 최근 적용 번호보다 작은 새 파일은 `OUT-OF-ORDER`로 거부됩니다. 브랜치 병합 후 번호가 겹치면 뒤 번호로 다시 매깁니다.

## 3. 로컬 사용법 (Windows PowerShell + Docker)

[DB 개발환경 가이드](../../docs/development/DB_DEVELOPMENT_SETUP.md) STEP 05의 `career-dev-db` 컨테이너 기준입니다.

```powershell
# 1) 최초 1회: 관리자 bootstrap (역할·스키마·이력 테이블). 재실행해도 안전.
Get-Content .\database\security\DRAFT_00_create_roles_schema.sql -Raw | docker exec -i career-dev-db psql -X -v ON_ERROR_STOP=1 -U dev_local -d career_dev
Get-Content .\database\security\DRAFT_01_migration_history.sql -Raw | docker exec -i career-dev-db psql -X -v ON_ERROR_STOP=1 -U dev_local -d career_dev

# 2) 러너가 사용할 psql 지정
$env:MIGRATE_PSQL = "docker exec -i career-dev-db psql -U dev_local -d career_dev"

# 3) 확인 → 적용
python database\migrate.py lint
python database\migrate.py status
python database\migrate.py apply --target local --dry-run
python database\migrate.py apply --target local
python database\migrate.py verify
```

Linux/macOS는 `export MIGRATE_PSQL="psql -h 127.0.0.1 -p 25432 -U dev_local -d career_dev"` 처럼 지정합니다. 비밀번호는 `PGPASSWORD`/`.pgpass`로 전달하고 Git에 넣지 않습니다.

| 명령 | 설명 | DB 필요 |
|---|---|---|
| `lint` | 파일 이름·헤더·금지 SQL 검사 | ✗ |
| `status` | 적용/대기/DRIFT/OUT-OF-ORDER 목록 | ✓ |
| `verify` | DRIFT·순서 문제 있으면 실패(exit 1) | ✓ |
| `apply --target local\|ci\|staging [--to 0003] [--dry-run]` | 대기 중 migration을 번호 순서로 적용 | ✓ |

## 4. 실패·복구 전략

1. **적용 중 실패**: 해당 migration과 이력 행이 함께 롤백되고, 뒤 파일은 실행하지 않습니다. 원인을 고친 뒤 같은 파일을 다시 실행합니다(아직 미적용이므로 수정 가능).
2. **적용 후 문제 발견**: 적용된 파일은 수정하지 않고, 되돌리는 내용을 담은 새 migration을 추가합니다.
3. **데이터 손상 등 복구 불가**: Staging 적용 전 백업(T114 범위)을 복원합니다. 백업·복원 확인 없이는 Staging에 적용하지 않습니다.
4. **동시 실행**: 트랜잭션마다 `pg_advisory_xact_lock`을 잡고, 이력 PK와 사전 검사로 같은 번호의 중복 적용을 막습니다.
5. 잠금 대기 10초(`lock_timeout`), 문장 15분(`statement_timeout`) 초과 시 실패·롤백합니다.

## 5. Staging 적용 절차 (PM/JM 지정 실행자만)

```bash
python database/migrate.py apply --target staging --approval REDMINE-1522 --confirm-db ai_career_poc --dry-run
python database/migrate.py apply --target staging --approval REDMINE-1522 --confirm-db ai_career_poc
```

- 러너는 다음 경우 실행을 거부합니다: CI 환경(`CI`/`GITHUB_ACTIONS`), 승인번호 누락, `--confirm-db`와 실제 DB 이름 불일치, `ai_career_poc`에 `local`/`ci` 대상으로 접속.
- 선행: Redmine DB 요청 → PR 리뷰·Merge → 백업 확인 → 지정 실행자 실행 → `verify` → 결과 기록 ([DATABASE.md](../../docs/DATABASE.md)).
- `docker compose down -v` 금지, Staging 자동 배포 파이프라인에 이 러너를 연결하지 않습니다.

## 6. 테스트

```bash
python3 -B -m unittest database/tests/test_migration_runner.py -v      # lint 단위 테스트
MIGRATION_TEST_ADMIN_PSQL="psql -h localhost -U postgres" \
  python3 -B -m unittest database/tests/test_migration_runner.py -v    # + 일회용 DB 통합 테스트
```

통합 테스트는 테스트마다 새 데이터베이스를 만들고 지웁니다. **일회용 PostgreSQL에만** 사용하세요. CI는 `.github/workflows/db-migration-runner-test.yml`에서 `postgres:18.3` 서비스 컨테이너(GCP Cloud SQL과 같은 마이너 버전)로 실행합니다.

검증 항목: 신규 설치(DRAFT 10개 테이블 재현·소유자·권한), 재실행 no-op, 실패 시 롤백·중단, 체크섬 DRIFT 차단, 순서 위반 거부, `--to`/`--dry-run`, 트랜잭션 내 중복 적용 차단, Staging 안전장치, 이력 테이블 앱 변경 차단.

### GCP 적용 리허설 (#344)

`database/tests/test_t344_gcp_pg18_rehearsal.py`는 GCP Cloud SQL `ai_career_poc`의 현재 상태를 재현하고, 계획된 적용 절차를 같은 순서로 실행합니다.

- 재현하는 상태
  - 소유자 `ai_career_poc` NOLOGIN
  - 0001은 실행기 밖에서 생성됨
  - 이력 테이블 없음
  - 실행자는 슈퍼유저가 아닌 구성원
- 검증 순서
  1. [`GCP_01_migration_history_bootstrap.sql`](../security/GCP_01_migration_history_bootstrap.sql)로 0001 baseline 등록
  2. `migrate.py --role ai_career_poc --target staging`로 0002·0003 적용
  3. 실행기만으로 만든 0001~0003 기준 DB와 스키마 서명 비교

데이터는 합성 seed만 쓰고, 클라우드에는 접속하지 않습니다. bootstrap SQL은 **제안안이며 운영에 적용하지 않았습니다**. 운영 적용에는 별도 PM 승인이 필요합니다.

## 7. SQLAlchemy·Pydantic과의 역할 분리

Backend API는 SQLAlchemy 2.0 + Pydantic 2로 작성합니다(PM 공지, #44). 스키마 기준이 두 곳으로 나뉘지 않도록 아래처럼 역할을 나눕니다.

| 담당 | 하는 일 | 하지 않는 일 |
|---|---|---|
| SQL migration (`database/migrations/`) | 테이블·컬럼·제약조건·인덱스 생성/변경 (스키마의 단일 기준) | 애플리케이션 데이터 처리 |
| SQLAlchemy 모델 (`backend/app/...`) | 이미 존재하는 테이블을 매핑해 조회·저장 | 테이블 생성/변경 |
| Pydantic 스키마 | API 요청·응답 DTO 검증 | DB 구조 정의 |

- 공용/Staging DB에서 `Base.metadata.create_all()`·`drop_all()`을 호출하지 않습니다. 테스트에서만 일회용 DB에 한해 사용할 수 있습니다.
- 모델에 컬럼이 필요하면 **먼저 migration PR**을 올리고, 모델 변경은 같은 PR 또는 후속 PR에서 migration과 일치시킵니다.
- 모델의 `__table_args__ = {"schema": "career"}`, 컬럼 타입·NULL 여부·제약 이름은 migration SQL과 동일하게 맞춥니다.
- Alembic으로 전환할지는 PM 결정 사항입니다. 전환하더라도 이미 적용된 SQL migration 이력(`career_migration.schema_migrations`)을 기준선으로 이어받는 방식을 권장합니다.

## 8. 미결정·후속 (리뷰 요청)

- T07(DB 계정·권한) 결과에 따라 실제 LOGIN 계정과 `career_migrator` 부여 방식 확정.
- `CREATE INDEX CONCURRENTLY` 같은 비트랜잭션 migration 지원 여부 (T99 인덱스 작업 때 필요할 수 있음).
- T09의 `0001_initial_schema.sql`은 T05 ERD 승인 후 작성. DRAFT_0001과의 관계는 "DRAFT는 참고용, 0001이 정식"으로 제안.
- Seed(T10)는 migration과 분리 유지 제안 (idempotent seed 별도 실행).
