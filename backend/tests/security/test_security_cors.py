"""T86 CORS — Origin 허용 여부는 인증·인가를 대신하지 않습니다 (실패 시나리오 9).

현재 구조: 브라우저는 같은 Origin 의 Nginx(/api) 만 호출하고, 앱에는 CORS 미들웨어가 없습니다(csrf.py 주석).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.main import create_app
from tests.conftest import bearer, signup
from tests.fakes import MemoryAuthRepository, override_auth_repository

EVIL = "https://evil.example"
NGINX = Path(__file__).resolve().parents[3] / "poc/staging/frontend/nginx.conf"


def acao(response):
    return response.headers.get("access-control-allow-origin")


def test_app_has_no_cors_middleware_and_nginx_sends_no_cors_headers(app):
    assert not [m for m in app.user_middleware if m.cls is CORSMiddleware], "CORS 추가는 보안 검토 대상"
    assert "Access-Control-" not in NGINX.read_text(encoding="utf-8")


def test_cross_origin_requests_get_no_cors_grant_and_auth_still_applies(client):
    no_token = client.get("/api/v1/me", headers={"Origin": EVIL})
    assert no_token.status_code == 401 and acao(no_token) is None
    token = signup(client, email="t86-cors@example.com").json()["access_token"]
    with_token = client.get("/api/v1/me", headers={"Origin": EVIL, **bearer(token)})
    assert with_token.status_code == 200 and acao(with_token) is None, "browser cannot read it cross-origin"
    preflight = client.options("/api/v1/me", headers={"Origin": EVIL, "Access-Control-Request-Method": "GET",
                                                     "Access-Control-Request-Headers": "authorization"})
    assert acao(preflight) is None and preflight.status_code >= 400


def test_ambient_cookie_never_authenticates_api_calls(client):
    """CSRF 헤더 검사는 쿠키 인증 경로(/auth)에만 있습니다. 그 밖의 API 는 Bearer 만 인정하므로
    브라우저가 자동으로 붙이는 refresh 쿠키로는 인증되지 않아야 합니다(교차 사이트 요청 위조 불가)."""
    signup(client, email="t86-csrf@example.com")
    assert client.cookies.get("refresh_token"), "refresh cookie is in the jar"
    for method, path in (("PATCH", "/api/v1/me"), ("POST", "/api/v1/me/experiences"), ("GET", "/api/v1/me/sessions")):
        response = client.request(method, path, headers={"Origin": EVIL}, json={"display_name": "x"})
        assert response.status_code == 401, f"{method} {path}"


def test_cookie_authenticated_auth_routes_require_the_csrf_header(client):
    signup(client, email="t86-csrf2@example.com")
    for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
        response = client.post(path, headers={"Origin": EVIL, "X-CSRF-TOKEN": ""})
        assert response.status_code == 403, path


@pytest.fixture
def permissive_cors_app(monkeypatch):
    """가정: 누군가 CORS 를 넓게 열었다. 그래도 인증·인가는 그대로여야 한다."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "t15-test-secret-0123456789-abcdefghij")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    application = create_app()
    application.add_middleware(CORSMiddleware, allow_origins=[EVIL], allow_credentials=True,
                               allow_methods=["*"], allow_headers=["*"])
    override_auth_repository(application, MemoryAuthRepository())
    with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as c:
        yield c
    get_settings.cache_clear()


def test_an_allowed_origin_does_not_authenticate_or_authorize(permissive_cors_app):
    c = permissive_cors_app
    preflight = c.options("/api/v1/admin/audit-events", headers={"Origin": EVIL, "Access-Control-Request-Method": "GET"})
    assert acao(preflight) == EVIL, "CORS layer says the origin may call"
    anonymous = c.get("/api/v1/admin/audit-events", headers={"Origin": EVIL})
    assert anonymous.status_code == 401 and acao(anonymous) == EVIL
    token = signup(c, email="t86-cors-seeker@example.com").json()["access_token"]
    seeker = c.get("/api/v1/admin/audit-events", headers={"Origin": EVIL, **bearer(token)},
                   params={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"})
    assert seeker.status_code == 403, "CORS pass ≠ admin"
