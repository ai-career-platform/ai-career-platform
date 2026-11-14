# T100 — 채용공고 고급 검색·필터 UX 검증

> 상태: **FRONTEND_MOCK=PASS / REAL_API_INTEGRATION=HOLD** — T98 계약 미승인(#201), T99 서버는 기능 플래그 기본 꺼짐(#202).
> 이 브랜치는 T99 → T98 위에 쌓여 있고, main Frontend CI 복구 커밋(#199)을 포함합니다. 병합 순서: #199 → #201 → #202 → 이 PR.
> 2026-11-11 · F-012 · 화면 UI-012 · 선행: T24(병합), T98·T99(미병합)

## 1. 무엇을 바꿨나

| 파일 | 내용 |
|---|---|
| `frontend/src/pages/JobPostingsPage.tsx` | `advanced` 모드 추가: 상세 조건(고용형태 체크, 근무 지역 17개(최대 5), 게시일), 검색어 = 제목·기업명. 조건을 바꿀 때마다 기록(push) → 뒤로가기. 초기화는 정렬 유지. **꺼지면 T24 그대로**(기존 시험 23건 무변경 통과) |
| `frontend/src/pages/jobSearchUrl.ts` | URL ↔ 상태: 모르는 키·값 버림, 중복·순서 무관, 상한 자르기, 기본값·cursor 생략, 예전 링크 이름(company·role·closed·order) 읽기 |
| `frontend/src/api/jobSearch.ts` | T98 계약 타입·상수, HTTP Adapter(준비만, 미연결) |
| `frontend/src/mocks/jobSearch.ts` | T98 §3~§5 를 흉내 낸 Mock(422, 기업명 검색, `%`·`_` 문자 그대로, 지역 별칭, 안정 정렬, 조건에 묶인 cursor) |
| `frontend/src/api/http.ts` | `buildQuery`가 배열을 키 반복으로 보냄(`region=a&region=b`) — 기존 호출 영향 없음 |
| `frontend/src/config/env.ts`, `routes.tsx` | `VITE_API_MOCK=true` + `VITE_JOB_SEARCH_ADVANCED_UI=true`일 때만 `advanced` |
| 시험 | `JobSearchAdvanced.test.tsx`(38), T89 접근성 회귀에서 `/job-postings`를 고급 모드로 점검 |

## 2. 필터 → URL → API → 결과 일치

같은 기준으로 세 곳을 검증합니다.
- 기준: T98 수용 사례 JSON (손으로 쓴 기대값)
- 실제 서버(T99 PG 시험)
- 이 화면의 Mock (이 PR의 시험)

화면 시험에서는 체크·검색을 할 때 URL과 API 호출 인자, 화면 결과가 모두 T98 기대값과 같아야 합니다(예: A12 = 검색어 + 정규직 + 서울·경기).

## 3. 시험 결과 (로컬: Windows 11 · Node 24, **Mock PASS이며 실제 API PASS 아님**)

| 범주 | 시험 | 결과 |
|---|---|---|
| URL | 왕복·순서·중복 무관, 기본값 생략, 이메일·사용자 ID·cursor·잘못된 값 제거, 지역 5개 상한, 예전 링크, 배열 쿼리 | PASS |
| Mock = T98 | 수용 16건, 거부 9건(422), 페이지 무중복, cursor 조건 묶음(400), 지역 별칭 = T98 §4 문서 표 | PASS |
| 조합 | 고용형태 + 지역 2곳 + 검색어 → URL·API 인자·결과가 A12와 일치 | PASS |
| 공유·뒤로가기 | 공유 URL로 같은 결과, 뒤로가기 2번 → 이전 조건·체크 상태·결과 복원 | PASS |
| 0건·초기화 | 빈 상태 + "검색 조건 초기화" → 필터 제거·정렬 유지·초기화 버튼 비활성 | PASS |
| 잘못된 URL | 모르는 값은 버리고 API에 보내지 않음, 사용자에게 422 표시 없음 | PASS |
| 오류 | 조회 실패 → alert + 다시 시도 → 복구 | PASS |
| 페이지 | 조건이 바뀌면 1페이지부터 | PASS |
| 플래그 꺼짐 | T24 화면, 상세 조건 없음, T18 목록 API 호출 | PASS |
| 접근성(T89 자동 규칙) | `/job-postings` 고급 모드 | PASS |
| 실제 Chrome(Mock dev 서버) | 1280px·375px 가로 넘침 없음, 키보드 Space로 정규직 선택 → 20→4건, 서울 추가 → 1건, 뒤로가기 → 이전 URL·체크 복원, 공유 URL 새 창 → 같은 1건, 공고 API 네트워크 요청 0건 | PASS |

- `JobSearchAdvanced.test.tsx` **38 PASS**, 기존 `JobPostingsPage.test.tsx` 23 PASS(무변경), 전체 Vitest **445 passed / 22 skipped**, lint 0, tsc 0, build 성공
- 스크린리더 실제 낭독·Firefox·Safari: **NOT_RUN**

## 4. 한계 / HOLD

1. 실제 API 연결: **연결됨(아래 §5)**. 운영·Staging 활성화는 여전히 T98 승인 → 서버 `JOB_SEARCH_ADVANCED=true` + `VITE_JOB_SEARCH_ADVANCED_UI=true` 순서(둘 다 기본 꺼짐)
2. 기업·직무는 화면에서 1개씩만 고릅니다(계약은 최대 10개). 공유 URL에 여러 개가 있으면 API에는 모두 보내지만 선택 상자는 첫 값만 보입니다.
3. Mock 모드 개발 서버에는 기업·직무 목록 Mock이 없어 그 영역은 기존과 같이 오류를 표시합니다(T24 기존 동작).
4. 지역은 근무지 표기 기준 추정(화면에 안내). 기술·경력·연봉 필터는 데이터가 없어 제공하지 않음(T98 §2)

## 5. 실제 API 연결 (2026-11-14, PM 결정)

| 항목 | 내용 |
|---|---|
| 플래그 | `env.jobSearchAdvancedUi = VITE_JOB_SEARCH_ADVANCED_UI === 'true'` (Mock 조건 제거, **기본 꺼짐**). 서버 `JOB_SEARCH_ADVANCED`도 켜야 고급 조건이 적용됨 |
| 데이터 | Mock 모드(`VITE_API_MOCK=true`)면 Mock Adapter, 아니면 `createApi(http).jobSearch`(= `createHttpJobSearchService`, 앱의 같은 HttpClient·로그인 토큰) |
| 계약 대조 | 쿼리 이름(`q`, `company_id`·`job_role_id`·`employment_type`·`region` 키 반복, `posted_within`, `include_closed`, `sort`, `limit`, `cursor`), 값(정렬 `-published_at`/`expires_at`, 고용형태 4종, 지역 17개, 기간 4종), 응답(`JobPostingPage` = `items` + `next_cursor`)이 `backend/app/routers/job_postings.py`·`schemas/job_postings.py` 와 일치. 불일치 없음 |
| 서버 플래그 꺼짐 | T18 목록이 응답(고급 조건은 무시, 다중 company_id·job_role_id 는 하나만 적용). 화면은 그대로 표시, 오류는 기존 오류·빈 상태 |
| 공개 범위 | 게시 중·만료 전 공고만(초안 제외)은 서버가 정함. 프런트는 바꾸지 않음 |
| 시험 | 실제 HttpClient 경로 3건(쿼리·정렬, 커서 페이지 이동·조건 변경 시 1페이지, 서버 플래그 꺼짐·422 오류 복구), 플래그 가드 시험을 새 규칙으로 갱신 |
