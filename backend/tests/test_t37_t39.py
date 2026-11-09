from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import AppError, ErrorCode
from app.repositories.bookmarks import BookmarkRow
from app.repositories.job_postings import PostingRow
from app.schemas.career_history import Experience, ExperienceInput, ExperiencePatch, ProjectInput, ProjectPatch
from app.services.bookmarks import BookmarkService
from app.services.career_history import CareerHistoryService
from app.services.job_postings import ListCursor

USER = uuid4()
NOW = datetime(2026, 11, 9, tzinfo=UTC)


class HistoryRepo:
    def __init__(self): self.items = {}
    def list_experiences(self, user_id): return list(self.items.values())
    def create_experience(self, user_id, data):
        item = Experience(experience_id=uuid4(), updated_at=NOW, **data.model_dump()); self.items[item.experience_id] = item; return item
    def update_experience(self, user_id, item_id, data): return self.items.get(item_id)
    def delete_experience(self, user_id, item_id): return self.items.pop(item_id, None) is not None
    def list_projects(self, user_id): return []
    def create_project(self, user_id, data):
        if data.skill_ids: raise ValueError("unknown skill")
        return object()
    def update_project(self, user_id, item_id, data): return None
    def delete_project(self, user_id, item_id): return False


def test_t37_date_range_duplicate_skills_and_empty_patch_validation():
    with pytest.raises(ValidationError):
        ExperienceInput(organization="A", title="B", start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
    with pytest.raises(ValidationError): ExperiencePatch()
    with pytest.raises(ValidationError): ProjectPatch()
    # 생략은 허용, NOT NULL 필드에 명시적 null은 422 (DB 오류 500이 되지 않게).
    for patch in ({"organization": None}, {"title": None}):
        with pytest.raises(ValidationError): ExperiencePatch(**patch)
    for patch in ({"title": None}, {"skill_ids": None}):
        with pytest.raises(ValidationError): ProjectPatch(**patch)
    assert ExperiencePatch(description=None).description is None
    skill = uuid4()
    with pytest.raises(ValidationError): ProjectInput(title="P", skill_ids=[skill, skill])


def test_t37_crud_not_found_and_unknown_skill_boundaries():
    repo = HistoryRepo(); service = CareerHistoryService(repo)
    item = service.create_experience(USER, ExperienceInput(organization="A", title="Dev"))
    assert service.list_experiences(USER) == [item]
    service.delete_experience(USER, item.experience_id)
    with pytest.raises(AppError) as error: service.delete_experience(USER, item.experience_id)
    assert error.value.code == ErrorCode.NOT_FOUND
    with pytest.raises(AppError) as error: service.create_project(USER, ProjectInput(title="P", skill_ids=[uuid4()]))
    assert error.value.code == ErrorCode.VALIDATION_FAILED


class BookmarkRepo:
    def __init__(self, rows=(), visible=True): self.rows, self.visible, self.adds, self.removes = list(rows), visible, 0, 0
    def list(self, user_id, after, limit, now): return self.rows[:limit]
    def add(self, user_id, posting_id): self.adds += 1; return self.visible
    def remove(self, user_id, posting_id): self.removes += 1


def posting(index: int):
    item_id = UUID(int=index + 1)
    row = PostingRow(item_id, f"Job {index}", "published", UUID(int=100), "Co", None, None, None,
                     "full_time", "Seoul", NOW, None)
    return BookmarkRow(row, NOW.replace(microsecond=index))


def test_t39_list_cursor_and_idempotent_mutations():
    repo = BookmarkRepo([posting(2), posting(1)])
    service = BookmarkService(repo, ListCursor(b"x" * 32), clock=lambda: NOW)
    page = service.list(USER, 1, None)
    assert [x.title for x in page.items] == ["Job 2"] and page.next_cursor
    service.add(USER, posting(1).posting.job_posting_id); service.add(USER, posting(1).posting.job_posting_id)
    service.remove(USER, posting(1).posting.job_posting_id); service.remove(USER, posting(1).posting.job_posting_id)
    assert (repo.adds, repo.removes) == (2, 2)


def test_t39_unknown_posting_is_404():
    service = BookmarkService(BookmarkRepo(visible=False), ListCursor(b"x" * 32))
    with pytest.raises(AppError) as error: service.add(USER, uuid4())
    assert error.value.code == ErrorCode.NOT_FOUND
