# T85 — 운영 감사·AI 비용 대시보드 검증

> 판정: **FRONTEND_MOCK=PASS / REAL_API_INTEGRATION=HOLD** — 두 관리자 화면을 Mock Adapter로 구현하고 검증했습니다. 실제 API 연결은 하지 않았습니다.
> 확인일 2026-11-10 · 기준 main `4b39f55` (T84 #185·#186 병합 후) · 브랜치 `task/t85-admin-audit-usage-dashboard`

## 1. 구현 화면

| 화면 | 경로 | 내용 |
|---|---|---|
| 운영 감사 기록 (UI-028) | `/admin/audit-events` | 기간(KST)·작업 코드 검색, 최신 순 목록(발생 시각·작업 코드·대상·작업자·요청 ID), 이전·다음 페이지, 새로 조회, 빈 결과·로딩·오류·재시도 |
| AI 사용량·추정 비용 (UI-028) | `/admin/ai-usage` | 기간(KST 날짜)·집계 단위(일·기능·모델), 요청 수·입력/출력 토큰 합, 행별 추정 비용(USD, 미검증), 비용 미검증 경고, 데이터 없음 안내 |

**노출 조건**:
- 경로·메뉴는 `VITE_API_MOCK=true` **그리고** `VITE_ADMIN_AUDIT_UI=true`일 때만 생깁니다(`env.adminAuditUi`). 운영·일반 빌드에서는 항상 꺼져 있고, 기본 `routes`에도 두 경로가 없습니다.
- 켜져 있어도 기존 `RequireAuth roles={['admin']}`를 지납니다. 플래그만으로 보안을 대신하지 않습니다.

## 2. 컴포넌트 재사용

T82 관리자 패턴을 따랐습니다: 기능 플래그 + `RequireAuth` + Service Provider/Context + Mock Adapter + 준비된 HTTP Adapter.

| 재사용 | 용도 |
|---|---|
| `AppLayout` 주 메뉴 | 관리자에게만 "운영 감사 (Mock)", "AI 사용량·비용 (Mock)" |
| `RequireAuth` | 비로그인 → 로그인, admin 아님 → 403 화면 |
| `useQuery` | 조건 변경 시 이전 요청 취소(AbortSignal), 늦은 응답 무시 |
| `DataTable`, `StatePanel`, `Button` | 표·로딩·빈 결과·오류·재시도 |
| `ApiError`, `createHttpClient` | 오류 코드 해석, Bearer·401 처리 |
| 생성 타입 `schema.gen.ts` | `AuditEvent`, `AuditEventPage`, `AiUsageBucket`, `group_by` 값 |

새 의존성(UI·차트 라이브러리)은 없습니다. 숫자 정확도를 우선해 표로 표시했습니다.

## 3. API 계약

- 기준: T84 **현재 확정 계약**(`docs/api/openapi.yaml`)만 씁니다. D1~D5 제안 응답(마스킹 필드, `AiUsageReport`, 90일 제한)은 가정하지 않습니다.
- `AdminAuditService { listEvents(query, signal), getUsage(query, signal) }` — `createMockAdminAuditService`와 `createHttpAdminAuditService`가 같은 인터페이스를 구현합니다.
- HTTP Adapter 경로: `/v1/admin/audit-events`, `/v1/admin/ai-usage`. HttpClient의 baseUrl이 `/api`이므로 실제 요청은 `/api/v1/...`이고 `/api`가 중복되지 않습니다(테스트).
- **HttpClient 최소 확장**: `HttpRequest.onResponseHeaders?(headers)` 콜백 1개를 추가했습니다. 성공 응답에서만 불리고, 기존 반환 타입·호출은 바꾸지 않았습니다. HTTP Adapter는 이 콜백으로 `X-AI-Cost-Status`를 읽습니다.
- 비용 상태: `'unverified'`(헤더 값 정확히 일치)와 `'unknown'`(없음·다른 값)만 있습니다. **"검증 완료" 상태는 타입에 없습니다.**

## 4. Mock 데이터 (합성만)

- **감사 30건**:
  - 유형: 로그인(`auth.login.success`), 권한 변경(`admin.role.grant`), 관리자 작업(`admin.posting.close`), 문서 다운로드(`document.file.download`), 시스템(`system.behavior.purge`), AI(`agent.tool.call`, `ai.model.deploy`).
  - 4건은 같은 시각(동률 정렬 확인용)입니다. ID는 `00000000-0000-4000-8000-…`, 요청 ID는 `req-mock-NNNN` 형식입니다.
- **사용량 5건**:
  - `document_analysis`·`rag_answer`·`agent`, 모델 3종, 여러 날짜를 씁니다.
  - 0원 행 1건(무료로 확인된 값 아님), 탈퇴 사용자 행 2건(사용자 ID 없이 상태만)이 들어 있습니다.
- Mock은 서버 동작을 흉내 냅니다:
  - 반열림 기간, 최신 순 정렬
  - 조건에 묶인 cursor(다르면 400 `INVALID_CURSOR`)
  - 형식 오류 422
  - KST 날짜 집계, 비용 합은 마이크로달러 정수로 계산
- 화면에는 "가상 데이터(Mock)" 안내가 항상 보입니다. 사용량 화면에는 "표시 중: 가상 데이터(Mock)"도 함께 나옵니다. 실제 사용자 ID·이메일·토큰·문서는 없습니다.

## 5. 관리자 권한

| 경우 | 동작 | 테스트 |
|---|---|---|
| 플래그 꺼짐 | 메뉴 없음, 두 경로 404 | Routes |
| 비로그인 | 로그인 화면으로 이동 | Routes (두 경로) |
| 일반 사용자 | 403 화면, 메뉴·표 없음 | Routes (두 경로) |
| 관리자 | 메뉴 2개, 두 화면 Mock 데이터 | Routes |
| 서버 403 (권한 회수) | "권한이 없습니다… 회수되었을 수 있습니다" | Pages |
| 서버 401 (토큰 만료) | "로그인이 만료되었습니다", HttpClient `onUnauthorized`가 세션 처리 → `RequireAuth`가 로그인으로 | Pages, Contract |

## 6. 감사 검색

- 기간: `datetime-local`(KST) → `+09:00` 오프셋 ISO로 보냅니다. 기본값은 최근 7일이고, 종료는 미포함입니다.
- 화면 검증: 시작 ≥ 종료, 작업 코드 형식(`영역.대상.동작`) 오류이면 요청을 보내지 않습니다.
- 작업 코드 필터는 정확히 일치합니다(확정 계약). 접두어 검색은 없습니다(D7 미결정).
- **사용자 ID 검색은 제공하지 않습니다.** 확정 계약에는 `actor_user_id`가 있지만, GET 쿼리 문자열이 uvicorn·Nginx 접근 로그에 남는 문제(T84 보고서 §8)가 해결되지 않았기 때문입니다. 서비스 타입에서도 뺐습니다. **이 화면이 서버 로그 문제를 해결한 것은 아닙니다.**
- 작업자·`user` 대상 ID는 화면에서 `앞8…끝4`로 줄여 표시합니다. 이는 **표시만 줄이는 것**이고, 확정 API 응답과 브라우저 메모리에는 원래 UUID가 있습니다(서버 마스킹 D3 미승인).

## 7. Cursor 동작

| 항목 | 구현 |
|---|---|
| 다음 페이지 | 응답 `next_cursor`를 스택에 넣고 그 cursor로 요청 |
| 이전 페이지 | 스택에서 하나 빼서 이전 cursor(첫 페이지는 없음)로 다시 요청 |
| 조건 변경·조회·새로 조회 | 스택을 비우고 1페이지부터 |
| 중복·늦은 응답 | `useQuery`가 이전 요청을 abort하고 늦은 응답을 버림 (테스트) |
| 400 `INVALID_CURSOR` | 안내 + "처음부터 다시 조회" |
| 401·403·422·503 | 고정 문구(서버 원문 미표시), 503만 "다시 시도" |
| 스냅샷 한계 | 화면 안내: "페이지를 넘기는 동안 새로 기록되거나 늦게 저장된 기록은 빠지거나 나타날 수 있습니다(조회 시점 고정 아님)" — T84 조건 B와 같은 설명 |

## 8. AI 사용량 집계

- **기간**: KST 날짜이고 양쪽을 포함합니다. 시작 > 종료는 화면에서 거부합니다. 최대 기간은 "아직 정해지지 않았습니다"라고만 안내합니다(D5 90일은 서버 제한으로 설명하지 않음).
- **집계 단위**: `day`(KST, "YYYY-MM-DD (KST)"), `feature_code`(한글 이름 + 코드), `provider_model`.
- **정수 표시**: 요청 수·토큰은 `ko-KR` 천 단위 구분 정수로 표시합니다. 요약 카드는 표 행의 정수 합입니다.
- **비용**:
  - 행별로 서버 값을 그대로 USD로 표시합니다(최대 소수 6자리, 예: `$0.300001`).
  - **비용 합계는 서버가 주지 않으므로 화면에서 계산하지 않습니다**("서버 미제공 — 행별 값만 표시").

## 9. 비용 상태

- 경고 문구는 항상 보입니다: **"추정 비용은 검증되지 않았으며 실제 청구액과 다를 수 있습니다."**
- 헤더가 없거나 모르는 값이면 "(서버가 비용 확인 상태를 알려 주지 않아 검증되지 않은 것으로 표시합니다.)"를 덧붙입니다.
- 각 비용 칸에 "미검증" 배지를 붙입니다. 0원이면 "무료로 확인된 값 아님"을 덧붙입니다.
- 사용 기록이 없으면 "집계된 사용 기록 없음 … 비용이 0원이라는 뜻은 아닙니다"를 표시합니다. 비용 미검증과 다른 상태로 구분합니다.
- "검증 완료", "확정 금액", "청구 금액:" 문구가 없음을 테스트로 확인합니다.

## 10. 개인정보 비노출

- 사용자 ID 검색 입력이 없습니다. 작업자·사용자 대상 ID는 줄여서 표시합니다.
- 화면에 이메일(`@`)·`token`·`password`·전체 사용자 UUID가 없음을 테스트로 확인합니다.
- 사용량 화면에는 사용자 정보가 전혀 없습니다(탈퇴 여부도 표시하지 않음, 합계에만 포함).
- 오류 화면에는 서버 메시지 원문 대신 고정 문구를 씁니다.

## 11. 테스트 명령

```bash
cd frontend
npm ci
npm run typecheck
npm run lint
npm test          # vitest run
npm run build
npm run check:api # Linux CI 기준 (Windows 로컬은 CRLF 차이)
```

## 12. 테스트 결과 (로컬, Windows)

| 검사 | 결과 |
|---|---|
| `npm run typecheck` | PASS |
| `npm run lint` (oxlint --deny-warnings) | PASS |
| `npm test` | **350 passed, 22 skipped** (32 파일 중 29 실행, 3 skip은 기존 파일) |
| — 신규 `src/api/adminAuditHttp.contract.test.ts` | 15 passed (계약·HTTP Adapter·헤더 콜백) |
| — 신규 `src/pages/admin/AdminAuditPages.test.tsx` | 25 passed (작업지시서 1~30) |
| — 신규 `src/pages/admin/AdminAuditRoutes.test.tsx` | 8 passed (플래그·권한·메뉴) |
| `npm run build` | PASS |
| 생성 타입 (`openapi-typescript --check`) | Windows에서 "not up-to-date" — 다시 생성해 CR을 무시하고 비교하면 **같음**(CRLF 차이만). `openapi.yaml`·`schema.gen.ts` 변경 없음. CI(Linux)에서 판정 |
| 브라우저 확인 (headless Chrome, Mock 모드, 1280·375px) | 가로 넘침 없음(표는 자체 스크롤), 두 화면 렌더, 페이지 이동 동작. 감사·사용량 API 네트워크 요청 0건. 콘솔 404 1건은 `/favicon.ico`(저장소에 파비콘 없음, 기존 상태) |

작업지시서 STEP 09 대응:

| 번호 | 테스트 |
|---|---|
| 1·2·3 | Routes(관리자·비로그인·일반 사용자), Pages 1 |
| 4·5 | Pages 4·5 |
| 6·7 | Pages 6·6b·7 (화면 검증 포함) |
| 8·9·10 | Pages 8·9, 10 |
| 11 | Pages 11 (감사), 사용량 늦은 응답 |
| 12 | Pages 12 |
| 13·14·15 | Pages 13·14 (401·403·422), 15 (503 재시도) |
| 16~18·26 | Pages 16·17·18·26 |
| 19~21 | Pages 19·20·21 |
| 22 | Pages 22 (UTC 14:59:59.999 / 15:00) |
| 23·24·29 | Pages 23·24·29, 24b (헤더 없음) |
| 25·27·28 | Pages 25, 27, 28 |
| 30 | Pages 30a (감사), 30b (사용량) |
| 계약 | Contract: openapi.yaml 경로·파라미터·필드 = 생성 타입 = Mock 응답 = T84 백엔드 응답 예 |

## 13. CI 결과

PR 본문과 GitHub Checks를 따릅니다.

## 14. 실제 API 연결 여부

**연결하지 않았습니다.**
- `AdminAuditServiceProvider`는 Mock만 고르고, HTTP Adapter를 import하지 않습니다(테스트로 고정).
- HTTP Adapter는 가짜 fetch로만 시험했습니다. 실제 Backend·DB 호출은 0건입니다.

## 15. 미완료 선행조건

| 항목 | 상태 |
|---|---|
| T20 공통 UI | 완료 (#43) |
| T84 Backend·계약 | 병합 (#185·#186). 확정 계약만 사용. D1~D5 NOT_APPROVED |
| T60 AI 사용량 기록 | 미착수 → 실제 사용량 데이터 없음 |
| 접근 로그의 쿼리 문자열 문제 | 미해결 → 사용자 ID 검색 미제공 |
| 실제 연결 | T60, T84 정책 승인, 접근 로그 처리 후 Provider에서 HTTP Adapter 선택 (별도 단계) |
| "내보내기 마스킹" (T85 작업지시서 §2) | 내보내기 기능 없음 — 범위 밖, 후속 |

## 16. Staging 미변경

Backend·DB·Migration·OpenAPI·배포 설정·Staging 변경이 없습니다. 실제 감사 기록·사용량 데이터를 읽거나 쓰지 않았습니다.
