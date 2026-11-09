# T64 STEP 04 — 오프라인 실행 관리 통합 검증 / 운영 인계 범위

## 목적

T64 STEP 01(상태 기록) → STEP 02(단일 프로세스 claim) → STEP 03(Heartbeat 만료·재시도 판정)와 T62/T63 **합성 Fixture Batch Worker**를 하나의 검증 시나리오로 연결한다.

- `crawler/jobs/offline_run_report.py`는 실행된 T62/T63 Worker의 summary를 검증하고 **메모리 claim을 최종 완료 처리하는 순수 어댑터**다. 기존 Worker를 수정하거나 자동으로 실행시키지 않는다.
- `crawler/tests/test_offline_run_integration.py`에서 명시적으로 `claim → run(...) → finish_from_worker(...)`를 호출해 테스트한다.
- 이 기능은 실제 Scheduler/Dispatcher/관리자 API가 아니다. DB, 서버, 타이머, 외부 채용 사이트에 접근하지 않는다.

## 실행 결과 계약

최종 `RunRecord.snapshot()`에는 `run_id`, `source_id`, `status`, UTC 시작/종료 시각, 허용 목록의 집계 카운터, 비민감 `error_code`만 기록한다.

T62/T63 Worker summary를 성공/부분 성공으로 기록하기 전 검증:

- `run_id`/출처 불일치 거부, `mode=synthetic_fixture_only`, `external_requests=0`만 허용
- `fetched = normalized + invalid + duplicates + review`
- `normalized = inserted + updated + unchanged`
- `in_memory_only`에서 `db_writes=0`, `local_postgres`에서 `db_writes=inserted+updated`
- `invalid/duplicates/review` 중 1건 이상이면 `PARTIAL`, 없으면 `SUCCEEDED`
- 오염된 카운터, 잘못된 상태를 발견하면 claim을 RUNNING으로 유지하여 **허위 성공 기록을 막는다**
- 원본 공고·URL·DB 비밀번호·예외 원문은 snapshot에 기록하지 않음
- 데이터 저장 단위가 여전히 T62 Worker 내부에 있으므로, 이미 저장된 내용을 이 보고 단계에서 자동 ROLLBACK하지는 못함

## 복구 시나리오

합성 Worker의 성공/멱등 재처리, 수동·예약 충돌, Heartbeat 중단 후 `FAILED` 기록, **별도 오류 정책 검토 후 새로운 run_id**로 재시도 가능한지 검증한다. 인메모리 만료 처리는 실제 Worker 프로세스를 중지하지 않으며, 운영에서 그대로 재사용하면 안 된다.

## Windows 로컬 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

T64 STEP 03까지 기존 **150개** + 신규 **15개** = 총 **165개 예상**. 실제 Windows 및 GitHub CI 검증 후 병합한다.

## T64 전체 DoD / HOLD

| 항목 | 이 PR 후 범위 | 운영 완료 조건 |
|---|---|---|
| 실행 상태/UTC 시각/안전한 집계 | 메모리 기반 모의 검증 | 영구 DB 기록 및 감사 로그 필요 |
| 동일 run_id 중복/수동·예약 충돌 | 단일 프로세스 잠금 테스트 | DB unique/lease·다중 프로세스 동시성 시험 필요 |
| Heartbeat 만료/재시도 정책 | 합성 시계·수동 상태 전이 | 실제 프로세스 종료 확인·fencing·재기동 필요 |
| T62/T63 수집·품질 연동 | 합성 fixture/메모리 통합 | 승인된 출처와 저장 계약 필요 |
| 스케줄/KST·관리자 RBAC | 미구현 | T09/T28/T61/관리자 API 계약 승인 필요 |
| Ubuntu systemd timer/service | 미배포 | 운영 승인 전 enable/start 금지 |

T64를 **전체 PASS로 보고하지 말 것**. 오프라인 개발/로컬 통합 스코프 PASS만 가능하며, 실운영 스케줄·보안·DB 기반 클레임/장애 복구는 HOLD.

## 로컬 실습 종료 후

이 단계에서 `PGPASSWORD` 또는 다른 DB 자격증명 설정을 요구하지 않는다. 실제 사이트/운영 연결은 금지한다. 기존 `jobkorea_update_test.json` 파일과 학습용 PostgreSQL 데이터는 변경하지 않는다.
