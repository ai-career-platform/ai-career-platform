# T97 — 알림함·수신 설정 화면 검증

> 상태: **FRONTEND_MOCK=PASS / REAL_API_INTEGRATION=HOLD** — 알림함 API 계약이 없고, 수신 설정 API는 T95 제안 단계이며, T96(#198)은 API 경로를 만들지 않았습니다.
> 기준 main `ceee31d` + [#199](https://github.com/ai-career-platform/ai-career-platform/pull/199)(main Frontend CI 복구) · 2026-11-11 · 기능 F-003, F-005
> 선행: T20·T21(병합) · T95(병합, PROPOSED) · T96(#198 미병합, API 없음)

## 1. 화면

| 화면 | 경로 | 내용 |
|---|---|---|
| UI-N04 알림함(신규 ID 제안) | `/me/notifications` | 최신 순 목록, 안 읽음 표시(굵은 제목 + "안 읽음" 글자 + 왼쪽 띠 — 색만 쓰지 않음), 한 건·전체 읽음 처리, 빈 상태·오류·다시 시도 |
| UI-005 알림 수신 설정 | `/me/notification-settings` | 분류별 묶음(fieldset), 필수 알림은 체크된 채 잠김("필수 알림 — 끌 수 없음"), 선택 알림은 바꾸면 바로 저장, 실패 시 원래 값으로 되돌리고 알림 |

- **기능 플래그** `VITE_NOTIFICATIONS_UI=true`일 때만 경로·메뉴가 생깁니다(기본 꺼짐, Staging 이미지는 `false` 고정). Mock 모드면 Mock Adapter, 아니면 실제 API를 씁니다.
- **실제 API(추가)**: 서버 `NOTIFICATIONS_API=true`(기본 꺼짐) + `database/migrations/0005_notifications.sql`. §3 경로 그대로 구현(`backend/app/routers/notifications.py`). 알림함은 outbox 의 `channel='in_app' AND status='sent'` 본인 행, 수신 설정은 `notification_preferences` 표(행 없음 = T95 기본값). 운영(GCP) 적용·플래그 켜기는 별도 PM 승인.
- 켜져 있어도 로그인 사용자만 들어갑니다(`RequireAuth`). 데이터는 **로그인 사용자 ID별 Mock 저장소**로 분리합니다.
- 마케팅·추천 알림은 동의 전 **기본 꺼짐**입니다. 화면이 임의로 켜지 않습니다(지시서 §5).

## 2. 파일

`frontend/src/api/notifications.ts`(타입·라벨·오류 문구) · `frontend/src/mocks/notifications.ts`(사용자별 Mock) · `frontend/src/notifications/*`(Provider·Context) · `frontend/src/pages/NotificationsPage.tsx` · `frontend/src/pages/NotificationSettingsPage.tsx` · `frontend/src/pages/Notifications.css` · `routes.tsx` · `layouts/AppLayout.tsx` · `config/env.ts` · 시험 `frontend/src/pages/NotificationPages.test.tsx`, T89 접근성 회귀에 두 화면 추가

## 3. 데이터 계약 — 제안 (승인 필요)

수신 설정은 [T95 OpenAPI 제안](../notifications/t95_openapi_proposal.yaml) 그대로입니다. 알림함은 계약이 없어 아래를 **제안**합니다.

| 메서드·경로 | 응답 | 비고 |
|---|---|---|
| `GET /api/v1/me/notifications` | `{ items: InboxItem[], unread_count }` | 최신 순. 페이지 나눔은 서버 계약 때 결정 |
| `POST /api/v1/me/notifications/{id}/read` | `InboxItem` | 남의 알림 ID → 404(존재 비노출), 이미 읽음이면 그대로 |
| `POST /api/v1/me/notifications/read-all` | `{ updated }` | |
| `InboxItem` | `notification_id, type, title, summary, created_at, read_at\|null` | 본문 전체·링크·토큰·이메일은 담지 않음 |

서버 쪽은 T96 outbox의 `channel='in_app'` 행에 `read_at`을 더하는 방식이 가장 작습니다(T96 문서 §5).

## 4. 시험 결과 (로컬: Windows 11 · Node 24)

| 범주 | 시험 | 결과 |
|---|---|---|
| 플래그 | 꺼짐: 로그인해도 메뉴 없음·404, 기본 경로에 없음, Mock 모드 필수, Provider가 HTTP를 쓰지 않음 | PASS |
| 미로그인 | 두 경로 모두 로그인 화면으로 이동 | PASS |
| 읽음 | 안 읽음 2건 표시 → 한 건 읽음(1건, 상태 알림) → 모두 읽음(0건, 버튼 비활성), 저장소 반영 | PASS |
| **사용자 격리** | 사용자 A가 모두 읽음 → 관리자 B는 여전히 2건, B가 A의 알림 ID 읽음 처리 → 404, ID 겹침 없음, ID에 이메일 없음 | PASS |
| 빈 상태 | "받은 알림이 없습니다" | PASS |
| 오류 | 목록 오류 → alert + 다시 시도 → 복구, 읽음 실패 → alert, 안 읽음 그대로 | PASS |
| 설정 | 필수 잠김(설명 연결), 마케팅·추천 기본 끔, 점검 기본 켬, 켜기·끄기 저장(A만 바뀌고 B 그대로), 저장 실패 → 원래 값 복원 + alert, 불러오기 오류·다시 시도 | PASS |
| 계약 | 필수 끄기 요청 422(일부만 바뀌지 않음), 빈 목록 422, 요약에 링크·토큰·이메일 없음 | PASS |
| 접근성 자동 점검(T89 규칙) | 두 화면 | PASS |
| 실제 브라우저(Chrome, Mock dev 서버) | 1280px·375px 가로 넘침 없음, 키보드 Space로 설정 변경, 필수 잠김, 체크 영역 높이 44px, 알림 API 네트워크 요청 0건 | PASS |

- `NotificationPages.test.tsx` **14 PASS**, 전체 Vitest **423 passed / 22 skipped**, lint 0, `tsc -b` 0, `vite build` 성공
- 첫 전체 실행에서 기존 시험 2건(T85 경로·T89 403 화면)이 빌드와 동시에 돌면서 시간 초과로 실패했고, 다시 실행하니 통과했습니다(코드 변경 없음).
- 실제 브라우저 첫 로드에서 404 응답 1건이 콘솔에 남았습니다. 다시 열었을 때는 재현되지 않았고, 알림 API 요청은 아니었습니다.
- 스크린리더 실제 낭독·Firefox·Safari: **NOT_RUN**

## 5. HOLD / 결정 필요

1. 알림함 API 계약(§3) 승인과 서버 구현(T96 outbox 확장 또는 별도 표) → HTTP Adapter로 교체(Provider 한 곳)
2. T95 수신 설정 API·신규 동의 코드 3개 승인 → 설정 변경이 실제 `user_consents` 이력이 됨
3. 화면 ID UI-N04 등록(`docs/FULL_SCOPE_TRACEABILITY.md`)
4. 안 읽음 개수 배지(헤더) — 서버 집계 API가 생긴 뒤
