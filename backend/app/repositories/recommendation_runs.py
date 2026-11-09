"""T45: request-scoped SQLAlchemy Core access; no DDL and no Staging setup."""
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, Integer, String, Uuid, column, select, table, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.job_postings import PostingFilter, SqlJobPostingRepository
from app.repositories.my_skills import SqlMySkillsRepository
from app.repositories.target_roles import SqlTargetRoleRepository
from app.schemas.job_postings import JobPostingSummary
from app.schemas.recommendation_runs import ModelVersionRef, RecommendationItem, RecommendationRun
from app.services.job_postings import _summary

SCHEMA = "career"
model_versions = table("model_versions", column("model_version_id", Uuid), column("model_code", String),
    column("version", String), column("kind", String), column("description", String), schema=SCHEMA)
runs = table("recommendation_runs", column("recommendation_run_id", Uuid), column("user_id", Uuid),
    column("model_version_id", Uuid), column("status", String),
    column("generated_at", DateTime(timezone=True)), schema=SCHEMA)
items = table("recommendation_items", column("recommendation_run_id", Uuid), column("job_posting_id", Uuid),
    column("rank", Integer), column("score", Float), column("reason", String), schema=SCHEMA)
feedback = table("recommendation_feedback", column("feedback_id", Uuid), column("user_id", Uuid),
    column("job_posting_id", Uuid), column("feedback", String),
    column("created_at", DateTime(timezone=True)), schema=SCHEMA)

MODEL_CODE = "skill_overlap_baseline"
MODEL_VERSION = "skill-overlap-draft-v2"


@dataclass(frozen=True)
class Candidate:
    posting: JobPostingSummary
    skill_codes: tuple[str, ...]


@dataclass(frozen=True)
class Inputs:
    skills: tuple[str, ...]
    target_priorities: dict[UUID, int]
    candidates: tuple[Candidate, ...]
    excluded_ids: frozenset[UUID]


class SqlRecommendationRepository:
    def __init__(self, session: Session):
        self.db = session
        self.postings = SqlJobPostingRepository(session)

    def load_inputs(self, user_id: UUID, now: datetime) -> Inputs:
        try:
            user_skills = SqlMySkillsRepository(self.db).list_skills(user_id)
            targets = SqlTargetRoleRepository(self.db).list_for_user(user_id)
            seen_feedback: set[UUID] = set()
            excluded: set[UUID] = set()
            for job_id, action in self.db.execute(
                select(feedback.c.job_posting_id, feedback.c.feedback)
                .where(feedback.c.user_id == user_id)
                .order_by(feedback.c.created_at.desc(), feedback.c.feedback_id.desc())
            ):
                if job_id not in seen_feedback:
                    seen_feedback.add(job_id)
                    if action == "not_interested":
                        excluded.add(job_id)
            filt = PostingFilter(q=None, company_id=None, job_role_id=None,
                                 include_closed=False, sort="-published_at")
            rows = self.postings.list_postings(filt, after=None, limit=500, now=now)
            candidates = tuple(
                Candidate(JobPostingSummary(**_summary(row)), tuple(sorted({s.code for s in
                    self.postings.posting_skills(row.job_posting_id, row.job_role_id)})))
                for row in rows
            )
            return Inputs(tuple(sorted({s.code for s in user_skills})),
                          {x.job_role.job_role_id: x.priority for x in targets},
                          candidates, frozenset(excluded))
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def store(self, user_id: UUID, status: str, ranked: list[tuple[UUID, float | None, str]],
              now: datetime) -> RecommendationRun:
        try:
            # Rule baseline is explicitly tagged as a DRAFT; not an approved ML artifact.
            self.db.execute(pg_insert(model_versions).values(
                model_code=MODEL_CODE, version=MODEL_VERSION, kind="rule",
                description="T27 educational rule baseline, not a probability or trained model"
            ).on_conflict_do_nothing(index_elements=["model_code", "version"]))
            version_id = self.db.scalar(select(model_versions.c.model_version_id).where(
                model_versions.c.model_code == MODEL_CODE,
                model_versions.c.version == MODEL_VERSION))
            run_id = self.db.scalar(pg_insert(runs).values(
                user_id=user_id, model_version_id=version_id, status=status,
                generated_at=now).returning(runs.c.recommendation_run_id))
            if ranked:
                self.db.execute(pg_insert(items).values([
                    dict(recommendation_run_id=run_id, job_posting_id=job_id,
                         rank=i, score=score, reason=reason)
                    for i, (job_id, score, reason) in enumerate(ranked, 1)
                ]))
            self.db.commit()
            result = self.get(user_id, run_id)
            assert result is not None
            return result
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def latest(self, user_id: UUID) -> RecommendationRun | None:
        try:
            run_id = self.db.scalar(select(runs.c.recommendation_run_id).where(
                runs.c.user_id == user_id).order_by(
                    runs.c.generated_at.desc(), runs.c.recommendation_run_id.desc()).limit(1))
            return None if run_id is None else self.get(user_id, run_id)
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def get(self, user_id: UUID, run_id: UUID) -> RecommendationRun | None:
        try:
            row = self.db.execute(select(runs.c.recommendation_run_id, runs.c.status,
                runs.c.generated_at, model_versions.c.model_code, model_versions.c.version,
                model_versions.c.kind).join(model_versions,
                runs.c.model_version_id == model_versions.c.model_version_id).where(
                runs.c.user_id == user_id, runs.c.recommendation_run_id == run_id)).one_or_none()
            if row is None:
                return None
            ranked = self.db.execute(select(items.c.job_posting_id, items.c.rank, items.c.score,
                items.c.reason).where(items.c.recommendation_run_id == run_id)
                .order_by(items.c.rank)).all()
            result_items = []
            for item in ranked:
                posting = self.postings.get_posting(item.job_posting_id, datetime.now(UTC))
                if posting is None:  # deleted/hidden posting is never exposed
                    continue
                action = self.db.scalar(select(feedback.c.feedback).where(
                    feedback.c.user_id == user_id,
                    feedback.c.job_posting_id == item.job_posting_id).order_by(
                    feedback.c.created_at.desc(), feedback.c.feedback_id.desc()).limit(1))
                result_items.append(RecommendationItem(rank=item.rank, score=item.score,
                    reason=item.reason, feedback=action if action in ("liked", "not_interested") else None,
                    job_posting=JobPostingSummary(**_summary(posting))))
            return RecommendationRun(recommendation_run_id=row.recommendation_run_id,
                status=row.status, model_version=ModelVersionRef(
                    model_code=row.model_code, version=row.version, kind=row.kind),
                generated_at=row.generated_at, items=result_items)
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
