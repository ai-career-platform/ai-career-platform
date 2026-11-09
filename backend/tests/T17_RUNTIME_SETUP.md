# T17 로컬 실행 안내

T14 `get_db`와 T17 조회가 연결된 상태다. 공유 Staging 접속 정보는 사용하지 않는다.
공통 `.env.example`·설정 파일은 수정하지 않았으며 `.env`는 자동으로 읽지 않는다.

## 현재 main 인증과의 연결

T17 조회는 T06 선택 인증 계약을 유지한다. Authorization 헤더가 없으면
비로그인 조회, 헤더가 있으면 T15 토큰 서명/만료와 DB 세션·사용자 상태를
검증한다. 잘못된 토큰을 비로그인으로 간주해 통과시키지 않는다.
401 응답은 공통 UNAUTHENTICATED/TOKEN_EXPIRED와 WWW-Authenticate를 사용한다.
main의 인증 코드와 메시지를 재사용하며 별도 JWT 구현은 두지 않는다.
DB와 cursor 키는 비로그인 조회에도 필요하다. 인증한 요청에는 T15의
정상 사용자·세션 DB 레코드가 추가로 필요하다.
JWT_SECRET 등 인증 실행 설정은 main의 backend/README.md를 따른다.

## 준비

- `backend/.venv`에 `requirements-dev.txt` 설치.
- 본인 전용 PostgreSQL에 T05 검증 스키마·T10 합성 Seed 적용.
  정식 T09 Migration 호환성 검증과는 구분한다.
- 임시 테스트 클러스터는 검증 후 종료했다. 새 환경에서는
  [검증 스키마 안내](../../database/schema/README.md)와
  [Seed 안내](../../database/seeds/README.md)를 따라 본인 전용 DB를 준비한다.

## 실행

아래는 앞서 만든 전용 임시 클러스터(25437)가 실행 중일 때 사용하는 예시다.
현재 실행 중인 서버를 임의로 종료하지 말고, 별도 터미널에서 사용 가능한 포트를 쓴다.

```powershell
cd C:\dev\ai-career-platform\backend
$env:DATABASE_URL='postgresql://t17_test@127.0.0.1:25437/postgres'
$env:T17_CURSOR_KEY=(& .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(48))')
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 25438
```

새 키 생성은 기존 cursor를 무효화한다. 위 예시는 일회성 로컬 검증용이고,
계속 사용하는 환경에서는 비공개로 관리한 같은 키를 모든 프로세스에 제공해야 한다.
키를 화면에 출력하거나 Git에 넣지 않는다. DATABASE_URL은 SQLAlchemy의
`postgresql+psycopg://`가 아니라 T14 규약의 `postgresql://` 형식을 사용한다.

확인할 주소:

- `http://127.0.0.1:25438/docs`
- `http://127.0.0.1:25438/health/db`
- `http://127.0.0.1:25438/api/v1/job-roles?limit=1`
- `http://127.0.0.1:25438/api/v1/skills?q=python`

직무 상세는 목록 응답의 job_role_id로 조회한다. 다음 페이지는 응답의
next_cursor를 같은 검색 조건과 함께 전달한다.

테스트: 전용 클러스터가 준비된 상태에서

```powershell
$env:T17_LOCAL_POSTGRES='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
Remove-Item Env:T17_LOCAL_POSTGRES
```

2026-11-09: 111 passed, 1 warning. 테스트에서 DB 설정은 전용 localhost
주소로 제한하고, 서비스 override 없는 T14 연결 경로도 검증한다.

종료: 본인이 띄운 서버 터미널에서 Ctrl+C 후 해당 세션 환경변수를 정리한다.
임시 DB도 본인이 만든 클러스터의 pg_ctl 명령으로 종료한다. 기존 DB 서비스는 종료하지 않는다.

```powershell
Remove-Item Env:DATABASE_URL,Env:T17_CURSOR_KEY -ErrorAction SilentlyContinue
```
