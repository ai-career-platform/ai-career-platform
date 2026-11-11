"""T99 고급 검색 — 일회용 PostgreSQL 18 + 최소 권한 앱 역할 + 실제 FastAPI 경로(JOB_SEARCH_ADVANCED=true).

T98 수용 사례(docs/search/t98_acceptance_cases.json)를 그대로 실제 SQL·HTTP 에 돌립니다. 합성 데이터만 씁니다.
seed 의 공고는 이 일회용 DB 에서만 비웁니다(TRUNCATE). 공유 Staging DB 는 쓰지 않습니다.
"""
import json
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies.auth import get_auth_settings
from app.repositories.job_postings import SqlJobPostingRepository
from app.routers.job_postings import get_job_posting_service
from app.services.job_postings import JobPostingService, ListCursor, derive_cursor_key
from tests.security.security_pg import ROOT, disposable_pg, requires_pg

pytestmark = requires_pg
CASES = json.loads((ROOT / "docs/search/t98_acceptance_cases.json").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(CASES["now"].replace("Z", "+00:00"))
PROPOSED_INDEXES = (ROOT / "database/proposed/T99_job_search_indexes.sql").read_text(encoding="utf-8")


def uid(key: str) -> UUID:
    """p01 → ...0001, c1 → ...c001, r1 → ...a001 (합성 고정 ID)."""
    kind, n = key[0], int(key[1:])
    prefix = {"p": "0000", "c": "c000", "r": "a000"}[kind]
    return UUID(f"00000000-0000-4000-8000-{prefix}{n:08d}")


def dataset_sql() -> list[str]:
    def lit(v):
        return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"
    out = ["TRUNCATE career.job_postings CASCADE",
           "INSERT INTO career.data_sources(source_id, code, name, license_ref) VALUES "
           "('00000000-0000-4000-8000-5000000000aa', 't99_synthetic', 'T99 합성', 'synthetic-test-only')"]
    for key, c in CASES["companies"].items():
        out.append(f"INSERT INTO career.companies(company_id, name, source_id) VALUES "
                   f"('{uid(key)}', {lit(c['name'])}, '00000000-0000-4000-8000-5000000000aa')")
    for key, code in CASES["job_roles"].items():
        out.append(f"INSERT INTO career.job_roles(job_role_id, code, name) VALUES ('{uid(key)}', 't99_{code}', 'T99 {code}')")
    for key, p in CASES["postings"].items():
        role = lit(None if p["role"] is None else uid(p["role"]))
        out.append(
            "INSERT INTO career.job_postings(job_posting_id, company_id, job_role_id, source_id, title, employment_type, "
            f"location_text, status, published_at, expires_at) VALUES ('{uid(key)}', '{uid(p['company'])}', {role}, "
            f"'00000000-0000-4000-8000-5000000000aa', {lit(p['title'])}, {lit(p['employment_type'])}, "
            f"{lit(p['location_text'])}, {lit(p['status'])}, {lit(p['published_at'])}, {lit(p['expires_at'])})")
    return out


def frozen_clock(app):
    def service(session: Annotated[Session, Depends(get_db)], settings=Depends(get_auth_settings)) -> JobPostingService:
        return JobPostingService(SqlJobPostingRepository(session), ListCursor(derive_cursor_key(settings.jwt_secret)),
                                 clock=lambda: NOW)
    app.dependency_overrides[get_job_posting_service] = service


def make_pg(monkeypatch, advanced: bool, extra=()):
    monkeypatch.setenv("JOB_SEARCH_ADVANCED", "true" if advanced else "false")
    for ctx in disposable_pg(monkeypatch, write_tables=(), extra_sql=(*dataset_sql(), *extra)):
        frozen_clock(ctx.client.app)
        yield ctx


@pytest.fixture
def adv(monkeypatch):
    yield from make_pg(monkeypatch, True)


@pytest.fixture
def legacy(monkeypatch):
    yield from make_pg(monkeypatch, False)


def query(params: dict) -> str:
    pairs = []
    for k, v in params.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            v = v["repeat"] * v["times"]
        values = v if isinstance(v, list) else [v]
        for item in values:
            if k in {"company_id", "job_role_id"} and item in CASES["companies"] | CASES["job_roles"]:
                item = uid(item)
            pairs.append((k, str(item).lower() if isinstance(item, bool) else str(item)))
    return urlencode(pairs)


def keys(items) -> list[str]:
    reverse = {uid(k): k for k in CASES["postings"]}
    return [reverse[UUID(i["job_posting_id"])] for i in items]


def walk(client, params: dict, size: int) -> list[str]:
    seen, cursor = [], None
    for _ in range(20):
        q = query({**params, "limit": size}) + (f"&cursor={cursor}" if cursor else "")
        r = client.get(f"/api/v1/job-postings?{q}")
        assert r.status_code == 200, r.text
        seen += keys(r.json()["items"])
        cursor = r.json()["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("pagination did not end")


def test_t98_acceptance_cases_on_real_sql(adv):
    for case in CASES["cases"]:
        r = adv.client.get(f"/api/v1/job-postings?{query(case['params'])}")
        assert r.status_code == 200, (case["id"], r.text)
        assert keys(r.json()["items"]) == case["expect"], (case["id"], case["why"])
        assert r.json()["next_cursor"] is None


def test_t98_invalid_cases_are_422(adv):
    for case in CASES["invalid"]:
        r = adv.client.get(f"/api/v1/job-postings?{query(case['params'])}")
        assert r.status_code == 422, (case["id"], r.status_code, r.text)
        assert r.json()["code"] == "VALIDATION_FAILED"


def test_pagination_has_no_duplicates_or_gaps_including_ties(adv):
    for case in CASES["pagination"]:
        full = keys(adv.client.get(f"/api/v1/job-postings?{query(case['params'])}").json()["items"])
        for size in (1, case["page_size"], 3):
            assert walk(adv.client, case["params"], size) == full, (case["id"], size)


def test_cursor_is_bound_to_normalised_filters(adv):
    first = adv.client.get("/api/v1/job-postings?employment_type=full_time&employment_type=contract&limit=1").json()
    cursor = first["next_cursor"]
    same = adv.client.get(f"/api/v1/job-postings?employment_type=contract&employment_type=full_time"
                          f"&employment_type=contract&limit=1&cursor={cursor}")
    assert same.status_code == 200                                       # 순서·중복만 다름 → 같은 조건
    for other in ("employment_type=contract", "employment_type=full_time&employment_type=contract&region=seoul",
                  "employment_type=full_time&employment_type=contract&posted_within=7d",
                  "employment_type=full_time&employment_type=contract&sort=expires_at"):
        r = adv.client.get(f"/api/v1/job-postings?{other}&limit=1&cursor={cursor}")
        assert (r.status_code, r.json()["code"]) == (400, "INVALID_CURSOR"), other


@pytest.mark.parametrize("q", ["' OR '1'='1", "%' ; DROP TABLE career.job_postings; --", "\\", "a\\%b", "$1", "%%%%"])
def test_injection_and_escape_strings_are_plain_text(adv, q):
    r = adv.client.get("/api/v1/job-postings?" + urlencode({"q": q, "include_closed": "true"}))
    assert r.status_code == 200 and r.json()["items"] == []
    assert adv.scalar("SELECT count(*) FROM career.job_postings") == len(CASES["postings"])


def test_region_token_tolerates_spacing_and_rejects_non_regions(adv):
    adv.db.execute("UPDATE career.job_postings SET location_text = E'  서울\\t\\t강남구 ' WHERE job_posting_id = %s",
                   (uid("p01"),))
    adv.db.execute("UPDATE career.job_postings SET location_text = '재택근무' WHERE job_posting_id = %s", (uid("p10"),))
    assert keys(adv.client.get("/api/v1/job-postings?region=seoul").json()["items"]) == ["p01"]
    assert keys(adv.client.get("/api/v1/job-postings?region=gwangju").json()["items"]) == []


def test_reference_time_closing_between_pages_never_repeats_items(adv):
    """페이지 사이에 공고가 마감되면 다음 페이지에서 빠질 수 있지만, 이미 본 공고가 다시 나오지는 않음(계약 §5)."""
    first = adv.client.get("/api/v1/job-postings?limit=3").json()
    seen = keys(first["items"])
    adv.db.execute("UPDATE career.job_postings SET status = 'closed' WHERE job_posting_id = %s", (uid("p09"),))
    rest = keys(adv.client.get(f"/api/v1/job-postings?limit=10&cursor={first['next_cursor']}").json()["items"])
    assert "p09" not in rest and not set(seen) & set(rest)
    assert seen + rest == [k for k in CASES["cases"][0]["expect"] if k != "p09"]


def test_flag_off_keeps_the_t18_contract(legacy):
    by_company_name = legacy.client.get("/api/v1/job-postings?q=" + "베타")
    assert by_company_name.status_code == 200 and by_company_name.json()["items"] == []     # T18: 제목만
    ignored = legacy.client.get("/api/v1/job-postings?employment_type=freelance&region=tokyo")
    assert keys(ignored.json()["items"]) == CASES["cases"][0]["expect"]                     # 모르는 매개변수 무시
    params = {p["name"] for p in legacy.client.get("/openapi.json").json()["paths"]["/api/v1/job-postings"]["get"]["parameters"]}
    assert params == {"q", "company_id", "job_role_id", "include_closed", "sort", "limit", "cursor"}


def test_flag_on_openapi_and_proposed_indexes_apply(adv):
    params = {p["name"] for p in adv.client.get("/openapi.json").json()["paths"]["/api/v1/job-postings"]["get"]["parameters"]}
    assert params == {"q", "company_id", "job_role_id", "employment_type", "region", "posted_within", "include_closed",
                      "sort", "limit", "cursor"}
    adv.db.execute(PROPOSED_INDEXES)                                     # 제안 인덱스는 일회용 DB 에만
    for case in CASES["cases"]:
        r = adv.client.get(f"/api/v1/job-postings?{query(case['params'])}")
        assert keys(r.json()["items"]) == case["expect"], case["id"]    # 인덱스 유무와 무관하게 같은 결과
