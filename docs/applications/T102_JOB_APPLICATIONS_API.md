# T102 — 개인 채용 지원 기록 API

> 상태: **PARTIAL** — API·시험 완료. 운영 활성화는 **HOLD**(T101 계약·표 미승인, 기능 플래그 `JOB_APPLICATIONS_API` 기본 꺼짐).
> 이 브랜치는 T101(#204) 위에 쌓여 있습니다(T101 먼저 병합). main `ceee31d` · 2026-11-11 · F-012·F-013 · 제안 FR-JOB-008
> 선행: T15·T18·T39 병합, T101 미병합

## 1. 구성

| 파일 | 역할 |
|---|---|
| `backend/app/schemas/job_applications.py` | DTO(T101 제안 OpenAPI). 요청은 모르는 필드 거부, memo 2000자 |
| `backend/app/services/job_applications.py` | 단계 이동 표(T101 §4), 지원일 규칙(KST), 날짜 범위, 사용자당 500건, version 낙관적 잠금, 공고 표시 상태(게시 중·마감·없음) |
| `backend/app/repositories/job_applications.py` | 모든 쿼리를 `user_id`로 묶음, 바인딩 변수만, 사용자별 advisory lock(상한·중복 직렬화), `version` 조건부 UPDATE |
| `backend/app/routers/job_applications.py` | `/api/v1/me/job-applications` GET·POST, `/{id}` GET·PATCH·DELETE |
| `backend/app/main.py`, `app/core/config.py` | `JOB_APPLICATIONS_API=true`일 때만 등록. **기본 꺼짐 = 경로 없음(404)** |
| 시험 | `tests/test_t102_job_applications.py`(단위 61), `tests/test_t102_job_applications_postgres.py`(PG 8) |

표는 `database/proposed/T101_job_applications.sql`(제안)을 그대로 씁니다. 정식 migration을 만들거나 적용하지 않았습니다.

## 2. 계약과 다른 점 (의도)

| 항목 | T101 제안 | T102 구현 | 이유 |
|---|---|---|---|
| 409 오류 코드 | `APPLICATION_EXISTS`·`APPLICATION_LIMIT`·`INVALID_STAGE_TRANSITION`·`VERSION_CONFLICT` | 모두 기존 **`CONFLICT`**, 원인은 서버 로그(`log_detail`)에만 | 오류 코드 표는 확정 계약(`docs/API_CONTRACT.md` §1.4)과 시험으로 묶여 있음. D-7 승인 후 전용 코드로 교체 |

## 3. 시험 결과 (로컬: Windows 11 · Python 3.12 · PostgreSQL 18.6 일회용 클러스터)

| 범주 | 시험 | 결과 |
|---|---|---|
| 계약 일치 | 이동 표·단계·지원일 규칙 = T101 문서 표·계약 시험의 참조 기계 | PASS |
| 상태 이동 | **49쌍 전부**: 허용이면 version+1, 금지면 409이고 기록 그대로 | PASS |
| 날짜 | 지원 이후 단계에서 지원일이 없으면 KST 오늘로 채움, 준비 단계로 돌아가면 지움, 미래·2000년 이전 지원일 422, 다음 일정 2년 초과 422, 지원 전 지원일 422 | PASS |
| 수정 의미 | 보내지 않은 필드 유지, null은 지움, 빈 수정 422, stage null 422 | PASS |
| 소유권(PG) | B가 A의 기록 GET·PATCH·DELETE → 404, 목록에 안 보임, A의 기록 변화 없음, 같은 공고를 B는 따로 기록 가능 | PASS |
| 인증(PG) | 비로그인 401 | PASS |
| 중복·없는 공고(PG) | 같은 공고 409, 없는 공고·draft 404, 잘못된 단계·메모 2001자·모르는 필드·미래 지원일 422(기록 생성 안 됨) | PASS |
| 동시 수정(PG) | 오래된 version 409, 금지 이동 409, DB 값 변화 없음 | PASS |
| 목록(PG) | 12건을 5개씩 → 중복·누락 없음, 단계 필터(중복 값 무시), 조건이 다른 cursor 400 | PASS |
| 공고 상태(PG) | 마감 → `closed`, 공고 삭제 → `unavailable` + 제목·기업명 스냅샷 유지 | PASS |
| 상한(PG) | 500건이면 409, 다른 사용자는 영향 없음 | PASS |
| 삭제·보존(PG) | 삭제 즉시 행 없음, 사용자 삭제 → CASCADE, memo가 로그에 없음 | PASS |
| 플래그 | 기본 꺼짐 → 경로 없음 | PASS |

실행:

```powershell
cd backend
$env:T16_ISOLATED_DB_TEST="YES"; $env:T16_TEST_ADMIN_URL="postgresql://<admin>@127.0.0.1:<port>/t16_profile_test"
python -m pytest -q tests/test_t102_job_applications.py tests/test_t102_job_applications_postgres.py
```

## 4. HOLD / 후속

| 항목 | 필요한 것 |
|---|---|
| 운영·Staging 활성화 | T101 승인 → 정식 migration 번호·적용 승인 → 플래그 켬 |
| `docs/api/openapi.yaml`·FR-JOB-008·UI-N05 등록 | T101 승인 후 |
| 전용 409 코드 | T101 D-7 승인 후 `API_CONTRACT.md` §1.4 와 함께 |
| T87 개인정보 분류 | migration 승인 시 `RETENTION_MAP`에 `job_applications.user_id: DELETE` |
| T86 보안 인벤토리·IDOR 범위 | 플래그를 기본으로 켤 때 경로 5개를 보호 경로·IDOR 시험에 추가 |
| 병합 충돌 | T99(#202)도 `config.py`·`main.py`에 플래그를 더함 — 나중에 병합되는 쪽에서 두 줄을 함께 유지 |
