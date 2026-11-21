"""T129 공개 포트폴리오 API — 일회용 PostgreSQL 18 + migration 0007(T128) + 최소 권한 앱 역할 + 실제 FastAPI(PUBLIC_PORTFOLIO_API=true).

합성 사용자 A·B(security_pg)와 합성 경력·프로젝트만 씁니다. 공유 Staging DB 는 쓰지 않습니다.
`consent_policies('public_profile', ...)` 행은 운영 seed 가 아니라 이 시험의 fixture 데이터입니다(약관 승인 전).
"""
import hashlib
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_url
from app.repositories.public_portfolio import SqlPortfolioRepository
from tests.security.security_pg import ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
DDL = (ROOT / "database/migrations/0007_public_portfolio.sql").read_text(encoding="utf-8")
POLICY_VERSION = "t129-test-1"
POLICY = ("INSERT INTO career.consent_policies (policy_code, version, is_required, content_url, effective_at) "
          f"VALUES ('public_profile', '{POLICY_VERSION}', false, 'https://example.invalid/public-profile', "
          "now() - interval '1 day')")
ME = "/api/v1/me/public-profile"
PUBLIC = "/api/v1/public/portfolios"
SECRET_BIO = "연락처 010-0000-0000 은 비공개-T129"
WRITE = ("public_profile_selections", "public_profile_selected_experiences", "public_profile_selected_projects",
         "public_profile_consent_records", "public_profile_links", "user_consents")


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("PUBLIC_PORTFOLIO_API", "true")
    yield from disposable_pg(monkeypatch, write_tables=WRITE, extra_sql=(DDL, POLICY))


def seed_profile(pg, user, org):
    """합성 프로필: 경력 2개(하나는 비공개로 둘 것), 프로젝트 1개, 기술 1개."""
    pg.db.execute("INSERT INTO career.user_profiles (user_id, headline, bio, location_text) VALUES (%s, %s, %s, %s)",
                  (user, f"{org} 백엔드", SECRET_BIO, "서울 강남구"))
    shown, hidden, proj = uuid4(), uuid4(), uuid4()
    pg.db.execute("INSERT INTO career.user_experiences (experience_id, user_id, organization, title, start_date, end_date, "
                  "description) VALUES (%s, %s, %s, '개발자', '2023-03-15', '2025-01-31', 'API 개발'), "
                  "(%s, %s, %s, '인턴', '2022-01-01', NULL, NULL)", (shown, user, org, hidden, user, f"{org}-비공개회사"))
    pg.db.execute("INSERT INTO career.user_projects (project_id, user_id, title, summary) VALUES (%s, %s, %s, '요약')",
                  (proj, user, f"{org}-비공개프로젝트"))
    pg.db.execute("INSERT INTO career.user_skills (user_id, skill_id, proficiency) "
                  "SELECT %s, skill_id, 4 FROM career.skills ORDER BY code LIMIT 1", (user,))
    return {"shown": str(shown), "hidden": str(hidden), "proj": str(proj)}


def settings(pg, user):
    return pg.client.get(ME, headers=pg.h[user])


def select(pg, user, fields, exp=(), proj=(), alias=None, version=None):
    version = version or settings(pg, user).json()["selection"]["version"]
    return pg.client.put(f"{ME}/selection", headers=pg.h[user], json={
        "fields": fields, "experience_ids": list(exp), "project_ids": list(proj), "alias": alias, "version": version})


def confirm(pg, user):
    version = settings(pg, user).json()["selection"]["version"]
    return pg.client.post(f"{ME}/consent", json={"version": version}, headers=pg.h[user])


def share(pg, user, ttl_days=30):
    return pg.client.post(f"{ME}/links", json={"ttl_days": ttl_days}, headers=pg.h[user])


def token_of(link):
    return link["url"].rsplit("/", 1)[1]


def view(pg, link):
    return pg.client.get(f"{PUBLIC}/{token_of(link)}")


