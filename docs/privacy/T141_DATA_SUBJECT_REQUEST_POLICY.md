# 개인정보 열람·정정·삭제·반출 요청 정책 (T141)

> 상태: **PROPOSED**. PM·법무 승인 전이며, 운영 기능을 켜는 근거가 아닙니다.
> - 기계 판독용 정의: [`t141_data_subject_requests.json`](t141_data_subject_requests.json). 문서와 JSON은 `backend/tests/test_t141_data_subject_policy.py`로 일치를 확인합니다.
> - 재사용: T31 동의·탈퇴 접수 API, T83 감사 이벤트 계약, T128 공개 프로필 동의 정책.
> - 실제 개인정보 삭제·반출은 실행하지 않았습니다. 시험은 합성 데이터만 씁니다.

## 1. 현재 사실 (main `822fa16`)

| 항목 | 상태 |
|---|---|
| 탈퇴 접수 | T31 `POST /api/v1/me/deletion-request`. 접수하면 계정 비활성·세션 폐기. **물리 삭제는 미구현**, 보존 기간(D-06 30일)은 초안 |
| 탈퇴 취소 | T31 `DELETE`는 **HOLD**. 비활성 계정은 재인증할 수 없어 503으로 막혀 있음 |
| 동의 기록 | T31 `user_consents` append-only |
| 감사 기록 | T83 계약(`privacy.deletion.request`, `privacy.export.request`). 보존 security 2년 제안 |
| 반출 | 없음 → T142에서 플래그 뒤 API 제안 |
| 재인증 | **없음.** 로그인 세션만 있음 → T142에서 비밀번호 재확인 제안 |

## 2. 요청 유형

| 코드 | 이름 | 본인 처리 | 재인증 | 처리 기한 | 결과 |
|---|---|---|---|---|---|
| `access` | 열람 | 가능 | 필요 | 10일 | 화면 조회. 통합 열람은 반출과 같은 묶음 |
| `rectification` | 정정 | 가능 | 불필요(기존 수정 API) | 10일 | 기존 수정 화면으로 고칠 수 없는 항목만 접수 |
| `erasure` | 삭제 | 가능 | 필요 | 10일 | §6 삭제 계획 적용 |
| `export` | 반출 | 가능 | 필요 | 10일 | 1회용 다운로드 묶음 |

처리 기한 10일은 **법무 확인 전 후보값**입니다.

## 3. 신원 재확인

- **본인 처리(self-service)**: 로그인 세션 + **10분 안 비밀번호 재확인**. 재확인은 그 세션(`session_id`)에만 묶이고, 시도 제한은 T15 로그인 limiter를 같이 씁니다.
- **담당자 처리(assisted)**: 로그인할 수 없는 사람(예: 탈퇴 접수로 비활성화된 계정)의 요청. `pending_verification`으로 접수하고 담당자가 확인합니다. 확인 **방법 코드와 결과만** 남기고, 신분증 사본 같은 원문은 저장하지 않습니다.
- 재확인 없이 우회하는 토큰·복구 경로는 만들지 않습니다(T31 HOLD 유지).

## 4. 상태와 전이

| 상태 | 종료 | 뜻 |
|---|---|---|
| `pending_verification` | 아니오 | 담당자 신원 확인 전 |
| `received` | 아니오 | 확인 완료, 처리 대기(본인 처리는 여기서 시작) |
| `in_progress` | 아니오 | 처리 중 |
| `completed` | 아니오 | 완료. 반출은 다운로드 가능 기간 |
| `failed` | 아니오 | 실패. 한도(3회) 안에서 재시도 |
| `rejected` | 예 | 반려(사유 필수) |
| `cancelled` | 예 | 본인 취소(처리 시작 전만) |
| `expired` | 예 | 반출 다운로드 만료·사용 완료. 파일 삭제 |
| `closed` | 예 | 반출 외 요청 종결 |

전이는 JSON `transitions`가 기준입니다. 요약:
- `pending_verification → received`(담당자 확인) / `→ rejected` / `→ cancelled`(본인)
- `received → in_progress`(시스템·담당자) / `→ rejected` / `→ cancelled`
- `in_progress → completed` / `→ failed`(사유 필수)
- `failed → received`(재시도, 3회 미만) / `→ rejected`
- `completed → expired`(반출만) / `→ closed`(반출 외)
- `in_progress` 뒤에는 본인이 취소할 수 없습니다. 삭제가 일부 적용된 상태로 멈추지 않게 하기 위해서입니다.

