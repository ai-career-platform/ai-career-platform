"""T123 기업 등록·초대·소속 관리 서비스 (T121 역할 정책 PROPOSED · T122 데이터 계약 = migration 0008).

- 권한: company_policy.org_decision (소속 아님 404, 역할 부족·상태 제한 403).
- 초대 토큰: 32바이트 임의값. 저장은 SHA-256 해시만, 원문은 메일로 1회. 응답·로그·감사에 넣지 않는다.
- 수락 실패(없음·만료·취소·다른 이메일)는 모두 같은 404. 이미 멤버면 409.
- 마지막 owner 강등·제외·탈퇴는 409. 모든 변경은 `repo.transaction()` 안에서 조직 행을 잠근 뒤 검사한다
  (동시 요청에도 owner 0명 불가, 대기 초대 중복·토큰 재사용 불가). 예외가 나면 그 거래의 쓰기는 모두 취소된다.
- 저장소: `CompanyRepository` 규약. MemoryCompanyRepository(단위 시험·데모)와
  SqlCompanyRepository(app/repositories/company_accounts.py, migration 0008).
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
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
OPEN_EXCLUDED = frozenset({"closed", "rejected"})


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


class CompanyRepository(Protocol):
    """서비스가 쓰는 저장소 규약. `lock=True` 는 거래가 끝날 때까지 그 행을 잠근다(SQL: FOR UPDATE)."""

    def transaction(self) -> AbstractContextManager[None]: ...
    def get_organization(self, organization_id: uuid.UUID, *, lock: bool = False) -> Organization | None: ...
    def role_of(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None: ...
    def owners(self, organization_id: uuid.UUID) -> int: ...
    def linked_company_taken(self, company_id: uuid.UUID) -> bool: ...
    def add_organization(self, org: Organization, owner: Member) -> None: ...
    def update_organization(self, org: Organization, now: datetime) -> None: ...
    def memberships(self, user_id: uuid.UUID) -> list[tuple[Organization, str]]: ...
    def list_members(self, organization_id: uuid.UUID) -> list[Member]: ...
    def get_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> Member | None: ...
    def add_member(self, member: Member) -> None: ...
    def update_member(self, member: Member, now: datetime) -> None: ...
    def delete_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None: ...
    def has_member_with_email(self, organization_id: uuid.UUID, email_canonical: str, users: UserDirectory) -> bool: ...
    def expire_invitations(self, organization_id: uuid.UUID, now: datetime) -> None: ...
    def pending_invitation_exists(self, organization_id: uuid.UUID, email_canonical: str) -> bool: ...
    def list_invitations(self, organization_id: uuid.UUID) -> list[Invitation]: ...
    def get_invitation(self, invitation_id: uuid.UUID, *, lock: bool = False) -> Invitation | None: ...
    def find_invitation_by_hash(self, token_hash: str) -> Invitation | None: ...
    def add_invitation(self, inv: Invitation) -> None: ...
    def update_invitation(self, inv: Invitation) -> None: ...
    def record(self, action: str, actor: uuid.UUID | None, organization_id: uuid.UUID, resource: str,
               at: datetime) -> None: ...


@dataclass
class MemoryCompanyRepository:
    """시험·데모용 저장소. 하나의 잠금으로 직렬화해 T122 제약(부분 유일·owner 최소 1명)을 지킨다.

    메모리라 거래 취소(rollback)는 없다 — 서비스는 검사를 모두 마친 뒤에 쓴다.
    """

    organizations: dict[uuid.UUID, Organization] = field(default_factory=dict)
    members: dict[tuple[uuid.UUID, uuid.UUID], Member] = field(default_factory=dict)
    invitations: dict[uuid.UUID, Invitation] = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.lock:
            yield

    def get_organization(self, organization_id: uuid.UUID, *, lock: bool = False) -> Organization | None:
        return self.organizations.get(organization_id)

    def role_of(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        member = self.members.get((organization_id, user_id))
        return member.role if member else None

    def owners(self, organization_id: uuid.UUID) -> int:
        return sum(1 for (org, _), m in self.members.items() if org == organization_id and m.role == "owner")

    def linked_company_taken(self, company_id: uuid.UUID) -> bool:
        return any(o.linked_company_id == company_id and o.status not in OPEN_EXCLUDED
                   for o in self.organizations.values())

    def add_organization(self, org: Organization, owner: Member) -> None:
        self.organizations[org.organization_id] = org
        self.members[(owner.organization_id, owner.user_id)] = owner

    def update_organization(self, org: Organization, now: datetime) -> None:
        self.organizations[org.organization_id] = org

    def memberships(self, user_id: uuid.UUID) -> list[tuple[Organization, str]]:
        out = []
        for (org_id, uid), member in self.members.items():
            org = self.organizations.get(org_id)
            if uid == user_id and org and org.status not in OPEN_EXCLUDED:
                out.append((org, member.role))
        return sorted(out, key=lambda pair: pair[0].created_at)

    def list_members(self, organization_id: uuid.UUID) -> list[Member]:
        return sorted((m for (org, _), m in self.members.items() if org == organization_id), key=lambda m: m.joined_at)

    def get_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> Member | None:
        return self.members.get((organization_id, user_id))

    def add_member(self, member: Member) -> None:
        self.members[(member.organization_id, member.user_id)] = member

    def update_member(self, member: Member, now: datetime) -> None:
        self.members[(member.organization_id, member.user_id)] = member

    def delete_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        del self.members[(organization_id, user_id)]

    def has_member_with_email(self, organization_id: uuid.UUID, email_canonical: str, users: UserDirectory) -> bool:
        return any(org == organization_id and (u := users.get(uid)) and canonical_email(u.email) == email_canonical
                   for (org, uid) in self.members)

    def expire_invitations(self, organization_id: uuid.UUID, now: datetime) -> None:
        for inv in list(self.invitations.values()):
            if inv.status == "pending" and inv.expires_at <= now and inv.organization_id == organization_id:
                self.invitations[inv.invitation_id] = replace(inv, status="expired", closed_at=now)

    def pending_invitation_exists(self, organization_id: uuid.UUID, email_canonical: str) -> bool:
        return any(i.organization_id == organization_id and i.email_canonical == email_canonical
                   and i.status == "pending" for i in self.invitations.values())

    def list_invitations(self, organization_id: uuid.UUID) -> list[Invitation]:
        rows = [i for i in self.invitations.values() if i.organization_id == organization_id]
        return sorted(rows, key=lambda i: i.created_at, reverse=True)

    def get_invitation(self, invitation_id: uuid.UUID, *, lock: bool = False) -> Invitation | None:
        return self.invitations.get(invitation_id)

    def find_invitation_by_hash(self, token_hash: str) -> Invitation | None:
        return next((i for i in self.invitations.values() if secrets.compare_digest(i.token_hash, token_hash)), None)

    def add_invitation(self, inv: Invitation) -> None:
        self.invitations[inv.invitation_id] = inv

    def update_invitation(self, inv: Invitation) -> None:
        self.invitations[inv.invitation_id] = inv

    def record(self, action: str, actor: uuid.UUID | None, organization_id: uuid.UUID, resource: str,
               at: datetime) -> None:
        # 이메일·토큰은 남기지 않는다(T122 §5)
        self.audit.append({"action_code": action, "actor_user_id": actor, "organization_id": organization_id,
                           "resource_id": resource, "occurred_at": at})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CompanyAccountService:
    def __init__(self, repo: CompanyRepository, users: UserDirectory, mail: MailSender,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
                 invite_link_base: str = "/company-invitations/accept"):
        self.repo, self.users, self.mail, self.clock = repo, users, mail, clock
        self.token_factory, self.link_base = token_factory, invite_link_base

    # ------------------------------------------------------------ 공통
    def _authorize(self, action: str, organization_id: uuid.UUID, user_id: uuid.UUID, *,
                   lock: bool = False) -> Organization:
        org = self.repo.get_organization(organization_id, lock=lock)
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
        with self.repo.transaction():
            if linked_company_id and self.repo.linked_company_taken(linked_company_id):
                raise AppError(ErrorCode.CONFLICT, log_detail="company already linked to an open organization")
            org = Organization(uuid.uuid4(), name.strip(), "pending", linked_company_id, user_id, now)
            self.repo.add_organization(org, Member(org.organization_id, user_id, "owner", now))
            self.repo.record("org.register", user_id, org.organization_id, str(org.organization_id), now)
        return org, "owner"

    def my_organizations(self, user_id: uuid.UUID) -> list[tuple[Organization, str]]:
        return self.repo.memberships(user_id)

    def get(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> Organization:
        return self._authorize("org.view_console", organization_id, user_id)

    def verify(self, admin: uuid.UUID, admin_roles: frozenset[str], organization_id: uuid.UUID, decision: str,
               reason: str | None, version: int) -> Organization:
        if "admin" not in admin_roles:
            raise AppError(ErrorCode.FORBIDDEN, log_detail="org.verify requires admin")
        now = self.clock()
        with self.repo.transaction():
            org = self.repo.get_organization(organization_id, lock=True)
            if org is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="organization missing")
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
            self.repo.update_organization(org, now)
            self.repo.record(f"org.verify.{decision}", admin, organization_id, str(organization_id), now)
        return org

    # ------------------------------------------------------------ 멤버
    def members(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[tuple[Member, UserInfo | None]]:
        self._authorize("member.list", organization_id, user_id)
        return [(m, self.users.get(m.user_id)) for m in self.repo.list_members(organization_id)]

    def change_role(self, user_id: uuid.UUID, organization_id: uuid.UUID, target: uuid.UUID, role: str,
                    version: int) -> Member:
        now = self.clock()
        with self.repo.transaction():
            self._authorize("member.change_role", organization_id, user_id, lock=True)
            member = self.repo.get_member(organization_id, target)
            if member is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="member missing")
            self._version(member.version, version)
            if member.role == "owner" and role != "owner" and self.repo.owners(organization_id) <= 1:
                raise AppError(ErrorCode.CONFLICT, log_detail="last owner cannot be demoted")
            member = replace(member, role=role, version=member.version + 1)
            self.repo.update_member(member, now)
            self.repo.record("org.member.role_change", user_id, organization_id, str(target), now)
        return member

    def remove(self, user_id: uuid.UUID, organization_id: uuid.UUID, target: uuid.UUID) -> None:
        now = self.clock()
        with self.repo.transaction():
            action = "member.leave" if target == user_id else "member.remove"
            self._authorize(action, organization_id, user_id, lock=True)
            member = self.repo.get_member(organization_id, target)
            if member is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="member missing")
            if member.role == "owner" and self.repo.owners(organization_id) <= 1:
                raise AppError(ErrorCode.CONFLICT, log_detail="last owner cannot leave or be removed")
            self.repo.delete_member(organization_id, target)
            self.repo.record(f"org.{action}", user_id, organization_id, str(target), now)

    # ------------------------------------------------------------ 초대
    def _send(self, email: str, token: str) -> None:
        if not self.mail.available:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="mail provider not configured")
        self.mail.send(OutgoingMail(to=email, template="organization_invitation", link=f"{self.link_base}#token={token}"))

    def invitations(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[Invitation]:
        now = self.clock()
        with self.repo.transaction():
            self._authorize("member.invite", organization_id, user_id, lock=True)
            self.repo.expire_invitations(organization_id, now)
            return self.repo.list_invitations(organization_id)

    def invite(self, user_id: uuid.UUID, organization_id: uuid.UUID, email: str, role: str,
               ttl: timedelta = DEFAULT_TTL) -> Invitation:
        if not timedelta(0) < ttl <= MAX_TTL:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="ttl out of range")
        now, address = self.clock(), canonical_email(email)
        token = self.token_factory()
        with self.repo.transaction():
            self._authorize("member.invite", organization_id, user_id, lock=True)
            self.repo.expire_invitations(organization_id, now)
            if self.repo.pending_invitation_exists(organization_id, address):
                raise AppError(ErrorCode.CONFLICT, log_detail="pending invitation exists")
            if self.repo.has_member_with_email(organization_id, address, self.users):
                raise AppError(ErrorCode.CONFLICT, log_detail="already a member")
            inv = Invitation(uuid.uuid4(), organization_id, address, role, _hash(token), "pending", user_id, now, now + ttl)
            self._send(email.strip(), token)
            self.repo.add_invitation(inv)
            self.repo.record("org.invite.create", user_id, organization_id, str(inv.invitation_id), now)
        return inv

    def resend(self, user_id: uuid.UUID, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> Invitation:
        now, token = self.clock(), self.token_factory()
        with self.repo.transaction():
            self._authorize("member.invite_resend", organization_id, user_id, lock=True)
            self.repo.expire_invitations(organization_id, now)
            inv = self.repo.get_invitation(invitation_id, lock=True)
            if inv is None or inv.organization_id != organization_id:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="invitation missing")
            if inv.status != "pending" or inv.resend_count >= MAX_RESENDS:
                raise AppError(ErrorCode.CONFLICT, log_detail="not pending or resend limit")
            ttl = min(inv.expires_at - inv.created_at, MAX_TTL)
            inv = replace(inv, token_hash=_hash(token), created_at=now, expires_at=now + ttl,
                          resend_count=inv.resend_count + 1)
            self._send(inv.email_canonical, token)
            self.repo.update_invitation(inv)                     # 이전 토큰은 해시가 바뀌어 즉시 무효
            self.repo.record("org.invite.resend", user_id, organization_id, str(invitation_id), now)
        return inv

    def revoke(self, user_id: uuid.UUID, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        now = self.clock()
        with self.repo.transaction():
            self._authorize("member.invite_revoke", organization_id, user_id, lock=True)
            inv = self.repo.get_invitation(invitation_id, lock=True)
            if inv is None or inv.organization_id != organization_id:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="invitation missing")
            if inv.status != "pending":
                raise AppError(ErrorCode.CONFLICT, log_detail="invitation not pending")
            self.repo.update_invitation(replace(inv, status="revoked", closed_at=now))
            self.repo.record("org.invite.revoke", user_id, organization_id, str(invitation_id), now)

    def accept(self, user_id: uuid.UUID, user_roles: frozenset[str], token: str) -> tuple[Organization, str]:
        now, digest = self.clock(), _hash(token)
        hidden = AppError(ErrorCode.NOT_FOUND, log_detail="invitation token rejected")
        if "admin" in user_roles and "job_seeker" not in user_roles:
            raise hidden                                           # T121: invite.accept 은 운영 관리자 거부
        me = self.users.get(user_id)
        found = self.repo.find_invitation_by_hash(digest)
        if found is None:
            raise hidden
        with self.repo.transaction():
            # 잠금 순서는 다른 변경과 같다(조직 → 초대). 잠근 뒤 초대를 다시 읽어 동시 수락·재전송·취소를 걸러낸다.
            org = self.repo.get_organization(found.organization_id, lock=True)
            self.repo.expire_invitations(found.organization_id, now)
            inv = self.repo.get_invitation(found.invitation_id, lock=True)
            if (inv is None or inv.status != "pending" or not secrets.compare_digest(inv.token_hash, digest)
                    or inv.expires_at <= now or me is None or canonical_email(me.email) != inv.email_canonical):
                raise hidden
            if org is None or org.status != "active":
                raise hidden
            if self.repo.role_of(inv.organization_id, user_id):
                raise AppError(ErrorCode.CONFLICT, log_detail="already a member")
            self.repo.add_member(Member(inv.organization_id, user_id, inv.role, now))
            self.repo.update_invitation(replace(inv, status="accepted", closed_at=now, accepted_by=user_id))
            self.repo.record("org.invite.accept", user_id, inv.organization_id, str(inv.invitation_id), now)
        return org, inv.role


def masked(email: str) -> str:
    return mask_email(email)
