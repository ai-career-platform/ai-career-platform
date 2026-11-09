# T64 STEP 01 — 오프라인 실행 상태 모델

## 범위

`crawler/jobs/run_state.py`에 합성 JobKorea 수집 실행의 상태 전이 계약만 구현한다. **기존 T62/T63 Worker에는 연결하지 않았다.** 외부 사이트 HTTP, 실제 작업 예약, systemd, 관리자 API, 데이터베이스 읽기/쓰기가 없는 순수 Python 모델이다.

## 실행 상태

- 최초 `PENDING`
- `PENDING → RUNNING` 또는 `PENDING → CANCELLED`
- `RUNNING → SUCCEEDED | PARTIAL | FAILED | CANCELLED`
- 완료(terminal) 상태는 재시작/재전이를 차단. 실제 재시도는 향후 별도 attempt/run과 idempotency 계약으로 설계
- `FAILED`에는 영문 대문자·숫자·밑줄만으로 구성된 최대 64자리 `error_code` 필수. 원본 오류 메시지, DSN, 비밀번호, URL 등 저장하지 않음

## 시간/집계

- 호출 측이 시간 `datetime`을 반드시 제공. 암묵적 현재 시각 읽지 않음
- 입력은 시간대가 있는 datetime만 허용, 내부 및 Snapshot은 UTC로 기록. KST 입력도 UTC로 정규화
- 이전 이벤트 시각보다 과거인 상태 전이는 거절
- 종료 이벤트에만 허용 목록 카운터를 기록하고, 음수·불리언·임의 필드를 차단
- Snapshot은 `run_id/source_id/status/requested_at/started_at/ended_at/counters/error_code`만 반환

## Windows 11 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 T62/T63 **84개** + STEP 01 신규 **22개** = 총 **106개 예상**. 실제 Windows 실행 및 GitHub CI 확인 전에는 PASS를 선언하지 않는다.

## HOLD / 후속 단계

- T64 STEP 02: 동일 `run_id` 및 수동·예약 중복 실행 방지 (아직 미구현)
- T64 STEP 03: 실패/timeout/heartbeat/재시도 상한 (아직 미구현)
- T64 STEP 04: 운영 계약/로컬 통합 검증 (아직 미구현)
- T61 출처 권한, T09 DB Migration, T28 인프라, 관리자 RBAC 확정 전에는 **실제 스케줄 활성화 및 실사이트 수집 HOLD**
