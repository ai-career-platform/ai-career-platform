# T93 — 계정 복구·이메일 인증 Backend 검증

> 판정: **PARTIAL**
> - **비밀번호 재설정**: 확정 계약(T06 `requestPasswordReset`·`resetPassword`)과 기존 0001 표(`password_reset_tokens`)로 구현하고 일회용 PostgreSQL에서 검증했습니다.
> - **메일 공급자 미정** → 요청 API는 모두에게 같은 503을 돌려줍니다(실제 운영 활성화 **HOLD**).
> - **이메일 인증**: API 계약과 DB 컬럼이 없어 **설계만** 했습니다(HOLD).
> 확인일 2026-11-11 · 기준 main `1f3cecd` · 실제 메일 발송 0건 · Migration 없음

## 1. 현재 인증 구조 (선행 확인)

| 항목 | 사실 | 근거 |
|---|---|---|
| 인증 방식 | **자체 인증**(이메일·Argon2id 비밀번호, JWT access + HttpOnly refresh 쿠키). 외부 IdP 없음 → 자체 재설정 중복 아님 | T15 #48, `app/services/auth.py` |
| 비밀번호 재설정 계약 | **확정**: 요청은 항상 202(가입 여부 무관), 30분 링크, 재설정 204 + 모든 세션 종료 + 감사 기록, 400 `INVALID_RESET_TOKEN`, 429 | `docs/api/openapi.yaml` |
| DB | `password_reset_tokens`(token_hash 64자 UNIQUE, `expires_at <= created_at + 30분` CHECK, `used_at`) 이미 있음 | 0001 |
| 오류 코드 | `INVALID_RESET_TOKEN`(400) 이미 있음 | `app/core/errors.py` |
| 이메일 인증 | 계약 없음, `users`에 인증 상태 컬럼 없음 | 0001, openapi |
| 메일 공급자 | **없음**(PM 결정 필요) | — |

## 2. 구현 (기존 인증 코드는 바꾸지 않고 별도 모듈)

| 파일 | 내용 |
|---|---|
| `app/services/mail.py` | 발송 어댑터. 기본 `UnavailableMailSender`, 시험용 `MemoryMailSender`(outbox·실패 주입) |
| `app/repositories/account_recovery.py` | SQL(0001 표만). 소비는 한 트랜잭션: 비밀번호 해시 교체 → 남은 토큰 모두 사용 처리 → **모든 세션 종료** → `audit_events`(`auth.password.reset`, request_id) |
| `app/services/account_recovery.py` | 열거 방지, 토큰 생성·해시, 요청 한도, 발송 재시도, 같은 400 |
| `app/routers/account_recovery.py` | `POST /api/v1/auth/password-reset-requests`(202), `POST /api/v1/auth/password-resets`(204) |
| `app/routers/api_v1.py` | 라우터 등록 1줄 |
| `tests/security/security_inventory.py` | T86 공개 경로 목록에 두 경로 추가(계약상 `security: []` — 게이트가 먼저 실패해 검토를 요구했고, 검토 후 등록) |

## 3. 보안 요구사항 대응

| 요구 | 구현 | 시험 |
|---|---|---|
| 계정 존재 여부 비노출 | 있는·없는·비활성 계정 모두 같은 202, 본문 없음. 메일 공급자가 없으면 **가입 여부 확인 전에** 모두 같은 503 | 단위 `test_same_result…`, `test_no_mail_provider…`; PG 응답 본문 동일 |
| 토큰 만료 | 30분(계약·DB CHECK). 만료면 400 | 단위·PG(만료 행), DB가 31분 토큰 거부 |
| 일회용·재사용 차단 | 사용 시 `used_at`, 같은 사용자의 남은 토큰도 모두 무효 | 단위 `reused`·`older_token_after_newer_use`, PG 재사용 400 |
| 재설정 후 인증 상태 | **모든 세션 종료**(기존 access token 즉시 401, 매 요청 DB 재조회). 새 비밀번호 로그인 200, 이전 비밀번호 401. 다른 사용자 영향 없음 | PG 전체 흐름 |
| 요청 빈도 제한 | 요청: 이메일당 3회/시간, IP당 10회/시간. 재설정: IP당 10회/15분 → 429 + `Retry-After` | 단위 |
| 잘못된 링크 | 없음·위조·만료·사용됨·비활성 사용자 모두 **같은 400** | 단위 5종, PG 2종 |
| 토큰 저장 | 원문 저장 안 함, sha256 hex만. 링크에만 원문 | 단위·PG |
| 발송 실패·재시도 | 즉시 최대 3회 시도. 모두 실패하면 토큰 롤백(남기지 않음), 응답은 같은 202 | 단위·PG |
| 같은 접수 메시지 | 202 본문 없음(화면 문구는 T94) | — |
| 로그 비노출 | 이메일·토큰·링크·비밀번호를 로그에 남기지 않음(발송 실패도 횟수만) | 단위·PG(caplog) |

