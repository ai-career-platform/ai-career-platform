# T09 스키마 비교 결과

Redmine #1522 · `database/migrations/0001_initial_schema.sql`

- 기준 설계는 T05 병합 커밋 `a004efb`의 데이터 사전과 ERD다. 검증 작업의 기준 `main`은 `704f413`이다.
- T08 PR #39의 러너 커밋 `a7735df87110b98ef0cd8faa580f0b436f3f7d56`로 검증했다.
- 검증 SQL의 SHA-256은 `bf592121befe1cfca9010d601e2f5af33af654461fba0bf930a3fb7249bc9d38`이다.

## PostgreSQL 18.1 격리 검증

| 항목 | 결과 |
|---|---|
| T08 lint 및 dry-run | `0001` 한 파일 인식. 기존 DRAFT 파일은 적용 대상에서 제외 |
| 신규 적용과 재실행 | 최초 1건 적용, 재실행 시 추가 적용 0건, `verify` 통과 |
| 적용 이력 | `career_migration.schema_migrations`에 `0001` 1건 |
| 테이블 및 소유자 | 51개, 전부 `career_migrator` 소유 |
| FK | 76개 |
| 스키마 비교 | T05 검증용 DDL과 `career`의 `pg_dump --schema-only --no-owner --no-privileges` 결과 일치. 컬럼, 기본값, 제약조건 및 인덱스 차이 0건 |
| 계약 케이스 | 정상 입력, 위반 거부 17건, 계정 삭제 후 개인 데이터 정리 및 감사 기록 익명화 통과 |

소유자는 스키마 덤프 비교와 별도로 조회했다. 기존 계약 테스트의 임시 복사본에서 예상 예외 목록에 PostgreSQL 18.1의 `restrict_violation`을 추가해 실행했다. 기존 T05 테스트 파일은 별도 수정이 필요하다. 전체 T09 상태는 PR 리뷰와 CI 확인 전까지 `PARTIAL`이다.

## 재현 절차

1. PostgreSQL 18.1의 새 일회용 DB 두 개를 준비한다. 후보 DB에 `database/security/DRAFT_00_create_roles_schema.sql`과 T08의 `database/security/DRAFT_01_migration_history.sql`을 관리자 계정으로 순서대로 적용한다. 각 파일은 `psql -X -v ON_ERROR_STOP=1 -f <파일>`로 실행한다.
2. `MIGRATE_PSQL`을 후보 DB에 연결하는 `psql` 명령으로 지정한다. T08 러너를 별도로 체크아웃한 경우 `--dir`에는 T09 브랜치의 마이그레이션 폴더를 지정한다.

   ```text
   python <T08의 migrate.py 경로> --dir database/migrations lint
   python <T08의 migrate.py 경로> --dir database/migrations apply --target local --dry-run
   python <T08의 migrate.py 경로> --dir database/migrations apply --target local
   python <T08의 migrate.py 경로> --dir database/migrations apply --target local
   python <T08의 migrate.py 경로> --dir database/migrations verify
   ```

3. 기준 DB에 `CREATE SCHEMA career`를 실행하고 `python database/model/check_data_dictionary.py --ddl`의 출력을 적용한다. 두 DB에 `pg_dump -d <DB> --schema=career --schema-only --no-owner --no-privileges --restrict-key=t09compare`를 실행하고 출력을 비교한다.
4. `database/tests/t05_contract_cases.sql`을 복사하고 `expect_error`의 `WHEN` 목록에 `OR restrict_violation`을 추가한다. 복사본을 후보 DB에서 `psql -X -v ON_ERROR_STOP=1 -f <복사본>`으로 실행한다.
