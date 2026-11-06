# 서비스 행동 이벤트·동의 계약 (T71)

> 상태: **DRAFT / NOT APPROVED / NOT MIGRATED** · 2026-11-06 · Redmine #1540
> 근거: [작업지시서 T71](../work-orders/remaining-30/T71.md), F-025·F-005 ([추적표](../FULL_SCOPE_TRACEABILITY.md)), `POST /api/v1/me/consents`·`GET /api/v1/insights` ([API 계약](../API_CONTRACT.md)), B01 `user_consents`·F07 `behavior_events` ([전체 데이터 모델](../../database/FULL_DATABASE_MODEL.md)), ML04/ML06/ML07 ([AI 시스템 구조](../AI_SYSTEM_ARCHITECTURE.md)), [감사 이벤트 계약 T83](../security/AUDIT_EVENT_CONTRACT.md)
> 선행 일감 T04(요구사항)·T05(ERD)·T31(동의·탈퇴 API)는 아직 완료 증빙이 없습니다. 그래서 이 문서는 **설계와 일회용 DB mock 검증까지만** 다룹니다. 수집 API·실제 Migration 은 **HOLD** 입니다.
> **동의 정책이 승인되기 전에는 실제 사용자 행동을 추적하지 않습니다.**

## 1. 목적과 범위

사용자가 **동의한 목적에 필요한 최소한의 행동만**, **가명으로**, **정해진 기간 동안만** 남기고, 동의를 철회하거나 탈퇴하면 **즉시 멈추고 지우는** 규칙입니다.

| 포함 | 제외 (다른 일감) |
|---|---|
| 수집 목적과 동의 정책, event_code 목록과 허용 속성 | 수집 API·프론트 클라이언트 (T72) |
| 동의 상태별 허용 이벤트 매트릭스 | 품질·보존·삭제 검증 자동화 (T73) |
| 가명 식별, 민감속성 제외 규칙 | 군집·이상탐지 모델 (T74, T77) |
| 철회·탈퇴 시 차단·삭제, 보존 기간 | 동의 화면·API 구현 (T31, T32) |
| 집계 조회의 최소 인원(k-익명) 기준 | 보안·관리자 감사 기록 (T83) |

**행동 이벤트와 감사 이벤트는 다릅니다.** 로그인·권한 변경·개인정보 접근 같은 보안 기록은 동의와 상관없이 [감사 이벤트(T83)](../security/AUDIT_EVENT_CONTRACT.md)에 남습니다. 이 문서의 행동 이벤트는 **분석·개인화 목적이라 동의가 있어야만** 수집합니다.

## 2. 동의 정책

| policy_code | 목적 | 이 동의로 수집하는 이벤트 | 기본값 |
|---|---|---|---|
| `behavior_analytics` | 서비스 이용 통계·화면 개선. **집계로만** 사용 | page/search/posting/role/skill_gap 조회 | 미동의 (opt-in) |
| `personalization` | 행동 기반 추천·개인화 (ML06) | 북마크 신호, 추천 클릭·숨김 | 미동의 (opt-in) |

- 두 정책은 **따로** 동의·철회합니다. 하나를 철회해도 다른 쪽 데이터는 남습니다.
- 동의 기록은 덮어쓰지 않고 **이력으로 쌓습니다** (`user_consents`: user_id, policy_code, policy_version, granted, recorded_at, source). 가장 최근 행이 현재 상태입니다.
- 정책 문구가 바뀌면 `policy_version` 을 올립니다. 재동의 요구 여부는 **PM 결정 필요**.
- 비로그인 방문자는 동의를 받을 방법이 없으므로 **추적하지 않습니다** (익명 쿠키 추적도 없음).

## 3. 이벤트 목록과 허용 속성 (allow-list)

| event_code | 필요한 동의 | 허용 속성 (이 외 키는 거부) | 보존 |
|---|---|---|---|
| `page.view` | behavior_analytics | `page_id`, `referrer_type` | 180일 |
| `search.submit` | behavior_analytics | `search_type`, `filter_count`, `result_count` | 180일 |
| `posting.view` | behavior_analytics | `job_posting_id`, `list_position` | 180일 |
| `role.view` | behavior_analytics | `job_role_id` | 180일 |
| `skill_gap.view` | behavior_analytics | `job_role_id`, `gap_count` | 180일 |
| `posting.bookmark` | personalization | `job_posting_id` | 365일 |
| `recommendation.click` | personalization | `recommendation_id`, `rank` | 365일 |
| `recommendation.dismiss` | personalization | `recommendation_id`, `reason_code` | 365일 |

