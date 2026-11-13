"""#328 Google OAuth(OIDC) 로그인 부품 — 설계: docs/security/GOOGLE_SSO_AUTO_SIGNUP_DESIGN.md (PR #329).

- Authorization Code + PKCE(S256) + state + nonce. Code 교환은 서버에서만, Client Secret 은 서버 파일에서만 읽는다.
- ID Token 은 Google JWKS 로 RS256 서명을 검증하고 iss·aud·azp·exp·iat·nonce·email_verified 를 확인한다.
- 이메일 Allowlist 는 서버 파일의 정확 일치(소문자 비교)만. 와일드카드·도메인 규칙 없음. 빈 파일 = 전원 거부.
- 쿠키 값(tx·pending·gate)은 GOOGLE_COOKIE_SECRET 으로 HS256 서명하고 purpose 클레임으로 용도를 묶는다.
- 1회 사용(state·pending)은 서버 메모리 `OneTimeUse` 로 강제한다. Backend 는 단일 uvicorn 프로세스로 실행된다
  (poc/staging/backend/Dockerfile* CMD, --workers 없음). 여러 프로세스로 늘리면 이 저장소를 공유 저장소로 바꿔야 한다.
  Google 의 authorization code 자체도 1회용이며(RFC 6749 §4.1.2), 계정 생성은 DB UNIQUE 가 최종 방어선이다.
- 이 모듈은 Secret·code·토큰·이메일 원문을 로그에 남기지 않는다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from hmac import compare_digest
from typing import Any

import jwt

from app.core.auth_config import GoogleSettings

logger = logging.getLogger(__name__)

SCOPE = "openid email profile"
TX_TTL_SECONDS = 600
PENDING_TTL_SECONDS = 600
GATE_TTL_SECONDS = 12 * 3600
ID_TOKEN_MAX_AGE_SECONDS = 600
CLOCK_LEEWAY_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10
RETURN_TO_MAX_LENGTH = 512

PURPOSE_TX = "google_tx"
PURPOSE_PENDING = "google_signup"
PURPOSE_GATE = "google_gate"
_COOKIE_ISSUER = "ai-career-platform/google"


class GoogleAuthError(Exception):
    """Google 인증 실패. 메시지는 내부 분류용 짧은 문자열이며 비밀값·이메일을 넣지 않는다."""


def sub_hash(sub: str) -> str:
    """로그용 식별자. sub 원문 대신 해시 앞 12자만 남긴다."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- PKCE / random
def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]  # RFC 7636: 43~128자
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------- Allowlist
class EmailAllowlist:
    """서버 파일의 정확 일치 목록. 파일이 바뀌면(mtime·크기) 다시 읽는다. 읽기 실패 = 전원 거부."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._emails: frozenset[str] = frozenset()

    @staticmethod
    def _parse(text: str) -> frozenset[str]:
        emails = set()
        for line in text.splitlines():
            value = line.strip().lower()
            if not value or value.startswith("#"):
                continue
            # 형식이 이상한 줄(공백·와일드카드·@ 개수 오류)은 어떤 이메일과도 일치하지 않게 버린다.
            if value.count("@") == 1 and not any(c.isspace() or c in "*?" for c in value):
                emails.add(value)
        return frozenset(emails)

    def _current(self) -> frozenset[str]:
        try:
            stat = os.stat(self._path)
        except OSError:
            logger.warning("google allowlist file is not readable; denying all")
            return frozenset()
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if stamp != self._stamp:
                try:
                    with open(self._path, encoding="utf-8") as handle:
                        self._emails = self._parse(handle.read())
                except (OSError, UnicodeDecodeError):
                    logger.warning("google allowlist file could not be read; denying all")
                    self._emails = frozenset()
                self._stamp = stamp
            return self._emails

    def contains(self, email: str) -> bool:
        return email.strip().lower() in self._current()


# ---------------------------------------------------------------- one-time use
class OneTimeUse:
    """jti 1회 사용 기록(메모리, TTL). claim 이 True 인 요청만 처리를 계속한다."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._used: dict[str, float] = {}

    def claim(self, jti: str, expires_at: float) -> bool:
        now = self._clock()
        with self._lock:
            for key in [k for k, exp in self._used.items() if exp <= now]:
                del self._used[key]
            if jti in self._used:
                return False
            self._used[jti] = max(expires_at, now) + CLOCK_LEEWAY_SECONDS
            return True

    def is_used(self, jti: str) -> bool:
        with self._lock:
            expires = self._used.get(jti)
            return expires is not None and expires > self._clock()

    def release(self, jti: str) -> None:
        """처리 전에 실패(입력 오류 등)해서 같은 값을 다시 써도 되는 경우에만 호출한다."""
        with self._lock:
            self._used.pop(jti, None)


# ---------------------------------------------------------------- signed cookie values
class CookieSigner:
    def __init__(self, secret: str, clock: Callable[[], float] = time.time) -> None:
        self._secret = secret
        self._clock = clock

    def sign(self, purpose: str, ttl: int, **claims: Any) -> tuple[str, dict[str, Any]]:
        now = int(self._clock())
        payload = {**claims, "purpose": purpose, "iss": _COOKIE_ISSUER, "iat": now, "exp": now + ttl,
                   "jti": secrets.token_urlsafe(16)}
        return jwt.encode(payload, self._secret, algorithm="HS256"), payload

    def verify(self, purpose: str, token: str | None) -> dict[str, Any] | None:
        if not token or len(token) > 4096:
            return None
        try:
            payload = jwt.decode(
                token, self._secret, algorithms=["HS256"], issuer=_COOKIE_ISSUER,
                options={"require": ["exp", "iat", "jti", "purpose"]},
                leeway=0,
            )
        except jwt.PyJWTError:
            return None
        if payload.get("purpose") != purpose or payload["exp"] < self._clock():
            return None
        return payload


