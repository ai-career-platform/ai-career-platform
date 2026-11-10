# T82 — 운영 관리자 검수 UI 검증 (Mock 전용)

> 상태: **구현 PASS (Mock) / 실연동 HOLD** · 기능: F-027 · 화면: UI-027 · 담당 문길래 (GilbertMoon) · 기준 main `1fe3025`
> 이 화면은 **가상 데이터(Mock)** 로만 동작합니다. 검수 API(T81)가 main에 없고, 검수 정책(T80)은 PM 승인 전 제안입니다.
> 테스트 PASS는 실제 서비스 연동이나 정책 확정을 뜻하지 않습니다.

## 1. 작업 개요

관리자 검수 큐·상세·담당 시작·승인·반려·처리 이력 화면을 만들었습니다. 화면은 `ModerationService` 인터페이스만 쓰고, 지금은 **메모리 Mock Adapter**(네트워크 요청 없음)만 연결됩니다. 기능은 **기본 꺼짐**이고 Mock 모드에서 플래그를 켤 때만 경로·메뉴가 생깁니다.

## 2. 선행 조건 확인 (main `1fe3025`, 실제 코드 기준)

| 일감 | 확인 결과 | 영향 |
|---|---|---|
| T20 | #43 병합 — 공통 레이아웃·UI 컴포넌트 (관리자 전용 Layout은 **없음**) | `AppLayout`·`DataTable`·`FilterChips`·`StatePanel`·`Button` 재사용 |
| T21 | #127 병합 — 로그인·인증 UI, `RequireAuth({ roles })` | 관리자 경로 가드 재사용 (미로그인 → 로그인, 역할 없음 → 403 화면) |
| T81 | **없음** — PR 없음, `backend/app`·`docs/api/openapi.yaml`·`frontend/src`에 moderation 코드 없음 | 실제 API 연결 **HOLD**. 타입은 T80 계약 제안 DTO로 수기 작성 |
| T80 | #145·#181 병합 — 정책·상태 모델·구현 계약 (모두 **PROPOSED**, F-027 1차 제외) | 상태 6개·전이 가드·오류 코드를 Mock과 화면에 반영, 확정 정책으로 취급하지 않음 |

## 3. 적용한 T80 정책·계약 (제안 그대로, 확정 아님)

- 상태 6개: PENDING·IN_REVIEW·APPROVED·REJECTED·APPEALED·CLOSED — 색과 함께 **글자**로 표시
- 전이 가드 (상태 모델 T02·T06·T07·T09): 자기 콘텐츠 검수 금지, 담당자만 승인·반려, 이의제기 재검토에서 최초 결정자 차단, 결정·종료된 건 재처리 차단, version 불일치 409
- 반려 사유 9종 필수, `OTHER`는 설명 필수, 설명 500자 이하, 설명은 응답·목록·이력에 나오지 않음
- 오류 응답: 기존 카탈로그만 (401·403 `FORBIDDEN`·404·409 `APPROVAL_CLOSED`/`CONFLICT`·422)
- **화면에서 제공하지 않는 조치** (정책 미승인): 게시 중단 표시, 임시 비공개, 이의제기 처리 방식 결정 — 화면에 그 사실을 안내

## 4. 구현 화면

| 경로 | 화면 | 주요 기능 |
|---|---|---|
| `/admin/moderation` | 검수 큐 | 상태·우선순위 필터(FilterChips), 콘텐츠 유형 select, 표(DataTable): 검수 건·유형·상태·우선순위·처리 기한(기한 초과 글자 표시)·담당자, 로딩·빈 결과·오류+다시 시도, 상세 이동 |
| `/admin/moderation/:caseId` | 검수 상세 | 대상 요약·대상 ID·요청 사유(계기·신고 수)·상태·우선순위·기한·담당자·반려 사유·결정·종료 사유, 자동 표시(flag), 조치(담당 시작·승인·반려), 처리 이력 |

