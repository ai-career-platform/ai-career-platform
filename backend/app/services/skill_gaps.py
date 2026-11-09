"""T43 orchestration; actual rule calculation is injected from T26."""

from collections.abc import Callable
import base64
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.errors import AppError, ErrorCode
from app.repositories.skill_gaps import SkillGapEvaluator, SkillGapRepository
from app.schemas.skill_gaps import SkillGap, SkillGapHistoryQuery, SkillGapSummaryPage


class SkillGapService:
    def __init__(
        self, repository: SkillGapRepository, evaluator: SkillGapEvaluator, *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], UUID] = uuid4,
        cursor_key: bytes | None = None,
    ):
        self.repository = repository
        self.evaluator = evaluator
        self.clock = clock
        self.new_id = new_id
        if cursor_key is not None and (not isinstance(cursor_key, bytes) or len(cursor_key) < 32):
            raise ValueError("cursor_key must contain at least 32 bytes")
        self._cursor_key = cursor_key

    def _history_cursor(
        self, *, user_id: UUID, role_id: UUID | None, timestamp: datetime, assessment_id: UUID,
    ) -> str:
        payload = json.dumps([
            1, str(user_id), str(role_id) if role_id else None,
            timestamp.astimezone(timezone.utc).isoformat(), str(assessment_id),
        ], separators=(",", ":")).encode()
        signature = hmac.digest(self._cursor_key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def _parse_history_cursor(
        self, token: str, *, user_id: UUID, role_id: UUID | None,
    ) -> tuple[datetime, UUID]:
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
                raise ValueError
            signature, payload = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.digest(self._cursor_key, payload, "sha256")):
                raise ValueError
            version, owner, role, timestamp, assessment = json.loads(payload)
            if type(version) is not int or version != 1 or owner != str(user_id):
                raise ValueError
            if role != (str(role_id) if role_id else None):
                raise ValueError
            timestamp = datetime.fromisoformat(timestamp)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError
            return timestamp, UUID(assessment)
        except (ValueError, TypeError, UnicodeError) as exc:
            raise AppError(ErrorCode.INVALID_CURSOR) from exc

    def list_history(self, *, user_id: UUID, query: SkillGapHistoryQuery) -> SkillGapSummaryPage:
        if self._cursor_key is None:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        before = self._parse_history_cursor(
            query.cursor, user_id=user_id, role_id=query.job_role_id,
        ) if query.cursor is not None else None
        rows = self.repository.list_owned(
            user_id=user_id, job_role_id=query.job_role_id,
            before=before, limit=query.limit + 1,
        )
        items = rows[:query.limit]
        next_cursor = None
        if len(rows) > query.limit:
            last = items[-1]
            next_cursor = self._history_cursor(
                user_id=user_id, role_id=query.job_role_id,
                timestamp=last.evaluated_at, assessment_id=last.assessment_id,
            )
        return SkillGapSummaryPage(items=items, next_cursor=next_cursor)

    def create(self, *, user_id: UUID, job_role_id: UUID) -> SkillGap:
        inputs = self.repository.load_inputs(user_id=user_id, job_role_id=job_role_id)
        if inputs is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if not inputs.is_target_role:
            raise AppError(ErrorCode.NOT_A_TARGET_ROLE)
        if not inputs.observed_levels:
            raise AppError(ErrorCode.NO_USER_SKILLS)
        if inputs.role.job_role_id != job_role_id:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        requirements = {item.skill.skill_id: item for item in inputs.requirements}
        if len(requirements) != len(inputs.requirements):
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        for item in inputs.requirements:
            if type(item.required_level) is not int or not 1 <= item.required_level <= 5:
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        for observed in inputs.observed_levels.values():
            if observed is not None and (type(observed) is not int or not 1 <= observed <= 5):
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        evaluation = self.evaluator.evaluate(inputs)
        # A repeated skill would violate the persisted composite key.
        skill_ids = [item.skill.skill_id for item in evaluation.items]
        if len(skill_ids) != len(set(skill_ids)):
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        for item in evaluation.items:
            requirement = requirements.get(item.skill.skill_id)
            expected = inputs.observed_levels.get(item.skill.skill_id)
            if (requirement is None or item.skill != requirement.skill
                    or item.required_level != requirement.required_level
                    or item.observed_level != (0 if expected is None else expected)):
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        assessment = SkillGap(
            assessment_id=self.new_id(), job_role=inputs.role,
            model_version=evaluation.model_version, is_stale=False,
            evaluated_at=self.clock(),
            items=sorted(evaluation.items, key=lambda item: (
                -item.gap, item.skill.code, item.skill.skill_id
            )),
        )
        try:
            self.repository.save(user_id=user_id, assessment=assessment)
            self.repository.commit()
        except Exception:
            self.repository.rollback()
            raise
        return assessment

    def get(self, *, user_id: UUID, assessment_id: UUID) -> SkillGap:
        result = self.repository.get_owned(user_id=user_id, assessment_id=assessment_id)
        if result is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return result
