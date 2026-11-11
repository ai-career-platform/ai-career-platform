# T89 — 웹 접근성·크로스브라우저 회귀 검사

> 판정: **PARTIAL** — 자동 회귀 시험(CI)과 실제 Chrome·Edge 점검을 통과했습니다. 이번 점검 범위에서는 고칠 UI 결함이 발견되지 않아 UI 코드는 바꾸지 않았습니다.
> 스크린리더 실제 낭독(NVDA·내레이터)과 Firefox·Safari는 **NOT_RUN**입니다. 자동 점검은 스크린리더 사용성 전체를 보장하지 않습니다.
> 확인일 2026-11-11 · 기준 main `1f3cecd` · 브랜치 `task/t89-accessibility-regression`

## 1. 선행 작업

| 일감 | 상태 | 화면 |
|---|---|---|
| T20 공통 UI | 병합 #43 | 레이아웃·버튼·표·상태 패널 |
| T21 로그인 | 병합 | `/login` |
| T24 공고 탐색 | 병합 | `/job-postings` |
| T44 Skill Gap UI | **미병합 #149** | 점검 대상 아님 |
| T57 | main에 화면 없음 | 점검 대상 아님 |
| T82 검수 UI (Mock) | 병합 #182 | `/admin/moderation` (플래그) |
| T85 감사·AI 비용 (Mock) | 병합 #187 | `/admin/audit-events`, `/admin/ai-usage` (플래그) |

## 2. 자동 회귀 시험 (CI 실행) — `frontend/src/a11y/AccessibilityRegression.test.tsx`

실제 라우터(`buildRoutes`)와 Mock HTTP 로그인으로 화면을 열고, 로딩이 끝난 뒤 공통 규칙을 점검합니다.

| 규칙 | 의미 |
|---|---|
| 모든 입력·선택·여러 줄 입력에 접근 가능한 이름(label·aria-label·aria-labelledby) | Label 연결 |
| 모든 버튼·링크에 이름 | 스크린리더 안내 |
| 모든 이미지에 `alt` | 대체 텍스트 |
| `role=button`이 아닌 요소는 포커스 가능해야 함, 클릭 가능한 `div`/`span` 금지 | Enter·Space 조작 |
| 양수 `tabindex` 금지 | Tab 순서 보존 |
| 중복 `id` 금지 | label·aria 연결 안전 |
| `main` 안 `h1` 정확히 1개 | 화면 제목 |
| 건너뛰기 링크가 `#main-content`를 가리킴 | 반복 메뉴 건너뛰기 |

| 화면 (19) | 결과 |
|---|---|
| 공개: `/`, `/login`, `/job-roles`, `/job-postings`, `/system-status`, 404 | PASS |
| 구직자: 계정, 개인정보 설정, 목표 직무, 경력, 북마크, 기술, 문서, 추천, 시장 추세, **관리자 경로 403 화면** | PASS |
| 관리자(Mock 플래그): 검수 큐, 감사 기록, AI 사용량 | PASS |
| 403 화면은 색이 아니라 `h1` 제목으로 안내 | PASS |

추가 시험:

