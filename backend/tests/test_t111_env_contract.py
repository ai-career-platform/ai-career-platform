"""T111 환경 계약·Secret 비노출·회전 시뮬레이션 시험.

- 실제 Secret 은 쓰지 않는다. 모든 키는 시험 안에서 만든 합성 값이다.
- 회전 시뮬레이션은 메모리 저장소 + TestClient 로만 수행한다(Staging·운영 미접속).
"""

import logging
import pathlib
import re
import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import env_contract
from app.core.config import API_V1_PREFIX, DatabaseSettings, Settings, get_settings
from app.core.auth_config import AuthSettings
from app.core.security import TokenInvalid, decode_access_token, issue_access_token
from app.main import create_app
from tests.conftest import CONSENTS, PASSWORD, bearer, build_probe_router
from tests.fakes import MemoryAuthRepository, override_auth_repository

REPO = pathlib.Path(__file__).resolve().parents[2]
APP_DIR = REPO / "backend" / "app"
ENV_READ = re.compile(
    r"""(?:environ\.get|getenv|environ\[|env_int|env_bool)\(?\s*["']([A-Z][A-Z0-9_]+)["']""")

KEY_A = "t111-synthetic-key-A-" + "a" * 24
KEY_B = "t111-synthetic-key-B-" + "b" * 24
SENTINEL = "t111-SENTINEL-must-not-leak-0123456789"


def staging_env(**overrides) -> dict[str, str]:
    env = {
        "APP_ENV": "staging",
        "APP_VERSION": "abc1234",
        "DATABASE_URL": "postgresql://app_user:s3cr3tvalue@db.internal:5432/career",
        "JWT_SECRET": "z" * 40,
    }
    env.update(overrides)
    return env


# ------------------------------------------------------------------ 계약과 코드 동기화
def test_contract_covers_every_variable_the_backend_reads():
    read = set()
    for path in APP_DIR.rglob("*.py"):
        read.update(ENV_READ.findall(path.read_text(encoding="utf-8")))
    assert read, "환경변수 읽기 패턴을 하나도 찾지 못함(정규식 점검 필요)"
    assert read - set(env_contract.BY_NAME) == set(), "코드가 읽지만 계약에 없는 변수"
    assert set(env_contract.BY_NAME) - read == set(), "계약에 있지만 코드가 읽지 않는 변수"


def test_root_env_example_lists_every_contract_variable_without_secrets():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in text.splitlines() if re.match(r"^[A-Z][A-Z0-9_]*=", line))
    missing = set(env_contract.BY_NAME) - set(values)
    assert missing == set(), f".env.example 에 없는 변수: {sorted(missing)}"
    for var in env_contract.CONTRACT:
        if var.secret:
            assert values[var.name] == "", f"{var.name} 예제 값은 비어 있어야 함"
    for name, value in values.items():
        assert not re.search(r"[A-Za-z0-9_\-]{32,}", value), f"{name} 예제에 긴 무작위 값처럼 보이는 문자열"


def test_matrix_document_matches_contract():
    doc = (REPO / "docs" / "ops" / "ENVIRONMENT_MATRIX.md").read_text(encoding="utf-8")
    for var in env_contract.CONTRACT:
        assert f"`{var.name}`" in doc, f"매트릭스 문서에 {var.name} 없음"


# ------------------------------------------------------------------ 필수값·형식 검사
def test_valid_staging_environment_has_no_findings():
    assert env_contract.check_environment("staging", staging_env()) == []


def test_local_and_ci_need_nothing():
    assert env_contract.check_environment("local", {}) == []
    assert env_contract.check_environment("ci", {}) == []


def test_staging_reports_each_missing_required_variable():
    found = {(f.name, f.problem) for f in env_contract.check_environment("staging", {})}
    assert found == {("APP_ENV", "missing"), ("APP_VERSION", "missing"),
                     ("DATABASE_URL", "missing"), ("JWT_SECRET", "missing")}


@pytest.mark.parametrize(("name", "value", "problem"), [
    ("JWT_SECRET", "short-secret", "weak"),
    ("JWT_SECRET", "please-change-me-" + "x" * 30, "placeholder"),
    ("DATABASE_URL", "mysql://u:p@h/db", "invalid"),
    ("DATABASE_URL", "postgresql://u:p%zz@h/db", "invalid"),
    ("DATABASE_URL", "postgresql://user:pw@example.internal/db", "placeholder"),
    ("APP_ENV", "production", "forbidden_in_target"),
    ("AUTH_COOKIE_SECURE", "false", "forbidden_in_target"),
    ("AUTH_COOKIE_SECURE", "maybe", "invalid"),
    ("DB_POOL_SIZE", "0", "invalid"),
    ("ACCESS_TOKEN_TTL_SECONDS", "86400", "invalid"),
    ("JOB_SEARCH_ADVANCED", "ture", "invalid"),
    ("BEHAVIOR_EVENTS_RATE_LIMIT", "60", "invalid"),
    ("PASSWORD_RESET_LINK_BASE", "http://evil.test/reset", "forbidden_in_target"),
    ("PASSWORD_RESET_LINK_BASE", "//evil.test/reset", "forbidden_in_target"),
])
def test_staging_rejects_bad_values(name, value, problem):
    findings = env_contract.check_environment("staging", staging_env(**{name: value}))
    assert [(f.name, f.problem) for f in findings] == [(name, problem)]


