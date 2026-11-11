"""T148 기업·개인·관리자 다중 역할 권한 경계 E2E.

사용자 유형 4가지
- 개인 사용자(job_seeker)
- 기업 담당자(company_member)
- 기업 관리자(company_owner)
- 운영 관리자(admin)

검증 층(섞지 않는다)
- [ROUTER+MEMORY] 실제 FastAPI 라우터·실제 인증(서명·세션·DB 역할 재조회)
  - 기업(T123)·공고(T126)·공개 포트폴리오(T129) 기능 플래그를 한 앱에서 모두 켠다.
  - 저장소는 메모리다. 이 기능들은 정식 migration 이 없어 기본 의존성이 503 이다.
- [POSTGRESQL] 일회용 PG 18.6 + 실제 0001 스키마·T10 Seed
  - 운영 관리자 경로의 역할 회수·세션 회수·IDOR 를 확인한다.
  - T86 `disposable_pg` 를 쓰고, 앱은 최소 권한 역할로 접속한다.

필수 시나리오 번호는 docs/testing/T148_VALIDATION_REPORT.md §7 표와 같다.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.security import issue_access_token
from app.main import create_app
from app.routers.company_accounts import get_company_service
from app.routers.company_postings import get_posting_service
from app.routers.public_portfolio import get_portfolio_service
from app.services import company_postings as cp
from app.services import public_portfolio as pp
from app.services.company_accounts import CompanyAccountService, MemoryCompanyRepository, UserInfo
from app.services.mail import MemoryMailSender
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository
from tests.security.security_pg import ADMIN, USER_A, USER_B, disposable_pg, requires_pg

API = API_V1_PREFIX
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
FLAGS = ("COMPANY_ACCOUNTS_API", "COMPANY_POSTINGS_API", "PUBLIC_PORTFOLIO_API", "JOB_APPLICATIONS_API")
# 로그인 없이 허용된 경로(검토된 목록). 새 공개 경로가 생기면 이 시험이 실패해 검토를 강제한다.
PUBLIC_ROUTES = {
    "GET /health", "GET /health/db", "GET /version", "GET /api/v1/consent-policies",
    "POST /api/v1/auth/signup", "POST /api/v1/auth/login",
    "POST /api/v1/auth/password-reset-requests", "POST /api/v1/auth/password-resets",
    "GET /api/v1/companies", "GET /api/v1/companies/{company_id}",
    "GET /api/v1/job-postings", "GET /api/v1/job-postings/{job_posting_id}",
    "GET /api/v1/job-roles", "GET /api/v1/job-roles/{job_role_id}", "GET /api/v1/skills",
    "GET /api/v1/public/portfolios/{token}",
}
POSTING = {"title": "백엔드 개발자", "description": "FastAPI 서비스 개발", "employment_type": "full_time",
           "location_text": "서울", "apply_url": "https://careers.example.com/apply",
           "expires_at": (NOW + timedelta(days=30)).isoformat()}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Directory:
    def __init__(self, auth):
        self.auth = auth

    def get(self, uid):
        r = self.auth.get_user(uid)
        return UserInfo(r.user_id, r.email, r.display_name) if r else None


class Profiles:
    def __init__(self):
        self.data: dict[uuid.UUID, pp.ProfileData] = {}

    def load(self, user_id):
        return self.data.get(user_id)


def _app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    for flag in FLAGS:
        monkeypatch.setenv(flag, "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    return app, auth


def _path(route: APIRoute) -> str:
    return re.sub(r"\{([^}]+)\}", lambda m: "x" * 40 if m.group(1) == "token" else str(uuid.uuid4()), route.path)


def _routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route


@pytest.fixture
def world(monkeypatch):
    app, auth = _app(monkeypatch)
    clock, mail = Clock(), MemoryMailSender()
    company_repo = MemoryCompanyRepository()
    accounts = CompanyAccountService(company_repo, Directory(auth), mail, clock=clock)
    posting_repo = cp.MemoryPostingRepository()
    postings = cp.CompanyPostingService(accounts, posting_repo, cp.MemoryPublicPostings(), clock=clock)
    profiles, portfolio_repo = Profiles(), pp.MemoryPortfolioRepository()
    portfolios = pp.PublicPortfolioService(portfolio_repo, profiles, clock=clock)
    app.dependency_overrides[get_company_service] = lambda: accounts
    app.dependency_overrides[get_posting_service] = lambda: postings
    app.dependency_overrides[get_portfolio_service] = lambda: portfolios
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                    raise_server_exceptions=False) as client:
        w = World(app, client, auth, mail, clock, company_repo, posting_repo, profiles, portfolio_repo)
        w.setup()
        yield w
    get_settings.cache_clear()


class World:
    def __init__(self, app, client, auth, mail, clock, company_repo, posting_repo, profiles, portfolio_repo):
        self.app, self.c, self.auth, self.mail, self.clock = app, client, auth, mail, clock
        self.company_repo, self.posting_repo = company_repo, posting_repo
        self.profiles, self.portfolio_repo = profiles, portfolio_repo

    # ---------------------------------------------------------------- people
    def user(self, email, admin=False):
        r = self.c.post(f"{API}/auth/signup", json={"email": email, "password": PASSWORD,
                                                   "display_name": email.split("@")[0], "consents": CONSENTS})
        assert r.status_code == 201, r.text
        uid = self.auth.find_local_identity(email).user_id
        if admin:
            self.auth.grant_role(uid, "admin")
            r = self.c.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        token = r.json()["access_token"]
        return {"h": bearer(token), "id": uid, "token": token}

    def org(self, owner, name):
        body = self.c.post(f"{API}/organizations", json={"name": name}, headers=owner["h"]).json()
        ok = self.c.post(f"{API}/admin/organizations/{body['organization_id']}/verification",
                         json={"decision": "approve", "version": body["version"]}, headers=self.ops["h"])
        assert ok.status_code == 200, ok.text
        return body["organization_id"]

    def join(self, org, owner, who, email, role="member"):
        assert self.c.post(f"{API}/organizations/{org}/invitations", json={"email": email, "role": role},
                           headers=owner["h"]).status_code == 201
        token = self.mail.outbox[-1].link.split("#token=", 1)[1]
        assert self.c.post(f"{API}/organization-invitations/accept", json={"token": token},
                           headers=who["h"]).status_code == 200

    def setup(self):
        self.ops = self.user("ops@example.com", admin=True)                  # 운영 관리자
        self.seeker = self.user("seeker@example.com")                        # 개인 사용자
        self.seeker2 = self.user("seeker2@example.com")
        self.owner = self.user("owner-a@example.com")                        # 기업 A 관리자
        self.member = self.user("member-a@example.com")                      # 기업 A 담당자
        self.rival = self.user("owner-b@example.com")                        # 기업 B 관리자
        self.org_a = self.org(self.owner, "합성 기업 A")
        self.org_b = self.org(self.rival, "합성 기업 B")
        self.join(self.org_a, self.owner, self.member, "member-a@example.com")
        for who in (self.seeker, self.seeker2):
            exp = (uuid.uuid4(),)
            self.profiles.data[who["id"]] = pp.ProfileData(
                display_name="합성 후보", headline="백엔드 개발자", bio="연락처 010-0000-0000 은 비공개",
                location_text="서울 강남구", email="hidden@example.com",
                experiences=(pp.Experience(exp[0], "가상회사", "개발자", None, None, "API"),), projects=(),
                skills=(("Python", 4),), target_roles=("백엔드 개발자",))
            who["exp"] = exp

    # ---------------------------------------------------------------- helpers
    def posting(self, org=None, who=None):
        r = self.c.post(f"{API}/organizations/{org or self.org_a}/postings", json=POSTING,
                        headers=(who or self.member)["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def publish_profile(self, who):
        v = self.c.get(f"{API}/me/public-profile", headers=who["h"]).json()["selection"]["version"]
        assert self.c.put(f"{API}/me/public-profile/selection", headers=who["h"], json={
            "fields": ["display_name", "headline", "experience.organization", "skills"],
            "experience_ids": [str(who["exp"][0])], "project_ids": [], "alias": None, "version": v}).status_code == 200
        v = self.c.get(f"{API}/me/public-profile", headers=who["h"]).json()["selection"]["version"]
        assert self.c.post(f"{API}/me/public-profile/consent", json={"version": v}, headers=who["h"]).status_code == 200
        link = self.c.post(f"{API}/me/public-profile/links", json={"ttl_days": 7}, headers=who["h"])
        assert link.status_code == 201, link.text
        return link.json()

    def view(self, link):
        return self.c.get(f"{API}/public/portfolios/{link['url'].rsplit('/', 1)[1]}")


# =============================================================== 6·7·10 경로 전수: 비로그인 401, 권한 부족 403
def test_6_every_non_public_route_rejects_anonymous_with_401(monkeypatch):
    app, _ = _app(monkeypatch)
    client = TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                        raise_server_exceptions=False)
    seen_public, wrong = set(), []
    for method, route in _routes(app):
        key = f"{method} {route.path}"
        status = client.request(method, _path(route), json={}).status_code
        if key in PUBLIC_ROUTES:
            seen_public.add(key)
            assert status != 401, key
        elif status != 401:
            wrong.append((key, status))
    assert wrong == []
    assert seen_public == PUBLIC_ROUTES                     # 공개 목록에 없는 공개 경로가 생기면 실패
    get_settings.cache_clear()


# 역할 검사를 서비스 안에서 하는(T123·T126) 관리자 경로는 본문 검증이 먼저라, 형식이 맞는 본문을 보내야 403 이 보인다.
ADMIN_BODIES = {
    "/verification": {"decision": "approve", "version": 1},
    "/decision": {"decision": "approve", "version": 1},
    "/takedown": {"reason_code": "other", "note": "합성"},
}


def _admin_body(path):
    return next((b for suffix, b in ADMIN_BODIES.items() if path.endswith(suffix)), {})


def test_7_job_seeker_and_company_roles_get_403_on_every_admin_route(world):
    admin_routes = [(m, r) for m, r in _routes(world.app) if r.path.startswith(f"{API}/admin/")]
    assert len(admin_routes) >= 6
    for who in (world.seeker, world.member, world.owner):
        for method, route in admin_routes:
            r = world.c.request(method, _path(route), json=_admin_body(route.path), headers=who["h"])
            assert r.status_code == 403, (who["id"], method, route.path, r.status_code)
            assert r.json()["code"] == "FORBIDDEN"


def test_7_observation_service_level_admin_checks_validate_the_body_first(world):
    """관찰(F-1, Low): 형식이 틀린 본문은 비관리자에게도 403 대신 422.
    데이터·상태 노출은 없고 스키마는 OpenAPI 에도 공개돼 있다. 라우터 수준 require_roles 로 옮길지 결정 필요."""
    statuses = {}
    before = (len(world.company_repo.audit), len(world.posting_repo.audit))
    for method, route in _routes(world.app):
        if route.path.startswith(f"{API}/admin/") and any(route.path.endswith(s) for s in ADMIN_BODIES):
            statuses[route.path] = world.c.request(method, _path(route), json={}, headers=world.seeker["h"]).status_code
    assert set(statuses.values()) == {422}, statuses
    assert (len(world.company_repo.audit), len(world.posting_repo.audit)) == before


def test_7_company_member_cannot_do_owner_actions_and_admin_has_no_console_access(world):
    org = world.org_a
    assert world.c.post(f"{API}/organizations/{org}/invitations", json={"email": "x@example.com"},
                        headers=world.member["h"]).status_code == 403
    members = world.c.get(f"{API}/organizations/{org}/members", headers=world.member["h"]).json()
    owner_row = next(m for m in members if m["role"] == "owner")
    assert world.c.delete(f"{API}/organizations/{org}/members/{owner_row['user_id']}",
                          headers=world.member["h"]).status_code == 403
    # 운영 관리자는 기업 콘솔(멤버 목록)을 보지 못한다(T121: org.view_console admin=deny)
    assert world.c.get(f"{API}/organizations/{org}/members", headers=world.ops["h"]).status_code in {403, 404}
    # 기업 역할은 스스로 게시할 경로가 없다 — 운영 관리자 결정만
    p = world.posting()
    p = world.c.post(f"{API}/organizations/{org}/postings/{p['posting_id']}/submit",
                     json={"version": p["version"]}, headers=world.member["h"]).json()
    decide = world.c.post(f"{API}/admin/company-postings/{p['posting_id']}/decision",
                          json={"decision": "approve", "version": p["version"]}, headers=world.owner["h"])
    assert decide.status_code == 403


# =============================================================== 1 다른 기업 데이터 차단
def test_1_cross_company_access_is_404_for_every_company_resource(world):
    rival_posting = world.posting(world.org_b, world.rival)
    b = world.org_b
    for method, path, body in [
        ("GET", f"{API}/organizations/{b}", None),
        ("GET", f"{API}/organizations/{b}/members", None),
        ("GET", f"{API}/organizations/{b}/invitations", None),
        ("POST", f"{API}/organizations/{b}/invitations", {"email": "spy@example.com"}),
        ("GET", f"{API}/organizations/{b}/postings", None),
        ("POST", f"{API}/organizations/{b}/postings", POSTING),
        ("GET", f"{API}/organizations/{b}/postings/{rival_posting['posting_id']}", None),
        ("PATCH", f"{API}/organizations/{b}/postings/{rival_posting['posting_id']}",
         {"title": "탈취", "version": rival_posting["version"]}),
        # 내 조직 경로에 남의 공고 id 를 넣어도 404
        ("GET", f"{API}/organizations/{world.org_a}/postings/{rival_posting['posting_id']}", None),
    ]:
        for who in (world.member, world.owner, world.seeker):
            r = world.c.request(method, path, json=body, headers=who["h"])
            assert r.status_code == 404, (who["id"], method, path, r.status_code)
    kept = world.c.get(f"{API}/organizations/{b}/postings/{rival_posting['posting_id']}", headers=world.rival["h"])
    assert kept.status_code == 200 and kept.json()["title"] == POSTING["title"]      # 원본 변경 없음
    assert len(world.c.get(f"{API}/organizations/{b}/postings", headers=world.rival["h"]).json()) == 1


# =============================================================== 2 권한 회수 후 즉시 거부
def test_2_removed_member_loses_access_on_the_next_request(world):
    org = world.org_a
    assert world.c.get(f"{API}/organizations/{org}/postings", headers=world.member["h"]).status_code == 200
    members = world.c.get(f"{API}/organizations/{org}/members", headers=world.owner["h"]).json()
    target = next(m for m in members if m["role"] == "member")
    assert world.c.delete(f"{API}/organizations/{org}/members/{target['user_id']}",
                          headers=world.owner["h"]).status_code == 204
    for method, path, body in [("GET", f"{API}/organizations/{org}", None),
                               ("GET", f"{API}/organizations/{org}/postings", None),
                               ("POST", f"{API}/organizations/{org}/postings", POSTING)]:
        assert world.c.request(method, path, json=body, headers=world.member["h"]).status_code == 404


def test_2_platform_admin_role_revocation_and_session_or_account_disable_apply_immediately(world):
    queue = f"{API}/admin/company-postings"
    assert world.c.get(queue, headers=world.ops["h"]).status_code == 200
    world.auth.revoke_role(world.ops["id"], "admin")
    assert world.c.get(queue, headers=world.ops["h"]).status_code == 403        # 같은 토큰, 다음 요청
    sid = jwt.decode(world.seeker["token"], options={"verify_signature": False})["sid"]
    assert world.c.get(f"{API}/me", headers=world.seeker["h"]).status_code == 200
    world.auth.revoke_session(uuid.UUID(sid), world.seeker["id"], NOW)
    assert world.c.get(f"{API}/me", headers=world.seeker["h"]).status_code == 401
    world.auth.set_status(world.seeker2["id"], "disabled")
    assert world.c.get(f"{API}/me", headers=world.seeker2["h"]).status_code == 401


# =============================================================== 3 역할 토큰 위조 거부
def test_3_forged_or_tampered_tokens_are_rejected_and_token_roles_are_never_trusted(world):
    queue = f"{API}/admin/company-postings"
    claims = jwt.decode(world.seeker["token"], options={"verify_signature": False})
    sid, uid = uuid.UUID(claims["sid"]), world.seeker["id"]
    # (a) 올바른 서명이지만 토큰 안에 admin 을 넣어도 DB 역할을 다시 읽으므로 403
    with_admin_claim = issue_access_token(TEST_SECRET, uid, sid, ["admin"], 600)
    assert world.c.get(queue, headers=bearer(with_admin_claim)).status_code == 403
    # (b) 다른 키로 서명
    other_key = issue_access_token("x" * 64, uid, sid, ["admin"], 600)
    # (c) 서명은 그대로 두고 payload 의 roles 만 바꿈
    head, body, sig = world.seeker["token"].split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["roles"] = ["admin"]
    tampered = ".".join([head, base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("="), sig])
    # (d) alg=none
    none_alg = jwt.encode({**payload}, key="", algorithm="none")
    # (e) 만료
    expired = issue_access_token(TEST_SECRET, uid, sid, [], 60, now=datetime.now(UTC) - timedelta(hours=2))
    # (f) 다른 사람의 세션 id 와 섞음
    other_sid = uuid.UUID(jwt.decode(world.ops["token"], options={"verify_signature": False})["sid"])
    mixed = issue_access_token(TEST_SECRET, uid, other_sid, ["admin"], 600)
    for token in (other_key, tampered, none_alg, expired, mixed, "not.a.jwt", ""):
        r = world.c.get(queue, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, (token[:20], r.status_code)


# =============================================================== 4·8 공유 링크 만료·철회, 비공개 프로필 비노출
def test_4_shared_link_revoke_expiry_and_withdraw_all_return_the_same_404(world):
    link = world.publish_profile(world.seeker)
    ok = world.view(link)
    assert ok.status_code == 200
    body = ok.text
    assert "010-0000-0000" not in body and "hidden@example.com" not in body and "강남구" not in body
    assert world.c.delete(f"{API}/me/public-profile/links/{link['link_id']}",
                          headers=world.seeker["h"]).status_code == 204
    revoked = world.view(link)
    link2 = world.publish_profile(world.seeker)
    world.clock.now += timedelta(days=8)                                   # ttl 7일 초과
    expired = world.view(link2)
    world.clock.now = NOW
    link3 = world.publish_profile(world.seeker)
    assert world.c.delete(f"{API}/me/public-profile/consent", headers=world.seeker["h"]).status_code == 204
    withdrawn = world.view(link3)
    never = world.c.get(f"{API}/public/portfolios/{'A' * 43}")
    assert {r.status_code for r in (revoked, expired, withdrawn, never)} == {404}
    assert len({r.text for r in (revoked, expired, withdrawn, never)}) == 1   # 이유를 구별할 수 없게


def test_8_private_profile_is_not_reachable_before_consent_and_by_other_roles(world):
    # 동의 전에는 링크를 만들 수 없다
    assert world.c.post(f"{API}/me/public-profile/links", json={"ttl_days": 7},
                        headers=world.seeker2["h"]).status_code in {403, 409}
    # 기업·운영 관리자에게 후보자 개인 프로필을 여는 경로가 없다(경로 이름으로 확인)
    exposed = [f"{m} {r.path}" for m, r in _routes(world.app)
               if re.search(r"candidate|portfolio|public-profile", r.path)
               and not r.path.startswith(f"{API}/me/") and r.path != f"{API}/public/portfolios/{{token}}"]
    assert exposed == []


# =============================================================== 5 타 사용자 IDOR
def test_5_idor_on_another_users_share_link_and_invitations(world):
    link = world.publish_profile(world.seeker)
    r = world.c.delete(f"{API}/me/public-profile/links/{link['link_id']}", headers=world.seeker2["h"])
    assert r.status_code == 404
    assert world.view(link).status_code == 200                                 # 남의 요청으로 철회되지 않음
    # 다른 기업 초대 id 로 재전송·취소
    assert world.c.post(f"{API}/organizations/{world.org_b}/invitations", json={"email": "c@example.com"},
                        headers=world.rival["h"]).status_code == 201
    inv = world.c.get(f"{API}/organizations/{world.org_b}/invitations", headers=world.rival["h"]).json()[0]
    for method, path in [("POST", f"{API}/organizations/{world.org_a}/invitations/{inv['invitation_id']}/resend"),
                         ("DELETE", f"{API}/organizations/{world.org_a}/invitations/{inv['invitation_id']}"),
                         ("POST", f"{API}/organizations/{world.org_b}/invitations/{inv['invitation_id']}/resend")]:
        assert world.c.request(method, path, json={}, headers=world.owner["h"]).status_code == 404, path


# =============================================================== 9 감사 추적
def test_9_audit_trail_records_actor_and_action_without_emails(world):
    p = world.posting()
    p = world.c.post(f"{API}/organizations/{world.org_a}/postings/{p['posting_id']}/submit",
                     json={"version": p["version"]}, headers=world.member["h"]).json()
    assert world.c.post(f"{API}/admin/company-postings/{p['posting_id']}/decision",
                        json={"decision": "approve", "version": p["version"]}, headers=world.ops["h"]).status_code == 200
    org_actions = [(a["action_code"], a["actor_user_id"]) for a in world.company_repo.audit]
    assert ("org.verify.approve", world.ops["id"]) in org_actions
    assert ("org.invite.accept", world.member["id"]) in org_actions
    posting_actions = [(a["action_code"], a["actor_user_id"]) for a in world.posting_repo.audit]
    assert [code for code, _ in posting_actions][-3:] == [code for code, _ in posting_actions][-3:]
    assert any(actor == world.ops["id"] for _, actor in posting_actions)
    assert any(actor == world.member["id"] for _, actor in posting_actions)
    dump = repr(world.company_repo.audit) + repr(world.posting_repo.audit)
    assert "@example.com" not in dump                                        # 이메일 원문 없음
    # 거부된 시도는 상태를 바꾸지 않는다(감사에 성공 행이 생기지 않음)
    before = len(world.company_repo.audit)
    world.c.post(f"{API}/organizations/{world.org_b}/invitations", json={"email": "spy@example.com"},
                 headers=world.member["h"])
    assert len(world.company_repo.audit) == before


# =============================================================== 기능 플래그 꺼짐 = 경로 없음(기본 회귀)
def test_10_default_flags_off_expose_no_company_or_portfolio_routes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    for flag in FLAGS:
        monkeypatch.delenv(flag, raising=False)
    get_settings.cache_clear()
    paths = create_app().openapi()["paths"]
    assert not [p for p in paths if re.search(r"organization|company-postings|public-profile|public/portfolios|"
                                              r"job-applications", p)]
    get_settings.cache_clear()


# =============================================================== [POSTGRESQL] 실제 DB 인증
@pytest.fixture
def pg(monkeypatch):
    yield from disposable_pg(monkeypatch, write_tables=("user_experiences", "audit_events"),
                             migrations=("0001", "0002", "0003"))


@requires_pg
def test_pg_admin_role_revocation_session_revocation_and_idor_on_real_db(pg):
    c, h = pg.client, pg.h
    audit = f"{API}/admin/audit-events?from=2026-11-01T00:00:00Z&to=2026-12-01T00:00:00Z"
    assert c.get(audit).status_code == 401
    assert c.get(audit, headers=h[USER_A]).status_code == 403
    assert c.get(audit, headers=h[ADMIN]).status_code == 200
    # 역할 회수(DB) → 같은 토큰으로 다음 요청부터 403
    pg.db.execute("DELETE FROM career.user_roles WHERE user_id = %s AND role_id = "
                  "(SELECT role_id FROM career.roles WHERE code = 'admin')", (ADMIN,))
    assert c.get(audit, headers=h[ADMIN]).status_code == 403
    # 세션 회수(DB) → 401
    pg.db.execute("UPDATE career.auth_sessions SET revoked_at = now() WHERE user_id = %s", (USER_B,))
    assert c.get(f"{API}/me", headers=h[USER_B]).status_code == 401
    # IDOR: A 의 경력을 B 가 아닌 다른 로그인 사용자(관리자 계정, admin 역할 회수됨)로 조회·수정·삭제 → 404
    created = c.post(f"{API}/me/experiences", headers=h[USER_A], json={
        "organization": "합성 회사", "title": "개발자", "start_date": "2024-01-01"})
    assert created.status_code == 201, created.text
    eid = created.json()["experience_id"]
    for method in ("GET", "PATCH", "DELETE"):
        r = c.request(method, f"{API}/me/experiences/{eid}", headers=h[ADMIN], json={"title": "탈취"})
        assert r.status_code in {404, 405}, (method, r.status_code)
    assert pg.scalar("SELECT title FROM career.user_experiences WHERE experience_id = %s", eid) == "개발자"
