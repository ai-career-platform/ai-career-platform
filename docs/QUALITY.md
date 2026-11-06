# 테스트·증빙·완료 기준

## 코드 PR
- 기능 테스트: 정상 / 오류 / 경계 / 미존재 / 권한 없음.
- API: Request/Response 계약 및 Swagger 재현 결과.
- DB: 트랜잭션, Unique/FK 제약, 쿼리, 연결 실패 시 예외 처리.
- Frontend: Preview/화면 캡처, 로딩·빈 결과·오류 상태.
- AI: 점수 의미(예: 매칭 점수는 채용 성공 확률이 아님), 모델 버전·평가 기준·실패 시 대체.
- 보안: Secrets 스캔, 인증/인가, 입력/출력 검증.
- 재실행 가능한 명령과 사용 환경을 기록하고 Mock PASS와 실환경 PASS를 분리.

## 공통 증빙 단계
| 단계 | 최소 증빙 |
|---|---|
| 개발 시작 | Redmine 10%, 브랜치, 작업 범위 |
| PR 리뷰 요청 | Redmine 90%, PR URL, 테스트 결과, CI URL |
| 리뷰/승인 | GitHub 리뷰 댓글, 해결된 대화, CI 결과 |
| Merge | Squash Merge SHA |
| 완료 | Staging 확인 결과, Redmine 100% Closed |

## PR CI 게이트 (T28, `.github/workflows/ci.yml`)
`main` 대상 PR, `main` push, 수동 실행 시 아래 job이 같은 `CI` run 안에서 병렬로 실행됩니다. 하나라도 실패하면 run 전체가 실패하고, `main` push라면 Auto-CD(`staging-publish.yml`)도 진행되지 않습니다. 신규 job은 모두 `permissions: contents: read`, `ubuntu-24.04`(기본 `python3` = 3.12), SHA 고정 `actions/checkout`, `timeout-minutes`를 사용하며 Secret을 쓰지 않습니다. 네트워크는 checkout, pip 설치(직접 의존성만 버전 고정, `--retries 5`), setup-node(Node 24)와 `npm ci`(package-lock.json 기준)에만 사용합니다. 오탐으로 게이트가 막히면 값을 자리표시자로 바꾸거나, 리뷰어 확인 후 해당 줄에 `secret-scan: allow` 주석을 다는 순서로 처리합니다.

| Job (표시 이름) | 검사 내용 | 증명하지 않는 것 |
|---|---|---|
| `CI Smoke Test` (기존, **이름·단계 변경 금지**) | `README.md` 존재, `poc/staging/automation/tests` unittest(Auto-CD 자동화 42개) | 서비스 기능 |
| `Backend pytest` | `backend/requirements-dev.txt` 설치 후 `backend/` pytest, OpenAPI 3.1 계약·요구사항 매핑 검사, API 검사기 실패 주입 테스트, 데이터 사전 계약 테스트(로컬 파일 검사) | 실제 DB 연결, SQL 실행, 배포 환경 |
| `PoC Staging pytest` | `staging-publish.yml`과 같은 고정 버전으로 `poc/staging/tests` pytest. 배포 직전에만 잡히던 실패를 PR에서 탐지 | 실제 Compose·Staging 상태 |
| `Lint (ruff, compile, shell syntax)` | `ruff==0.16.9` + 루트 `ruff.toml`(E9 문법, F pyflakes만), `backend`·`scripts/ci` 포맷 검사, `compileall`, `*.sh`의 `bash -n` | 스타일 전반(E501 등), 타입 검사, shellcheck, actionlint |
| `Frontend lint, test, build` | `frontend/.nvmrc`(Node 24)로 `npm ci`(lock 기준) → `npm run lint`(oxlint, 경고도 실패) → `npm test`(Vitest) → `npm run build`(tsc 타입 검사 + Vite 빌드), `npm run test:integration`(정식 FE 클라이언트 → 실제 로컬 Backend HTTP, T29) | 업무 기능·React 화면 E2E, Nginx/CORS, DB, 브라우저 호환·접근성, 화면 디자인 |
| `Docs links, secret patterns, coverage notes` | `scripts/ci` 단위 테스트, Markdown 상대 링크 검사, 환경 예시 계약 검사(T111), 정규식 Secret 패턴 검사, 테스트가 없는 영역 표기 | 실환경 설정·Secret 회전, 앵커·외부 URL 유효성, 알려지지 않은 형식의 비밀정보, git 이력 속 비밀정보 |

