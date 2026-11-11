# T123 검증 보고서 — 기업 담당자 등록·초대·접근 API

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**
> - 실제 FastAPI 라우터·인증에 메모리 저장소와 Mock 메일을 붙여 검증했습니다.
> - DB 저장소, 실제 메일, Staging은 미실행입니다. 기능 플래그는 기본 꺼짐입니다.
> **스택**: main `ab56765` → T121 #210 → T122 #213 → 이 PR

## 1. 목적
기업 등록·멤버 초대·역할 회수 API를 만듭니다. 만료·중복·권한 상승·다른 기업 접근 차단을 시험합니다.

## 2. 선행 일감
- T15 인증·T93 메일 어댑터: main
- T121·T122: **#210·#213 미병합(스택)**
- `mask_email`(T96), `canonical_email`(T15), `MemoryMailSender`(T93)를 재사용합니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/services/company_policy.py` (신규) | T121 매트릭스 사본, `org_decision`(허용·403·404) |
| `backend/app/services/company_accounts.py` (신규) | 서비스와 메모리 저장소 |
| `backend/app/schemas/company_accounts.py` (신규) | DTO(T122 제안과 같은 모양) |
| `backend/app/routers/company_accounts.py` (신규) | 엔드포인트 12개. 기본 의존성은 503 |
| `backend/app/core/config.py`, `backend/app/main.py` | `company_accounts_api` 플래그(기본 꺼짐), 조건부 등록 |
| `backend/tests/test_t123_company_accounts.py` (신규) | 21건 |
| `docs/enterprise/T123_COMPANY_INVITATION_API.md` (신규) | API·보안 규칙·HOLD |

## 4. 시험 결과 (로컬 Windows 11 · Python 3.12, **메모리 저장소이며 DB 저장소 PASS 아님**)

| 범주 | 시험 | 결과 |
|---|---|---|
| 정책 | 코드 사본 = T121 매트릭스(행동 11개 × 역할 4개, 조직 상태 규칙) | PASS |
| 플래그 | 기본 꺼짐(경로 없음), 켜도 저장소 없으면 503, 비로그인 401 | PASS |
| **정상 흐름** | 등록 → 운영 승인 → 초대 → 수락 → owner 승격 → 제외 → **다음 요청 404(즉시 회수)**, 감사 6건(이메일 없음) | PASS |
| 토큰 | 응답·목록에 토큰·이메일 원문 없음, 저장은 64자 해시, 링크는 fragment | PASS |
| **만료·취소·다른 이메일** | 모두 같은 404 본문, 만료 처리 뒤 새 초대 가능, 임의 토큰 404 | PASS |
| 재전송 | 5회까지, 6번째 409, 재전송 전 토큰 무효, 최신 토큰 수락 | PASS |
| 중복 | 같은 이메일(대소문자 무관) 409, 이미 멤버 409, 토큰 재사용 404 | PASS |
| TTL | 8일 거부 | PASS |
| **권한 상승** | 담당자의 초대·자기 owner 승격·owner 제외·초대 목록은 403, 본인 탈퇴는 204 | PASS |
| **다른 기업 접근** | 경쟁 기업 owner·외부인·운영 관리자 × 6개 경로 = 모두 404, 없는 조직 404 | PASS |
| **마지막 owner** | 제외·강등 409. 두 owner 동시 상호 강등에도 owner ≥ 1 | PASS |
| 동시 수정 | 오래된 version 409 | PASS |
| 조직 상태 | pending은 열람 가능·초대 403 | PASS |
| 운영 검증 | 관리자 아님 403, 반려 사유 없음 422, version 409, 반려 뒤 재승인 409·조직 404, **자기 조직 검증 403** | PASS |
| 기타 | 수집 회사 중복 연결 409, 등록 검증 4종 422, 메일 불가 503(초대 행 안 생김) | PASS |

- `test_t123_company_accounts.py` **21 passed**. T121·T122 시험과 함께 46 passed / 10 skipped(skipped는 일회용 PG 미설정)
- 전체 Backend: **1197 passed / 275 skipped**. 실패·오류 32건은 기존 Windows 전용 시험으로 이번 변경과 무관하며, PASS로 세지 않았습니다.

## 5. 병합 주의
- `config.py`·`main.py`에 플래그 한 줄씩을 추가합니다. T126·T129(같은 방식)와 겹치므로 나중에 병합하는 쪽에서 모두 유지해야 합니다.
- T111(#207)이 먼저 병합되면 환경 계약 시험이 `COMPANY_ACCOUNTS_API`를 요구합니다. 그 경우 `env_contract.py`에 한 줄을 추가해야 합니다.

## 6. 미승인·후속
DB 저장소(정식 migration 후), 실제 메일 공급자, 조직 종료·정지 API, 소유자 없는 조직 처리
