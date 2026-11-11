# T87 — 동의 철회·탈퇴·보존 E2E 검증

> 판정: **PARTIAL** — 철회·탈퇴 접수의 전파와 삭제/보존 분류를 실제 PostgreSQL에서 검증했습니다.
> 물리 삭제(purge) 작업은 미구현이고 보존 기간 정책이 미승인이라 **HOLD**입니다. 일회용 DB에서 흉내만 내어 분류표대로 동작하는지 사전 검증했습니다.
> 확인일 2026-11-11 · 기준 main `1f3cecd` · 브랜치 `task/t87-privacy-e2e` · Backend 업무 코드 변경 0건

## 1. 선행 작업 상태

| 일감 | 상태 | 근거 |
|---|---|---|
| T31 동의·탈퇴 요청 API | 완료 — 동의는 추가만(append-only), 탈퇴는 **접수만**(비활성화 + 세션 폐기). 취소는 503(재인증 정책 미정) | PR #139, `app/services/privacy.py` |
| T49 개인 문서 | 완료 — 삭제 시 worker가 파일 → 메타데이터 순으로 삭제, FK CASCADE로 분석·청크·인용 정리 | PR #159, `app/document_worker.py` |
| T53 (작업지시서상 문서 분석·검색 인덱스) | 문서 청크(`document_chunks.index_ref`) 경로만 존재. 외부 벡터 인덱스 연동 없음(T56 Mock) | 0001 DDL |
| T71·T72 행동 데이터 동의 | 완료 — `behavior_tracking` 철회 시 같은 트랜잭션에서 수집 이벤트 삭제 | PR #36, T72 |
| T73 행동 데이터 보존·purge | 완료 — 만료분 purge(감사 기록 포함), 일회용 DB 증거 요구 | PR #180 |
| T83 감사 계약 | **DRAFT / 미승인 / 미적용** | PR #35 |

## 2. 기존 시험과의 관계 (중복 작성 안 함)

| 이미 검증됨 | 위치 |
|---|---|
| 동의 이력·원자성·동시성, 탈퇴 접수 원자성·롤백·동시성·취소 HOLD | `tests/test_privacy_postgres.py` |
| 행동 데이터 철회·재동의·재전송 차단, 만료 purge·감사·롤백, 사용자 삭제 시 이벤트·동의 CASCADE | `tests/test_behavior_data_postgres.py` |
| 분석 worker의 동의 재확인 | `tests/test_document_analyses_postgres.py` |
| 문서 삭제 worker 재시도·부분 실패 | `tests/test_documents.py` (Linux) |

T87은 **시스템을 가로지르는 전파**와 **전체 삭제/보존 분류**만 추가했습니다 (`backend/tests/test_t87_privacy_e2e_postgres.py`).

## 3. 시험과 결과 (로컬 일회용 PostgreSQL 18)

| # | 시험 | 확인 내용 | 결과 |
|---|---|---|---|
| 1 | `test_every_user_foreign_key_has_a_reviewed_retention_class` | `career.users`를 참조하는 FK **25개 전부**가 검토된 분류(DELETE/ANONYMIZE)와 일치하고, RESTRICT가 없음(purge가 막히지 않음). 새 개인 데이터 표가 분류 없이 생기면 실패 | PASS |
| 2 | `test_withdrawal_stops_new_processing_for_a_only` | A가 `behavior_tracking`·`llm_processing`을 철회하면 A 행동 이벤트 0, 재전송 3회 후에도 0(**신규 처리 0**). 분석 요청 403 `CONSENT_REQUIRED`, 분석 행 0. B는 이벤트 유지·분석 202. 동의 이력 `[True, False]` 보존 | PASS |
| 3 | `test_deletion_request_cuts_every_protected_route_and_keeps_b` | 접수 응답 202(영수증: status·requested_at, 식별정보 없음). 사용자 비활성, 활성 세션 0, 요청 1건. **A 토큰으로 비공개 경로 48개 전부 401**(T86 경로 목록 재사용). A 문서를 B는 404. B 데이터 불변. 물리 데이터는 아직 남음(접수 단계) | PASS |
| 4 | `test_deletion_intake_failure_changes_nothing_and_retry_recovers` | 중간 실패(세션 폐기 권한 회수) → 503, 요청 행 0, 사용자 active, 토큰 유효(**반쪽 상태 없음**). 권한 복구 후 재시도 → 1건, 이후 401 | PASS |
| 5 | `test_simulated_physical_purge_follows_the_retention_map` | (HOLD 기능의 사전 검증, 일회용 DB에서만) A 사용자 행 삭제 → DELETE 분류 표의 A 행 0, 문서 청크(검색 인덱스 참조) 0. 감사·AI 사용량·탈퇴 영수증은 행 수 유지(사용자 참조만 NULL). B 데이터 불변 | PASS |