### 담당
- 담당 역할 `privacy_officer`는 **아직 없습니다.** 임시로 `admin` 역할에 매핑하는 안을 제안합니다(PM 결정).
- 담당자는 **자기 요청을 확인·반려하지 않습니다**(`not_requester`).

### 반려·실패 사유 코드
- 반려: `identity_not_verified`, `duplicate_request`, `manifestly_excessive`, `legal_hold`, `not_data_subject`
- 실패: `export_too_large`, `storage_unavailable`, `dependency_unavailable`, `internal_error`

## 5. 제한

| 항목 | 값 |
|---|---|
| 유형별 열린 요청 | 1건(중복은 409 `CONFLICT`) |
| 유형별 30일 요청 수 | 3건 |
| 재시도 한도 | 3회 |
| 반출 다운로드 | **1회, 24시간** |
| 반출 최대 크기 | 50 MiB. 넘으면 `export_too_large`로 실패하고 분할 반출을 제안 |

## 6. 데이터 범주별 반출·삭제 분기

| 범주 | 표 | 반출 | 삭제 요청 시 |
|---|---|---|---|
| account | users, user_profiles | 포함(`email_canonical` 제외) | 삭제 |
| credentials | auth_identities, auth_sessions, password_reset_tokens | **제외** | 삭제 |
| career | user_experiences, user_projects, user_project_skills, user_skills, user_target_roles | 포함 | 삭제 |
| documents | user_documents, document_analyses, document_chunks | 메타데이터 + 파일(`storage_key` 제외) | 저장소 파일까지 삭제 |
| consents | user_consents | 포함 | **익명화 보존**(동의 증빙) |
| activity | user_job_bookmarks, behavior_events, recommendation_feedback | 포함 | 삭제 |
| derived | skill_gap_*, recommendation_*, match_evaluations, user_segment_assignments | 포함(`model_version_id` 제외) | 삭제 |
| ai_runs | agent_*, retrieval_* | 요약만(프롬프트·응답 원문 제외) | 삭제 |
| audit | audit_events | 요약만 | **익명화 보존**(T83, 보존 기한까지) |
| ai_usage | ai_usage_records | 제외 | **익명화 보존** |
| deletion_requests | account_deletion_requests | 포함 | **익명화 보존**(처리 증빙) |

어떤 경우에도 반출하지 않는 열: `password_hash`, `refresh_token_hash`, `token_hash`, `client_ip_hash`, `storage_key`, `row_hash`.

T128 공개 프로필 공유 링크는 삭제 요청 접수 즉시 모두 철회합니다.

## 7. 감사 기록

- 모든 전이는 T83 감사 이벤트를 남깁니다(`privacy.dsr.*`, retention_class `security`).
- 메타데이터에는 `request_id`, `request_type`, `from`, `to`, `reason_code`만 넣습니다. 이메일·파일 내용·토큰은 넣지 않습니다(T83 §4 금지 필드).
- 다운로드 성공·실패(`privacy.dsr.download`)도 남깁니다.

## 8. 불변 조건 (시험으로 고정)

- **D-INV1** 본인 요청만 본인 데이터에 접근한다. 다른 사용자 요청은 존재를 숨긴다(404)
- **D-INV2** 열람·삭제·반출은 10분 안 재인증 없이 접수하지 않는다
- **D-INV3** 비밀번호 해시·토큰 해시·IP 해시·저장 키는 반출하지 않는다
- **D-INV4** 반려·실패는 사유 코드가 있어야 한다
- **D-INV5** 담당자는 자기 요청을 승인·반려하지 않는다
- **D-INV6** 종료 상태에서는 다른 상태로 가지 않는다
- **D-INV7** 모든 전이는 T83 감사 이벤트를 남긴다. 메타데이터에 개인정보 원문을 넣지 않는다
- **D-INV8** 삭제는 보존 대상(감사·동의·탈퇴 기록·AI 사용량)을 지우지 않고 익명화한다
- **D-INV9** 반출 다운로드는 1회·24시간만 유효하고, 토큰은 SHA-256 해시로만 저장한다

## 9. 결정 필요 (PM·법무)

1. 처리 기한(10일 후보)과 유형별 요청 횟수 제한
2. `privacy_officer` 역할 신설 또는 `admin` 임시 매핑
3. 동의·감사·탈퇴 기록의 익명화 보존 기간(T83 security 2년 후보, D-06 30일 초안)
4. 비활성 계정의 요청 경로(assisted)와 탈퇴 취소 재인증 방식(T31 HOLD)
5. 처리 정지(processing restriction) 요청 유형 추가 여부
6. 반출 형식(JSON 묶음 + 원본 문서) 확정