- 목록·상세에 **신고자 정보, 관리자 내부 메모, 비공개 원문은 없습니다**(DTO에서 제외, 테스트로 확인).
- 승인·반려는 확인 대화상자(`components/ConfirmDialog`)를 거칩니다. 포커스 이동·Tab 순환·Esc 닫기·원래 버튼으로 포커스 복귀는 `PrivacySettingsPage` 대화상자와 같은 규칙입니다.
- 비활성 버튼에는 이유를 `aria-describedby`로 연결합니다(예: "자기 콘텐츠는 검수할 수 없습니다.").
- 조치 중에는 모든 조치 버튼·대화상자 버튼이 비활성화되고, **렌더 전에도 ref 잠금**으로 연속 클릭의 두 번째 요청을 막습니다.
- 409는 "최신 내용 다시 불러오기" 버튼으로 다시 조회합니다.

## 5. 구조 — API·Mock 분리

```
ModerationQueuePage / ModerationCasePage
            │  useModerationService()
            ▼
   ModerationService (api/moderation.ts — 제안 DTO·인터페이스)
            ├── createMockModerationService (mocks/moderation.ts) ← 지금 연결
            └── createHttpModerationService (api/moderationHttp.ts) ← T81 이후, 현재 미연결
```

- 연결 지점은 `admin/ModerationServiceProvider.tsx` 한 곳입니다.
- `availableActions()`는 **버튼 표시용(UX)** 이고 보안 경계가 아닙니다. Mock Adapter가 같은 규칙으로 따로 거부해 "서버 판단"을 흉내 내며, 실제 권한 판단은 T81 Backend가 해야 합니다.
- `admin.content.review` 권한은 T80 제안 코드라 화면은 이를 가정하지 않고 기존 `admin` 역할로만 가드합니다.

## 6. Mock 데이터

`mocks/moderation.ts` — 합성 9건, 이메일은 `@example.invalid`, 제목은 `[합성]` 접두어. 로그인 Mock 관리자 `admin@example.com`(기존 handlers.ts 계정)의 user_id와 맞춰 경계 조건을 고루 담았습니다.

| 건 | 상태 | 시나리오 |
|---|---|---|
| mc-00001 | PENDING, P1, 기한 초과, 개인정보 패턴 flag | 담당 시작 가능 |
| mc-00002 | PENDING, 공용 자료 | 소유자 = 로그인 관리자 → 자기 콘텐츠 금지 |
| mc-00003 | IN_REVIEW, 담당 = 나 | 승인·반려 가능 |
| mc-00004 | IN_REVIEW, 담당 = 다른 관리자 | 결정 불가 |
| mc-00005 | APPEALED, 최초 결정자 = 나 | 재검토 담당 불가 |
| mc-00006 | APPEALED, 최초 결정자 = 다른 관리자 | 재검토 담당 가능 |
| mc-00007 | APPROVED | 읽기 전용 |
| mc-00008 | REJECTED (HARMFUL) | 반려 사유·이력 표시 |
| mc-00009 | CLOSED (TARGET_DELETED) | 종료 사유, 조치 비활성 |

Mock 상태 변경은 브라우저 메모리에만 남고(새로고침 시 초기화) 실제 DB·API와 연결되지 않습니다.

## 7. 접근 제어·기능 플래그

| 조건 | 결과 |
|---|---|
| 플래그 꺼짐 (기본, 운영·일반 빌드) | 메뉴 없음, `/admin/moderation`은 404 화면, 기본 export `routes`에 경로 없음 |
| 플래그 켜짐 + 미로그인 직접 URL | 로그인 화면으로 이동 |
| 플래그 켜짐 + 일반 사용자 | 403 "접근 권한이 없습니다", 메뉴 없음 |
| 플래그 켜짐 + admin | 메뉴 "콘텐츠 검수 (Mock)", 큐·상세 |

