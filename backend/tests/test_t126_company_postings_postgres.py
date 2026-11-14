"""T126/T127 기업 공고·운영 검수 — 일회용 PostgreSQL 18 + migration 0008·0009 + 최소 권한 앱 역할 + 실제 FastAPI
(COMPANY_POSTINGS_API=true).

핵심: 초안·검수 중·반려 공고는 공개 공고 API(`GET /job-postings`)·기업 페이지(`/companies`)에 절대 나오지 않고,
운영 승인 뒤에만 나온다. 승인(공개 행 생성)·마감·내림·만료는 상태 변경·감사 이벤트와 한 트랜잭션.
합성 사용자 A·B·관리자(security_pg)와 합성 조직만 씁니다. 공유 Staging DB 는 쓰지 않습니다.
`data_sources('company_direct')` 행은 운영 seed 가 아니라 이 시험의 fixture 데이터입니다(약관 승인 전).
"""
import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import sqlalchemy_url
from app.repositories.company_postings import SqlOrgDirectory, SqlPostingRepository, SqlPublicPostings
from app.services.company_postings import CompanyPostingService
from tests.security.security_pg import ADMIN, ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
MIGRATIONS = ROOT / "database/migrations"
DDL = tuple((MIGRATIONS / name).read_text(encoding="utf-8")
            for name in ("0008_organizations.sql", "0009_company_postings.sql"))
SOURCE = ("INSERT INTO career.data_sources (code, name, license_ref) "
          "VALUES ('company_direct', '기업 직접 등록(시험)', 't126-test-terms')")
# organizations: 승인 때 조직 행 잠금(FOR NO KEY UPDATE)에 UPDATE 권한 필요(0008 이 career_app 에 부여). 행은 바꾸지 않음.
WRITE = ("organization_job_postings", "organization_job_posting_events", "organization_public_companies",
         "companies", "job_postings", "organizations")
API = "/api/v1"
ORG_A, ORG_B = UUID("00000000-0000-4000-8000-0000000012a1"), UUID("00000000-0000-4000-8000-0000000012b1")
ORG_A_NAME = "합성 직접등록 기업 T126"


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("COMPANY_POSTINGS_API", "true")
    for world in disposable_pg(monkeypatch, write_tables=WRITE, extra_sql=(*DDL, SOURCE)):
        for org, name, owner in ((ORG_A, ORG_A_NAME, USER_A), (ORG_B, "합성 경쟁 기업 T126", USER_B)):
            world.db.execute("INSERT INTO career.organizations (organization_id, name, status, verified_at) "
                             "VALUES (%s, %s, 'active', now())", (org, name))
            world.db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) "
                             "VALUES (%s, %s, 'owner')", (org, owner))
        yield world


def fields(title):
    return {"title": title, "description": "FastAPI 서비스 개발", "employment_type": "full_time",
            "location_text": "서울", "apply_url": "https://careers.example.invalid/apply",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()}


def base(org=ORG_A):
    return f"{API}/organizations/{org}/postings"


def draft(pg, title=None, **values):
    title = title or f"T126-PG-{uuid4().hex[:10]}"
    r = pg.client.post(base(), json={**fields(title), **values}, headers=pg.h[USER_A])
    assert r.status_code == 201, r.text
    return r.json()


def act(pg, posting, action, who=USER_A):
    return pg.client.post(f"{base()}/{posting['posting_id']}/{action}", json={"version": posting["version"]},
                          headers=pg.h[who])


def decide(pg, posting, decision="approve", who=ADMIN, **extra):
    return pg.client.post(f"{API}/admin/company-postings/{posting['posting_id']}/decision",
                          json={"decision": decision, "version": posting["version"], **extra}, headers=pg.h[who])


def public_titles(pg, q, include_closed=False):
    r = pg.client.get(f"{API}/job-postings", params={"q": q, "include_closed": str(include_closed).lower()})
    assert r.status_code == 200, r.text
    return [i["title"] for i in r.json()["items"]]


