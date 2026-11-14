"""T123 기업 조직·소속·초대 DB 접근. 표: database/migrations/0008_organizations.sql (T122 데이터 계약).

- 값은 모두 바인딩 변수로만 전달한다. 조직 범위 쿼리는 organization_id 로 묶는다(서비스가 권한을 먼저 판정).
- 동시성: 변경은 `transaction()` 안에서 조직 행을 `FOR UPDATE` 로 잠근 뒤 검사한다(서비스 `lock=True`).
  같은 조직의 역할 변경·제외·초대·수락이 직렬화되어 마지막 owner 보호·대기 초대 하나·토큰 1회 사용이 지켜진다.
  잠금 순서는 항상 조직 → 초대.
- 초대는 token_hash(UNIQUE) 로만 찾는다. 토큰 원문은 이 모듈에 들어오지 않는다.
- 감사는 career.audit_events(action_code 'org.*', resource_id = 조직·사용자·초대 ID). 이메일·토큰은 남기지 않는다.
- 이 모듈은 로그를 쓰지 않는다.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.services.company_accounts import Invitation, Member, Organization, UserDirectory, UserInfo

_ORG_COLUMNS = ("organization_id, name, status, linked_company_id, created_by_user_id, created_at, version, "
                "status_reason, verified_at, verified_by_user_id")
_MEMBER_COLUMNS = "organization_id, user_id, role, joined_at, version"
_INV_COLUMNS = ("invitation_id, organization_id, email_canonical, role, token_hash, status, invited_by_user_id, "
                "created_at, expires_at, resend_count, closed_at, accepted_by_user_id")

# audit_events.resource_type — resource_id 가 가리키는 것
_RESOURCE_TYPES = {"org.register": "organization", "org.verify.approve": "organization",
                   "org.verify.reject": "organization", "org.member.role_change": "organization_member",
                   "org.member.remove": "organization_member", "org.member.leave": "organization_member"}
_SQLSTATE_UNIQUE, _SQLSTATE_FK = "23505", "23503"


def _org(r) -> Organization:
    return Organization(organization_id=r.organization_id, name=r.name, status=r.status,
                        linked_company_id=r.linked_company_id, created_by=r.created_by_user_id,
                        created_at=r.created_at, version=r.version, status_reason=r.status_reason,
                        verified_at=r.verified_at, verified_by=r.verified_by_user_id)


def _member(r) -> Member:
    return Member(organization_id=r.organization_id, user_id=r.user_id, role=r.role, joined_at=r.joined_at,
                  version=r.version)


def _inv(r) -> Invitation:
    return Invitation(invitation_id=r.invitation_id, organization_id=r.organization_id,
                      email_canonical=r.email_canonical, role=r.role, token_hash=r.token_hash.strip(), status=r.status,
                      invited_by=r.invited_by_user_id, created_at=r.created_at, expires_at=r.expires_at,
                      resend_count=r.resend_count, closed_at=r.closed_at, accepted_by=r.accepted_by_user_id)


def _sqlstate(exc: IntegrityError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


class SqlCompanyRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    # ------------------------------------------------------------ 조직
    def get_organization(self, organization_id: UUID, *, lock: bool = False) -> Organization | None:
        row = self.db.execute(text(f"SELECT {_ORG_COLUMNS} FROM career.organizations WHERE organization_id = :o"
                                   + (" FOR UPDATE" if lock else "")), {"o": organization_id}).first()
        return _org(row) if row else None

    def role_of(self, organization_id: UUID, user_id: UUID) -> str | None:
        return self.db.execute(text("SELECT role FROM career.organization_members "
                                    "WHERE organization_id = :o AND user_id = :u"),
                               {"o": organization_id, "u": user_id}).scalar()

    def owners(self, organization_id: UUID) -> int:
        return self.db.execute(text("SELECT count(*) FROM career.organization_members "
                                    "WHERE organization_id = :o AND role = 'owner'"), {"o": organization_id}).scalar_one()

    def linked_company_taken(self, company_id: UUID) -> bool:
        return self.db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM career.organizations WHERE linked_company_id = :c "
            "AND status NOT IN ('closed', 'rejected'))"), {"c": company_id}).scalar_one()

    def add_organization(self, org: Organization, owner: Member) -> None:
        try:
            with self.db.begin_nested():
                self.db.execute(text(
                    "INSERT INTO career.organizations (organization_id, name, status, linked_company_id, "
                    "created_by_user_id, version, created_at, updated_at) "
                    "VALUES (:o, :name, :status, :company, :by, :v, :now, :now)"),
                    {"o": org.organization_id, "name": org.name, "status": org.status, "company": org.linked_company_id,
                     "by": org.created_by, "v": org.version, "now": org.created_at})
                self.db.execute(text(
                    "INSERT INTO career.organization_members (organization_id, user_id, role, joined_at, role_changed_at) "
                    "VALUES (:o, :u, :role, :now, :now)"),
                    {"o": owner.organization_id, "u": owner.user_id, "role": owner.role, "now": owner.joined_at})
        except IntegrityError as exc:
            if _sqlstate(exc) == _SQLSTATE_UNIQUE:       # 동시에 같은 수집 회사를 연결(ux_organizations_linked_company)
                raise AppError(ErrorCode.CONFLICT, log_detail="company already linked to an open organization") from None
            if _sqlstate(exc) == _SQLSTATE_FK:           # 없는 수집 회사 ID
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="linked company does not exist") from None
            raise

    def update_organization(self, org: Organization, now: datetime) -> None:
        self.db.execute(text(
            "UPDATE career.organizations SET status = :status, status_reason = :reason, verified_at = :verified_at, "
            "verified_by_user_id = :verified_by, version = :v, updated_at = :now WHERE organization_id = :o"),
            {"o": org.organization_id, "status": org.status, "reason": org.status_reason,
             "verified_at": org.verified_at, "verified_by": org.verified_by, "v": org.version, "now": now})

    def memberships(self, user_id: UUID) -> list[tuple[Organization, str]]:
        rows = self.db.execute(text(
            f"SELECT {', '.join('o.' + c.strip() for c in _ORG_COLUMNS.split(','))}, m.role AS member_role "
            "FROM career.organization_members m JOIN career.organizations o ON o.organization_id = m.organization_id "
            "WHERE m.user_id = :u AND o.status NOT IN ('closed', 'rejected') "
            "ORDER BY o.created_at, o.organization_id"), {"u": user_id})
        return [(_org(r), r.member_role) for r in rows]

    # ------------------------------------------------------------ 멤버
    def list_members(self, organization_id: UUID) -> list[Member]:
        rows = self.db.execute(text(f"SELECT {_MEMBER_COLUMNS} FROM career.organization_members "
                                    "WHERE organization_id = :o ORDER BY joined_at, user_id"), {"o": organization_id})
        return [_member(r) for r in rows]

    def get_member(self, organization_id: UUID, user_id: UUID) -> Member | None:
        row = self.db.execute(text(f"SELECT {_MEMBER_COLUMNS} FROM career.organization_members "
                                   "WHERE organization_id = :o AND user_id = :u"),
                              {"o": organization_id, "u": user_id}).first()
        return _member(row) if row else None

    def add_member(self, member: Member) -> None:
        try:
            with self.db.begin_nested():
                self.db.execute(text(
                    "INSERT INTO career.organization_members (organization_id, user_id, role, joined_at, role_changed_at, "
                    "version) VALUES (:o, :u, :role, :now, :now, :v)"),
                    {"o": member.organization_id, "u": member.user_id, "role": member.role, "now": member.joined_at,
                     "v": member.version})
        except IntegrityError as exc:
            if _sqlstate(exc) == _SQLSTATE_UNIQUE:
                raise AppError(ErrorCode.CONFLICT, log_detail="already a member") from None
            raise

    def update_member(self, member: Member, now: datetime) -> None:
        self.db.execute(text(
            "UPDATE career.organization_members SET role = :role, version = :v, role_changed_at = :now "
            "WHERE organization_id = :o AND user_id = :u"),
            {"o": member.organization_id, "u": member.user_id, "role": member.role, "v": member.version, "now": now})

    def delete_member(self, organization_id: UUID, user_id: UUID) -> None:
        self.db.execute(text("DELETE FROM career.organization_members WHERE organization_id = :o AND user_id = :u"),
                        {"o": organization_id, "u": user_id})

    def has_member_with_email(self, organization_id: UUID, email_canonical: str, users: UserDirectory) -> bool:
        return self.db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM career.organization_members m JOIN career.users u ON u.user_id = m.user_id "
            "WHERE m.organization_id = :o AND u.email_canonical = :e)"),
            {"o": organization_id, "e": email_canonical}).scalar_one()

    # ------------------------------------------------------------ 초대
    def expire_invitations(self, organization_id: UUID, now: datetime) -> None:
        self.db.execute(text(
            "UPDATE career.organization_invitations SET status = 'expired', closed_at = :now "
            "WHERE organization_id = :o AND status = 'pending' AND expires_at <= :now"),
            {"o": organization_id, "now": now})

    def pending_invitation_exists(self, organization_id: UUID, email_canonical: str) -> bool:
        return self.db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM career.organization_invitations WHERE organization_id = :o "
            "AND email_canonical = :e AND status = 'pending')"), {"o": organization_id, "e": email_canonical}).scalar_one()

    def list_invitations(self, organization_id: UUID) -> list[Invitation]:
        rows = self.db.execute(text(f"SELECT {_INV_COLUMNS} FROM career.organization_invitations "
                                    "WHERE organization_id = :o ORDER BY created_at DESC, invitation_id"),
                               {"o": organization_id})
        return [_inv(r) for r in rows]

    def get_invitation(self, invitation_id: UUID, *, lock: bool = False) -> Invitation | None:
        row = self.db.execute(text(f"SELECT {_INV_COLUMNS} FROM career.organization_invitations "
                                   "WHERE invitation_id = :i" + (" FOR UPDATE" if lock else "")),
                              {"i": invitation_id}).first()
        return _inv(row) if row else None

    def find_invitation_by_hash(self, token_hash: str) -> Invitation | None:
        row = self.db.execute(text(f"SELECT {_INV_COLUMNS} FROM career.organization_invitations "
                                   "WHERE token_hash = :h"), {"h": token_hash}).first()
        return _inv(row) if row else None

    def add_invitation(self, inv: Invitation) -> None:
        try:
            with self.db.begin_nested():
                self.db.execute(text(
                    "INSERT INTO career.organization_invitations (invitation_id, organization_id, email_canonical, role, "
                    "token_hash, status, invited_by_user_id, resend_count, created_at, expires_at) "
                    "VALUES (:i, :o, :e, :role, :h, :status, :by, :n, :created, :expires)"),
                    {"i": inv.invitation_id, "o": inv.organization_id, "e": inv.email_canonical, "role": inv.role,
                     "h": inv.token_hash, "status": inv.status, "by": inv.invited_by, "n": inv.resend_count,
                     "created": inv.created_at, "expires": inv.expires_at})
        except IntegrityError as exc:
            if _sqlstate(exc) == _SQLSTATE_UNIQUE:       # ux_organization_invitations_pending
                raise AppError(ErrorCode.CONFLICT, log_detail="pending invitation exists") from None
            raise

    def update_invitation(self, inv: Invitation) -> None:
        self.db.execute(text(
            "UPDATE career.organization_invitations SET token_hash = :h, status = :status, created_at = :created, "
            "expires_at = :expires, resend_count = :n, closed_at = :closed, accepted_by_user_id = :accepted "
            "WHERE invitation_id = :i AND organization_id = :o"),
            {"i": inv.invitation_id, "o": inv.organization_id, "h": inv.token_hash, "status": inv.status,
             "created": inv.created_at, "expires": inv.expires_at, "n": inv.resend_count, "closed": inv.closed_at,
             "accepted": inv.accepted_by})

    # ------------------------------------------------------------ 감사
    def record(self, action: str, actor: UUID | None, organization_id: UUID, resource: str, at: datetime) -> None:
        self.db.execute(text(
            "INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, occurred_at) "
            "VALUES (:actor, :action, :type, :rid, :at)"),
            {"actor": actor, "action": action, "type": _RESOURCE_TYPES.get(action, "organization_invitation"),
             "rid": UUID(resource), "at": at})


class SqlUserDirectory:
    """멤버 표시 이름·이메일(마스킹 전 원문은 응답에 넣지 않는다 — 라우터가 마스킹)."""

    def __init__(self, session: Session) -> None:
        self.db = session

    def get(self, user_id: UUID) -> UserInfo | None:
        row = self.db.execute(text("SELECT user_id, email, display_name FROM career.users WHERE user_id = :u"),
                              {"u": user_id}).first()
        return UserInfo(row.user_id, row.email, row.display_name) if row else None
