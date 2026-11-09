"""적합도 평가 업무 규칙 (FR-ANL-001, API createMatch·getMatch).

- 대상: 공고 또는 직무 하나. 공고는 게시(published)·마감(closed)만 계산하고, 마감·만료면 한계 설명에 표시.
  초안(draft) 공고, 없는 공고, 비활성 직무는 404.
- 보유 기술(user_skills)이 없으면 400 NO_USER_SKILLS.
- 계산 기준(model_versions의 승인된 `match_rule` v1)이 없으면 503. 결과마다 계산 기준 ID를 저장한다.
- 조회는 본인 결과만. 다른 사람 결과는 404로 존재를 숨긴다.
"""

import uuid
from datetime import UTC, datetime

from app.core.errors import AppError, ErrorCode
from app.repositories.matching import MatchRecord, MatchRepository, NewMatch
from app.services import match_rule
from app.services.match_rule import Requirement


def _now() -> datetime:
    return datetime.now(UTC)


class MatchService:
    def __init__(self, repo: MatchRepository, clock=_now) -> None:
        self._repo = repo
        self._clock = clock

    def create(self, user_id: uuid.UUID, *, job_posting_id: uuid.UUID | None, job_role_id: uuid.UUID | None) -> MatchRecord:
        now = self._clock()
        if job_posting_id is not None:
            requirements, closed = self._posting_requirements(job_posting_id, now)
        else:
            requirements, closed = self._role_requirements(job_role_id), False

        proficiencies = self._repo.user_proficiencies(user_id)
        if not proficiencies:
            raise AppError(ErrorCode.NO_USER_SKILLS)

        model = self._repo.approved_model_version(match_rule.MODEL_CODE, match_rule.VERSION)
        if model is None:
            raise AppError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                log_detail=f"approved model_versions row missing: {match_rule.MODEL_CODE} v{match_rule.VERSION}",
            )

        outcome = match_rule.evaluate(
            requirements, proficiencies, self._repo.user_project_skill_ids(user_id), posting_closed=closed
        )
        record = self._repo.add_match(
            NewMatch(
                user_id=user_id, job_posting_id=job_posting_id, job_role_id=job_role_id,
                model_version_id=model.model_version_id, status=outcome.status, score=outcome.score,
                matched_skill_count=outcome.matched_skill_count, missing_skill_count=outcome.missing_skill_count,
                limitations=outcome.limitations, evaluated_at=now,
            )
        )
        self._repo.commit()
        return record

    def get(self, user_id: uuid.UUID, match_id: uuid.UUID) -> MatchRecord:
        record = self._repo.get_match(match_id)
        if record is None or record.user_id != user_id:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="match missing or owned by another user")
        return record

    def _posting_requirements(self, job_posting_id: uuid.UUID, now: datetime) -> tuple[list[Requirement], bool]:
        posting = self._repo.get_posting(job_posting_id)
        if posting is None or posting.status not in ("published", "closed"):
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job posting missing or not public")
        role_levels = self._repo.role_skill_levels(posting.job_role_id) if posting.job_role_id else {}
        requirements = [
            Requirement(
                s.skill_id,
                s.required_level or role_levels.get(s.skill_id) or match_rule.DEFAULT_REQUIRED_LEVEL,
                s.is_required,
            )
            for s in self._repo.posting_skills(job_posting_id)
        ]
        closed = posting.status == "closed" or (posting.expires_at is not None and posting.expires_at <= now)
        return requirements, closed

    def _role_requirements(self, job_role_id: uuid.UUID) -> list[Requirement]:
        if not self._repo.role_is_active(job_role_id):  # None(없음) 또는 False(비활성)
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job role missing or inactive")
        return [Requirement(skill_id, level, True) for skill_id, level in self._repo.role_skill_levels(job_role_id).items()]