- 플래그: `env.adminModerationUi = VITE_API_MOCK === 'true' && VITE_ADMIN_MODERATION_UI === 'true'` (빌드 시 값). **Mock 모드가 아니면 항상 꺼짐**이고 URL 쿼리로는 켤 수 없습니다.
- `.env.mock`(`npm run dev:mock` 전용)에만 `VITE_ADMIN_MODERATION_UI=true`를 넣었습니다.
- 인증 상태에 `/me`의 `user_id`를 `userId`(선택 필드)로 추가했습니다 — "내 담당·내 콘텐츠" 표시용이며 기존 화면 동작은 바뀌지 않습니다.

## 8~9. 테스트 (Vitest + Testing Library, 실제 클릭·화면 결과 확인)

| 파일 | 건수 | 내용 |
|---|---|---|
| `src/api/moderation.test.ts` | 25 | 조치 가능 판정 9건 매트릭스, 반려 입력 규칙, 오류 문구 6종, Mock Adapter의 서버형 거부(401·403·404·409 2종·422·version), 이의제기 재검토 담당, 응답 복사본, 실제 API Adapter의 제안 경로 |
| `src/pages/admin/ModerationPages.test.tsx` | 26 | 아래 표 |
| `src/pages/admin/ModerationRoutes.test.tsx` | 5 | Mock 로그인 경유: 플래그 꺼짐(관리자도 메뉴 없음·404, 기본 routes에 경로 없음), 미로그인 → 로그인, 일반 사용자 → 403·메뉴 없음, admin → 메뉴·큐·상세 |

지시서 필수 항목 대응 (모두 PASS, 로컬):

| # | 항목 | 테스트 |
|---|---|---|
| 1~3 | 목록 렌더링, 상태 필터, 유형 필터 (+우선순위) | queue: lists…, filters… |
| 4, 8 | 상세 조회, 이력 표시 | case detail: shows target… / rejects… |
| 5~7 | 담당 배정, 승인, 반려 | actions: assigns…, approves…, rejects… |
| 9~11 | 미로그인·일반 사용자·직접 URL 차단 | ModerationRoutes |
| 12~14 | 자기 콘텐츠, 다른 담당자, 결정 완료 건 | boundaries (화면 비활성 + 이유) + moderation.test (Mock 서버 거부) |
| 15~18 | 403·404·409·422 표시 | server errors… / 404 for an unknown case |
| 19~21 | 승인·반려 연속 클릭 1회, 요청 중 비활성 (+담당 시작) | double submission (지연 60ms Mock) |
| 22 | 실패 후 재시도 | a failed request can be retried |
| 23~24 | 빈 목록, API 오류 + 다시 시도 | queue: empty / API error |
| 25~26 | 잘못된 반려 사유, OTHER 설명 누락 | blocks a missing reason and OTHER… (요청 0건 확인) |
| 추가 | 플래그 꺼짐 시 메뉴·경로 비활성 | ModerationRoutes |
| 추가 | 네트워크 요청 없음 | 모든 페이지 테스트의 fetch 감시 가드 + 전용 테스트 |
| 추가 | 키보드: 대화상자 첫 컨트롤 포커스, Esc 닫기·포커스 복귀, 오류 메시지 연결(aria-describedby) | actions |

## 10~11. 실행 명령과 결과 (2026-11-10, Windows 11, Node 24)

```powershell
Set-Location frontend
npm ci
npm run typecheck   # PASS
npm run lint        # PASS (oxlint --deny-warnings)
npm test            # 288 passed / 22 skipped (기존 232 + T82 56)
npm run build       # PASS
npx vite build --mode mock   # PASS (Mock 모드 빌드)
npm run check:api   # 로컬 Windows: CRLF 차이만 (OpenAPI·schema.gen.ts 변경 없음, CI Linux에서 확인)
```

