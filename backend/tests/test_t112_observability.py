"""T112 관측 계약 시험 — request_id 연결, Query String·토큰·이메일 비노출, 오류·지연 지표."""

import logging
import pathlib
import re
import uuid

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.core.observability import (
    ACCESS_LOGGER, RequestMetrics, StripQueryFilter, install_uvicorn_access_filter, safe_path,
)
from app.main import create_app
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET
from tests.fakes import MemoryAuthRepository, override_auth_repository

REPO = pathlib.Path(__file__).resolve().parents[2]
SECRET_Q = "t112-query-secret-value"
EMAIL = "observe.me@example.com"
LINE = re.compile(r"http_request request_id=(\S+) method=(\S+) path=(\S+) status=(\d+) duration_ms=([\d.]+)")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    application = create_app()
    probe = APIRouter(prefix="/_probe")

    @probe.get("/boom")
    def boom() -> dict:
        raise RuntimeError("t112 simulated failure")

    application.include_router(probe, prefix=API_V1_PREFIX)
    override_auth_repository(application, MemoryAuthRepository())
    yield application
    get_settings.cache_clear()


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                    raise_server_exceptions=False) as test_client:
        yield test_client


def access_lines(caplog):
    return [LINE.search(r.getMessage()).groups() for r in caplog.records
            if r.name == ACCESS_LOGGER and LINE.search(r.getMessage())]


# ------------------------------------------------------------------ request_id 연결
def test_access_log_carries_the_same_request_id_as_the_response(client, caplog):
    caplog.set_level(logging.INFO, logger=ACCESS_LOGGER)
    response = client.get("/health")
    (rid, method, path, status, _), = access_lines(caplog)
    assert rid == response.headers["X-Request-ID"] and rid.startswith("req-")
    assert (method, path, status) == ("GET", "/health", "200")


def test_safe_incoming_request_id_is_propagated_and_unsafe_is_replaced(client, caplog):
    caplog.set_level(logging.INFO, logger=ACCESS_LOGGER)
    client.get("/health", headers={"X-Request-ID": "edge-abc12345"})
    client.get("/health", headers={"X-Request-ID": "bad id\r\nInjected: 1"})
    first, second = access_lines(caplog)
    assert first[0] == "edge-abc12345"
    assert second[0].startswith("req-") and "Injected" not in caplog.text


def test_error_header_and_logs_share_request_id_on_5xx(client, caplog):
    caplog.set_level(logging.INFO)
    response = client.get(f"{API_V1_PREFIX}/_probe/boom")
    assert response.status_code == 500
    rid = response.headers["X-Request-ID"]
    (log_rid, _, _, status, _), = access_lines(caplog)
    assert (log_rid, status) == (rid, "500")
    # 원인은 서버 로그(app.errors)에만, 같은 request_id 로
    assert any(r.name == "app.errors" and rid in r.getMessage() for r in caplog.records)
    assert "simulated failure" not in response.text


# ------------------------------------------------------------------ 비노출
def test_query_string_body_and_auth_header_never_reach_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    bearer = "eyJ" + "x" * 60
    client.get(f"{API_V1_PREFIX}/job-postings?q={SECRET_Q}&email={EMAIL}&token=abcdef",
               headers={"Authorization": f"Bearer {bearer}"})
    client.post(f"{API_V1_PREFIX}/auth/signup", json={
        "email": EMAIL, "password": PASSWORD, "display_name": "관측", "consents": CONSENTS})
    client.post(f"{API_V1_PREFIX}/auth/login", json={"email": EMAIL, "password": "wrong-password-1"})
    # 서버 로거만 본다(httpx 는 시험 클라이언트 자체의 로그)
    text = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    for needle in (SECRET_Q, EMAIL, PASSWORD, "wrong-password-1", bearer, "token=", "?"):
        assert needle not in text, needle
    paths = [line[2] for line in access_lines(caplog)]
    assert f"{API_V1_PREFIX}/job-postings" in paths and f"{API_V1_PREFIX}/auth/login" in paths


