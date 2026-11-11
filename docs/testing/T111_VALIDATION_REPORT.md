# T111 검증 보고서 — 환경·설정 계약과 Secret 회전 절차

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 회전은 합성 키로만 시뮬레이션했습니다.
> - Staging의 실제 설정·권한은 확인하지 않았습니다(접속 0회).

## 1. 목적과 범위

Local/CI/Staging에서 Backend가 읽는 환경변수를 하나의 계약으로 정했습니다. 함께 다룬 것은 다음과 같습니다.
- 필수값·형식 검사
- Secret 비노출 장치
- Secret 회전·유출 대응 절차

## 2. 선행 일감

| 일감 | 상태 | 이번에 쓴 것 |
|---|---|---|
| T07 저장소 기본 구조 | 병합 | `.gitignore` 규칙 |
| T14 Backend 설정 | 병합 | `config.py`(`DatabaseSettings`) |
| T28 CI 게이트 | 병합 | `ci.yml` backend-pytest(이 시험이 CI에서 실행됨) |
| T90 릴리스 준비 | 병합 | `docs/release/RELEASE_RUNBOOK.md` |

참고: 다른 개발자의 미병합 브랜치 `jungseop/t111-environment-contract-20261106`(commit `355461d`, PR 없음)가 있습니다.
- 이 브랜치는 병합되지 않은 T28 브랜치 위에 있습니다. 그래서 그 코드를 가져오지 않고 main 기준으로 새로 작성했습니다.
- 두 작업의 통합 여부는 리뷰에서 결정이 필요합니다(§6).

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/core/env_contract.py` (신규) | 변수 20개의 계약(대상별 필수 여부, 기본값, Secret 여부, 소유자, 형식 검사)과 `check_environment()`, 값을 출력하지 않는 CLI |
| `backend/tests/test_t111_env_contract.py` (신규) | 시험 33건 |
| `.env.example` | 빠졌던 7개 변수 추가(가짜·기본값만, Secret은 빈 값) |
| `docs/ops/ENVIRONMENT_MATRIX.md` (신규) | 환경 매트릭스(계약 모듈에서 생성), 계정 분리 현황, 검사 명령 |
| `docs/ops/SECRET_ROTATION_RUNBOOK.md` (신규) | JWT·DB 비밀번호 회전, 복귀, 유출 대응 |

앱 동작은 바꾸지 않았습니다. 인증 코드와 기동 경로도 변경이 없습니다.

## 4. 시험 결과 (로컬: Windows 11 · Python 3.12)

| 범주 | 시험 | 결과 |
|---|---|---|
| 계약·코드 동기화 | `backend/app`이 읽는 변수 = 계약 목록(양방향) / `.env.example`에 계약 변수가 모두 있고 Secret은 빈 값 / 매트릭스 문서에 모든 변수 | PASS |
| 정상 | 올바른 Staging 값이면 문제 0건, Local·CI는 값이 없어도 문제 0건 | PASS |
| 필수값 누락 | Staging에서 `APP_ENV`, `APP_VERSION`, `DATABASE_URL`, `JWT_SECRET` 각각 `missing` | PASS |
| 잘못된 값 14종 | 짧은 JWT(`weak`), 자리표시자 JWT·DB URL(`placeholder`), MySQL URL·잘못된 % 인코딩(`invalid`), `APP_ENV=production`·`AUTH_COOKIE_SECURE=false`·http/`//` 재설정 링크(`forbidden_in_target`), 범위 밖 정수, 플래그 오타(`ture`), 비율 형식 | PASS |
| 파서 일치 | 경계값(풀 100/101, TTL 3601)에서 계약 검사와 실제 `from_env` 결과가 같음 | PASS |
| 기동 거부 | Staging에서 `JWT_SECRET`이 없거나 32자 미만이면 `create_app()` 거부 | PASS |
| **비밀 비노출** | 표식 문자열이 계약 결과·CLI 출력·설정 `repr`·설정 오류 메시지·기동 로그·`/version`에 없음 | PASS |
| Git 추적 | 실제 `.env`·키 파일(`*.pem`, `id_rsa` 등) 추적 0건, `.gitignore` 규칙, 예제 파일의 Secret 변수·URL 자격정보는 빈 값·자리표시자만 | PASS |
| **회전 A→B→A** | 옛 키 토큰 거부 / 앱 수준: A 토큰 200 → B 전환 후 401 → refresh로 B 토큰 200(재로그인 없음) → A로 복귀 후 B 토큰 401, refresh 계속 유효 / 목록 cursor는 회전 후 `INVALID_CURSOR` | PASS |

- `test_t111_env_contract.py`: **33 passed**
- 전체 Backend: **1184 passed / 265 skipped**. 실패·오류 32건은 기존 Windows 전용 시험(`test_documents.py`, `security/test_security_upload.py`, POSIX 권한 의존)으로 이번 변경과 무관하며, PASS로 세지 않았습니다. 같은 시험이 Linux CI에서는 통과합니다.
- skipped에는 일회용 PostgreSQL 시험이 포함됩니다. 이번 로컬 실행에서는 DB를 띄우지 않았고, CI의 Postgres 서비스에서 실행됩니다.
- CI: PR 생성 후 기록합니다.

## 5. 발견 사항

| ID | 내용 | 조치 |
|---|---|---|
| F-1 | `JWT_SECRET`을 회전하면 access token은 즉시 무효가 되지만 refresh 세션은 유지됩니다. refresh token이 해시로 저장되기 때문입니다. 그래서 짧은 401 뒤 자동으로 복구됩니다. 목록 cursor도 같은 키로 서명되어 함께 무효가 됩니다 | Runbook §1·§2에 기록, 시험으로 고정 |
| F-2 | DB 역할 하나에는 비밀번호가 하나뿐이라, 비밀번호를 바꿀 때 새 연결이 실패하는 구간이 생깁니다 | 두 역할 교대안 PROPOSED(공유 DB 변경이라 HOLD) |
| F-3 | `config.py`는 플래그를 `'true'` 외에는 모두 꺼짐으로 읽습니다. 오타(`ture`)는 조용히 꺼집니다 | 계약 검사가 `invalid`로 보고(코드 동작은 그대로, 안전 방향) |
| F-4 | 루트 `.env.example`에 `APP_ENV`, `APP_VERSION`, 기능 플래그 등 7개가 없었습니다 | 추가 |

## 6. 미승인·후속

1. PM 검토: 환경 매트릭스와 소유자 지정, Staging 필수값 4개
2. 이중 키 검증(`JWT_SECRET_PREVIOUS`): 인증 코드 변경이라 보안 리뷰와 승인이 필요합니다(PROPOSED)
3. 실제 Staging에서 `python -m app.core.env_contract --target staging` 실행과 앱 계정 권한 확인: 서버 접근 승인이 필요합니다(HOLD)
4. `jungseop/t111-environment-contract-20261106` 브랜치와의 통합 여부. 그 브랜치에는 `scripts/ci/check_env_examples.py`가 있습니다.
5. 새 환경변수를 추가하는 PR은 이 계약에도 함께 추가해야 합니다. 빠뜨리면 이 시험이 실패합니다.
