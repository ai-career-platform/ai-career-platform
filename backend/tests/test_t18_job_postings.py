"""T18 기업·채용공고 API — DB 없이 도는 단위·HTTP 테스트 (CI 기본 실행).

실제 PostgreSQL 검증은 tests/test_t18_job_postings_postgres.py (T18_TEST_DATABASE_URL 지정 시).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app
from app.repositories.job_postings import (
    CompanyDetailRow, CompanyRow, PostingFilter, PostingRow, PostingSkillRow, escape_like,
)
from app.routers.job_postings import get_job_posting_service
from app.services.job_postings import JobPostingService, ListCursor, derive_cursor_key
from tests.conftest import TEST_SECRET, bearer, signup
from tests.fakes import MemoryAuthRepository

NOW = datetime(2026, 11, 9, tzinfo=UTC)
KEY = derive_cursor_key(TEST_SECRET)


class FakeRepo:
    """정렬·필터를 단순 구현한 메모리 저장소. SQL 의미는 Postgres 테스트에서 검증한다."""

    def __init__(self) -> None:
        self.companies = [CompanyRow(uuid.UUID(int=i), f"기업 {i:02d}") for i in range(1, 8)]
        role = uuid.uuid4()
        self.role = role
        self.postings = [
            PostingRow(uuid.UUID(int=100 + i), f"백엔드 #{i}", "published", self.companies[0].company_id, "기업 01",
                       role, "BACKEND", "백엔드", "full_time", "서울",
                       NOW - timedelta(days=i), NOW + timedelta(days=30), "설명", None)
            for i in range(5)
        ]
        self.bookmarks: set[tuple[uuid.UUID, uuid.UUID]] = set()

    def list_companies(self, q, after, limit):
        rows = [c for c in self.companies if not q or q.lower() in c.name.lower()]
        if after is not None:
            ids = [c.company_id for c in rows]
            if after not in ids:
                return None
            rows = rows[ids.index(after) + 1:]
        return rows[:limit]

    def get_company(self, company_id, now):
        for c in self.companies:
            if c.company_id == company_id:
                return CompanyDetailRow(c.company_id, c.name, None, None, "synthetic_seed", 5)
        return None

    def list_postings(self, f: PostingFilter, after, limit, now):
        rows = [p for p in self.postings if not f.q or f.q in p.title]
        if after is not None:
            ids = [p.job_posting_id for p in rows]
            if after not in ids:
                return None
            rows = rows[ids.index(after) + 1:]
        return rows[:limit]

    def get_posting(self, job_posting_id, now):
        return next((p for p in self.postings if p.job_posting_id == job_posting_id), None)

    def posting_skills(self, job_posting_id, job_role_id):
        return [PostingSkillRow(uuid.UUID(int=900), "PYTHON", "Python", 4, True),
                PostingSkillRow(uuid.UUID(int=901), "DOCKER", "Docker", None, False)]

    def is_bookmarked(self, user_id, job_posting_id):
        return (user_id, job_posting_id) in self.bookmarks


@pytest.fixture
def fake() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def service(fake) -> JobPostingService:
    return JobPostingService(fake, ListCursor(KEY), clock=lambda: NOW)


@pytest.fixture
def client(monkeypatch, fake):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth_repo = MemoryAuthRepository()
    from app.dependencies.auth import get_auth_repository
    app.dependency_overrides[get_auth_repository] = lambda: auth_repo
    app.dependency_overrides[get_job_posting_service] = (
        lambda: JobPostingService(fake, ListCursor(KEY), clock=lambda: NOW))
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    get_settings.cache_clear()


# ------------------------------------------------------------------ cursor
def test_cursor_round_trip_and_binding():
    cur = ListCursor(KEY)
    last = uuid.uuid4()
    token = cur.encode("companies", {"q": "a"}, last)
    assert len(token) < 500
    assert cur.decode(token, "companies", {"q": "a"}) == last
    for kind, params in [("companies", {"q": "b"}), ("job_postings", {"q": "a"})]:
        with pytest.raises(AppError) as err:
            cur.decode(token, kind, params)
        assert err.value.code == ErrorCode.INVALID_CURSOR


@pytest.mark.parametrize("token", ["", "abc", "!!!!", "A" * 60])
def test_cursor_garbage_rejected(token):
    with pytest.raises(AppError) as err:
        ListCursor(KEY).decode(token, "companies", {"q": None})
    assert err.value.code == ErrorCode.INVALID_CURSOR


def test_cursor_tamper_and_foreign_key_rejected():
    cur = ListCursor(KEY)
    token = cur.encode("companies", {"q": None}, uuid.uuid4())
    flipped = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    other = ListCursor(derive_cursor_key("another-secret-0123456789-abcdefghijkl"))
    for bad, decoder in [(flipped, cur), (token, other)]:
        with pytest.raises(AppError):
            decoder.decode(bad, "companies", {"q": None})


def test_escape_like():
    assert escape_like("100%_a\\b") == "100\\%\\_a\\\\b"


# ------------------------------------------------------------------ service
def test_company_pages_have_no_gap_or_duplicate(service):
    seen, cursor = [], None
    while True:
        page = service.list_companies(None, 3, cursor)
        seen += [c.company_id for c in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [uuid.UUID(int=i) for i in range(1, 8)]


def test_last_page_has_null_cursor(service):
    assert service.list_companies(None, 7, None).next_cursor is None
    assert service.list_companies("없는", 20, None).items == []


def test_vanished_anchor_is_invalid_cursor(service, fake):
    page = service.list_companies(None, 2, None)
    fake.companies = [c for c in fake.companies if c.company_id != page.items[-1].company_id]
    with pytest.raises(AppError) as err:
        service.list_companies(None, 2, page.next_cursor)
    assert err.value.code == ErrorCode.INVALID_CURSOR


def test_posting_detail_anonymous_and_missing(service, fake):
    detail = service.get_posting(fake.postings[0].job_posting_id, None)
    assert detail.is_bookmarked is None
    assert [s.skill.code for s in detail.required_skills] == ["PYTHON", "DOCKER"]
    with pytest.raises(AppError) as err:
        service.get_posting(uuid.uuid4(), None)
    assert err.value.code == ErrorCode.NOT_FOUND


# ------------------------------------------------------------------ HTTP
def test_routes_are_public_and_match_contract_shape(client, fake):
    r = client.get(f"{API_V1_PREFIX}/companies", params={"limit": 2})
    assert r.status_code == 200
    assert set(r.json()) == {"items", "next_cursor"}
    assert set(r.json()["items"][0]) == {"company_id", "name"}

    r = client.get(f"{API_V1_PREFIX}/companies/{fake.companies[0].company_id}")
    assert r.status_code == 200
    assert set(r.json()) == {"company_id", "name", "website_url", "description", "open_posting_count", "source"}

    r = client.get(f"{API_V1_PREFIX}/job-postings")
    assert r.status_code == 200
    assert set(r.json()["items"][0]) == {
        "job_posting_id", "title", "status", "company", "job_role", "employment_type", "location_text",
        "published_at", "expires_at"}

    r = client.get(f"{API_V1_PREFIX}/job-postings/{fake.postings[0].job_posting_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["is_bookmarked"] is None
    assert body["required_skills"][1] == {
        "skill": {"skill_id": str(uuid.UUID(int=901)), "code": "DOCKER", "name": "Docker"},
        "required_level": None, "is_required": False}


@pytest.mark.parametrize("path", ["companies", "job-postings"])
def test_unknown_id_is_404_error_contract(client, path):
    r = client.get(f"{API_V1_PREFIX}/{path}/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json() == {"code": "NOT_FOUND", "status": 404, "message": "요청한 정보를 찾을 수 없습니다."}


@pytest.mark.parametrize("path,params", [
    ("companies", {"limit": 0}), ("companies", {"limit": 101}), ("companies", {"q": ""}),
    ("companies", {"q": "x" * 101}), ("companies/not-a-uuid", {}), ("job-postings", {"sort": "title"}),
    ("job-postings", {"company_id": "abc"}), ("job-postings", {"include_closed": "maybe"}),
    ("job-postings", {"cursor": "x" * 501}),
])
def test_validation_errors_are_422(client, path, params):
    r = client.get(f"{API_V1_PREFIX}/{path}", params=params)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_FAILED"


def test_tampered_cursor_is_400(client):
    r = client.get(f"{API_V1_PREFIX}/companies", params={"cursor": "tampered"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_CURSOR"


def test_cursor_reused_with_other_filter_is_400(client):
    first = client.get(f"{API_V1_PREFIX}/job-postings", params={"limit": 2}).json()
    r = client.get(f"{API_V1_PREFIX}/job-postings",
                   params={"limit": 2, "cursor": first["next_cursor"], "include_closed": "true"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_CURSOR"


def test_bad_token_is_401_not_silently_anonymous(client):
    r = client.get(f"{API_V1_PREFIX}/companies", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


def test_logged_in_detail_shows_bookmark_flag(client, fake):
    token = signup(client).json()["access_token"]
    posting = fake.postings[0].job_posting_id
    me = client.get(f"{API_V1_PREFIX}/me", headers=bearer(token)).json()
    url = f"{API_V1_PREFIX}/job-postings/{posting}"
    assert client.get(url, headers=bearer(token)).json()["is_bookmarked"] is False
    fake.bookmarks.add((uuid.UUID(me["user_id"]), posting))
    assert client.get(url, headers=bearer(token)).json()["is_bookmarked"] is True


def test_openapi_lists_t18_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/companies", "/companies/{company_id}", "/job-postings", "/job-postings/{job_posting_id}"]:
        assert f"{API_V1_PREFIX}{p}" in paths
    params = {p["name"] for p in paths[f"{API_V1_PREFIX}/job-postings"]["get"]["parameters"]}
    assert {"q", "company_id", "job_role_id", "include_closed", "sort", "limit", "cursor"} <= params
