# 감사 이벤트·보존·변조 방지 계약 (T83)

> 상태: **DRAFT / NOT APPROVED / NOT MIGRATED** · 2026-11-06 (T05 완료 후 개정)
> 근거: [작업지시서 T83](../work-orders/remaining-30/T83.md), F-028 ([추적표](../FULL_SCOPE_TRACEABILITY.md)), `GET /api/v1/admin/audit-events` (T06 OpenAPI `listAuditEvents`) ([API 계약](../API_CONTRACT.md)), F11 `audit_events` ([T05 데이터 사전 v0.2](../../database/DATA_DICTIONARY.md)), [AI 시스템 구조](../AI_SYSTEM_ARCHITECTURE.md), [보안 규정](../SECURITY.md)
> 선행 일감: **T05 완료**(PR #17 머지, 데이터 사전 F11 기준으로 개정). T06(API 계약)·T15(인증)는 진행 중이라 실제 Migration·API 연동은 **HOLD** 이고, 이 문서는 데이터 사전 F11 을 확장하는 계약과 일회용 DB mock 검증까지 다룹니다.

## 0. T05 데이터 사전(F11)과의 관계

| 구분 | 컬럼 |
|---|---|
| T05 F11 에 이미 있음 (그대로 따름) | `audit_event_id`, `actor_user_id`(FK → users, **SET NULL**), `action_code`, `resource_type`, `resource_id`, `request_id`, `occurred_at` |
| T83 이 T09 에 추가 제안 | `audit_seq`, `recorded_at`, `actor_type`, `result`, `reason_code`, `client_ip_hash`, `changed_fields`, `metadata`, `retention_class`, `retain_until`, `row_hash` |

- T05 결정에 맞춰 바꾼 점: ① `correlation_id` → `request_id` (이름·NULL 허용), ② `actor_user_id` FK 를 두고 탈퇴 시 **SET NULL 로 익명화**, ③ 기본 보존 1년.
- 데이터 사전에 쓰인 `role.grant`, `account.deletion_requested` 같은 action_code 는 이 계약의 형식 규칙을 그대로 만족합니다.

## 1. 목적과 범위

누가(actor), 무엇을(action), 어떤 대상에(resource), 언제(time), 어떤 결과로(result) 했는지를 **나중에 고칠 수 없게** 남기고, 비밀번호·토큰·원문 개인정보는 **아예 남지 않게** 하는 규칙입니다.

| 포함 | 제외 (다른 일감) |
|---|---|
| 감사 이벤트 필드·형식, 기록 대상 이벤트 목록 | 실제 Migration 반영 (T08/T09 절차) |
| 금지 필드·마스킹 규칙 | 관리자 조회 API·화면 (T84, T85) |
| 보존 기간·삭제(purge) 규칙 | AI 비용 기록 `ai_usage_records` (T60/T84) |
| 변경·삭제 방지와 변조 감지 방법 | 애플리케이션 로그·APM 수집 (T112) |
| 일회용 DB 검증 SQL·테스트 | Staging 적용 (별도 승인) |

## 2. 감사 이벤트 필드

| 필드 | 형식 | 필수 | 누가 채우나 | 규칙 |
|---|---|:-:|---|---|
| `audit_event_id` | uuid | O | DB 기본값 | 공개 식별자 |
| `audit_seq` | bigint identity | O | DB | 기록 순서. 빈 번호는 롤백으로도 생길 수 있어 삭제 증거로 쓰지 않음 |
| `occurred_at` | timestamptz (UTC) | O | 앱 | 실제 행동 시각. DB 시각보다 5분 넘게 미래면 거부 |
| `recorded_at` | timestamptz (UTC) | O | **DB 트리거** | 앱이 넣은 값은 무시하고 DB 시각으로 덮어씀 |
| `actor_type` | `user` `admin` `system` `ai_agent` `service` | O | 앱 | `user`·`admin` 이면 **기록 시점에** `actor_user_id`·`request_id` 필수 (INSERT 트리거 검사) |
| `actor_user_id` | uuid, FK → users (SET NULL) | 조건부 | 앱 | 사용자 ID만. 이메일·이름 금지. 탈퇴 후 NULL 로 익명화 (T05) |
| `action_code` | `영역.대상.동작` 소문자 점 표기, 2~4단계 | O | 앱 | 예: `user.profile.update`, `admin.posting.close`, `agent.tool.call` |
| `resource_type` | 소문자 스네이크 | O | 앱 | 예: `user_profile`, `job_posting`, `agent_run` |
| `resource_id` | uuid | - | 앱 | 대상이 없으면 NULL |
| `result` | `success` `denied` `failed` | O | 앱 | 권한 거부(403)와 실패(4xx/5xx)를 구분 |
| `reason_code` | 대문자 스네이크 | 조건부 | 앱 | `success` 가 아니면 필수. 예: `NOT_AUTHORIZED`, `TOOL_TIMEOUT` |
| `request_id` | `[A-Za-z0-9._:-]{8,64}` | 조건부 | 앱 | API 오류 응답의 `request_id` 와 같은 값 (T05 이름). 시스템 작업은 NULL 가능 |
| `client_ip_hash` | 소문자 hex 64자리 | - | 앱 | 원본 IP 금지. 서버 비밀키로 만든 HMAC-SHA256 만 저장 |
| `changed_fields` | text[] (필드 **이름** 만, 최대 50개) | - | 앱 | 값은 절대 넣지 않음. 변경이 없으면 빈 배열 대신 NULL |
| `metadata` | jsonb 객체, 최대 4KB | - | 앱 | 아래 금지 규칙 적용 |
| `retention_class` | `security` `standard` `ai_agent` | O | 앱 | 보존 기간 결정 (§5) |
| `retain_until` | timestamptz | O | **DB 트리거** | `recorded_at + 보존기간` |
| `row_hash` | sha256 hex | O | **DB 트리거** | 행 내용 지문. 변조 감지용 (§6) |

## 3. 기록 대상 이벤트 (최소 목록 제안)

| 영역 | action_code 예시 | retention_class |
|---|---|---|
| 인증 | `auth.login.success`, `auth.login.attempt`(실패), `auth.logout`, `auth.token.revoke` | security |
| 권한·관리자 | `admin.user.disable`, `admin.role.grant`, `admin.role.revoke`, `admin.posting.close`, `admin.content.review` | security |
| 개인정보 | `privacy.consent.update`, `privacy.deletion.request`, `privacy.export.request`, `document.file.download` | security |
| 사용자 데이터 변경 | `user.profile.update`, `user.skill.update`, `user.target_role.update`, `user.bookmark.create` | standard |
| AI/Agent | `agent.run.start`, `agent.tool.approve`, `agent.tool.call`, `ai.model.deploy`, `ai.model.rollback` | ai_agent (모델 배포·롤백은 security) |
| 운영 | `system.seed.apply`, `system.migration.apply`, `system.audit.purge` | security |

- 조회(GET)는 원칙적으로 기록하지 않습니다. 단, **다른 사람의 개인정보·문서를 관리자가 조회**한 경우(`admin.user.view`, `document.file.download`)는 기록합니다.
- 실패·거부도 반드시 기록합니다 (`result` = `denied`/`failed` + `reason_code`).

## 4. 금지 필드와 마스킹

**절대 저장하지 않는 것** (DB CHECK 로 강제)

| 금지 대상 | 강제 방법 |
|---|---|
| 비밀번호, 토큰, API Key, 세션·쿠키, 인증 헤더, OTP, 개인키 | `metadata` 의 **모든 깊이**의 키 이름이 `passw`, `secret`, `token`, `api_key`, `authorization`, `cookie`, `session`, `credential`, `private_key`, `otp` 를 포함하면 거부 |
| 이메일·전화번호·주민번호 등 식별 원문 | 키 이름 `email`, `phone`, `ssn`, `rrn` 거부 + `metadata` 값에 이메일 형식이 있으면 거부 |
| 이력서·문서 원문, LLM 프롬프트·응답 원문 | 키 이름 `resume_text`, `document_text`, `prompt`, `completion` 거부 |
| 변경 전·후 값 | `changed_fields` 는 필드 이름 형식(`^[a-z][a-z0-9_]*$`)만 허용 |
| 원본 IP | `client_ip_hash` 는 hex 64자리만 허용 |
| 큰 덩어리 데이터 | `metadata` 4KB 초과 거부 |

- DB CHECK 는 **마지막 방어선**입니다. 1차 책임은 Backend 의 감사 기록 함수(T84)가 허용 목록(allow-list) 키만 넣는 것입니다.
- 이름에 금지어가 들어간 정상 키(예: `token_count`)도 거부됩니다. AI 사용량은 감사 이벤트가 아니라 `ai_usage_records` 에 저장합니다.
- `actor_user_id` 는 T05 결정대로 `users` 를 참조하고, 탈퇴로 사용자 행이 지워지면 **NULL 로 익명화**됩니다. 감사 행 자체는 보존 기간 동안 남습니다.
- 그래서 "user·admin 이면 행위자 필수" 규칙은 CHECK 가 아니라 **INSERT 트리거**로 검사합니다. CHECK 로 두면 탈퇴 시 익명화가 막혀 회원 삭제가 실패합니다.

## 5. 보존 기간 (제안, 법무·PM 승인 필요)

| retention_class | 기간 | 근거 후보 |
|---|---|---|
| standard | 1년 | T05 F11 가안(1년)과 같음. 일반 데이터 변경 |
| ai_agent | 1년 | T05 가안과 같음. Agent 승인·실행 추적 |
| security | 2년 | **T05 가안보다 긴 제안.** 개인정보처리시스템 접속기록 보관 기준(최소 1년, 조건에 따라 2년) 후보 — **법무 확인 필요** |

- 보존 기간은 `audit_retention_policies` 표에 두고, 기록 시점에 `retain_until` 을 계산해 고정합니다. 나중에 표를 바꿔도 이미 쌓인 행의 기한은 바뀌지 않습니다.
- 삭제는 **`purge_expired()` 하나로만** 합니다. `retain_until` 이 지난 행만 지우고, 실행 결과는 `system.audit.purge` 이벤트로 다시 기록합니다 (T84 구현).
- 법적 보존 요청(legal hold)이 생기면 purge 를 멈추는 절차가 필요합니다 — **미확정**.

## 6. 변경·삭제 방지와 변조 감지

| 층 | 방법 | 막는 대상 |
|---|---|---|
| 권한 | 앱 계정은 `INSERT` 만, 관리자 조회 계정은 `SELECT` 만. `UPDATE`/`DELETE`/`TRUNCATE` 권한은 아무에게도 주지 않음 | 앱 버그·SQL Injection 으로 인한 수정·삭제 |
| 트리거 | `UPDATE` 는 거부하되 **탈퇴 익명화(`actor_user_id` → NULL, 다른 값 변경 없음)만 허용**하고 그때 `row_hash` 를 다시 계산. `DELETE` 는 purge 중이고 기한이 지난 행만 허용, `TRUNCATE` 거부 | 테이블 소유자(migrator)의 실수 |
| DB 소유 필드 | `recorded_at`, `retain_until`, `row_hash` 는 트리거가 덮어씀 | 앱이 시각·기한을 속이는 것 |
| 내용 지문 | `row_hash = sha256(정해진 순서의 모든 필드)` + `find_tampered_rows()` 로 정기 점검 | 소유자가 트리거를 끄고 몰래 고친 경우 **감지** |

**알려진 한계 (다음 단계 후보)**
- 소유자나 SUPERUSER 는 트리거를 끄고 `row_hash` 까지 다시 계산해 넣을 수 있습니다. 이를 막으려면 DB 밖 비밀키로 만든 HMAC, 또는 일정 주기로 해시 묶음을 외부 저장소에 남기는 방법(앵커링)이 필요합니다.
- 행 삭제 자체는 지문으로 감지할 수 없습니다. 삭제 감지에는 해시 체인(이전 행 해시 연결)이 필요하지만, 보존 기간 purge 와 함께 쓰는 방식이 정해지지 않아 이번 범위에서 뺐습니다.
- `ai_career_poc`(SUPERUSER) 계정을 앱이 쓰는 동안에는 위 권한 통제가 의미가 없습니다. T07 최소 권한 계정 전환이 선행되어야 합니다.

## 7. API 연결 (T84 참고용)

- `GET /api/v1/admin/audit-events` (T06 OpenAPI `listAuditEvents`) 는 `t83_audit_reader` 에 해당하는 **읽기 전용 계정**으로 조회합니다.
- 필터: T06 에 정의된 `from`·`to`(필수)·`actor_user_id`·`action_code` 를 따르고, 최대 90일 범위와 `action_code` 접두어 검색, `resource_type`, `result`, `request_id`. 페이지네이션은 공통 규약(`limit` ≤ 100, `cursor`)을 따릅니다.
- 응답에 `row_hash` 는 노출하지 않고, 대신 무결성 점검 결과(`integrity: ok|mismatch`)만 표시하는 안을 제안합니다.
- 이 조회 자체도 `admin.audit.view` 이벤트로 기록합니다.

## 8. 검증 (일회용 DB 전용)

| 파일 | 내용 |
|---|---|
| [`database/tests/audit/T83_audit_events_mock.sql`](../../database/tests/audit/T83_audit_events_mock.sql) | 계약을 그대로 옮긴 mock 스키마 `audit_mock` (Migration 아님) |
| [`database/tests/test_audit_contract.sh`](../../database/tests/test_audit_contract.sh) | 일회용 `postgres:18.1` 컨테이너에서 아래 35개 항목 검증 |

```bash
D1_TEST_ONLY=YES bash database/tests/test_audit_contract.sh
```

| 구분 | 확인 항목 |
|---|---|
| 정상 | 앱 계정 기록 3건(success/denied/failed), DB 소유 필드 자동 설정, 앱이 넣은 시각·해시 무시, 조회 계정 SELECT |
| 권한 경계 | 앱 계정 UPDATE·DELETE·SELECT·purge 거부, purge 플래그를 직접 켜도 DELETE 거부, 조회 계정 INSERT 거부 |
| 변경 방지 | 소유자 UPDATE·DELETE·TRUNCATE 트리거 거부 |
| 금지 내용 | password 키, 중첩된 access_token 키, prompt 키, 값 속 이메일, 4KB 초과, 값이 섞인 changed_fields |
| 형식 | 잘못된 action_code, reason_code 누락, user 인데 actor_user_id 없음, user 인데 request_id 없음, 잘못된 request_id, 없는 사용자(FK), 미래 시각, 없는 보존 등급 |
| 탈퇴 익명화 (T05) | 사용자 삭제 시 `actor_user_id` 만 NULL·행 유지·`row_hash` 유효, 다른 사용자로 바꾸기 거부, 익명화와 다른 값 변경을 함께 하면 거부 |
| 보존 | 기한 지난 2건만 purge, 나머지 4건 유지, purge 후 일반 DELETE 다시 거부 |
| 변조 감지 | 소유자가 트리거를 끄고 고친 행을 `find_tampered_rows()` 가 찾아냄 |

## 9. 미확정 항목 (PM·담당자 결정 필요)

1. security 등급 2년(T05 가안 1년보다 김) — 법무 확인
2. T83 추가 제안 컬럼을 T09 Migration 에 넣을지 (§0 표)
3. 감사 테이블 스키마 위치 — `career` 와 분리된 `audit` 스키마 여부 (FULL_DATABASE_MODEL §1 "감사 경계" 항목)
4. IP HMAC 비밀키 보관 위치와 교체 주기 (Secret 관리 방식 결정 후)
5. HMAC 서명·외부 앵커링·해시 체인 도입 시점
6. legal hold 절차
7. T06/T15 완료 후 실제 Migration(T08/T09 절차)과 Backend 기록 함수(T84) 연동

**판정:** `T83_STATUS=PARTIAL` — T05 F11 기준 계약·mock 검증 PASS(로컬 35항목), 보존정책·추가 컬럼 PM 승인 전, T06/T15 미완료로 실연동 HOLD.
