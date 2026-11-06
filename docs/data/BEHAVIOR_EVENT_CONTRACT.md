# 서비스 행동 이벤트·동의 계약 (T71)

> 상태: **DRAFT / NOT APPROVED / NOT MIGRATED** · 2026-11-06 (T05 완료 후 개정)
> 근거: [작업지시서 T71](../work-orders/remaining-30/T71.md), [T05 데이터 사전 v0.2](../../database/DATA_DICTIONARY.md) B09 `consent_policies`·B01 `user_consents`·F07 `behavior_events`, F-025·F-005 ([추적표](../FULL_SCOPE_TRACEABILITY.md)), `POST /api/v1/me/consents` ([T06 OpenAPI](../api/openapi.yaml)), ML04/ML06/ML07 ([AI 시스템 구조](../AI_SYSTEM_ARCHITECTURE.md)), [감사 이벤트 계약 T83](../security/AUDIT_EVENT_CONTRACT.md)
> 선행 일감: T04 완료, **T05 완료**(PR #17). T31(동의·탈퇴 API)은 진행 중이라 수집 API·실제 Migration 은 **HOLD** 이고, 이 문서는 데이터 사전을 확장하는 계약과 일회용 DB mock 검증까지 다룹니다.
> **동의 정책이 승인되기 전에는 실제 사용자 행동을 추적하지 않습니다.**

## 0. T05 데이터 사전과의 관계

| 구분 | 내용 |
|---|---|
| T05 에 이미 있음 (그대로 따름) | `behavior_events(event_id, user_id FK→users CASCADE, event_code, event_at, metadata)`, 보존 180일(가안), `consent_policies(policy_code, version, is_required, content_url, effective_at)`, `user_consents` 추가만 하는 이력, "`behavior_tracking` 최신 동의가 true 인 사용자만 기록" |
| T71 이 정하는 것 | `event_code` 허용 목록(카탈로그)과 이벤트별 `metadata` 허용 키, 값 형식, 동의 상태별 매트릭스, 철회 시 즉시 삭제, 집계 조회 k=5 |
| T71 이 T09 에 추가 제안 | `behavior_events.policy_code`·`policy_version`(수집 근거), `retain_until`(보존 기한 고정), 이벤트 카탈로그 표, 추천용 별도 동의 정책 `personalization` |

## 1. 목적과 범위

사용자가 **동의한 목적에 필요한 최소한의 행동만**, **정해진 기간 동안만** 남기고, 동의를 철회하거나 탈퇴하면 **즉시 멈추고 지우는** 규칙입니다. 분석하는 사람은 **개인을 알아볼 수 없는 집계만** 봅니다.

| 포함 | 제외 (다른 일감) |
|---|---|
| 동의 정책, event_code 목록과 허용 `metadata` | 수집 API·프론트 클라이언트 (T72) |
| 동의 상태별 허용 이벤트 매트릭스 | 품질·보존·삭제 검증 자동화 (T73) |
| 민감속성 제외, 조회 쪽 익명화(k=5) | 군집·이상탐지 모델 (T74, T77) |
| 철회·탈퇴 시 차단·삭제, 보존 기간 | 동의 화면·API 구현 (T31, T32) |

**행동 이벤트와 감사 이벤트는 다릅니다.** 로그인·권한 변경·개인정보 접근 같은 보안 기록은 동의와 상관없이 [감사 이벤트(T83)](../security/AUDIT_EVENT_CONTRACT.md)에 남습니다. 행동 이벤트는 **분석·개인화 목적이라 동의가 있어야만** 수집합니다.

## 2. 동의 정책

| policy_code | 출처 | 목적 | 이 동의로 수집하는 이벤트 | 기본값 |
|---|---|---|---|---|
| `behavior_tracking` | **T05** (B09 예시) | 서비스 이용 통계·화면 개선. 집계로만 사용 | page/search/posting/role/skill_gap 조회 | 미동의 (opt-in) |
| `personalization` | **T71 제안** | 행동 기반 추천·개인화 (ML06) | 북마크 신호, 추천 클릭·숨김 | 미동의 (opt-in) |

- 두 정책은 **따로** 동의·철회합니다. 하나를 철회해도 다른 쪽 데이터는 남습니다.
- `personalization` 을 따로 두지 않기로 하면 아래 매트릭스에서 personalization 이벤트도 `behavior_tracking` 으로 묶으면 됩니다 — **PM 결정 필요**.
- 두 정책 모두 `is_required = false` 입니다. T05 규칙(FR-ACC-006)대로 필수 정책(`terms` 등)은 가입 후 철회할 수 없습니다.
- 동의를 기록할 때는 그 정책의 **시행 중인 최신 버전**(`effective_at` 기준)을 씁니다. 정책 문구가 바뀌면 새 버전을 추가합니다. 재동의 요구 여부는 **PM 결정 필요**.
- 비로그인 방문자는 동의를 받을 방법이 없으므로 **추적하지 않습니다** (익명 쿠키 추적도 없음).

## 3. 이벤트 목록과 허용 metadata (allow-list)

| event_code | 필요한 동의 | 허용 `metadata` 키 (이 외 키는 거부) | 보존 |
|---|---|---|---|
| `page.view` | behavior_tracking | `page_id`, `referrer_type` | 180일 |
| `search.submit` | behavior_tracking | `search_type`, `filter_count`, `result_count` | 180일 |
| `posting.view` | behavior_tracking | `job_posting_id`, `list_position` | 180일 |
| `role.view` | behavior_tracking | `job_role_id` | 180일 |
| `skill_gap.view` | behavior_tracking | `job_role_id`, `gap_count` | 180일 |
| `posting.bookmark` | personalization | `job_posting_id` | 180일 |
| `recommendation.click` | personalization | `recommendation_id`, `rank` | 180일 |
| `recommendation.dismiss` | personalization | `recommendation_id`, `reason_code` | 180일 |

보존은 T05 가안(180일)을 그대로 따릅니다.

**metadata 값 규칙:** 숫자, true/false, 또는 공백 없는 ID·코드(`^[A-Za-z0-9_.:-]{1,64}$`)만 허용합니다. 공백이 들어간 문장은 거부되므로 **검색어 원문·자유 입력이 들어갈 수 없습니다** (T05 F07 "개인정보·자유 입력 금지"를 DB 에서 강제). 중첩 객체·배열도 거부하고, 키는 이벤트당 최대 10개, 1KB 이하입니다. 비어 있으면 NULL 로 저장합니다.

**컬럼**

| 컬럼 | 규칙 |
|---|---|
| `user_id` | T05: `users` 참조, 탈퇴로 사용자 행이 지워지면 **함께 삭제(CASCADE)** |
| `event_code` | 위 목록(catalog)에 있는 값만. `영역.동작` 소문자 |
| `event_at` | 발생 시각(UTC). 서버 시각보다 5분 넘게 미래이거나 7일보다 오래되면 거부 |
| `metadata` | 위 허용 키·값 규칙 |
| `policy_code`, `policy_version` | (T71 제안) 수집 당시 근거가 된 동의. 철회 시 삭제 범위를 정하는 데 씀 |
| `retain_until` | (T71 제안) 수집 시각 + 이벤트별 보존 기간 |

## 4. 익명성과 민감속성 제외

- T05 는 철회·탈퇴 시 바로 지울 수 있도록 `user_id` 를 그대로 저장합니다. 그래서 익명성은 **조회 쪽**에서 지킵니다.
  - 분석 계정은 원본 이벤트·동의 이력을 볼 수 없고, `user_id` 가 없는 집계(§7)만 봅니다.
  - 외부로 내보내는 분석 데이터가 생기면 `HMAC-SHA256(서버 비밀키, user_id)` 가명 키를 쓰는 안을 제안합니다 (이번 범위 아님).

**수집하지 않는 것**

| 분류 | 예 |
|---|---|
| 직접 식별 정보 | 이름, 이메일, 전화번호, IP 주소, 원본 User-Agent |
| 자유 입력·원문 | 검색어, 이력서·자기소개 문장, 채팅·LLM 질문 |
| 민감정보 | 건강, 종교, 정치 성향, 성별·나이·장애 여부 등 차별 우려 속성 |
| 정밀 위치·기기 정보 | GPS 좌표, 기기 고유 ID, 광고 ID |
| 화면 녹화성 데이터 | 마우스 이동, 키 입력, 스크롤 전체 궤적 |

## 5. 동의 상태별 허용 이벤트 매트릭스 (승인 대상)

| 동의 상태 | tracking 이벤트 (5종) | personalization 이벤트 (3종) | 기존 데이터 |
|---|:-:|:-:|---|
| 아무 동의 없음 | ✕ 버림 | ✕ 버림 | 없음 |
| behavior_tracking 만 동의 | ○ 저장 | ✕ 버림 | tracking 만 |
| personalization 만 동의 | ✕ 버림 | ○ 저장 | personalization 만 |
| 둘 다 동의 | ○ 저장 | ○ 저장 | 둘 다 |
| behavior_tracking 철회 | ✕ 버림 | 기존 상태 유지 | tracking 데이터 **즉시 삭제** |
| personalization 철회 | 기존 상태 유지 | ✕ 버림 | personalization 데이터 **즉시 삭제**, 추천 모델 반영(T73/ML06) |
| 철회 후 재동의 | ○ 저장 | 정책별 | 삭제된 데이터는 **복구하지 않음** |
| 탈퇴(계정 삭제) | ✕ 버림 | ✕ 버림 | T05: `users` 삭제 시 이벤트·동의 이력 **CASCADE 삭제** |

- "버림"은 오류가 아니라 정상 응답입니다. 수집 함수는 `blocked_no_consent` 를 돌려주고 아무것도 저장하지 않습니다. 없는 사용자·삭제된 사용자도 동의 기록이 없으므로 같은 결과입니다.
- 계약 위반(목록에 없는 이벤트·키, 잘못된 값, 시각 범위 밖, 비로그인)은 **오류로 거부**합니다.

## 6. 보존과 삭제

| 경우 | 처리 |
|---|---|
| 보존 기간 경과 | `purge_expired()` 가 `retain_until` 이 지난 행만 삭제 (정기 실행, T73) |
| 동의 철회 | 철회 기록과 **같은 트랜잭션에서** 그 정책으로 모은 이벤트 삭제 |
| 탈퇴 | T05 규칙: `users` 행 삭제 → 이벤트·동의 이력 CASCADE 삭제 (D-06 가안: 요청 30일 후) |
| 파생 데이터 | 집계·피처·모델에 이미 반영된 값의 처리(재학습·재집계 주기)는 T73·ML06 에서 정의 — **미확정** |

- T05 대로면 탈퇴 시 동의 이력도 지워집니다. 동의를 받았다는 증빙을 탈퇴 후에도 남겨야 하는지는 **법무 확인 필요** (필요하면 T83 감사 이벤트 `privacy.consent.update` 로 남는 기록으로 대신할 수 있음).

## 7. 집계 조회 (insights)

- 분석 계정은 원본 이벤트·동의 이력을 볼 수 없고 `insights_daily`(날짜, event_code, 이벤트 수, 사용자 수)만 봅니다. 이 뷰에는 `user_id` 가 없습니다.
- **같은 날·같은 이벤트에 서로 다른 사용자가 5명 미만이면 그 줄은 보여주지 않습니다** (k = 5).
- T06 OpenAPI 에는 행동 이벤트 집계 전용 경로가 없습니다. 행동 데이터를 쓰는 관리자 화면(`/admin/segments`, `/admin/anomalies`)과 이후 추가될 집계 API 에 같은 k=5 규칙을 적용하고, 응답에 "5명 미만 그룹 숨김"을 명시하는 안을 제안합니다.
- T06 `POST /me/consents` 는 선택 항목으로 `llm_processing`, `behavior_tracking` 만 받습니다. `personalization` 을 채택하면 T06 에도 추가가 필요합니다.

## 8. 권한 경계 (mock 기준)

| 역할 | 할 수 있는 것 | 할 수 없는 것 |
|---|---|---|
| 수집 API (`t71_ingest`) | `record_behavior_event()` 실행 | 표에 직접 INSERT, 원본 조회, 동의 변경 |
| 동의 API (`t71_consent`) | `record_consent()` 실행 (필수 정책 제외) | 이벤트 기록·조회 |
| 분석 (`t71_analyst`) | `insights_daily` 조회 | 원본 이벤트·동의 이력 조회, 삭제 실행 |
| 소유자 (migrator·개인정보 담당) | `purge_expired()` | 일상 앱 연결에 사용 금지 |

## 9. 검증 (일회용 DB 전용)

| 파일 | 내용 |
|---|---|
| [`database/tests/behavior/T71_behavior_events_mock.sql`](../../database/tests/behavior/T71_behavior_events_mock.sql) | T05 컬럼을 그대로 쓴 mock 스키마 `behavior_mock` + T71 카탈로그·함수·뷰 (Migration 아님) |
| [`database/tests/test_behavior_contract.sh`](../../database/tests/test_behavior_contract.sh) | 일회용 `postgres:18.1` 컨테이너에서 41개 항목 검증 |

```bash
D1_TEST_ONLY=YES bash database/tests/test_behavior_contract.sh
```

| 구분 | 확인 항목 |
|---|---|
| 동의 매트릭스 | tracking 만 동의 → 조회 저장·추천 클릭 버림, 미동의 → 전부 버림, 둘 다 동의 → 전부 저장, 버린 이벤트 미저장, 저장 행에 동의 근거(정책·버전) 기록 |
| 입력 계약 | 허용 목록 밖 키, 공백 있는 문장(검색어), 중첩 객체, 없는 event_code, 미래·7일 초과 시각, 비로그인 거부, 없는 사용자 → 버림 |
| T05 동의 규칙 | 필수 정책(`terms`) 철회 거부, 없는 정책 거부 |
| 권한 경계 | 수집 계정의 직접 INSERT·원본 조회·동의 변경 거부, 동의 계정의 이벤트 기록 거부, 분석 계정의 원본·동의 이력 조회·purge 거부, 집계 조회 허용, 집계에 `user_id` 없음 |
| 철회 | 철회 시 2건 즉시 삭제·이후 차단, 재동의 시 새 이벤트만 허용·삭제분 미복구, 동의 이력 3건 보존, personalization 철회 시 tracking 데이터 유지 |
| k-익명 | 4명 → 숨김, 5명 → 표시 |
| 탈퇴·보존 | 사용자 삭제 시 이벤트·동의 CASCADE 삭제 후 차단, 기한 지난 1건만 purge |

## 10. 미확정 항목 (PM·담당자 결정 필요)

1. 이벤트 목록 8종 승인
2. `personalization` 을 별도 동의 정책으로 둘지 (T05 에는 `behavior_tracking` 만 있음)
3. T71 추가 제안 컬럼(`policy_code`, `policy_version`, `retain_until`)과 이벤트 카탈로그 표를 T09 Migration 에 넣을지
4. 정책 버전 변경 시 재동의 요구 여부
5. 탈퇴 후 동의 증빙 보관 방법 (법무)
6. 파생 데이터(집계·피처·모델)에 철회·삭제를 반영하는 주기 — T73·ML06
7. k 값(5) 적정성, 일 단위보다 더 거친 집계가 필요한지
8. T31 완료 후 실제 Migration(T08/T09 절차)과 수집 API(T72) 연동

**판정:** `T71_STATUS=PARTIAL` — T05 F07/B01/B09 기준 계약·mock 검증 PASS(로컬 41항목), 허용 이벤트 매트릭스 PM 승인 전, T31 미완료로 실연동 HOLD.
