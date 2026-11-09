# T12 — Staging Migration·Seed 기존 증빙 재사용 및 적용 전 점검

> Redmine: T12 (초기 30개 작업) · 기준: `main` `6632fb9839654d88d2c375a51fc198b5dc0485d7` (2026-11-09 조회)  
> **T12_STATUS=PARTIAL — GitHub 문서·코드·CI 증빙 정리만 완료. Staging 실DB 변경/최신 상태 조회/적용 증빙은 미확인.**  
> 이 문서는 실제 Staging 적용 완료 보고서가 아니다. 이번 PR에서 SQL 실행, DB/볼륨 변경, 계정 변경, 서비스 재시작을 수행하지 않았다.

## 1. 목적·범위

PM이 앞서 작성·검증한 스키마·권한·Seed와 CI를 반복 구현하지 않고 T12에서 재사용한다. **Staging 적용 대상 DB의 현재 상태**, 최신 백업 및 격리 복원, 실제 적용/검산/서비스 정상화 여부만 별도 확인한다. 기존 DB에 테이블이 있다면 초기 `0001_initial_schema.sql`을 무조건 재실행하지 않는다.

## 2. 기존 검증 근거 (재사용 가능)

| 항목 | 확인된 근거 | T12에서의 의미 |
|---|---|---|
| T07 권한 모델 | PR [#46](https://github.com/ai-career-platform/ai-career-platform/pull/46) 병합, 격리 권한 테스트 | 역할 설계/테스트 재사용. Staging 실제 LOGIN 매핑은 별개 |
| T08 러너 | PR [#39](https://github.com/ai-career-platform/ai-career-platform/pull/39) 병합; PostgreSQL 18.1 CI PASS | forward-only, 트랜잭션·체크섬·staging guard 코드 재사용 |
| T09 정식 DDL | PR [#45](https://github.com/ai-career-platform/ai-career-platform/pull/45) 병합; `database/T09_SCHEMA_DIFF.md` | 51개 테이블/76 FK, T05 대비 차이 0건 로컬 보고. **빈 DB 최초 설치 대상** |
| T10 Seed | PR [#34](https://github.com/ai-career-platform/ai-career-platform/pull/34) 병합; PostgreSQL 18.1 T10 전용 CI PASS | 15개 테이블의 합성 멱등 Seed. 기존 실DB 적용 검증과는 구분 |
| T11 통합 검증 | PR [#49](https://github.com/ai-career-platform/ai-career-platform/pull/49) 병합; PostgreSQL 18.1 CI 로그 `T11_SUMMARY pass=176 warn=8` / `T11_FULL_SCHEMA_TEST=PASS` | 51개 테이블·권한·제약 검증. 경고 8건은 별도 개선 |
| 기존 백업/격리 복원 | `docs/work-orders/crawler-enhancement/T151_STEP05B_BACKUP_RESTORE_PASS.md` | **크롤러 DB 관련 사용자 보고 증빙**. T12 대상 앱 DB의 최신 백업·복원 PASS로 자동 승계 불가 |
| 기존 Staging DB 기록 | `database/FULL_DATABASE_MODEL.md` §1: 2026-11-06 기준 사용자 정의 테이블 0개라고 기록 | 과거 스냅샷일 뿐. 이후 DB 작업이 있어 **현재 상태로 가정 금지** |

## 3. 먼저 해결해야 할 식별·중복 적용 위험

- 문서에 서로 다른 DB가 등장한다. 앱 Staging 예시는 `ai_career_poc` (`database/migrations/README.md`)이고, 크롤러 작업 T151은 `ai_career_crawler_training`을 대상으로 한다. **DB명, 접속 대상, 호스트/컨테이너, 볼륨을 동일한 T12 대상인지 먼저 식별**한다. 서로의 백업·스키마 상태를 혼용하지 않는다.
- T151의 STEP05C 문서에는 '기존 앱 51개 테이블 보존'이라고 기재돼 있으나, T12 대상 DB의 현재 `career` 스키마 테이블 수와 Migration ledger는 GitHub 코드만으로 확정되지 않는다.
- `0001_initial_schema.sql`은 초기 설치형 DDL로 `CREATE TABLE`을 사용한다. 기존 테이블이 있으면 중복 실행 금지. ledger가 없는데 테이블이 있다면 임의로 이력 INSERT하거나 DROP/CREATE 하지 말고 **상태를 HOLD**로 기록한다.
- T10 `0001_initial_seed.sql`은 로컬/일회용 검증을 기준으로 작성됐다. 스키마 일치, 기존 데이터 충돌 여부를 분리 확인하고 공유 Staging에 즉시 투입하지 않는다.

## 4. T12 최소 사전 점검 (읽기 전용)

아래는 **실제 실행하지 않은** 실행 템플릿이다. 이미 연결된 PM/운영 환경의 읽기 전용 `psql`에서 **T12 앱 대상 DB를 확정한 후에만** 사용한다. DB 비밀번호/접속 문자열 원문을 PR에 남기지 않는다.

```sql
SELECT current_database() AS db_name, current_user AS login_role,
       current_setting('server_version') AS pg_version;
SELECT nspname FROM pg_namespace WHERE nspname IN ('career', 'career_migration');
SELECT count(*) AS career_tables
  FROM pg_tables WHERE schemaname = 'career';
SELECT to_regclass('career_migration.schema_migrations') AS migration_ledger;
SELECT to_regclass('career.users') AS users_table,
       to_regclass('career.job_postings') AS postings_table;
```

`migration_ledger`가 존재하고 조회 권한이 있을 때만 이력 조회:

```sql
SELECT version, name, checksum, applied_at
  FROM career_migration.schema_migrations ORDER BY version;
```

추가로 최신 동일 DB·볼륨의 백업 파일/해시 및 **격리 복원 PASS**, 기존 데이터 건수/지문, Backend `/api/health/db` 등 실제 서비스 경로의 변경 전 상태를 확인한다. 현재 파일상 경로는 `poc/staging/README.md`의 PoC 예시이며 실제 배포 URL/구조는 별도 확인한다.

## 5. 적용 분기·중단 조건

| 읽기 전용 조사 결과 | 다음 결정 |
|---|---|
| 대상 DB 식별 불명, 백업 미확인, 격리 복원 미확인 | **HOLD**. DB 변경 없음 |
| `career` 테이블 0개, ledger 미적용 | T07/T08 bootstrap 경계와 T09 적용 준비 가능 여부만 판단. 실제 적용은 별도 실행 단계 |
| 기존 `career` 테이블 존재 + `0001` ledger 존재 | `migrate.py status/verify` 결과와 체크섬 확인. **초기 DDL 재실행 금지** |
| 기존 테이블 존재 + ledger 없음/불일치 | **HOLD**. 삭제/초기화/수동 이력 조작 없이 출처·스키마 일치 조사 |
| 기존 데이터/크롤러 DB와 앱 DB 경계 불명 | **HOLD**. 접근 대상 재식별 |
| Seed가 이미 존재 | 데이터 중복·업데이트 영향 확인 후 대상 Seed만 검증. 수량만으로 무조건 재삽입하지 않음 |

금지: `docker compose down -v`, 볼륨 삭제, 원본 DB 초기화, 파괴적 스키마 변경, 무검증 Seed 강제 적용, 계정 비밀번호·민감 로그 커밋.

## 6. T12 실제 완료 시에만 기입할 Evidence

| 필드 | 현재 | 실제 완료 기준 |
|---|---|---|
| T12 대상 DB/볼륨 식별 | NOT_VERIFIED | 실제 대상 식별값(비밀 마스킹) |
| 변경 전 앱 테이블 수·ledger | NOT_VERIFIED | 읽기 전용 출력 및 timestamp |
| 최신 동일 DB 백업/해시 | NOT_VERIFIED | 실제 파일/해시 검증 |
| 동일 DB 격리 복원 | NOT_VERIFIED | 독립 복원 결과 PASS |
| 정식 `0001` 적용 또는 기존 상태 인정 | NOT_VERIFIED | migration status/verify 및 ledger 증빙 |
| T10 Seed 실제 적용 여부/검산 | NOT_VERIFIED | `verify_seed.sql` 결과 또는 미적용 사유 |
| 기존 데이터 보존 | NOT_VERIFIED | 전후 건수·지문 비교 |
| Backend health/서비스 정상화 | NOT_VERIFIED | 변경 전후 응답·시각 |
| 다운타임 | NOT_VERIFIED | 실제 시각 또는 '없음' 근거 |
| Staging DB 변경 | **NO (이번 GitHub PR 범위)** | DB 변경 별도 실행 기록 |

## 7. 결론

**코드/CI 선행 조건은 재사용 가능, 실제 T12 Staging 실행 DoD는 아직 검증되지 않았다.**
따라서 이 PR은 **T12 준비·증빙 재사용 PR**이며 T12 전체 종료/DB 적용 승인 PR로 해석하지 않는다. 실제 실행 환경의 읽기 전용 결과와 복원·적용·검산 결과가 확보되면 같은 문서에 팩트만 추가하여 `PASS` 여부를 판정한다.

```text
TASK=T12
SOURCE_MAIN_SHA=6632fb9839654d88d2c375a51fc198b5dc0485d7
PREDECESSORS=T07,T08,T09,T10,T11_MERGED
PR_SCOPE=EVIDENCE_REUSE_ONLY
STAGING_DB_READ=NOT_VERIFIED
STAGING_BACKUP_RESTORE=NOT_VERIFIED_FOR_T12_TARGET
STAGING_MIGRATION=NOT_EXECUTED
STAGING_SEED=NOT_EXECUTED
STAGING_CHANGED=NO
T12_STATUS=PARTIAL
BLOCKER=TARGET_DB_CURRENT_STATE_AND_T12_SPECIFIC_BACKUP_RESTORE_AND_APPLY_EVIDENCE
```
