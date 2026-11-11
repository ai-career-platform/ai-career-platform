# 내 데이터 반출 요청 API (T142)

> 상태: **PROPOSED · 기본 꺼짐.** `PERSONAL_DATA_REQUESTS_API=true`일 때만 경로가 등록됩니다. 저장소 migration이 승인되기 전이라, 켜도 기본 의존성은 503 `DEPENDENCY_UNAVAILABLE`입니다.
> - 정책: [T141](T141_DATA_SUBJECT_REQUEST_POLICY.md), [`t141_data_subject_requests.json`](t141_data_subject_requests.json)
> - 코드: `backend/app/services/personal_data_requests.py`, `backend/app/routers/personal_data_requests.py`
> - 제안 DDL: `database/proposed/T142_personal_data_requests.sql`(적용 금지, 일회용 DB에서만 검증)

## 1. 재사용과 범위

- **삭제 요청은 새로 만들지 않습니다.** T31 `POST/GET /api/v1/me/deletion-request`를 그대로 쓰고, 목록 API에서 T141 상태 이름으로만 바꿔 보여 줍니다.
  - 변환: `requested→received`, `cancelled→cancelled`, `completed→closed`
- 새로 만든 것은 반출(export) 요청, 재인증, 1회용 다운로드입니다.
- 열람·정정은 기존 조회·수정 API를 씁니다(T141 §2).

## 2. 경로 (`/api/v1/me/data-requests`, 모두 로그인 필수)

| 메서드·경로 | 재인증 | 성공 | 오류 |
|---|---|---|---|
| `POST /reauth` `{password}` | — | 200 `{reauth_token, expires_at}`(10분) | 401 `INVALID_CREDENTIALS`, 429 |
| `GET /` | — | 200 `{items}`(반출 + T31 탈퇴) | 401 |
| `POST /exports` | 필요 | 202 `received`, `Location` | 403(+`X-Reauth-Required`), 409 `CONFLICT`, 429 |
| `GET /exports/{id}` | — | 200 | 404(타인·없음) |
| `POST /exports/{id}/cancel` | — | 200 `cancelled` | 404, 409(처리 시작 후) |
| `POST /exports/{id}/download-link` | 필요 | 201 `{token, expires_at, uses:1}` | 403, 404, 409(완료 전·만료) |
| `POST /download` `{token}` | — | 200 JSON 첨부(64 KiB 단위 전송) | 404(잘못·사용·만료·타인), 422 |

- 응답은 모두 `Cache-Control: no-store`입니다.
- 재인증 토큰은 `X-Reauth-Token` 헤더로 받습니다. 그 **세션과 사용자에게만** 유효합니다.
- 다운로드 토큰은 **URL에 넣지 않고** POST 본문으로 받습니다. 접근 로그·Referer로 새지 않게 하기 위해서입니다.
- 오류 코드는 기존 코드만 씁니다(T116 스냅샷 변경 없음). 재인증이 필요하다는 사실은 403 응답의 `X-Reauth-Required: true` 헤더로 구분합니다.

## 3. 동작 규칙

| 규칙 | 구현 |
|---|---|
| 열린 요청 1건 | `received`·`in_progress`·`failed`·`completed` 중 하나가 있으면 409. 동시 요청은 잠금 안에서 하나만 성공 |
| 30일 3건 | 넘으면 429 |
| Worker 잡기 | 잠금 안에서 `received→in_progress`. Worker 둘이 같은 요청을 잡지 않음 |
| 실패·재시도 | 원본 읽기 실패 시 `failed`(`dependency_unavailable`). 3회까지 `received`로 되돌림. `export_too_large`는 재시도하지 않음 |
| 크기 한도 | 50 MiB. 넘으면 `failed`(`export_too_large`), 묶음은 저장하지 않음 |
| 반출 제외 | T141 `never_export_columns`를 **어떤 깊이에서도** 제거(비밀번호·토큰 해시, IP 해시, 저장 키, 행 해시) |
| 다운로드 | 링크는 10분·1회. 새 링크를 만들면 이전 링크는 무효. 받으면 요청은 `expired`, 묶음 삭제 |
| 만료 | 완료 후 24시간이 지나면 `expired`, 묶음 삭제 |
| 타인 | 조회·취소·링크·다운로드 모두 404. 타인이 토큰을 써 보면 그 토큰도 소모(유출 시 피해 최소화) |
| 저장 | 재인증·다운로드 토큰은 SHA-256 해시만 저장 |
| 감사 | `privacy.export.request`, `privacy.dsr.{reauth,start,complete,fail,retry,cancel,download,expire}`. 메타데이터는 허용 키(`request_id`, `request_type`, `from`, `to`, `reason_code`, `result`)만 |

## 4. 운영 연결 전에 필요한 것 (HOLD)

1. T141 정책 승인
2. 제안 DDL을 정식 migration으로 승인하고 적용(T115 게이트)
3. SQL 저장소, 비밀번호 확인 연결(T15 `auth_identities`), 원본 수집기(T141 §6 표별 조회)
4. Worker 실행 방식(T145 백그라운드 작업 계약)과 묶음 저장 위치(T144 암호화 저장소)
5. 이 일감은 운영 Worker나 Timer를 켜지 않았습니다.