def public_companies(pg):
    r = pg.client.get(f"{API}/companies", params={"q": "T126"})
    assert r.status_code == 200, r.text
    return [c["name"] for c in r.json()["items"]]


def direct_rows(pg):
    return pg.db.execute("SELECT p.job_posting_id, p.status, p.title FROM career.job_postings p "
                         "JOIN career.data_sources s USING (source_id) WHERE s.code = 'company_direct' "
                         "ORDER BY p.created_at").fetchall()


def events(pg, posting_id):
    return [r[0] for r in pg.db.execute("SELECT action_code FROM career.organization_job_posting_events "
                                        "WHERE posting_id = %s ORDER BY occurred_at, action_code",
                                        (posting_id,)).fetchall()]


# ------------------------------------------------------------------ 공개 노출: 승인 전 없음, 승인 후 있음
def test_draft_pending_rejected_never_public_and_approved_is(pg):
    title = f"T126-PG-{uuid4().hex[:10]}"
    d = draft(pg, title)
    assert public_titles(pg, title, include_closed=True) == [] and public_companies(pg) == []
    p = act(pg, d, "submit").json()
    assert p["status"] == "pending_review"
    assert public_titles(pg, title, include_closed=True) == [] and public_companies(pg) == []
    rejected = decide(pg, p, "reject", reason_code="misleading_terms").json()
    assert rejected["status"] == "rejected" and rejected["public_posting_id"] is None
    assert public_titles(pg, title, include_closed=True) == [] and public_companies(pg) == []
    assert direct_rows(pg) == []
    # 반려 후 수정 → 초안 → 재검수 → 승인
    edited = pg.client.patch(f"{base()}/{d['posting_id']}", json={"description": "고친 설명",
                                                                  "version": rejected["version"]},
                             headers=pg.h[USER_A]).json()
    assert edited["status"] == "draft" and edited["reason_code"] is None
    p = act(pg, edited, "submit").json()
    assert public_titles(pg, title, include_closed=True) == []
    approved = decide(pg, p)
    assert approved.status_code == 200, approved.text
    pub = approved.json()
    assert pub["status"] == "published" and pub["public_posting_id"]
    assert public_titles(pg, title) == [title]
    assert public_companies(pg) == [ORG_A_NAME]
    detail = pg.client.get(f"{API}/job-postings/{pub['public_posting_id']}").json()
    assert detail["company"]["name"] == ORG_A_NAME and detail["source_url"] is None     # D-3 결정 전 미복사
    company = pg.client.get(f"{API}/companies/{detail['company']['company_id']}").json()
    assert company["source"] == "company_direct" and company["open_posting_count"] == 1
    # 공개 행은 company_direct 원천, 조직→회사 매핑 1개, 이벤트는 순서대로
    assert [(r[1], r[2]) for r in direct_rows(pg)] == [("published", title)]
    assert pg.scalar("SELECT count(*) FROM career.organization_public_companies WHERE organization_id = %s", ORG_A) == 1
    assert set(events(pg, d["posting_id"])) == {"posting.draft_create", "posting.submit_review", "posting.reject",
                                                "posting.draft_edit", "posting.publish"}
    # 기업이 마감 → 공개 목록에서 사라지고 공개 행은 closed (같은 트랜잭션)
    closed = act(pg, pub, "close").json()
    assert closed["status"] == "closed" and public_titles(pg, title) == []
    assert [r[1] for r in direct_rows(pg)] == ["closed"]
    assert pg.client.get(f"{API}/companies/{detail['company']['company_id']}").json()["open_posting_count"] == 0


