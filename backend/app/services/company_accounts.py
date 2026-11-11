"""T123 기업 등록·초대·소속 관리 서비스 (T121 정책·T122 데이터 계약, 모두 PROPOSED).

- 권한: company_policy.org_decision (소속 아님 404, 역할 부족·상태 제한 403).
- 초대 토큰: 32바이트 임의값. 저장은 SHA-256 해시만, 원문은 메일로 1회. 응답·로그·감사에 넣지 않는다.
- 수락 실패(없음·만료·취소·다른 이메일)는 모두 같은 404. 이미 멤버면 409.
- 마지막 owner 강등·제외·탈퇴는 409. 모든 변경은 저장소 잠금 안에서(동시 요청에도 owner 0명 불가).
- 저장소: MemoryCompanyRepository 만 있다. DB 저장소는 정식 migration 승인 뒤(T122 제안 DDL) — 그 전에는
  라우터가 503 을 돌려준다(app/routers/company_accounts.py).
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.core.security import canonical_email
from app.services.company_policy import Outcome, org_decision
from app.services.mail import MailSender, OutgoingMail
from app.services.notifications import mask_email

DEFAULT_TTL = timedelta(hours=72)
MAX_TTL = timedelta(days=7)
MAX_RESENDS = 5


@dataclass(frozen=True)
class Organization:
    organization_id: uuid.UUID
    name: str
    status: str
    linked_company_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    version: int = 1
    status_reason: str | None = None
    verified_at: datetime | None = None
    verified_by: uuid.UUID | None = None


@dataclass(frozen=True)
class Member:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    joined_at: datetime
    version: int = 1


@dataclass(frozen=True)
class Invitation:
    invitation_id: uuid.UUID
    organization_id: uuid.UUID
    email_canonical: str
    role: str
    token_hash: str
    status: str
    invited_by: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    resend_count: int = 0
    closed_at: datetime | None = None
    accepted_by: uuid.UUID | None = None


@dataclass(frozen=True)
class UserInfo:
    user_id: uuid.UUID
    email: str
    display_name: str


class UserDirectory(Protocol):
    def get(self, user_id: uuid.UUID) -> UserInfo | None: ...


@dataclass
class MemoryCompanyRepository:
    """시험·데모용 저장소. 하나의 잠금으로 직렬화해 T122 제약(부분 유일·owner 최소 1명)을 지킨다."""

    organizations: dict[uuid.UUID, Organization] = field(default_factory=dict)
    members: dict[tuple[uuid.UUID, uuid.UUID], Member] = field(default_factory=dict)
    invitations: dict[uuid.UUID, Invitation] = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def role_of(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        member = self.members.get((organization_id, user_id))
        return member.role if member else None

    def owners(self, organization_id: uuid.UUID) -> int:
        return sum(1 for (org, _), m in self.members.items() if org == organization_id and m.role == "owner")

    def record(self, action: str, actor: uuid.UUID | None, organization_id: uuid.UUID, resource: str,
               at: datetime) -> None:
        # 이메일·토큰은 남기지 않는다(T122 §5)
        self.audit.append({"action_code": action, "actor_user_id": actor, "organization_id": organization_id,
                           "resource_id": resource, "occurred_at": at})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CompanyAccountService:
    def __init__(self, repo: MemoryCompanyRepository, users: UserDirectory, mail: MailSender,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
                 invite_link_base: str = "/company-invitations/accept"):
        self.repo, self.users, self.mail, self.clock = repo, users, mail, clock
        self.token_factory, self.link_base = token_factory, invite_link_base

    # ------------------------------------------------------------ 공통
    def _org(self, organization_id: uuid.UUID) -> Organization:
        org = self.repo.organizations.get(organization_id)
        if org is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="organization missing")
        return org

    def _authorize(self, action: str, organization_id: uuid.UUID, user_id: uuid.UUID) -> Organization:
        org = self.repo.organizations.get(organization_id)
        role = self.repo.role_of(organization_id, user_id) if org else None
        outcome = org_decision(action, role, org.status if org else "closed")
        if outcome is Outcome.HIDDEN:
            raise AppError(ErrorCode.NOT_FOUND, log_detail=f"{action}: not a member or hidden org")
        if outcome is Outcome.FORBIDDEN:
            raise AppError(ErrorCode.FORBIDDEN, log_detail=f"{action}: role {role} / status {org.status}")
        return org

    @staticmethod
    def _version(current: int, expected: int) -> None:
        if current != expected:
            raise AppError(ErrorCode.CONFLICT, log_detail="version mismatch")

    # ------------------------------------------------------------ 조직
    def register(self, user_id: uuid.UUID, name: str, linked_company_id: uuid.UUID | None) -> tuple[Organization, str]:
        now = self.clock()
        with self.repo.lock:
            if linked_company_id and any(o.linked_company_id == linked_company_id and o.status not in {"closed", "rejected"}
                                         for o in self.repo.organizations.values()):
                raise AppError(ErrorCode.CONFLICT, log_detail="company already linked to an open organization")
            org = Organization(uuid.uuid4(), name.strip(), "pending", linked_company_id, user_id, now)
            self.repo.organizations[org.organization_id] = org
            self.repo.members[(org.organization_id, user_id)] = Member(org.organization_id, user_id, "owner", now)
            self.repo.record("org.register", user_id, org.organization_id, str(org.organization_id), now)
        return org, "owner"

    def my_organizations(self, user_id: uuid.UUID) -> list[tuple[Organization, str]]:
        out = []
        for (org_id, uid), member in self.repo.members.items():
            org = self.repo.organizations.get(org_id)
            if uid == user_id and org and org.status not in {"closed", "rejected"}:
                out.append((org, member.role))
        return sorted(out, key=lambda pair: pair[0].created_at)

    def get(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> Organization:
        return self._authorize("org.view_console", organization_id, user_id)

    def verify(self, admin: uuid.UUID, admin_roles: frozenset[str], organization_id: uuid.UUID, decision: str,
               reason: str | None, version: int) -> Organization:
        if "admin" not in admin_roles:
            raise AppError(ErrorCode.FORBIDDEN, log_detail="org.verify requires admin")
        now = self.clock()
        with self.repo.lock:
            org = self._org(organization_id)
            if self.repo.role_of(organization_id, admin):
                raise AppError(ErrorCode.FORBIDDEN, log_detail="admin is a member of this organization (not self)")
            if org.status != "pending":
                raise AppError(ErrorCode.CONFLICT, log_detail="organization not pending")
            self._version(org.version, version)
            if decision == "approve":
                org = replace(org, status="active", verified_at=now, verified_by=admin, version=org.version + 1)
            else:
                if not (reason or "").strip():
                    raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="reject needs a reason")
                org = replace(org, status="rejected", status_reason=reason.strip(), version=org.version + 1)
            self.repo.organizations[organization_id] = org
            self.repo.record(f"org.verify.{decision}", admin, organization_id, str(organization_id), now)
        return org

    # ------------------------------------------------------------ 멤버
    def members(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[tuple[Member, UserInfo | None]]:
        self._authorize("member.list", organization_id, user_id)
        rows = [m for (org, _), m in self.repo.members.items() if org == organization_id]
        return [(m, self.users.get(m.user_id)) for m in sorted(rows, key=lambda m: m.joined_at)]

    def change_role(self, user_id: uuid.UUID, organization_id: uuid.UUID, target: uuid.UUID, role: str,
                    version: int) -> Member:
        now = self.clock()
        with self.repo.lock:
            self._authorize("member.change_role", organization_id, user_id)
            member = self.repo.members.get((organization_id, target))
            if member is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="member missing")
            self._version(member.version, version)
            if member.role == "owner" and role != "owner" and self.repo.owners(organization_id) <= 1:
                raise AppError(ErrorCode.CONFLICT, log_detail="last owner cannot be demoted")
            member = replace(member, role=role, version=member.version + 1)
            self.repo.members[(organization_id, target)] = member
            self.repo.record("org.member.role_change", user_id, organization_id, str(target), now)
        return member

    def remove(self, user_id: uuid.UUID, organization_id: uuid.UUID, target: uuid.UUID) -> None:
        now = self.clock()
        with self.repo.lock:
            action = "member.leave" if target == user_id else "member.remove"
            self._authorize(action, organization_id, user_id)
            member = self.repo.members.get((organization_id, target))
            if member is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="member missing")
            if member.role == "owner" and self.repo.owners(organization_id) <= 1:
                raise AppError(ErrorCode.CONFLICT, log_detail="last owner cannot leave or be removed")
            del self.repo.members[(organization_id, target)]
            self.repo.record(f"org.{action}", user_id, organization_id, str(target), now)

    # ------------------------------------------------------------ 초대
    def _send(self, email: str, token: str) -> None:
        if not self.mail.available:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="mail provider not configured")
        self.mail.send(OutgoingMail(to=email, template="organization_invitation", link=f"{self.link_base}#token={token}"))

    def invitations(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[Invitation]:
        self._authorize("member.invite", organization_id, user_id)
        now = self.clock()
        with self.repo.lock:
            self._expire(organization_id, now)
            rows = [i for i in self.repo.invitations.values() if i.organization_id == organization_id]
        return sorted(rows, key=lambda i: i.created_at, reverse=True)

    def _expire(self, organization_id: uuid.UUID | None, now: datetime) -> None:
        for inv in list(self.repo.invitations.values()):
            if inv.status == "pending" and inv.expires_at <= now and (organization_id in (None, inv.organization_id)):
                self.repo.invitations[inv.invitation_id] = replace(inv, status="expired", closed_at=now)

    def invite(self, user_id: uuid.UUID, organization_id: uuid.UUID, email: str, role: str,
               ttl: timedelta = DEFAULT_TTL) -> Invitation:
        if not timedelta(0) < ttl <= MAX_TTL:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="ttl out of range")
        now, address = self.clock(), canonical_email(email)
        token = self.token_factory()
        with self.repo.lock:
            self._authorize("member.invite", organization_id, user_id)
            self._expire(organization_id, now)
            if any(i.organization_id == organization_id and i.email_canonical == address and i.status == "pending"
                   for i in self.repo.invitations.values()):
                raise AppError(ErrorCode.CONFLICT, log_detail="pending invitation exists")
            if any(org == organization_id and (u := self.users.get(uid)) and canonical_email(u.email) == address
                   for (org, uid) in self.repo.members):
                raise AppError(ErrorCode.CONFLICT, log_detail="already a member")
            inv = Invitation(uuid.uuid4(), organization_id, address, role, _hash(token), "pending", user_id, now, now + ttl)
            self._send(email.strip(), token)
            self.repo.invitations[inv.invitation_id] = inv
            self.repo.record("org.invite.create", user_id, organization_id, str(inv.invitation_id), now)
        return inv

    def resend(self, user_id: uuid.UUID, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> Invitation:
        now, token = self.clock(), self.token_factory()
        with self.repo.lock:
            self._authorize("member.invite_resend", organization_id, user_id)
            self._expire(organization_id, now)
            inv = self.repo.invitations.get(invitation_id)
            if inv is None or inv.organization_id != organization_id:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="invitation missing")
            if inv.status != "pending" or inv.resend_count >= MAX_RESENDS:
                raise AppError(ErrorCode.CONFLICT, log_detail="not pending or resend limit")
            ttl = min(inv.expires_at - inv.created_at, MAX_TTL)
            inv = replace(inv, token_hash=_hash(token), created_at=now, expires_at=now + ttl,
                          resend_count=inv.resend_count + 1)
            self._send(inv.email_canonical, token)
            self.repo.invitations[invitation_id] = inv           # 이전 토큰은 해시가 바뀌어 즉시 무효
            self.repo.record("org.invite.resend", user_id, organization_id, str(invitation_id), now)
        return inv

    def revoke(self, user_id: uuid.UUID, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        now = self.clock()
        with self.repo.lock:
            self._authorize("member.invite_revoke", organization_id, user_id)
            inv = self.repo.invitations.get(invitation_id)
            if inv is None or inv.organization_id != organization_id:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="invitation missing")
            if inv.status != "pending":
                raise AppError(ErrorCode.CONFLICT, log_detail="invitation not pending")
            self.repo.invitations[invitation_id] = replace(inv, status="revoked", closed_at=now)
            self.repo.record("org.invite.revoke", user_id, organization_id, str(invitation_id), now)

    def accept(self, user_id: uuid.UUID, user_roles: frozenset[str], token: str) -> tuple[Organization, str]:
        now = self.clock()
        hidden = AppError(ErrorCode.NOT_FOUND, log_detail="invitation token rejected")
        if "admin" in user_roles and "job_seeker" not in user_roles:
            raise hidden                                           # T121: invite.accept 은 운영 관리자 거부
        me = self.users.get(user_id)
        with self.repo.lock:
            self._expire(None, now)
            inv = next((i for i in self.repo.invitations.values() if secrets.compare_digest(i.token_hash, _hash(token))),
                       None)
            if (inv is None or inv.status != "pending" or me is None
                    or canonical_email(me.email) != inv.email_canonical):
                raise hidden
            org = self.repo.organizations.get(inv.organization_id)
            if org is None or org.status != "active":
                raise hidden
            if (inv.organization_id, user_id) in self.repo.members:
                raise AppError(ErrorCode.CONFLICT, log_detail="already a member")
            self.repo.members[(inv.organization_id, user_id)] = Member(inv.organization_id, user_id, inv.role, now)
            self.repo.invitations[inv.invitation_id] = replace(inv, status="accepted", closed_at=now, accepted_by=user_id)
            self.repo.record("org.invite.accept", user_id, inv.organization_id, str(inv.invitation_id), now)
        return org, inv.role


def masked(email: str) -> str:
    return mask_email(email)