최소 권한 확인에서 드러난 사실:
- 문서 조회·분석 요청은 행 잠금(`FOR UPDATE/SHARE`)을 써서 `user_documents` UPDATE 권한이 필요합니다.
- 분석 요청은 처음 한 번 `model_versions`에 INSERT합니다.

배포 시 DB 권한 설계(T07)에 반영할 항목입니다.

## 4. 삭제/보존 분류 (0001 FK 기준, 미래 purge 시)

| 분류 | 표 |
|---|---|
| **DELETE** (사용자와 함께 삭제) | user_profiles, auth_identities, auth_sessions, user_roles(user), password_reset_tokens, user_consents, user_experiences, user_projects, user_skills, user_target_roles, skill_gap_assessments, recommendation_runs, recommendation_feedback, match_evaluations, user_documents(→ 분석·청크·인용 CASCADE), retrieval_runs, agent_runs, behavior_events, user_segment_assignments, user_job_bookmarks |
| **ANONYMIZE** (행 보존, 사용자 참조 NULL) | account_deletion_requests(영수증), audit_events(감사), ai_usage_records(익명 집계), user_roles.granted_by, agent_tool_approvals.approver |

법정 보존 기간은 결정하지 않았습니다. T05 가안 1년, T83 제안 보안 2년은 **미승인**이므로, 이 표는 "무엇이 남는가"만 고정하고 "얼마나 남는가"는 정하지 않습니다.

## 5. 삭제 처리 영수증·이력

- 접수 응답(202)이 영수증입니다: `request_id`, `status=requested`, `requested_at`, `scheduled_purge_at=null`.
- 요청 행은 사용자 삭제 후에도 익명화된 채 남습니다(처리 이력).
- 동의 철회 이력은 `user_consents`에 추가만 됩니다.

## 6. Findings

| ID | 심각도 | 내용 | 조치 |
|---|---|---|---|
| F87-1 | Medium (T83 승인 대기) | 탈퇴 접수·동의 철회가 `audit_events`에 기록되지 않습니다. T83 계약은 `privacy.deletion.request`·`privacy.consent.update`를 보안 등급 기록 대상으로 **제안**하지만 미승인입니다. 현재 동작을 시험으로 고정했습니다 | T83 승인 후 T31 서비스에 감사 INSERT 추가(같은 트랜잭션) → 시험 단정 반전 |
| F87-2 | Low (UX·정책) | 접수 직후 계정이 비활성이라, 본인이 처리 상태를 다시 조회할 수 없습니다(GET 401). 취소도 503(재인증 정책 미정) | 처리 상태 확인 방법(이메일 영수증 등 — T95 알림 계약) PM 결정 |
| — | HOLD | 물리 삭제 작업(보존 기간 경과 후 사용자 행 삭제, 문서 파일 삭제 연계) 미구현 | 보존 기간 승인 후 구현. 시험 5가 사전 검증 기준 |
| — | HOLD | 외부 검색 인덱스(벡터 저장소) 정리 — 현재 외부 인덱스 없음(`index_ref`만 저장) | T56 실연동 시 삭제 연계 필요 |

## 7. 재현 방법

```bash
cd backend
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/t16_profile_test \
  APP_ENV=test python -m pytest -q tests/test_t87_privacy_e2e_postgres.py
```

T16 가드(loopback, DB 이름 `t16_profile_test`), 0001·0002 Migration + Seed, 합성 사용자 A·B(`@example.invalid`), 최소 권한 앱 역할을 씁니다. 문서 파일 저장소는 T51 PG 시험과 같은 메모리 저장소입니다.

## 8. 결과 요약

| 범위 | 결과 |
|---|---|
| T87 E2E (로컬 일회용 PG 18) | **5 passed** |
| T86 보안 시험(공용 fixture 변경 회귀) | 412 passed (+12 Windows 전용 업로드 오류, Linux CI 판정) |
| 전체 Backend (로컬 Windows, PG) | 1211 passed, 53 skipped, 1 failed + 31 errors — 모두 문서 저장소 POSIX 의존(기존과 동일) |
| CI | PR 본문 참고 |

공용 fixture 변경: `tests/security/security_pg.py`에 `disposable_pg(write_tables, migrations, extra_sql)`를 추가했습니다. 기존 `sec_pg` 동작은 그대로입니다.

Staging·운영·공유 DB 변경 0건, 실제 회원 데이터 사용·삭제 0건입니다.
