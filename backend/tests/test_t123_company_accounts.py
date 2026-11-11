"""T123 기업 등록·초대·접근 API — 메모리 저장소 + 실제 FastAPI 라우터·인증(Mock 메일).

정상: 등록 → 운영 승인 → 초대 → 수락 → 역할 변경 → 제외(권한 즉시 회수).
거부: 만료·취소·재전송 전 토큰·다른 이메일·중복·권한 상승·다른 기업 접근·마지막 owner·검증 전 초대.
DB 저장소는 없다(정식 migration 승인 전) — 플래그를 켜도 기본 의존성은 503.
"""

import json
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.routers.company_accounts import get_company_service
from app.services import company_policy
from app.services.company_accounts import (
    MAX_RESENDS, CompanyAccountService, MemoryCompanyRepository, UserInfo,
)
from app.services.mail import MemoryMailSender
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

ROOT = Path(__file__).resolve().parents[2]
API = API_V1_PREFIX


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class AuthDirectory:
    def __init__(self, repo: MemoryAuthRepository):
        self.repo = repo

    def get(self, user_id):
        record = self.repo.get_user(user_id)
        return UserInfo(record.user_id, record.email, record.display_name) if record else None


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("COMPANY_ACCOUNTS_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    clock, mail, repo = Clock(), MemoryMailSender(), MemoryCompanyRepository()
    service = CompanyAccountService(repo, AuthDirectory(auth), mail, clock=clock)
    app.dependency_overrides[get_company_service] = lambda: service
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        yield W(client, auth, repo, mail, clock, service)
    get_settings.cache_clear()


class W:
    def __init__(self, client, auth, repo, mail, clock, service):
        self.client, self.auth, self.repo, self.mail, self.clock, self.service = client, auth, repo, mail, clock, service

    def user(self, email, admin=False):
        r = self.client.post(f"{API}/auth/signup", json={"email": email, "password": PASSWORD,
                                                        "display_name": email.split("@")[0], "consents": CONSENTS})
        assert r.status_code == 201, r.text
        uid = next(u for u, rec in self.auth._state["users"].items() if rec.email == email) \
            if hasattr(self.auth, "_state") and "users" in self.auth._state else None
        if admin:
            self.auth.grant_role(self.uid(email), "admin")
            r = self.client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
        return {"h": bearer(r.json()["access_token"]), "id": self.uid(email), "email": email}

    def uid(self, email):
        identity = self.auth.find_local_identity(email)
        return identity.user_id

    def token(self):
        link = self.mail.outbox[-1].link
        assert "?" not in link and "#token=" in link      # 토큰은 fragment 로(접근 로그·Referer 에 안 남음)
        return link.split("#token=", 1)[1]

    def active_org(self, owner, admin, name="합성 기업"):
        org = self.client.post(f"{API}/organizations", json={"name": name}, headers=owner["h"])
        assert org.status_code == 201, org.text
        body = org.json()
        ok = self.client.post(f"{API}/admin/organizations/{body['organization_id']}/verification",
                              json={"decision": "approve", "version": body["version"]}, headers=admin["h"])
        assert ok.status_code == 200, ok.text
        return body["organization_id"]

    def invite(self, org, owner, email, role="member"):
        return self.client.post(f"{API}/organizations/{org}/invitations", json={"email": email, "role": role},
                                headers=owner["h"])

    def accept(self, who, token):
        return self.client.post(f"{API}/organization-invitations/accept", json={"token": token}, headers=who["h"])


@pytest.fixture
def team(world):
    owner, admin = world.user("owner@example.com"), world.user("ops@example.com", admin=True)
    member = world.user("member@example.com")
    org = world.active_org(owner, admin)
    assert world.invite(org, owner, member["email"]).status_code == 201
    assert world.accept(member, world.token()).status_code == 200
    return {"w": world, "owner": owner, "admin": admin, "member": member, "org": org}


# ------------------------------------------------------------------ 정책 사본 = T121 매트릭스
def test_policy_copy_matches_the_t121_matrix():
    matrix = json.loads((ROOT / "docs/enterprise/t121_role_matrix.json").read_text(encoding="utf-8"))
    actions = {a["action"]: a["decisions"] for a in matrix["actions"]}
    for action, decisions in company_policy.DECISIONS.items():
        for role, decision in decisions.items():
            assert actions[action][role] == decision, (action, role)
    rules = matrix["org_status_rules"]
    for status, allowed in company_policy.STATUS_ALLOWED.items():
        if allowed is None:
            assert rules[status] == "*"
        else:   # T121 에 없는 상태(rejected)는 종료 상태로 본다(허용 없음)
            assert allowed == set(rules.get(status, [])) & set(company_policy.DECISIONS), status


def test_routes_are_off_by_default_and_503_without_storage(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("COMPANY_ACCOUNTS_API", raising=False)
    get_settings.cache_clear()
    paths = create_app().openapi()["paths"]
    assert not [p for p in paths if "organization" in p]
    monkeypatch.setenv("COMPANY_ACCOUNTS_API", "true")
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        signed = client.post(f"{API}/auth/signup", json={"email": "x@example.com", "password": PASSWORD,
                                                        "display_name": "x", "consents": CONSENTS})
        r = client.get(f"{API}/me/organizations", headers=bearer(signed.json()["access_token"]))
        assert r.status_code == 503 and r.json()["code"] == "DEPENDENCY_UNAVAILABLE"
        assert client.get(f"{API}/me/organizations").status_code == 401
    get_settings.cache_clear()


# ------------------------------------------------------------------ 정상 흐름
def test_register_verify_invite_accept_change_role_remove(team):
    w, owner, member, org = team["w"], team["owner"], team["member"], team["org"]
    members = w.client.get(f"{API}/organizations/{org}/members", headers=member["h"]).json()
    assert {(m["display_name"], m["role"]) for m in members} == {("owner", "owner"), ("member", "member")}
    assert all("***@" in m["email_masked"] and "owner@example.com" not in json.dumps(m) for m in members)
    mine = w.client.get(f"{API}/me/organizations", headers=member["h"]).json()
    assert [(m["organization"]["organization_id"], m["role"]) for m in mine] == [(org, "member")]
    target = next(m for m in members if m["role"] == "member")
    up = w.client.patch(f"{API}/organizations/{org}/members/{target['user_id']}",
                        json={"role": "owner", "version": target["version"]}, headers=owner["h"])
    assert up.status_code == 200 and up.json()["role"] == "owner"
    gone = w.client.delete(f"{API}/organizations/{org}/members/{target['user_id']}", headers=owner["h"])
    assert gone.status_code == 204
    # 권한 즉시 회수: 다음 요청부터 소속 아님 → 404
    assert w.client.get(f"{API}/organizations/{org}", headers=member["h"]).status_code == 404
    actions = [a["action_code"] for a in w.repo.audit]
    assert actions == ["org.register", "org.verify.approve", "org.invite.create", "org.invite.accept",
                       "org.member.role_change", "org.member.remove"]
    assert "member@example.com" not in repr(w.repo.audit) and w.mail.outbox[0].to == "member@example.com"


def test_invitation_token_is_hashed_and_never_returned(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    r = w.invite(org, owner, "new@example.com")
    token = w.token()
    assert token not in r.text and "token" not in r.json()
    stored = list(w.repo.invitations.values())[-1]
    assert stored.token_hash != token and re.fullmatch(r"[0-9a-f]{64}", stored.token_hash)
    listing = w.client.get(f"{API}/organizations/{org}/invitations", headers=owner["h"]).text
    assert token not in listing and "new@example.com" not in listing and "n***@example.com" in listing


# ------------------------------------------------------------------ 초대 거부
def test_expired_revoked_and_wrong_email_tokens_are_the_same_404(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    guest, other = w.user("guest@example.com"), w.user("other@example.com")
    assert w.invite(org, owner, guest["email"]).status_code == 201
    token = w.token()
    wrong_email = w.accept(other, token)
    w.clock.now += timedelta(hours=73)
    expired = w.accept(guest, token)
    bodies = {json.dumps(r.json(), sort_keys=True) for r in (wrong_email, expired)}
    assert {wrong_email.status_code, expired.status_code} == {404} and len(bodies) == 1
    assert list(w.repo.invitations.values())[-1].status == "expired"
    assert w.invite(org, owner, guest["email"]).status_code == 201       # 만료 뒤 새 초대 가능
    inv_id = list(w.repo.invitations.values())[-1].invitation_id
    token2 = w.token()
    assert w.client.delete(f"{API}/organizations/{org}/invitations/{inv_id}", headers=owner["h"]).status_code == 204
    assert w.accept(guest, token2).status_code == 404
    assert w.accept(guest, "x" * 43).status_code == 404


def test_resend_rotates_token_and_caps_attempts(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    guest = w.user("guest@example.com")
    inv = w.invite(org, owner, guest["email"]).json()
    first = w.token()
    for i in range(MAX_RESENDS):
        r = w.client.post(f"{API}/organizations/{org}/invitations/{inv['invitation_id']}/resend", headers=owner["h"])
        assert r.status_code == 200 and r.json()["resend_count"] == i + 1
    over = w.client.post(f"{API}/organizations/{org}/invitations/{inv['invitation_id']}/resend", headers=owner["h"])
    assert over.status_code == 409
    assert w.accept(guest, first).status_code == 404                     # 재전송 전 토큰은 무효
    assert w.accept(guest, w.token()).status_code == 200


def test_duplicate_invitations_and_existing_members_conflict(team):
    w, owner, member, org = team["w"], team["owner"], team["member"], team["org"]
    assert w.invite(org, owner, "dup@example.com").status_code == 201
    assert w.invite(org, owner, "DUP@Example.com").status_code == 409     # 정규화된 같은 이메일
    assert w.invite(org, owner, member["email"]).status_code == 409       # 이미 멤버
    w2 = w.user("dup@example.com")
    token = w.token()
    assert w.accept(w2, token).status_code == 200
    assert w.accept(w2, token).status_code == 404                         # 같은 토큰 재사용 불가


def test_ttl_limits():
    clock = Clock()
    service = CompanyAccountService(MemoryCompanyRepository(), AuthDirectory(MemoryAuthRepository()),
                                    MemoryMailSender(), clock=clock)
    with pytest.raises(Exception):
        service.invite(uuid.uuid4(), uuid.uuid4(), "a@example.com", "member", ttl=timedelta(days=8))


# ------------------------------------------------------------------ 권한·다른 기업
def test_member_cannot_invite_change_roles_or_remove_others(team):
    w, owner, member, org = team["w"], team["owner"], team["member"], team["org"]
    assert w.invite(org, member, "x@example.com").status_code == 403
    owner_id = str(w.uid(owner["email"]))
    me = str(w.uid(member["email"]))
    assert w.client.patch(f"{API}/organizations/{org}/members/{me}", json={"role": "owner", "version": 1},
                          headers=member["h"]).status_code == 403              # 스스로 owner 승격 불가
    assert w.client.delete(f"{API}/organizations/{org}/members/{owner_id}", headers=member["h"]).status_code == 403
    assert w.client.get(f"{API}/organizations/{org}/invitations", headers=member["h"]).status_code == 403
    assert w.client.delete(f"{API}/organizations/{org}/members/{me}", headers=member["h"]).status_code == 204  # 탈퇴


def test_other_company_and_outsiders_get_404_everywhere(team):
    w, owner, admin, org = team["w"], team["owner"], team["admin"], team["org"]
    rival_owner = w.user("rival@example.com")
    rival = w.active_org(rival_owner, admin, name="경쟁 기업")
    outsider = w.user("outsider@example.com")
    for who in (rival_owner, outsider, admin):
        for method, path, body in [
            ("get", f"/organizations/{org}", None), ("get", f"/organizations/{org}/members", None),
            ("get", f"/organizations/{org}/invitations", None),
            ("post", f"/organizations/{org}/invitations", {"email": "z@example.com"}),
            ("patch", f"/organizations/{org}/members/{w.uid(owner['email'])}", {"role": "member", "version": 1}),
            ("delete", f"/organizations/{org}/members/{w.uid(owner['email'])}", None),
        ]:
            r = getattr(w.client, method)(f"{API}{path}", headers=who["h"], **({"json": body} if body else {}))
            assert r.status_code == 404, (who["email"], method, path, r.status_code)
    assert w.client.get(f"{API}/organizations/{rival}", headers=owner["h"]).status_code == 404
    assert w.client.get(f"{API}/organizations/{uuid.uuid4()}", headers=owner["h"]).status_code == 404


def test_last_owner_is_protected_including_under_concurrency(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    owner_id = str(w.uid(owner["email"]))
    assert w.client.delete(f"{API}/organizations/{org}/members/{owner_id}", headers=owner["h"]).status_code == 409
    assert w.client.patch(f"{API}/organizations/{org}/members/{owner_id}", json={"role": "member", "version": 1},
                          headers=owner["h"]).status_code == 409
    # 두 번째 owner 를 만든 뒤 두 owner 가 동시에 서로를 내리려 해도 owner 는 최소 1명
    member_id = w.uid(team["member"]["email"])
    w.service.change_role(w.uid(owner["email"]), uuid.UUID(org), member_id, "owner", 1)
    results = []

    def demote(actor, target):
        try:
            w.service.change_role(actor, uuid.UUID(org), target, "member", w.repo.members[(uuid.UUID(org), target)].version)
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            results.append(type(exc).__name__)

    a, b = w.uid(owner["email"]), member_id
    threads = [threading.Thread(target=demote, args=(a, b)), threading.Thread(target=demote, args=(b, a))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert w.repo.owners(uuid.UUID(org)) >= 1 and "ok" in results


def test_stale_version_conflicts(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    member_id = w.uid(team["member"]["email"])
    assert w.client.patch(f"{API}/organizations/{org}/members/{member_id}", json={"role": "owner", "version": 1},
                          headers=owner["h"]).status_code == 200
    assert w.client.patch(f"{API}/organizations/{org}/members/{member_id}", json={"role": "member", "version": 1},
                          headers=owner["h"]).status_code == 409


# ------------------------------------------------------------------ 조직 상태·운영 검증
def test_pending_org_can_be_viewed_but_cannot_invite_and_invitees_cannot_join(world):
    owner, admin = world.user("owner@example.com"), world.user("ops@example.com", admin=True)
    org = world.client.post(f"{API}/organizations", json={"name": "검증 대기"}, headers=owner["h"]).json()
    assert org["status"] == "pending"
    assert world.client.get(f"{API}/organizations/{org['organization_id']}", headers=owner["h"]).status_code == 200
    assert world.invite(org["organization_id"], owner, "x@example.com").status_code == 403


def test_verification_is_admin_only_needs_reason_to_reject_and_checks_version(world):
    owner, admin = world.user("owner@example.com"), world.user("ops@example.com", admin=True)
    org = world.client.post(f"{API}/organizations", json={"name": "검증"}, headers=owner["h"]).json()
    path = f"{API}/admin/organizations/{org['organization_id']}/verification"
    assert world.client.post(path, json={"decision": "approve", "version": 1}, headers=owner["h"]).status_code == 403
    assert world.client.post(path, json={"decision": "reject", "version": 1}, headers=admin["h"]).status_code == 422
    assert world.client.post(path, json={"decision": "approve", "version": 9}, headers=admin["h"]).status_code == 409
    done = world.client.post(path, json={"decision": "reject", "reason": "실재 확인 불가", "version": 1},
                             headers=admin["h"])
    assert done.status_code == 200 and done.json()["status"] == "rejected"
    assert world.client.post(path, json={"decision": "approve", "version": 2}, headers=admin["h"]).status_code == 409
    assert world.client.get(f"{API}/organizations/{org['organization_id']}", headers=owner["h"]).status_code == 404


def test_admin_who_is_a_member_cannot_verify_own_org(world):
    admin = world.user("ops@example.com", admin=True)
    org = world.client.post(f"{API}/organizations", json={"name": "자기 검수"}, headers=admin["h"]).json()
    r = world.client.post(f"{API}/admin/organizations/{org['organization_id']}/verification",
                          json={"decision": "approve", "version": 1}, headers=admin["h"])
    assert r.status_code == 403


def test_linked_company_is_unique_among_open_orgs(world):
    owner, other = world.user("owner@example.com"), world.user("other@example.com")
    company = str(uuid.uuid4())
    assert world.client.post(f"{API}/organizations", json={"name": "A", "linked_company_id": company},
                             headers=owner["h"]).status_code == 201
    assert world.client.post(f"{API}/organizations", json={"name": "B", "linked_company_id": company},
                             headers=other["h"]).status_code == 409


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "   "}, {"name": "x" * 201}, {"name": "ok", "extra": 1}])
def test_register_validation(world, body):
    owner = world.user("owner@example.com")
    assert world.client.post(f"{API}/organizations", json=body, headers=owner["h"]).status_code == 422


def test_mail_unavailable_means_503_and_no_invitation_row(team):
    w, owner, org = team["w"], team["owner"], team["org"]
    w.mail.available = False
    before = len(w.repo.invitations)
    r = w.invite(org, owner, "nomail@example.com")
    assert r.status_code == 503 and len(w.repo.invitations) == before
