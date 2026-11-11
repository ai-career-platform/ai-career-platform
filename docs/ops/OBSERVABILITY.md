# Staging 관측 계약 (T112)

> 상태: **PROPOSED**, PM 검토 전입니다.
> - 운영 수집기, Compose, Nginx 설정은 바꾸지 않았습니다.
> - 앱 코드에는 다음 두 가지만 넣었습니다.
>   1. 요청 단위 구조화 로그와 지표 누적. 로거가 기본 비활성이라 출력되지 않습니다.
>   2. uvicorn access log의 Query String 제거.

## 1. 추적 ID 흐름

```
브라우저 ──> Nginx ──(X-Request-ID)──> Backend ──> 응답 헤더 X-Request-ID
                                          ├─ app.access 로그 request_id=
                                          ├─ app.errors 로그 request_id= (4xx INFO, 5xx ERROR + 스택)
                                          └─ 감사 기록 audit_events.request_id
```

| 구간 | 현재 | 이번 변경 |
|---|---|---|
| Nginx → Backend | **ID를 넘기지 않음**. Backend가 `req-…`를 새로 만듦 | 제안 설정 `nginx_observability.proposed.conf`(`proxy_set_header X-Request-ID $request_id`). **미적용** |
| Backend 내부 | `RequestIdMiddleware`(기존 구현). 안전한 형식이면 들어온 값을 그대로 쓰고, 아니면 새로 만듦 | 재사용, 변경 없음 |
| Backend 로그 | 오류 로그에만 request_id가 있음 | 모든 요청 1줄 `http_request request_id= method= path= status= duration_ms=` |
| DB | 요청 ID가 없음 | **미구현**. `application_name`·주석 태깅은 연결 풀 공유 때문에 요청 단위 적용이 어려움(후속) |
| AI 공급자 | 실제 공급자 미연결(Mock) | 연결 시 request_id를 공급자 호출 로그에 남기는 것을 계약으로 둠(T113 Runbook) |

## 2. 로그 필드 계약

| 필드 | 값 | 넣지 않는 것 |
|---|---|---|
| `request_id` | `req-` + 16진수, 또는 Proxy 값 | — |
| `method` | GET 등 | — |
| `path` | **경로만**. 이메일 모양 구간은 `:email`, 40자 이상 토큰 모양 구간은 `:token`. UUID는 남김(불투명 ID) | Query String, 요청 본문, `Authorization`, `Cookie` |
| `status` | 응답 코드. 처리 중 예외는 500 | — |
| `duration_ms` | 앱 처리 시간 | — |

시험에서 표식 문자열로 확인한 비노출 항목은 다음과 같습니다.
- Query 값(`?q=`, `?email=`, `?token=`)
- 비밀번호(가입·로그인 실패)
- Bearer 토큰
- 이메일
- 줄바꿈이 들어간 ID 주입 시도

## 3. 발견 사항

| ID | 심각도 | 내용 | 조치 |
|---|---|---|---|
| **F-1** | Medium | 비밀번호 재설정 링크가 `/password-reset?token=…` 형식(T93·T94)입니다. 그런데 Nginx 기본 `combined` 형식은 `$request`(Query 포함)를 남기므로 **재설정 토큰이 Proxy access log에 남습니다**. uvicorn 기본 access log도 Query를 남깁니다(API 경로에 한함). 토큰은 1회용이고 TTL이 있어 위험이 제한되지만, 로그를 읽을 수 있는 사람은 유효시간 안에 계정을 탈취할 수 있습니다 | ① uvicorn access log: **Query 제거 필터 적용**(이번 PR, `?[query redacted]` 표식만 남김). T86 Finding F-1(감사 API `actor_user_id`가 Query로 접근 로그에 남음)과 같은 원인이라, T86의 개선안 프로토타입을 앱에 넣고 T86 시험을 "남지 않음" 기준으로 갱신 ② Nginx: Query·Referer를 뺀 log_format **제안**(미적용, 승인 필요) ③ 근본 대안으로 토큰을 URL fragment(`#token=`)로 옮기는 방안 제안(T94 화면·T93 메일 계약 변경이라 PM 결정) |
| F-2 | Low | Nginx가 `X-Request-ID`를 넘기지 않아 Proxy 로그와 앱 로그를 같은 ID로 잇지 못합니다 | 제안 설정 |
| F-3 | Info | 앱이 로그 설정을 하지 않아 `app.errors`의 INFO(4xx 원인)는 기본 설정에서 출력되지 않습니다. 5xx(ERROR)만 출력됩니다 | 로그 설정 제안(§5). 운영 컨테이너 변경이라 HOLD |

## 4. 지표 (최소 계약)

| 지표 | 계산 | 출처 |
|---|---|---|
| 요청 수 | 상태 구간(2xx/3xx/4xx/5xx)별 건수 | `RequestMetrics`(프로세스 안 누적) 또는 로그 |
| 5xx 비율 | 5xx / 전체 | 같음 |
| 지연 분포 | 구간 50·100·250·500·1000·2500·5000ms·초과 | 같음 |
| 상태 확인 | `/health`(프로세스), `/health/db`(DB 연결) | 기존 엔드포인트 |

- `RequestMetrics`는 `app.state.request_metrics`에 있고 **외부로 노출하는 엔드포인트가 없습니다**.
  - `/metrics`를 공개하면 내부 정보가 노출될 수 있습니다. 공개 여부·인증 방식은 PM 결정 사항입니다.
- 대시보드 패널 정의: `observability/dashboard_template.json`. 로그 필드만으로 계산할 수 있게 정의했습니다. 수집기가 정해지지 않아 쿼리 문법은 비워 두었습니다.

## 5. 켜는 방법 (승인 후, 이번에 하지 않음)

1. uvicorn `--log-config`에 `app.access`, `app.errors` 로거를 INFO로 추가하고, 출력은 stdout(JSON 권장)으로 합니다. Backend 이미지 CMD 변경이므로 Auto-CD 정책 변경은 아닙니다. 다만 **운영 컨테이너 변경이라 PM 승인이 필요**합니다.
2. 앱 로그가 생기면 uvicorn 기본 access log와 중복됩니다. `--no-access-log`를 함께 검토합니다.
3. Nginx에 제안 log_format과 `X-Request-ID` 전달을 반영합니다(Frontend 이미지).
4. 보존: Docker `json-file` 로그 드라이버에 `max-size`/`max-file`을 지정합니다(Compose 변경이라 승인 필요).

## 6. 보존·비용 (제안)

| 대상 | 보존 | 근거 |
|---|---|---|
| 앱·Proxy 로그 | 14일 | PoC·비상업. 장애 분석에 2주면 충분하고, 개인정보가 없는 필드만 남김 |
| 지표 | 30일 | 추세 비교(T119) |
| 감사 기록 | 기존 정책(T83/T84) | 이번 범위 아님 |

- 비용: 외부 수집 서비스를 쓰지 않습니다. 디스크는 한 줄에 약 150B입니다. 하루 10만 요청이면 약 15MB/일, 14일이면 약 210MB입니다(계산값이며 실측 아님).
