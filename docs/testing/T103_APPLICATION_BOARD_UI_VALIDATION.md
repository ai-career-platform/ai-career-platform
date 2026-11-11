# T103 — 개인 지원 현황 보드 UI 검증

> 상태: **FRONTEND_MOCK=PASS / REAL_API_INTEGRATION=HOLD** — T101 계약 미승인(#204), T102 API는 기능 플래그 뒤(#205, 기본 꺼짐).
> 이 브랜치는 T102 → T101 위에 쌓여 있고 main Frontend CI 복구 커밋(#199)을 포함합니다. 병합 순서: #199 → #204 → #205 → 이 PR.
> 2026-11-11 · F-012·F-013 · 화면 UI-N05(제안) · 선행: T20·T24 병합, T102 미병합

## 1. 화면 `/me/applications`

| 요소 | 내용 |
|---|---|
| 안내 | "**내가 기록한 상태입니다.** 기업의 공식 결과가 아니며, 채용사·채용 사이트의 실제 지원 현황과 자동으로 연결되지 않습니다." + Mock 표시 |
| 보드 | 7단계 열(관심~지원 취소), 열마다 건수. 좁은 화면에서는 세로로 쌓임 |
| 표 | 같은 기록을 표로(공고·기업·단계·지원일·다음 일정·공고 상태), 넓으면 표 안에서만 가로 스크롤 |
| 단계 변경 | 카드의 "단계" 선택 상자에 **허용된 단계만**(T101 §4). 끌어 놓기 대신 선택 상자라 키보드·스크린리더로도 같은 동작 |
| 저장 | 바꾸면 바로 반영(낙관적). 실패하면 원래 단계로 되돌리고 alert. 409(다른 탭에서 먼저 바뀜·허용 안 됨)면 최신 내용을 다시 불러옴 |
| 공고 상태 | "마감된 공고", "공고 정보 없음"(삭제됨) 글자 배지 — 색만 쓰지 않음 |
| 메모 | 펼치기, 2000자, "주민등록번호·연락처·건강 정보 같은 민감한 내용은 적지 마세요" 안내 |
| 삭제 | 확인 대화상자(취소·삭제), 즉시 삭제 안내 |
| 빈 상태 | "아직 기록한 지원이 없습니다" + 채용공고 탐색 링크 |
| 플래그 | `VITE_API_MOCK=true` + `VITE_APPLICATIONS_UI=true`일 때만 경로·메뉴. 로그인 사용자만, 사용자 ID별 Mock 저장소 |

파일: `frontend/src/api/jobApplications.ts`(타입·이동 표·HTTP Adapter 준비), `frontend/src/mocks/jobApplications.ts`, `frontend/src/applications/*`, `frontend/src/pages/ApplicationsBoardPage.{tsx,css}`, `routes.tsx`, `layouts/AppLayout.tsx`, `config/env.ts`, 시험 `ApplicationsBoard.test.tsx`, T89 접근성 회귀에 경로 추가.

## 2. 시험 결과 (로컬: Windows 11 · Node 24, **Mock PASS이며 실제 API PASS 아님**)

| 범주 | 시험 | 결과 |
|---|---|---|
| 플래그·접근 | 꺼짐: 로그인해도 404·메뉴 없음, 기본 경로에 없음, Mock 모드 필수, Provider가 HTTP를 쓰지 않음, 비로그인 → 로그인 | PASS |
| 보드 | 공식 결과 아님 안내, 7열 건수, 마감·공고 정보 없음 배지, 선택지가 허용 단계뿐(관심 카드 4개, 불합격 카드 2개) | PASS |
| 상태 변경 | 관심 → 지원 완료: 열 이동, 상태 알림, 저장소 stage·version 2·지원일 채움 | PASS |
| 저장 실패 롤백 | 원래 열로 복귀, alert, 저장소 변화 없음 | PASS |
| 동시 수정(409) | 다른 탭이 먼저 바꾼 뒤 오래된 화면에서 변경 → alert + 최신 상태로 갱신, 덮어쓰지 않음 | PASS |
| 메모·삭제 | 메모 저장, 삭제 확인(취소하면 유지, 삭제하면 제거) | PASS |
| 표 보기 | 같은 6건 + 머리글, 마감 배지 | PASS |
| **사용자 격리** | 사용자 A의 변경이 관리자 B 보드에 영향 없음, B가 A의 기록 수정·삭제 → 404 | PASS |
| 빈 상태·오류 | 빈 상태 + 공고 탐색 링크, 조회 오류 alert + 다시 시도 | PASS |
| 계약 일치 | 화면 이동 표 = T101 §4 문서 표, Mock이 금지 이동·오래된 version을 409로 거부, 준비 단계로 돌아가면 지원일 지움 | PASS |
| 접근성(T89 자동 규칙) | `/me/applications` | PASS |
| 실제 Chrome(Mock dev 서버) | 1280px·375px 가로 넘침 없음(표는 자체 스크롤), 키보드 포커스 후 선택으로 "지원 완료 3건" 열로 이동, 표 7행, 지원 현황 API 요청 0건 | PASS |

- `ApplicationsBoard.test.tsx` **13 PASS**, T89 접근성 회귀 36 PASS(1건 추가), 전체 Vitest **421 passed / 22 skipped**, lint 0, tsc 0, build 성공
- 스크린리더 실제 낭독·Firefox·Safari: **NOT_RUN**

## 3. HOLD / 후속

1. 실제 API 연결: T101 승인 → 정식 migration → T102 플래그 → Provider에서 `createHttpJobApplicationService` 선택
2. 공고 화면에서 "지원 현황에 추가" 버튼(생성 흐름) — T24/T100 화면 변경이라 별도 일감
3. 화면 ID UI-N05 등록, 다음 일정 알림(T96 연계)은 T101 D-6 승인 후
4. 한 번에 100건까지만 불러옴(서버 limit 상한) — 기록이 많으면 페이지 이동 필요
