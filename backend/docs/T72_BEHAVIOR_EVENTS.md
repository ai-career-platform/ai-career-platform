# T72 — 동의 기반 행동 이벤트 수집 API·클라이언트

> 상태: **PARTIAL** — 코드·격리 DB 검증 완료, **실제 수집은 기본 꺼짐**, T71 정책 미승인, Staging 미적용
> 근거: [T72 작업지시서](../../docs/work-orders/remaining-30/T72.md) · [T71 행동 이벤트 계약](../../docs/data/BEHAVIOR_EVENT_CONTRACT.md) (DRAFT) · F-025 · FR-ADM-006 · NFR-PRV-001

## 1. API

`POST /api/v1/me/behavior-events` (Bearer 인증, `docs/api/openapi.yaml` `recordMyBehaviorEvent`)

```json
{ "event_id": "3ad04800-5d47-47b4-a144-270e7e2e5f5c", "event_code": "posting.view",
  "event_at": "2026-11-10T03:00:00Z", "metadata": { "job_posting_id": "jp_123", "list_position": 3 } }
```

| 결과 | HTTP | 본문 `status` | 저장 |
|---|---|---|---|
| 동의 있음 + 허용 이벤트 | 201 | `recorded` | 1건 |
| 같은 `event_id` 재전송 | 200 | `duplicate` | 추가 없음 |
| 동의 없음·철회됨·이벤트가 최신 동의보다 이전 | 200 | `blocked_no_consent` | 없음 |
| personalization 3종 (T71 미승인) | 200 | `blocked_policy_pending` | 없음 |
| 서버 수집 스위치 꺼짐 (기본) | 200 | `collection_disabled` | 없음, DB 접근 없음 |
| 계약 위반 (아래 §2) · 쿼리 파라미터 · `user_id` 포함 | 422 | `VALIDATION_FAILED` | 없음 |
| JSON 형식 오류 | 400 | `MALFORMED_JSON` | 없음 |
| 토큰 없음·위조·만료, 비활성·탈퇴 계정 | 401 | `UNAUTHENTICATED` 등 | 없음 |
| Rate Limit 초과 (설정 시) | 429 | `RATE_LIMITED` + `Retry-After` | 없음 |
| DB 오류 | 503 | `DEPENDENCY_UNAVAILABLE` (롤백) | 없음 |

"버림"을 오류가 아닌 정상 응답으로 둔 것은 T71 §5(`blocked_no_consent`)를 따른 것이다.

## 2. 입력 검증 (T71 §3과 mock 함수 그대로)

- `event_code`: 8종 목록만. `user_id`는 받지 않는다(본문 `extra=forbid`, 쿼리 거부). 사용자는 토큰으로만 정한다.
- `metadata`: 이벤트별 허용 키만, 값은 숫자(유한값)·true/false·`^[A-Za-z0-9_.:-]{1,64}$`. 공백 있는 문장(검색어 원문·자유 입력), 중첩 객체, 배열, null 거부. 키 10개·1KB(`octet_length(metadata::text)` 기준) 이하. 비어 있으면 NULL 저장.
- `event_at`: 시간대 필수. 서버 시각 +5분 초과 미래, −7일 초과 과거는 422 (경계값 포함 테스트).
- `event_id`: UUID v4만 (nil·max·다른 버전 거부).

## 3. 동의 확인과 철회

처리 순서: 인증 → 입력 검증 → 수집 스위치 → Rate Limit → 시각 범위 → **사용자 행 잠금**(`SELECT … FOR UPDATE`, T31 `lock_user`) → 계정 상태 → 최신 `behavior_tracking` 동의 → 저장 → Commit.

- 동의는 서버가 매 요청 `user_consents` 최신 행으로 확인한다. Frontend 상태는 믿지 않는다.
- **철회:** T31 `POST /me/consents`에서 `behavior_tracking` `granted=false`를 기록하면 **같은 사용자 행 잠금·같은 트랜잭션** 안에서 그 사용자의 tracking 이벤트 5종을 삭제한다(T71 §6). 수집과 철회가 같은 잠금을 쓰므로, 진행 중이던 수집은 먼저 커밋된 뒤 철회에 지워지고, 철회가 먼저면 수집은 철회 후 상태를 본다.
- **복원 방지:** 이벤트 발생 시각이 최신 동의 기록 시각보다 이르면 저장하지 않는다. 철회(삭제) → 재동의 후 예전 이벤트를 다시 보내도 되살아나지 않는다. 클라이언트 시계가 서버보다 늦으면 동의 직후 이벤트가 버려질 수 있다(안전한 쪽으로 실패).
- 앱 DB 역할에는 `career.behavior_events` DELETE 권한이 필요하다(DRAFT_00 `career_app` 기본 권한에 포함).

## 4. 중복 처리 (스키마 변경 없음)

0001의 `behavior_events.event_id`는 서버 생성 uuid 기본키이고 중복 방지용 컬럼이 없다. 클라이언트 값을 기본키에 그대로 넣지 않고 다음 키를 쓴다.

```
저장 기본키 = uuid5(고정 namespace, "<user_id>:<클라이언트 event_id>")
INSERT … ON CONFLICT (event_id) DO NOTHING RETURNING event_id   → 없으면 duplicate
```

- 같은 사용자의 재전송은 같은 키 → `duplicate`. 동시 재전송도 1건만 저장(PostgreSQL 테스트).
- 다른 사용자가 같은 클라이언트 `event_id`를 보내도 키가 달라 서로의 이벤트를 덮거나 존재를 알 수 없다.
- 처음 저장된 내용이 유지된다(재전송 본문이 달라도 갱신하지 않음).
- T71이 제안한 `policy_code`·`policy_version`·`retain_until` 컬럼은 0001에 없어 **저장하지 않는다**(공유 Migration 변경은 범위 밖, §7).

