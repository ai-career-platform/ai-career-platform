"""T123 기업 등록·초대·소속 API — 일회용 PostgreSQL 18 + migration 0008(T122) + 최소 권한 앱 역할 + 실제 FastAPI.

COMPANY_ACCOUNTS_API=true. 메일은 메모리 outbox(실제 발송 없음). 합성 사용자(@example.invalid)만 씁니다.
공유 Staging DB 는 쓰지 않습니다. 동시성 시험은 앱 역할로 연결을 따로 열어 서비스(SqlCompanyRepository)를 직접 호출합니다.
"""
import hashlib
import logging
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import issue_access_token
from app.db import sqlalchemy_url
from app.repositories.company_accounts import SqlCompanyRepository, SqlUserDirectory
from app.routers.account_recovery import get_mail_sender
from app.services.company_accounts import CompanyAccountService
from app.services.mail import MemoryMailSender
from tests.conftest import TEST_SECRET, bearer
from tests.security.security_pg import ADMIN, ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
DDL = (ROOT / "database/migrations/0008_organizations.sql").read_text(encoding="utf-8")
WRITE = ("organizations", "organization_members", "organization_invitations", "audit_events")
API = "/api/v1"
EMAIL_B = "t86-b@example.invalid"


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("COMPANY_ACCOUNTS_API", "true")
    for ctx in disposable_pg(monkeypatch, write_tables=WRITE, extra_sql=(DDL,)):
        ctx.mail = MemoryMailSender()
        ctx.client.app.dependency_overrides[get_mail_sender] = lambda: ctx.mail
        yield ctx
        ctx.client.app.dependency_overrides.clear()


def add_user(pg, email: str) -> uuid.UUID:
    """합성 구직자 한 명(세션 포함)을 더한다. pg.h[uid] 에 인증 헤더."""
    uid = uuid.uuid4()
    pg.db.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                  (uid, email, email, email.split("@")[0]))
    pg.db.execute("INSERT INTO career.user_roles(user_id, role_id) SELECT %s, role_id FROM career.roles "
                  "WHERE code='job_seeker'", (uid,))
    sid = uuid.uuid4()
    pg.db.execute("INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) VALUES(%s,%s,%s,%s)",
                  (sid, uid, uid.hex * 2, datetime.now(UTC) + timedelta(hours=1)))
    pg.h[uid] = bearer(issue_access_token(TEST_SECRET, uid, sid, [], 3600))
    return uid


def register(pg, who=USER_A, name="합성 기업", **extra):
    return pg.client.post(f"{API}/organizations", json={"name": name, **extra}, headers=pg.h[who])


def active_org(pg, owner=USER_A, name="합성 기업") -> str:
    r = register(pg, owner, name)
    assert r.status_code == 201, r.text
    body = r.json()
    ok = pg.client.post(f"{API}/admin/organizations/{body['organization_id']}/verification",
                        json={"decision": "approve", "version": body["version"]}, headers=pg.h[ADMIN])
    assert ok.status_code == 200, ok.text
    return body["organization_id"]


def invite(pg, org, email, who=USER_A, role="member"):
    return pg.client.post(f"{API}/organizations/{org}/invitations", json={"email": email, "role": role},
                          headers=pg.h[who])


def last_token(pg) -> str:
    link = pg.mail.outbox[-1].link
    assert "?" not in link and "#token=" in link
    return link.split("#token=", 1)[1]


def accept(pg, who, token):
    return pg.client.post(f"{API}/organization-invitations/accept", json={"token": token}, headers=pg.h[who])


def team(pg):
    """A(owner) + B(member) 가 있는 active 조직."""
    org = active_org(pg)
    assert invite(pg, org, EMAIL_B).status_code == 201
    r = accept(pg, USER_B, last_token(pg))
    assert r.status_code == 200, r.text
    return org


