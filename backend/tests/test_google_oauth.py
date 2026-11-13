"""#328 STEP 03-a Google OAuth 자동 가입·로그인 + 게이트 시험 (설계 PR #329 §11.1, 보안 검토 8개 항목).

- 가짜 IdP(tests/google_idp.py)와 시험용 RSA 키·합성 Client Secret 만 쓴다. 실제 Google·Staging 에 접속하지 않는다.
- 저장소는 메모리 구현(tests/fakes.py). 실제 PostgreSQL 은 tests/test_google_oauth_postgres.py.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.auth_config import AuthSettings, GoogleSettings, normalize_public_path_prefix
from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.repositories.auth import IdentityTaken, NewUser
from app.services.google_oauth import (
    PURPOSE_GATE,
    PURPOSE_PENDING,
    EmailAllowlist,
    GoogleOAuthClient,
    OneTimeUse,
    safe_return_to,
)
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer, signup
from tests.fakes import MemoryAuthRepository, override_auth_repository
from tests.google_idp import CLIENT_ID, CLIENT_SECRET, FakeGoogle

AUTH = f"{API_V1_PREFIX}/auth"
START, CALLBACK = f"{AUTH}/google/start", f"{AUTH}/google/callback"
PENDING, SIGNUP, GATE = f"{AUTH}/google/pending", f"{AUTH}/google/signup", f"{AUTH}/gate"
SIGNOUT, SIGNED_OUT = f"{AUTH}/google/signout", f"{AUTH}/google/signed-out"
COOKIE_SECRET = "t328-google-cookie-secret-0123456789-xyz"
# TestClient(httpx) 는 서버가 준 쿠키를 'testserver.local' 도메인으로 저장한다. 직접 넣는 쿠키도 같은 도메인이어야
# 서버 쿠키를 덮어쓰고 실제로 전송된다(아니면 '안 보냈는데 401' 인 거짓 통과가 생긴다).
JAR_DOMAIN = "testserver.local"
ALLOWED = "seeker@gmail.com"


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def idp() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def google_files(tmp_path):
    secret = tmp_path / "client_secret"
    secret.write_text(CLIENT_SECRET + "\n", encoding="utf-8")
    allow = tmp_path / "allowlist.txt"
    allow.write_text(f"# 시험용 합성 주소\n{ALLOWED.upper()}\nother@example.com\n*@gmail.com\n", encoding="utf-8")
    return {"secret": secret, "allow": allow}


def google_env(monkeypatch, files, *, gate=False, prefix=""):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GOOGLE_LOGIN_ENABLED", "1")
    monkeypatch.setenv("GOOGLE_GATE_ENFORCED", "1" if gate else "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", str(files["secret"]))
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", f"https://testserver{prefix}{CALLBACK}")
    monkeypatch.setenv("GOOGLE_ALLOWLIST_FILE", str(files["allow"]))
    monkeypatch.setenv("GOOGLE_COOKIE_SECRET", COOKIE_SECRET)
    monkeypatch.setenv("PUBLIC_PATH_PREFIX", prefix)
    get_settings.cache_clear()


def build(monkeypatch, files, repo, idp, **env):
    google_env(monkeypatch, files, **env)
    application = create_app()
    override_auth_repository(application, repo)
    runtime = application.state.google
    runtime.client = GoogleOAuthClient(runtime.settings, transport=idp.transport, key_resolver=idp.key_resolver)
    return application


@pytest.fixture
def gapp(monkeypatch, google_files, repo, idp):
    application = build(monkeypatch, google_files, repo, idp)
    yield application
    get_settings.cache_clear()


@pytest.fixture
def gclient(gapp):
    with TestClient(gapp, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        yield client


@pytest.fixture
def gated(monkeypatch, google_files, repo, idp):
    application = build(monkeypatch, google_files, repo, idp, gate=True)
    with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        yield client
    get_settings.cache_clear()


# ---------------------------------------------------------------- helpers
def cookies_of(response) -> dict[str, str]:
    """Set-Cookie 헤더 → {이름: 원문 헤더}"""
    out = {}
    for raw in response.headers.get_list("set-cookie"):
        out[raw.split("=", 1)[0]] = raw
    return out


def begin(client, **params):
    response = client.get(START, params=params, follow_redirects=False)
    assert response.status_code == 302, response.text
    return response


def google_login(client, idp, *, email=ALLOWED, sub="google-sub-1", start_params=None, **claims):
    start = begin(client, **(start_params or {}))
    code, state = idp.authorize(start.headers["location"], sub=sub, email=email, **claims)
    return client.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)


def complete_signup(client, consents=CONSENTS, display_name="김구글"):
    return client.post(SIGNUP, json={"display_name": display_name, "consents": consents})


def signup_with_google(client, idp, **kw):
    callback = google_login(client, idp, **kw)
    assert callback.headers["location"] == "/auth/google/signup", callback.headers["location"]
    response = complete_signup(client)
    assert response.status_code == 201, response.text
    return response


def assert_problem(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code
    return response


# ================================================================= 1. 플래그 꺼짐 = 기존 동작
def test_flags_off_google_routes_are_absent_and_refresh_cookie_path_unchanged(client):
    for method, path in [("GET", START), ("GET", CALLBACK), ("GET", PENDING), ("POST", SIGNUP), ("GET", GATE),
                         ("POST", SIGNOUT), ("GET", SIGNED_OUT)]:
        assert client.request(method, path).status_code == 404, path
    response = signup(client)
    assert response.status_code == 201
    assert f"Path={AUTH};" in response.headers["set-cookie"] or response.headers["set-cookie"].endswith(f"Path={AUTH}")
    assert "career_gate" not in response.headers["set-cookie"]
    # 게이트 미들웨어가 설치되지 않음: 공개 API 그대로
    assert client.get(f"{API_V1_PREFIX}/consent-policies").status_code == 200


def test_flags_off_app_state_has_no_google_runtime(app):
    assert app.state.google is None
    assert app.state.google_settings == GoogleSettings.disabled()


# ================================================================= 2. 설정 검증 (fail closed)
def _auth(app_env="test", **kw) -> AuthSettings:
    base = AuthSettings(jwt_secret=TEST_SECRET, access_token_ttl_seconds=900, refresh_token_ttl_seconds=3600,
                        cookie_secure=True, login_max_failures=5, login_lock_seconds=900, login_ip_max_attempts=30,
                        signup_ip_max_attempts=10, rate_window_seconds=900)
    return replace(base, **kw)


@pytest.mark.parametrize("name,value,message", [
    ("GOOGLE_CLIENT_ID", "", "GOOGLE_CLIENT_ID"),
    ("GOOGLE_CLIENT_SECRET_FILE", "", "GOOGLE_CLIENT_SECRET_FILE"),
    ("GOOGLE_CLIENT_SECRET_FILE", "/nonexistent/secret", "not readable"),
    ("GOOGLE_REDIRECT_URI", "https://testserver/wrong/callback", "path"),
    ("GOOGLE_REDIRECT_URI", "https://testserver/api/v1/auth/google/callback?x=1", "absolute https"),
    ("GOOGLE_ALLOWLIST_FILE", "", "GOOGLE_ALLOWLIST_FILE"),
    ("GOOGLE_ALLOWLIST_FILE", "/nonexistent/allow.txt", "GOOGLE_ALLOWLIST_FILE"),
    ("GOOGLE_COOKIE_SECRET", "short", "at least"),
    ("GOOGLE_COOKIE_SECRET", TEST_SECRET, "differ"),
])
def test_incomplete_google_settings_refuse_to_start(monkeypatch, google_files, name, value, message):
    google_env(monkeypatch, google_files)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        create_app()
    get_settings.cache_clear()


def test_empty_secret_file_refuses_to_start(monkeypatch, google_files):
    google_files["secret"].write_text("\n", encoding="utf-8")
    google_env(monkeypatch, google_files)
    with pytest.raises(ValueError, match="exactly one"):
        create_app()


def test_gate_without_login_refuses_to_start(monkeypatch):
    monkeypatch.setenv("GOOGLE_LOGIN_ENABLED", "0")
    monkeypatch.setenv("GOOGLE_GATE_ENFORCED", "1")
    with pytest.raises(ValueError, match="requires GOOGLE_LOGIN_ENABLED"):
        GoogleSettings.from_env("test", _auth())


def test_staging_rules(monkeypatch, google_files):
    google_env(monkeypatch, google_files)
    monkeypatch.setenv("GOOGLE_TEST_IDP_BASE_URL", "http://127.0.0.1:9999")
    with pytest.raises(ValueError, match="only in local-dev/test"):
        GoogleSettings.from_env("staging", _auth())
    monkeypatch.delenv("GOOGLE_TEST_IDP_BASE_URL")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "not-a-google-client")
    with pytest.raises(ValueError, match="web client id"):
        GoogleSettings.from_env("staging", _auth())
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", f"http://testserver{CALLBACK}")
    with pytest.raises(ValueError, match="absolute https"):
        GoogleSettings.from_env("staging", _auth())
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", f"https://testserver{CALLBACK}")
    with pytest.raises(ValueError, match="AUTH_COOKIE_SECURE"):
        GoogleSettings.from_env("staging", _auth(cookie_secure=False))
    ok = GoogleSettings.from_env("staging", _auth())
    assert ok.login_enabled and ok.token_endpoint == "https://oauth2.googleapis.com/token"
    assert CLIENT_SECRET not in repr(ok) and COOKIE_SECRET not in repr(ok) and CLIENT_ID not in repr(ok)


def test_test_idp_override_only_in_local(monkeypatch, google_files):
    google_env(monkeypatch, google_files)
    monkeypatch.setenv("GOOGLE_TEST_IDP_BASE_URL", "http://127.0.0.1:9999/")
    settings = GoogleSettings.from_env("test", _auth())
    assert settings.token_endpoint == "http://127.0.0.1:9999/token" and settings.issuers == ("http://127.0.0.1:9999",)


@pytest.mark.parametrize("raw,expected", [("", ""), ("/", ""), ("/career", "/career"), ("/career/", "/career"),
                                          ("  /career  ", "/career"), ("/a/b-c_d", "/a/b-c_d")])
def test_public_path_prefix_normalization(raw, expected):
    assert normalize_public_path_prefix(raw) == expected


@pytest.mark.parametrize("raw", ["career", "//career", "/career/../x", "/./career", "/ca reer", "/career?x", "/a//b"])
def test_public_path_prefix_rejects_unsafe_values(raw):
    with pytest.raises(ValueError):
        normalize_public_path_prefix(raw)


# ================================================================= 3. 인가 URL·PKCE·state·nonce
def test_start_redirects_with_code_flow_pkce_state_nonce(gclient):
    response = begin(gclient)
    url = urllib.parse.urlsplit(response.headers["location"])
    query = urllib.parse.parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query["response_type"] == ["code"] and query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
    assert query["client_id"] == [CLIENT_ID] and query["redirect_uri"] == [f"https://testserver{CALLBACK}"]
    assert len(query["state"][0]) >= 32 and len(query["nonce"][0]) >= 32 and query["state"] != query["nonce"]
    assert "client_secret" not in query and CLIENT_SECRET not in response.headers["location"]
    assert "prompt" not in query
    tx = cookies_of(response)["career_g_tx"]
    for attr in ("HttpOnly", "Secure", "SameSite=lax", f"Path={AUTH}/google", "Max-Age=600"):
        assert attr.lower() in tx.lower(), attr
    assert response.headers["cache-control"] == "no-store"
    # 매번 새 값
    again = urllib.parse.parse_qs(urllib.parse.urlsplit(begin(gclient).headers["location"]).query)
    assert again["state"] != query["state"] and again["code_challenge"] != query["code_challenge"]


def test_start_prompt_select_account(gclient):
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(
        begin(gclient, prompt="select_account").headers["location"]).query)
    assert query["prompt"] == ["select_account"]
    assert gclient.get(START, params={"prompt": "consent"}, follow_redirects=False).status_code == 422


def test_pkce_verifier_is_sent_only_to_token_endpoint(gclient, idp):
    start = begin(gclient)
    assert "code_verifier" not in start.headers["location"]
    code, state = idp.authorize(start.headers["location"])
    gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    (exchange,) = idp.exchanges
    assert exchange["grant_type"] == "authorization_code" and len(exchange["code_verifier"]) >= 43


# ================================================================= 4. return_to
@pytest.mark.parametrize("value", [None, "", "https://evil.example/", "//evil.example/x", "/\\evil", "/@evil",
                                   "/x/../career", "/api/v1/me", "/api", "/%2e%2e/x", "/a/%2E%2E/b",
                                   "/" + "a" * 600, "/ok\nSet-Cookie:x"])
def test_return_to_rejects_unsafe_values(value):
    assert safe_return_to(value, "") == "/"


@pytest.mark.parametrize("value", ["/", "/me/skills", "/job-postings?page=2"])
def test_return_to_keeps_same_site_paths(value):
    assert safe_return_to(value, "") == value


def test_return_to_with_prefix():
    assert safe_return_to("/career/me", "/career") == "/career/me"
    for bad in ("/me", "/careerx/me", "/career/api/v1/me", "/career/../x", "/church/"):
        assert safe_return_to(bad, "/career") == "/career/"


def test_returning_user_lands_on_validated_return_to(gclient, idp):
    signup_with_google(gclient, idp)
    response = google_login(gclient, idp, start_params={"return_to": "/me/skills"})
    assert response.headers["location"] == "/auth/google/done?next=%2Fme%2Fskills"
    response = google_login(gclient, idp, start_params={"return_to": "https://evil.example/"})
    assert response.headers["location"] == "/auth/google/done?next=%2F"


# ================================================================= 5. ID Token 검증
OTHER_KEY = FakeGoogle().key


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else.apps.googleusercontent.com"},
    {"iss": "https://evil.example"},
    {"azp": "someone-else.apps.googleusercontent.com"},
    {"exp": 1_000_000_000},
    {"iat": 1_000_000_000},
    {"nonce": "attacker-nonce"},
    {"email_verified": False},
    {"email_verified": "true"},
    {"email_verified": None},
    {"sub": None},
    {"email": None},
    {"email": "two@@gmail.com"},
    {"signing_key": OTHER_KEY},
])
def test_invalid_id_tokens_are_rejected(gclient, idp, repo, claims):
    response = google_login(gclient, idp, **claims)
    assert response.status_code == 400 and "text/html" in response.headers["content-type"]
    assert set(cookies_of(response)) == {"career_g_tx"}  # tx 삭제만. gate·pending·refresh 없음
    assert repo.stored()["users"] == {}


def test_hs256_token_signed_with_public_material_is_rejected(gclient, idp):
    # alg 혼동 공격: HS256 서명 토큰은 RS256 만 허용하므로 거부
    response = google_login(gclient, idp, signing_key="any-shared-secret-value-0123456789abcd", algorithm="HS256")
    assert response.status_code == 400


def test_missing_name_falls_back_to_email_local_part(gclient, idp):
    google_login(gclient, idp, name=None)
    assert gclient.get(PENDING).json()["display_name"] == "seeker"


# ================================================================= 6. callback 재사용·state·tx
def test_callback_replay_with_same_tx_cookie_is_rejected(gclient, idp, repo, caplog):
    caplog.set_level(logging.INFO, logger="app.routers.google_auth")
    start = begin(gclient)
    tx_cookie = gclient.cookies.get("career_g_tx")
    code, state = idp.authorize(start.headers["location"])
    first = gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    assert first.headers["location"] == "/auth/google/signup"
    # 공격자가 같은 tx 쿠키·code·state 를 다시 보냄 → 서버측 1회 사용으로 거부(Google 교환 전에 차단)
    gclient.cookies.set("career_g_tx", tx_cookie, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    exchanges = len(idp.exchanges)
    replay = gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    assert replay.headers["location"] == "/login?google_error=failed"  # 이미 게이트가 있으므로 SPA 안내
    assert len(idp.exchanges) == exchanges
    assert "reason=tx_replayed" in caplog.text  # 쿠키가 실제로 전송됐고 '재사용'으로 거부됨(누락 아님)


def test_google_code_is_single_use_even_with_a_fresh_transaction(gclient, idp):
    start = begin(gclient)
    code, state = idp.authorize(start.headers["location"])
    gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    second = begin(gclient)
    second_state = urllib.parse.parse_qs(urllib.parse.urlsplit(second.headers["location"]).query)["state"][0]
    reused = gclient.get(CALLBACK, params={"code": code, "state": second_state}, follow_redirects=False)
    assert reused.headers["location"] == "/login?google_error=failed"  # IdP invalid_grant


def test_concurrent_claims_of_one_transaction_allow_exactly_one():
    once = OneTimeUse()
    wins = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        wins.append(once.claim("same-jti", 9_999_999_999))

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1


def test_one_time_entries_expire():
    now = [1000.0]
    once = OneTimeUse(clock=lambda: now[0])
    assert once.claim("a", 1010) and not once.claim("a", 1010)
    now[0] = 2000.0
    assert once.claim("a", 2010)


@pytest.mark.parametrize("mutate", ["missing", "tampered", "state"])
def test_callback_rejects_missing_tampered_tx_or_wrong_state(gclient, idp, mutate):
    start = begin(gclient)
    code, state = idp.authorize(start.headers["location"])
    if mutate == "missing":
        gclient.cookies.clear()
    elif mutate == "tampered":
        value = gclient.cookies.get("career_g_tx")
        gclient.cookies.clear()
        gclient.cookies.set("career_g_tx", value[:-4] + "AAAA", domain=JAR_DOMAIN, path=f"{AUTH}/google")
    else:
        state = "attacker-state"
    response = gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    assert response.status_code == 400 and "career_gate" not in cookies_of(response)


def test_callback_with_tx_signed_by_other_key_is_rejected(gclient, idp):
    start = begin(gclient)
    code, state = idp.authorize(start.headers["location"])
    forged = jwt.encode({"purpose": "google_tx", "iss": "ai-career-platform/google", "iat": 1, "exp": 9_999_999_999,
                         "jti": "x", "state": state, "nonce": "n", "cv": "v", "rt": "/"}, "x" * 40, algorithm="HS256")
    gclient.cookies.clear()
    gclient.cookies.set("career_g_tx", forged, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    assert gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False).status_code == 400


def test_user_cancel_is_reported_as_cancelled(gclient, idp):
    begin(gclient)
    response = gclient.get(CALLBACK, params={"error": "access_denied"}, follow_redirects=False)
    assert response.status_code == 400 and "취소" in response.text


# ================================================================= 7. Allowlist
def test_not_allowlisted_account_gets_static_403_and_no_cookies(gclient, idp, repo):
    response = google_login(gclient, idp, email="stranger@gmail.com")
    assert response.status_code == 403 and "text/html" in response.headers["content-type"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    set_cookies = cookies_of(response)
    assert "career_g_pending" not in set_cookies and "refresh_token" not in set_cookies
    assert "max-age=0" in set_cookies["career_gate"].lower()  # 이전 게이트도 끊음
    assert repo.stored()["users"] == {}


def test_allowlist_is_exact_and_case_insensitive(gclient, idp):
    # 파일에는 대문자로 적혀 있음 → 허용. '*@gmail.com' 줄은 와일드카드로 동작하지 않음.
    assert google_login(gclient, idp, email="Seeker@Gmail.com").headers["location"] == "/auth/google/signup"
    assert google_login(gclient, idp, email="seeker2@gmail.com", sub="s2").status_code == 403
    assert google_login(gclient, idp, email="xseeker@gmail.com", sub="s3").status_code == 403


def test_empty_allowlist_denies_everyone(gclient, idp, google_files):
    google_files["allow"].write_text("# nobody yet\n", encoding="utf-8")
    assert google_login(gclient, idp).status_code == 403


def test_allowlist_file_removed_at_runtime_denies_everyone(gclient, idp, google_files):
    google_files["allow"].unlink()
    assert google_login(gclient, idp).status_code == 403


def test_allowlist_parser_ignores_malformed_lines():
    assert EmailAllowlist._parse("a@b.c\n bad line@x.y \n*@x.y\n@@\nno-at\n#c@d.e\nB@C.D") == {"a@b.c", "b@c.d"}


# ================================================================= 8. 최초 가입(pending)·약관·트랜잭션
def test_first_login_issues_pending_and_gate_without_db_writes(gclient, idp, repo):
    response = google_login(gclient, idp)
    assert response.headers["location"] == "/auth/google/signup"
    set_cookies = cookies_of(response)
    for attr in ("HttpOnly", "Secure", "SameSite=strict", f"Path={AUTH}/google", "Max-Age=600"):
        assert attr.lower() in set_cookies["career_g_pending"].lower(), attr
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=43200"):
        assert attr.lower() in set_cookies["career_gate"].lower(), attr
    assert "max-age=0" in set_cookies["career_g_tx"].lower()
    assert "refresh_token" not in set_cookies
    assert repo.stored()["users"] == {} and repo.commits == 0
    pending = gclient.get(PENDING)
    assert pending.status_code == 200 and pending.headers["cache-control"] == "no-store"
    assert pending.json()["email"] == ALLOWED and pending.json()["display_name"] == "김구글"


def test_signup_requires_current_required_consents_and_allows_retry(gclient, idp, repo):
    google_login(gclient, idp)
    missing = [c | {"granted": False} if c["policy_code"] == "terms" else c for c in CONSENTS]
    assert_problem(complete_signup(gclient, consents=missing), 422, "VALIDATION_FAILED")
    stale = [{"policy_code": "terms", "policy_version": "1999-01", "granted": True}, *CONSENTS[1:]]
    assert_problem(complete_signup(gclient, consents=stale), 422, "VALIDATION_FAILED")
    assert repo.stored()["users"] == {}
    assert complete_signup(gclient).status_code == 201  # 입력 오류는 pending 을 소모하지 않음


def test_signup_creates_google_identity_job_seeker_consents_and_session(gclient, idp, repo):
    response = signup_with_google(gclient, idp, sub="google-sub-XYZ")
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    claims = jwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"], issuer="ai-career-platform")
    assert claims["roles"] == ["job_seeker"]
    stored = repo.stored()
    user_id = uuid.UUID(claims["sub"])
    assert stored["external"][("google", "google-sub-XYZ")] == {"user_id": user_id, "password_hash": None}
    assert stored["identities"] == {}  # local identity 를 만들지 않음
    assert stored["users"][user_id].email == ALLOWED and stored["users"][user_id].display_name == "김구글"
    assert stored["roles"][user_id] == {"job_seeker"}
    assert [c[1:4] for c in stored["consents"]] == [(c["policy_code"], c["policy_version"], c["granted"])
                                                   for c in CONSENTS]
    assert len(stored["sessions"]) == 1
    set_cookies = cookies_of(response)
    for attr in ("refresh_token=", "HttpOnly", "Secure", "SameSite=strict", f"Path={AUTH}", "Max-Age=1209600"):
        assert attr.lower() in set_cookies["refresh_token"].lower(), attr
    assert "max-age=0" in set_cookies["career_g_pending"].lower()
    # 기존 refresh·me 흐름 그대로
    assert gclient.post(f"{AUTH}/refresh").status_code == 200
    assert gclient.get(f"{API_V1_PREFIX}/me", headers=bearer(body["access_token"])).json()["email"] == ALLOWED


def test_pending_cannot_be_replayed_after_signup(gclient, idp, caplog):
    caplog.set_level(logging.INFO)
    google_login(gclient, idp)
    pending = gclient.cookies.get("career_g_pending")
    assert complete_signup(gclient).status_code == 201
    gclient.cookies.set("career_g_pending", pending, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    assert gclient.cookies.get("career_g_pending") == pending
    assert_problem(complete_signup(gclient), 401, "GOOGLE_SIGNUP_EXPIRED")
    assert_problem(gclient.get(PENDING), 401, "GOOGLE_SIGNUP_EXPIRED")
    assert caplog.text.count("google pending already used") == 2  # 누락이 아니라 '재사용'으로 거부


def test_pending_missing_forged_or_wrong_purpose_is_401(gclient, gapp, idp):
    assert_problem(complete_signup(gclient), 401, "GOOGLE_SIGNUP_EXPIRED")
    signer = gapp.state.google.signer
    gate_token, _ = signer.sign(PURPOSE_GATE, 600, sub="s", email=ALLOWED, name="n")
    gclient.cookies.set("career_g_pending", gate_token, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    assert_problem(complete_signup(gclient), 401, "GOOGLE_SIGNUP_EXPIRED")  # purpose 가 다름
    expired, _ = signer.sign(PURPOSE_PENDING, -1, sub="s", email=ALLOWED, name="n")
    gclient.cookies.set("career_g_pending", expired, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    assert_problem(complete_signup(gclient), 401, "GOOGLE_SIGNUP_EXPIRED")


def test_signup_rechecks_allowlist(gclient, idp, google_files):
    google_login(gclient, idp)
    google_files["allow"].write_text("other@example.com\n", encoding="utf-8")
    assert_problem(complete_signup(gclient), 403, "GOOGLE_NOT_ALLOWED")


def test_signup_requires_csrf_header(gclient, idp):
    google_login(gclient, idp)
    response = gclient.post(SIGNUP, json={"display_name": "x", "consents": CONSENTS}, headers={"X-CSRF-TOKEN": ""})
    assert_problem(response, 403, "FORBIDDEN")


def test_double_submit_creates_one_account(gclient, idp, repo):
    google_login(gclient, idp)
    assert complete_signup(gclient).status_code == 201
    assert_problem(complete_signup(gclient), 401, "GOOGLE_SIGNUP_EXPIRED")
    assert len(repo.stored()["users"]) == 1


def test_second_tab_pending_for_same_sub_logs_into_the_same_account(gclient, idp, repo):
    # 두 탭에서 각각 Google 인증 → pending 2개. 한쪽이 가입을 끝내면 다른 쪽 pending 은 같은 계정 로그인(새 계정 없음)
    google_login(gclient, idp)
    first = gclient.cookies.get("career_g_pending")
    google_login(gclient, idp)
    second = gclient.cookies.get("career_g_pending")
    assert first != second
    gclient.cookies.set("career_g_pending", first, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    one = complete_signup(gclient)
    gclient.cookies.set("career_g_pending", second, domain=JAR_DOMAIN, path=f"{AUTH}/google")
    two = complete_signup(gclient)
    assert one.status_code == two.status_code == 201
    subs = {jwt.decode(r.json()["access_token"], options={"verify_signature": False})["sub"] for r in (one, two)}
    assert len(subs) == 1 and len(repo.stored()["users"]) == 1 and len(repo.stored()["sessions"]) == 2


class RacingRepo(MemoryAuthRepository):
    """signup 이 find_identity 로 None 을 본 직후, 다른 요청이 먼저 커밋한 상황을 재현한다.

    race="identity": 같은 sub 로 가입 완료(→ IdentityTaken → 그 계정으로 로그인)
    race="email": 같은 이메일의 다른 계정 생성(→ EmailTaken → 409)
    """

    def __init__(self, race: str) -> None:
        super().__init__()
        self.race = race
        self.armed = False

    def find_identity(self, provider, subject):
        found = super().find_identity(provider, subject)
        if self.armed and provider == "google" and found is None:
            self.armed = False
            email = ALLOWED if self.race == "email" else "elsewhere@gmail.com"
            winner = NewUser(email=email, email_canonical=email, display_name="경쟁", password_hash=None,
                             consents=[], role_code="job_seeker", identity_provider="google",
                             identity_subject=subject if self.race == "identity" else "other-sub")
            super().create_user(winner, datetime.now(UTC))
            self.commit()
        return found


@pytest.mark.parametrize("race,status", [("identity", 201), ("email", 409)])
def test_concurrent_signup_races_are_resolved_by_unique_constraints(monkeypatch, google_files, idp, race, status):
    repo = RacingRepo(race)
    application = build(monkeypatch, google_files, repo, idp)
    with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        start = begin(client)
        code, state = idp.authorize(start.headers["location"])
        client.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)  # 신규 판정
        repo.armed = True  # signup 의 find_identity 직후 경쟁 발생
        response = complete_signup(client)
    get_settings.cache_clear()
    assert response.status_code == status, response.text
    linked = [k for k in repo.stored()["external"] if k[1] == "google-sub-1"]
    if race == "email":
        assert response.json()["code"] == "GOOGLE_EMAIL_CONFLICT" and linked == []
    else:
        assert len(linked) == 1 and len(repo.stored()["users"]) == 1  # 계정 1개, 그 계정으로 로그인


def test_identity_taken_is_raised_by_memory_repo_for_duplicate_sub():
    repo = MemoryAuthRepository()
    new = NewUser(email="a@gmail.com", email_canonical="a@gmail.com", display_name="a", password_hash=None,
                  consents=[], role_code="job_seeker", identity_provider="google", identity_subject="dup")
    repo.create_user(new, datetime.now(UTC))
    with pytest.raises(IdentityTaken):
        repo.create_user(replace(new, email="b@gmail.com", email_canonical="b@gmail.com"), datetime.now(UTC))


# ================================================================= 9. 재방문·충돌·비활성
def test_returning_google_user_is_logged_in_without_consent_screen(gclient, idp, repo):
    signup_with_google(gclient, idp)
    gclient.cookies.clear()
    response = google_login(gclient, idp)
    assert response.headers["location"] == "/auth/google/done?next=%2F"
    set_cookies = cookies_of(response)
    assert "refresh_token" in set_cookies and "career_gate" in set_cookies and "career_g_pending" not in set_cookies
    assert len(repo.stored()["users"]) == 1 and len(repo.stored()["sessions"]) == 2
    assert gclient.post(f"{AUTH}/refresh").status_code == 200


def test_same_email_local_account_is_never_auto_linked(gclient, idp, repo):
    assert signup(gclient, email="Cras.Nec+box@gmail.com").status_code == 201
    allow_path = gclient.app.state.google.settings.allowlist_file
    with open(allow_path, "a", encoding="utf-8") as handle:
        handle.write("crasnec@gmail.com\n")
    response = google_login(gclient, idp, email="crasnec@gmail.com", sub="attacker-sub")
    assert response.headers["location"] == "/login?google_error=email_conflict"
    assert "career_gate" in cookies_of(response) and "refresh_token" not in cookies_of(response)
    assert repo.stored()["external"] == {} and len(repo.stored()["users"]) == 1
    # 기존 로컬 로그인은 그대로
    login = gclient.post(f"{AUTH}/login", json={"email": "crasnec@gmail.com", "password": PASSWORD})
    assert login.status_code == 200


def test_signup_endpoint_rechecks_email_conflict(gclient, idp):
    google_login(gclient, idp)
    assert signup(gclient, email=ALLOWED).status_code == 201  # 그사이 같은 이메일 로컬 가입
    assert_problem(complete_signup(gclient), 409, "GOOGLE_EMAIL_CONFLICT")


def test_disabled_google_user_is_refused_without_revealing_status(gclient, idp, repo):
    token = signup_with_google(gclient, idp).json()["access_token"]
    repo.set_status(uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"]), "disabled")
    response = google_login(gclient, idp)
    assert response.headers["location"] == "/login?google_error=failed"
    assert "refresh_token" not in cookies_of(response)


def test_redirect_locations_never_carry_tokens_or_identity(gclient, idp):
    locations = []
    callback = google_login(gclient, idp, sub="secret-sub-123")
    locations.append(callback.headers["location"])
    token = complete_signup(gclient).json()["access_token"]
    locations.append(google_login(gclient, idp, sub="secret-sub-123").headers["location"])
    for location in locations:
        for secret in (ALLOWED, "seeker", "secret-sub-123", token, "id_token", "code="):
            assert secret not in location, (secret, location)


def test_logs_do_not_contain_email_sub_code_or_secrets(gclient, idp, caplog):
    caplog.set_level(logging.DEBUG)
    start = begin(gclient)
    code, state = idp.authorize(start.headers["location"], sub="log-sub-777")
    gclient.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)
    complete_signup(gclient)
    google_login(gclient, idp, email="stranger@gmail.com", sub="log-sub-888")
    # httpx(시험 클라이언트) 로그는 요청 URL 을 그대로 남기므로 제외. 운영의 uvicorn.access 는 StripQueryFilter 로
    # 쿼리(code·state)를 지운다(app/core/observability.py) — 아래 시험이 확인.
    text = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    for secret in (ALLOWED, "stranger@gmail.com", "log-sub-777", "log-sub-888", code, CLIENT_SECRET, COOKIE_SECRET):
        assert secret not in text, secret
    assert "google_login result=signup_required" in text


def test_uvicorn_access_log_strips_oauth_query():
    from app.core.observability import StripQueryFilter
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:1", "GET", f"{CALLBACK}?code=SECRETCODE&state=S", "1.1", 302), None)
    StripQueryFilter().filter(record)
    assert "SECRETCODE" not in record.getMessage()


# ================================================================= 10. 쿠키 Path (PUBLIC_PATH_PREFIX)
def test_public_path_prefix_shapes_every_cookie_and_location(monkeypatch, google_files, repo, idp):
    application = build(monkeypatch, google_files, repo, idp, prefix="/career")
    with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        start = begin(client, return_to="/career/me")
        assert f"Path=/career{AUTH}/google".lower() in cookies_of(start)["career_g_tx"].lower()
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(start.headers["location"]).query)
        assert query["redirect_uri"] == [f"https://testserver/career{CALLBACK}"]
        # TestClient 는 /career 경로 쿠키를 /api 요청에 보내지 않으므로 tx 를 직접 실어 보낸다(nginx 접두사 제거 재현)
        tx = client.cookies.get("career_g_tx")
        code, state = idp.authorize(start.headers["location"])
        callback = client.get(CALLBACK, params={"code": code, "state": state}, headers={"Cookie": f"career_g_tx={tx}"},
                              follow_redirects=False)
        assert callback.headers["location"] == "/career/auth/google/signup"
        set_cookies = cookies_of(callback)
        assert "path=/career/;" in set_cookies["career_gate"].lower() + ";"
        assert f"path=/career{AUTH}/google".lower() in set_cookies["career_g_pending"].lower()
        response = client.post(f"{AUTH}/signup", json={"email": "local@example.com", "password": PASSWORD,
                                                       "display_name": "로컬", "consents": CONSENTS})
        assert f"path=/career{AUTH}".lower() in response.headers["set-cookie"].lower()
    get_settings.cache_clear()


def test_redirect_uri_path_must_include_prefix(monkeypatch, google_files):
    google_env(monkeypatch, google_files, prefix="/career")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", f"https://testserver{CALLBACK}")
    with pytest.raises(ValueError, match="path"):
        create_app()
    get_settings.cache_clear()


# ================================================================= 11. 완전 로그아웃(POST + CSRF)·일반 로그아웃
def test_full_signout_requires_csrf_and_clears_session_and_gate(gclient, idp, repo):
    signup_with_google(gclient, idp)
    assert_problem(gclient.post(SIGNOUT, headers={"X-CSRF-TOKEN": ""}), 403, "FORBIDDEN")
    assert_problem(gclient.post(SIGNOUT, headers={"Sec-Fetch-Site": "cross-site"}), 403, "FORBIDDEN")
    assert gclient.get(SIGNOUT).status_code == 405  # GET 로그아웃 없음
    response = gclient.post(SIGNOUT)
    assert response.status_code == 204
    set_cookies = cookies_of(response)
    for name in ("refresh_token", "career_gate", "career_g_pending"):
        assert "max-age=0" in set_cookies[name].lower(), name
    assert all(s["record"].revoked_at is not None for s in repo.stored()["sessions"].values())
    assert gclient.post(f"{AUTH}/refresh").status_code == 401
    page = gclient.get(SIGNED_OUT)
    assert page.status_code == 200 and "로그아웃" in page.text


def test_full_signout_without_session_still_clears_cookies(gclient):
    response = gclient.post(SIGNOUT)
    assert response.status_code == 204 and "career_gate" in cookies_of(response)


def test_regular_logout_keeps_gate_cookie(gclient, idp):
    signup_with_google(gclient, idp)
    response = gclient.post(f"{AUTH}/logout")
    assert response.status_code == 204
    assert "career_gate" not in cookies_of(response)
    assert gclient.get(GATE).status_code == 204


# ================================================================= 12. 게이트 (/auth/gate + 미들웨어)
def test_gate_endpoint(gclient, idp, gapp, google_files):
    assert_problem(gclient.get(GATE), 401, "EDGE_AUTH_REQUIRED")
    google_login(gclient, idp)
    assert gclient.get(GATE).status_code == 204
    google_files["allow"].write_text("other@example.com\n", encoding="utf-8")
    assert_problem(gclient.get(GATE), 401, "EDGE_AUTH_REQUIRED")  # Allowlist 제거 즉시 차단


def test_gate_disabled_middleware_is_not_installed(gclient):
    assert gclient.get(f"{API_V1_PREFIX}/consent-policies").status_code == 200


def gate_cookie(client, token):
    client.cookies.set("career_gate", token, domain=JAR_DOMAIN, path="/")


@pytest.mark.parametrize("path", [f"{API_V1_PREFIX}/consent-policies", f"{API_V1_PREFIX}/me", f"{AUTH}/login",
                                  f"{AUTH}/signup", f"{AUTH}/refresh", PENDING, SIGNUP, f"{API_V1_PREFIX}/job-roles",
                                  f"{API_V1_PREFIX}", f"{API_V1_PREFIX}/",
                                  f"{START}x", f"{AUTH}/google/startx", f"{AUTH}/google/callback/../../me"])
def test_gate_blocks_every_api_v1_route_without_cookie(gated, path):
    for method in ("GET", "POST"):
        response = gated.request(method, path, follow_redirects=False)
        assert_problem(response, 401, "EDGE_AUTH_REQUIRED")
        assert response.headers["x-request-id"] and response.headers["cache-control"] == "no-store"


def test_gate_blocks_bearer_only_requests(gated, gapp, repo, idp):
    # 게이트를 통과해 가입한 뒤 게이트 쿠키만 지우면 Bearer 만으로는 API 를 쓸 수 없다(LAN 직통 재현)
    token = signup_with_google(gated, idp).json()["access_token"]
    assert gated.get(f"{API_V1_PREFIX}/me", headers=bearer(token)).status_code == 200
    gate = gated.cookies.get("career_gate")
    gated.cookies.clear()
    assert_problem(gated.get(f"{API_V1_PREFIX}/me", headers=bearer(token)), 401, "EDGE_AUTH_REQUIRED")
    gate_cookie(gated, gate)
    assert gated.get(f"{API_V1_PREFIX}/me", headers=bearer(token)).status_code == 200


def test_gate_rejects_forged_expired_wrong_purpose_and_removed_users(gated, idp, google_files):
    google_login(gated, idp)
    good = gated.cookies.get("career_gate")
    signer = gated.app.state.google.signer
    for bad in (good[:-3] + "AAA", signer.sign(PURPOSE_GATE, -5, sub="s", email=ALLOWED)[0],
                signer.sign(PURPOSE_PENDING, 600, sub="s", email=ALLOWED, name="n")[0],
                jwt.encode({"purpose": "google_gate", "iss": "ai-career-platform/google", "iat": 1, "jti": "j",
                            "exp": 9_999_999_999, "sub": "s", "email": ALLOWED}, TEST_SECRET, algorithm="HS256"),
                "garbage", ""):
        gated.cookies.clear()
        gate_cookie(gated, bad)
        assert_problem(gated.get(f"{API_V1_PREFIX}/consent-policies"), 401, "EDGE_AUTH_REQUIRED")
    gated.cookies.clear()
    gate_cookie(gated, good)
    assert gated.get(f"{API_V1_PREFIX}/consent-policies").status_code == 200
    google_files["allow"].write_text("other@example.com\n", encoding="utf-8")
    assert_problem(gated.get(f"{API_V1_PREFIX}/consent-policies"), 401, "EDGE_AUTH_REQUIRED")


def test_gate_path_normalization_cannot_widen_exemptions_or_skip_protection():
    from app.core.google_gate import GoogleGateMiddleware
    from app.routers.google_auth import GATE_EXEMPT_PATHS
    gate = GoogleGateMiddleware(app=None, exempt_paths=GATE_EXEMPT_PATHS, cookie_name="career_gate")
    for path in ("//api/v1/me", "/api//v1/me", "/api/v1//me/", "/api/v1", "/api/v1/", f"{START}x",
                 f"{AUTH}/google/start/../../me", f"{AUTH}/google", f"{AUTH}/google/pending", f"{AUTH}/google/signup"):
        assert gate._protected(path), path
    for path in (START, f"{START}/", f"/{START}", CALLBACK, GATE, SIGNOUT, SIGNED_OUT, "/health", "/version",
                 "/health/db", "/", "/api/v10/x", "/apix"):
        assert not gate._protected(path), path


def test_gate_exemptions_are_exact_and_health_is_untouched(gated):
    assert gated.get("/health").status_code == 200
    assert gated.get("/version").status_code == 200
    assert gated.get(START, follow_redirects=False).status_code == 302
    assert gated.get(f"{START}/", follow_redirects=False).status_code in (302, 307)  # 끝 '/' 는 같은 경로
    assert gated.get(CALLBACK, follow_redirects=False).status_code == 400  # 도달은 하되 tx 없음 → 실패 페이지
    assert gated.get(GATE).status_code == 401
    assert gated.get(SIGNED_OUT).status_code == 200
    assert gated.post(SIGNOUT).status_code == 204


def test_lan_direct_request_without_prefixed_cookie_is_blocked(monkeypatch, google_files, repo, idp):
    """LAN :18080 직통 재현: 게이트 쿠키는 Path=/career/ 라서 '/api/...' 요청에 실리지 않는다 → 401."""
    application = build(monkeypatch, google_files, repo, idp, gate=True, prefix="/career")
    with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
        token, _ = application.state.google.signer.sign(PURPOSE_GATE, 600, sub="s", email=ALLOWED)
        client.cookies.set("career_gate", token, domain=JAR_DOMAIN, path="/career/")
        assert_problem(client.get(f"{API_V1_PREFIX}/consent-policies"), 401, "EDGE_AUTH_REQUIRED")
        assert_problem(client.post(f"{AUTH}/signup", json={"email": "lan@example.com", "password": PASSWORD,
                                                           "display_name": "LAN", "consents": CONSENTS}),
                       401, "EDGE_AUTH_REQUIRED")  # LAN 에서 로컬 계정 생성 불가
        assert repo.stored()["users"] == {}
    get_settings.cache_clear()


def test_gated_end_to_end_new_user_flow(gated, idp, repo):
    assert_problem(gated.get(f"{API_V1_PREFIX}/consent-policies"), 401, "EDGE_AUTH_REQUIRED")
    callback = google_login(gated, idp)
    assert callback.headers["location"] == "/auth/google/signup"
    assert gated.get(f"{API_V1_PREFIX}/consent-policies").status_code == 200
    assert gated.get(PENDING).status_code == 200
    assert complete_signup(gated).status_code == 201
    assert gated.post(f"{AUTH}/refresh").status_code == 200
    assert len(repo.stored()["users"]) == 1


def test_gated_failure_without_gate_shows_static_page_not_spa_redirect(gated):
    response = gated.get(CALLBACK, params={"error": "access_denied"}, follow_redirects=False)
    assert response.status_code == 400 and "location" not in response.headers


def test_gate_error_body_matches_common_error_format(gated):
    response = gated.get(f"{API_V1_PREFIX}/me")
    assert set(json.loads(response.text)) == {"code", "status", "message"}

def test_google_endpoints_are_rate_limited(gclient, gapp, monkeypatch):
    import app.routers.google_auth as google_auth
    monkeypatch.setattr(google_auth, "GOOGLE_IP_MAX_ATTEMPTS", 2)
    assert begin(gclient)  # 기존 AttemptLimiter 규칙: 한도 N 이면 N 번째 시도에서 잠김(test_auth 가입 제한과 같음)
    response = gclient.get(START, follow_redirects=False)
    assert_problem(response, 429, "RATE_LIMITED")
    assert int(response.headers["retry-after"]) > 0