**속성 값 규칙:** 숫자, true/false, 또는 공백 없는 ID·코드(`^[A-Za-z0-9_.:-]{1,64}$`)만 허용합니다. 공백이 들어간 문장은 거부되므로 **검색어 원문·자유 입력이 들어갈 수 없습니다.** 중첩 객체·배열도 거부하고, 속성은 이벤트당 최대 10개, 1KB 이하입니다.

**공통 필드**

| 필드 | 규칙 |
|---|---|
| `event_code` | 위 목록(catalog)에 있는 값만. `영역.동작` 소문자 |
| `occurred_at` | 클라이언트 발생 시각(UTC). 서버 시각보다 5분 넘게 미래이거나 7일보다 오래되면 거부 |
| `received_at` | 서버가 기록. 클라이언트 값 무시 |
| `subject_key` | 가명 식별자 (§4). 원본 user_id·이메일은 저장하지 않음 |
| `policy_code`, `policy_version` | 수집 당시 근거가 된 동의. 철회 시 삭제 범위를 정하는 데 씀 |
| `retain_until` | 수집 시각 + 이벤트별 보존 기간 |

## 4. 가명 식별과 민감속성 제외

- `subject_key = HMAC-SHA256(서버 비밀키, user_id)` 입니다. 비밀키 없이는 user_id 로 되돌릴 수 없고, 단순 `sha256(user_id)` 와도 다릅니다.
- 비밀키는 DB 밖(Secret 관리 수단)에 둡니다. mock 은 소유자만 읽는 표에 두었습니다. 키 교체 시 기존 이벤트를 다시 연결할지(재계산) 끊을지 **결정 필요**.
- 분석 담당자는 원본 이벤트를 볼 수 없고 집계(§7)만 봅니다. 따라서 subject_key 로 특정인을 추적할 수 없습니다.

**수집하지 않는 것**

| 분류 | 예 |
|---|---|
| 직접 식별 정보 | 이름, 이메일, 전화번호, 원본 user_id, IP 주소, 원본 User-Agent |
| 자유 입력·원문 | 검색어, 이력서·자기소개 문장, 채팅·LLM 질문 |
| 민감정보 | 건강, 종교, 정치 성향, 성별·나이·장애 여부 등 차별 우려 속성 |
| 정밀 위치·기기 정보 | GPS 좌표, 기기 고유 ID, 광고 ID |
| 화면 녹화성 데이터 | 마우스 이동, 키 입력, 스크롤 전체 궤적 |

## 5. 동의 상태별 허용 이벤트 매트릭스 (승인 대상)

| 동의 상태 | analytics 이벤트 (5종) | personalization 이벤트 (3종) | 기존 데이터 |
|---|:-:|:-:|---|
| 아무 동의 없음 | ✕ 버림 | ✕ 버림 | 없음 |
| analytics 만 동의 | ○ 저장 | ✕ 버림 | analytics 만 |
| personalization 만 동의 | ✕ 버림 | ○ 저장 | personalization 만 |
| 둘 다 동의 | ○ 저장 | ○ 저장 | 둘 다 |
| analytics 철회 | ✕ 버림 | 기존 상태 유지 | analytics 데이터 **즉시 삭제** |
| personalization 철회 | 기존 상태 유지 | ✕ 버림 | personalization 데이터 **즉시 삭제**, 추천 모델 반영(T73/ML06) |
| 철회 후 재동의 | ○ 저장 | 정책별 | 삭제된 데이터는 **복구하지 않음** |
| 탈퇴(계정 삭제) | ✕ 버림 | ✕ 버림 | **전부 삭제**, 모든 정책 철회 이력 기록 |

- "버림"은 오류가 아니라 정상 응답입니다. 수집 함수는 `blocked_no_consent` 를 돌려주고 아무것도 저장하지 않습니다. 클라이언트는 이 결과로 사용자를 방해하지 않습니다.
- 계약 위반(목록에 없는 이벤트·속성, 잘못된 값, 시각 범위 밖, 비로그인)은 **오류로 거부**합니다.

## 6. 보존과 삭제

| 경우 | 처리 |
|---|---|
| 보존 기간 경과 | `purge_expired()` 가 `retain_until` 이 지난 행만 삭제 (정기 실행, T73) |
| 동의 철회 | 철회 기록과 **같은 트랜잭션에서** 그 정책으로 모은 이벤트 삭제 |
| 탈퇴 | `erase_subject()` 가 모든 정책 철회 이력을 남기고 모든 이벤트 삭제 |
| 파생 데이터 | 집계·피처·모델에 이미 반영된 값의 처리(재학습·재집계 주기)는 T73·ML06 에서 정의 — **미확정** |

