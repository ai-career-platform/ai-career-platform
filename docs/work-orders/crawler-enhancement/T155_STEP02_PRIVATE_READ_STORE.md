# T155 STEP02 — 비공개 관리자 조회 서비스 (HTTP 미노출)

기준 `main`: `a1aa28241f598b227b7bcd364765f8fc22c0000b`.
Redmine #1582, Feature #1577.

## 구현
`crawler/admin/read_models.py`의 `CrawlerAdminReadStore`는 기존 T151/T64 테이블에서 **읽기 전용 메타데이터**만 조회한다. 검색어, Job/Attempt, Schedule(시간/상태), Runs, Events, 검색어별 집계를 제공한다. `limit` 1..100, `offset` 0..100000, 키워드 ID/작업 상태/Run UUID 유효성 검증, 모든 필터의 SQL 파라미터 바인딩을 적용한다.

`schedule.target_urls`/`approval`, Raw HTML, DSN, 비밀번호 등 비공개 원문은 반환하지 않는다. `crawler_training` 전용 DB를 호출자에게서 전달받으며, 서비스 자체는 DB에 연결하거나 작업을 실행하지 않는다. 마이그레이션/Timer/설정/스테이징을 변경하지 않는다.

## 반드시 지킬 인증 연동 게이트

GitHub PR #48 (T15 인증·인가) 아직 미병합 상태. 따라서 **이 단계에서 HTTP router/API 등록, 테스트용 bypass, 가짜 admin token, 로컬 접근 자동 허용 등을 추가하지 않는다.** 메인 `backend/app/routers/api_v1.py`의 기존 내용도 변경하지 않는다. 이 서비스는 단독으로 권한을 확인하지 않으므로 T15 `get_current_user` 및 `require_permissions`가 main에서 DB 세션과 함께 제대로 검증되기 전까지 외부 호출 불가다.

T15가 준비되면 실제 인증된 관리자 사용자만 조회하도록 API 연결한다. 익명 401/일반 사용자 403/관리자 200, 데이터베이스 오류 503, 필터 422, 원문 비노출을 TestClient 및 격리 DB로 검증한다. 실제 서비스 인가와 Crawler DB 조회에 사용하는 계정/권한도 분리한다.

## 다음
1. T15 PR #48 코드/병합·DB 이슈 해결 여부 확인.
2. T155 STEP03: 인증된 관리자 라우터에 이 private store 연결.
3. T155 STEP04: Keyword 변경 감사/멱등/실행 제어 추가.
4. T156 UI/통합 QA.

`T155_INTERNAL_READ_STORE=IMPLEMENTED`, `T155_HTTP_ADMIN_API=HOLD`, `T155_AUTH_GATE=HOLD`, `LIVE_COLLECTION=HOLD`.