# ------------------------------------------------------------------ 정상 흐름
def test_register_verify_invite_accept_change_role_remove_on_postgres(pg):
    r = register(pg)
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["version"] == 1
    org = r.json()["organization_id"]
    assert pg.db.execute("SELECT user_id, role FROM career.organization_members WHERE organization_id = %s",
                         (org,)).fetchall() == [(USER_A, "owner")]
    ok = pg.client.post(f"{API}/admin/organizations/{org}/verification", json={"decision": "approve", "version": 1},
                        headers=pg.h[ADMIN])
    assert ok.status_code == 200 and ok.json()["status"] == "active" and ok.json()["version"] == 2
    assert pg.db.execute("SELECT verified_by_user_id, verified_at IS NOT NULL FROM career.organizations").fetchone() \
        == (ADMIN, True)
    assert invite(pg, org, EMAIL_B).status_code == 201
    joined = accept(pg, USER_B, last_token(pg))
    assert joined.status_code == 200 and joined.json()["role"] == "member"
    assert joined.json()["organization"]["organization_id"] == org
    members = pg.client.get(f"{API}/organizations/{org}/members", headers=pg.h[USER_B]).json()
    assert sorted(m["role"] for m in members) == ["member", "owner"]
    assert all("***@" in m["email_masked"] for m in members) and "t86-a@example.invalid" not in str(members)
    mine = pg.client.get(f"{API}/me/organizations", headers=pg.h[USER_B]).json()
    assert [(m["organization"]["organization_id"], m["role"]) for m in mine] == [(org, "member")]
    up = pg.client.patch(f"{API}/organizations/{org}/members/{USER_B}", json={"role": "owner", "version": 1},
                         headers=pg.h[USER_A])
    assert up.status_code == 200 and up.json()["role"] == "owner" and up.json()["version"] == 2
    assert pg.client.delete(f"{API}/organizations/{org}/members/{USER_B}", headers=pg.h[USER_A]).status_code == 204
    assert pg.client.get(f"{API}/organizations/{org}", headers=pg.h[USER_B]).status_code == 404   # 즉시 회수
    actions = [r[0] for r in pg.db.execute("SELECT action_code FROM career.audit_events WHERE action_code LIKE 'org.%' "
                                           "ORDER BY occurred_at, action_code")]
    assert actions == ["org.register", "org.verify.approve", "org.invite.create", "org.invite.accept",
                       "org.member.role_change", "org.member.remove"]
    audit = pg.db.execute("SELECT string_agg(t::text, '|') FROM career.audit_events t").fetchone()[0]
    assert EMAIL_B not in audit


def test_invitation_token_is_stored_only_as_hash_and_never_returned(pg):
    org = active_org(pg)
    r = invite(pg, org, "New.Person@Example.invalid")
    assert r.status_code == 201
    token = last_token(pg)
    assert token not in r.text and "token" not in r.json() and len(token) >= 43
    row = pg.db.execute("SELECT token_hash, email_canonical, expires_at - created_at "
                        "FROM career.organization_invitations").fetchone()
    assert row[0] == hashlib.sha256(token.encode()).hexdigest() and row[1] == "new.person@example.invalid"
    assert row[2] == timedelta(hours=72)
    dump = pg.db.execute("SELECT string_agg(t::text, '|') FROM career.organization_invitations t").fetchone()[0]
    assert token not in dump
    listing = pg.client.get(f"{API}/organizations/{org}/invitations", headers=pg.h[USER_A])
    assert listing.status_code == 200 and token not in listing.text and "new.person@" not in listing.text
    assert listing.json()[0]["email_masked"].startswith("n***@")


