# T122 검증 보고서 — 기업 계정·소속·승인 상태 데이터 계약

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**: 제안 DDL·DTO이며 정식 migration은 없습니다. 공유 DB에는 적용하지 않았습니다.
> **스택**: main `ab56765` → T121 #210 → 이 PR
> **후속(2026-11-14)**: 제안 DDL은 `database/migrations/0008_organizations.sql` 로 승격되었습니다(열·키 이름 그대로). 아래 경로는 당시 기준입니다.

## 1. 목적
기업 조직·멤버 초대·승인·탈퇴 데이터 계약을 만듭니다. 소속 관계, 초대 TTL, 다중 소속, 삭제·감사 정책을 다룹니다.

## 2. 선행 일감
- T05 데이터 사전: 병합
- T121 역할 정책: **#210 미병합(스택)**
- `career.companies`(수집 회사)와 `career.audit_events`를 재사용합니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `database/proposed/T122_organizations.sql` (신규) | `organizations`·`organization_members`·`organization_invitations`, 제약·부분 유일 인덱스 |
| `docs/enterprise/T122_COMPANY_MEMBERSHIP_CONTRACT.md` (신규) | ERD, 상태 전이, 초대 규칙, 삭제·감사·보존, 결정 D-1~D-5 |
| `docs/enterprise/t122_openapi_proposal.yaml` (신규) | API·DTO 제안(엔드포인트 12개) |
| `backend/tests/test_t122_company_membership_contract.py` (신규) | 문서·DTO 4건 + 일회용 PG 10건 |

## 4. 시험 결과 (로컬 Windows 11 · PostgreSQL 18.6 일회용, 루프백 · migration 0001~0003 + 제안 DDL)

| 시험 | 결과 |
|---|---|
| DDL이 PROPOSED이고 migrations 폴더에 없음 | PASS |
| DTO enum = DDL = T121 역할·조직 상태 규칙 | PASS |
| DTO에 `token_hash`·이메일 원문 없음(마스킹만) | PASS |
| 문서에 TTL·다중 소속·CASCADE·감사·마지막 owner·30일 | PASS |
| 조직 상태 값, active면 검증 시각 필수, closed면 종료 시각 필수, 빈 이름 거부 | PASS |
| 역할 값, 같은 조직 중복 소속 거부, **다른 조직 다중 소속 허용** | PASS |
| **초대 TTL 7일 정확히 허용 / 7일+1초·0초 거부** | PASS |
| 조직·이메일당 대기 초대 1개, 다른 조직 별개, 종료 후 새 초대 허용 | PASS |
| 토큰 해시 유일, 해시 형식(원문 거부), 이메일 소문자·@ 필수 | PASS |
| 종료 상태에는 `closed_at` 필수, 재전송 6회 거부 | PASS |
| **사용자 삭제 → 소속 CASCADE, 행위자 참조 SET NULL, 조직 유지** | PASS |
| 조직 삭제 → 멤버·초대 CASCADE | PASS |
| 수집 회사 연결: 열린 조직 1개만, 반려 후 재연결 허용, 회사 삭제 시 SET NULL | PASS |
| 전역 역할(`admin`, `job_seeker`) 변화 없음 | PASS |

**14 passed.** CI에서는 Postgres 서비스(18.1)에서 같은 시험이 실행됩니다.

## 5. 한계·후속
- "마지막 owner" 규칙과 "소유자 없는 조직" 처리는 DB 제약이 아니라 서비스 규칙입니다. T123에서 시험합니다.
- 종료 초대 30일 purge 작업은 제안만 했습니다.
- PM 결정 대상은 D-1~D-5입니다.
