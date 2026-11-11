# 환경 매트릭스 (T111)

> 상태: **PROPOSED** — PM 검토 전. 실제 Staging 값은 확인하지 않았습니다(접속 0회).
> 원천: [`backend/app/core/env_contract.py`](../../backend/app/core/env_contract.py). 표는 이 모듈에서 생성했습니다.
> 시험 `backend/tests/test_t111_env_contract.py`는 코드가 읽는 이름과 이 계약이 어긋나면 실패합니다.

## 1. Backend 환경변수

| 변수 | Local | CI | Staging | 코드 기본값 | Secret | 소유 | 잘못된 값일 때 | 설명 |
|---|---|---|---|---|---|---|---|---|
| `APP_ENV` | 선택 | 선택 | **필수** | `local-dev` | 아니오 | DevOps | 기본값 사용 | 실행 환경 이름. local-dev/test 외에서는 JWT_SECRET 필수 |
| `APP_VERSION` | 선택 | 선택 | **필수** | `0.1.0` | 아니오 | DevOps(Auto-CD) | 기본값 사용 | 배포 SHA. /version 에 노출 |
| `DATABASE_URL` | 선택 | 선택 | **필수** | — | 예 | DBA | 형식 오류면 기동 거부, 없으면 DB 기능 비활성 | 앱 계정 PostgreSQL URL. 없으면 DB 기능 비활성 |
| `DB_POOL_SIZE` | 선택 | 선택 | 선택 | `5` | 아니오 | DevOps | 기동 거부 | 연결 풀 크기 1~100 |
| `DB_TIMEOUT_SECONDS` | 선택 | 선택 | 선택 | `5` | 아니오 | DevOps | 기동 거부 | 연결 대기 1~60초 |
| `JWT_SECRET` | 선택 | 선택 | **필수** | — | 예 | 보안 담당 | local-dev/test 외에서 없으면 기동 거부, 32자 미만 거부 | HS256 서명·cursor 서명 키(32자 이상). local-dev/test 에서만 생략 가능(프로세스별 임의 키) |
| `ACCESS_TOKEN_TTL_SECONDS` | 선택 | 선택 | 선택 | `900` | 아니오 | 보안 담당 | 기동 거부 | 60~3600 |
| `REFRESH_TOKEN_TTL_SECONDS` | 선택 | 선택 | 선택 | `1209600` | 아니오 | 보안 담당 | 기동 거부 | 3600~2592000 |
| `AUTH_COOKIE_SECURE` | 선택 | 선택 | 선택 | `true` | 아니오 | 보안 담당 | 기동 거부 | refresh 쿠키 Secure. Staging 에서 false 금지 |
| `LOGIN_MAX_FAILURES` | 선택 | 선택 | 선택 | `5` | 아니오 | 보안 담당 | 기동 거부 | 1~100 |
| `LOGIN_LOCK_SECONDS` | 선택 | 선택 | 선택 | `900` | 아니오 | 보안 담당 | 기동 거부 | 10~86400 |
| `LOGIN_IP_MAX_ATTEMPTS` | 선택 | 선택 | 선택 | `30` | 아니오 | 보안 담당 | 기동 거부 | 1~10000 |
| `SIGNUP_IP_MAX_ATTEMPTS` | 선택 | 선택 | 선택 | `10` | 아니오 | 보안 담당 | 기동 거부 | 1~10000 |
| `AUTH_RATE_WINDOW_SECONDS` | 선택 | 선택 | 선택 | `900` | 아니오 | 보안 담당 | 기동 거부 | 10~86400 |
| `PASSWORD_RESET_LINK_BASE` | 선택 | 선택 | 선택 | `/password-reset` | 아니오 | Backend | 기본값 사용 | 재설정 링크 기준 주소. Staging 에서는 같은 Origin 경로 또는 https 만 |
| `DOCUMENT_STORAGE_ROOT` | 선택 | 선택 | 선택 | — | 아니오 | DevOps | 없으면 파일 I/O 비활성 | 문서 저장 절대경로(0700). 없으면 파일 I/O 비활성 |
| `BEHAVIOR_EVENTS_ENABLED` | 선택 | 선택 | 선택 | `false` | 아니오 | PM(승인) | 1/true/yes 외 값은 꺼짐 | 행동 이벤트 수집. 승인 전 꺼짐 |
| `BEHAVIOR_EVENTS_RATE_LIMIT` | 선택 | 선택 | 선택 | — | 아니오 | Backend | 기동 거부 | <count>/<seconds> |
| `JOB_SEARCH_ADVANCED` | 선택 | 선택 | 선택 | `false` | 아니오 | PM(승인) | 'true' 외 값은 꺼짐(계약 검사가 오타 보고) | T99 고급 검색. 승인 전 꺼짐 |
| `JOB_APPLICATIONS_API` | 선택 | 선택 | 선택 | `false` | 아니오 | PM(승인) | 'true' 외 값은 꺼짐(계약 검사가 오타 보고) | T102 지원 기록 API. 승인 전 꺼짐 |
| `COMPANY_ACCOUNTS_API` | 선택 | 선택 | 선택 | `false` | 아니오 | PM(승인) | 'true' 외 값은 꺼짐 | T123 기업 계정 API. 승인 전 꺼짐 |