| 시험 | 결과 |
|---|---|
| 키보드만으로 로그인 제출, 실패 오류가 `role=alert`로 안내되고 비밀번호를 되돌려주지 않음 | PASS |
| 모달: 열면 첫 컨트롤에 포커스, Tab·Shift+Tab 순환(포커스 가둠), Esc 닫기, 닫으면 여는 버튼으로 포커스 복귀, `aria-modal` | PASS |
| 색 대비(디자인 토큰, WCAG 2.x 일반 텍스트 4.5:1): 본문·보조 글자 × 배경·표면, 주요·위험·경고·성공 색, 주요 버튼 흰 글자 | PASS (10쌍) |
| 대비 계산 함수가 WCAG 기준값과 일치(21:1, #767676 4.54:1) | PASS |
| **자기 검증**: 점검 함수가 위반 9종(이름 없는 입력·버튼·링크, alt 없음, 가짜 버튼, 양수 tabindex, 중복 id, h1 개수, 건너뛰기 링크)을 실제로 잡아냄 | PASS |

합계 35건 PASS.

## 3. 실제 브라우저 점검 (로컬 수동 실행) — `frontend/scripts/a11y-browser-check.mjs`

- 환경: Mock 모드 개발 서버, 합성 계정, headless.
- 브라우저: **Chrome 156.0.8078.74**, **Edge 157.0.4341.42**.
- 화면 크기 3종: 데스크톱 1280, 모바일 375, **200% 확대**(1280 → CSS 폭 640, 배율 2).
- 화면 7개: `/`, `/login`, `/job-postings`, `/job-roles`, `/me/skills`, `/recommendations`, `/account/privacy`.

| 점검 | Chrome (3 크기 × 7 화면) | Edge (3 × 7) |
|---|---|---|
| 가로 넘침 없음 (작은 화면에서 표는 자체 스크롤) | PASS | PASS |
| 첫 Tab = 건너뛰기 링크, 화면에 보임 | PASS | PASS |
| 건너뛰기 링크 Enter → 본문(`main`)으로 포커스 이동 | PASS | PASS |
| 다음 Tab의 포커스 표시(outline·box-shadow) 보임 | PASS | PASS |
| 키보드만으로 로그인(Tab 이동, 입력, Enter 제출) | PASS | PASS |
| 페이지 스크립트 오류 | 0 | 0 |

원자료: `docs/testing/T89_BROWSER_RESULTS.json`

첫 실행에서는 "첫 Tab = 건너뛰기 링크"가 모든 화면에서 실패했습니다. 원인은 점검 스크립트가 먼저 화면을 클릭해 Tab 시작점을 바꾼 것이었습니다. 스크립트를 고친 뒤 통과했습니다. UI 결함이 아니었습니다.

## 4. 남은 관찰 사항 (결함 아님, 개선 후보)

| 항목 | 내용 |
|---|---|
| 로그인 화면의 Tab 수 | 페이지를 연 직후 이메일 칸까지 Tab 9회입니다(건너뛰기 링크·헤더·주 메뉴). 건너뛰기 링크를 쓰면 줄어듭니다. 로그인 화면에서 이메일 칸 자동 포커스는 낭독 순서 문제와 맞바꿈이 있어 제안만 합니다 |
| 다크 모드 | 토큰이 밝은 테마 하나뿐이라 점검 대상이 없습니다 |

## 5. 실행하지 않은 것 (NOT_RUN)

- 스크린리더 실제 낭독(NVDA·JAWS·내레이터·VoiceOver)
- Firefox·Safari·모바일 실제 기기
- 컴포넌트별 CSS에 직접 쓴 색상(토큰 외)의 대비 — 토큰만 점검
- T44·T57 화면(main에 없음)

## 6. 실행 방법

```bash
cd frontend
npm run typecheck && npm run lint && npx vitest run && npm run build
npx vitest run src/a11y                 # T89 접근성 회귀만

# 실제 브라우저 (선택, 수동)
VITE_API_MOCK=true npx vite --port 5189
PLAYWRIGHT_CORE=<playwright-core 경로> BASE_URL=http://127.0.0.1:5189 CHROME=<chrome.exe> EDGE=<msedge.exe> \
  node scripts/a11y-browser-check.mjs > result.json
```

## 7. 결과 (로컬 Windows)

| 검사 | 결과 |
|---|---|
| typecheck | PASS |
| lint (oxlint --deny-warnings) | PASS |
| Vitest 전체 | 385 passed, 22 skipped (T89 신규 35) |
| build | PASS |
| 실제 Chrome·Edge | PASS (§3) |
| CI | PR 본문 참고 |

UI·Backend·Staging·배포 설정 변경 0건, 새 의존성 0건입니다. playwright-core는 저장소 의존성으로 추가하지 않았고, 수동 점검 때 경로로만 지정합니다.