def test_relative_and_https_reset_base_are_allowed():
    for value in ("/password-reset", "https://career.example.org/password-reset"):
        assert env_contract.check_environment("staging", staging_env(PASSWORD_RESET_LINK_BASE=value)) == []


def test_contract_bounds_match_code_parsers(monkeypatch):
    """계약 범위와 실제 파서 범위가 같은지 경계값으로 확인한다."""
    monkeypatch.setenv("DB_POOL_SIZE", "100")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert DatabaseSettings.from_env().pool_size == 100
    monkeypatch.setenv("DB_POOL_SIZE", "101")
    with pytest.raises(ValueError):
        DatabaseSettings.from_env()
    assert env_contract.check_environment("ci", {"DB_POOL_SIZE": "101"})[0].problem == "invalid"
    monkeypatch.setenv("ACCESS_TOKEN_TTL_SECONDS", "3601")
    monkeypatch.setenv("JWT_SECRET", KEY_A)
    with pytest.raises(ValueError):
        AuthSettings.from_env("test")
    assert env_contract.check_environment("ci", {"ACCESS_TOKEN_TTL_SECONDS": "3601"})[0].problem == "invalid"


def test_app_refuses_to_start_outside_local_without_jwt_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="JWT_SECRET is required"):
            create_app()
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------------ 비밀 비노출
def test_findings_and_cli_never_print_values(monkeypatch, capsys):
    env = staging_env(JWT_SECRET=SENTINEL[:20], DATABASE_URL=f"mysql://u:{SENTINEL}@h/db")
    findings = env_contract.check_environment("staging", env)
    assert findings and all(SENTINEL[:20] not in str(f) for f in findings)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert env_contract.main(["--target", "staging"]) == 1
    out = capsys.readouterr().out
    assert SENTINEL not in out and SENTINEL[:20] not in out
    assert "DATABASE_URL: invalid" in out and "JWT_SECRET: weak" in out


def test_settings_repr_and_errors_hide_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{SENTINEL}@h/db")
    monkeypatch.setenv("JWT_SECRET", SENTINEL)
    settings = Settings.from_env()
    auth = AuthSettings.from_env("test")
    assert SENTINEL not in repr(settings) and SENTINEL not in repr(auth)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{SENTINEL}%zz@h/db")
    with pytest.raises(ValueError) as caught:
        DatabaseSettings.from_env()
    assert SENTINEL not in str(caught.value)


