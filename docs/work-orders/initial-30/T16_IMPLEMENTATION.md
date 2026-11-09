# T16 — 내 프로필 API 통합 검증

Redmine #1556 · PR #40 · 브랜치 `task/t16-profile-api`

## 구현

- T14 `app.db.get_db`의 요청 단위 SQLAlchemy Session과 기존 Engine/pool을 재사용한다. 별도 연결 풀·드라이버 연결은 만들지 않는다.
- T15 `get_current_user`의 서명·만료·DB 세션·사용자 상태 검증을 그대로 사용한다. 임시 인증·503 placeholder·인증 우회는 제거했다.
- 기존 T15 GET `/api/v1/me`, permissions/sessions 라우트를 유지하고 PATCH만 연결한다. 사용자 ID는 인증 주체에서만 가져오며 GET/PATCH query 입력은 422로 거부한다.
- 기존 T15 Me/Profile 응답 DTO와 공통 AppError/ErrorResponse를 재사용한다. 오류는 최신 main 계약의 `application/json` `{code,status,message}`와 X-Request-ID 헤더다. 구형 T16 ProfileRoute/Problem 오류 체계는 제거했다. 잘못된 JSON은 공통 계약의 400, 값 검증은 422다.
- T06 Me 계약에 필수인 본인 원문 이메일은 유지한다. email_canonical, 인증 해시·토큰 등은 노출하지 않고 이메일 수정은 거부한다.
- PATCH display_name 1~100, headline 최대200, bio 최대5000, location_text 최대120. 생략 값 보존, nullable 명시 null 제거, 빈 PATCH/추가 필드/타입·길이 위반은 422.
- T09 `database/migrations/0001_initial_schema.sql`의 career.users/user_profiles와 기존 ORM 모델을 사용한다. 사용자 행을 FOR UPDATE로 잠그고 변경 필드만 적용하여 동시 PATCH와 profile 행 최초 생성도 직렬화한다.
- 인증 조회로 시작된 Session 트랜잭션에 함께 참여한다. users/profile 변경·응답 조회 후 commit, 오류 시 rollback, get_db finally에서 Session close 및 pool 반환.
- T15는 소멸·비활성 사용자/세션을 401로 거부한다. 인증 후 프로필 조회 시 사라진 행은 404. 다른 사용자 ID를 경로·본문·쿼리로 선택할 수 없다.
- `/api/v1/me` 성공·오류 응답에 Cache-Control: no-store를 적용한다.

## 검증과 재현

로컬: Python3.12, PostgreSQL18.6 일회용 loopback 인스턴스. **171 passed / 0 failed / 0 skipped**. Starlette/AnyIO deprecated alias 경고1개.
T13 smoke, T14 Session, T15 인증·인가, T16 계약45개 및 PostgreSQL 통합8개를 포함한 Backend 전체 결과다. SQLite 테스트 어댑터를 제거하고 프로필 계약 검증도 PostgreSQL+SQLAlchemy Session으로 실행한다.

- 정식 T09 0001 migration을 일회용 DB에만 적용하고 비관리자 SELECT/INSERT/UPDATE writer로 요청 실행.
- 실제 서명 JWT + DB auth_sessions를 사용한 API 검증에는 dependency override가 없다. 필드 계약/404 세부 검사는 테스트 앱의 합성 CurrentUser override로 분리했다.
- 독립 관리자 연결로 commit 확인, profile 쓰기 오류·commit 오류의 rollback, 부모 lock 기반 동시 PATCH의 생략 필드 보존, 연결 pool checkedout=0 확인.
- 기존 T16의 모든 동작 검사를 유지하되 main 공통 오류 형식과 실제 T15 disabled401 계약에 맞췄다.

```bash
python -m pip install -r backend/requirements-dev.txt
# 반드시 일회용 loopback DB. 실제 자격정보를 로그/PR에 출력하지 않는다.
# T16_ISOLATED_DB_TEST=YES
# T16_TEST_ADMIN_URL=<loopback t16_profile_test>
# T15_TEST_DATABASE_URL=<disposable auth test DB>
# T15_SCHEMA_SQL=<absolute repository>/database/migrations/0001_initial_schema.sql
cd backend
python -m pytest -q
```

PG 테스트는 명시 opt-in과 localhost DB명 t16_profile_test를 검사한다. test fixture는 해당 일회용 DB의 career 스키마를 매번 재생성하므로 공유/스테이징 주소를 절대 사용하지 않는다. GitHub Backend tests는 PostgreSQL18.1 서비스에서 T15/T16을 모두 활성화한다. 일반 Backend pytest job은 opt-in PG 검사들을 SKIP하며 해당 DB 검증은 별도 backend job이 담당한다.

## Evidence 및 영향

실행 로그 `t16-postgres-full-pytest.log`, 환경·정상 종료 `t16-isolated-postgres-evidence.json`은 로컬 작업 outputs에 보존한다. PR 본문에 실제 HEAD 및 CI 결과를 기록한다.
공유 Staging DB/서비스/볼륨 변경 없음. 테스트 데이터는 합성 데이터만 사용했다. 필수 리뷰 승인 및 CI 충족 전 병합하지 않는다.
