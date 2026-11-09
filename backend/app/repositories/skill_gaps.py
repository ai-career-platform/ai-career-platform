"""T43 integration ports, not a replacement for T15/T26/T33/T35.

SQLAlchemy persistence targets the formal T09 schema. The actual T26
calculator and stale policy remain injected upstream dependencies.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Uuid, column, func, insert, select, table, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.catalog import job_roles, job_role_skills, skills
from app.repositories.my_skills import user_skills
from app.schemas.catalog import JobRoleRef, Skill
from app.schemas.skill_gaps import GapModelVersion, SkillGap, SkillGapItem, SkillGapSummary


SCHEMA = "career"
user_target_roles = table(
    "user_target_roles", column("user_id", Uuid), column("job_role_id", Uuid), schema=SCHEMA,
)
model_versions = table(
    "model_versions", column("model_version_id", Uuid), column("model_code", String),
    column("version", String), column("kind", String),
    column("approved_at", DateTime(timezone=True)), schema=SCHEMA,
)
skill_gap_assessments = table(
    "skill_gap_assessments", column("assessment_id", Uuid), column("user_id", Uuid),
    column("job_role_id", Uuid), column("model_version_id", Uuid),
    column("evaluated_at", DateTime(timezone=True)), schema=SCHEMA,
)
skill_gap_items = table(
    "skill_gap_items", column("assessment_id", Uuid), column("skill_id", Uuid),
    column("required_level", Integer), column("observed_level", Integer),
    column("gap", Integer), schema=SCHEMA,
)


@dataclass(frozen=True)
class RequiredGapSkill:
    skill: Skill
    required_level: int


@dataclass(frozen=True)
class GapInputSnapshot:
    role: JobRoleRef
    is_target_role: bool
    requirements: tuple[RequiredGapSkill, ...]
    # None means a registered skill with unknown proficiency; missing key
    # means the user has not registered that skill. T26 interprets both.
    observed_levels: dict[UUID, int | None]


@dataclass(frozen=True)
class RuleEvaluation:
    model_version: GapModelVersion
    items: tuple[SkillGapItem, ...]


class SkillGapEvaluator(Protocol):
    def evaluate(self, snapshot: GapInputSnapshot) -> RuleEvaluation:
        """T26 adapter: return the versioned, deterministic rule result."""
        ...


class SkillGapRepository(Protocol):
    def list_owned(
        self, *, user_id: UUID, job_role_id: UUID | None,
        before: tuple[datetime, UUID] | None, limit: int,
    ) -> list[SkillGapSummary]:
        """User-scoped summaries, ordered by (evaluated_at DESC, ID DESC).

        Apply owner AND optional role filtering before exclusive keyset
        comparison and limit. Counts/sums come from persisted gap items, not
        current T26 results. Fetch at most limit rows, never the whole history.
        Assessment timestamp and ID must remain immutable after insertion.
        """
        ...

    def load_inputs(self, *, user_id: UUID, job_role_id: UUID) -> GapInputSnapshot | None:
        """Consistent user-scoped snapshot; None means the role does not exist."""
        ...

    def save(self, *, user_id: UUID, assessment: SkillGap) -> None:
        """Stage assessment and level snapshots in the current transaction.

        Resolve the approved model version, reject unapproved versions, and
        persist numeric level snapshots. Revision evidence and stale policy
        must be agreed separately with T25/T33/T35.
        """
        ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def get_owned(self, *, user_id: UUID, assessment_id: UUID) -> SkillGap | None:
        """Query by owner AND assessment ID; foreign/missing IDs both return None.

        Return persisted levels, not recomputed history. Compute is_stale from
        upstream revision evidence including additions/removals of skills/roles.
        """
        ...


class SqlSkillGapRepository:
    """T43 persistence using T14 Session and the T09 schema.

    No schema changes or default stale policy. A caller must explicitly supply
    a reviewed stale checker; runtime wiring stays disabled until that exists.
    Reads of input levels use one statement for a consistent DB snapshot.
    The service commits a successful save and rolls back any save failure.
    """

    def __init__(
        self, session: Session, *,
        stale_checker: Callable[[UUID, UUID, datetime], bool],
    ):
        self.session = session
        self.stale_checker = stale_checker

    def load_inputs(self, *, user_id: UUID, job_role_id: UUID) -> GapInputSnapshot | None:
        def operation():
            r, s, req, owned, targets = job_roles.c, skills.c, job_role_skills.c, user_skills.c, user_target_roles.c
            requirements = select(func.jsonb_agg(func.jsonb_build_object(
                "skill_id", s.skill_id, "code", s.code, "name", s.name,
                "required_level", req.required_level,
            ))).select_from(job_role_skills.join(skills, req.skill_id == s.skill_id)).where(
                req.job_role_id == r.job_role_id
            ).correlate(job_roles).scalar_subquery()
            levels = select(func.jsonb_agg(func.jsonb_build_object(
                "skill_id", owned.skill_id, "proficiency", owned.proficiency,
            ))).where(owned.user_id == user_id).scalar_subquery()
            target = select(targets.user_id).where(
                targets.user_id == user_id, targets.job_role_id == r.job_role_id,
            ).correlate(job_roles).exists()
            row = self.session.execute(select(
                r.job_role_id, r.code, r.name, target.label("is_target"),
                requirements.label("requirements"), levels.label("levels"),
            ).where(r.job_role_id == job_role_id)).mappings().one_or_none()
            if row is None:
                return None
            return GapInputSnapshot(
                role=JobRoleRef(job_role_id=row["job_role_id"], code=row["code"], name=row["name"]),
                is_target_role=row["is_target"],
                requirements=tuple(RequiredGapSkill(
                    skill=Skill(skill_id=item["skill_id"], code=item["code"], name=item["name"]),
                    required_level=item["required_level"],
                ) for item in row["requirements"] or []),
                observed_levels={UUID(item["skill_id"]): item["proficiency"] for item in row["levels"] or []},
            )
        return self._run(operation)

    def save(self, *, user_id: UUID, assessment: SkillGap) -> None:
        def operation():
            m = model_versions.c
            model_id = self.session.scalar(select(m.model_version_id).where(
                m.model_code == assessment.model_version.model_code,
                m.version == assessment.model_version.version,
                m.kind == "rule", m.approved_at.is_not(None),
            ))
            if model_id is None:
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
            self.session.execute(insert(skill_gap_assessments).values(
                assessment_id=assessment.assessment_id, user_id=user_id,
                job_role_id=assessment.job_role.job_role_id, model_version_id=model_id,
                evaluated_at=assessment.evaluated_at,
            ))
            if assessment.items:
                self.session.execute(insert(skill_gap_items), [{
                    "assessment_id": assessment.assessment_id, "skill_id": item.skill.skill_id,
                    "required_level": item.required_level, "observed_level": item.observed_level,
                    "gap": item.gap,
                } for item in assessment.items])
        return self._run(operation)

    def commit(self) -> None:
        self._run(self.session.commit)

    def rollback(self) -> None:
        self.session.rollback()

    def _stale(self, user_id: UUID, assessment_id: UUID, evaluated_at: datetime) -> bool:
        stale = self.stale_checker(user_id, assessment_id, evaluated_at)
        if type(stale) is not bool:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        return stale

    def get_owned(self, *, user_id: UUID, assessment_id: UUID) -> SkillGap | None:
        def operation():
            a, r, m, i, s = skill_gap_assessments.c, job_roles.c, model_versions.c, skill_gap_items.c, skills.c
            row = self.session.execute(select(
                a.assessment_id, a.evaluated_at, r.job_role_id, r.code, r.name,
                m.model_code, m.version, m.kind,
            ).select_from(skill_gap_assessments.join(job_roles, a.job_role_id == r.job_role_id).join(
                model_versions, a.model_version_id == m.model_version_id,
            )).where(a.user_id == user_id, a.assessment_id == assessment_id)).mappings().one_or_none()
            if row is None:
                return None
            item_rows = self.session.execute(select(
                s.skill_id, s.code, s.name, i.required_level, i.observed_level, i.gap,
            ).select_from(skill_gap_items.join(skills, i.skill_id == s.skill_id).join(
                skill_gap_assessments, i.assessment_id == a.assessment_id,
            )).where(a.user_id == user_id, a.assessment_id == assessment_id).order_by(
                i.gap.desc(), s.code, s.skill_id,
            )).mappings()
            return SkillGap(
                assessment_id=row["assessment_id"],
                job_role=JobRoleRef(job_role_id=row["job_role_id"], code=row["code"], name=row["name"]),
                model_version=GapModelVersion(model_code=row["model_code"], version=row["version"], kind=row["kind"]),
                is_stale=self._stale(user_id, assessment_id, row["evaluated_at"]),
                evaluated_at=row["evaluated_at"],
                items=[SkillGapItem(
                    skill=Skill(skill_id=item["skill_id"], code=item["code"], name=item["name"]),
                    required_level=item["required_level"], observed_level=item["observed_level"], gap=item["gap"],
                ) for item in item_rows],
            )
        return self._run(operation)

    def list_owned(
        self, *, user_id: UUID, job_role_id: UUID | None,
        before: tuple[datetime, UUID] | None, limit: int,
    ) -> list[SkillGapSummary]:
        def operation():
            a, r, i = skill_gap_assessments.c, job_roles.c, skill_gap_items.c
            statement = select(
                a.assessment_id, a.evaluated_at, r.job_role_id, r.code, r.name,
                func.count(i.skill_id).filter(i.gap > 0).label("missing_count"),
                func.coalesce(func.sum(i.gap), 0).label("total_gap"),
            ).select_from(skill_gap_assessments.join(job_roles, a.job_role_id == r.job_role_id).outerjoin(
                skill_gap_items, a.assessment_id == i.assessment_id,
            )).where(a.user_id == user_id)
            if job_role_id is not None:
                statement = statement.where(a.job_role_id == job_role_id)
            if before is not None:
                statement = statement.where(tuple_(a.evaluated_at, a.assessment_id) < tuple_(*before))
            rows = self.session.execute(statement.group_by(
                a.assessment_id, a.evaluated_at, r.job_role_id, r.code, r.name,
            ).order_by(a.evaluated_at.desc(), a.assessment_id.desc()).limit(limit)).mappings()
            return [SkillGapSummary(
                assessment_id=row["assessment_id"],
                job_role=JobRoleRef(job_role_id=row["job_role_id"], code=row["code"], name=row["name"]),
                missing_skill_count=row["missing_count"], total_gap=row["total_gap"],
                is_stale=self._stale(user_id, row["assessment_id"], row["evaluated_at"]),
                evaluated_at=row["evaluated_at"],
            ) for row in rows]
        return self._run(operation)

    def _run(self, operation):
        try:
            return operation()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