def test_startup_logs_do_not_contain_secrets(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", SENTINEL)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    caplog.set_level(logging.DEBUG)
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
            assert SENTINEL not in client.get("/version").text
    finally:
        get_settings.cache_clear()
    assert SENTINEL not in caplog.text


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git 을 사용할 수 없는 환경")
    return out.splitlines()


def test_no_real_env_or_key_files_are_tracked():
    files = _tracked_files()
    allowed = {".env.example", ".env.mock"}
    env_files = [f for f in files if re.search(r"(^|/)\.env(\.|$)", f) and f.rsplit("/", 1)[-1] not in allowed]
    assert env_files == []
    key_files = [f for f in files if re.search(r"\.(pem|key|p12|pfx)$|(^|/)id_(rsa|ed25519)$", f)]
    assert key_files == []


def test_gitignore_blocks_env_files():
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines and ".env.*" in lines and "!.env.example" in lines


def test_tracked_env_examples_hold_no_secret_values():
    # 계약에 있는 변수는 계약의 secret 표시를, 없는 변수는 이름(SECRET/PASSWORD/TOKEN/KEY)을 기준으로 본다
    secretish = re.compile(r"^(?P<k>[A-Z0-9_]*(SECRET|PASSWORD|TOKEN|KEY)[A-Z0-9_]*)=(?P<v>.*)$")
    for rel in [f for f in _tracked_files() if f.endswith((".env.example", ".env.mock"))]:
        for line in (REPO / rel).read_text(encoding="utf-8").splitlines():
            # 이름과 무관하게, 자격정보가 박힌 URL(scheme://user:pass@host)은 자리표시자만 허용
            embedded = re.search(r"://[^/\s:@]+:([^@\s]+)@", line)
            assert not embedded or env_contract._looks_placeholder(embedded[1]), f"{rel}: URL 에 자격정보"
            match = secretish.match(line.strip())
            if not match:
                continue
            known = env_contract.BY_NAME.get(match["k"])
            if (known is not None and not known.secret) or match["k"].endswith("_PATH"):
                continue
            value = match["v"].strip()
            assert value == "" or env_contract._looks_placeholder(value) or value.upper().startswith("CHANGE"), \
                f"{rel}: {match['k']} 에 자리표시자가 아닌 값"


# ------------------------------------------------------------------ 회전 시뮬레이션 (합성 키 A → B → A)
def test_token_signed_with_old_key_is_rejected_after_rotation():
    user, session = uuid.uuid4(), uuid.uuid4()
    token_a = issue_access_token(KEY_A, user, session, ["user"], 900)
    assert decode_access_token(KEY_A, token_a).user_id == user
    with pytest.raises(TokenInvalid):
        decode_access_token(KEY_B, token_a)


def _app(monkeypatch, repo, owners, key):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", key)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.include_router(build_probe_router(owners), prefix=API_V1_PREFIX)
    override_auth_repository(application, repo)
    return application


def test_rotation_a_to_b_and_rollback_keeps_sessions_via_refresh(monkeypatch):
    """회전 시 access token 은 즉시 무효(401), refresh 로 새 키 토큰을 받아 재로그인 없이 복구된다.

    refresh token 은 서버에 해시(SHA-256)로만 저장되며 JWT_SECRET 과 무관 — 세션은 회전에 살아남는다.
    """
    repo, owners = MemoryAuthRepository(), {}
    doc = uuid.uuid4()
    headers = {"X-CSRF-TOKEN": "1"}
    try:
        with TestClient(_app(monkeypatch, repo, owners, KEY_A), base_url="https://testserver", headers=headers) as a:
            signed = a.post(f"{API_V1_PREFIX}/auth/signup", json={
                "email": "rotate@example.com", "password": PASSWORD, "display_name": "회전", "consents": CONSENTS})
            assert signed.status_code == 201
            token_a = signed.json()["access_token"]
            owners[doc] = decode_access_token(KEY_A, token_a).user_id
            assert a.get(f"{API_V1_PREFIX}/_probe/documents/{doc}", headers=bearer(token_a)).status_code == 200
            refresh = a.cookies.get("refresh_token")

        # 1) A → B 전환: 옛 access token 거부(fail-closed)
        with TestClient(_app(monkeypatch, repo, owners, KEY_B), base_url="https://testserver", headers=headers) as b:
            assert b.get(f"{API_V1_PREFIX}/_probe/documents/{doc}", headers=bearer(token_a)).status_code == 401
            # 2) refresh 로 B 서명 토큰 발급 → 재로그인 없이 복구
            b.cookies.set("refresh_token", refresh, domain="testserver.local", path=f"{API_V1_PREFIX}/auth")
            renewed = b.post(f"{API_V1_PREFIX}/auth/refresh")
            assert renewed.status_code == 200
            token_b = renewed.json()["access_token"]
            assert b.get(f"{API_V1_PREFIX}/_probe/documents/{doc}", headers=bearer(token_b)).status_code == 200
            refresh = b.cookies.get("refresh_token")

        # 3) 실패 시 복귀(B → A): B 토큰은 거부, refresh 는 계속 유효
        with TestClient(_app(monkeypatch, repo, owners, KEY_A), base_url="https://testserver", headers=headers) as back:
            assert back.get(f"{API_V1_PREFIX}/_probe/documents/{doc}", headers=bearer(token_b)).status_code == 401
            back.cookies.set("refresh_token", refresh, domain="testserver.local", path=f"{API_V1_PREFIX}/auth")
            assert back.post(f"{API_V1_PREFIX}/auth/refresh").status_code == 200
    finally:
        get_settings.cache_clear()


def test_rotation_with_weak_new_key_fails_before_serving(monkeypatch):
    """새 키가 32자 미만이면 기동 단계에서 막힌다 → 기존 컨테이너를 유지한 채 중단."""
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("JWT_SECRET", "too-short")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValueError, match="at least 32"):
            create_app()
    finally:
        get_settings.cache_clear()
    assert env_contract.check_environment("staging", staging_env(JWT_SECRET="too-short"))[0].problem == "weak"


def test_rotation_invalidates_signed_list_cursors():
    """JWT_SECRET 에서 파생한 목록 cursor 서명키도 바뀐다 → 회전 전 cursor 는 400 INVALID_CURSOR (Runbook §1)."""
    from app.core.errors import AppError, ErrorCode
    from app.core.security import derive_key
    from app.routers.catalog import CURSOR_KEY_PURPOSE
    from app.services.catalog import CatalogService

    old = CatalogService(None, cursor_key=derive_key(KEY_A, CURSOR_KEY_PURPOSE))
    new = CatalogService(None, cursor_key=derive_key(KEY_B, CURSOR_KEY_PURPOSE))
    role = uuid.uuid4()
    token = old._encode_cursor("백엔드", "백엔드 개발자", role)
    assert old._parse_cursor(token, "백엔드")[1] == role
    with pytest.raises(AppError) as caught:
        new._parse_cursor(token, "백엔드")
    assert caught.value.code == ErrorCode.INVALID_CURSOR
