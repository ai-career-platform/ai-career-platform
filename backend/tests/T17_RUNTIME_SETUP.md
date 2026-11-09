# T17 로컬 실행 안내

T17 직무·기술 조회 API(`/api/v1/job-roles`, `/api/v1/job-roles/{id}`, `/api/v1/skills`)를
본인 전용 DB로 실행·검증하는 방법입니다. 공유 Staging 접속 정보는 사용하지 않습니다.

## 동작 요약

- **공개 조회:** 로그인 여부로 달라지는 응답이 없어서 `Authorization` 헤더를 읽지 않습니다.
  만료되거나 잘못된 토큰이 와도 비로그인과 같은 200을 줍니다(openapi.yaml도 401을 선언하지 않음).
- **DB:** T14 공통 `get_db` 세션을 씁니다. 카탈로그 전용 세션·인증 함수는 없습니다.
- **cursor 서명 키:** 별도 환경변수 없이 `JWT_SECRET`에서 용도별로 파생합니다
  (`HMAC(JWT_SECRET, "t17-job-roles-cursor-v1")`). `JWT_SECRET`이 바뀌면 이전 cursor만 400이 됩니다.
- **cursor 거부(400 `INVALID_CURSOR`):** 빈 값, 변조, 다른 검색어, 발급 형식과 다른 Base64,
  기준 직무가 사라졌거나 이름이 바뀐 경우. 이름이 바뀐 채로 이어 읽으면 항목이 조용히 빠지므로
  처음부터 다시 조회하게 합니다. 동시 데이터 변경에 대한 snapshot 보장은 없습니다.
- **비활성(`is_active=false`):** 목록·검색에서만 빠집니다. 이미 알고 있는 ID의 상세는 그대로 열립니다
  (데이터 사전: "폐기 시 참조 보존").

## 준비

1. `backend/.venv`에 `requirements-dev.txt`를 설치합니다.
2. 본인 전용 PostgreSQL에 T05 검증 스키마와 T10 합성 Seed를 적용합니다.

```bash
psql -d <로컬DB> -c "CREATE SCHEMA career"
psql -d <로컬DB> -v ON_ERROR_STOP=1 -f database/schema/T05_VALIDATION_ONLY.sql
psql -d <로컬DB> -v ON_ERROR_STOP=1 -f database/seeds/0001_initial_seed.sql
```

자세한 내용은 [검증 스키마 안내](../../database/schema/README.md)와 [Seed 안내](../../database/seeds/README.md)를 따릅니다.

## 실행

```bash
cd backend
export DATABASE_URL='postgresql://<user>@127.0.0.1:<port>/<로컬DB>'   # T14 규약: postgresql:// 형식
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

비밀번호는 `PGPASSWORD`나 `.pgpass`로 넘기고, 키·비밀번호를 화면에 출력하거나 Git에 넣지 않습니다.

확인할 주소: `/docs`, `/health/db`, `/api/v1/job-roles?limit=1`, `/api/v1/skills?q=python`.
다음 페이지는 응답의 `next_cursor`를 같은 검색 조건과 함께 보냅니다.

## 테스트

```bash
cd backend
.venv/bin/python -m pytest -q                      # DB 없이 도는 단위·HTTP 테스트
T17_TEST_DATABASE_URL='postgresql://<user>@127.0.0.1:<port>/<로컬DB>' \
  .venv/bin/python -m pytest -q tests/test_catalog_postgres.py   # 실제 PostgreSQL (선택)
```

Postgres 테스트는 호스트가 localhost가 아니면 실행을 거부하고, 바꾼 데이터는 롤백·정리합니다.
