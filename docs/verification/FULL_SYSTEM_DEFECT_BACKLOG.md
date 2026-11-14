# 전체 시스템 E2E 결함 목록 (2026-11-14)

등급: P0 무단 공개·데이터 손상·권한 우회·핵심 흐름 막힘 / P1 주요 API 오류·상태 불일치·FE/BE 계약 불일치·실제 기능 미연결 / P2 / P3.
근거는 `docs/verification/FULL_SYSTEM_E2E_REPORT.md` 와 CI artifact `full-system-e2e`(run 43604942164).

**P0: 없음.** 무단 공개·권한 우회·데이터 손상은 발견되지 않았다(비공개 공고 노출 0, 비관리자 결정 403, SQL 정합성 검사 전부 PASS).

| ID | 등급 | 기능 | 재현 | 기대 | 실제 | 원인 | 수정 | 담당 PR |
|---|---|---|---|---|---|---|---|---|
| FSE-001 | P1 | USER/PORTFOLIO (가입) | `consent_policies` 에 `public_profile` 행(T129 공개 포트폴리오에 필요)을 넣고 `GET /api/v1/consent-policies` | 200, 가입 약관 목록 | **500** (pydantic literal_error) → 회원가입 화면이 약관을 못 불러옴 | `ConsentPolicy.policy_code` 가 가입 약관 4종 Literal 인데 서비스가 표의 모든 현행 약관을 그대로 반환 | **수정됨** `37d690e`: 가입 약관 코드만 반환 + `tests/test_auth.py::test_consent_policies_skip_feature_policies_instead_of_500` | #361(이 PR). 기능 약관을 넣는 #352(T129) 병합 전에 같이 반영 필요 |
| FSE-002 | P1 | USER | /account 에서 이름·한 줄 소개·지역 수정 시도 | 수정 화면 | 화면 없음. `PATCH /me` 는 동작(API PASS) | 프론트 미구현(실제 기능 미연결) | 미수정(화면 설계 필요) | 프로필 UI(T16 계열) 후속 |
| FSE-003 | P2 | USER | /me/career-history 경력 수정 | 수정 버튼 | 추가·삭제만 있음. `PATCH /me/experiences/{id}` 는 동작 | 프론트 미구현 | 미수정 | 경력 UI 후속 |
| FSE-004 | P2 | USER (지원 현황) | 실제 API 모드로 /me/applications | Mock 안내 없음 | "가상 데이터(Mock)입니다. 서버 연동은 아직 없습니다." 항상 표시(오해 유발) | 다른 화면과 달리 `env.mockEnabled` 조건 없음 | **수정됨** `f506fa8` + E2E 회귀(안내가 보이면 FAIL) | #361(이 PR), 원 기능 #350(T101–T103) |
| FSE-005 | P2 | MODERATION (감사) | 실제 API 빌드에서 /admin/audit-events | 감사 화면 | 경로 없음(`adminAuditUi` 는 Mock 전용). API `GET /admin/audit-events` 는 동작(검수 열람 기록 확인) | T84 정책 D1–D5 미승인으로 의도된 제한 | 미수정(PM 결정 대기) | T85 / PM |
| FSE-006 | P2 | COMPANY | 기업 등록 후 조직 '운영 확인 대기' | 관리자 승인 화면 | 화면 없음, `POST /admin/organizations/{id}/verification` API 로만 가능 → 운영 도구 없으면 조직이 공고를 못 올림 | 운영 콘솔 미구현 | 미수정 | T123/T124 후속 |
| FSE-007 | P3 | COMPANY | '운영 확인 대기' 조직 선택 | 초대 목록 호출 안 함 또는 안내 | `GET /organizations/{id}/invitations` 403 (화면은 정상) | 화면이 상태와 관계없이 조회 | 미수정 | T124 |
| FSE-008 | P3 | 공통 | Google 로그인 꺼진 상태로 아무 화면 | 불필요한 호출 없음 | 페이지 로드마다 `GET /api/v1/auth/gate` 404 (console 오류로 남음) | 게이트 확인을 플래그와 무관하게 호출 | 미수정 | #328 계열 |

참고(결함 아님): 로컬 Windows 에서 문서 업로드 503 — 저장 폴더 권한(0o700) 검사가 Windows 에서 성립하지 않음. Linux CI 에서는 PASS.

## 내일 우선순위

1. FSE-001 수정(이 PR 의 `37d690e`)을 #352(T129) 또는 main 에 먼저 반영 — `public_profile` 약관을 넣는 순간 가입이 깨짐.
2. FSE-002 프로필 수정 화면 범위 결정(PM) — API 는 준비됨.
3. FSE-006 조직 승인 운영 화면(또는 운영 절차 문서) — 없으면 기업 흐름이 실제 운영에서 멈춤.
4. FSE-004(수정 완료) 를 #350 에도 반영.
5. FSE-005 감사 화면 실제 모드 허용 여부(PM, T84 D1–D5).
6. FSE-003, FSE-007, FSE-008 정리.

## PM 결정 필요(BLOCKED 성격)

- 감사 기록 화면을 실제 API 모드에서 열지(FSE-005).
- 기업 초대 메일 공급자 — 연결 전에는 초대 시나리오를 E2E 로 검증할 수 없음.
- 알림 생성 흐름(다른 행위자 → 사용자) 범위 — 현재 스택에는 알림을 만드는 흐름이 없어 수신 경로 미검증.
