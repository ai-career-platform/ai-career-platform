"""Synthetic local fixtures only; not approved taxonomy or production seed."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.catalog import (
    JobRoleDetail, JobRoleQuery, JobRoleRef, RequiredSkill, Skill, SkillQuery,
)
from app.services.catalog import (
    CatalogNotFound, CatalogService, InvalidCatalogCursor,
)


class MemoryCatalog:
    """Test adapter. Production filtering/sorting still needs DB verification."""

    def __init__(self):
        self.roles = [
            JobRoleRef(job_role_id=UUID(int=i), code=f"test-{i}", name=name)
            for i, name in [(3, "Frontend"), (2, "Backend"), (1, "Backend")]
        ]
        self.skills = [
            Skill(skill_id=UUID(int=i), code=f"test-skill-{i}", name=name)
            for i, name in [(1, "CPython"), (2, "Python"), (3, "100% SQL")]
        ]

    def list_job_roles(self, *, q, after, limit):
        self.last_limit = limit
        rows = sorted(self.roles, key=lambda r: (r.name, r.job_role_id))
        return [
            r for r in rows
            if (q is None or q.casefold() in r.name.casefold())
            and (after is None or (r.name, r.job_role_id) > after)
        ][:limit]

    def get_job_role(self, role_id):
        for role in self.roles:
            if role.job_role_id == role_id:
                return JobRoleDetail(
                    **role.model_dump(), description=None, required_skills=[]
                )
        return None

    def search_skills(self, *, q, limit):
        query = q.casefold()
        rows = [s for s in self.skills if query in s.name.casefold()]
        return sorted(
            rows, key=lambda s: (
                not s.name.casefold().startswith(query), s.name, s.skill_id
            )
        )[:limit]


@pytest.fixture
def service():
    return CatalogService(MemoryCatalog(), cursor_key=b"local-test-key-only-" * 2)


def test_pagination_ties_and_terminal_cursor(service):
    cursor = None
    ids = []
    for _ in range(3):
        page = service.list_job_roles(JobRoleQuery(limit=1, cursor=cursor))
        ids.extend(item.job_role_id.int for item in page.items)
        cursor = page.next_cursor
    assert ids == [1, 2, 3]
    assert cursor is None
    assert service.repository.last_limit == 2


def test_search_and_repeatable_response(service):
    query = JobRoleQuery(q="BACK", limit=1)
    first = service.list_job_roles(query)
    assert first == service.list_job_roles(query)
    assert first.items[0].name == "Backend"
    second = service.list_job_roles(
        JobRoleQuery(q="BACK", limit=1, cursor=first.next_cursor)
    )
    assert second.items[0].job_role_id.int == 2
    assert second.next_cursor is None


@pytest.mark.parametrize("q", ["no match", "%' OR 1=1 --", "백엔드"])
def test_empty_search(service, q):
    page = service.list_job_roles(JobRoleQuery(q=q))
    assert page.model_dump() == {"items": [], "next_cursor": None}


def test_detail_missing_and_empty_relationship(service):
    assert service.get_job_role(UUID(int=1)).required_skills == []
    with pytest.raises(CatalogNotFound):
        service.get_job_role(UUID(int=999))


def test_skills_prefix_rank_case_and_literal_wildcard(service):
    result = service.search_skills(SkillQuery(q="PY"))
    assert [s.name for s in result.items] == ["Python", "CPython"]
    assert service.search_skills(SkillQuery(q="0%")).items[0].name == "100% SQL"
    assert service.search_skills(SkillQuery(q="absent")).items == []


@pytest.mark.parametrize("token", ["", "!bad", "a" * 100, "e30"])
def test_invalid_cursor(service, token):
    with pytest.raises(InvalidCatalogCursor):
        service.list_job_roles(JobRoleQuery(cursor=token))


def test_cursor_tampering_search_change_and_key_rotation(service):
    token = service.list_job_roles(JobRoleQuery(limit=1)).next_cursor
    for query in [
        JobRoleQuery(q="Backend", cursor=token),
        JobRoleQuery(cursor=("A" if token[0] != "A" else "B") + token[1:]),
    ]:
        with pytest.raises(InvalidCatalogCursor):
            service.list_job_roles(query)
    other = CatalogService(MemoryCatalog(), cursor_key=b"different-test-key" * 2)
    with pytest.raises(InvalidCatalogCursor):
        other.list_job_roles(JobRoleQuery(cursor=token))


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True, "20"])
def test_invalid_limit(limit):
    with pytest.raises(ValidationError):
        JobRoleQuery(limit=limit)


@pytest.mark.parametrize("limit", [1, 20, 100])
def test_valid_limit(limit):
    assert JobRoleQuery(limit=limit).limit == limit


def test_query_boundaries():
    assert JobRoleQuery(q="a" * 100).q
    assert SkillQuery(q="a" * 60).q
    for model, values in [
        (JobRoleQuery, {"q": ""}), (JobRoleQuery, {"q": "a" * 101}),
        (JobRoleQuery, {"cursor": "a" * 501}),
        (SkillQuery, {}), (SkillQuery, {"q": "a"}),
        (SkillQuery, {"q": "a" * 61}),
    ]:
        with pytest.raises(ValidationError):
            model(**values)


def test_dto_shape_and_level(service):
    detail = service.get_job_role(UUID(int=1)).model_dump(mode="json")
    assert set(detail) == {
        "job_role_id", "code", "name", "description", "required_skills"
    }
    skill = service.repository.skills[0]
    for level in [0, 6]:
        with pytest.raises(ValidationError):
            RequiredSkill(skill=skill, required_level=level)


def test_cursor_long_unicode_and_changed_anchor(service):
    name = "가" * 160
    service.repository.roles = [
        JobRoleRef(job_role_id=UUID(int=i), code=f"test-{i}", name=name)
        for i in [1, 2]
    ]
    q = "가" * 100
    page = service.list_job_roles(JobRoleQuery(q=q, limit=1))
    assert len(page.next_cursor) <= 500
    next_page = service.list_job_roles(JobRoleQuery(q=q, cursor=page.next_cursor))
    assert next_page.items[0].job_role_id.int == 2
    service.repository.roles.pop(0)
    with pytest.raises(InvalidCatalogCursor):
        service.list_job_roles(JobRoleQuery(q=q, cursor=page.next_cursor))
