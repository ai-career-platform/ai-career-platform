# T48 추천 설명·피드백 UI (Redmine #1590)

- 날짜: 2026-11-09
- 기능 추적: F-018 / 화면 UI-017 맞춤 추천 / 요구사항 FR-ANL-003, FR-ANL-004
- 상태: **PARTIAL** (Mock으로만 검증)
- 브랜치: `task/t48-recommendation-feedback-ui` (T46 `task/t46-recommendation-list-ui` b61b7e0 위에서 작업, T46 base `origin/main` 2cdd70c)
- 선행: T20(공통 UI, 머지됨), T46(추천 목록 UI, 미머지), T47(피드백 API, 미머지), T45(추천 실행 API, 미머지)

## 범위
- 추천 카드마다 `추천 설명 보기` 버튼과 피드백 버튼을 붙인다. T46의 확장 지점 `renderItemActions`를 `routes.tsx`에서 연결했다
- 추천 설명 대화상자 (`RecommendationExplanationDialog`)
  - 추천 이유(fallback이면 표시 이유), 추천 상태, 계산 기준(`model_code vversion (종류)`), 생성 시각, 적합 점수(없으면 `점수 없음`)를 보여준다. 점수가 확률이 아니라는 안내를 함께 둔다
  - 항상 "참고용, AI의 확정 판단이 아님" 안내를 보여준다. 기준 추천(fallback)이면 개인화가 아니라는 안내를 추가한다
  - 부족 역량: `RecommendationItem` 계약에 항목이 없다. 데이터를 지어내지 않고 `부족 역량 정보 없음 — … 추후 제공 예정`으로 표시한다
  - 접근성: `role="dialog"`, `aria-modal`, `aria-labelledby`(제목), `aria-describedby`(안내 문구). 열리면 닫기 버튼으로 초점이 이동하고, Tab과 Shift+Tab은 대화상자 안에서만 돈다. Esc, 닫기 버튼, 바깥 클릭으로 닫히고, 닫히면 연 버튼으로 초점이 돌아온다
- 피드백 버튼 (`RecommendationFeedbackActions`)
  - `관심 있음`(liked)과 `관심 없음`(not_interested)은 토글 버튼이며 `aria-pressed`로 현재 값을 나타낸다. 처음 값은 `item.feedback`(이전 피드백)이다
  - 정정: 다른 값을 누르면 바꾼다. 눌린 버튼을 다시 누르거나 `피드백 취소`를 누르면 `cleared`를 보낸다. `피드백 취소`는 피드백이 있을 때만 보인다
  - 중복 전송 방지: 저장 중에는 버튼을 비활성화하고 `aria-busy`를 켠다. 상태가 갱신되기 전에 연달아 눌러도 ref로 한 번만 보낸다
  - 저장 후 `GET /recommendation-runs/{id}`로 같은 추천을 다시 조회해 저장된 상태를 보여준다. 재조회만 실패하면 저장 응답(201)으로 화면을 맞춘다. 그 사이 새 추천을 받았다면 이전 추천으로 덮어쓰지 않는다(`RecommendationsPage.applyRunChange`)
  - 저장 실패: `role="alert"` 오류 안내와 `다시 시도` 버튼을 보여준다. 기존 상태는 그대로 둔다. 401이면 기존 AuthContext 흐름에 따라 로그인 화면으로 보낸다
  - 안내 문구: `피드백은 내 추천 개선에만 사용돼요.` 피드백이 기업이나 고용주에게 간다는 표현은 쓰지 않는다
- 문구 정리: T46의 `좋아요`를 계약 값 이름에 맞춰 `관심 있음`으로 바꿨다(카드 상태, 필터 칩). 공통 문구는 `components/recommendationLabels.ts`에 모았다

