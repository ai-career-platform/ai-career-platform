# T46 개인화 추천 목록 UI (Redmine #1588)

- 날짜: 2026-11-09
- 기능 추적: F-017 / 화면 UI-017 맞춤 추천 / 요구사항 FR-ANL-003
- 상태: **PARTIAL** (T45 머지 반영. 실제 Backend·DB 연결 화면 검증과 CI는 아직)
- 브랜치: `task/t46-recommendation-list-ui` (base `origin/main` 2cdd70c, 이후 `origin/main` d0d18e1 merge로 T45 #156 반영)

## 범위
- `/recommendations` 화면(로그인 필요, `RequireAuth` 아래)과 사이드바 `맞춤 추천` 메뉴
- 최근 추천 조회. 추천이 없으면(404) `추천 받기` 버튼이 있는 빈 상태를 보여준다
- `새 추천 받기`(POST)로 다시 계산한다. 실패하면 기존 목록은 그대로 두고 오류 안내만 띄운다
- 카드: 순위, 적합 점수(0~100, 확률이 아니라는 안내 포함, `score=null`이면 `점수 없음`), 추천 이유, 공고 요약(공통 `JobCard` 재사용), 공고 상세 링크, 내 최신 피드백 표시
- 추천 상태 표시: `completed`=맞춤 추천, `fallback`=기준 추천(개인화 아님) 배지와 원인 중립 안내 문구(계약상 fallback은 계산 실패 전반에서 생길 수 있음), `failed`=추천 실패와 다시 추천 받기 버튼
- 접근성: 카드 제목은 `h2`(페이지 `h1` > 카드 `h2` > JobCard `h3`). 점수 숫자는 `aria-hidden`이고 스크린리더에는 `적합 점수 100점 만점에 N점`(공통 `.sr-only`, `src/styles/global.css`)으로 읽힌다. 고용 형태·마감 표시는 `관련 기술`이 아니라 `공고 정보` 목록으로 읽힌다(`JobCard`에 `tagsLabel` prop 추가, tags가 비면 목록을 그리지 않음)
- 계산 기준(`model_code · version (규칙 기반 등)`, T45 실제 값은 `skill_overlap_baseline · skill-overlap-draft-v2 (규칙 기반)`)과 생성 시각을 항상 표시한다. "AI의 확정 판단이 아님" 안내 문구를 함께 둔다
- 클라이언트 필터: 피드백 상태(전체/관심 있음/피드백 없음/관심 없음. T48에서 `좋아요`를 `관심 있음`으로 바꿈)
- 확장 지점: `RecommendationCard`의 `actions` 슬롯과 `RecommendationsPage`의 `renderItemActions(item, run, onRunChange)`. T48에서 설명 모달과 피드백 버튼을 여기에 연결한다

## 계약 매핑 (docs/api/openapi.yaml)
| 화면 동작 | API | 처리 |
|---|---|---|
| 첫 진입·다시 시도 | `GET /api/v1/recommendation-runs/latest` | 200 목록 / 404 빈 상태 / 401 로그인 화면 / 그 외 오류 상태 |
| 추천 받기·새 추천 받기 | `POST /api/v1/recommendation-runs` `{limit: 20}` | 201 결과로 교체. 422·5xx는 오류 안내 |
| (확장용 함수) | `GET /api/v1/recommendation-runs/{recommendation_run_id}` | `getRecommendationRun` |

- 타입: `frontend/src/api/recommendations.ts` (`RecommendationRun`, `RecommendationItem`, `JobPostingSummary`, `ModelVersionRef`)
- DB 대응: D05 `recommendation_runs`(status, generated_at, model_version), D06 `recommendation_items`(rank, score, reason), D07 `recommendation_feedback`(카드의 최신 피드백 표시)
- Mock: `frontend/src/mocks/recommendations.ts`. T45 머지 코드(`backend/app/services|repositories|schemas/recommendation_runs.py`)와 같은 모양으로 맞췄다:
  completed·fallback 모두 `model_version = skill_overlap_baseline / skill-overlap-draft-v2 (rule)`, completed reason은 T27 문구(`요구 기술 N개 중 M개가 일치합니다.`) + 목표 직무면 ` 목표 직무에 포함됩니다.`,
  fallback reason은 `보유 기술 또는 공고의 요구 기술 정보가 부족하여 최신 공고를 표시합니다.`(score=null), 공개 공고가 없으면 fallback + 빈 items(`create: 'fallback_empty'`), DB 오류 503 `DEPENDENCY_UNAVAILABLE`(`create: 'unavailable'`). `handlers.ts`에서 로그인 토큰을 확인한 뒤 호출한다. 새 추천(POST, completed)은 `feedback`(내 최신 피드백)을 그대로 두고, 관심 없음으로 표시한 공고를 빼고 순위를 다시 매긴다. 테스트는 `setRecommendationMockScenario`로 상태를 바꾼다. 회사와 공고는 모두 가상 데이터다

## T45 머지 코드와 계약 비교 (2026-11-09, d0d18e1)
- 경로·메서드·응답 DTO(`RecommendationRun`, `RecommendationItem`, `ModelVersionRef`, `JobPostingSummary`)는 openapi.yaml과 T45 코드가 같다. Frontend 타입 변경 없음.
- T45 차이(계약 위반 아님, 화면 영향만 기록):
  - `status=failed`는 계약 enum에만 있고 T45는 만들지 않는다(completed/fallback만). 화면의 failed 처리는 방어용으로 유지.
  - fallback도 같은 규칙 버전 `skill_overlap_baseline`을 돌려준다(계약 예시 `match_rule v1`과 다름). 별도 fallback 모델 코드 없음.
  - POST는 계약에 없는 503(`DEPENDENCY_UNAVAILABLE`)도 돌려줄 수 있다(router `error_responses(401, 503)`). 화면은 일반 오류 안내로 처리.
  - GET은 이후 비공개·삭제된 공고 항목을 빼므로 `rank`가 연속이 아닐 수 있다. 화면은 받은 `rank`를 그대로 표시.
  - 201 `Location` 헤더는 화면에서 쓰지 않는다.

## 테스트 명령 (frontend/, Node 24)
~~~bash
npm ci
npm run lint
npm test
npm run build
~~~
- 추가 테스트(21개): `src/pages/RecommendationsPage.test.tsx` 13개(로그인 필요 리다이렉트, 401 세션 만료, 목록·h2 제목·스크린리더 점수·공고 정보 목록·점수 의미·근거·계산 기준, 상세 링크, 빈 상태와 생성, 새로고침과 관심 없음 공고 제외·순위 재계산·최신 피드백 유지, fallback 배지와 원인 중립 안내, T45 fallback 문구와 공개 공고 없음 fallback 빈 상태, failed 상태, 조회 오류와 재시도, 새로고침 실패, 필터, 메뉴), `src/components/RecommendationCard.test.tsx` 2개, `src/api/recommendations.test.ts` 6개(경로·메서드·Bearer·limit 기본값, 404를 null로 처리, Mock 401·422, T45 응답 모양: 같은 규칙 버전·fallback 문구·빈 fallback·503)
- 결과(Node v24.22.2, merge 후): `npm ci` 취약점 0건, `npm run lint` PASS, `npm test` 15 files passed·2 skipped / 105 tests passed·10 skipped, `npm run build` PASS
- Backend(merge 후, Backend 코드 변경 없음): `cd backend && python -m pytest -q` 338 passed, 125 skipped, 1 warning(로컬 PostgreSQL 없음으로 DB E2E skip)

## PARTIAL 사유
T45(#156)가 main에 머지되어 선행 일감 블로커는 풀렸고, API 타입·Mock을 T45 실제 코드에 맞췄다. 다만 화면을 실제 Backend·DB(`VITE_API_MOCK=false`)와 연결한 검증, Staging 확인, 이 merge 커밋의 GitHub CI 실행은 아직 하지 않았다. Mock 성공은 실제 서비스 PASS가 아니다.

## HOLD / 후속
- 로컬 Backend + 격리 DB로 `npm run dev`(VITE_API_MOCK=false) 화면 확인(Staging DB 사용 금지)
- 공고 상세 화면 `/job-postings/:id`(UI-012): main의 T24는 `/job-postings` 목록 안 상세 패널만 있고 `:id` 라우트가 없다. 카드 링크는 계약 경로 이름으로 두었고 지금은 NotFound 화면으로 간다(T24 후속에서 라우트 추가 필요)
- 추천 설명 모달과 좋아요·관심 없음 버튼은 T48(`renderItemActions` 사용), 피드백 API는 T47
- 프로필 정보 부족 안내: main에 `/me/skills`, `/me/target-roles` 화면이 생겼으므로 fallback 안내에 링크 연결은 후속으로 둔다
- 브라우저 수동 확인과 화면 캡처는 PR 작성자가 따로 남긴다
