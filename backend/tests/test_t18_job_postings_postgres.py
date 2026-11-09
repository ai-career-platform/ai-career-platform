"""T18 PostgreSQL 통합 테스트 (선택 실행) — T08 Migration + T10 Seed가 적용된 **로컬 일회용 DB** 기준.

`T18_TEST_DATABASE_URL`을 지정했을 때만 실행한다. 호스트가 localhost/127.0.0.1이 아니면 실행을 거부한다.
테스트는 Seed를 바꾸지 않고, 테스트 전용 기업·공고를 넣었다가 끝나면 지운다.

    # 준비 (database/migrations/README.md 절차)
    psql -d career_dev -f database/security/DRAFT_00_create_roles_schema.sql
    psql -d career_dev -f database/security/DRAFT_01_migration_history.sql
    python database/migrate.py apply --target local
    psql -d career_dev -f database/seeds/0001_initial_seed.sql
    # 실행
    export T18_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/career_dev
    python -m pytest tests/test_t18_job_postings_postgres.py -v
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import API_V1_PREFIX, get_settings
from app.core.config import DatabaseSettings
from app.db import create_db_engine
from app.main import create_app
from tests.conftest import TEST_SECRET

DB_URL = os.environ.get("T18_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="T18_TEST_DATABASE_URL not set")

API = API_V1_PREFIX
RUN = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def engine():
    host = make_url(DB_URL).host
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("T18 Postgres tests run only against a local disposable DB")
    eng = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=2, timeout=5))
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def fx(engine):
    """테스트 전용 기업 1곳과 상태별 공고 5건. 끝나면 지운다."""
    ids = {k: uuid.uuid4() for k in ["company", "open_new", "open_noexp", "expired", "closed", "draft"]}
    with engine.begin() as db:
        role_id, skill_default, default_level = db.execute(text("""
            SELECT r.job_role_id, rs.skill_id, rs.required_level
            FROM career.job_roles r JOIN career.job_role_skills rs USING (job_role_id)
            WHERE r.code = 'BACKEND_ENGINEER' ORDER BY rs.required_level DESC, rs.skill_id LIMIT 1""")).one()
        skill_explicit = db.execute(text("""
            SELECT skill_id FROM career.skills WHERE skill_id NOT IN
              (SELECT skill_id FROM career.job_role_skills WHERE job_role_id = :r) ORDER BY code LIMIT 1"""),
            {"r": role_id}).scalar_one()
        db.execute(text("""
            INSERT INTO career.companies (company_id, name, website_url, description, source_id)
            SELECT :id, :name, 'https://t18.example.invalid', 'T18 통합 테스트용 합성 기업', source_id
            FROM career.data_sources WHERE code = 'synthetic_seed'"""),
            {"id": ids["company"], "name": f"T18IT 테스트기업 {RUN}"})
        rows = [
            ("open_new", "published", "now() - interval '1 day'", "now() + interval '10 days'",
             f"T18IT {RUN} 100% 백엔드"),
            ("open_noexp", "published", "now() - interval '2 days'", "NULL", f"T18IT {RUN} 상시채용"),
            ("expired", "published", "now() - interval '40 days'", "now() - interval '1 day'", f"T18IT {RUN} 마감지남"),
            ("closed", "closed", "now() - interval '30 days'", "now() + interval '5 days'", f"T18IT {RUN} 조기마감"),
            ("draft", "draft", "NULL", "NULL", f"T18IT {RUN} 임시저장"),
        ]
        for key, status, pub, exp, title in rows:
            db.execute(text(f"""
                INSERT INTO career.job_postings (job_posting_id, company_id, job_role_id, source_id, title,
                       employment_type, location_text, status, published_at, expires_at)
                SELECT :id, :c, :r, source_id, :t, 'full_time', '서울', :s, {pub}, {exp}
                FROM career.data_sources WHERE code = 'synthetic_seed'"""),
                {"id": ids[key], "c": ids["company"], "r": role_id, "t": title, "s": status})
        db.execute(text("""
            INSERT INTO career.job_posting_skills (job_posting_id, skill_id, is_required, required_level) VALUES
              (:p, :sd, true, NULL), (:p, :se, false, 2)"""),
            {"p": ids["open_new"], "sd": skill_default, "se": skill_explicit})
    ids.update(role=role_id, skill_default=skill_default, default_level=default_level, skill_explicit=skill_explicit)
    yield ids
    with engine.begin() as db:
        db.execute(text("DELETE FROM career.job_postings WHERE company_id = :c"), {"c": ids["company"]})
        db.execute(text("DELETE FROM career.companies WHERE company_id = :c"), {"c": ids["company"]})


@pytest.fixture(scope="module")
def client(fx):
    mp = pytest.MonkeyPatch()
    mp.setenv("APP_ENV", "test")
    mp.setenv("JWT_SECRET", TEST_SECRET)
    mp.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
    mp.undo()


def _all_pages(client, path, params):
    seen, cursor = [], None
    for _ in range(100):
        body = client.get(f"{API}/{path}", params={**params, **({"cursor": cursor} if cursor else {})}).json()
        seen += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("pagination did not end")


def test_default_list_is_open_only_without_gap_or_duplicate(client, engine, fx):
    with engine.connect() as db:
        expected = db.execute(text("""SELECT count(*) FROM career.job_postings
            WHERE status = 'published' AND (expires_at IS NULL OR expires_at > now())""")).scalar_one()
    items = _all_pages(client, "job-postings", {"limit": 7})
    ids = [i["job_posting_id"] for i in items]
    assert len(ids) == len(set(ids)) == expected
    assert {i["status"] for i in items} == {"published"}
    keys = [i["published_at"] for i in items]
    assert keys == sorted(keys, reverse=True)
    for hidden in ("expired", "closed", "draft"):
        assert str(fx[hidden]) not in ids


def test_include_closed_shows_closed_and_expired_as_closed_but_never_draft(client, fx):
    items = _all_pages(client, "job-postings", {"company_id": str(fx["company"]), "include_closed": "true",
                                                "limit": 2})
    status = {i["job_posting_id"]: i["status"] for i in items}
    assert status == {str(fx["open_new"]): "published", str(fx["open_noexp"]): "published",
                      str(fx["expired"]): "closed", str(fx["closed"]): "closed"}


def test_sort_expires_at_puts_soonest_first_and_no_deadline_last(client, fx):
    items = client.get(f"{API}/job-postings", params={"company_id": str(fx["company"]), "sort": "expires_at"}).json()
    assert [i["job_posting_id"] for i in items["items"]] == [str(fx["open_new"]), str(fx["open_noexp"])]


def test_expires_at_pagination_full_seed(client):
    items = _all_pages(client, "job-postings", {"sort": "expires_at", "include_closed": "true", "limit": 9})
    ids = [i["job_posting_id"] for i in items]
    assert len(ids) == len(set(ids))
    with_exp = [i["expires_at"] for i in items if i["expires_at"]]
    assert with_exp == sorted(with_exp)


def test_filters_q_role_company(client, fx):
    r = client.get(f"{API}/job-postings", params={"q": f"t18it {RUN} 100%"}).json()  # 대소문자 무시, % 는 문자 그대로
    assert [i["job_posting_id"] for i in r["items"]] == [str(fx["open_new"])]
    assert client.get(f"{API}/job-postings", params={"q": f"T18IT {RUN} 1_0"}).json()["items"] == []
    r = client.get(f"{API}/job-postings", params={"job_role_id": str(fx["role"]), "limit": 100}).json()
    assert r["items"] and all(i["job_role"]["code"] == "BACKEND_ENGINEER" for i in r["items"])
    assert client.get(f"{API}/job-postings", params={"company_id": str(uuid.uuid4())}).json() == {
        "items": [], "next_cursor": None}


def test_company_list_search_and_detail(client, fx):
    names = [c["name"] for c in _all_pages(client, "companies", {"limit": 6})]
    assert len(names) == len(set(names)) >= 21
    r = client.get(f"{API}/companies", params={"q": f"t18it 테스트기업 {RUN}"}).json()
    assert r == {"items": [{"company_id": str(fx["company"]), "name": f"T18IT 테스트기업 {RUN}"}],
                 "next_cursor": None}
    detail = client.get(f"{API}/companies/{fx['company']}").json()
    assert detail["open_posting_count"] == 2  # 마감 지남·closed·draft 제외
    assert detail["source"] == "synthetic_seed"
    assert detail["website_url"] == "https://t18.example.invalid"


def test_posting_detail_skills_fallback_and_visibility(client, fx):
    d = client.get(f"{API}/job-postings/{fx['open_new']}").json()
    assert d["is_bookmarked"] is None and d["company"]["company_id"] == str(fx["company"])
    skills = {s["skill"]["skill_id"]: s for s in d["required_skills"]}
    assert skills[str(fx["skill_default"])]["required_level"] == fx["default_level"]  # 직무 기본값으로 채움
    explicit = skills[str(fx["skill_explicit"])]
    assert (explicit["required_level"], explicit["is_required"]) == (2, False)
    assert d["required_skills"][0]["is_required"] is True
    assert client.get(f"{API}/job-postings/{fx['closed']}").json()["status"] == "closed"
    assert client.get(f"{API}/job-postings/{fx['expired']}").json()["status"] == "closed"
    r = client.get(f"{API}/job-postings/{fx['draft']}")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_cursor_anchor_closed_between_pages_still_continues(client, engine, fx):
    first = client.get(f"{API}/job-postings", params={"company_id": str(fx["company"]), "limit": 1}).json()
    assert first["items"][0]["job_posting_id"] == str(fx["open_new"])
    with engine.begin() as db:
        db.execute(text("UPDATE career.job_postings SET status = 'closed' WHERE job_posting_id = :p"),
                   {"p": fx["open_new"]})
    try:
        r = client.get(f"{API}/job-postings", params={"company_id": str(fx["company"]), "limit": 1,
                                                      "cursor": first["next_cursor"]})
        assert r.status_code == 200  # 기준 공고가 마감돼도 400이 아니라 같은 위치에서 이어진다
        assert [i["job_posting_id"] for i in r.json()["items"]] == [str(fx["open_noexp"])]
    finally:
        with engine.begin() as db:
            db.execute(text("UPDATE career.job_postings SET status = 'published' WHERE job_posting_id = :p"),
                       {"p": fx["open_new"]})


@pytest.fixture
def extra_undated(engine, fx):
    """마감일·게시일이 없는 마감 공고 2건을 더 넣는다 (NULL 기준 cursor 검증용). 끝나면 지운다."""
    ids = [uuid.uuid4(), uuid.uuid4()]
    with engine.begin() as db:
        for pid in ids:
            db.execute(text("""
                INSERT INTO career.job_postings (job_posting_id, company_id, job_role_id, source_id, title,
                       employment_type, location_text, status, published_at, expires_at)
                SELECT :id, :c, :r, source_id, :t, 'full_time', '서울', 'closed', NULL, NULL
                FROM career.data_sources WHERE code = 'synthetic_seed'"""),
                {"id": pid, "c": fx["company"], "r": fx["role"], "t": f"T18IT {RUN} 날짜없음"})
    yield ids
    with engine.begin() as db:
        db.execute(text("DELETE FROM career.job_postings WHERE job_posting_id = ANY(:ids)"), {"ids": ids})


@pytest.mark.parametrize("limit", [1, 2, 3])
@pytest.mark.parametrize("sort", ["expires_at", "-published_at"])
def test_pagination_survives_null_sort_keys_at_page_boundary(client, fx, extra_undated, sort, limit):
    """NULL 키(infinity)가 페이지 경계가 되어도 500 없이 중복·누락 없이 끝까지 간다."""
    params = {"company_id": str(fx["company"]), "include_closed": "true", "sort": sort, "limit": limit}
    ids = [i["job_posting_id"] for i in _all_pages(client, "job-postings", params)]
    expected = {str(fx[k]) for k in ("open_new", "open_noexp", "expired", "closed")} | {str(i) for i in extra_undated}
    assert len(ids) == len(set(ids)) and set(ids) == expected


def test_company_cursor_survives_rename_of_anchor(client, engine, fx):
    first = client.get(f"{API}/companies", params={"limit": 2}).json()
    anchor = first["items"][-1]["company_id"]
    with engine.begin() as db:
        old = db.execute(text("SELECT name FROM career.companies WHERE company_id = :c"), {"c": anchor}).scalar_one()
        db.execute(text("UPDATE career.companies SET name = :n WHERE company_id = :c"),
                   {"n": "ZZZ T18IT 개명", "c": anchor})
    try:
        rest = client.get(f"{API}/companies", params={"limit": 100, "cursor": first["next_cursor"]})
        assert rest.status_code == 200
        names = {c["name"] for c in rest.json()["items"]}
        assert len(rest.json()["items"]) >= 19 and f"T18IT 테스트기업 {RUN}" in names
    finally:
        with engine.begin() as db:
            db.execute(text("UPDATE career.companies SET name = :n WHERE company_id = :c"), {"n": old, "c": anchor})


def test_default_list_can_use_status_published_index(engine):
    with engine.begin() as db:
        db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(db.execute(text("""EXPLAIN SELECT job_posting_id FROM career.job_postings
            WHERE status = 'published' AND (expires_at IS NULL OR expires_at > now())
            ORDER BY published_at DESC, job_posting_id DESC LIMIT 21""")).scalars())
    assert "ix_job_postings_3" in plan
