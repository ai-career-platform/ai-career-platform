"""T129 공개 포트폴리오 공유 링크 API — 메모리 저장소 + 실제 FastAPI 라우터·인증.

소유권·추측 방지·기간 제한·철회 즉시 중단·캐시 무효화(no-store, 현재 데이터 렌더링)·비공개 노출 0.
"""

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.routers.public_portfolio import VIEW_LIMIT, get_portfolio_service
from app.services import public_portfolio as pp
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

ROOT = Path(__file__).resolve().parents[2]
API = API_V1_PREFIX
POLICY = json.loads((ROOT / "docs/enterprise/t128_public_profile_fields.json").read_text(encoding="utf-8"))
SECRET_BIO = "연락처 010-0000-0000 은 비공개"
EMAIL = "candidate@example.com"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class Profiles:
    """현재 데이터를 돌려준다(공개 화면은 사본이 아니라 이것을 그린다)."""

    def __init__(self):
        self.data: dict[uuid.UUID, pp.ProfileData] = {}

    def load(self, user_id):
        return self.data.get(user_id)


def profile(exp_ids, proj_ids):
    return pp.ProfileData(
        display_name="김후보", headline="백엔드 개발자", bio=SECRET_BIO, location_text="서울 강남구", email=EMAIL,
        experiences=(pp.Experience(exp_ids[0], "A사", "개발자", date(2023, 3, 15), date(2025, 1, 31), "API 개발"),
                     pp.Experience(exp_ids[1], "B사(비공개)", "인턴", date(2022, 1, 1), None, None)),
        projects=(pp.Project(proj_ids[0], "추천 시스템", "협업 필터링", date(2024, 1, 1), None),),
        skills=(("Python", 4), ("SQL", 3)), target_roles=("백엔드 개발자",))


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PUBLIC_PORTFOLIO_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    clock, profiles, repo = Clock(), Profiles(), pp.MemoryPortfolioRepository()
    service = pp.PublicPortfolioService(repo, profiles, clock=clock)
    app.dependency_overrides[get_portfolio_service] = lambda: service
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        yield W(client, auth, profiles, repo, clock, service, app)
    get_settings.cache_clear()


class W:
    def __init__(self, client, auth, profiles, repo, clock, service, app):
        self.client, self.auth, self.profiles, self.repo, self.clock, self.service, self.app = (
            client, auth, profiles, repo, clock, service, app)

    def user(self, email):
        r = self.client.post(f"{API}/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "u",
                                                        "consents": CONSENTS})
        uid = self.auth.find_local_identity(email).user_id
        exp, proj = [uuid.uuid4(), uuid.uuid4()], [uuid.uuid4()]
        self.profiles.data[uid] = profile(exp, proj)
        return {"h": bearer(r.json()["access_token"]), "id": uid, "exp": exp, "proj": proj}

    def select(self, who, fields, exp=(), proj=(), alias=None):
        version = self.client.get(f"{API}/me/public-profile", headers=who["h"]).json()["selection"]["version"]
        return self.client.put(f"{API}/me/public-profile/selection", headers=who["h"], json={
            "fields": fields, "experience_ids": [str(e) for e in exp], "project_ids": [str(p) for p in proj],
            "alias": alias, "version": version})

    def confirm(self, who):
        version = self.client.get(f"{API}/me/public-profile", headers=who["h"]).json()["selection"]["version"]
        return self.client.post(f"{API}/me/public-profile/consent", json={"version": version}, headers=who["h"])

    def share(self, who, ttl_days=30):
        return self.client.post(f"{API}/me/public-profile/links", json={"ttl_days": ttl_days}, headers=who["h"])

    def view(self, url):
        token = url.rsplit("/", 1)[1]
        return self.client.get(f"{API}/public/portfolios/{token}")


@pytest.fixture
def shared(world):
    me = world.user("candidate@example.com")
    assert world.select(me, ["display_name", "headline", "experience.organization", "experience.title",
                             "experience.period", "skills"], exp=[me["exp"][0]]).status_code == 200
    assert world.confirm(me).status_code == 200
    link = world.share(me)
    assert link.status_code == 201
    return {"w": world, "me": me, "link": link.json()}


