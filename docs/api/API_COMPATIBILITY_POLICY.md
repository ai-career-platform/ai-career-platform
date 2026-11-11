# API 하위호환 정책 (T116)

> 상태: **PROPOSED**. 검사기·CI 규칙은 이 PR에 들어 있습니다. 버전 정책(§4)은 PM 승인 전입니다.
> 승인 전에는 "기존 클라이언트 호환 제거 금지"(T116 §5)만 강제합니다.

## 1. 기준선

- 기준 계약: **base 브랜치(main)의 `docs/api/openapi.yaml`**. PR은 이 파일과 비교합니다.
- `docs/**/t*_openapi_proposal.yaml`(PROPOSED)은 비교 대상이 아닙니다. 확정 계약에 자동으로 합치지 않습니다.
- 오류 코드 기준선: `docs/api/error_codes.snapshot.json`(코드 → HTTP 상태). `app/core/errors.py`의 `ERROR_CATALOG`와 같아야 합니다.

## 2. 규칙

| 구분 | BREAKING (CI 실패) | WARN (보고만) |
|---|---|---|
| 경로·메서드 | 삭제 | 추가 |
| 파라미터 | 새 필수 파라미터, 선택 → 필수, 자료형 축소, 요청 enum 값 삭제, 길이·범위 축소, 패턴 변경, path·header·필수 파라미터 삭제 | 선택 query 삭제(FastAPI는 모르는 query를 무시) |
| 요청 본문 | 본문 필수화, 새 필수 필드, `additionalProperties:false`인데 필드 삭제(보내면 422) | — |
| 응답 | 필드 삭제, 필수 → 선택, 자료형 변경(**null 추가 포함**), 2xx 코드 삭제·변경 | 응답 enum 값 추가, 4xx·5xx 문서 삭제, 2xx 코드 추가 |
| 오류 코드 | 코드 삭제, 같은 코드의 HTTP 상태 변경 | 추가는 스냅샷 갱신 필요(리뷰에서 보이도록 시험이 실패) |

## 3. 의도한 파괴적 변경

1. PR에 영향받는 클라이언트(Frontend 화면, 외부 소비자)와 같은 릴리스로 함께 바꾸는지 기록합니다.
2. `docs/api/compat_exceptions.yaml`에 `location`, `rule`(검사기 출력 그대로), `approved_by`, `reference`, `reason`을 추가합니다. **`approved_by`가 비어 있으면 무효**입니다.
3. 병합 뒤에는 기준선이 바뀌므로 다음 PR에서 항목을 지웁니다.

## 4. 버전·Deprecation (PROPOSED, PM 결정 필요)

- 현재는 `/api/v1` 하나이고, 외부 소비자 없이 같은 저장소의 Frontend만 소비합니다.
- 제안 1:
  - 필드·경로를 없애기 전에 먼저 `deprecated: true`와 `x-sunset: YYYY-MM-DD`를 표시합니다.
  - 최소 1회 릴리스 동안 유지한 뒤 예외 기록과 함께 삭제합니다.
- 제안 2: 같은 의미의 응답을 크게 바꿔야 하면 새 경로나 새 필드로 추가합니다. `/api/v2`는 외부 소비자가 생기면 결정합니다.

## 5. 이력 재현 결과 (실제 main 이력)

검사기를 과거 커밋에 돌린 결과, 예외 기록 없이 들어간 파괴적 변경 7건을 찾았습니다.

| 커밋 | 변경 | 검출 |
|---|---|---|
| `e1e8591` (#166 CSRF·XSS 보호) | 가입·로그인·refresh·logout에 `X-CSRF-TOKEN` 필수 헤더 | BREAKING 4건(new required parameter) |
| `d4a79b4` (#139 T31 동의·탈퇴 API) | 탈퇴 요청 응답 `scheduled_purge_at`이 null 허용, 동의 `policy_version` 최소 길이 1 | BREAKING 3건(response type widened ×2, request constraint tightened) |

- 두 변경 모두 Frontend를 같은 릴리스에서 함께 바꿨으므로 실제 장애는 없었던 것으로 보입니다. 다만 당시에는 기록이 없었습니다.
- 앞으로는 §3의 예외 기록으로 남깁니다.
