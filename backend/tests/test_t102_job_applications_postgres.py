"""T102 개인 지원 기록 API — 일회용 PostgreSQL 18 + 제안 DDL(T101) + 최소 권한 앱 역할 + 실제 FastAPI(JOB_APPLICATIONS_API=true).

합성 사용자 A·B(security_pg)와 seed 공고만 씁니다. 공유 Staging DB 는 쓰지 않습니다.
"""
import logging
from datetime import datetime

from app.services.job_applications import KST

import pytest

from tests.security.security_pg import ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
DDL = (ROOT / "database/proposed/T101_job_applications.sql").read_text(encoding="utf-8")
URL = "/api/v1/me/job-applications"


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("JOB_APPLICATIONS_API", "true")
    yield from disposable_pg(monkeypatch, write_tables=("job_applications",), extra_sql=(DDL,))


def postings(pg, n=3):
    return [str(r[0]) for r in pg.db.execute(
        "SELECT job_posting_id FROM career.job_postings WHERE status = 'published' AND (expires_at IS NULL OR "
        "expires_at > now()) ORDER BY job_posting_id LIMIT %s", (n,)).fetchall()]


def create(pg, user, posting, **body):
    return pg.client.post(URL, json={"job_posting_id": posting, **body}, headers=pg.h[user])


def test_crud_happy_path_and_snapshot(pg):
    (p,) = postings(pg, 1)
    r = create(pg, USER_A, p, memo="자기소개서 초안 준비")
    assert r.status_code == 201, r.text
    app = r.json()
    title, company = pg.db.execute("SELECT p.title, c.name FROM career.job_postings p JOIN career.companies c "
                                   "USING (company_id) WHERE job_posting_id = %s", (p,)).fetchone()
    assert app["stage"] == "interested" and app["version"] == 1 and app["applied_on"] is None
    assert app["posting"] == {"job_posting_id": p, "title": title, "company_name": company, "status": "published",
                              "expires_at": app["posting"]["expires_at"]}
    one = pg.client.get(f"{URL}/{app['application_id']}", headers=pg.h[USER_A])
    assert one.status_code == 200 and one.json() == app
    moved = pg.client.patch(f"{URL}/{app['application_id']}", json={"version": 1, "stage": "applied"}, headers=pg.h[USER_A])
    assert moved.status_code == 200, moved.text
    assert moved.json()["applied_on"] == datetime.now(KST).date().isoformat()          # 지원일 = KST 오늘
    assert moved.json()["version"] == 2 and moved.json()["stage_changed_at"] >= app["stage_changed_at"]
    assert pg.client.delete(f"{URL}/{app['application_id']}", headers=pg.h[USER_A]).status_code == 204
    assert pg.client.get(f"{URL}/{app['application_id']}", headers=pg.h[USER_A]).status_code == 404
    assert pg.scalar("SELECT count(*) FROM career.job_applications") == 0          # 즉시 물리 삭제


def test_other_users_records_are_invisible(pg):
    (p,) = postings(pg, 1)
    app = create(pg, USER_A, p).json()
    path = f"{URL}/{app['application_id']}"
    for method, kwargs in (("get", {}), ("patch", {"json": {"version": 1, "memo": "x"}}), ("delete", {})):
        r = getattr(pg.client, method)(path, headers=pg.h[USER_B], **kwargs)
        assert (r.status_code, r.json()["code"]) == (404, "NOT_FOUND"), method
    assert pg.client.get(URL, headers=pg.h[USER_B]).json()["items"] == []
    assert pg.scalar("SELECT memo IS NULL AND version = 1 FROM career.job_applications") is True
    assert create(pg, USER_B, p).status_code == 201                                  # B 는 같은 공고를 따로 기록 가능


def test_anonymous_is_401(pg):
    assert pg.client.get(URL).status_code == 401
    assert pg.client.post(URL, json={"job_posting_id": postings(pg, 1)[0]}).status_code == 401


def test_duplicate_missing_draft_and_validation(pg):
    p, q = postings(pg, 2)
    assert create(pg, USER_A, p).status_code == 201
    dup = create(pg, USER_A, p)
    assert (dup.status_code, dup.json()["code"]) == (409, "CONFLICT")
    draft = pg.db.execute("UPDATE career.job_postings SET status='draft' WHERE job_posting_id=%s RETURNING 1", (q,))
    assert draft.fetchone() and create(pg, USER_A, q).status_code == 404
    assert create(pg, USER_A, "00000000-0000-4000-8000-00000000dead").status_code == 404
    for body in ({"stage": "hired"}, {"memo": "가" * 2001}, {"extra": 1}, {"stage": "applied", "applied_on": "2999-01-01"},
                 {"stage": "preparing", "applied_on": "2026-11-01"}):
        r = create(pg, USER_A, postings(pg, 3)[2], **body)
        assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED"), body
    assert pg.scalar("SELECT count(*) FROM career.job_applications") == 1


