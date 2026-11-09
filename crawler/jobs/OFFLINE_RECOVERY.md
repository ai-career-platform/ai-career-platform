# T64 STEP 03 — 오프라인 Heartbeat·타임아웃·재시도 정책

## 구현 범위

`crawler/jobs/offline_recovery.py`는 T64 STEP 02의 메모리 기반 `InMemoryRunClaims`와 결합하는 **모의 감시·복구 정책**이다. 실제 스케줄러, 네트워크 요청, 재시도 실행, 타이머, OS 프로세스 종료, DB·파일 저장은 없다.

- `OfflineHeartbeatMonitor.heartbeat(run_id, at)`: RUNNING 상태에서만 유효, 시각은 timezone-aware datetime 필수, 이전 heartbeat보다 과거면 거부
- `inspect(run_id, at)`: 마지막 heartbeat 또는 시작시각부터 설정한 시간 이상 경과한 경우 RUNNING을 `FAILED / HEARTBEAT_TIMEOUT`으로 전이시키고 메모리 claim을 해제. 결과는 `EXPIRED`이며 **자동 재시도 승인이 아님**
- `retry_decision(error_code, attempt, policy)`: 별도로 전달한 시도 번호 및 오류 코드에 따라 `RETRY_ELIGIBLE`, `STOP_NONRETRYABLE`, `STOP_LIMIT` 중 하나 반환. 실재 작업을 재시작하지 않음
- `RecoveryPolicy`: 시도 횟수 기본 3회(1~5), timeout 기본 5분(0 초과~1시간). 정확히 timeout 경계에 도달하면 만료
- `WORKER_TIMEOUT`, `HEARTBEAT_TIMEOUT`, `TEMPORARY_IO`는 제한 내에서만 재시도 **가능 판정**
- `RATE_LIMITED`(429), `ACCESS_FORBIDDEN`(403), `UNAPPROVED_SOURCE`, `INVALID_CONTRACT` 및 미등록 오류는 중단
- 재시도가 필요할 경우 동일 run_id 재사용 금지. T64 STEP 02의 Claim 관리자에 **새 run_id**로 별도 요청해야 함

## 명확한 한계

- 단일 Python 프로세스용 학습 모델이다. 다른 프로세스/서버의 Heartbeat, Lease, 중단·재시작 여부는 알지 못함
- heartbeat/attempt 카운터가 프로세스 재시작 후 유지되지 않음. **운영 장애 복구 보장 없음**
- 정책 판정과 실제 Worker 실행은 연결되지 않았음. 실행 중인 Worker를 강제 중지하는 기능도 없음
- `inspect`에서 claim을 해제하는 것은 **가상으로 Worker가 중단되었다고 가정한 시뮬레이션**이다. 운영 환경에서는 프로세스 종료 확인·DB lease fencing이 선행되어야 함
- 현재 코드에서 시도 번호는 호출자가 제공. 지속·원자적 재시도 횟수 관리는 후속 범위
- 실제 잡코리아 접근 권리/출처 승인(T61), DB Migration(T09), 운영 인프라(T28), 관리자 RBAC, PM 배포 승인이 모두 필요. 그 전까지 운영 timer/크롤러 실행은 `HOLD`

## 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 125개 + 신규 `test_offline_recovery.py` 25개 = **총 150개 예상**. CI와 Windows 실행 결과 검증 전에는 PASS 미판정.
