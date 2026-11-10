"""T86 로그 개인정보 — 토큰·비밀번호·이메일·조회 조건 사용자 ID 가 응답·애플리케이션 로그에 남지 않는지 (실패 시나리오 8),
그리고 Finding F-1(접근 로그의 쿼리 문자열) 재현.

- 애플리케이션 로그: 앱 로거(app.*, uvicorn.error 등) — 여기서는 원문이 없어야 합니다(PASS 기준).
- 접근 로그: uvicorn.access / Nginx combined — 요청 줄 전체(쿼리 포함)를 남깁니다. **현재 동작을 재현해 기록**하고,
  개선안(쿼리 제거 필터)이 동작함을 함께 보입니다. 운영 Uvicorn·Nginx 설정은 바꾸지 않습니다.
"""
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest
import uvicorn

from app.main import create_app
from tests.conftest import CONSENTS, PASSWORD, bearer, signup

SYNTHETIC_ACTOR = uuid.UUID("0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
NGINX = Path(__file__).resolve().parents[3] / "poc/staging/frontend/nginx.conf"
DOCKERFILES = sorted((Path(__file__).resolve().parents[3] / "poc/staging/backend").glob("Dockerfile*"))


def server_logs(caplog) -> str:
    """httpx(테스트 클라이언트)와 uvicorn.access(접근 로그)를 뺀 서버 애플리케이션 로그."""
    return " | ".join(f"{r.name}:{r.getMessage()}:{r.exc_text or ''}" for r in caplog.records
                      if not r.name.startswith(("httpx", "uvicorn.access")))


def test_auth_flow_never_logs_credentials_tokens_or_email(client, caplog):
    email = "t86-log-user@example.com"
    with caplog.at_level(logging.DEBUG):
        signed = signup(client, email=email)
        token = signed.json()["access_token"]
        refresh = client.cookies.get("refresh_token")
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-" + PASSWORD})
        client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        client.post("/api/v1/auth/refresh")
        client.get("/api/v1/me", headers=bearer(token))
        client.get("/api/v1/me", headers=bearer(token + "x"))
        client.get("/api/v1/admin/audit-events", headers=bearer(token),
                   params={"from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z", "actor_user_id": str(SYNTHETIC_ACTOR)})
    logs = server_logs(caplog)
    assert any(r.name.startswith("app") for r in caplog.records), "server logs were captured"
    for secret in (PASSWORD, token, refresh, email, str(SYNTHETIC_ACTOR)):
        assert secret and secret not in logs


@pytest.mark.parametrize("body", [
    {"email": "not-an-email", "password": PASSWORD},
    {"email": "t86@example.com", "password": PASSWORD, "extra": PASSWORD},
    {"email": "t86@example.com", "password": ["array", PASSWORD]},
])
def test_validation_errors_do_not_echo_password(client, body):
    response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code in (401, 422)
    assert PASSWORD not in response.text


def test_signup_response_does_not_echo_password_or_consents_secrets(client):
    response = signup(client, email="t86-echo@example.com")
    assert PASSWORD not in response.text and "password" not in response.text.lower()
    assert len(CONSENTS) >= 1


# ---------------------------------------------------------------- Finding F-1: access log query string
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_uvicorn(monkeypatch):
    """실제 uvicorn 서버(기본 access_log=True)를 루프백 임시 포트로 띄웁니다. DB 없음."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "t15-test-secret-0123456789-abcdefghij")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from app.core.config import get_settings
    get_settings.cache_clear()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_config=None,
                                           access_log=True, lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    get_settings.cache_clear()


def _get(url: str) -> int:
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


class StripQueryFromAccessLog(logging.Filter):
    """개선안 프로토타입: uvicorn.access 레코드의 경로에서 쿼리 문자열을 지웁니다 (운영 미적용)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            args[2] = args[2].split("?", 1)[0] + ("?[query redacted]" if "?" in args[2] else "")
            record.args = tuple(args)
        return True


def test_finding_f1_uvicorn_access_log_records_the_query_string(live_uvicorn, caplog):
    query = f"from=2026-11-01T00:00:00Z&to=2026-11-02T00:00:00Z&actor_user_id={SYNTHETIC_ACTOR}"
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        assert _get(f"{live_uvicorn}/api/v1/admin/audit-events?{query}") == 401
        time.sleep(0.2)
    access = [r.getMessage() for r in caplog.records if r.name == "uvicorn.access"]
    assert access, "uvicorn default access log is on"
    # 현재 동작(Finding F-1): 인증 실패(401) 요청이어도 원문 사용자 ID 가 접근 로그에 남는다.
    assert any(str(SYNTHETIC_ACTOR) in line for line in access), access
    assert str(SYNTHETIC_ACTOR) not in server_logs(caplog), "application logs stay clean"


def test_finding_f1_mitigation_prototype_removes_the_query(live_uvicorn, caplog):
    access_logger = logging.getLogger("uvicorn.access")
    shim = StripQueryFromAccessLog()
    access_logger.addFilter(shim)
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            _get(f"{live_uvicorn}/api/v1/admin/audit-events?actor_user_id={SYNTHETIC_ACTOR}")
            time.sleep(0.2)
    finally:
        access_logger.removeFilter(shim)
    access = [r.getMessage() for r in caplog.records if r.name == "uvicorn.access"]
    assert access and all(str(SYNTHETIC_ACTOR) not in line for line in access), access
    assert any("/api/v1/admin/audit-events?[query redacted]" in line for line in access)


def test_finding_f1_deployment_config_still_logs_full_request_lines():
    """설정 확인(정적): Dockerfile 의 uvicorn 실행에 --no-access-log/log-config 가 없고, Nginx 는 기본 combined 형식."""
    assert DOCKERFILES
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")
        if "uvicorn" in text:
            assert "--no-access-log" not in text and "--log-config" not in text, dockerfile.name
    nginx = NGINX.read_text(encoding="utf-8")
    assert "log_format" not in nginx and "access_log off" not in nginx
