# T154 STEP01 — 오프라인 증분 배치 계획 (Live Disabled)

기존 T64 Scheduler·Dispatcher 및 T151 검색어 작업 멱등 키를 재사용할 수 있도록, **순수 함수 기반** 합성 Fixture 배치 계획만 추가한다.

- KST 야간 시간창 기본 21:00~다음날 08:00. 시작 포함, 종료 제외. 자정 전후 동일 야간 날짜로 멱등 키 생성.
- 게시물 ID 입력은 호출자가 제공한 **합성 ID**이며 중복 제거 후 최대 10개씩 묶어 분할.
- 검색어별 배치 키 `fixture:t154:{night}:{keyword_id}:{slot}` 생성. DB 작업 생성 및 Dispatcher 연결은 **하지 않음**.
- `checkpoint` 인수는 형식 검증만 수행하며 신규/수정 필터링을 구현했다고 주장하지 않음. 실질적인 증분 체크포인트 영속화, 시간창 설정 DB, 실패 작업 재개·차단 규칙은 후속 단계.
- Live 수집, HTTP, Scheduler/Timer 활성화, DB/스테이징 수정 없음.
- 테스트: `python -m unittest crawler.tests.test_t154_incremental_fixture -v`.

## 선행 의존성 상태

T153 STEP04의 `SELECT FOR UPDATE` 권한 문제는 PR #103을 통해 Advisory Lock 방식으로 수정·CI PASS·main 병합됨. **실제 스테이징 E2E 재검증 결과가 아직 전달되지 않았으므로 T153 전체는 HOLD**; 본 오프라인 T154 개발은 병행해도 실제 수집을 활성화하지 않는다.