# ------------------------------------------------------------------ 수락 실패 = 같은 404, 1회 사용
def test_expired_revoked_rotated_reused_wrong_email_and_unknown_tokens_are_the_same_404(pg):
    org = team(pg)
    guest, other = add_user(pg, "guest@example.invalid"), add_user(pg, "other@example.invalid")
    assert invite(pg, org, "guest@example.invalid").status_code == 201
    token = last_token(pg)
    wrong_email = accept(pg, other, token)
    pg.db.execute("UPDATE career.organization_invitations SET created_at = now() - interval '2 days', "
                  "expires_at = now() - interval '1 minute' WHERE email_canonical = 'guest@example.invalid'")
    expired = accept(pg, guest, token)
    listed = pg.client.get(f"{API}/organizations/{org}/invitations", headers=pg.h[USER_A]).json()
    assert {i["status"] for i in listed if i["email_masked"].startswith("g***@")} == {"expired"}
    assert invite(pg, org, "guest@example.invalid").status_code == 201             # 만료 뒤 새 초대
    rotated = last_token(pg)
    inv_id = pg.db.execute("SELECT invitation_id FROM career.organization_invitations WHERE status = 'pending' "
                           "AND email_canonical = 'guest@example.invalid'").fetchone()[0]
    resent = pg.client.post(f"{API}/organizations/{org}/invitations/{inv_id}/resend", headers=pg.h[USER_A])
    assert resent.status_code == 200 and resent.json()["resend_count"] == 1
    before_resend = accept(pg, guest, rotated)
    fresh = last_token(pg)
    assert accept(pg, guest, fresh).status_code == 200
    reused = accept(pg, guest, fresh)
    assert invite(pg, org, "late@example.invalid").status_code == 201
    late = add_user(pg, "late@example.invalid")
    late_token = last_token(pg)
    late_id = pg.db.execute("SELECT invitation_id FROM career.organization_invitations "
                            "WHERE email_canonical = 'late@example.invalid'").fetchone()[0]
    assert pg.client.delete(f"{API}/organizations/{org}/invitations/{late_id}", headers=pg.h[USER_A]).status_code == 204
    revoked = accept(pg, late, late_token)
    unknown = accept(pg, late, "x" * 43)
    failures = (wrong_email, expired, before_resend, reused, revoked, unknown)
    assert {r.status_code for r in failures} == {404}, [r.status_code for r in failures]
    assert len({r.text for r in failures}) == 1
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE organization_id = %s", org) == 3
    assert pg.scalar("SELECT status FROM career.organization_invitations WHERE invitation_id = %s", late_id) == "revoked"


def test_duplicate_pending_invitation_and_existing_member_conflict_and_resend_cap(pg):
    org = team(pg)
    assert invite(pg, org, "dup@example.invalid").status_code == 201
    assert invite(pg, org, "DUP@Example.invalid").status_code == 409                # 정규화된 같은 이메일
    assert invite(pg, org, EMAIL_B).status_code == 409                              # 이미 멤버
    inv_id = pg.db.execute("SELECT invitation_id FROM career.organization_invitations "
                           "WHERE email_canonical = 'dup@example.invalid'").fetchone()[0]
    for _ in range(5):
        assert pg.client.post(f"{API}/organizations/{org}/invitations/{inv_id}/resend",
                              headers=pg.h[USER_A]).status_code == 200
    over = pg.client.post(f"{API}/organizations/{org}/invitations/{inv_id}/resend", headers=pg.h[USER_A])
    assert over.status_code == 409
    assert pg.scalar("SELECT resend_count FROM career.organization_invitations WHERE invitation_id = %s", inv_id) == 5


def test_mail_unavailable_is_503_and_leaves_no_invitation_row(pg):
    org = active_org(pg)
    pg.mail.available = False
    r = invite(pg, org, "nomail@example.invalid")
    assert (r.status_code, r.json()["code"]) == (503, "DEPENDENCY_UNAVAILABLE")
    assert pg.scalar("SELECT count(*) FROM career.organization_invitations") == 0
    pg.client.app.dependency_overrides.pop(get_mail_sender)                         # 기본 = 공급자 없음
    assert invite(pg, org, "nomail@example.invalid").status_code == 503