def publish(pg, user=USER_A, org="가상테크"):
    items = seed_profile(pg, user, org)
    r = select(pg, user, ["display_name", "headline", "experience.organization", "experience.title",
                          "experience.period", "skills"], exp=[items["shown"]])
    assert r.status_code == 200, r.text
    assert confirm(pg, user).status_code == 200
    link = share(pg, user)
    assert link.status_code == 201, link.text
    return items, link.json()


def test_selection_and_consent_version_are_stored(pg):
    items = seed_profile(pg, USER_A, "가상테크")
    assert settings(pg, USER_A).json() == {"selection": {"fields": [], "experience_ids": [], "project_ids": [],
                                                         "alias": None, "version": 1, "consented": False}, "links": []}
    assert pg.client.get(f"{ME}/preview", headers=pg.h[USER_A]).json() == {}
    saved = select(pg, USER_A, ["headline", "experience.title"], exp=[items["shown"]], alias="  백엔드 K ")
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"fields": ["experience.title", "headline"], "experience_ids": [items["shown"]],
                            "project_ids": [], "alias": "백엔드 K", "version": 2, "consented": False}
    stale = select(pg, USER_A, ["bio"], version=1)
    assert (stale.status_code, stale.json()["code"]) == (409, "CONFLICT")
    assert share(pg, USER_A).status_code == 409                                         # 미리보기 확인 전
    ok = confirm(pg, USER_A)
    assert ok.status_code == 200 and ok.json()["consented"] is True and ok.json()["version"] == 2
    row = pg.db.execute("SELECT c.policy_code, c.policy_version, c.granted, r.selection_version "
                        "FROM career.user_consents c JOIN career.public_profile_consent_records r USING (consent_id) "
                        "WHERE c.user_id = %s", (USER_A,)).fetchall()
    assert row == [("public_profile", POLICY_VERSION, True, 2)]
    assert pg.scalar("SELECT confirmed_version FROM career.public_profile_selections WHERE user_id = %s", USER_A) == 2
    # 선택을 바꾸면 동의가 풀린다(PP-INV-7)
    assert select(pg, USER_A, ["headline"]).json()["consented"] is False
    assert pg.scalar("SELECT confirmed_version FROM career.public_profile_selections WHERE user_id = %s", USER_A) is None


def test_never_public_fields_and_empty_confirm_are_rejected(pg):
    seed_profile(pg, USER_A, "가상테크")
    for field in ("email", "documents"):
        r = select(pg, USER_A, ["headline", field])
        assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED"), field
    r = confirm(pg, USER_A)
    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED")
    assert pg.scalar("SELECT count(*) FROM career.public_profile_selections") == 0
    with pytest.raises(psycopg.errors.CheckViolation):                               # DB 도 막는다(PP-INV-2)
        pg.db.execute("INSERT INTO career.public_profile_selections (user_id, fields) VALUES (%s, ARRAY['email'])",
                      (USER_A,))


def test_link_stores_only_the_hash_and_public_view_shows_only_selected_fields(pg):
    items, link = publish(pg)
    token = token_of(link)
    assert len(token) >= 43 and link["notice"]
    stored = pg.db.execute("SELECT token_hash, expires_at - created_at FROM career.public_profile_links").fetchall()
    assert [s[0] for s in stored] == [hashlib.sha256(token.encode()).hexdigest()]
    assert stored[0][1].days == 30
    dump = pg.db.execute("SELECT string_agg(t::text, '|') FROM career.public_profile_links t").fetchone()[0]
    assert token not in dump                                                           # 원문 저장 없음
    assert token not in settings(pg, USER_A).text
    r = view(pg, link)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store" and r.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert r.headers["referrer-policy"] == "no-referrer"
    body = r.json()
    assert set(body) == {"display_name", "headline", "experiences", "skills", "shared_until"}
    assert body["display_name"] == "합성 사용자" and body["headline"] == "가상테크 백엔드"
    assert body["experiences"] == [{"organization": "가상테크", "title": "개발자",
                                    "period": {"start": "2023-03", "end": "2025-01"}}]
    assert len(body["skills"]) == 1 and body["skills"][0]["proficiency"] == 4
    for secret in (SECRET_BIO, "t86-a@example.invalid", "가상테크-비공개회사", "가상테크-비공개프로젝트", "서울 강남구",
                   "API 개발", items["hidden"], str(USER_A)):
        assert secret not in r.text, secret
    preview = pg.client.get(f"{ME}/preview", headers=pg.h[USER_A]).json()
    body.pop("shared_until")
    assert preview == body
    assert pg.scalar("SELECT view_count FROM career.public_profile_links") == 1
    # 소유자 데이터를 지우면 즉시 사라짐(CASCADE 로 선택 행도 정리)
    pg.db.execute("DELETE FROM career.user_experiences WHERE experience_id = %s", (items["shown"],))
    assert view(pg, link).json()["experiences"] == []
    assert pg.scalar("SELECT count(*) FROM career.public_profile_selected_experiences") == 0


