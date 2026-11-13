"""#328 시험 전용 가짜 Google IdP — 실제 Google·실제 Client Secret 을 쓰지 않는다.

- RSA 키를 시험 안에서 만들고 그 공개키로 ID Token 서명을 검증하게 한다(JWKS 대체).
- authorization code 는 1회용이고 PKCE(S256) verifier 를 확인한다(Google 과 같은 의미).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.google_oauth import GoogleAuthError

CLIENT_ID = "t328-client.apps.googleusercontent.com"
CLIENT_SECRET = "t328-synthetic-client-secret"
ISSUER = "https://accounts.google.com"


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class FakeGoogle:
    key: Any = field(default_factory=_rsa_key)
    kid: str = "t328-kid"
    codes: dict[str, dict] = field(default_factory=dict)
    exchanges: list[dict] = field(default_factory=list)

    # ---- AuthorizationURL → code
    def authorize(self, authorization_url: str, *, sub: str = "google-sub-1", email: str = "seeker@gmail.com",
                  name: str | None = "김구글", signing_key: Any = None, algorithm: str = "RS256",
                  **claims: Any) -> tuple[str, str]:
        """사용자가 Google 에서 로그인했다고 치고 (code, state) 를 돌려준다. claims 로 ID Token 을 바꾼다."""
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(authorization_url).query)
        now = int(time.time())
        payload = {
            "iss": ISSUER, "aud": CLIENT_ID, "azp": CLIENT_ID, "sub": sub, "email": email,
            "email_verified": True, "nonce": query["nonce"][0], "iat": now, "exp": now + 3600,
        }
        if name is not None:
            payload["name"] = name
        payload.update(claims)
        payload = {k: v for k, v in payload.items() if v is not None}
        key = signing_key if signing_key is not None else self.key
        token = jwt.encode(payload, key, algorithm=algorithm, headers={"kid": self.kid})
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"id_token": token, "challenge": query["code_challenge"][0],
                            "redirect_uri": query["redirect_uri"][0]}
        return code, query["state"][0]

    # ---- GoogleOAuthClient 에 주입
    def transport(self, url: str, form: dict[str, str]) -> dict[str, Any]:
        self.exchanges.append({k: v for k, v in form.items() if k != "client_secret"})
        entry = self.codes.pop(form.get("code", ""), None)  # 1회용: 두 번째 교환은 invalid_grant
        if entry is None or form.get("client_secret") != CLIENT_SECRET or form.get("client_id") != CLIENT_ID:
            raise GoogleAuthError("token_endpoint_http_400")
        verifier = form.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if challenge != entry["challenge"] or form.get("redirect_uri") != entry["redirect_uri"]:
            raise GoogleAuthError("token_endpoint_http_400")
        return {"id_token": entry["id_token"], "access_token": "t328-access", "token_type": "Bearer"}

    def key_resolver(self, token: str):
        if jwt.get_unverified_header(token).get("kid") != self.kid:
            raise GoogleAuthError("unknown_kid")
        return self.key.public_key()
