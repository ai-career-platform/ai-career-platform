# T24 — 기업·채용공고 탐색

상태: **PARTIAL / 검토 요청**. 경로 `/job-postings`, Redmine #1519.

## 화면이 하는 일 (모두 T18 정식 API)

| 기능 | API | 비고 |
|---|---|---|
| 공고 목록·검색 | `GET /v1/job-postings?q=&limit=20&cursor=` | 서버가 총 개수를 주지 않아 "N페이지 · M건 표시"로 범위를 밝힘 |
| 기업·직무 필터 | `company_id`, `job_role_id` | 선택지는 `/v1/companies`, `/v1/job-roles`에서 최대 100건. 더 있으면 안내 |
| 공고 상태 | `include_closed` | "모집 중만 / 마감 포함". **마감만** 보는 필터는 API에 없어 만들지 않음 |
| 정렬 | `sort=-published_at` / `expires_at` | 최신 등록순 / 마감 임박순 |
| 공고 상세·요구 기술 | `GET /v1/job-postings/{id}` | 필수/우대, 요구 수준(없으면 "미등록") |
| 기업 소개 | `GET /v1/companies/{id}` | 소개·진행 중 공고 수·웹사이트·데이터 출처(`source`) |

- 검색·기업·직무·상태·정렬 조건은 URL(`?q=&company=&role=&closed=1&order=expires`)에 남아 새로고침·공유 시 유지된다. URL의 ID가 UUID 모양이 아니면 버린다.
- 모집 상태·게시일·마감일은 API 값 그대로 쓰고, 없으면 "미등록/미정"으로 표시한다(수집 시각 등으로 추정하지 않음).
- 외부 링크(공고 원문, 기업 웹사이트)는 `http/https`이고 계정 정보가 없는 주소만 열며 `noopener noreferrer`와 호스트 이름을 함께 보여 준다. 원문 링크가 없으면 없다고 표시한다.
- 기업 `source`가 `synthetic_seed`이면 "합성 테스트 데이터 · 실제 채용 정보 아님"을 표시한다.
- 디자인은 T20 공통 컴포넌트(`TextField`, `Button`, `FilterChips`, `StatePanel`)와 원래 시안의 히어로·기업 카드·공고 카드·상세 레이아웃을 쓴다. 로딩·빈 결과·오류·재시도와 늦게 도착한 이전 응답 무시를 목록·선택지·상세·기업 소개에 각각 적용한다.

## 이 PR에 넣지 않은 것

- **별도 수집 공고(`/api/jobs/collected`)**: 정식 DB가 아닌 학습용 수집 저장소이고, `docs/data/SOURCE_REGISTRY.md` 기준 잡코리아 실수집·서비스 표시는 HOLD다. 정식 목록에 섞지 않는다. 실제 공고는 Backend/크롤러 담당이 정식 `career.job_postings`에 적재하면 이 화면에 그대로 나타난다.
- **관심 공고 저장(북마크)**: T39/T40 범위.

## 실행 및 검증

`frontend`에서 `npm ci`, `npm run lint`, `npx tsc -b`, `npm test`, `npm run build`. `npm run dev`는 같은 Origin `/api`를 쓰며 `DEV_API_PROXY_TARGET`(예: 허용된 Staging)으로 대상 서버를 고른다. 비밀값을 VITE 변수에 넣지 않는다.

단위 테스트(가상 응답)는 목록 표기·필터·URL 복원·잘못된 ID·커서·기업 카드·상세·안전하지 않은 링크 차단·누락 값·오류 재시도·늦은 응답 무시를 검사한다. Staging 읽기 확인 결과는 PR 설명에 적는다. 현재 Staging 정식 공고는 합성 Seed 데이터다.

메뉴와 라우트는 T23 PR과 다른 위치에 넣어 두 PR이 어떤 순서로 병합되어도 충돌하지 않게 했다. 공유 DB·배포 변경은 없다.
