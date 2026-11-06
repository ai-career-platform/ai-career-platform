# T11 제약조건·인덱스·권한 테스트 결과

- 대상: T09 PR #45 `database/migrations/0001_initial_schema.sql` (브랜치 `task/t09-schema-ddl`, 커밋 `da01951`)
- 테스트: `database/tests/test_full_schema.sh`, `database/tests/test_full_schema.sql`
- 환경: 일회용 `postgres:18.1` 컨테이너(`sha256:1090bc3a…bd17f`). 공유 Staging DB는 사용하지 않았다.
- 상태: `T11_STATUS=PARTIAL` (로컬 PASS, T09·T08 미머지, PR 리뷰와 CI 확인 전)

## 실행 방법

```bash
D1_TEST_ONLY=YES bash database/tests/test_full_schema.sh
```

Windows Git Bash에서는 경로 변환을 끄고 실행한다: `MSYS_NO_PATHCONV=1 D1_TEST_ONLY=YES bash database/tests/test_full_schema.sh`

스크립트는 `DRAFT_00_create_roles_schema.sql`을 적용한 뒤 `0001_initial_schema.sql`을 `career_migrator`로 적용한다.
T08 러너(PR #39)가 아직 병합되지 않아 `psql`로 직접 적용한다. 실패하면 첫 오류에서 멈춘다(`ON_ERROR_STOP=1`).

## 결과 요약

`T11_SUMMARY pass=176 warn=8`, `T11_FULL_SCHEMA_TEST=PASS`

| 구분 | 내용 | 결과 |
|---|---|---|
| 구조 | 테이블 51개, 소유자 `career_migrator`, 모든 테이블 PK | PASS |
| 개수 고정 | FK 76, CHECK 64, UNIQUE 제약 6, 인덱스 135(PK·UNIQUE 포함) | PASS |
| 권한 (카탈로그) | 51개 테이블 × reader/app × 7개 권한, PUBLIC grant 없음, schema CREATE 없음 | PASS |
| 권한 (실행) | reader INSERT/UPDATE/DELETE, app TRUNCATE/CREATE/DROP/ALTER, 무권한 role SELECT 거부 | 8건 거부 PASS |
| NOT NULL | 51개 테이블 전체에 빈 행 INSERT 거부 | 51건 PASS |
| FK | 없는 부모 참조 거부 (복합 FK 포함) | 6건 PASS |
| UNIQUE/PK | 단일·복합·부분 UNIQUE 중복 거부 | 17건 PASS |
| CHECK·경계값 | enum, 범위, 날짜 순서, 최소/최대 통과와 한 단계 밖 거부 | 거부 42건 + 길이 초과 3건, 허용 15건 PASS |
| ON DELETE | RESTRICT 7건 거부, CASCADE 자식 삭제, SET NULL 참조 유지 | PASS |
| 계정 삭제 | agent run → approval → tool call(RESTRICT 참조)까지 사용자 삭제로 정리 | PASS |
| 트랜잭션 보존 | 다중 행 INSERT 일부 실패 시 부분 반영 없음, 오류 난 트랜잭션은 COMMIT 시 전체 롤백 | PASS |
| EXPLAIN | 주요 조회 15개가 의도한 인덱스 사용 (`enable_seqscan=off`, 합성 리터럴만 사용) | PASS |

## 발견 사항 (WARN, T09 검토 요청)

1. **FK 인덱스 누락 7건**: 부모 행을 삭제·수정할 때 자식 테이블을 전체 스캔한다. 부분 인덱스는 조건이 달라 FK 검사에 쓰이지 않는다.
   - `auth_sessions(user_id)`: `WHERE revoked_at IS NULL` 부분 인덱스만 있음
   - `password_reset_tokens(user_id)`: `WHERE used_at IS NULL` 부분 인덱스만 있음
   - `account_deletion_requests(user_id)`: `WHERE status = 'requested'` 부분 UNIQUE만 있음
   - `user_roles(granted_by_user_id)`
   - `user_consents(policy_code, policy_version)`
   - `companies(source_id)`
   - `job_postings(source_id)`
2. **`market_observations` 중복 허용**: `job_role_id`가 NULL(전체 직무 지표)이면 `ix_market_observations_1`이 중복을 막지 못한다. UNIQUE 인덱스에서 NULL은 서로 다른 값으로 취급되기 때문이다. `NULLS NOT DISTINCT` 사용 여부를 결정해야 한다.

두 항목 모두 실패로 처리하지 않았다. 스키마 변경 여부는 T09 담당자와 리뷰어가 정한다.

## 참고와 미확정 항목

- T05 테스트는 `restrict_violation`을 예상 오류에 넣지 않았다. T11은 ON DELETE RESTRICT 위반을 PostgreSQL 18.1의 `23001`로 검증한다.
- `status = 'requested'`인 삭제 요청 조회는 부분 UNIQUE 인덱스 `ix_account_deletion_requests_1`을 사용한다. `ix_account_deletion_requests_2`는 다른 상태 조회로 검증했다.
- T09가 리뷰에서 바뀌면 개수 고정값(76/64/6/135)과 관련 케이스를 함께 수정해야 한다.
- FK 인덱스 누락을 실패로 볼지 경고로 볼지는 팀 결정이 필요하다.
