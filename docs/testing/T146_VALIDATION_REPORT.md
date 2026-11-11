# T146 검증 보고서 — 다국어·날짜·접근성 표준

## 1. 작업 목적
한국어·영어 문구 표준과 날짜·숫자 표시 규칙을 정하고, 시간대·긴 문자열·키보드·화면 읽기 기본 규칙을 시험으로 고정합니다.

## 2. 기존 구현·PR 재사용
- 기존 T146 PR·브랜치 없음(신규).
- 재사용
  - T89 접근성 자동 규칙(`src/a11y/AccessibilityRegression.test.tsx`)
  - T92 여정 시험(`src/journeys/UserJourney.test.tsx`)
  - T117 브라우저 스크립트 방식(앱 안 이동, playwright-core 외부 경로)
- 이미 KST를 명시한 화면별 포맷 함수는 바꾸지 않았습니다.

## 3. BASE_SHA / HEAD_SHA
- BASE_SHA: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록(커밋 뒤 확정)

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `frontend/src/i18n/format.ts` | 날짜·시각(KST/UTC 명시), 날짜 전용 값, KST 하루 범위, 상대 시각, 숫자·백분율·바이트 |
| `frontend/src/i18n/messages.ts` | 공통 상태 문구 ko/en 대응표와 `t()` |
| `frontend/src/i18n/format.test.ts` | 25건 |
| `frontend/src/pages/MyDocumentsPage.tsx`, `PrivacySettingsPage.tsx` | 시간대 미지정 표시 4곳 → `formatDateTime` + `<time>` |
| `frontend/src/pages/MyDocumentsPage.test.tsx` | 시간대 회귀 2건 추가 |
| `frontend/e2e/t146-i18n-a11y.mjs` | Chrome 점검 스크립트(Mock 모드) |
| `docs/frontend/I18N_A11Y_STANDARD.md` | 표준·가이드 |
| `docs/testing/t146/chrome-result.json` | 브라우저 결과 |

공통 파일(`routes.tsx`, `config/env.ts`, `AppLayout.tsx`, `config.py`, `main.py`)은 **변경하지 않았습니다**. 의존성 변경도 없습니다.

## 5. 선행조건
| 일감 | 상태 |
|---|---|
| T20 공통 UI | main 병합 |
| T89 접근성 회귀 | main 병합(#191) |
| T92 여정 일관성 | main 병합(#194, #199) |

## 6. 실제 실행 명령
```bash
cd frontend
npm run lint
npx tsc -b --noEmit
npx vitest run
npm run build
npx vite --mode mock --port 5202 --strictPort   # 점검 뒤 종료
E2E_BASE_URL=http://127.0.0.1:5202 E2E_OUT=… PLAYWRIGHT_CORE=… CHROME_PATH=… node e2e/t146-i18n-a11y.mjs
```

## 7. 정상·오류·경계 검증
| 구분 | 내용 | 결과 |
|---|---|---|
| 시간대 | 사용자 PC 시간대 6곳(UTC, LA, 서울, UTC+14, UTC-11, 런던)에서 같은 KST 출력 | PASS |
| 시험의 유효성 | 시간대를 실제로 바꾸면 로컬 `getDate()`가 달라지는지 먼저 확인 | PASS |
| 날짜 경계 | 15:30Z → 다음 날 KST, 1월·7월 모두 +9(서머타임 없음) | PASS |
| 날짜 전용 값 | 2026-02-29 거부, 2028-02-29 허용, 시각 문자열 거부 | PASS |
| 잘못된 값 | null·빈 값·형식 오류·13월 → `—`. NaN·Infinity·음수 크기 → `—` | PASS |
| 영어 | 날짜·시각·숫자·백분율·상대 시각 | PASS |
| 문구표 | ko/en 키 일치, 빈 문구 없음, 자리표시자 일치, 건너뛰기 링크 문구가 실제 화면과 같음 | PASS |
| 회귀(변이) | 문서 화면을 이전 코드로 되돌리면 UTC-11 시험이 **실패**하는 것 확인 후 복원 | 확인함 |
| 권한 | 해당 없음(표시 규칙만 변경, API·권한 변경 없음) | — |

## 8. Mock / 실제 API / 브라우저 구분
| 항목 | 결과 |
|---|---|
| UNIT_TESTS (Vitest 전체) | **PASS** — 544 passed, 22 skipped(기존 skip, 새 skip 없음), 39 files |
| FRONTEND_TESTS (lint·tsc·build) | **PASS** |
| BROWSER_E2E (Chrome, Mock 모드) | **PASS 30/30** (아래) |
| MOCK_VALIDATION | PASS |
| REAL_API_VALIDATION | NOT_RUN(표시 규칙 변경이라 API 무관) |
| STAGING_VALIDATION | NOT_RUN |
| 화면 읽기 프로그램 수동 낭독 | NOT_RUN |

브라우저 점검(320px, 1280px, 브라우저 시간대 `America/Los_Angeles`, 언어 `en-US`)
- `html lang=ko`
- 첫 Tab에 건너뛰기 링크가 보이고, Enter로 `main`에 포커스가 옮겨짐
- 키보드만으로 로그인
- 8개 화면 가로 넘침 없음
- 긴 파일명(한글 140자+영문 104자, 공백 없음) 카드가 줄바꿈되어 넘침 없음
- 개인정보·문서·추천 화면의 `<time>`이 한국 날짜. 각 단계에서 1건 이상을 실제로 확인했고, 0건이면 FAIL 처리합니다.
- 200% 확대에 해당하는 절반 폭

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
- 영어 화면 제공·언어 전환 방식은 PM 결정 전입니다(대응표만 있음).
- 수동 화면 읽기(NVDA·VoiceOver)는 NOT_RUN입니다.

## 11. 후속 작업
- 화면별 KST 포맷 함수(알림·추천·지원 보드·기업 콘솔 등)를 `i18n/format`으로 옮깁니다(동작 동일, 별도 PR).
- 새 화면부터 `t()` 공통 문구를 사용합니다.
