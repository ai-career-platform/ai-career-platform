# Phase 1 Staging 통합 검증 — 최종 보고서

> 작성: 2026-11-12 · 실행 SORNET(Claude Code) · 코디네이터 GPT-Web · PM 문길래
>
> **판정: PARTIAL.** 완료 조건 10개 중 4개가 충족되지 않았습니다(§10). **S10 재점검 결과는 §11** 에 있습니다(변화 없음: 승인 0건 → 병합·배포 없음).
> - **PR 병합은 0건입니다.** `main` 규칙셋이 승인 리뷰 1건을 요구하는데, 리뷰가 0건입니다. 지시에 따라 자체 승인과 우회 병합은 하지 않았습니다.
> - 병합이 없으니 Auto-CD 도 돌지 않았습니다. 그래서 **Staging 의 React 배포와 배포 후 검증은 `NOT_VERIFIED`** 입니다.
> - Phase 1 대상 목록은 원본 관리표가 없어 여전히 `PHASE1_SCOPE_PENDING` 입니다.
>
> Staging·DB·Secret 설정 변경은 0건입니다. Staging 에 보낸 요청은 GET 뿐입니다.

## 1. 기준

| 항목 | 값 |
|---|---|
| `main` | `c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce` (작업 중 변화 없음) |
| Staging 실행 SHA | `/api/version` = `c7dc2e1…` (= main) |
| Staging 접근 | HTTP 게이트웨이 `:18080` 가능 / SSH 키 인증 거부 → 호스트·DB 직접 접근 불가 |
| 격리 환경 | 로컬 일회용 PostgreSQL 18.6(loopback). migration 0001~0003 + T10 seed + 합성 계정 2개(구직자·관리자). 실제 Backend `app.main`, 프로덕션 React 번들(Docker 이미지와 같은 `VITE_*`), nginx 규칙을 재현한 로컬 게이트웨이 |
| 브라우저 | 헤드리스 Chrome + playwright-core(저장소 의존성 아님) |

## 2. Phase 1 기능 범위

- **확정하지 못했습니다(`PHASE1_SCOPE_PENDING`).** 우선순위 왼쪽 숫자 열이 있는 원본 관리표가 저장소·GitHub·로컬 어디에도 없습니다. 열 의미도 검증되지 않았습니다.
- 대신 **구현 완료 일감 109개**([매트릭스](STAGING_IMPLEMENTED_FEATURE_MATRIX.md))와 **Frontend 27개**([S8 §7](S8_REACT_STAGING_DEPLOY_PLAN.md))를 검증 대상으로 삼았습니다.
- 관리표를 확보하면 이 결과에서 Phase 1 행만 골라 다시 집계합니다.

## 3. PR 현황

