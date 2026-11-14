# T142 검증 보고서 — 내 데이터 반출 요청·상태 API

## 1. 작업 목적
T141 정책을 따라 본인 데이터 반출 요청, 처리 상태 조회, 재인증, 1회용 다운로드 API를 만듭니다. 기능은 **플래그 뒤, 기본 꺼짐**입니다.

## 2. 기존 구현·PR 재사용
- **T31 탈퇴 요청**(#139): 다시 만들지 않았습니다. 목록 API에서 T141 상태 이름으로 바꿔 보여 주기만 합니다(`DeletionSource`).
- **T15 인증**: `CurrentUserDep`(DB에서 세션·역할 재확인), `verify_password`(argon2), `AttemptLimiter`
- **T129 패턴**: 플래그 등록, 저장소 없으면 503, 토큰은 SHA-256 해시만 저장
- **T111 환경 계약**: `PERSONAL_DATA_REQUESTS_API`를 `env_contract.py`, `.env.example`, `ENVIRONMENT_MATRIX.md`에 추가

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- 스택: T141 브랜치 `task/t141-data-access-policy`(#230) 위
- HEAD_SHA: PR 댓글에 기록

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `backend/app/services/personal_data_requests.py` | 서비스·메모리 저장소 |
| `backend/app/routers/personal_data_requests.py` | 경로 7개 |
| `backend/app/core/config.py`, `backend/app/main.py` | 플래그 등록(기본 꺼짐) |
| `backend/app/core/env_contract.py`, `.env.example`, `docs/ops/ENVIRONMENT_MATRIX.md` | 환경 계약에 플래그 추가 |
| `database/migrations/0006_personal_data_requests.sql` | (구 제안 DDL) migration 0006 으로 승격. 운영(GCP) 적용은 별도 PM 승인 |
| `backend/tests/test_t142_personal_data_requests.py` | API 시험 25건 |
| `backend/tests/test_t142_proposed_ddl_postgres.py` | 제안 DDL 시험 5건(`T142_ADMIN_URL`이 있을 때만) |
| `docs/privacy/T142_PERSONAL_DATA_EXPORT_API.md` | API 설명 |

## 5. 선행조건
| 일감 | 상태 |
|---|---|
| T31 | 병합. 물리 삭제 미구현 |
| T49 | 병합(문서 저장소). 반출 묶음에 파일 원본 포함은 T144 이후 |
| T83 | 병합(계약). 감사 표 실연동 없음 → 메모리 감사 목록으로 검증 |
| T141 | **#230 미병합(PROPOSED)** |

## 6. 실제 실행 명령
```bash
cd backend
python -m pytest -q tests/test_t142_personal_data_requests.py
T142_ADMIN_URL=postgresql://<admin>@127.0.0.1:55496/postgres python -m pytest -q tests/test_t142_proposed_ddl_postgres.py
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=... T142_ADMIN_URL=... python -m pytest -q   # 전체 회귀
python ../docs/api/check_compat.py --base-ref origin/main
```

## 7. 정상·오류·권한 검증 (API 25건)
- **정상**: 요청 → 처리 → 링크 → 다운로드 → `expired`, 묶음 삭제. 목록에 T31 탈퇴 상태 포함
- **재인증**
  - 없음·위조 → 403 + `X-Reauth-Required`, 틀린 비밀번호 → 401
  - 10분 지나면 403
  - 다른 세션·다른 사용자의 토큰 → 403
  - 시도 제한 429(잠금 중에는 맞는 비밀번호도 거부)
- **소유권**: 타인의 조회·취소·링크·다운로드 → 404, 목록 비어 있음
- **익명**: 401(5개 경로)
- **1회용·만료**
  - 두 번째 다운로드 → 404
  - 링크는 10분 뒤 404, 묶음은 24시간 뒤 `expired`
  - 새 링크를 만들면 이전 링크 무효
- **민감 필드**: 비밀번호·토큰 해시, IP 해시, 저장 키, 행 해시가 중첩 깊이까지 묶음에 없음(값 문자열로도 확인)
- **대용량**: 약 1.4 MB 묶음을 64 KiB 단위로 전송하고 `Content-Length`가 일치. 한도 초과는 `failed`(`export_too_large`), 재시도 없음
- **중복·동시**
  - 열린 요청이 있으면 409 `CONFLICT`
  - 8개 스레드가 동시에 요청 → 정확히 1건 생성, 7건 CONFLICT
  - Worker 10개 동시 → 요청 5건을 각각 한 번씩만 처리
- **재시도**: 실패 3회 뒤 멈추고, 실패 뒤 성공으로 복구. 30일 3건 제한 429
- **취소**: 처리 시작 전만 가능, 그 뒤 409
- **감사**: 전 단계 기록. 메타데이터에 이메일·토큰·데이터 값 없음, 허용 키만
- **정책 일치**: 상수 = T141 JSON, 전이·감사 액션 = T141 전이
- **기본 꺼짐**: 플래그가 없으면 OpenAPI에 경로 없음. 켜도 저장소가 없으면 503

## 8. PostgreSQL / Mock / 실제 API 구분
| 구분 | 결과 |
|---|---|
| API(FastAPI TestClient + T15 메모리 인증 저장소) | PASS 25 |
| 제안 DDL, 일회용 PostgreSQL 18.6(`t142_ddl_*` DB 생성 → 삭제) | PASS 5. 열린 요청 유일, 사유 필수, 담당자≠요청자, 24시간, 토큰 해시 형식·10분, 링크 1개, 세션 삭제 시 재인증 허가 삭제, 탈퇴 시 익명화 |
| SQL 저장소 실연동 | **NOT_RUN**(migration 미승인) |
| 실제 서버 API(플래그 켠 서버) | **NOT_RUN** |
| Staging | NOT_RUN |

### 전체 회귀 (로컬 Windows, 일회용 PG 18.6, `T16_ISOLATED_DB_TEST=YES`)
- **1686 passed, 101 skipped**, 1 failed, 31 errors
- 1 failed·31 errors는 모두 `tests/test_documents.py`·`tests/security`의 `DOCUMENT_STORAGE_ROOT must have mode 0700`입니다(Windows에서 POSIX 권한 검사). **main `822fa16`에서도 같은 1 failed·31 errors**(같은 두 묶음: 403 passed)라 이 변경과 무관합니다. Linux CI에서 판정합니다.
- T116 호환성: `check_compat.py --base-ref origin/main` → `breaking=0 warn=0`

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- T141 정책 승인, 제안 DDL의 정식 migration 승인
- SQL 저장소·원본 수집기·Worker 실행(T145)·묶음 암호화 저장(T144)
- 문서 원본 파일 포함 여부(T141 §9-6)

## 11. 후속 작업
- T143: 내 데이터 화면(Mock)
- 승인 뒤: SQL 저장소, T145 작업 계약으로 Worker 연결
