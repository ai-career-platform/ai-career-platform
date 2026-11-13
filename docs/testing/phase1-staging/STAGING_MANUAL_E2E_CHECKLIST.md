# Staging 수동 E2E 체크리스트 (React 화면)

> 대상: 브라우저로 직접 확인하는 테스터 · 2026-11-12
> 원칙: **공유 Staging DB 를 바꾸는 동작은 하지 않습니다.** 아래 ⛔ 표시 버튼은 승인 전에는 누르지 않습니다.

## 1. 접속 주소

| 방식 | 주소 | 언제 |
|---|---|---|
| **A. Staging 배포본** (기본, **지금 사용**) | `http://<staging-host>:18080/` | #247 배포 완료(2026-11-12, `c1551a4`). 호스트 주소는 `docs/STAGING.md` "환경" 절에 있습니다. 시작 전 확인: `http://<staging-host>:18080/api/version` 의 `version` 이 최신 main SHA 인지 봅니다 |
| **B. 읽기 전용 미리보기** (배포 전 임시, 지금은 불필요) | `http://127.0.0.1:18098/` | 로컬에서 React 를 띄우고 API 는 **실제 Staging** 으로 보냅니다. GET 이외 요청은 도구가 403 으로 막습니다. 준비 방법은 §8 |

- 기존 상태 페이지: `/staging-status.html`.
- 사내망 PC 에서 접속합니다. 다른 프로젝트 포트(80·443·8000)는 열지 않습니다.

## 2. 브라우저 준비 (Chrome)

1. Chrome 을 엽니다. 다른 계정 정보가 섞이지 않게 **시크릿 창**(Ctrl+Shift+N)을 씁니다.
2. 주소창에 위 주소를 입력합니다.
3. **F12** 로 개발자 도구를 엽니다.
   - **Console** 탭: 빨간 오류를 봅니다.
   - **Network** 탭: `Preserve log` 와 `Disable cache` 를 체크합니다. 필터를 `Fetch/XHR` 로 두면 API 요청만 보입니다.
4. 반응형 확인: F12 → 기기 아이콘(Ctrl+Shift+M) → 폭 `320` 과 `1280` 으로 바꿔 봅니다.

## 3. 매 화면 공통 확인

| 항목 | PASS 기준 |
|---|---|
| 화면 | 제목(h1)과 본문이 보입니다. "페이지를 찾을 수 없습니다" 가 아닙니다(숨김 화면은 예외, §5) |
| Console | 빨간 JS 오류가 없습니다 |
| Network | API 요청이 모두 같은 주소의 `/api/...` 로 갑니다. 상태가 2xx 이거나, 로그인 전 `POST /api/v1/auth/refresh` 401 같은 예상된 응답입니다. **5xx 가 없습니다** |
| 새로고침(F5) | 같은 화면이 다시 열립니다 |

- **401 은 정상일 수 있습니다.** 로그인 전 `POST /api/v1/auth/refresh` 401 은 "로그인 안 됨" 확인용입니다. B 방식에서는 이 요청이 403(도구 차단)으로 보입니다.
- **API 응답을 보는 방법**: Network 에서 요청을 클릭 → `Headers`(Method·Status·URL) → `Response`(JSON). 화면에 보이는 값과 JSON 값이 같은지 봅니다.

## 4. 공개 화면 (로그인 없이) — R 그룹