# ---------------------------------------------------------------- return_to
def safe_return_to(value: str | None, prefix: str) -> str:
    """같은 사이트의 SPA 경로만 허용한다(Open Redirect 방지). 아니면 SPA 홈."""
    home = f"{prefix}/"
    if not value or len(value) > RETURN_TO_MAX_LENGTH:
        return home
    if any(ord(c) < 0x20 or c in "\\@" for c in value) or value.startswith("//"):
        return home
    if not value.startswith(home):
        return home
    decoded = urllib.parse.unquote(value)
    path = urllib.parse.urlsplit(decoded).path
    if decoded.startswith("//") or "\\" in decoded or any(seg in {".", ".."} for seg in path.split("/")):
        return home
    if path.startswith(f"{prefix}/api/") or path == f"{prefix}/api":
        return home
    return value


# ---------------------------------------------------------------- Google client
@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str  # 소문자, 앞뒤 공백 제거
    name: str


TokenTransport = Callable[[str, dict[str, str]], dict[str, Any]]
KeyResolver = Callable[[str], Any]


def _post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(form).encode("ascii")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310 (https 고정)
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 400 invalid_grant(재사용·만료 code) 등. 응답 본문은 로그에 남기지 않는다.
        raise GoogleAuthError(f"token_endpoint_http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise GoogleAuthError("token_endpoint_unavailable") from None


class GoogleOAuthClient:
    def __init__(
        self,
        settings: GoogleSettings,
        transport: TokenTransport | None = None,
        key_resolver: KeyResolver | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._transport = transport or _post_form
        self._clock = clock
        if key_resolver is None:
            jwks = jwt.PyJWKClient(settings.jwks_uri, cache_keys=True, lifespan=3600, timeout=HTTP_TIMEOUT_SECONDS)
            key_resolver = lambda token: jwks.get_signing_key_from_jwt(token).key  # noqa: E731
        self._key_resolver = key_resolver

    def authorization_url(self, state: str, nonce: str, code_challenge: str, select_account: bool = False) -> str:
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if select_account:
            params["prompt"] = "select_account"
        return f"{self.settings.authorization_endpoint}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> str:
        if not code or len(code) > 2048:
            raise GoogleAuthError("code_invalid")
        body = self._transport(self.settings.token_endpoint, {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "redirect_uri": self.settings.redirect_uri,
        })
        id_token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise GoogleAuthError("id_token_missing")
        return id_token

    def verify_id_token(self, id_token: str, nonce: str) -> GoogleIdentity:
        try:
            key = self._key_resolver(id_token)
            claims = jwt.decode(
                id_token, key, algorithms=["RS256"],
                audience=self.settings.client_id, issuer=list(self.settings.issuers),
                leeway=CLOCK_LEEWAY_SECONDS,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
        except (jwt.PyJWTError, GoogleAuthError, ValueError, KeyError):
            raise GoogleAuthError("id_token_invalid") from None
        now = self._clock()
        if not isinstance(claims.get("iat"), (int, float)) or now - claims["iat"] > ID_TOKEN_MAX_AGE_SECONDS:
            raise GoogleAuthError("id_token_too_old")
        if "azp" in claims and claims["azp"] != self.settings.client_id:
            raise GoogleAuthError("id_token_azp")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not compare_digest(token_nonce, nonce):
            raise GoogleAuthError("id_token_nonce")
        if claims.get("email_verified") is not True:
            raise GoogleAuthError("email_not_verified")
        sub, email = claims.get("sub"), claims.get("email")
        if not isinstance(sub, str) or not sub or len(sub) > 255:
            raise GoogleAuthError("id_token_sub")
        if not isinstance(email, str) or email.strip().count("@") != 1 or len(email.strip()) > 254:
            raise GoogleAuthError("id_token_email")
        email = email.strip().lower()
        name = claims.get("name")
        display = name.strip() if isinstance(name, str) and name.strip() else email.split("@", 1)[0]
        return GoogleIdentity(sub=sub, email=email, name=display[:100])


# ---------------------------------------------------------------- runtime bundle (app.state.google)
@dataclass
class GoogleRuntime:
    settings: GoogleSettings
    client: GoogleOAuthClient
    allowlist: EmailAllowlist
    signer: CookieSigner
    once: OneTimeUse

    @classmethod
    def build(cls, settings: GoogleSettings) -> "GoogleRuntime":
        return cls(
            settings=settings,
            client=GoogleOAuthClient(settings),
            allowlist=EmailAllowlist(settings.allowlist_file),
            signer=CookieSigner(settings.cookie_secret),
            once=OneTimeUse(),
        )

    def gate_claims(self, token: str | None) -> dict[str, Any] | None:
        """게이트 쿠키 검증: 서명·만료·purpose + Allowlist 재확인(제거 즉시 차단)."""
        claims = self.signer.verify(PURPOSE_GATE, token)
        if claims is None or not isinstance(claims.get("email"), str) or not isinstance(claims.get("sub"), str):
            return None
        if not self.allowlist.contains(claims["email"]):
            return None
        return claims