def test_revoked_expired_unknown_and_unconsented_links_are_the_same_404(pg):
    _, link = publish(pg)
    second = share(pg, USER_A).json()
    third = share(pg, USER_A).json()
    assert pg.client.delete(f"{ME}/links/{link['link_id']}", headers=pg.h[USER_A]).status_code == 204
    assert pg.client.delete(f"{ME}/links/{link['link_id']}", headers=pg.h[USER_A]).status_code == 204   # 멱등
    pg.db.execute("UPDATE career.public_profile_links SET created_at = now() - interval '2 days', "
                  "expires_at = now() - interval '1 minute' WHERE link_id = %s", (second["link_id"],))
    revoked, expired = view(pg, link), view(pg, second)
    unknown = pg.client.get(f"{PUBLIC}/{'A' * 43}")
    assert view(pg, third).status_code == 200
    select(pg, USER_A, ["headline", "bio"])                                              # 재확인 전
    unconsented = view(pg, third)
    responses = (revoked, expired, unknown, unconsented)
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1
    listed = {x["link_id"]: x for x in settings(pg, USER_A).json()["links"]}
    assert listed[link["link_id"]]["revoked"] is True and listed[third["link_id"]]["revoked"] is False


def test_other_users_selection_and_links_are_inaccessible(pg):
    items, link = publish(pg)
    seed_profile(pg, USER_B, "다른회사")
    r = select(pg, USER_B, ["experience.title"], exp=[items["shown"]])                  # 남의 경력 선택
    assert (r.status_code, r.json()["code"]) == (404, "NOT_FOUND")
    gone = pg.client.delete(f"{ME}/links/{link['link_id']}", headers=pg.h[USER_B])
    assert (gone.status_code, gone.json()["code"]) == (404, "NOT_FOUND")
    other = settings(pg, USER_B).json()
    assert other["links"] == [] and other["selection"]["version"] == 1
    assert link["link_id"] not in settings(pg, USER_B).text
    assert pg.client.get(f"{ME}/preview", headers=pg.h[USER_B]).json() == {}
    assert view(pg, link).status_code == 200                                             # A 링크는 그대로
    assert pg.scalar("SELECT revoked_at IS NULL FROM career.public_profile_links") is True
    # DB 수준: 복합 FK 가 남의 항목 선택을 막는다
    pg.db.execute("INSERT INTO career.public_profile_selections (user_id) VALUES (%s)", (USER_B,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg.db.execute("INSERT INTO career.public_profile_selected_experiences (user_id, experience_id) VALUES (%s, %s)",
                      (USER_B, items["shown"]))
    assert pg.client.get(ME).status_code == 401 and pg.client.post(f"{ME}/links", json={}).status_code == 401


def test_three_active_links_limit_and_ttl_bounds(pg):
    _, first = publish(pg)
    assert share(pg, USER_A, ttl_days=91).status_code == 422
    assert share(pg, USER_A, ttl_days=0).status_code == 422
    assert share(pg, USER_A, ttl_days=90).status_code == 201
    assert share(pg, USER_A, ttl_days=7).status_code == 201
    over = share(pg, USER_A)
    assert (over.status_code, over.json()["code"]) == (409, "CONFLICT")
    assert pg.scalar("SELECT count(*) FROM career.public_profile_links") == 3
    assert pg.client.delete(f"{ME}/links/{first['link_id']}", headers=pg.h[USER_A]).status_code == 204
    assert share(pg, USER_A).status_code == 201
    with pytest.raises(psycopg.errors.CheckViolation):                                   # TTL 90일 상한(DB)
        pg.db.execute("INSERT INTO career.public_profile_links (user_id, token_hash, expires_at) "
                      "VALUES (%s, %s, now() + interval '91 days')", (USER_A, "0" * 64))


def test_concurrent_link_creation_never_exceeds_three(pg):
    """선택 행 FOR UPDATE 잠금: 동시에 6개를 만들어도 활성 링크는 3개(앱 역할·별도 연결 6개)."""
    publish(pg)
    assert pg.client.delete(f"{ME}/links/{settings(pg, USER_A).json()['links'][0]['link_id']}",
                            headers=pg.h[USER_A]).status_code == 204
    engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=6, max_overflow=0)
    barrier, results = threading.Barrier(6), []

    def worker(i):
        with Session(engine) as session:
            barrier.wait()
            now = datetime.now(UTC)
            results.append(SqlPortfolioRepository(session).add_link(
                USER_A, hashlib.sha256(f"race-{i}".encode()).hexdigest(), now, now + timedelta(days=1), 3))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert sorted(r if isinstance(r, str) else "ok" for r in results) == ["limit"] * 3 + ["ok"] * 3
    assert pg.scalar("SELECT count(*) FROM career.public_profile_links WHERE revoked_at IS NULL") == 3


def test_withdraw_revokes_every_link_and_resets_selection(pg):
    _, link = publish(pg)
    second = share(pg, USER_A).json()
    assert pg.client.delete(f"{ME}/consent", headers=pg.h[USER_A]).status_code == 204
    assert view(pg, link).status_code == 404 and view(pg, second).status_code == 404
    s = settings(pg, USER_A).json()
    assert s["selection"]["fields"] == [] and s["selection"]["experience_ids"] == [] and not s["selection"]["consented"]
    assert all(x["revoked"] for x in s["links"])
    rows = pg.db.execute("SELECT c.granted, r.selection_version FROM career.user_consents c "
                         "JOIN career.public_profile_consent_records r USING (consent_id) "
                         "WHERE c.user_id = %s ORDER BY c.recorded_at, c.granted DESC", (USER_A,)).fetchall()
    assert rows == [(True, 2), (False, 2)]
    assert share(pg, USER_A).status_code == 409


def test_confirm_without_a_public_profile_policy_is_503_and_publishes_nothing(pg):
    seed_profile(pg, USER_A, "가상테크")
    pg.db.execute("DELETE FROM career.consent_policies WHERE policy_code = 'public_profile'")
    assert select(pg, USER_A, ["headline"]).status_code == 200
    r = confirm(pg, USER_A)
    assert (r.status_code, r.json()["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert settings(pg, USER_A).json()["selection"]["consented"] is False
    assert share(pg, USER_A).status_code == 409


def test_account_deletion_cascades_and_nothing_personal_is_logged(pg, caplog):
    with caplog.at_level(logging.DEBUG):
        _, link = publish(pg)
        token = token_of(link)
        assert view(pg, link).status_code == 200
    # 앱 로그만 본다(httpx 는 시험 클라이언트 자체의 요청 로그). 접근 로그 경로는 ':token' 으로 가려진다.
    app_logs = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert "/api/v1/public/portfolios/:token" in app_logs
    assert token not in app_logs and SECRET_BIO not in app_logs and "가상테크" not in app_logs
    pg.db.execute("DELETE FROM career.users WHERE user_id = %s", (USER_A,))              # 일회용 DB 의 합성 사용자
    for table in ("public_profile_selections", "public_profile_selected_experiences", "public_profile_links",
                  "public_profile_consent_records"):
        assert pg.scalar(f"SELECT count(*) FROM career.{table}") == 0, table
    assert view(pg, link).status_code == 404