def test_company_and_non_admin_cannot_publish_or_read_queue(pg):
    p = act(pg, draft(pg), "submit").json()
    for who in (USER_A, USER_B):
        assert decide(pg, p, who=who).status_code == 403
        assert pg.client.get(f"{API}/admin/company-postings", headers=pg.h[who]).status_code == 403
    queue = pg.client.get(f"{API}/admin/company-postings", headers=pg.h[ADMIN]).json()
    assert [q["posting_id"] for q in queue] == [p["posting_id"]]
    # 다른 조직 사용자는 목록·상세·수정 모두 404, 관리자도 기업 경로로는 작성 불가
    assert pg.client.get(base(), headers=pg.h[USER_B]).status_code == 404
    assert pg.client.get(f"{base()}/{p['posting_id']}", headers=pg.h[USER_B]).status_code == 404
    assert pg.client.get(f"{base(ORG_B)}/{p['posting_id']}", headers=pg.h[USER_B]).status_code == 404
    assert pg.client.post(base(), json=fields("관리자 작성"), headers=pg.h[ADMIN]).status_code == 404
    assert direct_rows(pg) == []


def test_admin_member_of_org_cannot_approve(pg):
    pg.db.execute("INSERT INTO career.organization_members (organization_id, user_id, role) VALUES (%s, %s, 'member')",
                  (ORG_A, ADMIN))
    p = act(pg, draft(pg), "submit").json()
    assert decide(pg, p).status_code == 403 and direct_rows(pg) == []


# ------------------------------------------------------------------ 원자성: 실패하면 아무것도 바뀌지 않음
def test_approve_without_company_direct_source_is_503_and_rolls_back(pg):
    p = act(pg, draft(pg), "submit").json()
    pg.db.execute("UPDATE career.data_sources SET is_active = false WHERE code = 'company_direct'")
    companies_before = pg.scalar("SELECT count(*) FROM career.companies")
    r = decide(pg, p)
    assert r.status_code == 503, r.text
    row = pg.db.execute("SELECT status, version, public_posting_id, published_at FROM career.organization_job_postings "
                        "WHERE posting_id = %s", (p["posting_id"],)).fetchone()
    assert row == ("pending_review", p["version"], None, None)
    assert direct_rows(pg) == [] and pg.scalar("SELECT count(*) FROM career.companies") == companies_before
    assert "posting.publish" not in events(pg, p["posting_id"])
    pg.db.execute("UPDATE career.data_sources SET is_active = true WHERE code = 'company_direct'")
    assert decide(pg, p).status_code == 200 and len(direct_rows(pg)) == 1


def test_publish_requires_expiry_within_60_days(pg):
    p = act(pg, draft(pg, expires_at=(datetime.now(UTC) + timedelta(days=61)).isoformat()), "submit").json()
    assert decide(pg, p).status_code == 422 and direct_rows(pg) == []


def test_duplicate_and_concurrent_approve_publish_once(pg):
    p = act(pg, draft(pg), "submit").json()
    engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=4, max_overflow=0)
    barrier, results = threading.Barrier(4), []

    def worker():
        with Session(engine) as session:
            service = CompanyPostingService(SqlOrgDirectory(session), SqlPostingRepository(session),
                                            SqlPublicPostings(session))
            barrier.wait()
            try:
                service.decide(ADMIN, frozenset({"admin"}), UUID(p["posting_id"]), "approve", None, None, p["version"])
                results.append("ok")
            except AppError as exc:
                results.append(exc.code.value if hasattr(exc.code, "value") else str(exc.code))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert results.count("ok") == 1 and len(results) == 4, results
    assert len(direct_rows(pg)) == 1
    assert events(pg, p["posting_id"]).count("posting.publish") == 1
    assert decide(pg, p).status_code == 409                                       # 늦은 중복 승인


