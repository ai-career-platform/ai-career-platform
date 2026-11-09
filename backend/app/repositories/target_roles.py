"""T35 persistence using the request-scoped T14 SQLAlchemy Session."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.target_roles import JobRole, UserTargetRole
from app.schemas.target_roles import JobRoleRef, TargetRole, TargetRoleItem


class TargetRoleRepository(Protocol):
    def list_for_user(self, user_id: UUID) -> list[TargetRole]: ...
    def replace(self, user_id: UUID, items: Sequence[TargetRoleItem]) -> list[TargetRole] | None: ...


class SqlTargetRoleRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_user(self, user_id: UUID) -> list[TargetRole]:
        try:
            rows = self.session.execute(
                select(UserTargetRole, JobRole)
                .join(JobRole, JobRole.job_role_id == UserTargetRole.job_role_id)
                .where(UserTargetRole.user_id == user_id)
                .order_by(UserTargetRole.priority)
            ).all()
            return [
                TargetRole(
                    job_role=JobRoleRef(job_role_id=role.job_role_id, code=role.code, name=role.name),
                    priority=target.priority,
                )
                for target, role in rows
            ]
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def replace(self, user_id: UUID, items: Sequence[TargetRoleItem]) -> list[TargetRole] | None:
        try:
            role_ids = [item.job_role_id for item in items]
            if role_ids:
                existing = set(self.session.scalars(
                    select(JobRole.job_role_id).where(
                        JobRole.job_role_id.in_(role_ids), JobRole.is_active.is_(True)
                    )
                ))
                if existing != set(role_ids):
                    self.session.rollback()
                    return None

            self.session.execute(delete(UserTargetRole).where(UserTargetRole.user_id == user_id))
            now = datetime.now(UTC)
            self.session.add_all([
                UserTargetRole(
                    user_id=user_id,
                    job_role_id=item.job_role_id,
                    priority=item.priority,
                    created_at=now,
                    updated_at=now,
                )
                for item in items
            ])
            self.session.flush()
            result = self.list_for_user(user_id)
            self.session.commit()
            return result
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except Exception:
            self.session.rollback()
            raise
