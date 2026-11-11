# T126 검증 보고서 — 기업 공고 작성·게시 요청 API

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 실제 FastAPI 라우터·인증과 메모리 저장소, 공개 표 대역으로 검증했습니다.
> - 정식 migration·운영 라우팅은 승인 전 HOLD입니다(플래그 기본 꺼짐, 켜도 503).
> **스택**: main `ab56765` → T121 #210 → T122 #213 → T123 #218, 그리고 **T125 #214를 병합 커밋으로 합침** → 이 PR

## 1. 목적
기업 공고 초안 CRUD와 게시 검수 요청을 만듭니다. 소유 기업 확인, 검수 요청, 동시 수정 충돌을 시험합니다.

## 2. 선행 일감
- T18 공고 API, T81 검수 계약: main
- T123(#218): 조직·소속 서비스를 재사용합니다.
- T125(#214): 상태 기계를 코드가 그대로 따르는지 시험합니다.
- 두 브랜치를 함께 쓰기 위해 T123 브랜치에 T125 브랜치를 **병합 커밋**으로 합쳤습니다. 커밋을 복사하지 않았습니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/company_postings.py` (신규) | 상태 기계(T125 전이 8개), 초안·수정·수정본·검수 요청·철회·마감, 운영 승인·반려·내림, 만료, 공개 표 대역(`company_direct`) |
| `backend/app/routers/company_postings.py` (신규) | 기업 7개 + 운영 3개 엔드포인트. 기본 의존성 503 |
| `backend/app/services/company_policy.py` | 공고 행동 6개(T121 매트릭스 값 그대로), pending·suspended 허용 목록 |
| `backend/app/core/config.py`, `backend/app/main.py` | `company_postings_api`(기본 꺼짐) |
| `backend/tests/test_t126_company_postings.py` (신규) | 21건 |

기존 공개 공고 API(T18·T99)와 `job_postings` 표는 변경하지 않았습니다.

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12, **메모리 저장소이며 DB 저장소 PASS 아님**)

| 범주 | 시험 | 결과 |
|---|---|---|
| 계약 일치 | 전이 표·반려·내림 사유·60일 = T125 JSON. 정책 사본 = T121 매트릭스(T123 시험) | PASS |
| 플래그 | 기본 꺼짐, 저장소 없으면 503 | PASS |
| **정상** | 초안 → 검수 요청 → 운영 승인 시 공개 표 1건(`company_direct`) → 마감 시 공개 표에서 사라짐. 초안·검수 중에는 공개 0건 | PASS |
| 반려 | 사유 없음·`other`에 설명 없음 422, 사유 표시, 수정하면 draft·사유 지움, 재요청 | PASS |
| 철회 | 검수 중 → draft | PASS |
| **무단 게시 차단** | owner·담당자의 승인·검수 목록·내림 = 403, 공개 0건 | PASS |
| 지름길 | 초안에서 바로 마감·철회 409, 검수 중·게시 중 직접 수정 409 | PASS |
| **자기 검수 금지** | 그 조직 멤버인 운영 관리자의 승인 403 | PASS |
| 운영 관리자 작성 금지 | 초안 작성·수정 404(소속 아님) | PASS |
| **타 기업 수정 차단** | 목록·조회·수정·검수 요청 404, 자기 조직 경로에 남의 공고 ID 404 | PASS |
| 권한 회수 | 제외된 멤버 즉시 404 | PASS |
| 조직 상태 | 검증 전 조직은 초안 가능, 검수 요청 403 | PASS |
| **동시 수정** | 오래된 version 409, 같은 version으로 5개 동시 수정 → 성공 1·충돌 4 | PASS |
| 검증 | 필수 항목 없으면 검수 요청 422, http 지원 링크 422, 만료 61일 승인 422 | PASS |
| 만료·내림 | 만료 시각 경과 → expired·공개 마감, 내림 사유 코드 검증, 종료 상태 전이 409 | PASS |
| **수정본** | 게시 중 수정은 수정본으로, 수정본 중복 409, **승인 전 공개 내용 그대로**, 승인 후 같은 공개 행 갱신 | PASS |
| 감사 | 행동 3건 기록, 본문 내용 미포함 | PASS |

- `test_t126_company_postings.py` **21 passed**
- 전체 Backend: **1238 passed / 275 skipped**. 실패·오류 32건은 기존 Windows 전용 시험이며 PASS로 세지 않았습니다.

## 5. 병합 주의
- 스택이 깊어 병합 순서는 #210 → #213·#214 → #218 → 이 PR입니다.
- `config.py`·`main.py`는 T129(#219)와 겹칩니다.
- T111(#207)이 먼저 병합되면 `env_contract.py`에 `COMPANY_POSTINGS_API`를 추가해야 합니다.

## 6. 미승인·후속
1. T125 승인 → 기업 공고 표·검수 표 migration → DB 저장소. 공개 반영은 `job_postings` + `data_sources(company_direct)`
2. 검수 처리 기한·이의 제기(T80 연계)
3. 게시 약관