def test_takedown_and_expiry_close_the_public_row(pg):
    a = decide(pg, act(pg, draft(pg), "submit").json()).json()
    assert pg.client.post(f"{API}/admin/company-postings/{a['posting_id']}/takedown", json={"reason_code": "nope"},
                          headers=pg.h[ADMIN]).status_code == 422
    down = pg.client.post(f"{API}/admin/company-postings/{a['posting_id']}/takedown",
                          json={"reason_code": "fraud_suspected", "note": "신고 확인"}, headers=pg.h[ADMIN]).json()
    assert down["status"] == "taken_down"
    assert pg.scalar("SELECT status FROM career.job_postings WHERE job_posting_id = %s", a["public_posting_id"]) == "closed"
    b = decide(pg, act(pg, draft(pg), "submit").json()).json()
    # 만료 시각을 과거로(시험용 직접 조작): 다음 기업 조회 때 expired + 공개 행 closed
    pg.db.execute("UPDATE career.organization_job_postings SET published_at = now() - interval '2 days', "
                  "expires_at = now() - interval '1 minute' WHERE posting_id = %s", (b["posting_id"],))
    pg.db.execute("UPDATE career.job_postings SET published_at = now() - interval '2 days', "
                  "expires_at = now() - interval '1 minute' WHERE job_posting_id = %s", (b["public_posting_id"],))
    listed = pg.client.get(base(), headers=pg.h[USER_A]).json()
    assert next(x for x in listed if x["posting_id"] == b["posting_id"])["status"] == "expired"
    assert [r[1] for r in direct_rows(pg)] == ["closed", "closed"]
    assert "system.expire" in events(pg, b["posting_id"])


def test_revision_changes_public_content_only_after_approval(pg):
    title = f"T126-PG-{uuid4().hex[:10]}"
    live = decide(pg, act(pg, draft(pg, title), "submit").json()).json()
    rev = pg.client.post(f"{base()}/{live['posting_id']}/revisions", headers=pg.h[USER_A]).json()
    assert rev["revision_of"] == live["posting_id"] and rev["public_posting_id"] is None
    assert pg.client.post(f"{base()}/{live['posting_id']}/revisions", headers=pg.h[USER_A]).status_code == 409
    rev = pg.client.patch(f"{base()}/{rev['posting_id']}", json={"title": title + "-시니어", "version": rev["version"]},
                          headers=pg.h[USER_A]).json()
    rev = act(pg, rev, "submit").json()
    assert public_titles(pg, title) == [title]                                    # 승인 전 공개 내용 그대로
    assert decide(pg, rev).status_code == 200
    assert public_titles(pg, title) == [title + "-시니어"] and len(direct_rows(pg)) == 1
    original = pg.client.get(f"{base()}/{live['posting_id']}", headers=pg.h[USER_A]).json()
    assert original["status"] == "published" and original["title"] == title + "-시니어"
    # 원본이 마감된 뒤에는 남은 수정본 승인으로 다시 공개되지 않는다
    rev2 = pg.client.post(f"{base()}/{live['posting_id']}/revisions", headers=pg.h[USER_A]).json()
    rev2 = act(pg, rev2, "submit").json()
    assert act(pg, original, "close").status_code == 200
    assert decide(pg, rev2).status_code == 409 and public_titles(pg, title) == []


# ------------------------------------------------------------------ DB 수준 안전장치
def test_database_rejects_public_row_for_unapproved_or_stale_states(pg):
    published = decide(pg, act(pg, draft(pg), "submit").json()).json()
    pending = act(pg, draft(pg), "submit").json()
    # 게시 전 상태는 공개 행을 가질 수 없다(CHECK)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.db.execute("UPDATE career.organization_job_postings SET public_posting_id = %s WHERE posting_id = %s",
                      (published["public_posting_id"], pending["posting_id"]))
    # 공고만 닫고 공개 행을 published 로 두면 커밋 거부(지연 제약 트리거)
    with pytest.raises(psycopg.errors.CheckViolation):
        with pg.db.transaction():
            pg.db.execute("UPDATE career.organization_job_postings SET status = 'closed', version = version + 1 "
                          "WHERE posting_id = %s", (published["posting_id"],))
    assert pg.scalar("SELECT status FROM career.organization_job_postings WHERE posting_id = %s",
                     published["posting_id"]) == "published"


def test_public_sink_never_touches_crawled_postings(pg):
    seeded = pg.db.execute("SELECT job_posting_id, status FROM career.job_postings WHERE status = 'published' "
                           "LIMIT 1").fetchone()
    engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]))
    with Session(engine) as session:
        SqlPublicPostings(session).close(seeded[0], datetime.now(UTC))
        session.commit()
    engine.dispose()
    assert pg.scalar("SELECT status FROM career.job_postings WHERE job_posting_id = %s", seeded[0]) == seeded[1]
