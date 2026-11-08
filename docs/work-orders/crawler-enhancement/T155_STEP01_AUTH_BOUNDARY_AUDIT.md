# T155 STEP01 — 관리자 API 재사용 감사 및 Fail-closed 통합 경계

기준 SHA: `9efb94c99c8d381862f528f91fb4ee20c7ca954b`. 본 단계는 현황/계약 문서화 **전용**으로 운영/DB/타이머/외부 HTTP 변경 없음.

## 확인된 재사용 가능 자산

- `crawler/jobs/keyword_management.py`: `KeywordStore` CRUD, Audit, Keyword Job, 발견 관계. Actor는 현재 `system:t151` 기본값: HTTP 관리자 요청에서는 이 기본값을 쓰지 않고 **인증된 DB 세션에서 유도된 사용자 식별자**만 기록해야 함.
- `crawler/jobs/scheduler.py`: T64 `SchedulerStore.read`로 schedule/runs/events 조회 가능. Scheduler write/configure/dispatch는 T155 권한·감사 전에는 HTTP 연결 금지.
- `crawler/jobs/fixture_retry_budget.py`, `fixture_night_executor.py`: 안전한 bounded fixture 실행. T155에서 임의의 Job ID를 받아 바로 subprocess/Worker를 시작하지 않는다.
- `crawler/storage/staging.py`: 전용 crawler_training DB, 앱 DB와 분리. 관리자 데이터 조회 시 전용 읽기 계정/권한을 확인해야 함.
- `backend/training_jobs_api.py`: 교육용 별도 FastAPI 조회 서비스; 주 서비스 `backend/app/main.py`에 장착되지 않은 **비관리자** API이므로 T155 권한 검증을 대신하지 않음.
- `backend/app/routers/api_v1.py`: 메인 `/api/v1` 빈 기능 라우터. 미완료 Auth 라우터의 존재를 가정하지 않음.

## 핵심 의존성

GitHub issue #48 (`T15 인증·인가 API`)이 현재 OPEN/PARTIAL. 구현 리뷰 자료에는 `get_current_user`, `require_roles`, `require_permissions` 재사용 계약이 명시되어 있으나 **main에 검증된 의존성으로 들어왔다고 확인되지 않음**. T155는 해당 구현이 main에 병합되어 실제 role/permission을 DB에서 조회하는지, 앱 라우터에 장착됐는지를 먼저 확인해야 한다.

## 단계적 구현 제안

1. T15 실제 main 통합 상태 확인(미병합이면 T155 관리자 endpoints 미노출). 우회용 고정 Bearer 헤더, 환경변수 관리자 역할, 프론트 제공 actor_id, localhost 허용, 익명 읽기 공개 금지.
2. T15 종속성을 주입하고, 가장 먼저 Read-only 메타데이터 API만 구현: `GET /api/v1/admin/crawler/keywords`, `GET /api/v1/admin/crawler/jobs`, `GET /api/v1/admin/crawler/runs`, `GET /api/v1/admin/crawler/events`. 정책과 실제 API_CONTRACT 최종 확인 후 path 확정. `limit<=100` / 페이지네이션 및 파라미터 바인딩.
3. 권한 테스트: 익명 401, 일반 사용자 403, 관리자 200, 유효하지 않은 입력 422, DB 불능 503, Raw HTML/DSN/password/body 미노출.
4. 뒤이어 Keyword 변경/감사, Schedule 읽기/수정, manual fixture 실행/중단/재시도 순으로 각 명령의 idempotency key, 감사 로그, 중단 상태 처리, T61 Live 차단을 독립 테스트.
5. GitHub PR → CI → main merge → Auto-CD → 스테이징 Fixture E2E; 기존 공고/앱 테이블/볼륨/타이머·Auto-CD 보존 검증.

## 다음 검증 게이트

`T155_READ_ONLY_PLAN=READY`, `T155_AUTH_IN_MAIN=HOLD`, `T155_HTTP_ADMIN_API=NOT_STARTED`, `LIVE_COLLECTION=HOLD`.

T153 전용 E2E 검증이 미완료라면 이는 별도로 병행 가능하지만, T155를 인증 없이 공개하는 근거는 될 수 없다.