- T82 신규 56건: `npx vitest run src/api/moderation.test.ts src/pages/admin` → 56 passed
- **실제 브라우저 확인** (`npm run dev:mock` + headless Chrome, 1280px·375px): admin 로그인 → 큐 → mc-00003 → 반려(OTHER 설명 누락 경고 확인 후 입력) → 반려 완료. 가로 스크롤 없음, `/api` 요청 없음(Vite 소스 모듈 로드만). 콘솔 오류는 브라우저의 `/favicon.ico` 404 1건(main과 동일, 이 기능과 무관).
- 확인 중 고친 점: 상태·우선순위 필터 이름이 화면에 보이지 않아 "전체" 칩이 둘 붙어 보이던 문제(눈에 보이는 이름 추가, 낭독 중복 방지), 긴 상태 이름이 배지 안에서 줄바꿈되던 문제.

## 12. CI 결과

PR 본문에 기록합니다.

## 13. API 실연동 보류 사유

- T81(검수 큐·조치 API) 미구현: main의 Backend·OpenAPI에 검수 경로·스키마가 없습니다. `/admin/reviews`는 API v0.2에서 삭제된 상태입니다.
- T80 정책·상태·권한 모델이 PM 승인 전이고, F-027은 1차 범위에서 제외돼 있습니다.
- 따라서 실제 엔드포인트로 요청을 보내지 않습니다. **실제 API가 연동된 것으로 보고하지 않습니다.**

## 14. T81 연결 시 바꿀 곳

1. T81 OpenAPI 병합 → `npm run gen:api` → `api/moderation.ts` 수기 타입을 `Schemas[...]` 생성 타입으로 교체 (`target_summary` 같은 제안 필드 확정 여부 확인)
2. `admin/ModerationServiceProvider.tsx`에서 `createHttpModerationService(useApi 의 HttpClient)` 선택
3. `env.adminModerationUi`의 Mock 전용 조건을 실제 모드 플래그로 바꾸는 것은 **정책 승인 후** 별도 결정
4. 권한: T81이 `admin.content.review` 등을 확정하면 `RequireAuth`·메뉴 조건을 그 권한 기준으로 조정
5. Mock 테스트 중 서버 판단 관련 항목은 T81 통합 테스트로 다시 확인 (Mock PASS ≠ 실제 PASS)

## 15. 미완료·제한

- 실제 API 연동, Staging 확인: **NOT_VERIFIED / HOLD**
- 이의제기 철회·게시 중단·임시 비공개·신고 접수 화면: 범위 밖 (정책 미승인)
- 다른 관리자 이름 표시: 사용자 디렉터리 API가 없어 ID로 표시
- 목록 페이지네이션: Mock은 `next_cursor: null`만 반환 (T81 커서 계약 확정 후)
- 실제 스크린리더 기기 확인은 하지 않았습니다(jsdom 접근성 이름·키보드 테스트만)

## 변경 파일

| 구분 | 파일 |
|---|---|
| 신규 | `frontend/src/api/moderation.ts`, `frontend/src/api/moderationHttp.ts`, `frontend/src/mocks/moderation.ts`, `frontend/src/admin/moderationContext.ts`, `frontend/src/admin/ModerationServiceProvider.tsx`, `frontend/src/components/ConfirmDialog.tsx`·`.css`, `frontend/src/pages/admin/ModerationQueuePage.tsx`, `ModerationCasePage.tsx`, `moderationUi.tsx`, `moderationFormat.ts`, `Moderation.css` |
| 신규 테스트 | `frontend/src/api/moderation.test.ts`, `frontend/src/pages/admin/ModerationPages.test.tsx`, `ModerationRoutes.test.tsx` |
| 수정 | `frontend/src/routes.tsx` (`buildRoutes(features)`, 플래그 켜질 때만 관리자 경로), `frontend/src/layouts/AppLayout.tsx` (admin + 플래그일 때만 메뉴), `frontend/src/config/env.ts`·`vite-env.d.ts` (플래그), `frontend/.env.mock`, `frontend/src/auth/useAuth.ts`·`AuthContext.tsx` (`userId` 선택 필드) |
| 문서 | `docs/testing/T82_ADMIN_MODERATION_UI_VALIDATION.md` |

Backend·DB·Migration·OpenAPI·Staging·운영 설정은 바꾸지 않았습니다.
