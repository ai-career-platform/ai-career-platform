"""테스트용 메모리 AuthRepository. PostgresAuthRepository와 같은 의미(트랜잭션 포함)로 동작한다."""

import copy
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from app.repositories.auth import (
    EmailTaken,
    IdentityTaken,
    LocalIdentity,
    NewUser,
    PolicyRecord,
    SessionRecord,
    UserRecord,
)

POLICY_EFFECTIVE = datetime(2026, 11, 6, tzinfo=UTC)
DEFAULT_POLICIES = [
    PolicyRecord("terms", "2026-11", True, "https://docs.ai-career.invalid/terms/2026-11", POLICY_EFFECTIVE),
    PolicyRecord("privacy", "2026-11", True, "https://docs.ai-career.invalid/privacy/2026-11", POLICY_EFFECTIVE),
    PolicyRecord("llm_processing", "2026-11", False, "https://docs.ai-career.invalid/llm/2026-11", POLICY_EFFECTIVE),
]
ROLE_PERMISSIONS = {
    "job_seeker": set(),
    "admin": {"admin.audit.read", "admin.models.read"},
}


class MemoryAuthRepository:
    def __init__(self) -> None:
        self.policies = list(DEFAULT_POLICIES)
        self._committed = self._empty()
        self._state = self._empty()
        self.commits = 0

    @staticmethod
    def _empty() -> dict:
        # identities: local(비교용 이메일 → 행). external: (provider, subject) → 행. emails: 모든 계정의 비교용 이메일
        return {"users": {}, "identities": {}, "external": {}, "emails": {}, "roles": {}, "sessions": {},
                "consents": [], "last_login": {}}

    # ---- helpers for tests
    def grant_role(self, user_id: uuid.UUID, role: str) -> None:
        self._state["roles"].setdefault(user_id, set()).add(role)
        self.commit()

    def revoke_role(self, user_id: uuid.UUID, role: str) -> None:
        self._state["roles"].get(user_id, set()).discard(role)
        self.commit()

    def set_status(self, user_id: uuid.UUID, status: str) -> None:
        self._state["users"][user_id] = replace(self._state["users"][user_id], status=status)
        self.commit()

    def stored(self) -> dict:
        return self._committed

    # ---- AuthRepository
    def current_policies(self, now: datetime) -> list[PolicyRecord]:
        latest: dict[str, PolicyRecord] = {}
        for p in sorted(self.policies, key=lambda p: p.effective_at):
            if p.effective_at <= now:
                latest[p.policy_code] = p
        return list(latest.values())

    def email_exists(self, email_canonical: str) -> bool:
        return email_canonical in self._state["identities"] or email_canonical in self._state["emails"]

    def create_user(self, new: NewUser, now: datetime) -> uuid.UUID:
        # SqlAuthRepository 와 같은 의미: users.email_canonical UNIQUE, (provider, subject) UNIQUE
        if self.email_exists(new.email_canonical):
            raise EmailTaken()
        external_key = (new.identity_provider, new.identity_subject)
        if new.identity_provider != "local" and external_key in self._state["external"]:
            raise IdentityTaken()
        if (new.identity_provider == "local") != (new.password_hash is not None):
            raise ValueError("password_hash is required for local identities only")
        user_id = uuid.uuid4()
        self._state["users"][user_id] = UserRecord(user_id, new.email, new.display_name, "active", now)
        self._state["emails"][new.email_canonical] = user_id
        if new.identity_provider == "local":
            self._state["identities"][new.email_canonical] = {"user_id": user_id, "password_hash": new.password_hash}
        else:
            self._state["external"][external_key] = {"user_id": user_id, "password_hash": None}
        self._state["roles"][user_id] = {new.role_code}
        self._state["consents"].extend((user_id, *c, now) for c in new.consents)
        self._state["last_login"][user_id] = now
        return user_id

    def find_identity(self, provider: str, subject: str) -> uuid.UUID | None:
        if provider == "local":
            row = self._state["identities"].get(subject)
        else:
            row = self._state["external"].get((provider, subject))
        return row["user_id"] if row else None

    def find_local_identity(self, email_canonical: str) -> LocalIdentity | None:
        row = self._state["identities"].get(email_canonical)
        if row is None:
            return None
        return LocalIdentity(row["user_id"], row["password_hash"], self._state["users"][row["user_id"]].status)

    def update_password_hash(self, user_id: uuid.UUID, password_hash: str, now: datetime) -> None:
        for row in self._state["identities"].values():
            if row["user_id"] == user_id:
                row["password_hash"] = password_hash

    def touch_last_login(self, user_id: uuid.UUID, now: datetime) -> None:
        self._state["last_login"][user_id] = now

    def get_user(self, user_id: uuid.UUID) -> UserRecord | None:
        return self._state["users"].get(user_id)

    def role_codes(self, user_id: uuid.UUID) -> list[str]:
        return sorted(self._state["roles"].get(user_id, set()))

    def permission_codes(self, user_id: uuid.UUID) -> list[str]:
        perms: set[str] = set()
        for role in self._state["roles"].get(user_id, set()):
            perms |= ROLE_PERMISSIONS.get(role, set())
        return sorted(perms)

    def create_session(self, user_id, refresh_hash, user_agent, now, expires_at) -> uuid.UUID:
        session_id = uuid.uuid4()
        self._state["sessions"][session_id] = {
            "record": SessionRecord(session_id, user_id, user_agent, now, expires_at, None),
            "hash": refresh_hash,
        }
        return session_id

    def get_session(self, session_id: uuid.UUID) -> SessionRecord | None:
        row = self._state["sessions"].get(session_id)
        return row["record"] if row else None

    def find_session_by_refresh(self, refresh_hash: str) -> SessionRecord | None:
        for row in self._state["sessions"].values():
            if row["hash"] == refresh_hash:
                return row["record"]
        return None

    def rotate_refresh(self, session_id: uuid.UUID, old_hash: str, new_hash: str) -> bool:
        row = self._state["sessions"].get(session_id)
        if row is None or row["hash"] != old_hash or row["record"].revoked_at is not None:
            return False
        row["hash"] = new_hash
        return True

    def list_active_sessions(self, user_id: uuid.UUID, now: datetime) -> list[SessionRecord]:
        rows = [
            r["record"] for r in self._state["sessions"].values()
            if r["record"].user_id == user_id and r["record"].revoked_at is None and r["record"].expires_at > now
        ]
        return sorted(rows, key=lambda r: (r.created_at, str(r.session_id)), reverse=True)

    def revoke_session(self, session_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool:
        row = self._state["sessions"].get(session_id)
        if row is None:
            return False
        rec = row["record"]
        if rec.user_id != user_id or rec.revoked_at is not None or rec.expires_at <= now:
            return False
        row["record"] = replace(rec, revoked_at=now)
        return True

    def expire_session(self, session_id: uuid.UUID, at: datetime) -> None:
        row = self._state["sessions"][session_id]
        row["record"] = replace(row["record"], expires_at=at)
        self.commit()

    def commit(self) -> None:
        self._committed = copy.deepcopy(self._state)
        self.commits += 1

    def rollback(self) -> None:
        self._state = copy.deepcopy(self._committed)


def override_auth_repository(app, repo) -> None:
    """인증 의존성(`get_auth_service`)이 저장소만 바꾼 AuthService를 쓰게 한다.

    설정·시도 제한기는 앱 것을 그대로 써서 실제 요청과 같은 규칙으로 동작한다.
    """
    from app.dependencies.auth import get_auth_service
    from app.services.auth import AuthService

    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        repo, app.state.auth_settings, app.state.attempt_limiter)
