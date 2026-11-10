"""T93 비밀번호 재설정 저장소 — 0001 의 password_reset_tokens 표를 그대로 씁니다(Migration 없음).

토큰 원문은 저장하지 않고 sha256 hex(token_hash)만 저장합니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ResetToken:
    token_id: UUID
    user_id: UUID
    expires_at: datetime
    used_at: datetime | None
    user_status: str


class RecoveryRepository(Protocol):
    def find_active_local_user(self, email_canonical: str) -> UUID | None: ...
    def create_token(self, user_id: UUID, token_hash: str, now: datetime, expires_at: datetime) -> None: ...
    def lock_token(self, token_hash: str) -> ResetToken | None: ...
    def consume(self, token: ResetToken, password_hash: str, now: datetime, request_id: str | None) -> int: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class SqlRecoveryRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def find_active_local_user(self, email_canonical):
        return self.db.execute(text(
            "SELECT i.user_id FROM career.auth_identities i JOIN career.users u ON u.user_id = i.user_id "
            "WHERE i.provider = 'local' AND i.subject = :email AND u.status = 'active'"), {"email": email_canonical}).scalar()

    def create_token(self, user_id, token_hash, now, expires_at):
        self.db.execute(text("INSERT INTO career.password_reset_tokens (user_id, token_hash, created_at, expires_at) "
                             "VALUES (:u, :h, :n, :e)"), {"u": user_id, "h": token_hash, "n": now, "e": expires_at})

    def lock_token(self, token_hash):
        row = self.db.execute(text(
            "SELECT t.token_id, t.user_id, t.expires_at, t.used_at, u.status FROM career.password_reset_tokens t "
            "JOIN career.users u ON u.user_id = t.user_id WHERE t.token_hash = :h FOR UPDATE OF t"), {"h": token_hash}).one_or_none()
        return ResetToken(*row) if row else None

    def consume(self, token, password_hash, now, request_id):
        """한 트랜잭션: 비밀번호 변경 → 이 토큰과 남은 토큰 모두 사용 처리 → 모든 세션 종료 → 감사 기록. 종료한 세션 수를 돌려줌."""
        self.db.execute(text("UPDATE career.auth_identities SET password_hash = :p, updated_at = :n "
                             "WHERE user_id = :u AND provider = 'local'"), {"p": password_hash, "n": now, "u": token.user_id})
        self.db.execute(text("UPDATE career.password_reset_tokens SET used_at = :n WHERE user_id = :u AND used_at IS NULL"),
                        {"n": now, "u": token.user_id})
        revoked = self.db.execute(text("UPDATE career.auth_sessions SET revoked_at = :n "
                                       "WHERE user_id = :u AND revoked_at IS NULL"), {"n": now, "u": token.user_id}).rowcount
        self.db.execute(text("INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, request_id) "
                             "VALUES (:u, 'auth.password.reset', 'user', :u, :r)"), {"u": token.user_id, "r": request_id})
        return revoked

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