# ------------------------------------------------------------------ 권한·IDOR
def test_member_gets_403_and_outsiders_other_orgs_and_admin_get_404(pg):
    org = team(pg)
    rival_owner = add_user(pg, "rival@example.invalid")
    rival = active_org(pg, rival_owner, name="경쟁 기업")
    assert invite(pg, rival, "rival-guest@example.invalid", who=rival_owner).status_code == 201
    rival_inv = pg.db.execute("SELECT invitation_id FROM career.organization_invitations "
                              "WHERE organization_id = %s", (rival,)).fetchone()[0]
    # 같은 조직 member: 역할 부족 403
    assert invite(pg, org, "x@example.invalid", who=USER_B).status_code == 403
    assert pg.client.get(f"{API}/organizations/{org}/invitations", headers=pg.h[USER_B]).status_code == 403
    assert pg.client.patch(f"{API}/organizations/{org}/members/{USER_B}", json={"role": "owner", "version": 1},
                           headers=pg.h[USER_B]).status_code == 403                 # 스스로 승격 불가
    assert pg.client.delete(f"{API}/organizations/{org}/members/{USER_A}", headers=pg.h[USER_B]).status_code == 403
    # 다른 조직 owner·외부인·운영 관리자: 존재 숨김 404
    outsider = add_user(pg, "outsider@example.invalid")
    for who in (rival_owner, outsider, ADMIN):
        for method, path, body in [
            ("get", f"/organizations/{org}", None), ("get", f"/organizations/{org}/members", None),
            ("get", f"/organizations/{org}/invitations", None),
            ("post", f"/organizations/{org}/invitations", {"email": "z@example.invalid"}),
            ("patch", f"/organizations/{org}/members/{USER_A}", {"role": "member", "version": 1}),
            ("delete", f"/organizations/{org}/members/{USER_A}", None),
        ]:
            r = getattr(pg.client, method)(f"{API}{path}", headers=pg.h[who], **({"json": body} if body else {}))
            assert r.status_code == 404, (who, method, path, r.status_code)
    # IDOR: 내 조직 경로에 남의 조직 초대·멤버 ID
    assert pg.client.post(f"{API}/organizations/{org}/invitations/{rival_inv}/resend",
                          headers=pg.h[USER_A]).status_code == 404
    assert pg.client.delete(f"{API}/organizations/{org}/invitations/{rival_inv}", headers=pg.h[USER_A]).status_code == 404
    assert pg.client.patch(f"{API}/organizations/{org}/members/{rival_owner}", json={"role": "member", "version": 1},
                           headers=pg.h[USER_A]).status_code == 404
    assert pg.client.delete(f"{API}/organizations/{org}/members/{rival_owner}", headers=pg.h[USER_A]).status_code == 404
    assert pg.client.get(f"{API}/organizations/{rival}", headers=pg.h[USER_A]).status_code == 404
    assert pg.client.get(f"{API}/organizations/{uuid.uuid4()}", headers=pg.h[USER_A]).status_code == 404
    assert pg.scalar("SELECT status FROM career.organization_invitations WHERE invitation_id = %s", rival_inv) == "pending"
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE organization_id = %s", rival) == 1
    # 멤버는 스스로 탈퇴할 수 있다
    assert pg.client.delete(f"{API}/organizations/{org}/members/{USER_B}", headers=pg.h[USER_B]).status_code == 204
    assert pg.client.get(f"{API}/me/organizations", headers=pg.h[USER_B]).json() == []
    assert pg.client.get(f"{API}/me/organizations").status_code == 401


def test_pending_org_is_viewable_but_cannot_invite(pg):
    org = register(pg).json()
    assert pg.client.get(f"{API}/organizations/{org['organization_id']}", headers=pg.h[USER_A]).status_code == 200
    assert invite(pg, org["organization_id"], EMAIL_B).status_code == 403
    assert pg.scalar("SELECT count(*) FROM career.organization_invitations") == 0


