"""#328 로컬 E2E 전용 가짜 Google IdP (OIDC Authorization Code + PKCE). 실제 Google·실제 Secret 을 쓰지 않는다.

Backend 를 `APP_ENV=local-dev`, `GOOGLE_TEST_IDP_BASE_URL=http://localhost:9101` 로 띄우면 이 서버를 Google 대신 쓴다
(Staging 에서는 이 변수가 있으면 Backend 가 기동을 거부한다).

- GET  /_identity?sub=&email=&name=   다음 로그인에 쓸 계정(시험 스크립트가 지정). email=cancel 이면 사용자가 취소한 것으로 응답
- GET  /authorize                      Google 로그인 화면 대신 즉시 redirect_uri 로 code·state 를 돌려준다
- POST /token                          code 1회용 + PKCE(S256) + client_secret 확인 → RS256 ID Token
- GET  /jwks                           공개키

    python scripts/e2e/google_sso/fake_idp.py --port 9101 --client-secret-file <path>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "e2e-google-sso"
LOCK = threading.Lock()
STATE: dict = {"identity": {"sub": "e2e-sub-default", "email": "allowed.one@example.com", "name": "E2E 사용자"},
               "codes": {}, "token_requests": 0}


def b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-idp"

    def log_message(self, fmt, *args):  # 요청 줄(코드 포함)을 남기지 않는다
        return

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/_identity":
            with LOCK:
                STATE["identity"] = {"sub": query.get("sub", ""), "email": query.get("email", ""),
                                     "name": query.get("name", "E2E 사용자")}
            return self._json(200, {"ok": True})
        if url.path == "/_stats":
            return self._json(200, {"token_requests": STATE["token_requests"], "open_codes": len(STATE["codes"])})
        if url.path == "/jwks":
            pub = KEY.public_key().public_numbers()
            return self._json(200, {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
                                              "n": b64(pub.n), "e": b64(pub.e)}]})
        if url.path == "/authorize":
            redirect_uri = query["redirect_uri"]
            identity = dict(STATE["identity"])
            if identity["email"] == "cancel":
                target = f"{redirect_uri}?{urllib.parse.urlencode({'error': 'access_denied', 'state': query['state']})}"
            else:
                code = secrets.token_urlsafe(24)
                with LOCK:
                    STATE["codes"][code] = {"identity": identity, "nonce": query["nonce"],
                                            "challenge": query["code_challenge"], "client_id": query["client_id"],
                                            "redirect_uri": redirect_uri}
                target = f"{redirect_uri}?{urllib.parse.urlencode({'code': code, 'state': query['state']})}"
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return None
        return self._json(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/token":
            return self._json(404, {"error": "not_found"})
        length = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
        with LOCK:
            STATE["token_requests"] += 1
            entry = STATE["codes"].pop(form.get("code", ""), None)  # 1회용
        verifier = form.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if (entry is None or form.get("client_secret") != self.server.client_secret
                or form.get("client_id") != entry["client_id"] or challenge != entry["challenge"]
                or form.get("redirect_uri") != entry["redirect_uri"]):
            return self._json(400, {"error": "invalid_grant"})
        now = int(time.time())
        identity = entry["identity"]
        claims = {"iss": self.server.issuer, "aud": entry["client_id"], "azp": entry["client_id"],
                  "sub": identity["sub"], "email": identity["email"], "email_verified": True,
                  "name": identity["name"], "nonce": entry["nonce"], "iat": now, "exp": now + 3600}
        token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})
        return self._json(200, {"id_token": token, "access_token": "e2e-access", "token_type": "Bearer",
                                "expires_in": 3600})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9101)
    parser.add_argument("--client-secret-file", required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.client_secret = open(args.client_secret_file, encoding="utf-8").read().strip()
    server.issuer = f"http://localhost:{args.port}"
    print(f"fake idp on {server.issuer}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