| # | 일감 | 경로 | 할 일 | 기대 결과 | API |
|---|---|---|---|---|---|
| R1 | T19·T20 | `/` | 첫 화면을 열고 왼쪽 메뉴와 상단 '로그인' 을 확인합니다 | 홈 화면이 열리고, 320px 에서도 가로 스크롤이 없습니다 | — |
| R2 | T19 | `/system-status` | 화면을 엽니다 | Backend·DB 연결이 정상으로 나오고, 버전이 `/api/version` 의 `version` 과 같습니다 | `GET /api/health` `GET /api/version` `GET /api/health/db` |
| R3 | T23 | `/job-roles` | 목록을 보고, 직무를 하나 눌러 상세를 엽니다 | 직무 목록(seed 30개)이 나오고 상세에 요구 기술이 보입니다 | `GET /api/v1/job-roles` `GET /api/v1/job-roles/{id}` |
| R4 | T24 | `/job-postings` | 목록을 보고 첫 공고 카드를 눌러 상세를 엽니다 | 카드에 '모집 중'과 마감일이 있고, 상세에 회사·직무·게시일·마감일·요구 기술이 나옵니다 | `GET /api/v1/job-postings` `GET /api/v1/job-postings/{id}` `GET /api/v1/companies/{id}` |
| R5 | T24 | `/job-postings` | '공고 검색' 에 `테스트` 를 입력하고 Enter 를 누릅니다 | 주소에 `?q=테스트` 가 붙고 결과가 줄어듭니다. F5 를 눌러도 검색이 유지됩니다 | `GET /api/v1/job-postings?…q=…` |
| R6 | T24 | `/job-postings` | '기업'·'직무'·'정렬' 을 바꾸고 '마감 포함' 을 누른 뒤 '조건 초기화' 를 누릅니다 | 조건마다 목록이 바뀌고, 초기화하면 처음 목록으로 돌아옵니다 | 같은 목록 API(쿼리만 다름) |
| R7 | T40 (#248 배포 후) | 공고 상세 | 로그인하지 않은 상태에서 상세를 봅니다 | '로그인하면 관심 공고로 저장할 수 있어요' 안내가 보이고, 저장 버튼은 없습니다 | — |
| R8 | T21 | `/login` | 화면만 확인합니다 | 이메일·비밀번호 입력란이 보입니다. ⛔ **'로그인' 버튼은 누르지 않습니다**(세션 기록 생성, §6) | — |
| R9 | T94 | `/password-reset` | 화면만 확인합니다 | 이메일 입력 화면이 보입니다. ⛔ **제출하지 않습니다**(재설정 토큰 생성) | — |
| R10 | T146 | `/job-postings` | 날짜 표기를 봅니다 | `2026년 12월 12일` 같은 한국식 날짜이고, PC 시간대를 바꿔도 날짜가 바뀌지 않습니다(KST) | — |

## 5. 숨겨져야 하는 화면 (기능 꺼짐) — H 그룹

각 주소를 직접 입력합니다. **"페이지를 찾을 수 없습니다"** 가 나오고, 왼쪽 메뉴에도 없으면 PASS 입니다.

- SPA 라서 HTTP 는 200 이 나옵니다. **판정은 화면 내용으로 합니다.**

| 일감 | 주소 |
|---|---|
| T82 | `/admin/moderation` |
| T85 | `/admin/audit-events`, `/admin/ai-usage` |
| T97 | `/me/notifications`, `/me/notification-settings` |
| T103 | `/me/applications` |
| T124 | `/company`, `/company-invitations/accept` |
| T127 | `/company/postings` |
| T130 | `/me/public-profile`, `/p/test` |
| T143 | `/me/data` |
| T156 | `/admin/crawler` |
| T100 | `/job-postings` 에 '상세 조건 · 시범 · Mock' 영역이 **없어야** 합니다 |

## 6. 로그인 화면 (A 그룹) — 승인 전 실행 금지

T22 `/account`, T32 `/account/privacy`, T34 `/me/skills`, T36 `/me/target-roles`, T38 `/me/career-history`, T40 `/me/bookmarks`, T46 `/recommendations`, T50 `/me/documents`, T68 `/market-trends`, T140 `/me/skills` 기술 검색

**아래가 모두 갖춰질 때만 진행합니다.**
1. PM 이 제공한 **기존 테스트 계정**이 있어야 합니다. 새 계정을 가입하지 않습니다.
2. 로그인으로 세션 행이 생기는 것에 대한 승인이 있어야 합니다.
3. HTTPS 또는 `http://127.0.0.1:18080`(SSH 터널) 접속이어야 합니다. 일반 HTTP 주소에서는 Secure 쿠키가 저장되지 않아 새로고침하면 로그아웃됩니다.

로그인한 뒤에는 **조회만** 합니다. ⛔ 표시 버튼은 누르지 않습니다.

## 7. ⛔ 공유 DB 를 바꾸는 버튼 (승인 전 클릭 금지)

| 화면 | 버튼·동작 | 바뀌는 데이터 |
|---|---|---|
| `/login` | 로그인 / 회원가입 | 세션, 사용자, 동의 |
| `/password-reset` | 재설정 메일 요청·비밀번호 변경 | 재설정 토큰, 비밀번호 |
| `/account` | 정보 저장, 세션 종료 | 프로필, 세션 |
| `/account/privacy` | 동의 변경, 탈퇴 요청 | 동의, 탈퇴 요청 |
| `/me/skills` | 저장(기술·숙련도) | 보유 기술 |
| `/me/target-roles` | 저장 | 목표 직무 |
| `/me/career-history` | 추가·수정·삭제 | 경력·프로젝트 |
| 공고 상세 / `/me/bookmarks` | 관심 공고 저장·해제 | 북마크 |
| `/recommendations` | 추천 실행 | 추천 실행 기록 |
| `/me/documents` | 업로드·삭제·분석 | 문서·분석 |
| 공통 | 로그아웃 | 세션 |

쓰기 시험은 격리 DB 에서만 합니다. 결과는 `PHASE1_STAGING_FINAL_REPORT.md` §6(36/36) 에 있습니다.

## 8. B 방식(읽기 전용 미리보기) 준비

#247 배포 전에만 씁니다.

```bash
# 1) React 빌드 (#247 이미지와 같은 플래그)
cd frontend && npm ci
VITE_API_BASE_URL=/api VITE_API_MOCK=false VITE_CRAWLER_ADMIN_UI=false VITE_SKILL_AUTOCOMPLETE=false VITE_BEHAVIOR_TRACKING=false npx vite build
# 2) 읽기 전용 미리보기 실행
python ../docs/testing/phase1-staging/tools/readonly_staging_preview.py dist http://<staging-host>:18080 18098
# 3) Chrome 으로 http://127.0.0.1:18098/ 접속
```

- 로그인·저장 같은 쓰기 요청은 도구가 403 으로 막습니다. 그래서 B 방식에서는 §4·§5 만 할 수 있습니다.
- 빌드 결과 `index.html` 하나에 JS·CSS 가 붙어 있습니다. `/staging-status.html` 은 B 방식에서는 없을 수 있습니다(A 방식에서 확인).

## 9. 자동 E2E (같은 항목)

```bash
cd frontend
E2E_BASE_URL=<A 또는 B 주소> E2E_TIERS=R,H E2E_READONLY=1 E2E_OUT=result.json E2E_SHOTS=shots \
PLAYWRIGHT_CORE=<playwright-core 경로> CHROME_PATH=<chrome.exe> node e2e/phase1-fe27.mjs
```

- `E2E_READONLY=1` 은 GET 이외 요청을 막고 FAIL 로 셉니다. 단, 시작할 때의 refresh 확인 요청은 예외입니다.
- 결과 JSON 에는 테스트마다 URL·요청(메서드·경로·상태)·Console 오류·스크린샷 파일명이 남습니다.

## 10. 기록 방법

| 날짜·시각 | 테스터 | 방식(A/B) | `/api/version` | # | 결과(PASS/FAIL) | 메모·스크린샷 파일 |
|---|---|---|---|---|---|---|
| | | | | R1 | | |

**FAIL 일 때 모을 것**
1. 화면 전체 스크린샷: Windows `Win+Shift+S`, 또는 F12 → Ctrl+Shift+P → `Capture full size screenshot`
2. Console: 오류 줄 우클릭 → `Save as...`
3. Network: 아무 요청이나 우클릭 → `Save all as HAR with content`
   - **HAR 에는 토큰·쿠키가 들어 있을 수 있습니다.** 공유하기 전에 지우거나 담당자에게만 전달합니다.
4. 실패한 요청의 Method, URL, Status, Response 본문 앞부분
5. `/api/version` 의 `version` 값과 접속 방식(A/B)
