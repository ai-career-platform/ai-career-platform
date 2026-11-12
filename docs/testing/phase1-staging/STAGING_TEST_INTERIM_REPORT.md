# Staging 통합 테스트 중간 보고서 — `PHASE1_SCOPE_PENDING`

> **이후 진행 결과는 [최종 보고서](PHASE1_STAGING_FINAL_REPORT.md)에 있습니다.** 이 문서는 2026-11-12 중간 시점의 기록입니다. F-02 는 #247, F-01 은 #244 로 수정했고(병합 대기), 이후 F-03(T40)·F-04·F-05 를 새로 찾았습니다.

> 작성: 2026-11-12 · 실행 SORNET(Claude Code) · 코디네이터 GPT-Web · PM 문길래
> - 기준 main `c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce` 이며, Staging 실행 SHA 와 같습니다.
> - **Phase 1 대상 확정은 보류 중입니다**(§7). 이 보고서는 대상 확정과 별도로 진행한 **구현 완료 기능의 Staging 읽기 전용 검증** 결과입니다.
> - Staging·DB·설정·Secret 변경은 0건이고, 쓰기 요청(POST·PUT·PATCH·DELETE)도 0건입니다.

## 1. 요약

| 항목 | 결과 |
|---|---|
| 조사 범위 | T13~T156, 144개 |
| 구현 완료(main 병합 PR 있음) | **109** (코드 78 · 문서 18 · 시험 11 · CI 도구 2). 자세한 내용은 [매트릭스](STAGING_IMPLEMENTED_FEATURE_MATRIX.md) |
| Staging 접근 | **HTTP 가능**(게이트웨이 `:18080`), **SSH 불가**(키 인증 거부) |
| DB 연동 | **간접 PASS**(`/health/db`, 공개 카탈로그 DB 조회·정합성). 스키마·Migration 직접 조회는 **BLOCKED** |
| S3 시험 항목(11) | PASS **6** · FAIL **2** · BLOCKED **3** |
| 일감별 기능 검증(144) | PASS 8 · FAIL 1 · BLOCKED 49 · NOT_RUN 5 · N/A 81 |
| 발견 결함 | F-01(수정 PR), F-02(알려진 문제, 승인 필요) + 관찰 3건 |
| 수정 PR | [#244](https://github.com/ai-career-platform/ai-career-platform/pull/244) (Draft, 미병합, Staging 미배포) |

## 2. Staging 환경 (S2-B)

출처: `docs/STAGING.md`, `poc/staging/**`, `.github/workflows/staging-publish.yml` 와 실제 응답입니다. 자격증명은 조회하지도 기록하지도 않았습니다.

| 항목 | 확인 내용 | 확인 방법 |
|---|---|---|
| 호스트 | 사설 IP Ubuntu 호스트(`docs/STAGING.md`). 배포 경로 `/home/kant/ai-career-staging-poc` | 문서 |
| 게이트웨이 URL | `http://<staging-host>:18080` — 내부망에서 HTTP 응답 확인 | 실제 요청 |
| Compose 서비스 | `frontend`(nginx 1.27.5) · `backend`(python 3.12 + uvicorn) · `db`(PostgreSQL, 내부 5432). release overlay 는 이미지 digest 고정 | 문서·저장소 |
| Backend 경로 | `/api/v1/*` → 서비스 API(T13~ 계약, prefix 유지), `/api/*` → PoC Health·크롤러 조회(prefix 제거) | `nginx.conf`, 실제 OpenAPI |
| Backend 이미지 | `poc/staging/backend/Dockerfile.integrated` (`backend/app` + `crawler/` + 훈련 조회 앱, `ENABLE_SERVICE_API=1`) | 저장소 |
| Frontend 이미지 | `poc/staging/frontend` = **PoC 상태 페이지**(`index.html`·`status.js`·`status.css`). `frontend/` React 앱은 **빌드·배포 대상이 아님** | 게시 워크플로·실제 응답 |
| PostgreSQL 연결 | 앱은 private `.env` 의 `POSTGRES_*` 또는 `DATABASE_URL` 을 씀. 크롤러는 별도 DB `ai_career_crawler_training`(`CRAWLER_DB_MODE`) | `poc/staging/backend/main.py`, 문서 |
| DB Migration 상태 | **BLOCKED**(직접 조회 불가). 참고: T120 E5·T150 F4 는 "Staging 0002·0003 미적용·원장 없음, #178 OPEN" 으로 기록 | 기존 Gate 문서 |
| 현재 배포 SHA | `/api/version` = `c7dc2e19…`(main 최신, #240 병합분) | 실제 요청 |
| Health | `/api/health` 200 · `/api/version` 200 · `/api/health/db` 200 | 실제 요청 |
| API 문서 | `/api/openapi.json`(67개 연산) · `/api/docs` 200 | 실제 요청 |
| 테스트 계정 | **제공되지 않음**. 저장소에도 없음 | — |
| SSH | 22번 포트는 열려 있으나 키 인증 거부(비밀번호 필요). 로그·`docker compose ps`·DB 직접 조회 불가 | 실제 시도(BatchMode) |

## 3. 읽기 전용 Staging 시험 결과 (S3)

### 실행 원칙
- 요청은 GET 만 보냈습니다.
- 인증은 토큰 없이, 또는 형식만 맞는 위조 토큰으로만 시도했습니다. 로그인하지 않았습니다.
- 경로 변수에는 합성 UUID(`00000000-…`)만 넣었습니다.
- 다른 프로젝트 포트(80·443·8000)에는 요청하지 않았습니다.

| # | 시험 | 결과 | 근거 |
|---|---|---|---|
| 1 | Health·API 접근 | **PASS** | health·version·health/db 3/3 200. 실행 SHA = main |
| 2 | Backend↔DB 연결 | **PASS** | `/health/db` 200. 공개 카탈로그 5종이 DB 에서 응답(아래 9) |
| 3 | DB Schema 조회 | **BLOCKED** | DB 포트 비공개, SSH·DB 계정 없음 |
| 4 | Migration 상태 | **BLOCKED** | 같은 이유. 원장(`schema_migrations`) 확인 불가 |
| 5 | 공개 조회 API | **PASS** | `consent-policies` 3건, `companies` 20, `job-roles` 30, `skills?q=` 정상, `job-postings` 80, `/api/jobs` 2, `/api/jobs/collected` 33 — 모두 200 |
| 5b | 공개 API 의 OpenAPI 계약 일치 | **FAIL → 수정 PR** | **F-01**: `companies`·`job-postings` 4개 경로가 런타임 OpenAPI 에서 인증 필수로 표시됨(계약은 선택) |
| 6 | 무인증 접근 차단 | **PASS** | 인증 필요 GET **26개 × (무토큰·위조 토큰) = 52건 모두 401**. 공개로 설계된 카탈로그 7개(T148 `PUBLIC_ROUTES`)는 200/404/422 로 정상 |
| 6b | 플래그 꺼진 기능 미노출 | **PASS** | `skills/suggest`(T139)·`me/data-requests`(T142)·`me/job-applications`(T102)·`me/notifications`(T97)·`public/portfolios`(T129)·`me/company-postings`·`admin/crawler/settings`(T155 쓰기) → 404, OpenAPI 에도 없음 |
| 7 | Frontend 페이지·정적 자원 | **PASS** | `/`·`/status.js`·`/status.css` 200. CSP·`X-Frame-Options: DENY`·`nosniff` 적용 |
| 8 | 주요 화면 ↔ Backend API | **FAIL (환경)** | **F-02**: React 앱이 배포되지 않음. `/login`·`/jobs` 404. 화면 일감 27개 Staging 검증 불가 |
| 9 | 기존 데이터 정합성 | **PASS** | 커서 전체 순회 중복 0(직무 30·공고 80·기업 20), 목록↔상세 15/15 일치, 공개 목록에 비게시·만료 공고 0, 공고→기업 16·공고→직무 24 참조 누락 0, 수집 공고 원본 URL 중복 0/33 |
| 10 | 서비스·애플리케이션 로그 | **BLOCKED** | 호스트 접근 필요(SSH) |

- 시험 항목 기준: PASS 6 (1, 2, 5, 6, 7, 9), FAIL 2 (5b, 8), BLOCKED 3 (3, 4, 10). 보조 항목 6b 는 PASS 입니다.
- 요청 수 기준: 약 140건이며, 모두 GET 입니다.

### 실행하지 않은 것 (의도적)
- 로그인, 회원가입, 비밀번호 재설정, 동의·탈퇴, 북마크, 문서 업로드, 매칭·추천 실행, 행동 이벤트 전송 — 모두 쓰기 또는 부작용이 있어 실행하지 않았습니다.
- 인증된 사용자로 하는 조회는 테스트 계정이 없어 BLOCKED 입니다.

## 4. 결과 분류 (S4) — 일감 기준

| 분류 | 기능 | 해당 일감 |
|---|---|---|
| PASS | 8 | T13, T14, T17, T31(공개 정책), T62·T151·T152·T153(수집 공고 조회) |
| FAIL | 1 | T18 (데이터 PASS, OpenAPI 표기 F-01) |
| BLOCKED | 49 | **Frontend 27**(F-02) + **Backend·DB 22**: 인증 조회는 계정 없음(T16, T33, T35, T37, T39, T41, T45, T49, T51, T67, T84, T155), 호스트·DB 필요(T63~T66, T73, T112, T114, T115, T144, T154) |
| NOT_RUN | 5 | T15(로그인), T26·T27(매칭·추천 POST), T72(행동 이벤트 POST), T93(재설정 메일) |
| N/A | 81 | 문서·정책, CI·시험 도구, 플래그 꺼짐 기능(T96, T99, T102, T123, T126, T129, T139, T142), 미병합·미착수 35 |

- 무인증 차단은 별도 축으로 셉니다. PASS 17 일감, NOT_RUN 2(POST 전용) 입니다.
- Mock·CI·로컬 PostgreSQL 결과는 이 표에 넣지 않았습니다.

## 5. 발견 결함·관찰 (S5)

| ID | 심각도 | 내용 | Root Cause | 조치 |
|---|---|---|---|---|
| **F-01** | Low(계약) | 런타임 OpenAPI 가 `GET /companies`, `/companies/{id}`, `/job-postings`, `/job-postings/{id}` 를 **인증 필수**로 표시합니다. 계약 `openapi.yaml` 과 실제 동작은 **인증 선택**입니다. Swagger·생성 클라이언트가 공개 API 에 토큰을 요구하게 됩니다 | T18 라우터에 T17 의 "인증 선택" 표기가 없음. 선택적 `HTTPBearer` 의존성이 bearer 항목만 넣음 | **[#244](https://github.com/ai-career-platform/ai-career-platform/pull/244)**: `{}` 만 덧붙임(동작 변경 없음). 회귀 시험은 수정 전 실패·수정 후 통과. 관련 148 passed |
| **F-02** | High(릴리스) | Staging Frontend 가 PoC 상태 페이지입니다. React 앱(`frontend/`)은 빌드·배포되지 않습니다 | `staging-publish.yml` 의 frontend context 가 `poc/staging/frontend` | **수정 PR 없음.** Auto-CD·Compose 변경이라 승인이 필요합니다. 이미 T90 G8·T150 F3 으로 알려진 문제입니다 |
| O-1 | Low(운영) | `docs/STAGING.md` 에는 `127.0.0.1:18080` 바인딩이라고 되어 있지만, 실제로는 내부망에서 `:18080` 에 접근됩니다 | 서버 설정 또는 문서가 오래됨 | 기록만 함. 호스트 운영자 확인 필요 |
| O-2 | Info | `/api/docs`(Swagger)·`/api/openapi.json` 이 인증 없이 공개됩니다 | Staging 설계(`main.py`) | 기록만 함. 공개 범위는 PM 결정 사항 |
| O-3 | Low | `/api/training`(Backend 가 직접 내보내는 HTML)에는 CSP 헤더가 없습니다. nginx 의 CSP 는 `/` 위치에만 적용됩니다 | `nginx.conf` 의 `/api/` 위치에 CSP 없음 | 기록만 함. Staging 설정 변경이라 승인 필요 |

### 수정 PR 목록

| PR | 결함 | 상태 | CI |
|---|---|---|---|
| [#244](https://github.com/ai-career-platform/ai-career-platform/pull/244) `fix/t18-optional-auth-openapi` | F-01 | Draft, 리뷰 요청(Crasnec), **미병합·Staging 미배포** | PR 댓글에 최신 HEAD 기준으로 기록 |

## 6. 데이터 변경 시험 준비 (S6)

공유 Staging DB 에서는 **실행하지 않습니다**. Staging 안에 검증된 격리 스키마나 테스트 DB 는 없습니다. 대신 이미 검증된 격리 환경이 있습니다.
- CI 의 일회용 PostgreSQL 서비스: Backend tests, Crawler MVP
- 로컬 일회용 PostgreSQL 18.6: T86 `disposable_pg` 도구로 스키마를 지웠다가 다시 만듭니다
- T117 로컬 실제 API 브라우저 환경

| 쓰기 시험 | 관련 일감 | 기존 격리 증빙 | Staging 실행 조건 |
|---|---|---|---|
| 회원가입·로그인·토큰 갱신·로그아웃 | T15, T21 | T86 보안 PG, T117 로컬 실제 API | 전용 테스트 DB 또는 스키마 + 합성 계정 정리 절차 |
| 프로필·목표 직무·기술·경력·프로젝트 수정 | T16, T33, T35, T37 | T35~T40 격리 PG E2E(#147) | 위와 같음 |
| 북마크 추가·삭제 | T39 | 격리 PG E2E | 위와 같음 |
| 동의·탈퇴 요청 | T31, T87 | T87 E2E(격리) | 실제 사용자 영향 없는 합성 계정만 |
| 문서 업로드·삭제·분석 | T49, T51 | T49 보안 E2E(CI) | 저장소 볼륨 분리 필요(T144 평문 저장 F-1 해결 전에는 실제 문서 금지) |
| 매칭·추천 실행 | T26, T27, T41, T45 | 합성 시험(CI) | 실행 기록 행 정리 절차 |
| 행동 이벤트 | T72, T73 | T73 보존·삭제 검증 | 동의 상태 합성 계정 |
| 비밀번호 재설정·메일 인증 | T93 | 로컬 | 메일 발송 차단(공급자 미연결 확인) |
| 관리자 감사·크롤러 설정·명령 | T84, T155 | T148 PG, T155 CI DB | 관리자 합성 계정 + 크롤러 0011 미적용 상태 확인 |
| 크롤러 실행·수집 | T151~T154 | Fixture·CI | **Live HOLD**(외부 사이트 수집 금지) |

**제안**: Staging 쓰기 시험이 필요하면 크롤러에 이미 승인된 방식을 그대로 따릅니다(`docs/STAGING.md` 의 1~4).
1. 같은 PostgreSQL 컨테이너에 **별도 DB** 와 **최소 권한 역할**을 만듭니다.
2. 별도 backend 인스턴스나 설정으로 그 DB 만 가리키게 합니다.
3. 백업 → 시험 → 정리 → 전후 행 수를 대조합니다.

모두 승인 사항이므로 이번에는 실행하지 않았습니다.

## 7. Phase 1 확정에 필요한 정보

1. **원본 관리표**(스프레드시트 또는 Redmine 내보내기). 저장소에는 없습니다.
   - 저장소 TSV 5개는 모두 우선순위 왼쪽 열이 '작업 제목'입니다.
   - GitHub Projects 는 `read:project` 권한이 없어 읽을 수 없습니다.
2. 우선순위 바로 왼쪽 숫자 열의 **열 제목과 정의**. 예시 행 `T138 | … | 1 | P1` 만으로는 이 숫자를 Phase 로 단정할 수 없습니다.
3. 원본 관리표의 행이 T13~T156 전체를 담고 있는지(T151~T156 크롤러 일감 포함 여부)

이 정보가 확보되면 [매트릭스](STAGING_IMPLEMENTED_FEATURE_MATRIX.md)의 `Phase 1` 열을 채웁니다. 그다음 해당 행만 다시 집계합니다.

## 8. 다음 실행 단계

| 순서 | 내용 | 필요한 것 |
|---|---|---|
| 1 | #244 CI 확인 → 리뷰·병합(GPT-Web) → Auto-CD 반영 후 Staging `/api/openapi.json` 재조회로 F-01 종료 | 병합 |
| 2 | 원본 관리표로 Phase 1 열 채우기, 대상 행만 재집계 | 관리표 |
| 3 | 인증 조회 시험(BLOCKED 12 일감): 읽기 전용 **기존** 테스트 계정이 있으면 GET 만 실행 | 계정(비공개 전달) |
| 4 | DB 스키마·Migration 원장·로그 점검(시험 3·4·10): 호스트 운영자가 읽기 전용 명령 실행 또는 SSH 읽기 권한 | 호스트 접근 |
| 5 | F-02: React 앱 Staging 배포 방안(게시 워크플로·이미지) 결정 → 이후 화면 일감 27개 Staging E2E | PM 승인(Auto-CD 변경) |
| 6 | 쓰기 시험: §6 격리 DB 방식 승인 후 실행 | PM·DB 담당 승인 |

```text
STAGING_HTTP_ACCESS=YES
STAGING_SSH_ACCESS=BLOCKED
STAGING_DB_DIRECT=BLOCKED
STAGING_DEPLOYED_SHA=c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce
IMPLEMENTED_TASKS=109/144
S3_PASS=6 S3_FAIL=2 S3_BLOCKED=3
WRITE_REQUESTS_SENT=0
STAGING_CHANGED=NO
SHARED_DB_CHANGED=NO
FIX_PRS=#244
PHASE1_SCOPE=PENDING
```
