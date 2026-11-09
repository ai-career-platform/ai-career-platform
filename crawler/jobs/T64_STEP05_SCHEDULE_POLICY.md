# T64 STEP 05 — 운영 비활성 상태의 KST 스케줄 판정 계약

## 범위

`crawler/jobs/offline_schedule.py`는 잡코리아 **합성 실행**을 대상으로 한 순수 Python 판정 함수다. 실제 수집 요청, 시스템 시계 읽기, systemd·cron 설정, DB·API 쓰기, 워커 시작·스레드 실행을 전혀 수행하지 않는다. T64 전체 운영 기능은 여전히 **PARTIAL/HOLD**다.

- `OfflineSchedule`의 기본값은 `enabled=False`. `03:00 KST`는 **승인되지 않은 제안 시각**이다.
- 관리자나 운영 스케줄 활성화 API는 없다. 테스트에서 `enabled=True`를 전달해도 `DUE`라는 판정만 생성할 뿐 실제 작업을 실행하지 않는다.
- `evaluate_daily(schedule, now, last_dispatched_for)`는 명시적으로 제공한 timezone-aware 시각을 `Asia/Seoul` 기준으로 해석한다.
- `last_dispatched_for`는 *실제 완료 시간*이 아니라 **이미 claim한 슬롯의 UTC 시각**이다. 이 함수는 조회·갱신하지 않으므로 복수 호출의 동시 `DUE` 판정을 막지 못한다.
- `DUE`: 오늘 슬롯 시작 이후, 보충 실행 시간창 이내이며 해당 슬롯을 이미 claim하지 않은 상태.
- `ALREADY_DISPATCHED`: 오늘 슬롯을 이미 claim한 경우. `NOT_DUE`: 오늘 예약 시각 전. `WINDOW_EXPIRED`: 보충 시간창을 지남. `DISABLED`: 실행 비활성.
- 기본 보충 허용 시간창은 **30분의 오프라인 정책 예시**다. 이 값은 확정된 운영 정책이 아니며 실제 스케줄 설정 승인이 필요하다.
- 복구/누락된 과거 날짜의 슬롯을 순회해 실행하지 않는다. **최대 1개 현재일 슬롯만 판단**하므로 대량 밀린 작업 실행을 권고하지 않는다.
- 시간은 UTC 정규화 결과만 `snapshot()`으로 반환하고 원본 URL/공고/비밀번호를 포함하지 않는다.

## 검증

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

기존 STEP 04까지 165개 + 신규 `test_offline_schedule.py` **20개 = 185개 예상**. Windows 로컬 테스트와 GitHub CI가 모두 성공한 뒤 PR을 병합한다.

## 운영 적용 전 선행 조건

T61 실사이트 접근·수집권한 승인, T09 DB 모델/마이그레이션 승인, T28 인프라 및 systemd 승인, 관리자 인증/RBAC, T62/T63 통합 운영 검증, DB 기반 원자적 claim 및 지속 실행 이력, PM 운영 일정·시간창 승인 **모두 선행되어야 한다**.

`DUE` 결과만으로 실제 Worker나 자동 재시도 기능을 실행하도록 연결하는 것은 **금지**한다. 기존 로컬 PostgreSQL 데이터 및 `jobkorea_update_test.json`은 변경하지 않는다.