## 5. 설정 (운영값 미확정)

| 환경변수 | 기본 | 의미 |
|---|---|---|
| `BEHAVIOR_EVENTS_ENABLED` | 꺼짐 | `true`/`1`/`yes`일 때만 저장 경로 동작 |
| `BEHAVIOR_EVENTS_RATE_LIMIT` | 없음 | `<건수>/<초>` (예 `60/60`). 사용자별, 기존 `AttemptLimiter`(프로세스 메모리) 재사용. 잘못된 값은 기동 실패 |
| `VITE_BEHAVIOR_TRACKING` (Frontend) | 꺼짐 | `true`일 때만 클라이언트가 전송 |

Rate Limit은 동의 확인을 대신하지 않는다(테스트). 다중 워커에서는 카운트가 공유되지 않는 기존 한계가 그대로 있다.

## 6. Frontend 클라이언트

`frontend/src/api/behaviorEvents.ts`

```ts
const tracker = createBehaviorTracker({
  enabled: env.behaviorTrackingEnabled,                 // 기본 false
  hasConsent: () => behaviorTrackingGranted(consents),   // GET /me/consents 이력의 최신 동의
  send: api.behaviorEvents.record,                       // 기존 인증 HttpClient
});
await tracker.track('posting.view', { job_posting_id: 'jp_123', list_position: 3 });  // 예외 없음
tracker.revoke();                                        // 철회 직후 즉시 중지
```

- 승인된 tracking 5종만 보낸다. personalization 3종과 허용 밖 키·값은 보내지 않는다(`skipped_not_allowed`).
- 네트워크 오류·5xx는 같은 `event_id`로 1회 재시도, 401·422·429는 재시도하지 않는다. 401은 기존 `onUnauthorized` 정책을 따른다.
- 서버가 `blocked_no_consent`를 돌려주면 이후 전송을 멈춘다. 재시도 직전에도 동의를 다시 확인한다.
- 실패는 결과 코드(`failed`)로만 돌려주고 화면 동작을 막지 않는다.
- **어떤 화면에도 호출 코드를 넣지 않았다.** 자동 추적·마우스·키 입력·페이지 전체 기록 기능은 없다.

## 7. 검증

| 범위 | 명령 | 결과 (2026-11-10, Windows 로컬) |
|---|---|---|
| Backend 단위 (실제 라우터·서비스 + 메모리 저장소) | `pytest tests/test_behavior_events.py` | 53 passed |
| Backend PostgreSQL 18.6 격리 DB | 아래 | T72 13 + T31 회귀 12 = 25 passed |
| Backend 전체 | `pytest` (격리 DB 포함) | 594 passed, 94 skipped. 실패 1·오류 19는 `test_documents.py` Windows 폴더 권한(0700) 문제로 **main에서도 동일** |
| T71 동시성 회귀 | `D1_TEST_ONLY=YES python -m unittest … test_behavior_concurrency.py` | 2 passed |
| T71 계약 41항목 | `test_behavior_contract.sh` 공용 본문을 로컬 PostgreSQL 18로 실행 (Docker 없음) | 41/41 PASS |
| OpenAPI 계약 | `python docs/api/check_openapi.py`, `pytest docs/api/test_check_openapi.py` | PASS (operation 75, 테이블 49/51), 9 passed |
| Frontend | `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`, `check:api` | 232 passed / 22 skipped, 모두 PASS |

```bash
# 일회용 loopback PostgreSQL 18, DB 이름 t16_profile_test (기존 T16 fixture 규칙)
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://<admin>@127.0.0.1:<port>/t16_profile_test \
  python -m pytest tests/test_behavior_events_postgres.py tests/test_privacy_postgres.py
```

PostgreSQL 테스트 항목: 동의 게이트·중복·저장 행 확인, personalization·잘못된 입력 미저장, 철회 시 본인 tracking 이벤트만 삭제·재동의 후 재전송 복원 안 됨, **수집이 INSERT 직전에 멈춘 동안 시작한 철회가 행 잠금을 기다렸다가 0건을 남김**, 동시 시작 5회, 동시 중복 1건, Commit 실패 롤백, 비활성 계정 401.
대조 실험: 서비스의 사용자 행 잠금을 잠금 없는 조회로 바꾸면 위 진행 중 수집 테스트가 실패한다(철회가 기다리지 않음). 동시 시작 5회 테스트는 잠금 없이도 통과할 수 있는 확률적 테스트다.

**Staging E2E: NOT_VERIFIED** (Staging DB·배포 변경 없음).

## 8. 미승인·HOLD

1. T71 이벤트 8종·동의 매트릭스는 PM 미승인. personalization 3종은 저장하지 않는다.
2. `personalization` 동의 정책 여부 미정 — `POST /me/consents`는 여전히 `llm_processing`, `behavior_tracking`만 받는다.
3. T71 제안 컬럼(`policy_code`, `policy_version`, `retain_until`)·카탈로그 표 Migration 미반영 → 보존 기한 자동 삭제(`purge_expired`, T73)는 이 PR 범위 밖.
4. 실제 수집 활성화(`BEHAVIOR_EVENTS_ENABLED`, `VITE_BEHAVIOR_TRACKING`)와 Rate Limit 운영값은 별도 승인.
5. Staging `ai_career_poc`에 `behavior_tracking` 동의 정책 행이 있는지, 앱 역할 DELETE 권한은 Staging 적용 단계에서 확인.