# ------------------------------------------------------------------ 정책 일치
def test_service_field_sets_match_the_t128_catalog():
    publishable = {f["key"] for f in POLICY["fields"] if f["publishable"]}
    never = {f["key"] for f in POLICY["fields"] if not f["publishable"]}
    assert pp.PUBLISHABLE_FIELDS == publishable and pp.NEVER_PUBLIC == never
    assert pp.MAX_ACTIVE_LINKS == POLICY["links"]["max_active_links"]
    assert pp.MAX_TTL == timedelta(days=POLICY["links"]["max_ttl_days"])
    assert pp.DEFAULT_TTL == timedelta(days=POLICY["links"]["default_ttl_days"])


def test_routes_are_off_by_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("PUBLIC_PORTFOLIO_API", raising=False)
    get_settings.cache_clear()
    assert not [p for p in create_app().openapi()["paths"] if "public" in p or "portfolio" in p]
    get_settings.cache_clear()


# ------------------------------------------------------------------ 비공개 기본·선택
def test_private_by_default_and_sharing_requires_confirmed_preview(world):
    me = world.user("a@example.com")
    assert world.client.get(f"{API}/me/public-profile/preview", headers=me["h"]).json() == {}
    assert world.share(me).status_code == 409                               # 선택·동의 없음
    assert world.select(me, ["headline"]).status_code == 200
    assert world.share(me).status_code == 409                               # 미리보기 확인 전
    assert world.confirm(me).status_code == 200
    assert world.share(me).status_code == 201
    assert world.repo.consents[-1]["policy_code"] == "public_profile" and world.repo.consents[-1]["granted"]


@pytest.mark.parametrize("field", sorted(pp.NEVER_PUBLIC))
def test_never_public_fields_are_rejected(world, field):
    me = world.user("a@example.com")
    assert world.select(me, ["headline", field]).status_code == 422


def test_selecting_someone_elses_items_is_hidden(world):
    me, other = world.user("a@example.com"), world.user("b@example.com")
    assert world.select(me, ["experience.title"], exp=[other["exp"][0]]).status_code == 404