@pytest.mark.parametrize(("raw", "expected"), [
    ("/api/v1/job-postings?q=abc", "/api/v1/job-postings"),
    ("/api/v1/users/a.b@example.com/profile", "/api/v1/users/:email/profile"),
    ("/password-reset/" + "A" * 43, "/password-reset/:token"),
    ("/api/v1/me/documents/" + "3f2b8c1e-0000-4000-8000-000000000001", None),
    ("/health", "/health"),
])
def test_safe_path_masks_identifiers_but_keeps_uuids(raw, expected):
    assert safe_path(raw) == (raw if expected is None else expected)


def test_uvicorn_access_log_filter_strips_query_strings():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("10.0.0.1:5555", "GET", f"/password-reset?token={SECRET_Q}", "1.1", 200), None)
    assert StripQueryFilter().filter(record) is True
    assert SECRET_Q not in record.getMessage() and "/password-reset" in record.getMessage()
    install_uvicorn_access_filter()
    install_uvicorn_access_filter()
    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, StripQueryFilter)]
    assert len(filters) == 1


def test_access_logger_is_silent_without_explicit_log_config():
    """기본 상태에서 app.access(INFO)는 출력되지 않는다 — 운영에서 켜는 것은 승인 후 로그 설정으로."""
    logger = logging.getLogger(ACCESS_LOGGER)
    # 앱은 이 로거에 핸들러·레벨을 붙이지 않는다. Python 기본(root WARNING)과 uvicorn 기본 로그 설정에서는
    # INFO 가 출력되지 않으므로, 켜려면 운영 로그 설정에 app.access 를 명시해야 한다.
    assert logger.level == logging.NOTSET and not logger.handlers and logger.propagate


# ------------------------------------------------------------------ 지표
def test_metrics_count_status_classes_error_rate_and_latency(app, client):
    client.get("/health")
    client.get(f"{API_V1_PREFIX}/_probe/boom")
    client.get(f"{API_V1_PREFIX}/me/sessions")     # 401
    snap = app.state.request_metrics.snapshot()
    assert snap["requests_total"] == 3
    assert snap["by_status_class"] == {"2xx": 1, "4xx": 1, "5xx": 1}
    assert snap["error_rate_5xx"] == pytest.approx(1 / 3)
    assert sum(snap["latency_buckets_ms"].values()) == 3


def test_metrics_bucket_boundaries():
    metrics = RequestMetrics()
    for duration in (50, 50.1, 5000, 5001):
        metrics.observe("GET", 200, duration)
    buckets = metrics.snapshot()["latency_buckets_ms"]
    assert (buckets["50"], buckets["100"], buckets["5000"], buckets["inf"]) == (1, 1, 1, 1)
    assert RequestMetrics().snapshot()["error_rate_5xx"] == 0.0


def test_metrics_are_per_app_and_hold_no_identifiers(app, client):
    client.get(f"{API_V1_PREFIX}/job-postings?q={SECRET_Q}")
    assert SECRET_Q not in repr(app.state.request_metrics.snapshot())
    assert str(uuid.uuid4())[:8] not in repr(app.state.request_metrics.snapshot())


# ------------------------------------------------------------------ Reverse Proxy 제안 설정
def test_proposed_nginx_log_format_excludes_query_and_referer():
    conf = (REPO / "docs" / "ops" / "observability" / "nginx_observability.proposed.conf").read_text(encoding="utf-8")
    log_format = conf.split("log_format", 1)[1].split(";", 1)[0]
    for forbidden in ("$request ", "$request_uri", "$args", "$query_string", "$http_referer",
                      "$http_authorization", "$http_cookie"):
        assert forbidden not in log_format + " ", forbidden
    for required in ("$request_id", "$uri", "$status", "$request_time", "$upstream_response_time"):
        assert required in log_format
    assert "proxy_set_header X-Request-ID $request_id" in conf


def test_dashboard_template_uses_only_logged_fields():
    import json
    template = json.loads((REPO / "docs" / "ops" / "observability" / "dashboard_template.json")
                          .read_text(encoding="utf-8"))
    allowed = {"request_id", "method", "path", "status", "duration_ms"}
    for panel in template["panels"]:
        assert set(panel["fields"]) <= allowed, panel["id"]
