# T16 — 내 프로필 API 구현·검증

- Redmine: https://sulfite-footbath-next.ngrok-free.dev/issues/1556
- 담당: 김여름 / kyrdufmal-summer
- 브랜치: `task/t16-profile-api`
- 기준: main `d1fae3a` (T06 OpenAPI 계약 PR #29 반영)
- 판정: **PARTIAL — 로컬 기능·PostgreSQL 검증 완료, T14/T15 실연동·PM 리뷰 대기**.

## 구현 범위

FR-ACC-005·FR-CMN-002에 따라 `GET/PATCH /api/v1/me`를 구현했다.
`Router → Service → Repository` 구조, Pydantic DTO, PostgreSQL 쿼리 어댑터를 분리했다.

- 응답은 T06의 `Me`/`Profile` 스키마와 일치한다. email은 기존 원문을 표시하고 비교용 email_canonical은 노출하지 않는다.
- 수정 필드는 display_name(1~100), headline(최대 200), bio(최대 5000), location_text(최대 120)만 허용한다.
- PATCH 생략은 기존 값 유지, 선택 필드 null은 지움, 빈 문자열은 허용한다. display_name은 null/빈 문자열 불가.
- 빈 PATCH, 잘못된 타입, 길이 초과, 중첩 profile, email·visibility·status·user_id 등 미허용 필드는 422이다.
- 사용자 ID는 인증 의존성에서만 받는다. 임의 user_id 쿼리는 422, 다른 사용자 ID 경로는 404이다.
- 사용자가 없거나 비활성화됐으면 404. profile 행이 없으면 빈 선택 필드를 응답하고 첫 PATCH에서 UPSERT한다.
- users/user_profiles 수정은 하나의 트랜잭션으로 처리한다. 먼저 users를 갱신해 동시 수정과 비활성화 여부를 확인한다. 성공 시 T14의 caller-commit 계약에 따라 명시적으로 commit한다.
- 401/404/422/503은 `application/problem+json`. 입력·토큰·이메일·DB 오류 원문은 오류 응답에 넣지 않는다. 응답에 no-store를 적용한다.

제목의 CRUD가 임의 POST/DELETE나 이메일 변경을 뜻하지 않는다. T06은 GET/PATCH만 정의하고, 프로필은 본인만 볼 수 있다. 이메일 변경 중복 검사나 공개범위 변경은 이 계약에서 허용되지 않아 422 거부를 검증했다.

## T14/T15 연동 상태

확인 시 main에는 T13 골격만 있고 T14/T15 인증·DB 의존성이 없다. T14는 Draft PR #25(HOLD) 상태다. 검증되지 않은 브랜치를 병합하거나 인증·DB 기반을 임의 구현하지 않았다.

`app/dependencies/profile.py`가 연동 지점이다.

- `get_authenticated_user`: T15가 서명·만료·세션 유효성을 검증한 후 `AuthenticatedUser(user_id=UUID(sub))`를 제공해야 한다. 현재 토큰 없음/잘못된 인증 방식은 401, Bearer가 있어도 인증 미연동으로 503. 임의 토큰·user_id를 신뢰하는 개발용 인증은 없다.
- `get_profile_repository`: T14의 요청별 연결로 `PostgresProfileRepository(connection)`을 제공해야 한다. 현재는 503으로 차단한다.
- SQL 어댑터는 T14 PR #25와 동일한 psycopg 기본 tuple row_factory, `%s` 바인딩, connection.transaction/commit 계약에 맞췄다. T14 연결은 승인된 schema search_path와 최소권한 계정이어야 한다.
- GET/PATCH 성공 검증은 테스트 인스턴스의 dependency_overrides에 합성 인증 주체를 넣어 실행했다. 실제 JWT 인증 PASS를 의미하지 않는다.

연결 예시(승인된 T14/T15 도입 후 실제 모듈 경로에 맞춰 적용):

```python
def profile_repository(db=Depends(get_db)):
    return PostgresProfileRepository(db)

app.dependency_overrides[get_profile_repository] = profile_repository
app.dependency_overrides[get_authenticated_user] = verified_t15_principal
```

T05/T06 문서가 main에 있어도 PM 검토 완료를 자동으로 주장하지 않는다. 승인된 운영 Migration, 최소권한 앱 계정, T15 세션 검증이 연결되기 전 Staging 적용은 HOLD다.

## 재현

저장소 루트에서 Python 3.12 이상 가상환경을 준비한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18016
```

`http://127.0.0.1:18016/docs`에서 GET/PATCH의 DTO와 오류 형식을 확인할 수 있다. 기본 앱의 실제 사용자 요청은 인증·저장소 미연동으로 차단된다. 테스트용 계정/토큰을 앱 코드에 추가하지 않는다.

## PostgreSQL 검증

**공유 DB에 실행하지 말 것.** 로컬 일회용 DB `t16_profile_test`만 허용하며, 임의 이름 schema와 제한된 테스트 writer role을 만들고 정리한다. T05 데이터 사전의 users/user_profiles DDL을 자동 생성해 테스트한다. 운영 Migration이 아니다.

```powershell
# 별도로 준비한 localhost 일회용 PostgreSQL 전용 관리자 연결만 지정한다.
$env:T16_ISOLATED_DB_TEST = 'YES'
$env:T16_TEST_ADMIN_URL = '<일회용 t16_profile_test 연결 URL>'
..\.venv\Scripts\python.exe -m pytest -q
```

실행 환경: Windows, Python 3.13.7, PostgreSQL **18.4** (server_version 180004), psycopg 3.3.4. 실제 Staging 목표 18.1과 패치 버전이 다르다. GitHub CI에 postgres:18.1 서비스 기반 검사를 추가했다. CI 결과는 별도로 확인해야 한다.

검증 내용: CRUD 중 계약상 조회·부분수정, omit/null, 최대 길이와 초과, 미허용 필드·타인 접근, missing/disabled 404, 오류 원문 비노출, SQL 바인딩, profile UPSERT, 저장 실패의 users 수정 롤백, 선행 read 트랜잭션이 있어도 다른 연결에서 저장 확인, 비관리자 writer 권한.

2026-11-06 최종 로컬 실행: **57 passed** (PostgreSQL 통합 5개 포함). Starlette/AnyIO 의존성의 deprecated alias 경고 1건이 있었고 테스트 실패는 없었다.

현재까지 공유 Staging DB/서비스/PoC/배포 설정 변경은 없다. PR 리뷰·인증 실연동·Staging 검증 전 Closed/100%로 표시하지 않는다.
