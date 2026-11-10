"""테스트용 메모리 MatchRepository. SqlMatchRepository와 같은 의미(commit 전에는 저장되지 않음)로 동작한다."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.repositories.matching import MatchRecord, ModelVersionRecord, NewMatch, PostingRecord, PostingSkillRecord
from app.services import match_rule

MATCH_RULE_V1 = ModelVersionRecord(uuid.UUID(int=0xA1), match_rule.MODEL_CODE, match_rule.VERSION, match_rule.KIND)


@dataclass
class MemoryMatchRepository:
    skills: dict[uuid.UUID, dict[uuid.UUID, int | None]] = field(default_factory=dict)  # user → skill → proficiency
    project_skills: dict[uuid.UUID, set[uuid.UUID]] = field(default_factory=dict)
    postings: dict[uuid.UUID, PostingRecord] = field(default_factory=dict)
    posting_reqs: dict[uuid.UUID, list[PostingSkillRecord]] = field(default_factory=dict)
    roles: dict[uuid.UUID, bool] = field(default_factory=dict)  # role → is_active
    role_reqs: dict[uuid.UUID, dict[uuid.UUID, int]] = field(default_factory=dict)
    model_versions: list[ModelVersionRecord] = field(default_factory=lambda: [MATCH_RULE_V1])
    matches: dict[uuid.UUID, MatchRecord] = field(default_factory=dict)
    _pending: dict[uuid.UUID, MatchRecord] = field(default_factory=dict)
    commits: int = 0

    # ---- helpers for tests
    def add_posting(self, role_id: uuid.UUID | None, reqs: list[tuple[uuid.UUID, int | None, bool]],
                    status: str = "published", expires_at: datetime | None = None) -> uuid.UUID:
        posting_id = uuid.uuid4()
        self.postings[posting_id] = PostingRecord(posting_id, role_id, status, expires_at)
        self.posting_reqs[posting_id] = [PostingSkillRecord(*r) for r in reqs]
        return posting_id

    def add_role(self, reqs: dict[uuid.UUID, int], active: bool = True) -> uuid.UUID:
        role_id = uuid.uuid4()
        self.roles[role_id] = active
        self.role_reqs[role_id] = dict(reqs)
        return role_id

    # ---- MatchRepository
    def user_proficiencies(self, user_id: uuid.UUID) -> dict[uuid.UUID, int | None]:
        return dict(self.skills.get(user_id, {}))

    def user_project_skill_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        return set(self.project_skills.get(user_id, set()))

    def get_posting(self, job_posting_id: uuid.UUID) -> PostingRecord | None:
        return self.postings.get(job_posting_id)

    def posting_skills(self, job_posting_id: uuid.UUID) -> list[PostingSkillRecord]:
        return list(self.posting_reqs.get(job_posting_id, []))

    def role_is_active(self, job_role_id: uuid.UUID) -> bool | None:
        return self.roles.get(job_role_id)

    def role_skill_levels(self, job_role_id: uuid.UUID) -> dict[uuid.UUID, int]:
        return dict(self.role_reqs.get(job_role_id, {}))

    def approved_model_version(self, model_code: str, version: str) -> ModelVersionRecord | None:
        return next((m for m in self.model_versions if (m.model_code, m.version) == (model_code, version)), None)

    def add_match(self, new: NewMatch) -> MatchRecord:
        model = next(m for m in self.model_versions if m.model_version_id == new.model_version_id)
        record = MatchRecord(
            uuid.uuid4(), new.user_id, new.job_posting_id, new.job_role_id, new.status, new.score,
            new.matched_skill_count, new.missing_skill_count, list(new.limitations), new.evaluated_at, model,
        )
        self._pending[record.match_id] = record
        return record

    def get_match(self, match_id: uuid.UUID) -> MatchRecord | None:
        return self.matches.get(match_id)

    def commit(self) -> None:
        self.matches.update(self._pending)
        self._pending.clear()
        self.commits += 1

    def rollback(self) -> None:
        self._pending.clear()
