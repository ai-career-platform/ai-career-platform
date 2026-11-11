"""T142 내 데이터 반출 요청 API — 메모리 저장소 + 실제 FastAPI 라우터·인증(T15 MemoryAuthRepository).

재인증·소유권(타인 404)·1회용 다운로드·만료·민감 필드 제외·대용량 한도·중복/동시 409·상태 전이·감사·T31 재사용.
합성 데이터만 쓴다.
"""

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.security import verify_password
from app.main import create_app
from app.routers.personal_data_requests import REAUTH_LIMIT, get_data_request_service
from app.services import personal_data_requests as pd
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer
from tests.fakes import MemoryAuthRepository, override_auth_repository

ROOT = Path(__file__).resolve().parents[2]
API = API_V1_PREFIX + "/me/data-requests"
POLICY = json.loads((ROOT / "docs/privacy/t141_data_subject_requests.json").read_text(encoding="utf-8"))
SYNTH_EMAIL = "synthetic-user@example.com"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


class Source:
    """합성 사용자 데이터. 금지 필드를 일부러 섞어 넣어 묶음에서 빠지는지 본다."""

    def __init__(self):
        self.data: dict[uuid.UUID, dict] = {}
        self.fail = False

    def load(self, user_id):
        if self.fail:
            raise ConnectionError("synthetic outage")
        return self.data.get(user_id)


