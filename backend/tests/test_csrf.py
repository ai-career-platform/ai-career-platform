"""브라우저의 쿠키 인증 CSRF 공격과 세션 부작용을 검증한다."""

import pytest

from tests.conftest import bearer, signup

AUTH = "/api/v1/auth"


@pytest.mark.parametrize("endpoint", ["signup", "login", "refresh", "logout"])
@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "multipart/form-data", "text/plain", "application/json"])
def test_auth_rejects_requests_without_custom_header(client, repo, endpoint, content_type):
    client.headers.pop("X-CSRF-TOKEN")
    response = client.post(f"{AUTH}/{endpoint}", content="{}", headers={"Content-Type": content_type})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.headers["x-request-id"]
    assert "set-cookie" not in response.headers
    assert repo.stored()["sessions"] == {}


@pytest.mark.parametrize("endpoint", ["signup", "login", "refresh", "logout"])
@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
def test_auth_rejects_other_sites_even_with_custom_header(client, endpoint, site):
    response = client.post(f"{AUTH}/{endpoint}", json={}, headers={"Sec-Fetch-Site": site})
    assert response.status_code == 403


@pytest.mark.parametrize("endpoint", ["refresh", "logout"])
@pytest.mark.parametrize("header", [None, "", "0"])
def test_rejected_cookie_request_does_not_rotate_or_revoke_session(client, endpoint, header):
    token = signup(client).json()["access_token"]
    old_cookie = client.cookies.get("refresh_token")
    client.headers.pop("X-CSRF-TOKEN")
    headers = {} if header is None else {"X-CSRF-TOKEN": header}
    response = client.post(f"{AUTH}/{endpoint}", headers=headers)
    assert response.status_code == 403
    assert client.cookies.get("refresh_token") == old_cookie
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    response = client.post(f"{AUTH}/refresh", headers={
        "X-CSRF-TOKEN": "1", "Sec-Fetch-Site": "same-origin",
    })
    assert response.status_code == 200
    assert client.cookies.get("refresh_token") != old_cookie


def test_external_origin_cannot_preflight_custom_header(client):
    response = client.options(f"{AUTH}/refresh", headers={
        "Origin": "https://attacker.example",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-TOKEN",
    })
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_public_get_needs_no_csrf_header(client):
    client.headers.pop("X-CSRF-TOKEN")
    assert client.get("/api/v1/consent-policies").status_code == 200