DB 격리 테스트는 별도 워크플로 `d1-postgres-sql-test.yml`(`database/**` 변경 PR)에서 일회용 PostgreSQL 컨테이너로 실행되며 위 게이트에는 포함되지 않습니다.

### 판정 표기
- `PASS`: 해당 PR SHA에서 GitHub Actions job이 실제로 성공한 경우에만 사용합니다. 로컬 실행 결과는 "로컬 PASS"로 따로 적습니다.
- `PARTIAL`: 일부 검사만 실행됐거나(예: GitHub CI 미실행, DB 테스트 미실행) 검사가 범위를 다 증명하지 못한 경우.
- `NOT_APPLICABLE`: 검사할 코드가 없는 경우. 현재 `POC_FRONTEND_TESTS=NOT_APPLICABLE`(정적 `poc/staging/frontend/index.html`, 빌드 도구 없음)입니다. 정식 `frontend/`(T19)는 `Frontend lint, test, build` job이 검사합니다.
- `NOT_VERIFIED`: 실행하지 못했거나 결과를 확인하지 못한 경우. PASS로 바꾸어 적지 않습니다.

### Secret 패턴 검사 규칙 (`scripts/ci/check_secrets.py`)
- 탐지: AWS Access Key ID, `PRIVATE KEY` PEM 헤더, GitHub/Slack/Google/OpenAI 형식 토큰, 따옴표 값 `password = "..."`·`"api_key": "..."`, `.env`/셸 형식 `DB_PASSWORD=...`·`-e POSTGRES_PASSWORD=...`(8자 이상), 접속 문자열 안의 비밀번호 `postgresql://user:pass@host`, 설정 파일(`.yml`·`.yaml`·`.env*`·`.ini`·`.toml` 등)의 따옴표 없는 값 `POSTGRES_PASSWORD: value`. 따옴표 없는 값 규칙은 코드(`password=os.environ[...]`) 오탐을 피하려고 설정 파일에만 적용하고, API 명세 예시값이 많은 `docs/` 아래 파일(예: `docs/api/openapi.yaml`의 `example`)에는 적용하지 않습니다.
- 허용: `CHANGE_ME`·`<...>`·`xxxx` 표기, `test`·`dummy`·`fixture`·`disposable`·`example` 등 자리표시자 단어(**단어 단위 일치**: `test-only`는 허용, `MyLatestPw`는 탐지), `${VAR}`·`{{ }}` 참조와 `{...}` 템플릿, 줄에 `secret-scan: allow` 주석이 있는 경우(리뷰어가 사유 확인).
- 대상: git 추적 파일 + 무시되지 않은 미추적 파일. `.gitignore` 대상(`.env` 등), 바이너리, 2MB 초과 파일은 검사하지 않습니다. 출력 값은 앞 4자만 남기고 마스킹합니다.
- 이 검사는 전용 스캐너(gitleaks 등)를 대체하지 않습니다. 발견 시 값을 지우는 것만으로는 부족하며, 이미 push된 값은 즉시 폐기·교체합니다.

### 로컬 실행 방법
저장소 루트에서 실행합니다. Python 3.12 권장, `git` 필요. ruff 버전은 CI와 같게 `0.16.9`를 사용합니다.

Linux/macOS (bash):
```bash
python3 -m venv .venv/ci
.venv/ci/bin/pip install -r backend/requirements-dev.txt ruff==0.16.9
python3 -B -m unittest discover -s poc/staging/automation/tests -v
(cd backend && ../.venv/ci/bin/python -B -m pytest -p no:cacheprovider -q)
.venv/ci/bin/python -B docs/api/check_openapi.py
.venv/ci/bin/python -B -m unittest discover -s docs/api -p 'test_*.py' -v
.venv/ci/bin/python -B -m unittest discover -s database/tests -p 'test_*.py' -v
python3 -m venv .venv/poc
.venv/poc/bin/pip install -r poc/staging/backend/requirements.txt pytest==8.3.5 httpx==0.28.1
.venv/poc/bin/python -B -m pytest -p no:cacheprovider poc/staging/tests -q
.venv/ci/bin/ruff check --no-cache .
.venv/ci/bin/ruff format --no-cache --check backend scripts/ci
PYTHONPYCACHEPREFIX=/tmp/ci-pycache python3 -m compileall -q backend poc scripts
git ls-files -z '*.sh' | xargs -0 -r -n1 bash -n
python3 -B -m unittest discover -s scripts/ci/tests -v
python3 -B scripts/ci/check_md_links.py
python3 -B scripts/ci/check_env_examples.py
python3 -B scripts/ci/check_secrets.py
(cd frontend && npm ci && npm run lint && npm test && npm run build)  # Node 24
```