# ------------------------------------------------------------------ 마지막 owner·버전
def test_last_owner_is_protected_and_stale_versions_conflict(pg):
    org = team(pg)
    assert pg.client.delete(f"{API}/organizations/{org}/members/{USER_A}", headers=pg.h[USER_A]).status_code == 409
    assert pg.client.patch(f"{API}/organizations/{org}/members/{USER_A}", json={"role": "member", "version": 1},
                           headers=pg.h[USER_A]).status_code == 409
    assert pg.client.patch(f"{API}/organizations/{org}/members/{USER_B}", json={"role": "owner", "version": 1},
                           headers=pg.h[USER_A]).status_code == 200
    stale = pg.client.patch(f"{API}/organizations/{org}/members/{USER_B}", json={"role": "member", "version": 1},
                            headers=pg.h[USER_A])
    assert (stale.status_code, stale.json()["code"]) == (409, "CONFLICT")
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE organization_id = %s AND role = 'owner'",
                     org) == 2


def _service(session):
    return CompanyAccountService(SqlCompanyRepository(session), SqlUserDirectory(session), MemoryMailSender())


def _race(n, work):
    """앱 역할 연결 n 개로 work(i, service) 를 동시에 실행하고 결과('ok' 또는 예외 코드)를 돌려준다."""
    engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=n, max_overflow=0)
    barrier, results = threading.Barrier(n), []

    def worker(i):
        with Session(engine) as session:
            service = _service(session)
            barrier.wait()
            try:
                work(i, service)
                results.append("ok")
            except AppError as exc:
                results.append(exc.code.value)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    return sorted(results)


def test_two_owners_demoting_each_other_concurrently_leave_one_owner(pg):
    """조직 행 FOR UPDATE: 동시에 서로를 내려도 owner 는 최소 1명(한쪽은 409)."""
    org = uuid.UUID(team(pg))
    assert pg.client.patch(f"{API}/organizations/{org}/members/{USER_B}", json={"role": "owner", "version": 1},
                           headers=pg.h[USER_A]).status_code == 200
    pairs = [(USER_A, USER_B, 2), (USER_B, USER_A, 1)]
    results = _race(2, lambda i, s: s.change_role(pairs[i][0], org, pairs[i][1], "member", pairs[i][2]))
    # 뒤쪽은 마지막 owner 보호(409) 또는 이미 member 로 내려가 역할 부족(403)
    assert results[1] == "ok" and results[0] in {"CONFLICT", "FORBIDDEN"}, results
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE organization_id = %s AND role = 'owner'",
                     org) == 1


def test_two_owners_removing_each_other_concurrently_leave_one_owner(pg):
    org = uuid.UUID(team(pg))
    pg.db.execute("UPDATE career.organization_members SET role = 'owner' WHERE user_id = %s", (USER_B,))
    pairs = [(USER_A, USER_B), (USER_B, USER_A)]
    results = _race(2, lambda i, s: s.remove(pairs[i][0], org, pairs[i][1]))
    # 먼저 잠근 쪽이 상대를 지우면, 뒤쪽은 더는 소속이 아니어서 404
    assert results == ["NOT_FOUND", "ok"], results
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE organization_id = %s AND role = 'owner'",
                     org) == 1


def test_concurrent_accepts_of_one_token_join_once(pg):
    org = active_org(pg)
    assert invite(pg, org, EMAIL_B).status_code == 201
    token = last_token(pg)
    results = _race(4, lambda i, s: s.accept(USER_B, frozenset({"job_seeker"}), token))
    assert results.count("ok") == 1 and set(results) <= {"ok", "NOT_FOUND"}, results
    assert pg.scalar("SELECT count(*) FROM career.organization_members WHERE user_id = %s", USER_B) == 1
    assert pg.scalar("SELECT status FROM career.organization_invitations") == "accepted"


