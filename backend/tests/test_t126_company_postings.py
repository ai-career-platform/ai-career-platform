"""T126 기업 공고 작성·검수 요청 API — 메모리 저장소 + 실제 FastAPI 라우터·인증.

무단 게시 차단(기업 역할의 게시 경로 없음), 타 기업 수정 차단(404), 검수 우회 금지, 동시 수정 409,
반려 사유 필수, 공개 표는 승인 때만 변경, 게시 중 수정은 수정본으로.
"""

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.routers.company_accounts import get_company_service
from app.routers.company_postings import get_posting_service
from app.services import company_postings as cp
from app.services.company_accounts import CompanyAccountService, Member, MemoryCompanyRepository, UserInfo
from app.services.mail import MemoryMailSender
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

ROOT = Path(__file__).resolve().parents[2]
API = API_V1_PREFIX
SM = json.loads((ROOT / "docs/enterprise/t125_posting_state_machine.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
FULL = {"title": "백엔드 개발자", "description": "FastAPI 서비스 개발", "employment_type": "full_time",
        "location_text": "서울", "apply_url": "https://careers.example.com/apply",
        "expires_at": (NOW + timedelta(days=30)).isoformat()}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Dir:
    def __init__(self, auth):
        self.auth = auth

    def get(self, uid):
        r = self.auth.get_user(uid)
        return UserInfo(r.user_id, r.email, r.display_name) if r else None


@pytest.fixture
def w(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("COMPANY_ACCOUNTS_API", "true")
    monkeypatch.setenv("COMPANY_POSTINGS_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    clock, mail = Clock(), MemoryMailSender()
    accounts = CompanyAccountService(MemoryCompanyRepository(), Dir(auth), mail, clock=clock)
    public = cp.MemoryPublicPostings()
    postings = cp.CompanyPostingService(accounts, cp.MemoryPostingRepository(), public, clock=clock)
    app.dependency_overrides[get_company_service] = lambda: accounts
    app.dependency_overrides[get_posting_service] = lambda: postings
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        world = World(client, auth, mail, clock, accounts, postings, public)
        world.setup()
        yield world
    get_settings.cache_clear()


class World:
    def __init__(self, client, auth, mail, clock, accounts, postings, public):
        self.c, self.auth, self.mail, self.clock = client, auth, mail, clock
        self.accounts, self.postings, self.public = accounts, postings, public

    def user(self, email, admin=False):
        r = self.c.post(f"{API}/auth/signup", json={"email": email, "password": PASSWORD, "display_name": email[:5],
                                                   "consents": CONSENTS})
        if admin:
            self.auth.grant_role(self.auth.find_local_identity(email).user_id, "admin")
            r = self.c.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        return bearer(r.json()["access_token"])

    def org(self, owner, name):
        body = self.c.post(f"{API}/organizations", json={"name": name}, headers=owner).json()
        return body

    def approve_org(self, org):
        assert self.c.post(f"{API}/admin/organizations/{org['organization_id']}/verification",
                           json={"decision": "approve", "version": org["version"]}, headers=self.admin).status_code == 200

    def setup(self):
        self.owner, self.admin = self.user("owner@example.com"), self.user("ops@example.com", admin=True)
        self.member, self.rival = self.user("member@example.com"), self.user("rival@example.com")
        org = self.org(self.owner, "합성 기업")
        self.approve_org(org)
        self.org_id = org["organization_id"]
        self.c.post(f"{API}/organizations/{self.org_id}/invitations", json={"email": "member@example.com"},
                    headers=self.owner)
        token = self.mail.outbox[-1].link.split("#token=", 1)[1]
        assert self.c.post(f"{API}/organization-invitations/accept", json={"token": token},
                           headers=self.member).status_code == 200
        rival = self.org(self.rival, "경쟁 기업")
        self.approve_org(rival)
        self.rival_org = rival["organization_id"]

    def base(self, org=None):
        return f"{API}/organizations/{org or self.org_id}/postings"

    def draft(self, who=None, **values):
        r = self.c.post(self.base(), json={**FULL, **values}, headers=who or self.member)
        assert r.status_code == 201, r.text
        return r.json()

    def act(self, posting, action, who=None, **extra):
        return self.c.post(f"{self.base()}/{posting['posting_id']}/{action}",
                           json={"version": posting["version"], **extra}, headers=who or self.member)

    def decide(self, posting, decision="approve", who=None, **extra):
        return self.c.post(f"{API}/admin/company-postings/{posting['posting_id']}/decision",
                           json={"decision": decision, "version": posting["version"], **extra},
                           headers=who or self.admin)

    def published(self):
        p = self.draft()
        p = self.act(p, "submit").json()
        return self.decide(p).json()


# ------------------------------------------------------------------ 상태 기계·정책 일치
def test_transition_table_matches_t125():
    expected = {(t["from"], t["to"]): t["action"] for t in SM["transitions"]}
    assert cp.TRANSITIONS == expected
    assert cp.REJECT_REASONS == set(SM["reject_reason_codes"])
    assert cp.TAKEDOWN_REASONS == set(SM["takedown_reason_codes"])
    assert cp.MAX_PUBLISH == timedelta(days=SM["limits"]["max_publish_days"])


def test_routes_off_by_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("COMPANY_POSTINGS_API", raising=False)
    get_settings.cache_clear()
    assert not [p for p in create_app().openapi()["paths"] if "postings" in p and "organizations" in p]
    get_settings.cache_clear()


# ------------------------------------------------------------------ 정상 흐름·공개 표
def test_draft_submit_approve_publishes_once_and_close_hides_it(w):
    p = w.draft()
    assert p["status"] == "draft" and w.public.published() == []
    p = w.act(p, "submit").json()
    assert p["status"] == "pending_review" and w.public.published() == []
    queue = w.c.get(f"{API}/admin/company-postings", headers=w.admin).json()
    assert [q["posting_id"] for q in queue] == [p["posting_id"]]
    p = w.decide(p).json()
    assert p["status"] == "published" and len(w.public.published()) == 1
    row = w.public.published()[0]
    assert row["source"] == "company_direct" and row["company"] == "합성 기업"
    p = w.act(p, "close").json()
    assert p["status"] == "closed" and w.public.published() == []


def test_reject_needs_reason_then_edit_returns_to_draft_and_resubmits(w):
    p = w.act(w.draft(), "submit").json()
    assert w.decide(p, "reject").status_code == 422
    assert w.decide(p, "reject", reason_code="other").status_code == 422          # other 는 설명 필수
    rej = w.decide(p, "reject", reason_code="personal_contact_info", note="개인 휴대전화 번호 삭제 필요").json()
    assert rej["status"] == "rejected" and rej["reason_code"] == "personal_contact_info"
    seen = w.c.get(f"{w.base()}/{p['posting_id']}", headers=w.member).json()
    assert seen["reason_note"] == "개인 휴대전화 번호 삭제 필요"
    edited = w.c.patch(f"{w.base()}/{p['posting_id']}", json={"description": "수정함", "version": rej["version"]},
                       headers=w.member).json()
    assert edited["status"] == "draft" and edited["reason_code"] is None
    assert w.act(edited, "submit").json()["status"] == "pending_review"


def test_withdraw_review_back_to_draft(w):
    p = w.act(w.draft(), "submit").json()
    back = w.act(p, "withdraw").json()
    assert back["status"] == "draft"


# ------------------------------------------------------------------ 무단 게시·검수 우회 차단
def test_company_roles_have_no_publish_path(w):
    p = w.act(w.draft(), "submit").json()
    for who in (w.owner, w.member):
        assert w.decide(p, who=who).status_code == 403
        assert w.c.get(f"{API}/admin/company-postings", headers=who).status_code == 403
        assert w.c.post(f"{API}/admin/company-postings/{p['posting_id']}/takedown",
                        json={"reason_code": "other"}, headers=who).status_code == 403
    assert w.public.published() == []


@pytest.mark.parametrize("action", ["close", "withdraw"])
def test_draft_cannot_shortcut(w, action):
    p = w.draft()
    assert w.act(p, action).status_code == 409


def test_cannot_edit_pending_or_published_directly(w):
    p = w.act(w.draft(), "submit").json()
    assert w.c.patch(f"{w.base()}/{p['posting_id']}", json={"title": "몰래", "version": p["version"]},
                     headers=w.member).status_code == 409
    pub = w.decide(p).json()
    assert w.c.patch(f"{w.base()}/{pub['posting_id']}", json={"title": "몰래", "version": pub["version"]},
                     headers=w.member).status_code == 409


def test_admin_member_of_the_org_cannot_approve_own_posting(w):
    # 운영 관리자가 그 조직 멤버이면 자기 검수 금지
    ops = w.auth.find_local_identity("ops@example.com").user_id
    w.accounts.repo.members[(uuid.UUID(w.org_id), ops)] = Member(uuid.UUID(w.org_id), ops, "member", NOW)
    p = w.act(w.draft(), "submit").json()
    assert w.decide(p).status_code == 403


def test_admin_cannot_author_or_edit(w):
    assert w.c.post(w.base(), json=FULL, headers=w.admin).status_code == 404       # 소속 아님
    p = w.draft()
    assert w.c.patch(f"{w.base()}/{p['posting_id']}", json={"title": "x", "version": p["version"]},
                     headers=w.admin).status_code == 404


# ------------------------------------------------------------------ 타 기업·소속
def test_other_company_cannot_see_or_change_postings(w):
    p = w.draft()
    rival_headers = w.rival
    path = f"{w.base()}/{p['posting_id']}"
    assert w.c.get(w.base(), headers=rival_headers).status_code == 404
    assert w.c.get(path, headers=rival_headers).status_code == 404
    assert w.c.patch(path, json={"title": "탈취", "version": p["version"]}, headers=rival_headers).status_code == 404
    assert w.c.post(f"{path}/submit", json={"version": p["version"]}, headers=rival_headers).status_code == 404
    # 자기 조직 경로에 남의 공고 ID 를 넣어도 404
    assert w.c.get(f"{w.base(w.rival_org)}/{p['posting_id']}", headers=rival_headers).status_code == 404


def test_removed_member_loses_access_immediately(w):
    p = w.draft()
    member_id = w.auth.find_local_identity("member@example.com").user_id
    assert w.c.delete(f"{API}/organizations/{w.org_id}/members/{member_id}", headers=w.owner).status_code == 204
    assert w.c.get(f"{w.base()}/{p['posting_id']}", headers=w.member).status_code == 404


def test_pending_org_can_draft_but_not_submit(w):
    org = w.org(w.rival, "검증 대기 기업")
    base = f"{API}/organizations/{org['organization_id']}/postings"
    d = w.c.post(base, json=FULL, headers=w.rival)
    assert d.status_code == 201
    assert w.c.post(f"{base}/{d.json()['posting_id']}/submit", json={"version": 1},
                    headers=w.rival).status_code == 403


# ------------------------------------------------------------------ 동시 수정·검증
def test_stale_version_and_concurrent_edits_conflict(w):
    p = w.draft()
    path = f"{w.base()}/{p['posting_id']}"
    assert w.c.patch(path, json={"title": "첫 수정", "version": p["version"]}, headers=w.member).status_code == 200
    assert w.c.patch(path, json={"title": "늦은 수정", "version": p["version"]}, headers=w.owner).status_code == 409
    fresh = w.c.get(path, headers=w.owner).json()
    results = []

    def edit(title):
        try:
            w.postings.edit(w.auth.find_local_identity("owner@example.com").user_id, uuid.UUID(w.org_id),
                            uuid.UUID(p["posting_id"]), {"title": title}, fresh["version"])
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(getattr(exc, "code", type(exc).__name__))

    threads = [threading.Thread(target=edit, args=(f"동시 {i}",)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and len(results) == 5


def test_submit_requires_required_fields_and_https_link(w):
    d = w.draft(description=None)
    assert w.act(d, "submit").status_code == 422
    assert w.c.post(w.base(), json={**FULL, "apply_url": "http://insecure.example.com"},
                    headers=w.member).status_code == 422


def test_publish_requires_expiry_within_60_days(w):
    p = w.act(w.draft(expires_at=(NOW + timedelta(days=61)).isoformat()), "submit").json()
    assert w.decide(p).status_code == 422


# ------------------------------------------------------------------ 만료·내림·수정본
def test_expiry_and_takedown_close_the_public_row(w):
    a = w.published()
    w.clock.now = NOW + timedelta(days=31)
    listed = w.c.get(w.base(), headers=w.member).json()
    assert next(x for x in listed if x["posting_id"] == a["posting_id"])["status"] == "expired"
    assert w.public.published() == []
    w.clock.now = NOW
    b = w.published()
    assert w.c.post(f"{API}/admin/company-postings/{b['posting_id']}/takedown", json={"reason_code": "nope"},
                    headers=w.admin).status_code == 422
    down = w.c.post(f"{API}/admin/company-postings/{b['posting_id']}/takedown",
                    json={"reason_code": "fraud_suspected", "note": "신고 확인"}, headers=w.admin).json()
    assert down["status"] == "taken_down" and w.public.published() == []
    assert w.act(down, "close").status_code == 409                       # 종료 상태


def test_revision_changes_public_content_only_after_approval(w):
    live = w.published()
    rev = w.c.post(f"{w.base()}/{live['posting_id']}/revisions", headers=w.member).json()
    assert rev["revision_of"] == live["posting_id"] and rev["status"] == "draft"
    assert w.c.post(f"{w.base()}/{live['posting_id']}/revisions", headers=w.member).status_code == 409
    rev = w.c.patch(f"{w.base()}/{rev['posting_id']}", json={"title": "시니어 백엔드 개발자",
                                                             "version": rev["version"]}, headers=w.member).json()
    rev = w.act(rev, "submit").json()
    assert w.public.published()[0]["title"] == "백엔드 개발자"            # 승인 전 공개 내용 그대로
    w.decide(rev)
    rows = w.public.published()
    assert len(rows) == 1 and rows[0]["title"] == "시니어 백엔드 개발자"
    original = w.c.get(f"{w.base()}/{live['posting_id']}", headers=w.member).json()
    assert original["status"] == "published" and original["title"] == "시니어 백엔드 개발자"


def test_duplicate_approve_is_409_and_publishes_once(w):
    p = w.act(w.draft(), "submit").json()
    assert w.decide(p).status_code == 200
    assert w.decide(p).status_code == 409
    assert len(w.public.rows) == 1


def test_revision_of_a_closed_original_cannot_republish(w):
    live = w.published()
    rev = w.c.post(f"{w.base()}/{live['posting_id']}/revisions", headers=w.member).json()
    rev = w.act(rev, "submit").json()
    assert w.act(live, "close").status_code == 200
    assert w.decide(rev).status_code == 409 and w.public.published() == []


def test_blank_title_edit_is_rejected(w):
    p = w.draft()
    assert w.c.patch(f"{w.base()}/{p['posting_id']}", json={"title": None, "version": p["version"]},
                     headers=w.member).status_code == 422


def test_audit_records_actions_without_content(w):
    w.published()
    actions = [a["action_code"] for a in w.postings.repo.audit]
    assert actions == ["posting.draft_create", "posting.submit_review", "posting.publish"]
    assert "FastAPI 서비스 개발" not in repr(w.postings.repo.audit)


def test_default_dependency_is_503_without_storage(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("COMPANY_POSTINGS_API", "true")
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        r = client.post(f"{API}/auth/signup", json={"email": "z@example.com", "password": PASSWORD,
                                                   "display_name": "z", "consents": CONSENTS})
        got = client.get(f"{API}/organizations/{uuid.uuid4()}/postings", headers=bearer(r.json()["access_token"]))
        assert got.status_code == 503
    get_settings.cache_clear()
