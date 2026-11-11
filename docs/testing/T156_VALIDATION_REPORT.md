# T156 검증 보고서 — 크롤러 관리자 UI·통합 QA

> 상태: **PARTIAL**
> - 로컬 격리 환경에서 `관리자 UI → 관리자 API → Fixture fetch → Raw 저장 → Parse → 정제 DB → 조회` 전 구간을 확인했습니다.
> - Staging은 검증하지 않았습니다. `STAGING_E2E=NOT_RUN`, `LIVE_COLLECTION=HOLD`
> - 화면 플래그 `VITE_CRAWLER_ADMIN_UI`는 기본 꺼짐입니다.

## 1. 작업 목적
T155 관리자 API를 쓰는 관리자 전용 크롤러 콘솔을 기존 라우팅과 인증 체계에 연결합니다.

## 2. 기존 구현·PR 재사용
- 인증: `RequireAuth roles={['admin']}`, `AuthProvider` 세션 HttpClient(토큰은 메모리, CSRF 헤더)
- 화면 패턴: T85 운영 감사 화면(Provider·Context·Mock Adapter·HTTP Adapter 분리)
- 공용 컴포넌트: `DataTable`, `StatePanel`, `ConfirmDialog`, `Button`, `formatKstDateTime`
- API: T155 읽기(#124, main)와 T155 쓰기(#233, 이 PR의 base)
- E2E 중간 구간: T152 `capture_fixture_batch`, T154 `FixturePayloadStore`·`process_fixture_job`, T153 `RawParseLedger`를 그대로 호출

## 3. BASE_SHA / HEAD_SHA
- Base 브랜치: `task/t155-crawler-admin-write-api` @ `a92b916` (Stacked)
- main 기준: `822fa16660afdaa5ad099f059b244216332becf1`
- HEAD_SHA: PR 댓글에 기록합니다.

## 4. 변경 파일
| 파일 | 내용 |
|---|---|
| `frontend/src/pages/admin/CrawlerAdminPage.tsx` | 탭 5개 화면(WAI-ARIA tabs: ←/→/Home/End) |
| `frontend/src/pages/admin/CrawlerAdminPanels.tsx` | 각 탭 내용(아래 §7) |
| `frontend/src/pages/admin/CrawlerAdmin.css` | 반응형(375px), 포커스 표시 |
| `frontend/src/api/crawlerAdmin.ts` | 계약 타입, 서비스 인터페이스, 409 사유 → 한국어 문구 |
| `frontend/src/api/crawlerAdminHttp.ts` | 실제 API Adapter. `/settings`가 404면 읽기 API `/schedules`로 대신 표시 |
| `frontend/src/mocks/crawlerAdmin.ts` | 메모리 Mock(합성 데이터). T155 거부 규칙을 같게 흉내 |
| `frontend/src/admin/CrawlerAdminServiceProvider.tsx`, `crawlerAdminContext.ts` | Mock 모드면 Mock, 아니면 세션 HttpClient |
| `frontend/src/api/http.ts`, `errors.ts` | **추가만**: 요청별 헤더(`Idempotency-Key`), 오류 응답 헤더 보존. Accept·CSRF·Authorization은 덮어쓸 수 없음 |
| `frontend/src/api/index.ts` | `crawlerAdmin` 등록 |
| `frontend/src/config/env.ts`, `frontend/.env.example` | `VITE_CRAWLER_ADMIN_UI`(기본 false) |
| `frontend/src/routes.tsx`, `frontend/src/layouts/AppLayout.tsx` | `/admin/crawler` 경로, admin 메뉴 "크롤러 관리"(플래그 + admin일 때만) |
| `frontend/src/pages/admin/CrawlerAdmin.test.tsx` | Vitest 17건 |
| `docs/testing/t156/*.json` | 브라우저 증빙(로컬 실제 API, Mock) |

기존 플래그·경로는 삭제하지 않았습니다.

## 5. 선행조건
| 선행 | 상태 |
|---|---|
| T155 읽기 API | main 병합(#124) |
| T155 쓰기 API | **#233 미병합**. 이 PR은 그 위에 쌓은 Stacked PR |
| T20·T21 공통 UI·인증 | main |
| Staging Backend 이미지의 `crawler` 패키지 포함 | 미해결(T155 Blocker 2) |

## 6. 실제 실행 명령
```bash
cd frontend
npm run lint; npx tsc -b --noEmit; npx vitest run; npm run build
# 로컬 실제 API E2E (일회용 PG 18.6 127.0.0.1:55496: 앱 DB t156_app + 크롤러 DB ai_career_crawler_training)
CRAWLER_ADMIN_WRITE_API=true CRAWLER_DB_MODE=local CRAWLER_LOCAL_DATABASE_URL=<crawler_staging 로컬 DSN> \
  DATABASE_URL=<로컬 t156_app> python -m uvicorn app.main:app --port 8156
VITE_API_MOCK=false VITE_CRAWLER_ADMIN_UI=true DEV_API_PROXY_TARGET=http://127.0.0.1:8156 npx vite --port 5203
node t156_e2e_real.cjs     # Chrome(playwright-core), 중간 구간은 t156_fixture_hop.py 호출 (로컬 작업 스크립트, 저장소 미포함 — 결과 JSON만 커밋)
VITE_API_MOCK=true VITE_CRAWLER_ADMIN_UI=true npx vite --mode mock --port 5203
node t156_mock_check.cjs
```
- 계정은 합성 계정 `t156-admin@example.com`, `t156-user@example.com`만 썼습니다.
- 서버는 모두 끝난 뒤 중지했고, 5203·8156 포트가 비어 있음을 확인했습니다.

## 7. 정상·오류·권한 검증
화면 기능:
- **검색어**
  - 목록과 통계(작업 수, 발견 공고 수)
  - 추가: NFKC·공백 정리, 1~100자, 우선순위 1~9999
  - 수정: 편집 폼을 열면 첫 입력에 포커스, Esc로 취소
  - 활성·비활성, 삭제(확인 대화상자), 변경 이력, Fixture 실행, 작업 보기
- **작업**: 상태·검색어 필터. 대기 작업은 중단, 실패·취소 작업은 재시도. RUNNING·FETCHED는 "Worker 처리 중"으로 표시하고 버튼 없음
- **실행 이력**: 수집·신규·중복·실패 수, 실패 건수 요약, 실행 로그(`safe_message`만)
- **스케줄 설정**: 실행 시각만 변경. "스케줄 활성"은 비활성화된 체크박스로 표시하고 별도 승인 필요를 안내. 야간 시간창은 읽기 전용. 서버 쓰기 API가 꺼져 있으면 읽기 전용 안내
- **명령 기록**: 수락·거부 원장
- **공통**: 로딩·빈 화면·오류 상태, 401·403(권한 회수)·404(쓰기 꺼짐)·409(사유별 문구)·422·503 문구. LIVE 실행 버튼은 없음

| 검증 | 결과 | 근거 |
|---|---|---|
| 플래그 꺼짐(기본): 메뉴 없음, `/admin/crawler`는 404, 기본 routes에 경로 없음 | PASS | Vitest |
| 비로그인 → 로그인 화면, 일반 사용자 → 403 화면·메뉴 없음 | PASS | Vitest, Chrome(실제 API) |
| admin: 메뉴 링크와 콘솔 표시 | PASS | Vitest, Chrome |
| 추가·수정·비활성·삭제·이력, 중복 409·빈 값 차단(API 호출 0) | PASS | Vitest(Mock), Chrome(실제 API: 대소문자만 다른 중복 → 서버 409 `KEYWORD_EXISTS` 문구) |
| 실행 → PENDING, 다시 실행 → `ACTIVE_JOB_EXISTS` 거부 | PASS | Vitest, Chrome(실제 API 201 → 409) |
| 비활성 검색어 실행 거부 | PASS | Vitest |
| 대기 작업 중단, 실패 작업 재시도 | PASS | Vitest, Chrome(Mock, 키보드 Enter) |
| 스케줄 시각 변경 후 복원, 활성 체크박스 비활성 | PASS | Chrome(실제 API PATCH 200 ×2). DB의 `enabled=false`, `mode=fixture`, `03:00` 그대로 |
| 탭 키보드(←/→/Home/End, 선택 탭만 Tab 순서) | PASS | Vitest, Chrome |
| 명령에 `Idempotency-Key`, CSRF, Bearer 헤더 | PASS | Vitest(가짜 fetch), Chrome 응답 기록(명령 4건 모두 키 있음) |
| 403·503 화면, 빈 목록 | PASS | Vitest |
| Raw HTML·URL 비노출 | PASS | Chrome DOM에 `application/ld+json` 없음, 화면에 `http(s)://` 없음(Vitest) |
| 375px 모바일: 페이지 가로 넘침 없음, 표는 자체 스크롤 영역 | PASS | Chrome 스크린샷 |

**로컬 실제 API 전 구간 E2E**(`docs/testing/t156/e2e-real-local-result.json`):

| 구간 | 증빙 |
|---|---|
| 관리자 UI → 관리자 API | UI에서 검색어 생성(POST 201), Fixture 실행(POST `/commands/run` 201, `FIXTURE_JOB_PENDING`), 감사 행위자 `admin:<합성 admin UUID>` |
| Fixture fetch(합성 바이트, 네트워크 차단) → Raw 저장 | raw_artifacts list 1, detail 2. SHA 재검증 2/2 |
| Parse(T153 원장) | VALID 2, lineage 2 |
| 정제 DB(T63 postings) | 합성 공고 2건(`T156 synthetic E2E posting …`), 검색어 발견 2 |
| Job 상태 | PENDING → COMPLETED. checkpoint 전진 |
| 조회(UI ← 관리자 API) | 작업 탭 "완료", 검색어 행 작업 1·발견 공고 2, 명령 기록 탭에 수락·거부 표시 |

- 중간 구간(Fixture fetch부터 정제 DB까지)은 UI 버튼이 아니라 **기존 T154 수동 Fixture 도구를 스크립트로 호출**했습니다.
- 이는 의도한 구조입니다. API는 Worker를 띄우지 않기 때문입니다(T155 설계).

## 8. PostgreSQL / Mock / 실제 API 구분
| 항목 | 결과 |
|---|---|
| FRONTEND_TESTS | PASS. lint 0, tsc OK, Vitest 534 passed / 22 skipped(main 517 + 신규 17), build OK |
| MOCK_VALIDATION | PASS. Vitest와 Chrome Mock 모드, 크롤러 API 네트워크 요청 0 |
| REAL_API_VALIDATION | PASS(로컬 격리 DB). Staging 아님 |
| BROWSER_E2E | PASS(로컬 Chrome, 실제 API 모드와 Mock 모드) |
| POSTGRESQL_TESTS | PASS(로컬 E2E가 일회용 PG 18.6에서 실행). PG 단위 테스트는 T155 PR에 있음 |
| STAGING_VALIDATION | NOT_RUN |
| LIVE_COLLECTION | HOLD |

## 9. CI 결과
PR 댓글에 최신 HEAD 기준으로 기록합니다.

## 10. 잔여 Blocker
1. T155 #233 병합이 먼저입니다. 그 전에는 이 PR의 base가 T155 브랜치입니다.
2. Staging 반영에는 다음이 모두 별도 승인으로 필요합니다.
   - 0011 적용
   - Backend 이미지에 `crawler` 포함
   - 서버 플래그 켜기
   - 프런트 플래그 빌드
3. 검색어별 신규·중복 통계는 서버 읽기 API에 없습니다. 검색어 화면은 작업 수와 발견 공고 수(누적)를, 실행 이력 화면은 실행별 신규·중복 수를 보여 줍니다. 검색어별 신규·중복 집계는 후속 API 과제입니다.
4. Vitest의 jsdom 환경은 실제 스크린리더가 아닙니다. 스크린리더 실기기 확인은 NOT_RUN입니다.

## 11. 후속 작업
- T155 → T156 순서로 병합(Stacked)
- 승인 후 Staging Fixture QA: 같은 E2E 스크립트로 반복 가능
- 검색어별 신규·중복 집계 API(T155 후속)
