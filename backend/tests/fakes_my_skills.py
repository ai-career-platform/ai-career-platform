"""테스트용 메모리 MySkillsRepository. SqlMySkillsRepository와 같은 의미(commit 전에는 저장되지 않음)로 동작한다."""

import copy
import uuid
from datetime import datetime

from app.core.errors import AppError, ErrorCode
from app.repositories.my_skills import UserSkillRecord


class MemoryMySkillsRepository:
    def __init__(self) -> None:
        # skill_id → (code, name, is_active)
        self.catalog: dict[uuid.UUID, tuple[str, str, bool]] = {}
        # user_id → skill_id → {"proficiency", "created_at", "updated_at"}
        self._committed: dict[uuid.UUID, dict[uuid.UUID, dict]] = {}
        self._state: dict[uuid.UUID, dict[uuid.UUID, dict]] = {}
        self.commits = 0
        self.fail_commit = False

    # ---- helpers for tests
    def add_skill(self, code: str, name: str, active: bool = True) -> uuid.UUID:
        skill_id = uuid.uuid4()
        self.catalog[skill_id] = (code, name, active)
        return skill_id

    def retire(self, skill_id: uuid.UUID) -> None:
        code, name, _ = self.catalog[skill_id]
        self.catalog[skill_id] = (code, name, False)

    def stored(self, user_id: uuid.UUID) -> dict[uuid.UUID, dict]:
        return self._committed.get(user_id, {})

    # ---- MySkillsRepository
    def list_skills(self, user_id: uuid.UUID) -> list[UserSkillRecord]:
        rows = [
            UserSkillRecord(sid, *self.catalog[sid][:2], row["proficiency"])
            for sid, row in self._state.get(user_id, {}).items()
        ]
        return sorted(rows, key=lambda r: (r.name, str(r.skill_id)))

    def usable_skill_ids(self, user_id: uuid.UUID, skill_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        owned = self._state.get(user_id, {})
        return {sid for sid in skill_ids if sid in self.catalog and (self.catalog[sid][2] or sid in owned)}

    def replace_skills(self, user_id: uuid.UUID, items: dict[uuid.UUID, int | None], now: datetime) -> None:
        old = self._state.get(user_id, {})
        new = {}
        for sid, proficiency in items.items():
            row = dict(old.get(sid) or {"proficiency": proficiency, "created_at": now, "updated_at": now})
            if sid in old and row["proficiency"] != proficiency:
                row.update(proficiency=proficiency, updated_at=now)
            new[sid] = row
        self._state[user_id] = new

    def commit(self) -> None:
        if self.fail_commit:
            # SqlMySkillsRepository는 DB 오류를 503으로 바꾼다
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="commit failed")
        self._committed = copy.deepcopy(self._state)
        self.commits += 1

    def rollback(self) -> None:
        self._state = copy.deepcopy(self._committed)