- 동의 이력(`user_consents`) 자체는 동의를 받았다는 증빙이므로 탈퇴 후에도 법정 기간 보관을 제안합니다 — **법무 확인 필요**.
- 철회·탈퇴 처리 결과는 감사 이벤트 `privacy.consent.update`, `privacy.deletion.request` 로 남깁니다 (T83).

## 7. 집계 조회 (insights)

- 분석 계정은 원본 이벤트·동의 이력·비밀키를 볼 수 없고 `insights_daily` 집계만 봅니다.
- **같은 날·같은 이벤트에 서로 다른 사용자가 5명 미만이면 그 줄은 보여주지 않습니다** (k = 5). 소수 인원의 행동이 드러나는 것을 막기 위해서입니다.
- `GET /api/v1/insights` 응답의 `limitations[]` 에 "5명 미만 그룹 숨김"을 명시하는 안을 제안합니다.

## 8. 권한 경계 (mock 기준)

| 역할 | 할 수 있는 것 | 할 수 없는 것 |
|---|---|---|
| 수집 API (`t71_ingest`) | `record_behavior_event()` 실행 | 표에 직접 INSERT, 원본 조회, 동의 변경 |
| 동의 API (`t71_consent`) | `record_consent()` 실행 | 이벤트 기록·조회 |
| 분석 (`t71_analyst`) | `insights_daily` 조회 | 원본 이벤트·동의 이력·비밀키 조회, 삭제 실행 |
| 소유자 (migrator·개인정보 담당) | `erase_subject()`, `purge_expired()` | 일상 앱 연결에 사용 금지 |

## 9. 검증 (일회용 DB 전용)

| 파일 | 내용 |
|---|---|
| [`database/tests/behavior/T71_behavior_events_mock.sql`](../../database/tests/behavior/T71_behavior_events_mock.sql) | 계약을 옮긴 mock 스키마 `behavior_mock` (Migration 아님) |
| [`database/tests/test_behavior_contract.sh`](../../database/tests/test_behavior_contract.sh) | 일회용 `postgres:18.1` 컨테이너에서 아래 39개 항목 검증 |

```bash
D1_TEST_ONLY=YES bash database/tests/test_behavior_contract.sh
```

| 구분 | 확인 항목 |
|---|---|
| 동의 매트릭스 | analytics 만 동의 → 조회 저장·추천 클릭 버림, 미동의 → 전부 버림, 둘 다 동의 → 전부 저장, 버린 이벤트 미저장 |
| 입력 계약 | 허용 목록 밖 속성, 공백 있는 문장(검색어), 중첩 객체, 없는 event_code, 미래·7일 초과 시각, 비로그인 거부 |
| 권한 경계 | 수집 계정의 직접 INSERT·원본 조회·동의 변경 거부, 동의 계정의 이벤트 기록 거부, 분석 계정의 원본·동의·비밀키·삭제 거부, 집계 조회 허용 |
| 가명 | 원본 user_id 미저장, subject_key 가 단순 해시와 다름 |
| 철회 | 철회 시 2건 즉시 삭제·이후 차단, 재동의 시 새 이벤트만 허용·삭제분 미복구, 동의 이력 3건 보존, personalization 철회 시 analytics 데이터 유지 |
| k-익명 | 4명 → 숨김, 5명 → 표시 |
| 삭제·보존 | 탈퇴 시 전부 삭제·이후 차단, 기한 지난 1건만 purge |

## 10. 미확정 항목 (PM·담당자 결정 필요)

1. 이벤트 목록 8종과 보존 기간(180일/365일) 승인
2. 정책 버전 변경 시 재동의 요구 여부
3. HMAC 비밀키 보관·교체 방식, 교체 시 기존 이벤트 연결 여부
4. 동의 이력 보관 기간 (법무)
5. 파생 데이터(집계·피처·모델)에 철회·삭제를 반영하는 주기 — T73·ML06
6. k 값(5) 적정성, 일 단위보다 더 거친 집계가 필요한지
7. FULL_DATABASE_MODEL F07 `behavior_events` 의 `user_id uuid?`·`metadata jsonb?` 를 `subject_key`·allow-list `properties` 로 바꾸는 안 반영 여부
8. T04/T05/T31 완료 후 실제 Migration(T08 절차)과 수집 API(T72) 연동

**판정:** `T71_STATUS=PARTIAL` — 계약·mock 검증 PASS(로컬), 허용 이벤트 매트릭스 PM 승인 전, 실연동 HOLD.