요청 한도 값은 계약에 숫자가 없어 **운영 기본값으로 제안**한 것입니다(PM 확인 필요).

## 4. 시험 결과 (로컬)

| 범위 | 결과 |
|---|---|
| `tests/test_t93_account_recovery.py` (단위, 메모리) | **14 passed** |
| `tests/test_t93_account_recovery_postgres.py` (일회용 PostgreSQL 18, 최소 권한) | **5 passed** — 공급자 없음 503 동일 응답, 전체 흐름(해시 저장·30분·세션 종료·감사·새 비밀번호 로그인·재사용 400·로그), 만료·위조 400, DB 31분 거부, 발송 실패 시 토큰 없음 |
| T86 보안 게이트 | 새 공개 경로 2개를 먼저 실패로 잡았고, 검토·등록 후 PASS |
| 전체 Backend (로컬 Windows, PG) | 1225 passed, 53 skipped, 1 failed + 31 errors — 모두 문서 저장소 POSIX 의존(기존과 동일) |

PG 시험은 T86 `sec_pg`와 같은 가드·최소 권한 fixture를 이 파일 안에 둡니다. 미병합 T87의 공용 `disposable_pg`에 의존하지 않기 위해서입니다.

## 5. HOLD·결정 필요

| 항목 | 상태 | 필요한 것 |
|---|---|---|
| 실제 메일 발송 | **HOLD** — `get_mail_sender`가 항상 Unavailable(환경변수로 켜는 경로 없음) | 메일 공급자·발신 주소·템플릿(T95) 승인 → 의존성 한 곳 교체 |
| 503 응답 | 계약에 없음(요청 API의 공급자 미설정 상태) | T06에 503 추가 또는 공급자 연결 후 제거 |
| 링크 기준 URL | 기본 `/password-reset`(상대). 운영은 절대 URL 필요(`PASSWORD_RESET_LINK_BASE`) | 배포 설정 |
| 요청 한도 값 | 제안값 | PM·보안 확인 |
| 이메일 인증 | **설계만** — §6 | 계약(T06)·컬럼(T05) 승인 |
| 시간 차이로 인한 계정 추측 | 있는 계정만 토큰 저장·발송을 해서 응답 시간이 다를 수 있음(부분 완화만) | 비동기 발송 큐 도입 시 해소(제안) |

## 6. 이메일 인증 설계 (PROPOSED, 구현 안 함)

- **DB(T05 제안, Migration 미작성)**: `users.email_verified_at timestamptz NULL`, `email_verification_tokens`(password_reset_tokens와 같은 구조: 해시·만료 24시간 후보·`used_at`)
- **API(T06 제안)**:
  - `POST /auth/email-verification-requests`: 로그인 사용자, 202, 한도
  - `POST /auth/email-verifications {token}`: 공개, 204, 같은 400
- **규칙**: 미인증 상태에서 제한할 기능은 PM 결정입니다(예: 문서 분석·알림 수신). 재설정·인증 메일은 **필수 보안 알림**(T95 — 마케팅 수신 동의와 무관)입니다.
- **시험 계획**: 위 §3 표와 같은 열거 방지·만료·재사용·한도·로그 항목.

## 7. 실행 방법

```bash
cd backend
APP_ENV=test python -m pytest -q tests/test_t93_account_recovery.py
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/t16_profile_test \
  APP_ENV=test python -m pytest -q tests/test_t93_account_recovery_postgres.py
```

Staging·공유 DB 변경 0건, 실제 이메일 발송 0건, Migration 작성·적용 0건입니다.
