"""T155: crawler admin write/command API behind CRAWLER_ADMIN_WRITE_API (default off).

Uses the real T15 auth stack (signed tokens + session/role lookup in the memory auth
repository). The crawler DB dependency is replaced by a fake store, or, only when
``T155_CRAWLER_PG_DSN`` is set, by the real ``CrawlerAdminWriteStore`` on an isolated
local crawler database. No Staging, no external HTTP.
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.routers.crawler_admin_write import get_crawler_admin_write_store
from tests.conftest import TEST_SECRET, bearer, signup
from tests.fakes import override_auth_repository

BASE = "/api/v1/admin/crawler"
JOB = "00000000-0000-4000-8000-0000000000aa"
WRITE_CALLS = [
    ("post", "/keywords", {"keyword": "AI", "priority": 5}, {}),
    ("patch", "/keywords/1", {"keyword": "AI", "priority": 5}, {}),
    ("put", "/keywords/1/enabled", {"enabled": False}, {}),
    ("delete", "/keywords/1", None, {}),
    ("get", "/keywords/1/audit", None, {}),
    ("get", "/settings", None, {}),
    ("get", "/commands", None, {}),
    ("patch", "/schedules/jobkorea-daily", {"local_time": "04:00"}, {"Idempotency-Key": "k-1"}),
    ("post", "/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "k-2"}),
    ("post", "/commands/stop", {"job_id": JOB}, {"Idempotency-Key": "k-3"}),
    ("post", "/commands/retry", {"job_id": JOB}, {"Idempotency-Key": "k-4"}),
]


class Conflict(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.crawler_admin_conflict = reason


class Result:
    def __init__(self, command_type, target, outcome="ACCEPTED", reason="OK", result=None, replayed=False):
        self.command_id = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
        self.command_type, self.target, self.outcome, self.reason = command_type, target, outcome, reason
        self.result, self.replayed = result or {}, replayed

    def as_dict(self):
        return {"command_id": str(self.command_id), "command_type": self.command_type, "target": self.target,
                "outcome": self.outcome, "reason": self.reason, "result": self.result, "replayed": self.replayed}


class FakeStore:
    def __init__(self):
        self.calls = []
        self.keywords = {1: {"keyword_id": 1, "keyword": "AI", "enabled": True, "priority": 1}}
        self.seen_keys = {}

    def create_keyword(self, value, *, priority, actor):
        self.calls.append(("create", value, priority, actor))
        if value.strip().casefold() in {k["keyword"].casefold() for k in self.keywords.values()}:
            raise Conflict("KEYWORD_EXISTS")
        if not value.strip():
            raise ValueError("blank")
        kid = max(self.keywords) + 1
        self.keywords[kid] = {"keyword_id": kid, "keyword": value.strip(), "enabled": True, "priority": priority}
        return self.keywords[kid]

    def update_keyword(self, keyword_id, value, *, priority, actor):
        self.calls.append(("update", keyword_id, value, priority, actor))
        if keyword_id not in self.keywords:
            return None
        self.keywords[keyword_id].update(keyword=value, priority=priority)
        return self.keywords[keyword_id]

    def set_keyword_enabled(self, keyword_id, enabled, *, actor):
        self.calls.append(("enabled", keyword_id, enabled, actor))
        if keyword_id not in self.keywords:
            return None
        self.keywords[keyword_id]["enabled"] = enabled
        return self.keywords[keyword_id]

    def delete_keyword(self, keyword_id, *, actor):
        self.calls.append(("delete", keyword_id, actor))
        return self.keywords.pop(keyword_id, None) is not None

    def keyword_audit(self, keyword_id, *, limit):
        self.calls.append(("audit", keyword_id, limit))
        return [{"audit_id": 1, "keyword_id": keyword_id, "actor": "admin:x", "action": "CREATE",
                 "before_state": None, "after_state": {"keyword": "AI"}, "occurred_at": "2026-11-11T00:00:00Z"}]

    def settings(self):
        self.calls.append(("settings",))
        return {"schedules": [{"schedule_id": "jobkorea-daily", "enabled": False, "mode": "fixture",
                               "local_time": "03:00"}],
                "night_window": {"start": "21:00", "end": "08:00", "editable": False},
                "live_collection": "HOLD", "schedule_activation": "REQUIRES_SEPARATE_APPROVAL"}

    def commands(self, *, limit, offset):
        self.calls.append(("commands", limit, offset))
        return []

    def _idem(self, key, signature, make):
        if key in self.seen_keys:
            if self.seen_keys[key][0] != signature:
                raise Conflict("IDEMPOTENCY_KEY_REUSED")
            prior = self.seen_keys[key][1]
            return Result(prior.command_type, prior.target, prior.outcome, prior.reason, prior.result, True)
        result = make()
        self.seen_keys[key] = (signature, result)
        return result

    def run(self, keyword_id, *, mode, idempotency_key, actor):
        self.calls.append(("run", keyword_id, mode, idempotency_key, actor))
        if mode == "live":
            return self._idem(idempotency_key, ("run", keyword_id, mode), lambda: Result(
                "RUN", f"keyword:{keyword_id}", "REFUSED", "LIVE_NOT_APPROVED:NOT_APPROVED"))
        return self._idem(idempotency_key, ("run", keyword_id, mode), lambda: Result(
            "RUN", f"keyword:{keyword_id}", reason="FIXTURE_JOB_PENDING", result={"job_id": JOB}))

    def stop(self, job_id, *, idempotency_key, actor):
        self.calls.append(("stop", str(job_id), idempotency_key, actor))
        return Result("STOP", f"job:{job_id}", "REFUSED", "RUNNING_JOB_STOP_UNSUPPORTED")

    def retry(self, job_id, *, idempotency_key, actor):
        self.calls.append(("retry", str(job_id), idempotency_key, actor))
        return Result("RETRY", f"job:{job_id}", reason="FIXTURE_JOB_PENDING")

    def update_schedule(self, schedule_id, *, changes, idempotency_key, actor):
        self.calls.append(("schedule", schedule_id, changes, idempotency_key, actor))
        if changes.get("enabled") is True:
            return Result("SCHEDULE_UPDATE", schedule_id, "REFUSED", "SCHEDULE_ACTIVATION_REQUIRES_APPROVAL")
        return Result("SCHEDULE_UPDATE", schedule_id, reason="SCHEDULE_TIME_UPDATED")


@pytest.fixture
def write_app(monkeypatch, repo):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CRAWLER_ADMIN_WRITE_API", "true")
    get_settings.cache_clear()
    application = create_app()
    override_auth_repository(application, repo)
    yield application
    get_settings.cache_clear()


@pytest.fixture
def wclient(write_app):
    with TestClient(write_app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as test_client:
        yield test_client


def _admin(client, repo, email="admin-t155w@example.com"):
    from app.core.security import decode_access_token
    token = signup(client, email=email).json()["access_token"]
    user_id = decode_access_token(TEST_SECRET, token).user_id
    repo.grant_role(user_id, "admin")
    return token, user_id


def _call(client, method, path, body, headers, token=None):
    hdrs = dict(headers)
    if token:
        hdrs.update(bearer(token))
    kwargs = {"headers": hdrs}
    if body is not None:
        kwargs["json"] = body
    return client.request(method.upper(), BASE + path, **kwargs)


# ------------------------------------------------------------------ flag off
def test_flag_off_by_default_no_write_routes(client):
    doc = client.get("/openapi.json").json()
    for verb in ("post", "patch", "put", "delete"):
        assert verb not in doc["paths"].get(BASE + "/keywords", {})
    assert BASE + "/commands/run" not in doc["paths"]
    assert BASE + "/settings" not in doc["paths"]
    assert get_settings().crawler_admin_write_api is False


# ------------------------------------------------------------------ authn/authz
def test_anonymous_401_before_store(wclient, write_app):
    def forbidden():
        raise AssertionError("store must not open before authentication")
    write_app.dependency_overrides[get_crawler_admin_write_store] = forbidden
    for method, path, body, headers in WRITE_CALLS:
        resp = _call(wclient, method, path, body, headers)
        assert resp.status_code == 401, (path, resp.text)
        assert resp.json()["code"] == "UNAUTHENTICATED"


def test_forged_or_expired_token_401(wclient, write_app):
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: (_ for _ in ()).throw(AssertionError())
    import jwt
    forged = jwt.encode({"sub": str(uuid.uuid4()), "roles": ["admin"]}, "not-the-secret-" * 4, algorithm="HS256")
    resp = _call(wclient, "post", "/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "k"}, forged)
    assert resp.status_code == 401


def test_nonadmin_403_before_store(wclient, write_app):
    token = signup(wclient, email="user-t155w@example.com").json()["access_token"]

    def forbidden():
        raise AssertionError("store must not open for a non-admin")
    write_app.dependency_overrides[get_crawler_admin_write_store] = forbidden
    for method, path, body, headers in WRITE_CALLS:
        resp = _call(wclient, method, path, body, headers, token)
        assert resp.status_code == 403, (path, resp.text)
        assert resp.json()["code"] == "FORBIDDEN"


def test_role_revocation_rejects_next_write(wclient, write_app, repo):
    token, user_id = _admin(wclient, repo, "revoke-t155w@example.com")
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    assert _call(wclient, "post", "/keywords", {"keyword": "LLM 운영"}, {}, token).status_code == 201
    repo.revoke_role(user_id, "admin")
    assert _call(wclient, "post", "/keywords", {"keyword": "다른"}, {}, token).status_code == 403
    assert len([c for c in store.calls if c[0] == "create"]) == 1


# ------------------------------------------------------------------ keywords
def test_keyword_crud_uses_authenticated_actor(wclient, write_app, repo):
    token, user_id = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    actor = f"admin:{user_id}"
    created = _call(wclient, "post", "/keywords", {"keyword": "데이터 엔지니어", "priority": 7}, {}, token)
    assert created.status_code == 201
    kid = created.json()["keyword_id"]
    assert store.calls[-1] == ("create", "데이터 엔지니어", 7, actor)
    assert _call(wclient, "patch", f"/keywords/{kid}", {"keyword": "DE", "priority": 8}, {}, token).json()["keyword"] == "DE"
    assert _call(wclient, "put", f"/keywords/{kid}/enabled", {"enabled": False}, {}, token).json()["enabled"] is False
    assert _call(wclient, "get", f"/keywords/{kid}/audit?limit=5", None, {}, token).status_code == 200
    assert store.calls[-1] == ("audit", kid, 5)
    assert _call(wclient, "delete", f"/keywords/{kid}", None, {}, token).status_code == 204
    assert _call(wclient, "delete", f"/keywords/{kid}", None, {}, token).status_code == 404
    assert _call(wclient, "patch", "/keywords/999", {"keyword": "x", "priority": 1}, {}, token).status_code == 404
    assert _call(wclient, "put", "/keywords/999/enabled", {"enabled": True}, {}, token).status_code == 404
    assert all(c[-1] == actor for c in store.calls if c[0] in ("create", "update", "enabled", "delete"))


def test_keyword_conflict_and_validation(wclient, write_app, repo):
    token, _ = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    dup = _call(wclient, "post", "/keywords", {"keyword": "ai"}, {}, token)
    assert dup.status_code == 409 and dup.json()["code"] == "CONFLICT"
    assert dup.headers["X-Crawler-Command-Reason"] == "KEYWORD_EXISTS"
    for body in ({"keyword": ""}, {"keyword": "x" * 101}, {"keyword": "x", "priority": 0},
                 {"keyword": "x", "priority": 10000}, {"keyword": "x", "actor": "admin:spoof"}, {}):
        resp = _call(wclient, "post", "/keywords", body, {}, token)
        assert resp.status_code == 422, body
        assert resp.json()["code"] == "VALIDATION_FAILED"
    assert _call(wclient, "post", "/keywords", {"keyword": "   "}, {}, token).status_code == 422
    assert _call(wclient, "patch", "/keywords/0", {"keyword": "x", "priority": 1}, {}, token).status_code == 422
    assert _call(wclient, "put", "/keywords/1/enabled", {"enabled": "yes"}, {}, token).status_code == 422


# ------------------------------------------------------------------ commands
def test_run_idempotency_replay_and_key_reuse(wclient, write_app, repo):
    token, _ = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    first = _call(wclient, "post", "/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "run-1"}, token)
    assert first.status_code == 201
    assert first.json()["result"]["job_id"] == JOB and first.json()["replayed"] is False
    assert first.headers["X-Crawler-Command-Reason"] == "FIXTURE_JOB_PENDING"
    replay = _call(wclient, "post", "/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "run-1"}, token)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    reuse = _call(wclient, "post", "/commands/run", {"keyword_id": 1, "mode": "live"},
                  {"Idempotency-Key": "run-1"}, token)
    assert reuse.status_code == 409
    assert reuse.headers["X-Crawler-Command-Reason"] == "IDEMPOTENCY_KEY_REUSED"


def test_live_run_and_schedule_activation_refused_409(wclient, write_app, repo):
    token, _ = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    live = _call(wclient, "post", "/commands/run", {"keyword_id": 1, "mode": "live"},
                 {"Idempotency-Key": "live-1"}, token)
    assert live.status_code == 409 and live.json()["code"] == "CONFLICT"
    assert live.headers["X-Crawler-Command-Reason"] == "LIVE_NOT_APPROVED:NOT_APPROVED"
    assert live.headers["X-Crawler-Command-Id"]
    enable = _call(wclient, "patch", "/schedules/jobkorea-daily", {"enabled": True},
                   {"Idempotency-Key": "sch-1"}, token)
    assert enable.status_code == 409
    assert enable.headers["X-Crawler-Command-Reason"] == "SCHEDULE_ACTIVATION_REQUIRES_APPROVAL"
    ok = _call(wclient, "patch", "/schedules/jobkorea-daily", {"local_time": "04:30"},
               {"Idempotency-Key": "sch-2"}, token)
    assert ok.status_code == 200 and ok.json()["reason"] == "SCHEDULE_TIME_UPDATED"
    stop = _call(wclient, "post", "/commands/stop", {"job_id": JOB}, {"Idempotency-Key": "stop-1"}, token)
    assert stop.status_code == 409
    retry = _call(wclient, "post", "/commands/retry", {"job_id": JOB}, {"Idempotency-Key": "retry-1"}, token)
    assert retry.status_code == 201


def test_command_validation_422(wclient, write_app, repo):
    token, _ = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    cases = [
        ("/commands/run", {"keyword_id": 1}, {}),  # missing Idempotency-Key
        ("/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "has space"}),
        ("/commands/run", {"keyword_id": 1}, {"Idempotency-Key": "x" * 201}),
        ("/commands/run", {"keyword_id": 0}, {"Idempotency-Key": "k"}),
        ("/commands/run", {"keyword_id": 1, "mode": "proxy"}, {"Idempotency-Key": "k"}),
        ("/commands/run", {"keyword_id": 1, "target_urls": ["https://example.com"]}, {"Idempotency-Key": "k"}),
        ("/commands/stop", {"job_id": "not-a-uuid"}, {"Idempotency-Key": "k"}),
    ]
    for path, body, headers in cases:
        resp = _call(wclient, "post", path, body, headers, token)
        assert resp.status_code == 422, (path, body, headers, resp.text)
    for body in ({}, {"local_time": "24:00"}, {"approval": {}}, {"mode": "proxy"}):
        resp = _call(wclient, "patch", "/schedules/jobkorea-daily", body, {"Idempotency-Key": "s"}, token)
        assert resp.status_code == 422, body
    assert _call(wclient, "patch", "/schedules/Bad_ID", {"local_time": "01:00"},
                 {"Idempotency-Key": "s"}, token).status_code == 422
    assert not [c for c in store.calls if c[0] in ("run", "stop", "schedule")]


def test_settings_and_responses_hide_raw_and_secrets(wclient, write_app, repo):
    token, _ = _admin(wclient, repo)
    store = FakeStore()
    write_app.dependency_overrides[get_crawler_admin_write_store] = lambda: store
    settings = _call(wclient, "get", "/settings", None, {}, token)
    assert settings.status_code == 200
    assert settings.json()["live_collection"] == "HOLD"
    for text in (settings.text, _call(wclient, "get", "/commands", None, {}, token).text):
        for forbidden in ("raw_html", "storage_key", "target_urls", "approval\"", "password"):
            assert forbidden not in text


def test_fail_closed_503_without_crawler_database(wclient, write_app, repo, monkeypatch):
    token, _ = _admin(wclient, repo)
    monkeypatch.setenv("CRAWLER_DB_MODE", "local")
    monkeypatch.delenv("CRAWLER_LOCAL_DATABASE_URL", raising=False)
    resp = _call(wclient, "post", "/keywords", {"keyword": "x"}, {}, token)
    assert resp.status_code == 503 and resp.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "postgres" not in resp.text.lower()


def test_openapi_lists_write_routes_with_security(wclient):
    doc = wclient.get("/openapi.json").json()
    assert doc["paths"][BASE + "/keywords"]["post"]["security"]
    assert doc["paths"][BASE + "/commands/run"]["post"]["security"]
    assert doc["paths"][BASE + "/keywords"]["get"]["security"]  # merged read route still present


# ------------------------------------------------------------------ real crawler DB (opt-in, local only)
@pytest.mark.skipif(not os.environ.get("T155_CRAWLER_PG_DSN"), reason="needs isolated local crawler DB")
def test_real_store_through_http(wclient, write_app, repo):
    repo_root = str(Path(__file__).resolve().parents[2])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import psycopg
    from crawler.admin.commands import CrawlerAdminWriteStore

    conn = psycopg.connect(os.environ["T155_CRAWLER_PG_DSN"], autocommit=True)

    def real_store():
        yield CrawlerAdminWriteStore(conn)
    write_app.dependency_overrides[get_crawler_admin_write_store] = real_store
    token, user_id = _admin(wclient, repo, "real-t155w@example.com")
    tag = uuid.uuid4().hex[:8]
    try:
        created = _call(wclient, "post", "/keywords", {"keyword": f"T155 http {tag}", "priority": 77}, {}, token)
        assert created.status_code == 201, created.text
        kid = created.json()["keyword_id"]
        assert _call(wclient, "post", "/keywords", {"keyword": f"t155 HTTP {tag}"}, {}, token).status_code == 409
        run = _call(wclient, "post", "/commands/run", {"keyword_id": kid}, {"Idempotency-Key": f"h-{tag}"}, token)
        assert run.status_code == 201, run.text
        job_id = run.json()["result"]["job_id"]
        assert _call(wclient, "post", "/commands/run", {"keyword_id": kid},
                     {"Idempotency-Key": f"h-{tag}"}, token).json()["replayed"] is True
        live = _call(wclient, "post", "/commands/run", {"keyword_id": kid, "mode": "live"},
                     {"Idempotency-Key": f"l-{tag}"}, token)
        assert live.status_code == 409
        assert live.headers["X-Crawler-Command-Reason"] == "LIVE_NOT_APPROVED:NOT_APPROVED"
        assert _call(wclient, "post", "/commands/stop", {"job_id": job_id},
                     {"Idempotency-Key": f"s-{tag}"}, token).status_code == 200
        audit = _call(wclient, "get", f"/keywords/{kid}/audit", None, {}, token).json()
        assert audit[0]["actor"] == f"admin:{user_id}" and audit[0]["action"] == "CREATE"
        status = conn.execute("SELECT status FROM crawler_training.keyword_jobs WHERE job_id=%s",
                              (job_id,)).fetchone()[0]
        assert status == "CANCELLED"
        jobs = _call(wclient, "get", f"/jobs?keyword_id={kid}", None, {}, token)
        # read route uses its own read-only dependency (not overridden): fails closed without env DSN
        assert jobs.status_code in (200, 503)
    finally:
        conn.close()
