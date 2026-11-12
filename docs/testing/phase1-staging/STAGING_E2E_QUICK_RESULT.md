# Staging E2E 빠른 결과 (S12)

> 2026-11-12 · 전체 보고서: [PHASE1_STAGING_FINAL_REPORT.md](PHASE1_STAGING_FINAL_REPORT.md) (PR #245)
> **판정: `STAGING_E2E_ENV=PARTIAL`.** 완료 조건 1 "Staging 에서 React 화면이 열린다" 를 충족하지 못했습니다.
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
