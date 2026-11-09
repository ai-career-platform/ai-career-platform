# T46 개인화 추천 목록 UI (Redmine #1588)

- 날짜: 2026-11-09
- 기능 추적: F-017 / 화면 UI-017 맞춤 추천 / 요구사항 FR-ANL-003
- 상태: **PARTIAL** (Mock으로만 검증)
- 브랜치: `task/t46-recommendation-list-ui` (base `origin/main` 2cdd70c)

## 범위
- `/recommendations` 화면(로그인 필요, `RequireAuth` 아래)과 사이드바 `맞춤 추천` 메뉴
- 최근 추천 조회. 추천이 없으면(404) `추천 받기` 버튼이 있는 빈 상태를 보여준다
- `새 추천 받기`(POST)로 다시 계산한다. 실패하면 기존 목록은 그대로 두고 오류 안내만 띄운다
- 카드: 순위, 적합 점수(0~100, 확률이 아니라는 안내 포함, `score=null`이면 `점수 없음`), 추천 이유, 공고 요약(공통 `JobCard` 재사용), 공고 상세 링크, 내 최신 피드백 표시
- 추천 상태 표시: `completed`=맞춤 추천, `fallback`=기준 추천(개인화 아님) 배지와 원인 중립 안내 문구(계약상 fallback은 계산 실패 전반에서 생길 수 있음), `failed`=추천 실패와 다시 추천 받기 버튼
- 접근성: 카드 제목은 `h2`(페이지 `h1` > 카드 `h2` > JobCard `h3`). 점수 숫자는 `aria-hidden`이고 스크린리더에는 `적합 점수 100점 만점에 N점`(공통 `.sr-only`, `src/styles/global.css`)으로 읽힌다. 고용 형태·마감 표시는 `관련 기술`이 아니라 `공고 정보` 목록으로 읽힌다(`JobCard`에 `tagsLabel` prop 추가, tags가 비면 목록을 그리지 않음)
- 계산 기준(`model_code vversion (규칙 기반 등)`)과 생성 시각을 항상 표시한다. "AI의 확정 판단이 아님" 안내 문구를 함께 둔다
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
- Mock: `frontend/src/mocks/recommendations.ts`. `handlers.ts`에서 로그인 토큰을 확인한 뒤 호출한다. 새 추천(POST, completed)은 `feedback`(내 최신 피드백)을 그대로 두고, 관심 없음으로 표시한 공고를 빼고 순위를 다시 매긴다. 테스트는 `setRecommendationMockScenario`로 상태를 바꾼다. 회사와 공고는 모두 가상 데이터다

## 테스트 명령 (frontend/, Node 24)
~~~bash
npm ci
npm run lint
npm test
npm run build
~~~
- 추가 테스트(19개): `src/pages/RecommendationsPage.test.tsx` 12개(로그인 필요 리다이렉트, 401 세션 만료, 목록·h2 제목·스크린리더 점수·공고 정보 목록·점수 의미·근거·계산 기준, 상세 링크, 빈 상태와 생성, 새로고침과 관심 없음 공고 제외·순위 재계산·최신 피드백 유지, fallback 배지와 원인 중립 안내, failed 상태, 조회 오류와 재시도, 새로고침 실패, 필터, 메뉴), `src/components/RecommendationCard.test.tsx` 2개(고용 형태·마감이 `공고 정보` 목록으로 표시, 태그가 없으면 빈 목록 없음), `src/api/recommendations.test.ts` 5개(경로·메서드·Bearer·limit 기본값, 404를 null로 처리, Mock 401·422)
- 결과(Node v24.22.2): `npm ci` 취약점 0건, `npm run lint` PASS, `npm test` 8 files passed·1 skipped / 46 tests passed·6 skipped, `npm run build` PASS

## PARTIAL 사유
선행 일감 T45(추천 실행 API)가 머지되지 않았다. 화면은 OpenAPI 계약과 Mock으로만 검증했고, 실제 Backend·DB와 연결한 검증은 하지 않았다. Mock 성공은 실제 서비스 PASS가 아니다.

## HOLD / 후속
- T45 머지 후 `npm run dev`(VITE_API_MOCK=false)로 실제 API 응답과 다시 검증한다
- 공고 상세 화면 `/job-postings/:id`(UI-012)는 T24 범위다. 지금은 링크만 계약 경로 이름으로 연결되어 있고 NotFound 화면으로 간다
- 추천 설명 모달과 좋아요·관심 없음 버튼은 T48(`renderItemActions` 사용), 피드백 API는 T47
- 프로필 정보 부족 안내(기술·목표 직무 입력 화면 링크)는 해당 화면이 생기면 연결한다
- 브라우저 수동 확인과 화면 캡처는 PR 작성자가 따로 남긴다
