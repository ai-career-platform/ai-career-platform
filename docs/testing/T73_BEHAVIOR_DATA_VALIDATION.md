# T73 — 행동 데이터 품질·보존·삭제 검증 보고서

> 상태: **PARTIAL** — 코드·격리 DB 검증 PASS / T71 정책 미승인 / 보존 기간 미확정 / Staging 미적용
> 테스트 PASS는 **운영 준비 완료를 뜻하지 않는다.** 실제 사용자 추적·운영 삭제·스케줄 연결은 모두 꺼져 있다.
> 위치: 요청은 `docs/qa/`였으나 저장소의 테스트 보고서 표준 위치인 `docs/testing/`에 둔다.

## 1. 작업 목표·기본 정보

| 항목 | 값 |
|---|---|
| 작업 | T73 (P1, F-025) · 담당 문길래 · 리뷰 Crasnec |
| 작업지시서 | [T73](../work-orders/remaining-30/T73.md) |
| 기준 main | `0f771f200238f6ed57b1941c63e7d63178ac3ce7` (T72 #179 Squash Merge) |
| 브랜치 / HEAD | `task/t73-behavior-quality-retention` / PR head 참조 |
| 실행일 | 2026-11-10 KST, Windows 11, Python 3.12, PostgreSQL 18.6 (로컬 일회용, 127.0.0.1) |
| 목표 | 행동 이벤트 품질 검출(중복·결측·불법 필드·시각·동의·삭제 상태), 보존 기간 만료 삭제 job, 철회·탈퇴 삭제 전파와 감사 증빙 검증 |

## 2. 기준 main SHA

`0f771f200238f6ed57b1941c63e7d63178ac3ce7` — 작업 시작 시 `git fetch` 후 확인, PR 생성 직전 다시 확인(PR 본문 참조).

## 3. T71/T72 선행 상태

| 선행 | 상태 | 영향 |
|---|---|---|
| T71 행동 이벤트 계약 (#36) | **DRAFT / NOT APPROVED** | 8종 목록·180일 보존·personalization 정책 모두 가안. 운영값으로 쓰지 않음 |
| T72 수집 API (#179) | **MERGED** `0f771f2` | 수집 기본 꺼짐. 이 PR은 T72 경로를 재사용·검증만 함 |
| T31 동의·탈퇴 API | main 반영 | 탈퇴 요청 = 계정 비활성화 + 세션 폐기 (물리 삭제 아님, D-06 미확정) |
| 0001 `behavior_events` | `event_id, user_id, event_code, event_at, metadata`만 있음 | `retain_until`·저장 시각·`policy_code` 없음 → 스키마 변경 없이 설계 (§6) |
| 0001 `audit_events` | 최소 컬럼(`action_code, resource_type, resource_id, request_id, occurred_at`) | 건수·결과 칸 없음 → 감사 행 + JSON 증빙 병행 (§11) |

## 4. 재사용한 코드 (새로 만들지 않음)

| 기능 | 재사용 위치 |
|---|---|
| 서버 측 최신 동의 확인, 사용자 행 잠금, uuid5 중복 방지, 동의 이전 이벤트 재전송 차단 | `app/services/behavior_events.py` (T72) — T73은 이 경로로만 수집 |
| 철회 시 tracking 이벤트 삭제 | `PrivacyService.record_consent()` + `SqlPrivacyRepository.delete_behavior_events()` (T72) — 직접 검증, 새 삭제 로직 없음 |
| 허용 이벤트·metadata 키·값 규칙·1KB·10키 | `app/schemas/behavior_events.py` 상수를 품질 SQL 파라미터로 그대로 전달 |
| 격리 DB fixture | `pg_app`(T16) → `behavior_pg`(T72) |
| 배치 실행 안전장치 | T66 `market_aggregation`의 `SAFE_ENVS`·loopback 규칙과 같은 방식 |
| 탈퇴 접수 | T31 `POST /me/deletion-request` (migration 0002 전제, T31 fixture와 동일하게 적용) |

## 5. 품질 검증 규칙 (`python -m app.behavior_data quality`, 읽기 전용)

`SET TRANSACTION READ ONLY` 트랜잭션에서 한 번 조회하고 롤백한다. **유형별 건수만** 출력하고 user_id·metadata 원본은 내보내지 않는다(테스트로 확인).

| 항목 | 검출 키 | 구분 |
|---|---|---|
| 중복 저장 키 | `duplicate_storage_key` | **DB 강제**(기본키). 0이어야 정상. 동일 클라이언트 재전송은 T72 uuid5 키로 `duplicate` 처리 |
| 필수값 결측 | `missing_required` | **DB 강제**(NOT NULL) |
| 사용자 참조 | `orphan_user` | **DB 강제**(FK, CASCADE) |
| 이벤트 코드 | `unknown_event_code`, `unapproved_event_code` | 앱 계약. personalization 3종이 저장돼 있으면 미승인 위반 |
| metadata | `metadata_not_object`, `metadata_key_not_allowed`, `metadata_value_invalid`, `metadata_too_many_keys`, `metadata_too_large`, `metadata_empty_object` | 앱 계약 (T72는 빈 객체를 NULL로 저장) |
| event_at | `event_at_future` (기준 시각 + 5분 초과) | 앱 계약. **7일 창은 수집 시점 규칙이라 과거 정상 행에 적용하지 않음**(테스트로 60일 전 정상 행 PASS 확인) |
| 수집 당시 동의 | `no_consent_at_event_time` | 이벤트 시각 이전 마지막 `behavior_tracking` 기록이 true가 아니면 위반 |
| 현재 삭제 상태 | `retained_without_current_consent` | 현재 최신 동의가 true가 아닌데 남은 tracking 행 (철회 후 잔존 포함) |
| 경고 | `same_payload_groups` | 같은 사용자·코드·시각·metadata 묶음. 정상일 수 있어 오류로 세지 않음 |

자동 수정 기능은 없다. 오류가 있으면 종료 코드 1.

## 6. 보존 기간 검증 (`python -m app.behavior_data purge`)

- **보존 기간 기본값 없음.** `--retention-days`와 `--as-of`(시간대 필수)를 반드시 받는다. 180일은 테스트 fixture 값일 뿐 운영값이 아니다.
- **기준 시각 결정:** T71은 `retain_until = 수집 시각 + 보존 기간`인데 0001에는 수집 시각이 없다. T72는 수집 시각보다 최대 7일 이른 `event_at`을 받으므로 `event_at < as_of − retention_days − 7일`인 행만 대상으로 한다. 계약보다 **먼저 지우는 일은 없고**, 최대 7일 늦게 지워질 수 있다. 정확한 기한은 `retain_until`(또는 `recorded_at`) 컬럼 Migration이 필요 — **후속 결정**.
- 기본 dry-run(대상 건수만, 쓰기·감사 행 없음). `--execute`는 `APP_ENV=local-dev|test` + loopback PostgreSQL에서만 허용, 그 외는 DB 연결 전에 종료.
- 한 트랜잭션: 대상 계산 → 삭제 → 감사 행 → 잔존 재확인(0이 아니면 실패) → 커밋. 실패 시 전부 롤백하고 `status=FAIL`, `deleted=0`.
- 운영 스케줄러·cron 연결 없음.

## 7. 철회 삭제 검증 (T72 경로 직접 검증)

| # | 항목 | 테스트 | 결과 |
|---|---|---|---|
| 1 | 동의 없는 사용자 이벤트 0건 | `test_withdrawal_and_reconsent_flow…` | PASS |
| 2 | 동의 후 정상 수집 | 같은 테스트, T72 `test_actual_consent_gate…` | PASS |
| 3 | 철회 시 해당 사용자 이벤트 삭제 | 같은 테스트 | PASS |
| 4 | 다른 사용자 이벤트 유지 | 같은 테스트 (B 1건 유지) | PASS |
| 5 | 철회 후 신규 수집 차단 | 같은 테스트 | PASS |
| 6 | 재동의 후 신규 이벤트 허용 | 같은 테스트 | PASS |
| 7 | 철회 전 이벤트 재전송 차단(복원 없음) | 같은 테스트 | PASS |
| 8 | 철회·수집 동시성 | T72 `test_actual_withdrawal_waits_for_inflight_collection…`(INSERT 직전 결정적 정지 → 철회가 행 잠금 대기 → 0건) + 동시 시작 5회 | PASS (T72에서 잠금 제거 시 실패 확인) |
| 9 | 삭제 중 오류 시 동의 변경까지 롤백 | `test_withdrawal_delete_failure_rolls_back_the_consent_change` | PASS (503, 최신 동의 true 유지, 이벤트 1건 유지) |
| 10 | 반복 철회 시 잔존 0건 | `test_repeated_withdrawal_leaves_zero…` (앱 우회 잔존 행도 재철회로 삭제, 이력 중복 없음) | PASS |

## 8. 계정 탈퇴 및 삭제 전파

| 항목 | 결과 |
|---|---|
| 탈퇴 요청 → 계정 `disabled`, 신규 이벤트 401 | PASS |
| 탈퇴 요청 시 기존 이벤트 | **남아 있음** (T31은 비활성화만, 물리 삭제는 D-06 30일 가안·미확정). 탈퇴 대기 기간의 행동 데이터 처리 정책은 HOLD |
| 사용자 물리 삭제(합성 사용자, 일회용 DB) → 이벤트·동의 이력 CASCADE 0건 | PASS |
| 다른 사용자 이벤트·동의 보존 | PASS |
| 물리 삭제 트랜잭션 롤백 시 아무것도 지워지지 않음 | PASS |
| 탈퇴 접수 중 오류 롤백 | T31 회귀 `test_actual_deletion_final_revoke_error_rolls_back_every_change` PASS |

## 9. PostgreSQL 테스트 (`tests/test_behavior_data_postgres.py` 17건)

| 테스트 | 기대 | 결과 |
|---|---|---|
| 정상 이벤트 (API) | 품질 PASS | PASS |
| 동일 event_id 재전송 | `duplicate`, 1건 | PASS |
| 필수값 누락·없는 사용자 (3종) | DB 거부, 품질 0 | PASS |
| 동일 저장 키 | PK 거부 | PASS |
| 불법 metadata·코드·미래 시각·동의 없음 (12행) | 유형별 정확한 건수, 출력에 ID·원문 없음 | PASS |
| 과거 시각 정상 행 | 수집 창으로 불량 판정 안 함 | PASS |
| 미래 이벤트 수집 | T72 422 (T72 테스트) | PASS |
| 품질 검사 읽기 전용 | `SET`로 시작, DML 없음 | PASS |
| 만료 경계 ±1초 | 경계 안쪽 보존, 바깥 대상 | PASS |
| Dry-run | 대상 2, 삭제 0, 감사 0 | PASS |
| 실제 격리 삭제 | 대상만 삭제, 감사 1행(run_id) | PASS |
| 재실행 | 추가 삭제 0, PASS | PASS |
| 감사 기록 실패 | 삭제 롤백, FAIL | PASS |
| 삭제 실패 | 롤백, FAIL | PASS |
| 철회 삭제 실패 | 동의 변경 롤백 | PASS |
| 반복 철회 / 철회·재동의 흐름 | 0건 / 복원 없음 | PASS |
| 탈퇴 요청 | 비활성화·401 | PASS |
| 물리 삭제 | CASCADE·타 사용자 보존·롤백 | PASS |
| 잘못된 환경 | 실행 차단 (단위 테스트 + CLI) | PASS |

### 전체 결과

| 범위 | 명령 | 결과 |
|---|---|---|
| T73 단위 | `pytest tests/test_behavior_data.py` | 17 passed |
| T73 PostgreSQL | `pytest tests/test_behavior_data_postgres.py` (격리 DB) | 17 passed |
| T72 단위 / PostgreSQL | `tests/test_behavior_events.py` / `_postgres.py` | 53 / 12 passed |
| T31 | `tests/test_privacy.py tests/test_privacy_postgres.py` | 29 passed |
| T71 동시성 | `D1_TEST_ONLY=YES python -m unittest … test_behavior_concurrency.py` | 2 OK |
| T71 계약 41항목 | `test_behavior_contract.sh` 공용 본문을 로컬 PG 18로 실행 (Docker 없음) | 41/41 PASS |
| Backend 전체 (격리 DB 포함) | `pytest` | 628 passed, 94 skipped / 실패 1·오류 19 |
| main 동일 조건 | `pytest` @ `0f771f2` | 594 passed, 94 skipped / 실패 1·오류 19 (**동일**) |
| Migration 영향 | `python database/migrate.py lint`, `git diff origin/main -- database/migrations` | LINT PASS, 변경 0 |
| OpenAPI | `python docs/api/check_openapi.py` | PASS (API 변경 없음) |

CI에는 격리 PostgreSQL 테스트·T71 셸 계약 테스트가 포함되지 않는다(위 로컬 결과로 구분).

## 10. 실패 및 해결 내역

| 실패 | 원인 | 조치 |
|---|---|---|
| `test_documents.py` 실패 1·오류 19 | Windows에서 `DOCUMENT_STORAGE_ROOT must have mode 0700` | main에서도 같은 결과 → **기존 환경 문제, T73 무관**. CI(Linux)는 통과 |
| 품질 테스트 `no_consent_at_event_time` 기대 3, 실제 2 | 테스트 기대값 오류 (해당 행은 B·동의 30일 전 A 2건) | 기대값 수정. 검사 SQL은 별도 DB에서 행별로 재확인 |
| 탈퇴 요청 503 (IntegrityError) | 0001만 적용된 DB에선 `scheduled_purge_at NOT NULL` → T31 탈퇴는 migration 0002 전제 | T31 fixture와 같이 테스트에서 0002 적용 |
| (참고) T72 보고의 PostgreSQL 건수 | T72 보고서는 "T72 13 + T31 12"로 적었으나 실제 T72 12 + T31 13 (합계 25 동일) | 이 보고서에서 정정 |

## 11. 감사 증빙

- 실제 삭제 1회마다 같은 트랜잭션에서 `career.audit_events` 1행: `action_code=system.behavior.purge`(T83 형식), `resource_type=behavior_event`, `resource_id=run_id`, `request_id=t73-purge:<run_id>`, `actor_user_id=NULL`.
- 건수·결과는 0001 `audit_events`에 칸이 없어 CLI JSON 증빙으로 남긴다: `run_id, operation, dry_run, as_of, retention_days, cutoff, target, deleted, remaining_expired, audit_recorded, status, reason_code`. user_id·metadata·토큰은 없다(테스트).
- **감사 기록 실패 → 삭제 롤백 → `FAIL`/`PURGE_FAILED_*`**. 감사 없는 삭제를 성공으로 보고하지 않는다(PostgreSQL 테스트: INSERT 권한 회수 시 4행 유지).
- dry-run은 DB에 쓰지 않으므로 감사 행이 없다(JSON만).
- 철회 삭제(T31 경로)의 감사 기록(`privacy.consent.update`)은 T83/T84 미구현으로 **HOLD**.

CLI 재현 결과 (일회용 DB, 합성 사용자 1명, as_of 2026-11-10, 180일 fixture → cutoff 2026-05-07):

```text
quality                         → status PASS, total 4, errors 0
purge (dry-run)                 → target 2, deleted 0, audit_recorded false, PASS
APP_ENV=staging purge --execute → "Shared or unset APP_ENV: …" exit 1 (DB 연결 전)
APP_ENV=test purge --execute    → target 2, deleted 2, remaining 0, audit_recorded true, PASS
APP_ENV=test purge --execute    → target 0, deleted 0, PASS (멱등)
남은 행: kept(2026-05-10), recent / audit_events: 2행 system.behavior.purge
```

## 12. 잔여 HOLD

1. T71 이벤트 8종·동의 매트릭스·personalization 정책 PM 미승인
2. 보존 기간(180일 가안) 미확정, `retain_until`/수집 시각 컬럼 Migration 미결정 → 현재 cutoff는 7일 보수 여유 포함
3. 운영 실행 승인·스케줄 연결 없음 (`--execute`는 격리 DB만)
4. 탈퇴 대기 기간 행동 데이터 처리, 물리 삭제 시점(D-06) 미확정
5. 감사 이벤트 확장 컬럼(result·reason·metadata, T83)과 철회 감사 기록(T84) 미구현
6. 파생 데이터(집계·피처·모델) 삭제 반영(T71 §10-6) 범위 밖
7. Staging 적용·E2E: NOT_VERIFIED

## 13. 재현 명령

```bash
# 일회용 loopback PostgreSQL 18 (DB 이름 t16_profile_test; 기존 T16 fixture 규칙)
cd backend
python -m pytest tests/test_behavior_data.py
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<admin>@127.0.0.1:<port>/t16_profile_test \
  python -m pytest tests/test_behavior_data_postgres.py tests/test_behavior_events_postgres.py tests/test_privacy_postgres.py

# CLI (DATABASE_URL은 일회용 DB)
python -m app.behavior_data quality --as-of 2026-11-10T00:00:00+00:00
python -m app.behavior_data purge --retention-days 180 --as-of 2026-11-10T00:00:00+00:00            # dry-run
APP_ENV=test python -m app.behavior_data purge --retention-days 180 --as-of 2026-11-10T00:00:00+00:00 --execute

# T71 회귀 (mock SQL을 올린 일회용 DB)
PGHOST=127.0.0.1 PGPORT=<port> PGUSER=<admin> PGDATABASE=t71_behavior_test D1_TEST_ONLY=YES \
  python -B -m unittest discover -s database/tests -p test_behavior_concurrency.py
```

## 14. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/behavior_data.py` | 신규: 품질 검사(읽기 전용)·보존 만료 삭제 job·CLI·실행 안전장치·감사 기록 |
| `backend/tests/test_behavior_data.py` | 신규: 단위 17건 (cutoff, 환경 차단, CLI, dry-run, 실패 롤백, 증빙 형식) |
| `backend/tests/test_behavior_data_postgres.py` | 신규: PostgreSQL 17건 |
| `docs/testing/T73_BEHAVIOR_DATA_VALIDATION.md` | 신규: 이 보고서 |

운영 코드 변경은 신규 모듈 1개뿐이며 T72·T31 코드, API, OpenAPI, Migration, Frontend, 설정은 바꾸지 않았다.

## 판정

```text
STAGING_DB_CHANGED=NO
REAL_USER_DATA_DELETED=NO
PRODUCTION_SCHEDULER_CHANGED=NO
T71_POLICY=NOT_APPROVED
STAGING_E2E=NOT_VERIFIED
T73_STATUS=PARTIAL (코드·격리 검증 PASS, 정책·보존 기간·운영 실행 HOLD)
```