def test_transitions_versions_and_concurrent_edit(pg):
    (p,) = postings(pg, 1)
    app = create(pg, USER_A, p).json()
    path = f"{URL}/{app['application_id']}"
    bad = pg.client.patch(path, json={"version": 1, "stage": "offered"}, headers=pg.h[USER_A])   # 관심 → 합격 금지
    assert (bad.status_code, bad.json()["code"]) == (409, "CONFLICT")
    ok = pg.client.patch(path, json={"version": 1, "stage": "applied"}, headers=pg.h[USER_A]).json()
    stale = pg.client.patch(path, json={"version": 1, "memo": "다른 탭"}, headers=pg.h[USER_A])
    assert (stale.status_code, stale.json()["code"]) == (409, "CONFLICT")
    assert pg.scalar("SELECT memo FROM career.job_applications") is None
    back = pg.client.patch(path, json={"version": ok["version"], "stage": "preparing"}, headers=pg.h[USER_A]).json()
    assert back["applied_on"] is None and back["version"] == 3


def test_listing_pages_filters_and_closed_or_deleted_postings(pg):
    ids = postings(pg, 12)
    created = [create(pg, USER_A, p, stage="applied" if i % 3 == 0 else "interested").json() for i, p in enumerate(ids)]
    seen, cursor = [], None
    while True:
        r = pg.client.get(URL, params={"limit": 5, **({"cursor": cursor} if cursor else {})}, headers=pg.h[USER_A])
        assert r.status_code == 200
        seen += [x["application_id"] for x in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == sorted(a["application_id"] for a in created) and len(seen) == len(set(seen)) == len(ids)
    applied = pg.client.get(URL, params=[("stage", "applied"), ("stage", "applied")], headers=pg.h[USER_A]).json()["items"]
    assert len(applied) == 4 and {x["stage"] for x in applied} == {"applied"}
    first = pg.client.get(URL, params={"limit": 2, "stage": "interested"}, headers=pg.h[USER_A]).json()
    other = pg.client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=pg.h[USER_A])
    assert (other.status_code, other.json()["code"]) == (400, "INVALID_CURSOR")              # 조건이 다른 cursor
    pg.db.execute("UPDATE career.job_postings SET expires_at = now() - interval '1 minute' WHERE job_posting_id = %s",
                  (ids[0],))
    pg.db.execute("DELETE FROM career.user_job_bookmarks WHERE job_posting_id = %s", (ids[1],))
    pg.db.execute("DELETE FROM career.job_posting_skills WHERE job_posting_id = %s", (ids[1],))
    pg.db.execute("DELETE FROM career.job_postings WHERE job_posting_id = %s", (ids[1],))
    views = {x["posting"]["title"]: x["posting"] for x in pg.client.get(URL, params={"limit": 100}, headers=pg.h[USER_A]).json()["items"]}
    statuses = sorted(v["status"] for v in views.values())
    assert statuses.count("closed") >= 1 and statuses.count("unavailable") == 1
    gone = next(v for v in views.values() if v["status"] == "unavailable")
    assert gone["job_posting_id"] is None and gone["title"]                                 # 스냅샷 유지


def test_limit_is_enforced(pg):
    (p, q) = postings(pg, 2)
    pg.db.execute("""INSERT INTO career.job_applications (user_id, job_posting_id, posting_title, company_name)
                     SELECT %s, NULL, '합성 ' || g, '합성' FROM generate_series(1, 500) g""", (USER_A,))
    r = create(pg, USER_A, p)
    assert (r.status_code, r.json()["code"]) == (409, "CONFLICT")
    assert create(pg, USER_B, q).status_code == 201


def test_account_deletion_cascades_and_memo_never_logged(pg, caplog):
    (p,) = postings(pg, 1)
    secret = "메모-민감-문장-T102"
    with caplog.at_level(logging.DEBUG):
        app = create(pg, USER_A, p, memo=secret).json()
        pg.client.patch(f"{URL}/{app['application_id']}", json={"version": 1, "stage": "offered"}, headers=pg.h[USER_A])
    assert secret not in caplog.text
    pg.db.execute("DELETE FROM career.users WHERE user_id = %s", (USER_A,))     # 일회용 DB 의 합성 사용자
    assert pg.scalar("SELECT count(*) FROM career.job_applications") == 0