| PR | 내용 | CI(최신 HEAD) | 리뷰 | 병합 |
|---|---|---|---|---|
| [#244](https://github.com/ai-career-platform/ai-career-platform/pull/244) | F-01 OpenAPI 인증 선택 표기 | 5/5 success (`f52f72d`) | 0 | **MERGE_BLOCKED** |
| [#245](https://github.com/ai-career-platform/ai-career-platform/pull/245) | 매트릭스·중간·최종 보고서·증빙(이 문서) | PR 댓글 | 0 | **MERGE_BLOCKED** |
| [#246](https://github.com/ai-career-platform/ai-career-platform/pull/246) | S8 배포 설계 | 3/3 success (`61cee43`) | 0 | **MERGE_BLOCKED** |
| [#247](https://github.com/ai-career-platform/ai-career-platform/pull/247) | **F-02 React Staging 배포 구현** + main lint 수정 + FE27 시나리오 | 4/4 success (`2c3f334`), 컨테이너 smoke PASS | 0 | **MERGE_BLOCKED** |
| [#248](https://github.com/ai-career-platform/ai-career-platform/pull/248) | **T40 북마크 저장 버튼 누락 수정** | 4/4 success (`12c3f3d`) | 0 | **MERGE_BLOCKED** |

- **병합 권장 순서**: #244 → #248 → #247 → #246 → #245
- #247 과 #248 은 같은 lint 수정 커밋(F-04)을 함께 담고 있어 충돌 없이 합쳐집니다.
- #247 병합이 곧 Staging React 배포입니다. 기존 Auto-CD 로 게시 → 배포 순서로 진행됩니다.

## 4. API 시험 (Staging, 실제)

증빙: [`evidence/staging_s3_http_checks_c7dc2e1.json`](evidence/staging_s3_http_checks_c7dc2e1.json)

| 묶음 | 건수 | 결과 |
|---|---|---|
| Health·version·DB health | 3 | PASS |
| 인증 필요 GET 26개 × (무토큰·위조 토큰) | 52 | PASS (모두 401) |
| 공개 카탈로그 7개 경로 무인증(T148 `PUBLIC_ROUTES`) | 7 | PASS (200/404/422) |
| 공개 조회(동의 정책·수집 공고) | 3 | PASS |
| 플래그 꺼진 기능 미노출 | 9 | PASS |
| 정적 자원·보안 헤더(배포 전 PoC 페이지) | 7 | PASS |
| **합계** | **81** | **81 PASS** |
| OpenAPI 계약 일치(F-01) | 1 | **FAIL → #244 로 수정**(Staging 반영은 병합 후) |

## 5. DB 정합성

| 범위 | 시험 | 결과 | 증빙 |
|---|---|---|---|
| **Staging** (API 경유, 읽기 전용) | 커서 전체 순회 중복 0(직무 30·공고 80·기업 20), 목록↔상세 15/15, 공개 목록 비게시·만료 0, 공고→기업 16·공고→직무 24 참조 누락 0, 수집 공고 URL 중복 0/33 | **PASS** (12) | [`evidence/staging_s3_data_consistency_c7dc2e1.txt`](evidence/staging_s3_data_consistency_c7dc2e1.txt) |
| **Staging** 기존 데이터 보존 | 공개 공고 80·공고 있는 기업 16·기업 20·직무 30 이 **T10 seed 와 정확히 일치**(격리 DB 에 같은 seed 를 넣어 대조) | **PASS** | §1 격리 DB |
| Staging 스키마·Migration 원장·FK/UNIQUE 직접 조회 | — | **BLOCKED** (DB 비공개, SSH 불가) | — |
| **격리 PG** (CI 와 같은 조건) | Backend 전체: FK·UNIQUE·트랜잭션 COMMIT/ROLLBACK·권한·격리 시험 포함 | **1874 passed**. 1 failed + 31 errors 는 Windows 0700 기준선뿐(main 과 같음, Linux CI 통과) | [`evidence/backend_full_pg_isolated.txt`](evidence/backend_full_pg_isolated.txt) |
| **격리 PG** E2E 쓰기 후 DB | 기술 저장 → `career.user_skills` 1행, 북마크 → `career.user_job_bookmarks` 1행 | **PASS** | §6 |

## 6. Frontend·E2E

| 실행 | 대상 | 결과 | 증빙 |
|---|---|---|---|
| **격리**: `phase1-fe27.mjs` R·H·A·W | 27개 일감 전부 | **36/36 PASS** | [`evidence/fe27_isolated_real_api.json`](evidence/fe27_isolated_real_api.json) |
| **격리**: `phase1-fe27.mjs` R·H 읽기 전용 모드 | 17개 일감 | **21/21 PASS** | (같은 스크립트, `E2E_READONLY=1`) |
| **격리**: 기존 T117 실제 API 시나리오 | 여정·권한·키보드·네트워크 오류 | **34/34 PASS** | [`evidence/t117_isolated_real_api.json`](evidence/t117_isolated_real_api.json) |
| **Staging 배포 전**: `phase1-fe27.mjs` R·H 읽기 전용 | 17개 일감 | **21/21 FAIL** — React 미배포(F-02). 판정이 올바름을 보여 주는 기준선 | [`evidence/fe27_staging_pre_deploy_c7dc2e1.json`](evidence/fe27_staging_pre_deploy_c7dc2e1.json) |
| **CI 컨테이너**: `docker_route_smoke.py` | 통합 frontend 이미지 + backend | `REACT_SPA_AND_STATUS_PAGE=PASS`, `DOCKER_BUILD_NGINX_AND_T16_ROUTES=PASS`. 이미지 안 vitest 42 files passed | #247 Crawler MVP run 43152875177 |
| **Staging 배포 후** | React·FE27·OpenAPI 재조회 | **NOT_VERIFIED** (병합 대기) | — |

- **화면 검증 방법**
  - React 루트(`#root h1`)가 렌더링되어야 화면으로 인정합니다.
  - 그 화면에서 실제로 호출된 `/api/v1` 요청과 상태 코드를 기록합니다.
  - 5xx, 실패 요청, 외부 Origin 요청, JS 오류가 하나라도 있으면 FAIL 입니다.
- **브라우저 시간대**: America/Los_Angeles 로 실행했는데도 마감일이 KST 로 표시됨을 확인했습니다(T146).
- **Mock 결과는 이 표에 넣지 않았습니다.** 격리 결과도 Staging 결과로 옮기지 않았습니다.

## 7. CI

- 5개 PR 의 최신 HEAD 에서 필수 검사 `CI Smoke Test` 를 포함해 모두 success 입니다(§3).
- main 의 Frontend CI 는 #240 이후 **실패 중**입니다(F-04). #247·#248 에 수정이 들어 있습니다.

## 8. 발견한 오류와 수정

| ID | 내용 | 원인 | 수정 | 재검증 |
|---|---|---|---|---|
| F-01 | 런타임 OpenAPI 가 공개 카탈로그 4경로를 인증 필수로 표시 | T18 라우터에 "인증 선택" 표기 없음 | #244 | 수정 전 실패·후 통과, 관련 148 passed |
| F-02 | Staging Frontend 가 PoC 페이지, React 미배포 | 게시 워크플로가 `poc/staging/frontend` 만 빌드 | #247 (같은 이미지에 React, 상태 페이지는 `/staging-status.html`) | CI 컨테이너 smoke PASS, 격리 E2E 36/36. **Staging 은 병합 후** |
| F-03 | **T40 공고 저장 버튼 없음**(작업지시서 DoD 미충족) | `bookmarks.add` 를 쓰는 화면 없음 | #248 (공고 상세 저장/해제 버튼) | 단위 4건 + 격리 E2E W(PUT 200 → 목록 표시 → DB 1행) |
| F-04 | main Frontend CI lint 실패(#240 이후) | 컴포넌트 파일이 hook 도 export(`react-refresh`) | #247·#248 (hook 을 `.ts` 로 분리) | Frontend CI pass |
| F-05 | 이미지 안 vitest 가 `../docs` 계약 파일을 못 읽음 | 빌드 컨텍스트에 `frontend/` 만 있음 | #247 (`docs` named context, `/repo` 구조) | 42 files passed, skip 증가 없음 |
| (시험 쪽) | 합성 동의 정책 코드 `marketing` → `GET /consent-policies` 500 | **시험 데이터 오류**(계약 밖 코드). 제품 결함 아님 | 격리 데이터 수정 | 이후 PASS |

**관찰(수정 안 함)**
- O-1: `:18080` 이 내부망에 열려 있습니다. 문서는 127.0.0.1 바인딩입니다.
- O-2: Swagger 가 공개되어 있습니다.
- O-3: `/api/training` 에 CSP 가 없습니다.
- O-4: refresh 쿠키가 `Secure` 라 HTTP Staging 에서는 새로고침하면 로그아웃됩니다(S8 R3).

## 9. 해결되지 않은 BLOCKED 와 필요한 조치

| 항목 | 막힌 이유 | 필요한 조치 |
|---|---|---|
| **PR 병합 5건** | 규칙셋: 승인 리뷰 1건 필수, 리뷰 0건. 우회 금지 | Crasnec 또는 쓰기 권한자의 리뷰 승인 |
| Staging React 배포·배포 후 검증 | 병합 대기 | 병합 → Auto-CD 확인 → `phase1-fe27.mjs E2E_READONLY=1 E2E_TIERS=R,H` + S3 재실행 |
| Staging DB 스키마·Migration 원장·로그 | SSH 키 인증 거부 | 호스트 운영자의 읽기 전용 실행 또는 SSH 권한 |
| Staging 로그인 조회(A 등급 10개) | 테스트 계정 없음, HTTP 에서 Secure 쿠키 | 테스트 계정과 HTTPS 또는 SSH 터널(S8 승인 4·5·6) |
| Phase 1 확정 | 원본 관리표 없음 | 관리표(TSV·xlsx) 제공 |

## 10. 완료 조건 판정

| # | 조건 | 판정 |
|---|---|---|
| 1 | 기존 Staging 기능·데이터 유지 | **PASS** (81 + 12 PASS, seed 일치, 쓰기 0) |
| 2 | React 실제 배포·HTTP 검증 | **NOT_VERIFIED** (CI 컨테이너 PASS, Staging 미배포) |
| 3 | Frontend↔Backend API 연동 | **PASS(격리)** / Staging NOT_VERIFIED |
| 4 | PostgreSQL 연결·정합성 | **PASS** (Staging API 경유 + 격리 PG) / Staging 직접 조회 BLOCKED |
| 5 | Phase 1 확정 범위 E2E | **HOLD** (범위 미확정. 27개 일감은 격리 PASS) |
| 6 | 결함 수정·재검증 | **PASS** (F-01~F-05, 격리·CI) |
| 7 | CI 필수 검사 | **PASS** (5 PR) |
| 8 | PR 병합 | **MERGE_BLOCKED** |
| 9 | 원격 main 최종 상태 | 확인함: `c7dc2e1` 그대로(병합 0) |
| 10 | 최종 보고서 반영 | 이 문서(#245, 병합 대기) |

```text
FINAL_STATUS=PARTIAL
MAIN_SHA=c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce
STAGING_DEPLOY_SHA=c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce
PRS_MERGED=0 (MERGE_BLOCKED: required review)
STAGING_WRITE_REQUESTS=0
PRODUCTION_CHANGED=NO
```

## 11. S10 재점검 (2026-11-12)

### 11.1 PR·main·Staging 상태
- `origin/main`·Staging 실행 SHA 는 둘 다 `c7dc2e1` 로 그대로입니다.
- 5개 PR 모두 OPEN 이고 Draft 가 아닙니다. 승인 리뷰는 **0건**, `mergeStateStatus=BLOCKED` 입니다.

| PR | HEAD | 필수 CI | 승인 | 판정 |
|---|---|---|---|---|
| #244 | `f52f72d` | 5/5 success | 0 | MERGE_BLOCKED |
| #248 | `12c3f3d` | 4/4 success | 0 | MERGE_BLOCKED |
| #247 | `2c3f334` | 4/4 success | 0 | **HOLD** (리뷰 승인 없음 + **별도 배포 승인 없음**) |
| #246 | `61cee43` | 3/3 success | 0 | MERGE_BLOCKED |
| #245 | 이 커밋 | — | 0 | MERGE_BLOCKED |

### 11.2 순차 병합 시뮬레이션 (로컬, 원격 변경 없음)
권장 순서(#244 → #248 → #247 → #246 → #245)대로 최신 `main` 위에 squash 를 차례로 적용했습니다.

- **충돌은 0건입니다.** #248 이 먼저 들어가면 #247 의 같은 lint 수정 3파일은 빈 변경으로 빠집니다(#247: 12 → 9 파일).
- 합친 상태의 검증 결과

| 영역 | 결과 |
|---|---|
| Frontend | oxlint 0 · `tsc -b` 0 · vitest **590 passed** · production build 성공 |
| `poc/staging/tests` | 17 passed |
| automation unittest | OK |
| Backend 전체(Windows) | 1645 passed, 1 failed + 31 errors = 기존 0700 기준선과 같음 |

### 11.3 #247 배포 안전 조건

| # | 조건 | 상태 |
|---|---|---|
| 1 | React 이미지 빌드 | PASS (CI Crawler MVP) |
| 2 | Docker route smoke | PASS (`REACT_SPA_AND_STATUS_PAGE`, `DOCKER_BUILD_NGINX_AND_T16_ROUTES`) |
| 3 | Frontend lint·typecheck·test·build | PASS (Frontend CI + 이미지 안 실행) |
| 4 | nginx 설정 검증 | PASS (컨테이너 `nginx -t` + 정적 시험 4건) |
| 5 | 기존 Backend API 경로 유지 | PASS (`/api/`·`/api/v1/` 블록 불변, smoke 의 T16 경로) |
| 6 | 상태 페이지 보존 | PASS (`/staging-status.html`) |
| 7 | 기능 플래그 기본값 | PASS (빌드 플래그 꺼짐, `env.ts` 전수 대조 시험) |
| 8 | Staging 접근 범위 검토 | **결정 필요**: `:18080` 이 내부망에 열려 있음(O-1). React 가입 화면이 공유 DB 에 쓸 수 있음(S8 R4) |
| 9 | 배포 전 정상 digest·복구 절차 | **기록함**(아래) / 절차는 `RELEASE_RUNBOOK.md` §3 |
| 10 | 배포 승인 | **없음 → HOLD** |

배포 전 정상 이미지(롤백 기준, 게시 run `43051867953` #207, `c7dc2e1`):
- backend `ghcr.io/ai-career-platform/ai-career-platform-backend@sha256:4e8a5e0018eddc8197e3d86e99029e42c9a580bbcda0f9d37be42ea48b740c50`
- frontend `ghcr.io/ai-career-platform/ai-career-platform-frontend@sha256:72ba1693761f419e8a234a60fd6b0da424dd2229e1b14698d1a3cb4e0a8018b5`

### 11.4 Staging 회귀 (읽기 전용, `c7dc2e1`)
- HTTP 시험 **81/81 PASS**: health 3, 무토큰·위조 토큰 401 52, 공개 카탈로그 7, 공개 조회 3, 플래그 꺼짐 9, 정적·헤더 7
- 데이터 정합성 PASS: 페이지 중복 0, 비게시·만료 0, 참조 누락 0, seed 일치
- **F-01 은 Staging 에 그대로 남아 있습니다.** 런타임 OpenAPI 의 4경로가 여전히 `[{"HTTPBearer": []}]` 입니다. #244 가 배포되지 않았으므로 예상대로입니다.
- R·H·A 브라우저 시험은 **NOT_VERIFIED**(React 미배포)입니다. 실행 조건인 "#247 이 Staging 에 배포됨"이 충족되지 않아 실행하지 않았습니다.

### 11.5 판정

| 구분 | 판정 |
|---|---|
| GitHub 병합 | 0건 (MERGE_BLOCKED) |
| CI | PASS (5 PR + 합친 상태 로컬 재현) |
| 격리 PostgreSQL·E2E | PASS (36/36, 34/34, 1874 passed) |
| Staging 실제 연동 | 부분: Backend·간접 DB PASS / React·F-01~F-03 반영 NOT_VERIFIED / DB 직접 BLOCKED |
| Phase 1 전체 | `PHASE1_SCOPE_PENDING` |
| 릴리스 | **NO_GO** (T150 Gate NO_GO 유지, Staging 미반영) |

## 12. S11 재점검 (2026-11-12)

S10 이후 상태가 바뀌지 않았습니다. 같은 시험은 반복하지 않았고(§11 증빙 재사용), 상태 조회와 접근 수단 1회 확인만 했습니다.

| 항목 | 결과 |
|---|---|
| `origin/main`, Staging `/api/version` | 둘 다 `c7dc2e1` |
| #244 `f52f72d` · #248 `12c3f3d` · #247 `2c3f334` · #246 `61cee43` · #245 | CI 전부 success. 충돌 없음(`MERGEABLE`). **승인 0건**, 리뷰 요청(Crasnec) 유지 → `MERGE_BLOCKED`. #247 은 배포 승인도 없어 **HOLD** |
| Auto-CD | 실행되지 않음(병합 없음). 롤백 기준 digest 는 §11.3 |
| SSH 키 인증 | 여전히 거부 → DB 스키마·Migration 원장·서비스 로그 **BLOCKED** |
| 테스트 계정·HTTPS 경로 | 제공되지 않음 → A 등급 **BLOCKED** |
| Phase 1 원본 관리표 | 저장소 TSV 5개 모두 우선순위 왼쪽 열이 '작업 제목'. `read:project` 권한 없음 → `PHASE1_SCOPE_PENDING` |
| `:18080` 접근 범위 | 변경하지 않음. **PM 결정 사항**: 127.0.0.1 바인딩 복원 또는 내부망 허용 유지 |

결함 상태(상태를 서로 대체하지 않음)

| ID | FIXED_IN_PR | MERGED | DEPLOYED | VERIFIED_STAGING |
|---|---|---|---|---|
| F-01 | #244 | 아니오 | 아니오 | 아니오(Staging OpenAPI 에 결함 남아 있음) |
| F-02 | #247 | 아니오 | 아니오 | 아니오 |
| F-03 | #248 | 아니오 | 아니오 | 아니오(격리 E2E PASS) |
| F-04 | #247·#248 | 아니오 | — (CI 전용) | — (main Frontend CI 는 아직 실패) |
| F-05 | #247 | 아니오 | 아니오 | — (CI PASS) |

판정: **Staging PARTIAL**, **Release NO_GO**(T150 Gate 유지).
