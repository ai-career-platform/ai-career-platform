# T64 STEP 02 — 오프라인 실행 Claim 중복 방지

## 목적 / 구현

`crawler/jobs/run_claims.py`는 하나의 Python 프로세스 내에서 수동/예약 요청의 실행권을 안전하게 점유(claim)하는 **합성 시뮬레이터**다. T64 STEP 01의 `RunRecord`를 재사용하며, 독립 `threading.Lock`으로 한 프로세스 내부에서만 동시 요청을 직렬화한다.

- `claim(run_id, source_id, trigger, requested_at, started_at)`: 동일 `run_id` 이력 존재 시 재요청 거부; 동일 출처에 RUNNING 실행이 존재하면 서로 다른 `run_id`라도 거부
- `trigger`는 `manual`, `scheduled`만 허용. 둘은 동일한 출처 lock을 공유
- `finish(run_id, target, at, counters, error_code)`: T64 STEP 01 종료 상태 전이 규칙을 검증한 뒤에만 출처 점유 해제. 검증 실패 시 기존 claim 유지
- 완료 후 같은 `run_id`는 다시 사용할 수 없고, **새 run_id**로 해당 출처의 후속 실행 가능
- `get`, `trigger_for`, `active_run`: 인메모리 조회 전용, 반환 RunRecord는 불변 객체

## 안전 경계

- 이 구현에는 **운영용 중복 실행 방지 보장 없음**. 여러 Python 프로세스, 재부팅/프로세스 종료, 여러 서버 간에는 공유 상태가 없으므로 충돌 방지 불가능
- 추후 PostgreSQL 트랜잭션 + unique 제약/lease/advisory lock 기반 원자적 claim이 별도 필요(T09 DB 계약 및 T28 인프라 승인 전에는 구현/운영 적용 금지)
- 기존 T62/T63 Worker 실행 경로, CLI, 관리자 API, DB 테이블, systemd 타이머를 변경하지 않음
- 실제 잡코리아 사이트 HTTP 요청 없음, 스케줄 구동 없음, DB 읽기/쓰기 없음

## Windows 테스트

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 T62/T63/T64 STEP 01 **106개** + 신규 STEP 02 **19개** = **125개 예상**. 동시성 테스트는 `ThreadPoolExecutor`에서 8개의 동시 claim 경쟁을 재현하며, 정확히 한 요청만 성공해야 한다.

GitHub CI와 Windows 로컬 테스트 PASS 확인 전에는 병합하지 않는다.

## 후속

T64 STEP 03은 실패/timeout/heartbeat/재시도 경계의 **오프라인 시뮬레이션** 예정. 운영 기능/실사이트 연동은 T61/T09/T28/관리자 RBAC/PM 승인 전까지 HOLD.
