# T155 STEP03 — T15 인증 연동 관리자 조회 API (main 기반)

Feature #1577 / T155 Redmine #1582. T15 PR #48 merged at `6f5ed624343fe1467734eab0c652b67fe91bd135`.

## 구현

- 기존 `backend/app/dependencies/auth.py`의 DB-backed `require_roles("admin")`를 모든 `/api/v1/admin/crawler/*` 조회 경로에 적용.
- 검색어, Job/Attempt, Schedule 메타데이터, Run, Event, 검색어별 집계 총 6개 GET 경로.
- 기존 T155 `crawler/admin/read_models.py` SELECT-only 저장소(기존 PR #119/#120 통합 PostgreSQL PASS) 재사용.
- 별도 crawler DB 연결 및 `SET TRANSACTION READ ONLY`. 인증 성공 이후에만 접근하며 준비 실패는 503.
- 검색 조건 422, 익명 401, 비관리자 403, 관리자 200, 역할 회수 즉시 403 TestClient 검증. 원문 Raw/URL 집합/승인 설정 비노출.
- Job 시작·중단·재시도, 설정 변경, 관리자 쓰기는 미구현; 외부 HTTP/Timer 영향 없음.

## 배포 경계 및 남은 검증

스테이징 PoC 이미지는 `poc/staging/backend/Dockerfile.integrated`로 빌드하고 `poc/staging/backend/main.py`을 실행한다. 이는 T15/T155 주 Backend `backend/app/main.py`과 **별개**다. 따라서 PR CI가 녹색이어도 현재 스테이징 관리자 API 동작을 주장할 수 없다.

다음 통합 단계는 별도 Backend 이미지에 실제 `backend/app` 및 `crawler` 모듈, PyJWT/argon2/psycopg 의존성, 두 전용 DB 권한을 명시적으로 포함시키는 것이다. 필요한 T15 앱 DB 스키마/Seed 준비 및 관리자 세션·role DB 기반 검증 후, 격리 환경 401/403/200/422/503 및 실제 크롤러 DB 조회 E2E가 PASS인 경우에만 운영 접근 경로를 결정한다. 기존 PoC Auto-CD·DB·원본 7건·합성 28건·야간 Timer 상태는 변경하지 않는다.

본 PR은 **주 Backend 코드 구현 및 테스트**이며 스테이징 런타임 통합까지 완료했다는 의미가 아니다.