Windows PowerShell:
```powershell
py -3.12 -m venv .venv/ci
.\.venv\ci\Scripts\pip install -r backend\requirements-dev.txt ruff==0.16.9
py -3.12 -B -m unittest discover -s poc/staging/automation/tests -v
Push-Location backend; ..\.venv\ci\Scripts\python -B -m pytest -p no:cacheprovider -q; Pop-Location
.\.venv\ci\Scripts\python -B docs/api/check_openapi.py
.\.venv\ci\Scripts\python -B -m unittest discover -s docs/api -p 'test_*.py' -v
.\.venv\ci\Scripts\python -B -m unittest discover -s database/tests -p 'test_*.py' -v
py -3.12 -m venv .venv/poc
.\.venv\poc\Scripts\pip install -r poc\staging\backend\requirements.txt pytest==8.3.5 httpx==0.28.1
.\.venv\poc\Scripts\python -B -m pytest -p no:cacheprovider poc/staging/tests -q
.\.venv\ci\Scripts\ruff check --no-cache .
.\.venv\ci\Scripts\ruff format --no-cache --check backend scripts/ci
$env:PYTHONPYCACHEPREFIX = "$env:TEMP\ci-pycache"; py -3.12 -m compileall -q backend poc scripts; Remove-Item Env:PYTHONPYCACHEPREFIX
py -3.12 -B -m unittest discover -s scripts/ci/tests -v
py -3.12 -B scripts/ci/check_md_links.py
py -3.12 -B scripts/ci/check_env_examples.py
py -3.12 -B scripts/ci/check_secrets.py
Push-Location frontend; npm ci; npm run lint; npm test; npm run build; Pop-Location
```
`bash -n` 셸 문법 검사는 Git Bash 또는 WSL에서 실행합니다. 가상환경은 `.gitignore`에 포함된 `.venv/` 아래에 만듭니다. 무시되지 않는 폴더에 만들면 링크·Secret 검사가 미추적 파일로 읽어 느려지거나 오탐이 생깁니다.

### 알려진 한계
- `poc/staging/automation/tests/test_boundaries.py`의 미사용 import(F401) 1건은 Auto-CD 코드 수정 금지 원칙에 따라 `ruff.toml`에서 예외 처리했습니다. 별도 승인 PR에서 정리합니다.
- actionlint·shellcheck·Python 타입 검사(mypy/pyright)·Frontend E2E·의존성 취약점 검사(npm audit 포함)는 아직 게이트에 없습니다.
- Backend 직접 의존성(pydantic 포함)은 `requirements.txt`에 고정되어 있습니다. 간접 의존성(anyio, starlette 등)은 고정되지 않아 경고·결과가 달라질 수 있습니다.
- 기존 `CI Smoke Test` job의 `actions/checkout@v5`는 Auto-CD 보존을 위해 그대로 두었습니다(태그 고정). 신규 job은 SHA 고정입니다.

## 배포 게이트
- SHA·이미지 Digest·CI 성공·승인 상태 확인.
- 배포 전 디스크·RAM 및 기존 18개 운영 컨테이너 상태 점검.
- 배포 후 Frontend/API/DB HTTP 200 및 오류 로그 확인.
- 확인하지 못한 항목은 PASS가 아니라 `NOT_VERIFIED` 또는 `HOLD`.

## 테스트 데이터
Staging 공통 Seed/샘플 데이터는 유지하되 CI 자동화 테스트는 분리된 DB 또는 트랜잭션으로 격리합니다. 배포 시 DB 초기화 금지.
