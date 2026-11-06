# T29 — Frontend 클라이언트 ↔ 로컬 Backend HTTP 회귀

담당 범위: T29 / Redmine #1535. 상태: **PARTIAL**.

정식 `frontend/src/api/client.ts`·`health.ts`에서 실제 `backend/app`의
Uvicorn HTTP 서버를 호출합니다. Mock을 끄고 Node의 실제 fetch를 사용하며,
서버는 `127.0.0.1`의 임의 포트에만 바인딩합니다. 테스트 종료 시 생성한
Backend 프로세스를 종료합니다. 공유 DB나 Staging에는 연결하지 않습니다.

## 실행

Node 24, Backend 개발 의존성이 설치된 Python이 필요합니다.

Windows PowerShell (저장소 루트):

```powershell
$env:INTEGRATION_PYTHON = (Resolve-Path backend/.venv/Scripts/python.exe).Path
Push-Location frontend
npm ci
npm run test:integration
Pop-Location
Remove-Item Env:INTEGRATION_PYTHON
```

Linux (저장소 루트):

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && INTEGRATION_PYTHON="$PWD/../backend/.venv/bin/python" npm run test:integration)
```

`INTEGRATION_PYTHON` 생략 시 PATH의 `python`을 사용합니다. 일반 `npm test`는
기존 jsdom 단위 테스트만 실행하고, HTTP 테스트는 `npm run test:integration`으로
분리합니다. 이 명령에는 통합 테스트 TypeScript 타입 검사도 포함됩니다.
CI에서는 `Frontend lint, test, build` job이 두 테스트 집합을 모두 실행합니다.

## 검증 범위

| 항목 | 실행 방식 | 판정 범위 |
|---|---|---|
| `/health`, `/version` DTO | 실제 FE 클라이언트 → 실제 로컬 HTTP | 구현된 시스템 API |
| 버전 구분 | 테스트 환경 버전과 Mock fixture 버전 대조 | Mock 오사용 방지 |
| `/openapi.json` | 실제 로컬 HTTP | 시스템 경로·버전 |
| 404·405, Allow, 공통 오류 DTO | 실제 로컬 HTTP | 없는 경로·허용되지 않은 메서드 |
| 요청 ID 전파·잘못된 ID 교체 | 실제 로컬 HTTP | 응답 헤더 |
| 네트워크 실패 | 생성한 Backend 프로세스 종료 후 실제 호출 | `ApiError.status=0` |
| 401·404·422·500 클라이언트 처리 | `client.test.ts`의 주입 응답 | **Mock 단위 검사**, 실제 인증·업무 API 검증 아님 |

## 미완료 항목

- 가입·프로필·직무·기업·공고 사용자 흐름: 현재 정식 Backend에는 시스템 API만
  구현되어 있어 업무 기능 E2E는 미실행입니다. T16/T17/T18/T22/T23/T24 완료 후 확장합니다.
- 이 테스트는 FE의 HTTP 클라이언트를 실행합니다. React 화면·브라우저 렌더·CORS
  정책·Nginx/Vite 프록시·DB 권한·Staging 배포 검증은 포함하지 않습니다.
- T19 기본 개발 프록시는 PoC Nginx를 경유하지만 본 테스트는 정식 Backend에
  직접 연결합니다. PoC `/health/db`의 성공을 정식 앱 통합 완료로 취급하지 않습니다.
- GitHub Actions에서 해당 SHA의 실제 실행 결과를 확인하기 전에는 CI PASS를
  주장하지 않습니다. 로컬 성공과 업무 E2E 완료를 구분합니다.

2026-11-06 로컬: 실제 HTTP 테스트 9개, 기존·추가 FE 단위 테스트 별도 실행.
