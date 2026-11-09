"""T45 educational rules-based recommendation run. POST writes; GET is read-only."""
from datetime import UTC, date, datetime
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.recommendation_runs import Candidate, SqlRecommendationRepository
from app.schemas.recommendation_runs import RecommendationRun
from app.services.recommendation_baseline import Posting, recommend


class RecommendationService:
    def __init__(self, repo: SqlRecommendationRepository, clock=lambda: datetime.now(UTC)):
        self.repo = repo
        self.clock = clock

    def create(self, user_id: UUID, limit: int = 20) -> RecommendationRun:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise AppError(ErrorCode.VALIDATION_FAILED)
        now = self.clock()
        data = self.repo.load_inputs(user_id, now)
        eligible = [c for c in data.candidates if c.posting.job_posting_id not in data.excluded_ids]
        ranked: list[tuple[UUID, float | None, str]] = []
        status = "fallback"
        if data.skills and eligible:
            # T18 filtering already handles exact timestamp expiration, NULL = ongoing.
            # The T27 date-only primitive is invoked only on T18-confirmed open postings.
            baseline = recommend(data.skills, [Posting(
                id=str(c.posting.job_posting_id), skills=c.skill_codes,
                source_id="catalog", expires_on=(c.posting.expires_at.date()
                    if c.posting.expires_at is not None else date.max))
                for c in eligible], as_of=now.date(), limit=min(50, len(eligible)))
            scores = {UUID(x.posting_id): x for x in baseline.items}
            # Baseline returns <=50; eligible is latest-first. Do not claim a full-corpus top-K.
            matched = [c for c in eligible if c.posting.job_posting_id in scores]
            matched.sort(key=lambda c: (-scores[c.posting.job_posting_id].score,
                data.target_priorities.get(c.posting.job_role.job_role_id, 999)
                    if c.posting.job_role else 999, str(c.posting.job_posting_id)))
            for c in matched[:limit]:
                result = scores[c.posting.job_posting_id]
                target = c.posting.job_role is not None and c.posting.job_role.job_role_id in data.target_priorities
                reason = result.reason + (" 목표 직무에 포함됩니다." if target else "")
                ranked.append((c.posting.job_posting_id, float(result.score), reason))
            if ranked:
                status = "completed"
        if not ranked:
            ranked = [(c.posting.job_posting_id, None,
                "보유 기술 또는 공고의 요구 기술 정보가 부족하여 최신 공고를 표시합니다.")
                for c in eligible[:limit]]
        return self.repo.store(user_id, status, ranked, now)

    def latest(self, user_id: UUID) -> RecommendationRun:
        result = self.repo.latest(user_id)
        if result is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return result

    def get(self, user_id: UUID, run_id: UUID) -> RecommendationRun:
        result = self.repo.get(user_id, run_id)
        if result is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return result