def synthetic(email):
    return {
        "account": {"email": email, "display_name": "합성 사용자", "password_hash": "$argon2id$synthetic"},
        "credentials": [{"provider": "local", "refresh_token_hash": "a" * 64}],
        "career": {"experiences": [{"organization": "합성 회사", "title": "개발자"}],
                   "skills": [{"name": "Python", "proficiency": 4}]},
        "documents": [{"original_filename": "resume.pdf", "storage_key": "f" * 32, "size_bytes": 1024}],
        "audit": [{"action_code": "auth.login.success", "client_ip_hash": "b" * 64, "row_hash": "c" * 64}],
        "nested": {"deeper": [{"token_hash": "d" * 64, "keep": 1}]},
    }


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("PERSONAL_DATA_REQUESTS_API", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth = MemoryAuthRepository()
    override_auth_repository(app, auth)
    clock, source, repo = Clock(), Source(), pd.MemoryRequestRepository()
    emails: dict[uuid.UUID, str] = {}
    deletions: dict[uuid.UUID, pd.DeletionStatus] = {}

    def verifier(user_id, password):
        ident = auth.find_local_identity(emails[user_id])
        return ident is not None and verify_password(ident.password_hash, password)

    service = pd.PersonalDataRequestService(repo, source, verifier, deletions.get, clock=clock)
    app.dependency_overrides[get_data_request_service] = lambda: service
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        yield W(client, auth, source, repo, clock, service, emails, deletions)
    get_settings.cache_clear()


class W:
    def __init__(self, client, auth, source, repo, clock, service, emails, deletions):
        self.client, self.auth, self.source, self.repo, self.clock = client, auth, source, repo, clock
        self.service, self.emails, self.deletions = service, emails, deletions

    def user(self, email):
        r = self.client.post(f"{API_V1_PREFIX}/auth/signup", json={
            "email": email, "password": PASSWORD, "display_name": "u", "consents": CONSENTS})
        assert r.status_code == 201, r.text
        uid = self.auth.find_local_identity(email).user_id
        self.emails[uid] = email
        self.source.data[uid] = synthetic(email)
        return {"h": bearer(r.json()["access_token"]), "id": uid, "email": email}

    def login(self, who):
        r = self.client.post(f"{API_V1_PREFIX}/auth/login", json={"email": who["email"], "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {**who, "h": bearer(r.json()["access_token"])}

    def reauth(self, who, password=PASSWORD):
        return self.client.post(f"{API}/reauth", json={"password": password}, headers=who["h"])

    def with_reauth(self, who):
        r = self.reauth(who)
        assert r.status_code == 200, r.text
        return {**who["h"], "X-Reauth-Token": r.json()["reauth_token"]}

    def export(self, who):
        return self.client.post(f"{API}/exports", headers=self.with_reauth(who))

    def link(self, who, request_id):
        return self.client.post(f"{API}/exports/{request_id}/download-link", headers=self.with_reauth(who))

    def download(self, who, token):
        return self.client.post(f"{API}/download", json={"token": token}, headers=who["h"])


def ready(world, who):
    """요청 → 처리 → 다운로드 링크까지."""
    req = world.export(who)
    assert req.status_code == 202, req.text
    world.service.process_next()
    link = world.link(who, req.json()["request_id"])
    assert link.status_code == 201, link.text
    return req.json()["request_id"], link.json()["token"]


# ------------------------------------------------------------------ 정책 일치·기본 꺼짐
def test_service_constants_match_t141_policy():
    limits = POLICY["limits"]
    assert pd.MAX_ATTEMPTS == limits["max_attempts"]
    assert pd.ARTIFACT_TTL == timedelta(hours=limits["export_download_ttl_hours"])
    assert pd.MAX_EXPORT_BYTES == limits["export_max_bytes"]
    assert pd.REQUESTS_PER_30_DAYS == limits["requests_per_type_per_30_days"]
    assert pd.REAUTH_TTL == timedelta(minutes=POLICY["identity_verification"]["self_service"]["reauth_max_age_minutes"])
    assert pd.NEVER_EXPORT == set(POLICY["never_export_columns"])
    assert set(pd.TERMINAL_STATES) == {s for s, m in POLICY["states"].items() if m["terminal"]}
    policy_pairs = {(t["from"], t["to"]) for t in POLICY["transitions"]}
    assert set(pd.TRANSITIONS) <= policy_pairs
    for (a, b), action in pd.TRANSITIONS.items():
        (t,) = [t for t in POLICY["transitions"] if (t["from"], t["to"]) == (a, b)]
        assert t["audit"] == action


def test_routes_are_off_by_default_and_503_without_storage(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("PERSONAL_DATA_REQUESTS_API", raising=False)
    get_settings.cache_clear()
    assert not [p for p in create_app().openapi()["paths"] if "data-requests" in p]
    monkeypatch.setenv("PERSONAL_DATA_REQUESTS_API", "true")
    get_settings.cache_clear()
    app = create_app()
    override_auth_repository(app, MemoryAuthRepository())
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        r = client.post(f"{API_V1_PREFIX}/auth/signup", json={
            "email": "x@example.com", "password": PASSWORD, "display_name": "u", "consents": CONSENTS})
        assert client.get(API, headers=bearer(r.json()["access_token"])).status_code == 503
    get_settings.cache_clear()


def test_anonymous_requests_are_401(world):
    for method, path in (("get", API), ("post", f"{API}/exports"), ("post", f"{API}/reauth"),
                         ("get", f"{API}/exports/{uuid.uuid4()}"), ("post", f"{API}/download")):
        assert getattr(world.client, method)(path).status_code == 401, path


# ------------------------------------------------------------------ 재인증
def test_export_requires_recent_reauth(world):
    me = world.user("a@example.com")
    r = world.client.post(f"{API}/exports", headers=me["h"])
    assert r.status_code == 403 and r.headers["X-Reauth-Required"] == "true"
    assert r.json()["code"] == "FORBIDDEN"
    bad = {**me["h"], "X-Reauth-Token": "x" * 43}
    assert world.client.post(f"{API}/exports", headers=bad).status_code == 403
    assert world.reauth(me, "wrong-password-0").status_code == 401
    assert world.export(me).status_code == 202


def test_reauth_expires_after_ten_minutes(world):
    me = world.user("a@example.com")
    headers = world.with_reauth(me)
    world.clock.now += timedelta(minutes=10)
    assert world.client.post(f"{API}/exports", headers=headers).status_code == 403


def test_reauth_token_is_bound_to_session_and_user(world):
    me = world.user("a@example.com")
    other_session = world.login(me)
    headers = world.with_reauth(me)
    moved = {**other_session["h"], "X-Reauth-Token": headers["X-Reauth-Token"]}
    assert world.client.post(f"{API}/exports", headers=moved).status_code == 403
    them = world.user("b@example.com")
    stolen = {**them["h"], "X-Reauth-Token": headers["X-Reauth-Token"]}
    assert world.client.post(f"{API}/exports", headers=stolen).status_code == 403


def test_reauth_attempts_are_rate_limited(world):
    me = world.user("a@example.com")
    codes = [world.reauth(me, "wrong-password-0").status_code for _ in range(REAUTH_LIMIT + 1)]
    # 창 안에서 REAUTH_LIMIT번째 시도부터 잠긴다(T15 login limiter와 같은 의미).
    assert codes[:REAUTH_LIMIT - 1] == [401] * (REAUTH_LIMIT - 1) and set(codes[REAUTH_LIMIT - 1:]) == {429}
    assert world.reauth(me).status_code == 429                          # 맞는 비밀번호도 잠금 동안 거부


def test_reauth_and_tokens_are_stored_hashed_only(world):
    me = world.user("a@example.com")
    headers = world.with_reauth(me)
    _, token = ready(world, me)
    assert headers["X-Reauth-Token"] not in world.repo.reauth
    assert token not in world.repo.downloads
    assert all(len(h) == 64 for h in [*world.repo.reauth, *world.repo.downloads])


# ------------------------------------------------------------------ 상태·소유권
def test_export_lifecycle_and_single_use_download(world):
    me = world.user("a@example.com")
    req = world.export(me)
    assert req.headers["Cache-Control"] == "no-store"
    rid = req.json()["request_id"]
    assert req.json()["status"] == "received"
    assert world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()["status"] == "received"
    assert world.link(me, rid).status_code == 409                       # 아직 완료 전
    world.service.process_next()
    body = world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()
    assert body["status"] == "completed" and body["expires_at"] and body["size_bytes"] > 0
    token = world.link(me, rid).json()["token"]
    first = world.download(me, token)
    assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
    assert "attachment" in first.headers["Content-Disposition"]
    assert first.json()["data"]["career"]["skills"][0]["name"] == "Python"
    assert world.download(me, token).status_code == 404                 # 1회용
    assert world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()["status"] == "expired"
    assert rid not in {str(k) for k in world.repo.artifacts}             # 묶음 삭제


def test_other_users_cannot_see_or_download(world):
    me, them = world.user("a@example.com"), world.user("b@example.com")
    rid, token = ready(world, me)
    assert world.client.get(f"{API}/exports/{rid}", headers=them["h"]).status_code == 404
    assert world.client.post(f"{API}/exports/{rid}/cancel", headers=them["h"]).status_code == 404
    assert world.link(them, rid).status_code == 404
    assert world.download(them, token).status_code == 404
    assert world.client.get(API, headers=them["h"]).json()["items"] == []
    # 타인 시도로 토큰이 소모되었으므로 본인도 새 링크를 받아야 한다(토큰 유출 시 피해 최소화).
    assert world.download(me, token).status_code == 404
    new = world.link(me, rid).json()["token"]
    assert world.download(me, new).status_code == 200


def test_download_link_expires_and_artifact_expires_after_24h(world):
    me = world.user("a@example.com")
    rid, token = ready(world, me)
    world.clock.now += timedelta(minutes=11)
    assert world.download(me, token).status_code == 404
    world.clock.now += timedelta(hours=24)
    assert world.link(me, rid).status_code == 409
    assert world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()["status"] == "expired"
    assert world.repo.artifacts == {}


def test_new_link_invalidates_previous_link(world):
    me = world.user("a@example.com")
    rid, old = ready(world, me)
    new = world.link(me, rid).json()["token"]
    assert world.download(me, old).status_code == 404
    assert world.download(me, new).status_code == 200


def test_malformed_and_unknown_tokens(world):
    me = world.user("a@example.com")
    assert world.download(me, "short").status_code == 422
    assert world.download(me, "z" * 43).status_code == 404
    assert world.client.get(f"{API}/exports/not-a-uuid", headers=me["h"]).status_code == 422


# ------------------------------------------------------------------ 민감 필드·대용량
def test_bundle_never_contains_secret_columns_at_any_depth(world):
    me = world.user("a@example.com")
    _, token = ready(world, me)
    raw = world.download(me, token).text
    for key in pd.NEVER_EXPORT:
        assert f'"{key}"' not in raw, key
    for value in ("$argon2id$synthetic", "a" * 64, "f" * 32, "b" * 64, "c" * 64, "d" * 64):
        assert value not in raw
    assert '"keep": 1' in raw


def test_large_bundle_streams_in_chunks(world):
    me = world.user("a@example.com")
    world.source.data[me["id"]]["career"]["notes"] = ["합성 메모 " * 50] * 2000       # 약 1.4 MB
    _, token = ready(world, me)
    r = world.download(me, token)
    assert r.status_code == 200 and int(r.headers["Content-Length"]) == len(r.content) > 1_000_000


def test_oversized_bundle_fails_without_retry(world):
    me = world.user("a@example.com")
    world.service.max_export_bytes = 100
    rid = world.export(me).json()["request_id"]
    world.service.process_next()
    body = world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()
    assert body["status"] == "failed" and body["reason_code"] == "export_too_large"
    assert world.service.retry_failed() == 0
    assert world.repo.artifacts == {}


# ------------------------------------------------------------------ 중복·동시·재시도·취소
def test_duplicate_open_request_is_409(world):
    me = world.user("a@example.com")
    assert world.export(me).status_code == 202
    r = world.export(me)
    assert r.status_code == 409 and r.json()["code"] == "CONFLICT"


def test_concurrent_requests_create_exactly_one(world):
    me = world.user("a@example.com")
    results, barrier = [], threading.Barrier(8)

    def go():
        barrier.wait()
        try:
            results.append(world.service.create_export(me["id"]).request_id)
        except Exception as exc:  # noqa: BLE001
            results.append(getattr(exc, "code", exc))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(isinstance(r, uuid.UUID) for r in results) == 1
    assert results.count("CONFLICT") == 7


def test_concurrent_workers_claim_each_request_once(world):
    users = [world.user(f"u{i}@example.com") for i in range(5)]
    for u in users:
        world.service.create_export(u["id"])
    claimed, barrier = [], threading.Barrier(10)

    def worker():
        barrier.wait()
        while (r := world.service.process_next()) is not None:
            claimed.append(r.request_id)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == len(set(claimed)) == 5
    starts = [a for a in world.repo.audit if a["action_code"] == "privacy.dsr.start"]
    assert len(starts) == 5


def test_thirty_day_request_limit(world):
    me = world.user("a@example.com")
    headers = world.with_reauth(me)
    for _ in range(3):
        rid = world.client.post(f"{API}/exports", headers=headers).json()["request_id"]
        world.client.post(f"{API}/exports/{rid}/cancel", headers=me["h"])
    assert world.client.post(f"{API}/exports", headers=headers).status_code == 429
    world.clock.now += timedelta(days=31)
    assert world.export(me).status_code == 202


def test_failure_retry_is_bounded(world):
    me = world.user("a@example.com")
    rid = world.export(me).json()["request_id"]
    world.source.fail = True
    for attempt in range(1, 4):
        world.service.process_next()
        body = world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()
        assert body["status"] == "failed" and body["attempts"] == attempt
        assert body["reason_code"] == "dependency_unavailable"
        world.service.retry_failed()
    assert world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()["status"] == "failed"
    assert world.export(me).status_code == 409                          # 실패도 열린 요청(담당자 처리)


def test_retry_then_success(world):
    me = world.user("a@example.com")
    rid = world.export(me).json()["request_id"]
    world.source.fail = True
    world.service.process_next()
    world.source.fail = False
    assert world.service.retry_failed() == 1
    world.service.process_next()
    assert world.client.get(f"{API}/exports/{rid}", headers=me["h"]).json()["status"] == "completed"


def test_cancel_only_before_processing(world):
    me = world.user("a@example.com")
    rid = world.export(me).json()["request_id"]
    assert world.client.post(f"{API}/exports/{rid}/cancel", headers=me["h"]).json()["status"] == "cancelled"
    assert world.client.post(f"{API}/exports/{rid}/cancel", headers=me["h"]).status_code == 409
    rid2 = world.export(me).json()["request_id"]
    world.service.process_next()
    assert world.client.post(f"{API}/exports/{rid2}/cancel", headers=me["h"]).status_code == 409


# ------------------------------------------------------------------ 목록·T31·감사
def test_list_includes_t31_deletion_status_in_t141_terms(world):
    me = world.user("a@example.com")
    world.export(me)
    world.deletions[me["id"]] = pd.DeletionStatus(uuid.uuid4(), "requested", world.clock.now - timedelta(days=1), None)
    items = world.client.get(API, headers=me["h"]).json()["items"]
    assert [(i["request_type"], i["status"], i["source"]) for i in items] == [
        ("export", "received", "T142"), ("erasure", "received", "T31")]
    assert set(pd.DELETION_STATE.values()) <= set(POLICY["states"])


def test_audit_trail_has_no_personal_data(world):
    me = world.user("a@example.com")
    world.reauth(me, "wrong-password-0")
    _, token = ready(world, me)
    world.download(me, token)
    actions = [a["action_code"] for a in world.repo.audit]
    for expected in ("privacy.dsr.reauth", "privacy.export.request", "privacy.dsr.start", "privacy.dsr.complete",
                     "privacy.dsr.download", "privacy.dsr.expire"):
        assert expected in actions, expected
    dump = json.dumps([a["metadata"] for a in world.repo.audit], ensure_ascii=False)
    assert me["email"] not in dump and token not in dump and "Python" not in dump
    assert {k for a in world.repo.audit for k in a["metadata"]} <= pd.AUDIT_KEYS
    denied = [a for a in world.repo.audit if a["metadata"].get("result") == "denied"]
    assert denied and denied[0]["metadata"]["reason_code"] == "invalid_credentials"
