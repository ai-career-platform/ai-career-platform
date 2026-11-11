# T94 — 계정 복구·이메일 확인 UI 검증

> 판정: **FRONTEND_MOCK=PASS / REAL_API_INTEGRATION=HOLD**
> - 확정 계약(`requestPasswordReset`·`resetPassword`) 기준으로 화면을 만들고 Mock Adapter로 검증했습니다.
> - Backend(T93 PR #195)가 미병합이라 실제 API는 연결하지 않았습니다.
> - 이메일 인증 화면은 계약이 없어 **HOLD**입니다(T93 §6 설계만).
> 확인일 2026-11-11 · 기준 main `1f3cecd` · 경로 `/password-reset` (UI-N03)

## 1. 화면

| 단계 | 제목 | 내용 |
|---|---|---|
| 복구 요청 | 비밀번호 재설정 | 이메일 입력 → "재설정 링크 받기". 형식 오류는 요청하지 않고 `role=alert` |
| 발송 안내·확인 대기 | 메일을 확인해 주세요 | **가입 여부와 관계없이 같은 문구**("가입된 계정이 있으면 … 30분"), 스팸함 안내, "다시 요청" |
| 새 비밀번호 | 새 비밀번호 설정 | 새 비밀번호·확인(10~128자, 일치 확인), "바꾸면 모든 기기에서 로그아웃" 안내 |
| 성공 | 비밀번호를 바꿨습니다 | 모든 기기 로그아웃 안내, 로그인 링크 |
| 만료·잘못된 링크 | 링크를 사용할 수 없습니다 | 만료(30분)·사용됨·잘못됨을 **구분하지 않는 한 문구**, "새 링크 요청" |
| 요청 제한 | (알림) | 429 → "요청이 너무 많습니다…" |
| 공급자 없음 | (알림) | 503 → "지금은 메일을 보낼 수 없습니다…" |
| 이미 로그인 | 이미 로그인되어 있습니다 | 양식 대신 안내와 "내 계정으로 이동" |
| 일반 빌드 | 비밀번호 재설정 준비 중 | Mock 모드가 아니면(T93 미병합) 기능 미제공 안내 — 가짜 성공 없음 |

단계가 바뀌면 제목에 포커스를 옮겨 스크린리더가 새 단계를 읽습니다. 로그인 화면의 "비밀번호를 잊으셨나요?" 링크(기존 404)가 이제 이 화면으로 이어집니다.

## 2. 보안

| 요구 | 처리 | 시험 |
|---|---|---|
| 계정 존재 여부 비노출 | 성공 문구 하나, 오류 문구에도 "가입되지 않음" 같은 표현 없음 | 있는·없는 계정 문구 동일, 오류 매핑 4종 |
| 토큰이 주소·기록에 남지 않음 | 화면을 열면 **즉시 `?token=`을 주소에서 지움**(`replace`), 토큰은 메모리에만 | 로드 후 `location.search === ''`, 페이지 HTML·제목에 토큰 없음 |
| 콘솔·분석에 남기지 않음 | 로그 출력 코드 없음, 분석 이벤트 없음 | 모든 시험에서 console.* 감시 → 토큰·비밀번호 문자열이 나오면 실패 |
| 비밀번호 | 화면 상태에만, 성공 후 비움. `autoComplete="new-password"` | — |
| 인증 헤더 미전송 | HTTP Adapter는 `token: null`(공개 경로) | 가짜 fetch에서 `Authorization` 없음 |
| 네트워크 | 화면 시험에서 실제 요청 0 | 모든 시험 공통 가드 |

## 3. 구조

| 파일 | 내용 |
|---|---|
| `frontend/src/api/accountRecovery.ts` | 서비스 인터페이스(생성 타입 `PasswordResetRequest`·`PasswordReset`), HTTP Adapter(준비만), 오류 → 고정 문구 |
| `frontend/src/mocks/accountRecovery.ts` | Mock: 같은 성공, 30분·1회 토큰, 사용 시 남은 토큰 무효, 같은 400, 이메일별 한도 429, 503 모드 |
| `frontend/src/pages/PasswordResetPage.tsx` | 화면. Mock 모드에서만 Mock 서비스, 그 외 `null` → 준비 중 안내 |
| `frontend/src/routes.tsx` | `/password-reset` 공개 경로 1줄 |
| `frontend/src/pages/LoginPage.tsx` | 주석만 갱신 |

Mock 모드 개발 편의로, 발송 안내 화면에 "가상 메일함(Mock 모드 전용): 재설정 링크 열기"를 보여 줍니다. 합성 토큰이며 일반 빌드에는 나오지 않습니다.

## 4. 시험 결과 (로컬) — `frontend/src/pages/PasswordResetPage.test.tsx` 13건

| 시험 | 결과 |
|---|---|
| 있는·없는 계정에 같은 안내 | PASS |
| 이메일 형식 오류는 요청 전에 막음 | PASS |
| 503·429 고정 문구 | PASS |
| 토큰을 주소에서 즉시 제거, 페이지·제목에 없음 | PASS |
| 새 비밀번호 길이·일치 확인(요청 전) → 성공 화면(제목 포커스)·로그인 링크 | PASS |
| 만료·재사용·위조 링크 → 같은 "사용할 수 없음" → 새 링크 요청 | PASS (3) |
| 이미 로그인한 사용자 안내 | PASS |
| 일반 빌드(서비스 없음) 준비 중 안내, 버튼 없음 | PASS |
| 입력 label·오류 `role=alert` | PASS |
| HTTP Adapter: 경로·본문 키가 계약과 같음, Authorization 없음 | PASS (가짜 fetch) |
| 오류 문구가 계정 존재를 드러내지 않음 | PASS |

| 검사 | 결과 |
|---|---|
| typecheck · lint · build | PASS |
| Vitest 전체 | 363 passed, 22 skipped |
| 실제 API·메일 | **NOT_RUN** (T93 미병합, 공급자 없음) |

## 5. HOLD·연결 순서

1. T93 #195 병합, 메일 공급자 승인
2. `PasswordResetPage`의 기본 서비스를 `createHttpAccountRecoveryService(useApi의 HttpClient)`로 교체(일반 빌드)
3. 격리 환경 실제 흐름 시험(메일 링크 → 재설정 → 로그인)
4. 이메일 인증 화면: 계약(T06)·컬럼(T05) 승인 후

T92 PR #194의 내비게이션 게이트는 `/password-reset`을 "알려진 끊긴 링크"로 고정합니다. 이 PR이 먼저 병합되면 T92 쪽 목록에서 이 항목을 지워야 합니다(반대 순서면 이 PR에서 정리).

Backend·Staging·배포 설정 변경 0건, 실제 메일 발송 0건입니다.
