"""T51: existing 0001 tables only (document_analyses, model_versions, user_skills).

No DDL, Migration or Seed. Reuses T49 document locking, T31 consent rows and the
T33 skill policy. ai_usage_records is intentionally NOT written: the mock
provider has no real token usage or cost and none is fabricated.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, and_, column, func, or_, select, table, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.documents import UserDocument
from app.repositories.catalog import skills
from app.repositories.documents import SqlDocumentRepository
from app.repositories.my_skills import SqlMySkillsRepository, UserSkillRecord, user_skills, users
from app.repositories.privacy import SqlPrivacyRepository
from app.repositories.recommendation_runs import model_versions
from app.schemas.catalog import Skill

LLM_POLICY = "llm_processing"
MODEL_CODE = "resume_analysis_mock"
MODEL_VERSION = "mock-fixture-v1"
MODEL_KIND = "rule"  # deterministic fixture; NOT an LLM and not an approved model
MODEL_DESCRIPTION = "T51 synthetic mock analyzer: deterministic fixture output, no LLM or external call"

analyses = table(
    "document_analyses", column("analysis_id", Uuid), column("document_id", Uuid),
    column("model_version_id", Uuid), column("analysis_type", String), column("status", String),
    column("result", JSONB), column("error_code", String),
    column("requested_at", DateTime(timezone=True)), column("completed_at", DateTime(timezone=True)),
    schema="career",
)


@dataclass
class AnalysisRecord:
    analysis_id: UUID
    document_id: UUID
    owner_user_id: UUID
    analysis_type: str
    status: str
    result: dict | None
    error_code: str | None
    model_code: str
    version: str
    kind: str
    requested_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class ClaimedJob:
    analysis_id: UUID
    document_id: UUID
    owner_user_id: UUID
    analysis_type: str


class AnalysisRepository(Protocol):
    def transaction(self): ...
    def lock_document(self, owner: UUID, document_id: UUID): ...
    def llm_consent_granted(self, user_id: UUID, now: datetime) -> bool: ...
    def ensure_model_version(self) -> UUID: ...
    def active_for_document(self, document_id: UUID, analysis_type: str) -> AnalysisRecord | None: ...
    def count_active_for_owner(self, owner: UUID) -> int: ...
    def insert(self, owner: UUID, document_id: UUID, analysis_type: str, model_version_id: UUID,
               now: datetime) -> AnalysisRecord: ...
    def get_owned(self, owner: UUID, analysis_id: UUID, lock: bool = False) -> AnalysisRecord | None: ...
    def expire_stale(self, now: datetime, queue_ttl: timedelta, running_ttl: timedelta) -> int: ...
    def claim_next(self) -> ClaimedJob | None: ...
    def finish(self, analysis_id: UUID, status: str, result: dict | None, error_code: str | None,
               now: datetime) -> bool: ...
    def requeue(self, analysis_id: UUID) -> bool: ...
    def resolve_active_skills(self, codes: list[str]) -> dict[str, Skill]: ...
    def usable_skill_ids(self, owner: UUID, skill_ids: set[UUID]) -> set[UUID]: ...
    def upsert_user_skills(self, owner: UUID, items: dict[UUID, int], now: datetime) -> None: ...
    def list_user_skills(self, owner: UUID) -> list[UserSkillRecord]: ...


class SqlAnalysisRepository:
    def __init__(self, session: Session):
        self.session = session
        self.documents = SqlDocumentRepository(session)
        self.privacy = SqlPrivacyRepository(session)
        self.my_skills = SqlMySkillsRepository(session)

    @contextmanager
    def transaction(self):
        try:
            yield
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except Exception:
            self.session.rollback()
            raise

    def lock_document(self, owner, document_id):
        return self.documents.get(owner, document_id)  # T49: owner-scoped, FOR UPDATE

    def llm_consent_granted(self, user_id, now):
        latest = self.privacy.latest_consent(user_id, LLM_POLICY)
        if latest is None or not latest.granted:
            return False
        policy = self.privacy.current_policy(LLM_POLICY, now)
        return policy is not None and policy.version == latest.policy_version

    def ensure_model_version(self):
        self.session.execute(pg_insert(model_versions).values(
            model_code=MODEL_CODE, version=MODEL_VERSION, kind=MODEL_KIND, description=MODEL_DESCRIPTION,
        ).on_conflict_do_nothing(index_elements=["model_code", "version"]))
        return self.session.scalar(select(model_versions.c.model_version_id).where(
            model_versions.c.model_code == MODEL_CODE, model_versions.c.version == MODEL_VERSION))

    def _select(self):
        a, m = analyses.c, model_versions.c
        return (select(a.analysis_id, a.document_id, UserDocument.owner_user_id, a.analysis_type, a.status,
                       a.result, a.error_code, m.model_code, m.version, m.kind, a.requested_at, a.completed_at)
                .select_from(analyses.join(UserDocument, UserDocument.document_id == a.document_id)
                             .join(model_versions, m.model_version_id == a.model_version_id)))

    def active_for_document(self, document_id, analysis_type):
        a = analyses.c
        row = self.session.execute(self._select().where(
            a.document_id == document_id, a.analysis_type == analysis_type, a.status.in_(["queued", "running"]))
            .order_by(a.requested_at.desc(), a.analysis_id.desc()).limit(1)).first()
        return None if row is None else AnalysisRecord(*row)

    def count_active_for_owner(self, owner):
        a = analyses.c
        return self.session.scalar(select(func.count()).select_from(
            analyses.join(UserDocument, UserDocument.document_id == a.document_id)).where(
            UserDocument.owner_user_id == owner, a.status.in_(["queued", "running"])))

    def insert(self, owner, document_id, analysis_type, model_version_id, now):
        analysis_id = self.session.scalar(pg_insert(analyses).values(
            document_id=document_id, model_version_id=model_version_id, analysis_type=analysis_type,
            status="queued", requested_at=now).returning(analyses.c.analysis_id))
        return self.get_owned(owner, analysis_id)

    def get_owned(self, owner, analysis_id, lock=False):
        stmt = self._select().where(analyses.c.analysis_id == analysis_id, UserDocument.owner_user_id == owner,
                                    UserDocument.status != "deleting")
        if lock:
            stmt = stmt.with_for_update(of=analyses)
        row = self.session.execute(stmt).first()
        return None if row is None else AnalysisRecord(*row)

    def expire_stale(self, now, queue_ttl, running_ttl):
        a = analyses.c
        return self.session.execute(update(analyses).where(or_(
            and_(a.status == "queued", a.requested_at < now - queue_ttl),
            and_(a.status == "running", a.requested_at < now - running_ttl),
        )).values(status="failed", error_code="TIMEOUT", completed_at=now)).rowcount

    def claim_next(self):
        a = analyses.c
        row = self.session.execute(
            select(a.analysis_id, a.document_id, UserDocument.owner_user_id, a.analysis_type)
            .select_from(analyses.join(UserDocument, UserDocument.document_id == a.document_id))
            .where(a.status == "queued").order_by(a.requested_at, a.analysis_id).limit(1)
            .with_for_update(of=analyses, skip_locked=True)).first()
        if row is None:
            return None
        self.session.execute(update(analyses).where(a.analysis_id == row.analysis_id, a.status == "queued")
                             .values(status="running"))
        return ClaimedJob(*row)

    def finish(self, analysis_id, status, result, error_code, now):
        a = analyses.c
        return self.session.execute(update(analyses).where(a.analysis_id == analysis_id, a.status == "running")
            .values(status=status, result=result, error_code=error_code, completed_at=now)).rowcount == 1

    def requeue(self, analysis_id):
        a = analyses.c
        return self.session.execute(update(analyses).where(a.analysis_id == analysis_id, a.status == "running")
                                    .values(status="queued")).rowcount == 1

    def resolve_active_skills(self, codes):
        s = skills.c
        rows = self.session.execute(select(s.skill_id, s.code, s.name).where(
            s.code.in_(codes), s.is_active.is_(True))).all()
        return {r.code: Skill(skill_id=r.skill_id, code=r.code, name=r.name) for r in rows}

    def usable_skill_ids(self, owner, skill_ids):
        return self.my_skills.usable_skill_ids(owner, skill_ids)  # T33 policy: active, or already owned

    def upsert_user_skills(self, owner, items, now):
        """Add or update only the selected skills. Never deletes other owned skills."""
        us = user_skills.c
        self.session.execute(select(users.c.user_id).where(users.c.user_id == owner).with_for_update())
        stmt = pg_insert(user_skills).values([
            {"user_id": owner, "skill_id": sid, "proficiency": p, "created_at": now, "updated_at": now}
            for sid, p in items.items()])
        self.session.execute(stmt.on_conflict_do_update(
            index_elements=[us.user_id, us.skill_id],
            set_={"proficiency": stmt.excluded.proficiency, "updated_at": now},
            where=us.proficiency.is_distinct_from(stmt.excluded.proficiency)))

    def list_user_skills(self, owner):
        return self.my_skills.list_skills(owner)