## 계약 매핑 (docs/api/openapi.yaml)
| 화면 동작 | API | 처리 |
|---|---|---|
| 관심 있음 / 관심 없음 / 피드백 취소 | `POST /api/v1/recommendation-feedback` `{recommendation_run_id, job_posting_id, feedback}` | 201 `RecommendationFeedback`. 401 로그인 화면 / 404·422·5xx 오류 안내와 다시 시도 |
| 저장 후 상태 재조회 | `GET /api/v1/recommendation-runs/{recommendation_run_id}` | 200 결과로 목록 교체. 실패하면 저장 응답으로 해당 카드만 반영 |
| 이전 피드백 표시 | `RecommendationItem.feedback` (`liked / not_interested / null`) | `aria-pressed`, 카드의 `… 표시함` 표시 |
| 설명 | `RecommendationItem.reason`, `score`, `RecommendationRun.status·model_version·generated_at` | 대화상자. 부족 역량 필드는 계약에 없음 |

- 타입·함수: `frontend/src/api/recommendations.ts` (`RecommendationFeedbackInput`, `RecommendationFeedback`, `RecommendationFeedbackChoice`, `createRecommendationFeedback`, `applyFeedbackToRun`)
- DB 대응: D07 `recommendation_feedback`(추가만 하는 이력, 공고별 최신 행이 현재 값, `cleared`는 조회 시 null), D06 `recommendation_items.reason/score`, D05 `recommendation_runs.status/model_version_id/generated_at`
- Mock (`frontend/src/mocks/recommendations.ts`): 사용자별·공고별 최신 피드백을 메모리에 둔다. T47 규칙을 따른다. 알 수 없는 키·잘못된 enum·`recommendation_run_id: null`이면 422, 내 추천에 없는 공고나 실행이면 404, 같은 값은 멱등이다. 다음 추천(POST)에서는 `not_interested` 공고를 뺀다. 시나리오 `feedback: saved|error|unauthorized`, `runById: ok|error`. 호출 기록은 `recommendationMockLog`에 남는다. 데이터는 모두 가상이다

## 테스트 명령 (frontend/, Node 24)
~~~bash
npm ci
npm run lint
npm test
npm run build
~~~
- 추가 테스트: `src/components/RecommendationFeedbackActions.test.tsx` 14개
  - 피드백 9개: 이전 피드백 표시, 저장 본문·중복 전송 방지·재조회 순서, 정정과 취소, 토글 해제, 오류와 다시 시도, 재조회 실패 보정, not_interested의 다음 추천 제외, 401, 기업 제공 표현 없음
  - 대화상자 5개: role·label·description·초점 이동·부족 역량 없음 상태, Esc와 초점 복귀, Tab 가두기, 닫기 버튼과 바깥 클릭, fallback 표시
- `src/api/recommendations.test.ts`에 3개 추가: POST 경로·본문·헤더, `applyFeedbackToRun`, Mock 401·422·404·멱등
- T46 필터 테스트는 `관심 있음` 문구에 맞게 고쳤다

## PARTIAL 사유
선행 일감 T45(추천 실행 API)가 머지되지 않았다. T46과 T47도 아직 머지 전이다. 화면은 OpenAPI 계약과 Mock으로만 검증했고, 실제 Backend·DB와 연결한 저장·재조회는 확인하지 않았다. Mock 성공은 실제 서비스 PASS가 아니다.

## HOLD / 후속
- T45·T47 머지 후 `VITE_API_MOCK=false`로 실제 API에서 저장 → 재조회 흐름을 다시 검증한다(DoD "저장 후 상태 재조회"의 실 연동 증빙)
- 부족 역량: 추천 항목에 부족 역량 필드가 생기거나 `GET /skill-gaps` 결과와 연결하는 방식이 계약에 정해지면 "추후 제공" 상태를 실제 목록으로 바꾼다. 계약 변경 제안은 T06 절차를 따른다
- 추적표(F-018)는 `UI-018 추천 설명`과 옛 경로 `POST /recommendations/{id}/feedback`을 적고 있다. 현재 계약 v0.2(`POST /recommendation-feedback`, 화면 UI-017)을 따랐으며, 별도 UI-018 화면은 만들지 않고 UI-017 안의 대화상자로 구현했다
- 브라우저 수동 확인, 스크린리더 확인, 화면 캡처는 PR 작성자가 따로 남긴다
