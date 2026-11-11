# T112 검증 보고서 — Staging 관측 체계

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 앱 코드와 시험만 넣었습니다.
> - 운영 수집기, Compose, Nginx, 로그 보존 설정은 바꾸지 않았습니다(승인 필요).

## 1. 목적

웹 → Nginx → API → DB/AI 구간을 같은 요청 ID로 추적합니다. 비밀값·개인정보 없이 오류·지연·상태를 볼 수 있는 최소 관측 계약을 둡니다.

## 2. 선행 일감

| 일감 | 상태 | 사용 |
|---|---|---|
| T28 CI | 병합 | backend-pytest |
| T30 운영 문서 | 병합 | `/health`, `/health/db` |
| T83 감사 | 병합 | `audit_events.request_id`(같은 ID) |
| T86 보안 회귀 | 병합 | Finding F-1(접근 로그 Query 노출), 개선안 프로토타입 |

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/core/observability.py` (신규) | `AccessLogMiddleware`(요청 1줄 `http_request request_id= method= path= status= duration_ms=`), `RequestMetrics`(상태 구간·5xx 비율·지연 구간), `safe_path`(Query 제거·이메일/토큰 모양 가림), `StripQueryFilter`(uvicorn.access) |
| `backend/app/main.py` | 미들웨어 등록(RequestId 안쪽), 필터 설치 — 5줄 |
| `backend/tests/test_t112_observability.py` (신규) | 16건 |
| `backend/tests/security/test_security_logging.py` | T86 F-1 시험 2건을 "적용 후 남지 않음" 기준으로 갱신(아래 §5) |
| `docs/ops/OBSERVABILITY.md` (신규) | 추적 흐름, 로그 필드 계약, 발견 사항, 지표, 켜는 방법, 보존·비용 |
| `docs/ops/observability/nginx_observability.proposed.conf` (신규) | Query·Referer 없는 log_format, `X-Request-ID` 전달 — **미적용** |
| `docs/ops/observability/dashboard_template.json` (신규) | 로그 필드만 쓰는 패널 6개, 보존 제안 |
| `docs/testing/T86_SECURITY_REGRESSION_VALIDATION.md` | F-1 갱신 메모 1줄 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12)

| 범주 | 시험 | 결과 |
|---|---|---|
| ID 연결 | 접근 로그 request_id = 응답 헤더 / 안전한 들어온 ID 유지 / 줄바꿈 주입 ID 교체 | PASS |
| 5xx | 응답 헤더, 접근 로그(status=500), `app.errors` 로그가 같은 ID / 원인 문구는 응답에 없음 | PASS |
| **비노출** | Query 값, 이메일, 가입·로그인 비밀번호, Bearer 토큰, `token=`, `?`가 서버 로그에 없음 | PASS |
| 경로 가림 | Query 제거, 이메일 → `:email`, 43자 토큰 → `:token`, UUID 유지 | PASS (5건) |
| uvicorn 필터 | Query 제거 + `?[query redacted]`, 중복 설치 없음 | PASS |
| 기본 비활성 | `app.access`에 핸들러·레벨을 붙이지 않음(운영 로그 설정 전 출력 안 됨) | PASS |
| 지표 | 2xx/4xx/5xx 집계, 5xx 비율 1/3, 지연 구간 경계(50/50.1/5000/5001), 식별자 미포함 | PASS |
| 제안 설정 | Nginx log_format에 `$request`·`$args`·`$http_referer`·`Authorization`·`Cookie` 없음, `$request_id` 전달 / 대시보드는 로그 필드만 사용 | PASS |
| T86 F-1 (실제 uvicorn 서버, 루프백) | 401 요청의 `actor_user_id`·기간이 접근 로그에 없음, `?[query redacted]` 표시 | PASS |

- `test_t112_observability.py` 16 passed. `security/test_security_logging.py`는 갱신 후 8 passed(합계 24).
- 전체 Backend(T86 시험 갱신 전 실행): 1165 passed / 265 skipped.
  - T86 F-1 시험 2건이 실패했습니다. 이 PR이 고친 현상을 "현재 동작"으로 고정한 시험이었기 때문입니다. 갱신 후 통과합니다.
  - 그 밖의 실패·오류 32건은 기존 Windows 전용 시험입니다. PASS로 세지 않았습니다.
- CI: PR 생성 후 기록합니다.

## 5. 발견 사항

| ID | 심각도 | 내용 | 조치 |
|---|---|---|---|
| F-1 | Medium | `/password-reset?token=…` 재설정 토큰과 감사 API `actor_user_id`(T86 F-1)가 Query로 전달되어 접근 로그에 남음 | uvicorn: 앱 필터 적용(이번 PR). Nginx: 제안만(승인 필요). 근본 대안: 재설정 토큰을 `#fragment`로(PM 결정) |
| F-2 | Low | Nginx가 `X-Request-ID`를 넘기지 않아 Proxy와 앱 로그를 잇지 못함 | 제안 설정 |
| F-3 | Info | 앱 로그 설정이 없어 4xx 원인(INFO)이 기본 출력되지 않음 | 로그 설정 제안(컨테이너 변경, HOLD) |

## 6. 미승인·후속

1. 운영 로그 설정(`--log-config`, `--no-access-log`), Nginx log_format·`X-Request-ID`, Docker 로그 보존: PM 승인 후 별도 PR
2. `/metrics` 노출 여부와 인증 방식(PM 결정)
3. DB·AI 공급자 구간 request_id 전파(후속)
4. 실제 Staging에서 추적 재현: HOLD(접속·설정 변경 승인 필요)
