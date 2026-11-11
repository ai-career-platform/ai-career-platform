# T125 검증 보고서 — 기업 공고 게시·검수·수정 정책

> 2026-11-11 · 담당 문길래 · 실행 SORNET(Claude Code)
> **DELIVERY_STATUS=PARTIAL / INTEGRATION_STATUS=HOLD**: 정책은 PROPOSED(PM·법무 승인 전)이고, 구현과 DB 변경은 없습니다.
> **스택**: main `ab56765` → T121 #210 → 이 PR

## 1. 목적
기업 자체 공고 등록과 운영 검수 정책을 정합니다. 초안·승인대기·반려·게시·만료 상태 전이와 출처 표준을 다룹니다.

## 2. 선행 일감
- T18 공고 API, T80 검수 정책(DRAFT): main
- T121: **#210 미병합(스택)**
- T80 상태 모델(PENDING·APPROVED·REJECTED)과 `not self` 규칙을 재사용합니다.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `docs/enterprise/T125_COMPANY_POSTING_POLICY.md` (신규) | 현재 사실, 원칙(초안·공개 분리, 우회 금지, 출처 `company_direct`), 상태 7개, 전이 8개, 수정본 흐름, 반려·내림 사유 코드, 불변 조건 8개, 결정 D-1~D-6 |
| `docs/enterprise/t125_posting_state_machine.json` (신규) | 상태 기계 원본(T126 구현이 읽음) |
| `backend/tests/test_t125_posting_state_machine.py` (신규) | 20건 |

## 4. 시험 결과 (로컬)

| 시험 | 결과 |
|---|---|
| 형식(상태·수행자, 중복 전이 없음), 모든 상태 도달 가능 | PASS |
| P-INV-1: 기업 역할의 published 전이 없음 | PASS |
| P-INV-2: 게시·반려는 운영 관리자만, `not_member_of_org` 조건 | PASS |
| P-INV-3: 공개 표 변경은 `posting.publish`만, 공개 상태는 published뿐 | PASS |
| P-INV-4: 반려·내림에 사유 필수 | PASS |
| P-INV-5: 종료 상태 3개에 나가는 전이 없음 | PASS |
| P-INV-6: 운영 관리자는 작성·수정·검수 요청 불가 | PASS |
| P-INV-7: 사람이 하는 전이는 version 확인(내림 제외) | PASS |
| P-INV-8: 검수 요청·게시는 active 조직만 | PASS |
| 지름길 7종 금지(draft→published, rejected→pending_review, 종료→published 등) | PASS |
| **전이 수행자 = T121 매트릭스 허용 역할**(양방향) | PASS |
| 사유 코드·한도·불변 조건·출처가 문서에 있음 | PASS |

**20 passed.**

## 5. 미승인·후속
- PM 결정 D-1~D-6. **D-4(차별 요건 기준)는 법무 검토가 필요합니다.**
- 게시 약관(`license_ref`) 작성이 필요합니다.
- T126에서 이 상태 기계를 구현합니다(기능 플래그 뒤).
