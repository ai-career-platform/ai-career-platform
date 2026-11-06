# T111 — 환경 설정 계약

담당 일감: T111 / Redmine #1538. 2026-11-06 기준 **PARTIAL**.
추적된 예시 파일의 정합성과 값 비노출 진단만 구현했습니다. 실환경 설정 검사,
DB 계정 분리 적용, 실제 Secret 회전·무중단 반영은 미실행입니다.

## 구성별 변수와 관리 주체

| 구성 / 예시·입력 | 변수 | 필수 여부·기본 동작 | 관리 주체 / 교체 시점 |
|---|---|---|---|
| 루트 `.env.example` | `STAGING_SSH_HOST`, `STAGING_SSH_PORT`, `STAGING_SSH_USER`, `STAGING_SSH_KEY_PATH`, `STAGING_SSH_ALIAS` | 운영 접근 정보 기록용. 앱이 자동으로 읽지 않음. 예시는 빈 값 | PM/JM·승인된 운영자 / 접근 경로·담당자 변경 시 |
| [정식 Backend 예시](../../backend/.env.example) | `APP_ENV`, `APP_VERSION` | 선택값. 미설정 시 `local-dev`, `0.1.0`. `.env` 자동 로드 없음; 셸에 설정 | Backend 담당자 / 실행 환경·릴리스 변경 시 |
| [Frontend 예시](../../frontend/.env.example) | `VITE_API_BASE_URL` | 기본 `/api`, 같은 Origin의 경로 | Frontend 담당자 / 프록시 계약 변경 시 재빌드 |
| 동일 | `VITE_API_MOCK` | 예시 `false`; [Mock 예시](../../frontend/.env.mock)는 `true` | Frontend 담당자 / 실행 모드 선택 시 |
| 동일 | `DEV_API_PROXY_TARGET` | 개발 Vite 서버 전용. 기본 로컬 PoC Nginx | Frontend 담당자 / 로컬 프록시 변경 시 |
| [PoC 예시](../../poc/staging/.env.example) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `APP_ENV`, `APP_VERSION` | Compose가 비어 있거나 없는 입력을 거부. 비밀번호 예시는 자리표시자 | PM/JM·운영자 / 승인된 설정·자격증명 변경 시 |
| [PoC Compose](../../poc/staging/compose.yaml) | `POSTGRES_HOST`, `POSTGRES_PORT` | Compose가 내부 DB 서비스 경로로 주입. 호스트용 예시에 추가할 필요 없음 | PM/JM·운영자 / 서비스 계약 변경 시 |
| [게시 워크플로](../../.github/workflows/staging-publish.yml) | `GH_TOKEN`, `APPROVED_MERGERS`, `SOURCE_SHA`, GitHub 실행 메타데이터 | Actions가 주입. 로컬 환경 예시에 복사하지 않음 | 저장소 관리자 / 권한·승인자·실행별 변경 |
| [배포 오버레이](../../poc/staging/automation/compose.release.yaml) | `FRONTEND_IMAGE`, `BACKEND_IMAGE`, `DEPLOY_SHA` | 검증한 manifest에서 배포기가 주입. 개발자가 `.env`에 임의 지정하지 않음 | 승인된 배포 절차 / 릴리스별 |
| [배포 서비스](../../poc/staging/automation/ai-career-staging-deploy.service) | `CREDENTIALS_DIRECTORY` / `github-token` | systemd credential 경로. 자격증명 내용은 코드·환경 예시에 넣지 않음 | PM/JM·운영자 / 만료·권한 변경·유출 의심 시 |

정식 Backend와 현재 배포 중인 PoC는 별도 구성입니다. 정식 Backend에 새 설정이
추가되면 `backend/.env.example`을 갱신하며, 이를 PoC Compose 변경 요구로
자동 전환하지 않습니다. PoC DB 역할의 제한과 승인은
[접근 매트릭스](../../database/security/ACCESS_MATRIX.md)와 [DB 정책](../DATABASE.md)을 따릅니다.
정식 앱 DB 설정은 T14 구현 전까지 확정된 것으로 취급하지 않습니다.

## 오프라인 검사

저장소 루트에서 실행합니다. Python 표준 라이브러리만 사용합니다.

```bash
python -B scripts/ci/check_env_examples.py
python -B -m unittest discover -s scripts/ci/tests -p 'test_check_env_examples.py' -v
```

검사 항목:

- 예시 파일 존재·중복 키·대입 구문과 필수 변수 이름.
- 정식 Backend 설정 읽기와 정식 Backend 예시의 일치.
- PoC의 필수 Compose 입력과 PoC 예시, PoC Python 설정 읽기와 Compose 매핑의 일치.
- FE 실연동/Mock 모드 구분, 같은 Origin API 경로, 자격증명이 없는 개발 프록시 URL.
- `VITE_*`의 명백한 비밀정보 변수명 차단, PoC 비밀번호의 명시적 자리표시자 유지.
- 오류 출력에는 변수 이름·문제 종류만 포함. 실제 `.env`, 셸 환경, systemd credential,
  SSH 키·토큰 파일은 읽지 않습니다.

한계: 현재 소스의 리터럴 `os.environ`/`os.getenv`, `import.meta.env`, 현재의 평면
Compose 환경 매핑만 정적으로 검사합니다. 전체 dotenv/YAML 해석기, 런타임 유효성 검사,
권한 검사 또는 Secret 탐지기의 대체물이 아닙니다. 정규식 비밀정보 검사는 기존
`scripts/ci/check_secrets.py`가 별도로 수행합니다. CI의 예시 검사 성공을 실제
운영 자격증명의 유효성이나 최소권한 검증 성공으로 표시하지 않습니다.

## 승인·검증이 남은 항목

- 실제 Local/CI/Staging 필수값 검증과 소유권·접근권한 증빙.
- T07/T14/T28/T90의 승인·검증 결과와 정식 Backend DB 계약.
- 승인된 대상에서의 자격증명 회전, 소비자 반영·구 자격증명 폐기·서비스 연속성 검증.
- GitHub CI 해당 SHA의 성공 확인. 현재 기록은 로컬 결과입니다.

회전과 유출 대응 초안은 [SECRET_ROTATION.md](SECRET_ROTATION.md)를 참고합니다.
