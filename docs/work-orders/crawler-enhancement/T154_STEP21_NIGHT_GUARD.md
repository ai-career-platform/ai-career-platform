# T154 STEP21 — 야간 Fixture 30분 슬롯 단일 실행 연결 (비활성)

STEP20 결과: HOLD. T64 Dispatcher는 T154 Worker 호출하지 않으며, 21:00~08:00 22회 제한/08:00 완전 종료 미검증, 보관된 백업에 0009 Attempt 테이블 누락. **기존 서버·DB 무변경.**

이번 변경은 T64 Scheduler에 우회 연결하지 않고 **독립적인 수동 one-shot 호출 경계**만 제공한다.
- KST 21:00 포함, 다음날 08:00 제외.
- 밤당 슬롯 0..21, 각 30분, 총 22 슬롯. 자정 넘는 슬롯도 밤 시작일에 귀속.
- 신규 수동 Migration 0010 `fixture_night_slots`의 PK (night_date,slot_index) + UNIQUE (night_date,job_id)로 동일 슬롯 및 동일 작업 밤 중복 예약 차단.
- `execute_night_fixture_once()`는 3개의 별도 DB 연결 사용: night-slot / durable attempt / worker. `NightSlotStore.reserve`를 commit한 뒤 STEP16 `execute_manual_fixture_attempt`를 **정확히 한 번** 호출한다.
- 슬롯은 작업이 실패해도 소비 처리한다. 늦게 시작한 슬롯을 보충 실행하지 않는다.
- 신규 Raw/Fixture Job 생성, 반복 스케줄, systemd Timer, T64 Dispatcher 연결, 외부 HTTP는 **포함하지 않는다**.
- DB는 아직 0010 미적용. 기존 0002~0009 재적용 금지.

## 중요 차단 사항
이 함수는 **작업 시작 시간만 검사한다**. 이미 실행 중인 Worker를 08:00에 강제 종료하는 OS-level hard-stop은 구현되지 않았다. 따라서 이 PR의 병합·CI PASS만으로 야간 자동 실행을 활성화하면 안 된다. 또한 자동 실행에 사용할 job 목록 공급 방식과 전체 백업(Attempt 0009 + Slot 0010 포함)이 미확인 상태다.

## 검증 및 다음 단계
1. GitHub CI Smoke Test/offline-tests PASS.
2. 격리 PostgreSQL에서 0010 수동 적용/permissions/두 연결 이상의 동시 slot 예약/아침 08:00 경계/22개 슬롯/기존 T154 Worker 수동 호출/롤백 확인.
3. 서버 최신 전체 백업(0009/0010 테이블 포함)·복원 테스트.
4. 별도 제한적 one-shot systemd service와 timer: OS 수준 종료 데드라인, 최대 실행 시간, 실행 시각·횟수·오류 메트릭 증빙. 검증 전 disabled/inactive.
5. 실제 스테이징 활성화는 별도 체크리스트 이후. Live collection HOLD.