def test_concurrent_invitations_to_one_email_create_one_row(pg):
    org = uuid.UUID(active_org(pg))
    results = _race(4, lambda i, s: s.invite(USER_A, org, "race@example.invalid", "member"))
    assert results == ["CONFLICT"] * 3 + ["ok"], results
    assert pg.scalar("SELECT count(*) FROM career.organization_invitations WHERE status = 'pending'") == 1


# ------------------------------------------------------------------ 조직 등록·운영 검증
def test_verification_is_admin_only_needs_reason_checks_version_and_not_own_org(pg):
    org = register(pg).json()
    path = f"{API}/admin/organizations/{org['organization_id']}/verification"
    assert pg.client.post(path, json={"decision": "approve", "version": 1}, headers=pg.h[USER_A]).status_code == 403
    assert pg.client.post(path, json={"decision": "reject", "version": 1}, headers=pg.h[ADMIN]).status_code == 422
    assert pg.client.post(path, json={"decision": "approve", "version": 9}, headers=pg.h[ADMIN]).status_code == 409
    done = pg.client.post(path, json={"decision": "reject", "reason": "실재 확인 불가", "version": 1}, headers=pg.h[ADMIN])
    assert done.status_code == 200 and done.json()["status"] == "rejected" and done.json()["status_reason"] == "실재 확인 불가"
    assert pg.client.post(path, json={"decision": "approve", "version": 2}, headers=pg.h[ADMIN]).status_code == 409
    assert pg.client.get(f"{API}/organizations/{org['organization_id']}", headers=pg.h[USER_A]).status_code == 404
    assert pg.client.get(f"{API}/me/organizations", headers=pg.h[USER_A]).json() == []
    own = register(pg, ADMIN, "자기 검수").json()
    r = pg.client.post(f"{API}/admin/organizations/{own['organization_id']}/verification",
                       json={"decision": "approve", "version": 1}, headers=pg.h[ADMIN])
    assert r.status_code == 403
    assert pg.client.post(f"{API}/admin/organizations/{uuid.uuid4()}/verification",
                          json={"decision": "approve", "version": 1}, headers=pg.h[ADMIN]).status_code == 404


def test_linked_company_is_unique_among_open_orgs_and_must_exist(pg):
    company = pg.db.execute("SELECT company_id FROM career.companies LIMIT 1").fetchone()
    if company is None:
        source = pg.db.execute("SELECT source_id FROM career.data_sources LIMIT 1").fetchone()[0]
        company = pg.db.execute("INSERT INTO career.companies (name, source_id) VALUES ('합성 회사', %s) "
                                "RETURNING company_id", (source,)).fetchone()
    company_id = str(company[0])
    assert register(pg, USER_A, "A", linked_company_id=company_id).status_code == 201
    assert register(pg, USER_B, "B", linked_company_id=company_id).status_code == 409
    missing = register(pg, USER_B, "C", linked_company_id=str(uuid.uuid4()))
    assert (missing.status_code, missing.json()["code"]) == (422, "VALIDATION_FAILED")
    assert pg.scalar("SELECT count(*) FROM career.organizations") == 1
    assert pg.scalar("SELECT count(*) FROM career.organization_members") == 1
    for body in ({"name": ""}, {"name": "   "}, {"name": "x" * 201}, {"name": "ok", "extra": 1}):
        assert pg.client.post(f"{API}/organizations", json=body, headers=pg.h[USER_A]).status_code == 422


def test_tokens_and_emails_are_not_logged(pg, caplog):
    with caplog.at_level(logging.DEBUG):
        org = active_org(pg)
        assert invite(pg, org, EMAIL_B).status_code == 201
        token = last_token(pg)
        assert accept(pg, USER_B, "y" * 43).status_code == 404
        assert accept(pg, USER_B, token).status_code == 200
    app_logs = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert token not in app_logs and EMAIL_B not in app_logs and "t86-b@" not in app_logs
    assert hashlib.sha256(token.encode()).hexdigest() not in app_logs
