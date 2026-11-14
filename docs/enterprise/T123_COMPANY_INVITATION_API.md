# 기업 담당자 등록·초대·접근 API (T123)

> 상태: **구현(기능 플래그 뒤, 기본 꺼짐) / 저장소 PostgreSQL(migration 0008)**
> - 계약: T121 역할 정책(#210, PROPOSED)·T122 데이터 계약(`database/migrations/0008_organizations.sql`).
> - `COMPANY_ACCOUNTS_API=true`일 때만 라우터를 등록합니다. DB 가 없으면 503 `DEPENDENCY_UNAVAILABLE`.
> - 저장소: `app/repositories/company_accounts.py`(`SqlCompanyRepository`, `SqlUserDirectory`). 단위 시험은 메모리 저장소,
>   DB 시험은 `backend/tests/test_t123_company_accounts_postgres.py`(일회용 PostgreSQL 18).
> - 초대 메일은 계정 복구와 같은 `get_mail_sender` 를 씁니다. 공급자 연결 전에는 초대 생성·재전송만 503 입니다.
> - 운영(GCP) migration 적용은 별도 PM 승인 후에만 합니다.

## 1. 엔드포인트 (`/api/v1`)

| 메서드 | 경로 | 행동(T121) | 거부 |
|---|---|---|---|
| POST | `/organizations` | `org.register` → pending, 신청자 owner | 수집 회사 중복 연결 409, 검증 422 |
| GET | `/me/organizations` | 내 소속(종료·반려 제외) | — |
| GET | `/organizations/{id}` | `org.view_console` | 소속 아님·종료 404 |
| GET | `/organizations/{id}/members` | `member.list`. 이메일은 마스킹 | 404 |
| PATCH | `/organizations/{id}/members/{user_id}` | `member.change_role`(owner만) | 담당자 403, 마지막 owner·version 409 |
| DELETE | `/organizations/{id}/members/{user_id}` | `member.remove`(owner) / 본인이면 `member.leave` | 403, 마지막 owner 409 |
| GET·POST | `/organizations/{id}/invitations` | `member.invite`(owner, **active 조직만**) | 담당자·pending 403, 중복·이미 멤버 409, 메일 불가 503 |
| POST | `/organizations/{id}/invitations/{inv}/resend` | 토큰·만료 교체, 최대 5회 | 409 |
| DELETE | `/organizations/{id}/invitations/{inv}` | 취소 | 409 |
| POST | `/organization-invitations/accept` | `invite.accept`(본인 이메일만) | 없음·만료·취소·재전송 전 토큰·다른 이메일 **모두 같은 404**, 이미 멤버 409 |
| POST | `/admin/organizations/{id}/verification` | `org.verify`(운영 관리자, **그 조직 멤버 아님**) | 403, 반려 사유 없음 422, pending 아님·version 409 |

## 2. 보안 규칙

- 권한 판단은 `app/services/company_policy.py`(T121 매트릭스 사본)가 합니다. 시험이 JSON 매트릭스와 같은지 비교합니다.
- 다른 기업·외부인·운영 관리자의 조직 범위 요청은 404입니다(존재 숨김).
- 초대 토큰:
  - 32바이트 임의값이고, 저장은 SHA-256 해시만 합니다.
  - 메일 링크에서는 `#token=`(fragment)으로 전달합니다. 접근 로그·Referer에 남지 않게 하기 위해서이며, T112 F-1 대응입니다.
  - 응답·목록·감사 기록에는 토큰도 이메일 원문도 넣지 않습니다.
- 모든 변경은 한 거래 안에서 조직 행을 `FOR UPDATE` 로 잠근 뒤 검사합니다(잠금 순서 조직 → 초대). 동시 강등·제외에도 owner가
  최소 1명 남고, 같은 이메일 대기 초대는 하나, 같은 토큰 수락은 한 번만 성공합니다(일회용 PG 동시성 시험).
- 감사: `career.audit_events` 에 `org.*` action_code, `resource_type` = `organization`·`organization_member`·`organization_invitation`,
  `resource_id` = 조직·사용자·초대 ID. 이메일·토큰은 남기지 않습니다(이 표에는 조직 ID 열이 없어 멤버·초대 행위의 조직은 대상 ID 로만 추적).
- 없는 수집 회사 ID 로 등록하면 422(`VALIDATION_FAILED`)입니다(FK, DB 저장소에서만 확인).
- 409는 기존 `CONFLICT` 코드 하나로 응답합니다(T116 오류 코드 기준선 유지). 원인은 서버 로그에만 남깁니다.

## 3. 하지 않은 것 (HOLD)

- 실제 메일 발송: 공급자 미정(T96). 시험은 `MemoryMailSender`
- 조직 정보 수정(이름 등) API: 서비스·T121 매트릭스에 해당 행동이 없어 만들지 않았습니다(정책 결정 필요)
- 조직 종료(`org.close`)·정지(`org.suspend`)·운영자 owner 지정 API: 후속
- 계정 삭제 시 소유자 없는 조직을 `suspended`로 바꾸는 처리(T122 §4, D-3 미결): 후속
- 종료 초대 30일 purge(T122 §6, D-2 미결): 후속