def test_preview_equals_public_view_and_shows_only_selected(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    preview = w.client.get(f"{API}/me/public-profile/preview", headers=me["h"]).json()
    public = w.view(link["url"]).json()
    shared_until = public.pop("shared_until")
    assert public == preview and shared_until.startswith("2026-12-11")
    text = json.dumps(public, ensure_ascii=False)
    for secret in (SECRET_BIO, EMAIL, "B사(비공개)", "서울 강남구", "추천 시스템", "API 개발", "백엔드 개발자\"]"):
        assert secret not in text, secret
    assert public["experiences"] == [{"organization": "A사", "title": "개발자",
                                      "period": {"start": "2023-03", "end": "2025-01"}}]   # 일 단위 없음
    assert public["display_name"] == "김후보"


def test_alias_replaces_real_name(world):
    me = world.user("a@example.com")
    world.select(me, ["display_name"], alias="백엔드 K")
    world.confirm(me)
    url = world.share(me).json()["url"]
    assert world.view(url).json()["display_name"] == "백엔드 K"


# ------------------------------------------------------------------ 링크·추측 방지·헤더
def test_link_token_is_strong_shown_once_and_stored_hashed(shared):
    w, link = shared["w"], shared["link"]
    token = link["url"].rsplit("/", 1)[1]
    assert len(token) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", token)    # 256비트 base64url
    stored = next(iter(w.repo.links.values()))
    assert stored.token_hash != token and re.fullmatch(r"[0-9a-f]{64}", stored.token_hash)
    settings = w.client.get(f"{API}/me/public-profile", headers=shared["me"]["h"]).text
    assert token not in settings


def test_public_response_headers_prevent_caching_indexing_and_referrer_leaks(shared):
    r = shared["w"].view(shared["link"]["url"])
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_unknown_malformed_expired_and_revoked_links_are_the_same_404(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    unknown = w.client.get(f"{API}/public/portfolios/{'A' * 43}")
    short = w.client.get(f"{API}/public/portfolios/abc")
    w.clock.now += timedelta(days=31)
    expired = w.view(link["url"])
    bodies = {json.dumps(r.json(), sort_keys=True) for r in (unknown, short, expired)}
    assert {unknown.status_code, short.status_code, expired.status_code} == {404} and len(bodies) == 1


def test_revocation_takes_effect_on_the_very_next_request(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    assert w.view(link["url"]).status_code == 200
    assert w.client.delete(f"{API}/me/public-profile/links/{link['link_id']}", headers=me["h"]).status_code == 204
    assert w.view(link["url"]).status_code == 404


def test_withdrawing_consent_kills_every_link_and_resets_selection(shared):
    w, me = shared["w"], shared["me"]
    second = w.share(me).json()
    assert w.client.delete(f"{API}/me/public-profile/consent", headers=me["h"]).status_code == 204
    assert w.view(shared["link"]["url"]).status_code == 404 and w.view(second["url"]).status_code == 404
    settings = w.client.get(f"{API}/me/public-profile", headers=me["h"]).json()
    assert settings["selection"]["fields"] == [] and settings["selection"]["consented"] is False
    assert all(link["revoked"] for link in settings["links"])
    assert w.repo.consents[-1]["granted"] is False


def test_changing_selection_requires_reconfirmation_before_links_work_again(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    assert w.select(me, ["headline", "bio"]).status_code == 200
    assert w.view(link["url"]).status_code == 404                           # 새 범위는 아직 미확인
    w.confirm(me)
    body = w.view(link["url"]).json()
    assert set(body) == {"headline", "bio", "shared_until"}


def test_owner_data_changes_and_deletions_show_immediately(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    current = w.profiles.data[me["id"]]
    w.profiles.data[me["id"]] = pp.ProfileData(**{**current.__dict__, "experiences": (), "headline": "새 소개"})
    body = w.view(link["url"]).json()
    assert body["experiences"] == [] and body["headline"] == "새 소개"
    # 새로 추가한 경력은 선택 목록에 없으므로 비공개
    new_exp = pp.Experience(uuid.uuid4(), "C사", "리드", date(2025, 2, 1), None, None)
    w.profiles.data[me["id"]] = pp.ProfileData(**{**current.__dict__, "experiences": (*current.experiences, new_exp)})
    assert "C사" not in w.view(link["url"]).text


def test_account_deletion_cascades_links(shared):
    w, me, link = shared["w"], shared["me"], shared["link"]
    w.repo.delete_user(me["id"])
    del w.profiles.data[me["id"]]
    assert w.view(link["url"]).status_code == 404 and w.repo.links == {}


def test_ttl_bounds_and_active_link_limit(shared):
    w, me = shared["w"], shared["me"]
    assert w.share(me, ttl_days=91).status_code == 422 and w.share(me, ttl_days=0).status_code == 422
    assert w.share(me, ttl_days=90).status_code == 201
    assert w.share(me).status_code == 201
    assert w.share(me).status_code == 409                                   # 3개 초과
    w.clock.now += timedelta(days=31)                                        # 30일 링크 2개 만료
    assert w.share(me).status_code == 201


def test_owners_cannot_touch_each_others_links(shared):
    w, link = shared["w"], shared["link"]
    other = w.user("b@example.com")
    assert w.client.delete(f"{API}/me/public-profile/links/{link['link_id']}", headers=other["h"]).status_code == 404
    assert w.view(link["url"]).status_code == 200
    assert link["link_id"] not in w.client.get(f"{API}/me/public-profile", headers=other["h"]).text


def test_owner_endpoints_require_login_and_public_view_does_not(shared):
    w = shared["w"]
    assert w.client.get(f"{API}/me/public-profile").status_code == 401
    assert w.client.post(f"{API}/me/public-profile/links", json={}).status_code == 401
    assert w.view(shared["link"]["url"]).status_code == 200


def test_view_counter_counts_without_storing_viewer_identity(shared):
    w = shared["w"]
    for _ in range(3):
        w.view(shared["link"]["url"])
    stored = next(iter(w.repo.links.values()))
    assert stored.views == 3 and set(stored.__dict__) == {"link_id", "user_id", "token_hash", "created_at",
                                                          "expires_at", "revoked_at", "views"}


def test_guessing_is_rate_limited_per_client(shared):
    w = shared["w"]
    codes = [w.client.get(f"{API}/public/portfolios/{'B' * 43}").status_code for _ in range(VIEW_LIMIT + 1)]
    assert codes[:VIEW_LIMIT - 1] == [404] * (VIEW_LIMIT - 1) and 429 in codes[VIEW_LIMIT - 1:]
