# T154 STEP23 Executor Report

기준 SHA: `4982db335a3f952caef4a2cc601ddafc57a42038`.
범위: 코드 구현, 실제 자식 프로세스 및 격리 PostgreSQL 검증. 스테이징 접속/변경, Timer 설치/활성화, Auto-CD 설정 변경은 수행하지 않는다.

## 구현

- `fixture_night_executor once --job-id UUID --raw-root PATH --log-file PATH`는 준비된 합성 Fixture 작업을 한 번만 처리한다. 30분 슬롯 선택은 현재 KST를 사용하며 과거 슬롯을 재생하지 않는다. 스케줄 설치/반복 루프/자동 재시도는 없다.
- Slot 연결의 한 트랜잭션에서 Job 잠금, Attempt 적격성, Slot 및 Attempt 예약을 확정한다. Worker 실행 전에 COMMIT된다. 기존 수동 Attempt 예약도 같은 Job 잠금 순서를 사용한다.
- COMPLETED, STOPPED, IN_PROGRESS, 3회 소진 작업은 Slot을 소모하지 않는다. 첫 PENDING 및 남은 예산이 있는 RETRYABLE만 허용한다. Slot은 야간당 22개, Attempt는 작업당 3회다.
- 자식은 기존 `execute_night_fixture_once` → 예약된 Attempt 실행 → `process_fixture_job`을 재사용한다. 세 연결은 동일 전용 DB의 서로 다른 backend PID인지 확인한다. 실제 Worker 연결의 세션 advisory lock으로 다른 one-shot Worker를 차단한다.
- Supervisor는 다음 08:00 KST 또는 최대 120초 중 빠른 마감을 적용한다. 기본 TERM 유예 2초와 DB 정리 예산 2초를 유효 작업 시간에서 먼저 뺀다. 시간이 부족하면 시작하지 않는다. TERM 무응답은 KILL 후 회수한다.
- 진단 DB 연결은 자식 시작 전에 연다. 종료된 자식이 사용한 PID, 고유 application token, 현재 runtime 계정이 모두 일치하는 세션만 제한 시간으로 종료한다. `pg_stat_activity` 및 `pg_locks`에서 잔존 여부를 확인하며 정리가 마감을 넘으면 PASS로 기록하지 않는다.
- Supervisor SIGTERM/SIGINT는 이벤트로 수신한다. 반복 신호가 정리 절차를 끊지 않는다. 강제 종료한 미완료 작업을 COMPLETED로 변경하거나 IN_PROGRESS를 자동 재예약하지 않는다.
- JSONL은 night_date/slot/job/start/end/status/attempt/처리 건수/오류 코드/종료 사유/HTTP 0/DB 정리 및 상태 불일치를 기록한다. 예외 원문, stderr, DSN, Raw HTML은 기록하지 않는다. 새 테이블/Migration은 없다.

## 검증

로컬 격리 PostgreSQL 18, loopback 전용 인스턴스, runtime `crawler_staging` 사용. 기존 0002~0010은 재적용하지 않는다. 원래 행 지문 보존을 비교하고 테스트 후 인스턴스를 정상 종료한다.

- 경계: 20:59 차단, 21:00 허용, 07:59 남은 60초 제한, 08:00 시작 차단.
- 실제 자식 성공, 시간 초과 종료, POSIX SIGTERM 무시 시 KILL, 이미 지난 마감은 프로세스 미생성.
- 실제 DB Slot/Attempt 동시 예약, COMMIT 가시성, 22개 상한, 3회 및 4회차 Slot 소모 0, STOPPED/IN_PROGRESS/COMPLETED 차단.
- 07:59:55의 5초 경계 테스트: 실제 Worker가 공고/이력/COMPLETED 상태를 미커밋으로 기록한 시점에 중단. Job=PENDING, 공고/이력/체크포인트 0, Attempt=IN_PROGRESS 유지, 세션/잠금 해제 및 정리 마감 확인.
- Linux CI는 SIGTERM을 무시하는 실제 PostgreSQL Worker와 Supervisor SIGTERM 후 롤백·잠금 해제를 추가 검증한다. Windows에서는 POSIX 전용 검사 2개를 명시적으로 skip한다.
- Crawler 단위/회귀 테스트 전체 및 기존 CI Smoke Test, offline-tests를 실행한다. 최종 CI 링크/결과와 집계는 제출 Evidence에 기록한다.

## 변경 파일

`crawler/jobs/fixture_night_executor.py`, `fixture_night_window.py`, `fixture_manual_retry.py`, `fixture_retry_budget.py`; 관련 단위 테스트, `crawler/tests/local_t154_night_executor.py`, `.github/workflows/crawler-mvp.yml`, 본 보고서와 활성화 체크리스트.

## 적용 한계

이 변경은 준비된 합성 Job을 받아 실행하는 one-shot 명령이다. 운영 Timer와 Job 공급은 설치하지 않는다. 신규 슬롯의 Job/Raw 준비와 정확한 야간 기간 제한은 별도 활성화 검수 대상이다. 스테이징 0010, 최신 전체 백업, 실제 환경 종료 검증은 미수행이다. 인프라 장애로 DB 정리를 확인할 수 없으면 NOT_VERIFIED와 수동 검수 필요를 기록한다. 로컬/CI 종료 테스트 PASS를 스테이징 운영 승인으로 해석하지 않는다.
