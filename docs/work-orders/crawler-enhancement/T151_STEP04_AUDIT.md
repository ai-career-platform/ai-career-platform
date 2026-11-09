# T151 STEP 04 — 검색어 변경 이력(Audit)

## 범위

- 새 수동 Migration `crawler/storage/migrations/0004_keyword_audit.sql`: `crawler_training.keyword_audit_events` **1개 신규 테이블**.
- 내부 `KeywordStore`의 검색어 생성/수정/활성화/soft-delete 작업과 감사 이력 기록을 **같은 DB 트랜잭션**으로 처리.
- `actor`, `action`, `before_state`, `after_state`, 발생 시각 저장. 감사 조회 `list_audit()`.
- 기존 T151 검색어·작업·발견 관계 3개 테이블과 T64의 4개 테이블은 수정하지 않음. Live 수집·Worker·Timer 연결 없음.

## 호출 계약

예시: `store.add_keyword("MLOps", actor="user:123")` / `store.set_enabled(4, False, actor="user:123")`.

- 기존 내부 호출 호환을 위해 actor 미지정 시 `system:t151`로 명확히 표기. **이는 실제 인간 관리자 식별을 보증하지 않는다.**
- T155에서 서버가 인증한 사용자 식별값을 반드시 `actor`에 넣고 RBAC를 수행해야 함. 클라이언트가 임의로 제공한 actor를 신뢰하지 않는다.
- 기존 T151 테스트에는 `0003`만 필요했으나, **STEP04 코드로 CRUD를 실행하려면 반드시 `0004`까지 선행 적용**해야 함.
- 0004 미적용 상태에서 변경 시도는 실패하고 동일 트랜잭션의 CRUD가 롤백됨; 조용히 감사 기록을 건너뛰지 않음.
- 0003 초기 Seed(기본 6개)는 별도 관리 API를 거치지 않으며 0004 적용 전에 생성되므로 개별 CREATE 감사 이벤트가 없음. Seed는 Migration 이력으로 추적한다.

## 검증

`python -m unittest crawler.tests.test_t151_keywords crawler.tests.test_t151_audit -v`

실 DB 통합 검증(로컬 Codex 필요): 격리 테스트 DB에 `0003` + `0004`를 순서대로 적용하고, 생성/수정/비활성/soft-delete의 정확한 before/after/actor/action, 실패 시 원자적 롤백, 동일 항목 다중 호출, 과거 Seed 기록의 부재를 확인. 기존 T64 regression도 실행.

**기존 실 스테이징 DB에는 자동으로 Migration을 실행하지 않는다.** 스테이징 적용은 별도 STEP05. Live HOLD / Timer disabled 상태 유지.

## 상태
GitHub 구현 및 offline CI 테스트 대상. 실제 격리 PostgreSQL 동작 검증은 별도.
