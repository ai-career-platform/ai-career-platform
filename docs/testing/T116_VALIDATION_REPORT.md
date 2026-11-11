# T116 검증 보고서 — API 하위호환 검사

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code) · BASE_SHA `ab56765`
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=NOT_RUN**
> - 검사기·시험·CI 단계를 넣었습니다.
> - 버전·deprecation 정책은 PROPOSED입니다.
> - CI 단계는 이 PR의 CI에서 처음 실행됩니다.

## 1. 목적

API DTO·경로·오류 의미가 Frontend와 외부 소비자를 깨지 않도록 계약 회귀 검증을 만듭니다.

## 2. 선행 일감

| 일감 | 상태 |
|---|---|
| T06 API 계약 | 병합(`docs/api/openapi.yaml`, `check_openapi.py`) |
| T28·T29 CI | 병합 |
| T90 릴리스 | 병합 |

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `docs/api/check_compat.py` (신규) | 기준 계약 대비 BREAKING·WARN·ALLOWED 판정, `$ref` 해석·순환 방지, CLI(exit 1 = 파괴적) |
| `docs/api/compat_exceptions.yaml` (신규) | 의도한 파괴적 변경 기록(현재 빈 목록, 승인자 필수) |
| `docs/api/error_codes.snapshot.json` (신규) | 오류 코드 27개 → HTTP 상태 기준선 |
| `docs/api/API_COMPATIBILITY_POLICY.md` (신규) | 규칙, 예외 절차, 버전 제안, 이력 재현 결과 |
| `backend/tests/test_t116_api_compat.py` (신규) | 37건 |
| `.github/workflows/backend-tests.yml` | PR에서 base 계약 대비 검사 단계 추가, 경로 필터에 새 파일 추가 |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12)

| 범주 | 시험 | 결과 |
|---|---|---|
| 정상 변경 9종 | 무변경, 응답 필드 추가, 선택 파라미터·요청 필드 추가, 제한 완화, 요청 enum 확장, 새 경로, deprecated 표시, 응답 필드 필수화 | 모두 통과(BREAKING 0) |
| 파괴적 변경 16종 | 경로·메서드 삭제, 새 필수 파라미터, 선택→필수, 자료형 축소, enum 삭제, maxLength 축소, 새 필수 요청 필드, 요청 필드 삭제(422), 응답 필드 삭제(직접·`$ref` 안·배열 안), 필수→선택, 자료형 변경, null 추가, 2xx 코드 변경 | 모두 BREAKING 검출 |
| 경계 | path 레벨 파라미터 삭제, 선택 query·오류 문서 삭제는 WARN, 응답 enum 추가는 WARN | PASS |
| 예외 | 승인자 없음·공백이면 무효, 위치가 정확히 같아야 함, 저장소 예외 목록은 비어 있음 | PASS |
| 견고성 | `$ref` 순환 | PASS |
| 실제 계약 | 현재 계약 자기 비교 0건, **이력 재현으로 `e1e8591` CSRF 헤더 변경 검출**(얕은 checkout이면 skip), PROPOSED 계약 미혼입 | PASS |
| 오류 코드 | `ERROR_CATALOG` = 스냅샷(삭제·상태 변경·추가 모두 실패로 노출) | PASS |
| CLI | 무변경 exit 0, 삭제 exit 1 + 출력 | PASS |

- `test_t116_api_compat.py`: **37 passed**
- CLI 실측(실제 이력):
  - `origin/main` 대비: breaking 0
  - `ab56765~60` 대비: **breaking 7**(CSRF 4건, T31 3건). 정책 문서 §5에 기록했습니다.
- 전체 Backend 회귀: 이 PR은 앱 코드를 바꾸지 않습니다. 시험 파일만 추가했고, 실행은 CI에서 합니다.
- CI: PR 생성 후 기록합니다. 새 CI 단계는 이 PR에서 처음 실행됩니다.

## 5. 미승인·후속

1. 버전·deprecation 정책(PM)
2. FastAPI 실제 스키마(`/openapi.json`)와 확정 계약의 일치 검사는 범위 밖입니다. 기존 기능별 시험이 일부를 확인합니다.
3. 이 단계 때문에 앞으로 계약을 바꾸는 PR은 예외 기록이 필요할 수 있습니다. 예외 기록에는 승인자가 있어야 합니다.