- **Local**: 아무 값도 없어도 기동합니다. `JWT_SECRET`이 없으면 프로세스마다 임의 키를 쓰고, 재시작하면 토큰이 무효가 됩니다.
- **CI**: Local과 같습니다. Postgres 시험은 별도 변수(`T16_ISOLATED_DB_TEST` 등)를 써서 일회용 DB에서만 돕니다. 이 변수들은 앱 설정이 아니라 시험 설정입니다.
- **Staging**: `APP_ENV=staging`, `APP_VERSION`(배포 SHA), `DATABASE_URL`, `JWT_SECRET`이 필수입니다. 그 밖의 검사는 다음과 같습니다.
  - 자리표시자 Secret을 막습니다(`change-me`, `example` 등).
  - `AUTH_COOKIE_SECURE=false`를 막습니다.
  - 재설정 링크는 같은 Origin 경로나 https만 허용합니다.

## 2. Backend 밖의 변수 (계약 모듈 범위 밖, 참고용)

| 구성요소 | 변수 | Secret | 비고 |
|---|---|---|---|
| Staging Compose(`poc/staging/compose.yaml`) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PASSWORD 예 | `${VAR:?}`로 필수 처리. 값은 서버의 비공개 `.env`. 예제는 `poc/staging/.env.example`(자리표시자) |
| Auto-CD Compose(`compose.release.yaml`) | `BACKEND_IMAGE`, `DEPLOY_SHA`, `JWT_SECRET`, `DATABASE_URL` | JWT·URL 예 | 이미지 digest 고정, SHA 필수 |
| Crawler | `CRAWLER_DB_MODE`, `CRAWLER_STAGING_DATABASE_URL`, `CRAWLER_LIVE_SCHEDULE_APPROVED` | URL 예 | 기본 `local`·`0`(실수집 미승인) |
| Migration 러너 | `MIGRATE_ROLE`(기본 `career_migrator`), `MIGRATE_PSQL` | 아니오 | 접속 정보는 실행자가 입력. 앱 계정과 분리 |
| Frontend(`frontend/.env.example`) | `VITE_API_BASE_URL`, `VITE_API_MOCK`, `VITE_*_UI` | **넣으면 안 됨** | `VITE_*`는 브라우저 번들에 그대로 노출 |
| 운영자 PC(루트 `.env.example`) | `STAGING_SSH_*` | 키 경로만 | 키 파일 자체는 저장소 밖 |

## 3. 최소 권한 계정 분리 (현재 구조 확인 결과)

| 계정 | 용도 | 권한 | 근거 |
|---|---|---|---|
| `career_app` | Backend 실행 | `career` 스키마 기본 CRUD, 이력 스키마 접근 불가 | `database/migrations/README.md` |
| `career_migrator` | Migration 러너 | DDL, `career_migration.schema_migrations` | `database/migrate.py --role` |
| PostgreSQL 관리자 계정 | 운영 관리 | 전체 | **개발자·GitHub에 배포 금지**(T111 §5) |

- Staging의 실제 권한 부여 상태는 이번에 확인하지 않았습니다(HOLD, 접속 승인 필요).
- `DATABASE_URL`에 관리자 계정을 쓰지 않는지는 계약 모듈이 검사할 수 없습니다. 배포 체크리스트에서 사람이 확인합니다.

## 4. 검사 명령 (값은 출력하지 않음)

```bash
cd backend
python -m app.core.env_contract --target staging   # 문제 있으면 exit 1, "FAIL 이름: 문제"만 출력
```

| 문제 | 뜻 |
|---|---|
| `missing` | 필수인데 비었음 |
| `invalid` | 형식·범위 오류(코드 파서와 같은 범위) |
| `weak` | 길이 부족(JWT 32자 미만) |
| `placeholder` | 예제 값 그대로(`change-me`, `example` 등) |
| `forbidden_in_target` | 그 환경에서 금지된 값(Staging의 `AUTH_COOKIE_SECURE=false`, `APP_ENV≠staging`, http 재설정 링크) |
