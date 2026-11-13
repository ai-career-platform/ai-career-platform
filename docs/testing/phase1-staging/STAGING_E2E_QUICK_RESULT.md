# Staging E2E 빠른 결과 (S12 → S15)

> 2026-11-12 · 전체 보고서: [PHASE1_STAGING_FINAL_REPORT.md](PHASE1_STAGING_FINAL_REPORT.md) (PR #245)
>
> **최신 판정(S15, §9): `STAGING_E2E_ENV=READY`** (R·H 읽기 전용 범위)
> - #248·#247 병합 → Auto-CD 로 Staging `c1551a4` 배포
> - 실제 Staging React 대상 자동 E2E: **22/22 PASS**
> - A 그룹(로그인)은 여전히 BLOCKED(§6)
>
> 아래 §1~§8 은 배포 전 S12·S13 기록이며 그대로 둡니다.
>
> **S12 당시 판정: `STAGING_E2E_ENV=PARTIAL`.** 완료 조건 1 "Staging 에서 React 화면이 열린다" 를 충족하지 못했습니다.
> - #247 이 병합되지 않아 Staging `/` 는 아직 PoC 상태 페이지입니다. 병합되지 않은 이유는 독립 승인 리뷰 0건과 배포 승인 없음입니다.
> - 그래서 같은 React 번들을 로컬에서 띄우고 **API 는 실제 Staging** 으로 보내는 읽기 전용 방식으로 자동 E2E 를 돌렸습니다.

## 1. 접속과 상태

| 항목 | 값 |
|---|---|
| Staging URL | `http://<staging-host>:18080/` (호스트는 `docs/STAGING.md` "환경") |
| Staging SHA | `/api/version` = `c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce` (= main) |
| React 실제 배포 | **아니오** (#247 OPEN, 승인 0, 배포 승인 없음 → HOLD) |
| PR | #248 `12c3f3d` · #247 `5412f71` · #244 `f52f72d` — 모두 CI success, 충돌 없음, 승인 0 → `MERGE_BLOCKED` |
| 롤백 기준 이미지 | 게시 run `43051867953`(#207) digest. 최종 보고서 §11.3 |

## 2. 자동 E2E 결과

실행 조건
- 브라우저: chromium 157 (headless)
- 스크립트: `frontend/e2e/phase1-fe27.mjs`, `E2E_TIERS=R,H E2E_READONLY=1`
- 번들: main + #248 + #247 을 합친 코드로, Docker 이미지와 같은 `VITE_*` 로 빌드
- API: 실제 Staging `:18080/api/**` 로 그대로 전달(`tools/readonly_staging_preview.py`, GET 이외 403)

| 실행 | 결과 | 증빙 |
|---|---|---|
| **실제 Staging Backend + 로컬 React**(R·H) | **22/22 PASS**, 17개 일감. 요청 87건 모두 GET, 2xx/3xx 외 응답 0 | [`evidence/s12/s12_staging_backend_RH.json`](evidence/s12/s12_staging_backend_RH.json), 스크린샷 `evidence/s12/*.png` |
| 같은 실행을 커밋한 미리보기 도구로 재실행 | **22/22 PASS** | [`evidence/s12/s12_tool_RH.json`](evidence/s12/s12_tool_RH.json) |
| 실제 Staging `/` (React 미배포) | 21/21 FAIL (배포 전 기준선) | [`evidence/fe27_staging_pre_deploy_c7dc2e1.json`](evidence/fe27_staging_pre_deploy_c7dc2e1.json) (#245) |

**기능별 결과** (실제 Staging API·DB 데이터, 화면은 로컬 React)

| 일감 | 확인 | 결과 |
|---|---|---|
| T19 | `/system-status` 버전 = `/api/version` | PASS |
| T20 | 랜드마크, 320·1280px 가로 넘침 없음 | PASS |
| T21 | 로그인 화면(제출 안 함) | PASS |
| T23 | 직무 목록 = API 첫 페이지 | PASS |
| T24 | 목록 = API, 상세 제목 일치 / 검색 `q=테스트` → 200·3건, **새로고침 후 유지** | PASS / PASS |
| T94 | 재설정 화면(제출 안 함) | PASS |
| T146 | 브라우저 시간대 LA 에서도 마감일 KST 표기 | PASS |
| T82·T85·T97·T103·T124·T127·T130·T143·T156 | 직접 URL → "페이지를 찾을 수 없습니다", 메뉴 미노출 | PASS (13 경로) |
| T100 | 고급 필터(Mock) 미노출 | PASS |
| T40(F-03, #248) | 비로그인 공고 상세: '로그인하면 관심 공고로 저장할 수 있어요' 안내 표시 | 화면 확인(스크린샷 `T24-R-5.png`) |

**판정 구분**
- 위 결과는 **Staging API·DB 연동 검증**입니다. **Staging React 배포 검증은 아닙니다.**
- #247 배포 뒤에는 `E2E_BASE_URL=http://<staging-host>:18080` 으로 같은 명령을 다시 실행해야 합니다.

## 3. Backend·DB (실제 Staging, 읽기 전용)
- `/api/health`, `/api/version`, `/api/health/db`: 200
- 인증 필요 GET 401: 52/52
- 공개 카탈로그·데이터 정합성: PASS. 같은 시점 S10 결과(81/81, 12/12)를 재사용했습니다.
- 이번 E2E 화면에서도 seed 데이터(공고·직무·기업)가 API 응답과 같게 표시되었습니다. 이것이 **Staging PostgreSQL 간접 연동 확인**입니다.

## 4. 수동 E2E
- [STAGING_MANUAL_E2E_CHECKLIST.md](STAGING_MANUAL_E2E_CHECKLIST.md)
  - A 방식: 배포 후 Staging 주소
  - B 방식: 지금 바로 할 수 있는 읽기 전용 미리보기
  - 화면별 순서, F12 Console·Network 확인, ⛔ DB 변경 버튼 목록, FAIL 증빙 수집 방법
- 지금은 B 방식으로만 할 수 있습니다(로컬 Node 빌드 필요). 설정 없이 바로 쓰는 A 방식은 #247 배포 후에 가능합니다.

## 5. 결함·PR
- **새 제품 결함: 없음.**
- 시험 도구 판정 오류 2건을 고쳤습니다(#247, `phase1-fe27.mjs`).
  - 검색 입력 선택자 중복
  - 앱이 스스로 취소한 GET 을 실패로 셈
- 시험 도구에 추가한 것(#247): 테스트별 URL·요청·Console·스크린샷 증빙, 검색·새로고침 시험
- 새 PR: 이 문서 PR 1건(문서와 읽기 전용 미리보기 도구)
- **F-06 (간헐 실패, 미수정)**: #247 HEAD `5412f71` 의 이미지 빌드 안에서 `src/pages/admin/ModerationRoutes.test.tsx` "flag off" 1건이 실패했습니다.
  - 근거: 제목 찾기가 1초 안에 끝나지 않았습니다(작업자 45개 병렬). 같은 소스의 Frontend CI 는 통과했고, 실패 job 만 재실행하자 **성공**했습니다(run 43160993554).
  - 위험: 이미지 빌드가 시험을 fail-closed 로 실행하므로, 이 간헐 실패가 게시를 멈출 수 있습니다.
  - 대응: 게시 run 재실행. 또는 후속 PR 로 이미지 안 vitest 작업자 수 제한·해당 시험 대기 시간 조정.

## 6. 인증·쓰기
- **A 그룹(로그인 조회): BLOCKED.** 기존 테스트 계정이 없고 HTTPS 경로도 없습니다. 새 계정은 만들지 않았습니다.
- **W 그룹: 공유 DB 에서 실행하지 않았습니다.** 격리 DB 결과는 최종 보고서 §6(36/36)에 있습니다.

## 7. 다음 작업
1. #248·#247 에 독립 승인 리뷰를 받고, #247 은 PM 배포 승인도 받습니다. `:18080` 접근 범위 결정도 함께 필요합니다.
2. 병합 후 Auto-CD 를 확인합니다: `/api/version` = 새 SHA, `/`·`/login`·`/job-postings` 에서 React 화면, `/staging-status.html` 은 상태 페이지.
3. 실제 Staging 주소로 `phase1-fe27.mjs` R·H 를 다시 실행하고 체크리스트 A 방식으로 수동 점검합니다. 이때 `ENV=READY` 를 판정합니다.
4. 테스트 계정과 HTTPS/터널이 준비되면 A 그룹을 진행합니다.

## 8. S13 (2026-11-12) — PM 배포 승인 반영

**PM 승인(S13)**
- 승인됨: #247 의 Staging 배포, 기존 Auto-CD 사용, 사내망 접근 유지
- 남은 조건: 독립 승인 리뷰 1건

**PR 상태**

| PR | HEAD | CI | 승인 | 판정 |
|---|---|---|---|---|
| #248 | `12c3f3d` | 4/4 | 0 | MERGE_BLOCKED |
| #247 | `5412f71` | 4/4 | 0 | MERGE_BLOCKED (배포 승인은 확보, 리뷰 대기) |
| #244 | `f52f72d` | 5/5 | 0 | MERGE_BLOCKED (F-01 OPEN) |

- #248 과 #247 에 Crasnec 리뷰 요청 댓글을 남겼습니다(검토 포인트, 롤백 기준, 병합 순서).
- 병합이 없으므로 Auto-CD 는 실행되지 않았습니다. Staging SHA 는 `c7dc2e1`, `/` 는 PoC 상태 페이지 그대로입니다.
- 그래서 **실제 Staging React 대상 자동 E2E 는 실행할 수 없었습니다.** 같은 스크립트로 배포 직후 바로 실행할 수 있습니다.
  - 명령: `E2E_BASE_URL=http://<staging-host>:18080 E2E_TIERS=R,H E2E_READONLY=1 node e2e/phase1-fe27.mjs`
  - 기준: 로컬 React + 실제 Staging API 22/22
- **외부 인터넷 노출**
  - Staging 주소는 사설 대역(RFC1918)이라 인터넷에서 직접 들어오는 경로는 없습니다.
  - 호스트의 ngrok 등 터널로 `:18080` 이 공개되는지는 SSH 없이 확인할 수 없습니다 → **NOT_VERIFIED**. 호스트 운영자가 확인해야 합니다.
- 판정: `STAGING_E2E_ENV=PARTIAL`

## 9. S15 (2026-11-12) — 실제 Staging React 배포 확인과 E2E

**판정: `STAGING_E2E_ENV=READY`** (R·H 읽기 전용 범위. A 그룹은 §6 대로 BLOCKED)

### 9.1 병합과 Auto-CD

| 단계 | 결과 |
|---|---|
| #248 병합 | `9ebc4c3` (05:54Z). 게시 run `43164741299` success → Staging `9ebc4c3` 배포 |
| #247 병합 | `c1551a4` (08:33Z) |
| main CI (`c1551a4`) | CI · Frontend CI · Crawler MVP 모두 success |
| 게시 run `43184329797` | success (08:36Z~08:38Z) |
| 게시 run: 이미지 안 시험 | 이미지 빌드 안에서 lint·vitest 통과(Test Files 43 passed, 3 skipped). **F-06 재발 없음** |
| 게시 run: 새 digest | frontend `sha256:350d56edf5b52f5a9b84e44e4bce4948aff96eef92bfafb970f57a136eff8f52`, backend `sha256:1753cafa3f197c30a7e583c48b429a69376365858a2efda68e0042f01a12ec34` |
| Staging 반영 | 08:39:56Z `/api/version` = `c1551a469bfcef19f788a6507181ee3468581f5a` (= main) |

- 롤백 기준은 그대로입니다: 게시 run `43051867953`(#207, `c7dc2e1`). 절차는 최종 보고서 §11.3 과 `docs/release/RELEASE_RUNBOOK.md` §3 입니다.
- **절차 기록**
  - #248 과 #247 은 승인 리뷰 0건(`REVIEW_REQUIRED`) 상태에서 저장소 bypass 권한 계정으로 병합되었습니다.
  - 이 작업(Claude)이 병합한 것은 아닙니다. 사후 독립 리뷰 여부는 PM 이 판단합니다.

### 9.2 경로 확인 (`http://<staging-host>:18080`)

| 경로 | 결과 |
|---|---|
| `/`, `/login`, `/job-postings`, `/system-status`, `/admin/crawler` | 200, React 셸(`#root`) |
| `/staging-status.html` | 200, 기존 상태 페이지(`status.js`) |
| `/api/health`, `/api/version`, `/api/health/db` | 200 |
| `/api/v1/job-postings?limit=1` | 200, seed 공고 |
| `/assets/<없는 파일>.js` | 404 (SPA fallback 이 적용되지 않음) |
| 헤더 | `index.html` 은 `no-cache`, `/assets/*.js` 는 `immutable`. CSP·`X-Frame-Options: DENY`·`nosniff` 있음 |

### 9.3 자동 E2E — 실제 Staging React

실행 조건
- 명령: `E2E_BASE_URL=http://<staging-host>:18080 E2E_TIERS=R,H E2E_READONLY=1 node e2e/phase1-fe27.mjs`
- 스크립트: main 과 같은 `frontend/e2e/phase1-fe27.mjs`
- 브라우저: chromium 157.0.8103.78
- 실행 시각: 08:40:26Z

| 항목 | 결과 |
|---|---|
| 시나리오 | **22/22 PASS**, 17개 일감 (T19·T20·T21·T23·T24·T94·T146, H 그룹 T82·T85·T97·T100·T103·T124·T127·T130·T143·T156) |
| Network | 요청 90건 모두 GET. 2xx/3xx 외 응답 0건 |
| Console | 오류 0건 |
| T19 | 화면의 Backend version = `c1551a4…` |
| T40 (F-03) | 비로그인 공고 상세에 '로그인하면 관심 공고로 저장할 수 있어요' 표시(`T24-R-5.png`) |

- 증빙: [`evidence/s15/s15_staging_RH.json`](evidence/s15/s15_staging_RH.json). 테스트마다 URL·요청·Console·스크린샷 파일명이 들어 있습니다. 호스트는 `<staging-host>` 로 가렸습니다.
- 스크린샷 9장: `evidence/s15/*.png`. 나머지 13장(H 그룹)은 같은 "페이지를 찾을 수 없습니다" 화면이라 넣지 않았습니다.
- S12 의 "로컬 React + Staging API" 22/22 와 같은 결과입니다. 이번 결과는 **실제 Staging 배포 검증**입니다.

### 9.4 Backend·DB (읽기 전용)

| 항목 | 결과 |
|---|---|
| 전체 GET 점검 | **81/81 PASS** — health 3, 인증 없음 401 26, 잘못된 토큰 401 26, 공개 카탈로그 7, 공개 3, 기능 꺼짐 9, frontend 7 |
| 증빙 | [`evidence/s15/s15_staging_api_get.json`](evidence/s15/s15_staging_api_get.json) |
| 정합성 | 상세 5/5 일치(직무·공고). 공고의 기업·직무 참조 누락 0. 공개 목록에 만료 공고 0. 수집 URL 33/33 고유 |
| OpenAPI | 경로 54개. S10 과 비교해 `info.version` 만 다릅니다(이번 두 PR 은 Backend 변경 없음) |

- **PostgreSQL 간접 연동: PASS.** 근거는 `/api/health/db` 200 과, 화면·API 에 표시된 seed 데이터가 일치한 것입니다.
- SSH 가 없어 DB 직접 조회·로그 확인은 여전히 BLOCKED 입니다.

### 9.5 수동 E2E

- [STAGING_MANUAL_E2E_CHECKLIST.md](STAGING_MANUAL_E2E_CHECKLIST.md) 의 **A 방식(Staging 주소)이 지금 바로 가능합니다.** 로컬 빌드는 필요 없습니다.
  - R1~R10: 공개 화면
  - H 그룹: 숨김 화면
  - ⛔ 버튼은 누르지 않습니다
- B 방식(읽기 전용 미리보기)은 더 이상 필요하지 않습니다. 기록용으로 남깁니다.
- 체크리스트 R7(T40 비로그인 안내)도 이제 Staging 에서 확인할 수 있습니다.

### 9.6 결함·남은 일

- **새 결함: 없음.** 수정 PR 없음.
- **F-06**: 이번 게시에서는 재발하지 않았습니다. 간헐 위험은 남아 있어 OPEN 입니다.
- **F-01 (#244)**: OPEN. OpenAPI 의 공개 경로 보안 표기 문제입니다. 화면·E2E 에는 영향이 없습니다.
- **A 그룹(로그인 조회)**: BLOCKED. 기존 테스트 계정이 없고, HTTPS 또는 SSH 터널도 없습니다(Secure 쿠키).
- **외부 인터넷 노출**: NOT_VERIFIED. 사설 대역이라 직접 노출 경로는 없지만, 호스트의 터널 여부는 운영자가 확인해야 합니다.
