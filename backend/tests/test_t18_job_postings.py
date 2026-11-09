"""T18 기업·채용공고 API — DB 없이 도는 단위·HTTP 테스트 (CI 기본 실행).

실제 PostgreSQL 검증은 tests/test_t18_job_postings_postgres.py (T18_TEST_DATABASE_URL 지정 시).
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import issue_access_token
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
_MIN = datetime.min.replace(tzinfo=UTC)


class FakeRepo:
    """정렬·필터를 단순 구현한 메모리 저장소. SQL 의미는 Postgres 테스트에서 검증한다."""

    def __init__(self) -> None:
        self.companies = [CompanyRow(uuid.UUID(int=i), f"기업 {i:02d}", f"기업 {i:02d}") for i in range(1, 8)]
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
        rows.sort(key=lambda c: (c.name.lower(), c.company_id))
        if after is not None:
            rows = [c for c in rows if (c.name.lower(), c.company_id) > after]
        return rows[:limit]

    def get_company(self, company_id, now):
        for c in self.companies:
            if c.company_id == company_id:
                return CompanyDetailRow(c.company_id, c.name, None, None, "synthetic_seed", 5)
        return None

    def list_postings(self, f: PostingFilter, after, limit, now):
        def is_open(p):
            return p.status == "published" and (p.expires_at is None or p.expires_at > now)

        rows = [
            p for p in self.postings
            if (f.include_closed or is_open(p))
            and (not f.q or f.q.lower() in p.title.lower())
            and (f.company_id is None or p.company_id == f.company_id)
            and (f.job_role_id is None or p.job_role_id == f.job_role_id)
        ]
        # 날짜 없는 공고는 두 정렬 모두 맨 뒤. 위치 = (날짜 있음 여부, 날짜, id)
        if f.sort == "expires_at":
            def pos(p):  # 오름차순: 날짜 없음이 가장 큼
                return p.expires_at is None, p.expires_at or _MIN, p.job_posting_id
            rows.sort(key=pos)
            if after is not None:
                key, last_id = after
                rows = [p for p in rows if pos(p) > (key is None, key or _MIN, last_id)]
        else:
            def pos(p):  # 내림차순: 날짜 없음이 가장 작다
                return p.published_at is not None, p.published_at or _MIN, p.job_posting_id
            rows.sort(key=pos, reverse=True)
            if after is not None:
                key, last_id = after
                rows = [p for p in rows if pos(p) < (key is not None, key or _MIN, last_id)]
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
    token = cur.encode("companies", {"q": "a"}, last, "기업 01")
    assert len(token) < 500
    assert cur.decode(token, "companies", {"q": "a"}) == (last, "기업 01")
    assert cur.decode(cur.encode("job_postings", {}, last, None), "job_postings", {}) == (last, None)
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
    token = cur.encode("companies", {"q": None}, uuid.uuid4(), "a")
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


def _walk_postings(service, f, limit):
    seen, cursor = [], None
    for _ in range(50):
        page = service.list_postings(f, limit, cursor)
        seen += [p.job_posting_id for p in page.items]
        cursor = page.next_cursor
        if cursor is None:
            return seen
    raise AssertionError("pagination did not end")


def _filter(**kw) -> PostingFilter:
    return PostingFilter(**{"q": None, "company_id": None, "job_role_id": None, "include_closed": False,
                            "sort": "-published_at", **kw})


def test_deleted_or_renamed_company_anchor_keeps_position(service, fake):
    """기준 기업이 사라지거나 이름이 바뀌어도 다음 페이지는 같은 위치에서 이어진다 (빈 페이지·400 아님)."""
    page = service.list_companies(None, 2, None)
    anchor = page.items[-1].company_id
    fake.companies = [CompanyRow(c.company_id, "ZZZ", "zzz") if c.company_id == anchor else c
                      for c in fake.companies]
    rest = service.list_companies(None, 10, page.next_cursor)
    assert [c.company_id for c in rest.items] == [uuid.UUID(int=i) for i in range(3, 8)]
    fake.companies = [c for c in fake.companies if c.company_id != anchor]
    assert len(service.list_companies(None, 10, page.next_cursor).items) == 5


def test_anchor_posting_closing_between_pages_still_continues(service, fake):
    first = service.list_postings(_filter(), 2, None)
    anchor = first.items[-1].job_posting_id
    fake.postings = [
        PostingRow(**{**p.__dict__, "status": "closed", "expires_at": NOW - timedelta(days=1)})
        if p.job_posting_id == anchor else p
        for p in fake.postings
    ]
    rest = service.list_postings(_filter(), 10, first.next_cursor)
    assert [p.job_posting_id for p in rest.items] == [uuid.UUID(int=100 + i) for i in (2, 3, 4)]


def _with_undated(fake, field):
    """날짜 없는 공고 3건을 섞는다 (id가 가장 큰 쪽이 뒤). field: expires_at | published_at"""
    base = fake.postings[0]
    extra = [PostingRow(**{**base.__dict__, "job_posting_id": uuid.UUID(int=200 + i), "title": f"날짜없음 {i}",
                           field: None}) for i in range(3)]
    fake.postings += extra
    return [p.job_posting_id for p in extra]


@pytest.mark.parametrize("limit", [1, 2, 3, 4])
def test_expires_at_sort_pages_through_null_deadlines(service, fake, limit):
    """마감일 없는 공고가 페이지 마지막(기준)이 되어도 끝까지 이어진다 (이전엔 DB의 infinity 오류로 500)."""
    undated = _with_undated(fake, "expires_at")
    fake.postings[1] = PostingRow(**{**fake.postings[1].__dict__, "expires_at": NOW + timedelta(days=1)})
    ids = _walk_postings(service, _filter(sort="expires_at"), limit)
    assert len(ids) == len(set(ids)) == 8
    assert ids[0] == fake.postings[1].job_posting_id  # 마감 가장 임박
    assert ids[-3:] == undated  # 마감일 없는 공고는 맨 뒤, id 순


@pytest.mark.parametrize("limit", [1, 2, 3, 4])
def test_published_at_sort_pages_through_null_published_when_closed_included(service, fake, limit):
    undated = _with_undated(fake, "published_at")
    ids = _walk_postings(service, _filter(include_closed=True), limit)
    assert len(ids) == len(set(ids)) == 8
    assert ids[-3:] == sorted(undated, reverse=True)


def test_empty_cursor_is_rejected_not_first_page(service):
    for call in (lambda: service.list_companies(None, 5, ""), lambda: service.list_postings(_filter(), 5, "")):
        with pytest.raises(AppError) as err:
            call()
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


def test_empty_cursor_query_is_400(client):
    r = client.get(f"{API_V1_PREFIX}/companies", params={"cursor": ""})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_CURSOR"


def test_bad_or_expired_token_is_treated_as_anonymous(client, fake):
    """공개 API는 만료·잘못된 토큰이어도 막지 않고 비로그인으로 처리한다 (200, is_bookmarked=null)."""
    expired = issue_access_token(TEST_SECRET, uuid.uuid4(), uuid.uuid4(), [], 60, now=NOW - timedelta(days=1))
    detail = f"{API_V1_PREFIX}/job-postings/{fake.postings[0].job_posting_id}"
    for header in ({"Authorization": "Bearer nope"}, {"Authorization": f"Bearer {expired}"},
                   {"Authorization": "Basic abc"}):
        for path in (f"{API_V1_PREFIX}/companies", f"{API_V1_PREFIX}/job-postings", detail):
            r = client.get(path, headers=header)
            assert r.status_code == 200, (header, path, r.text)
        assert client.get(detail, headers=header).json()["is_bookmarked"] is None


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
    for p in ["/companies", "/companies/{company_id}", "/job-postings", "/job-postings/{job_posting_id}"]:
        responses = paths[f"{API_V1_PREFIX}{p}"]["get"]["responses"]
        assert "503" in responses and "401" not in responses  # 공개 API: 인증 실패는 비로그인 처리


def test_openapi_yaml_matches_public_catalog_contract():
    spec = yaml.safe_load((Path(__file__).parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    for p in ["/companies", "/companies/{company_id}", "/job-postings", "/job-postings/{job_posting_id}"]:
        responses = spec["paths"][p]["get"]["responses"]
        assert "503" in responses and "401" not in responses
