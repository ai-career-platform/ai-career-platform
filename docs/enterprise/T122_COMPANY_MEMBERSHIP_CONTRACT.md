# 기업 계정·소속·초대 데이터 계약 (T122)

> 상태: 정책(T121 역할·D-1~D-5)은 **PROPOSED**. 표는 migration 0008 로 승격되었고, API(T123)는 `COMPANY_ACCOUNTS_API=true` 일 때만 열립니다(기본 꺼짐).
> - DDL: [`database/migrations/0008_organizations.sql`](../../database/migrations/0008_organizations.sql). 제안 `database/proposed/T122_organizations.sql` 을 열·키 이름 그대로 승격했고, 조직별 초대 목록 인덱스(`ix_organization_invitations_org`)와 조건부 GRANT 만 더했습니다. 운영(GCP) 적용은 별도 PM 승인 후에만 합니다.
> - DTO 제안: [`t122_openapi_proposal.yaml`](t122_openapi_proposal.yaml). 확정 계약에 합치지 않습니다.
> - 시험: `backend/tests/test_t122_company_membership_contract.py`. 일회용 PostgreSQL 18에서 제약을 검증합니다.
> - 권한 규칙: T121 [`t121_role_matrix.json`](t121_role_matrix.json). 이 PR은 T121(#210) 위에 쌓여 있습니다.

## 1. ERD (논리)

```
career.users ──< organization_members >── organizations ──o linked_company_id → career.companies (선택)
     │                 (role owner|member)        │
     │                                            └──< organization_invitations
     └── invited_by / accepted_by / created_by / verified_by (ON DELETE SET NULL)
career.audit_events (기존) ← action_code 'org.*'
```

| 표 | 핵심 열 | 제약 |
|---|---|---|
| `organizations` | `status`(pending·active·suspended·closed·rejected), `linked_company_id`, `version` | active면 `verified_at` 필수, closed와 `closed_at`은 함께, 열린 조직은 수집 회사 하나에 하나만 연결 |
| `organization_members` | PK(`organization_id`, `user_id`), `role`(owner·member) | 같은 조직 중복 금지. **다른 조직 다중 소속 허용**(T121 D-2) |
| `organization_invitations` | `email_canonical`, `token_hash`(SHA-256), `status`, `expires_at`, `resend_count` | **TTL 최대 7일**, 조직·이메일당 대기 초대 1개, 토큰 해시 유일·형식, 종료 상태면 `closed_at` 필수, 재전송 최대 5회 |

## 2. 상태 전이

**조직**: `pending → active | rejected`(운영 검증), `active ↔ suspended`(운영), `pending | active | suspended → closed`(owner 또는 운영).
- `closed`, `rejected`는 종료 상태입니다. 다시 열려면 새로 신청합니다.

**초대**:
- 상태는 `pending → accepted | revoked | expired`로만 바뀝니다.
- 재전송하면 같은 행의 `token_hash`, `expires_at`, `resend_count`가 바뀝니다. 이전 토큰은 즉시 무효가 됩니다.
- `expired`는 조회·수락 시점에 처리합니다. 배치 작업은 제안만 합니다(§6).

## 3. 초대 규칙

| 항목 | 규칙 |
|---|---|
| TTL | 기본 72시간, 최대 7일(DB CHECK) |
| 토큰 | 32바이트 이상 임의값. **원문은 저장하지 않고** 메일로 1회만 전달합니다. DB에는 SHA-256만 둡니다. 응답 본문에도 넣지 않습니다 |
| 수락 조건 | 로그인 사용자의 정규화 이메일 = `email_canonical`, 상태 pending, 만료 전 |
| 실패 응답 | 토큰 없음·만료·취소·이메일 불일치를 **모두 같은 404**로 응답합니다(토큰 유효성 추측 방지) |
| 중복 | 같은 조직·이메일에 대기 초대가 있으면 409. 이미 멤버면 409 |
| 권한 상승 방지 | owner만 초대할 수 있습니다. 초대 role이 owner이면 수락 즉시 owner가 됩니다. 기업 역할로 전역 `admin`은 부여할 수 없습니다(T121 INV-7) |
| 검증 전 조직 | pending 조직은 초대할 수 없습니다(T121 INV-8) |

## 4. 소속·삭제 정책

| 상황 | 처리 |
|---|---|
| 멤버 제외·탈퇴 | 행을 삭제해 권한을 즉시 회수합니다. 이력은 `audit_events`에 남깁니다 |
| **마지막 owner** | 강등·제외·탈퇴는 409로 거부합니다(T121 INV-6). DB 제약으로는 표현이 어려워 서비스가 조직 잠금 안에서 검사합니다(T123) |
| 사용자 계정 삭제(T31 purge) | 소속은 **ON DELETE CASCADE**로 삭제합니다. 행위자 참조(created·invited·accepted·verified_by)는 SET NULL입니다. 그 사용자가 마지막 owner였다면 조직은 소유자가 없어지므로, 서비스가 `suspended`(사유 `no_owner`)로 바꾸고 운영이 새 owner를 지정합니다(`admin.role.grant_company`, 제안) |
| 조직 종료 | `closed`로 바꾸고 멤버 행을 삭제하며, 대기 초대는 revoked로 바꿉니다. 조직 행은 감사 연결을 위해 남깁니다 |
| 조직 행 물리 삭제 | 운영 정리 시에만 합니다. 멤버와 초대는 CASCADE입니다 |
| 수집 회사 삭제 | `linked_company_id`를 SET NULL로 바꾸고 조직은 유지합니다 |

## 5. 감사 기록 (기존 `career.audit_events`)

새 표는 만들지 않습니다. 남기는 action_code(제안)는 다음과 같습니다.
- `org.register`, `org.verify.approve`, `org.verify.reject`, `org.suspend`, `org.close`
- `org.invite.create`, `org.invite.resend`, `org.invite.revoke`, `org.invite.accept`
- `org.member.role_change`, `org.member.remove`, `org.member.leave`

기록 원칙은 다음과 같습니다.
- 대상 이메일은 기록하지 않습니다. `resource_id`로 초대 ID나 사용자 ID만 남깁니다.
- 요청 ID는 T112의 request_id와 같은 값을 씁니다.

## 6. 보존

| 데이터 | 보존 |
|---|---|
| 대기 초대 | 만료 시각까지 |
| 종료 초대(이메일 포함) | 종료 후 **30일** 뒤 행 삭제(제안 purge 작업, `ix_organization_invitations_purge`) |
| 소속 | 제외·탈퇴·계정 삭제 즉시 삭제 |
| 감사 | 기존 감사 보존 정책(T83·T84) |

## 7. 결정 필요 (PM)

| ID | 항목 | 제안 |
|---|---|---|
| D-1 | 초대 TTL | 기본 72시간, 최대 7일 |
| D-2 | 종료 초대 보존 | 30일 |
| D-3 | 소유자 없는 조직 | `suspended(no_owner)`, 운영자가 owner 지정 |
| D-4 | 조직명 중복 | 허용(수집 회사 연결만 유일). 사칭 위험은 운영 검증(T121 D-3)으로 대응 |
| D-5 | 멤버 목록의 이메일 | 마스킹만(`k***@example.com`) |
