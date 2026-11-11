"""T121 기업 역할 정책(PROPOSED)의 코드 사본 — docs/enterprise/t121_role_matrix.json 과 같아야 한다.

`tests/test_t123_company_accounts.py` 가 이 표와 JSON 매트릭스를 비교한다(어긋나면 실패).
판정: allow | own(본인이 active 멤버인 조직) | self(본인 계정) | deny.
"""

from __future__ import annotations

from enum import StrEnum

ORG_ROLES = ("company_member", "company_owner")

# 이 모듈이 다루는 행동만(기업 계정·소속·초대). 공고(T126)·후보자(T129)는 각 모듈에서.
DECISIONS: dict[str, dict[str, str]] = {
    "org.register": {"job_seeker": "allow", "company_member": "allow", "company_owner": "allow", "admin": "deny"},
    "org.verify": {"job_seeker": "deny", "company_member": "deny", "company_owner": "deny", "admin": "allow"},
    "org.view_console": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "deny"},
    "member.list": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "deny"},
    "member.invite": {"job_seeker": "deny", "company_member": "deny", "company_owner": "own", "admin": "deny"},
    "member.invite_resend": {"job_seeker": "deny", "company_member": "deny", "company_owner": "own", "admin": "deny"},
    "member.invite_revoke": {"job_seeker": "deny", "company_member": "deny", "company_owner": "own", "admin": "deny"},
    "invite.accept": {"job_seeker": "self", "company_member": "self", "company_owner": "self", "admin": "deny"},
    "member.change_role": {"job_seeker": "deny", "company_member": "deny", "company_owner": "own", "admin": "deny"},
    "member.remove": {"job_seeker": "deny", "company_member": "deny", "company_owner": "own", "admin": "deny"},
    "member.leave": {"job_seeker": "deny", "company_member": "self", "company_owner": "self", "admin": "deny"},
    # T126 기업 공고(T125 상태 기계). 게시·반려·내림은 조직 범위가 아니라 운영 관리자 전용(아래 ADMIN_ONLY).
    "posting.draft_create": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "deny"},
    "posting.draft_edit": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "deny"},
    "posting.submit_review": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "deny"},
    "posting.withdraw_review": {"job_seeker": "deny", "company_member": "own", "company_owner": "own",
                                "admin": "deny"},
    "posting.view_internal": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "allow"},
    "posting.close": {"job_seeker": "deny", "company_member": "own", "company_owner": "own", "admin": "allow"},
}

# 운영 관리자만(해당 조직 멤버가 아닐 것 — T80 not self, T125 P-INV-2)
ADMIN_ONLY = {"posting.publish", "posting.reject", "posting.takedown", "org.verify"}

# T121 org_status_rules: active 는 전부, 나머지는 허용 목록만
STATUS_ALLOWED: dict[str, set[str] | None] = {
    "active": None,
    "pending": {"org.view_console", "member.list", "member.leave", "posting.draft_create", "posting.draft_edit",
                "posting.view_internal"},
    "suspended": {"org.view_console", "member.list", "member.leave", "posting.view_internal"},
    "closed": set(),
    "rejected": set(),
}


class Outcome(StrEnum):
    ALLOW = "allow"
    FORBIDDEN = "forbidden"   # 같은 조직, 역할 부족·상태 제한 → 403
    HIDDEN = "hidden"         # 소속이 아님 → 404(존재 숨김)


def org_decision(action: str, member_role: str | None, org_status: str) -> Outcome:
    """조직 범위 행동의 판정. member_role 은 'owner'|'member'|None(소속 아님)."""
    if member_role is None:
        return Outcome.HIDDEN
    decision = DECISIONS[action][f"company_{member_role}"]
    if decision not in {"own", "self"}:
        return Outcome.FORBIDDEN
    allowed = STATUS_ALLOWED.get(org_status, set())
    if allowed is not None and action not in allowed:
        return Outcome.HIDDEN if org_status in {"closed", "rejected"} else Outcome.FORBIDDEN
    return Outcome.ALLOW
