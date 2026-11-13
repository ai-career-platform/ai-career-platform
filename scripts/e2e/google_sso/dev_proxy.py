"""#328 로컬 E2E 전용 프록시 — Staging 의 공유 nginx `/career` 스니펫(설계 PR #329 §9)과 프론트 컨테이너 nginx 를 흉내 낸다.

- `/career`            → 301 `/career/`
- `/career/api/*`      → Backend `/api/*` (접두사 제거, Cookie·Set-Cookie·Location 그대로). 게이트는 Backend 미들웨어가 검사
- `/career/*` (그 밖)  → `--gate` 이면 먼저 Backend `GET /api/v1/auth/gate` (nginx auth_request) → 401 이면
                         302 `/career/api/v1/auth/google/start?return_to=<원래 경로>`; 통과하면 dist 정적 파일, 없으면 index.html
- 그 밖                 → 404 (Redmine·/church/ 자리. 이 프록시는 건드리지 않는다)

    python scripts/e2e/google_sso/dev_proxy.py --port 9100 --backend http://127.0.0.1:9102 --dist frontend/dist --gate
"""

from __future__ import annotations

import argparse
import http.client
import mimetypes
import posixpath
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PREFIX = "/career"
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "content-length", "host"}


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 쿼리(code·state)를 남기지 않도록 경로만
        path = urllib.parse.urlsplit(self.path).path
        print(f"proxy {self.command} {path} -> {getattr(self, '_status', '-')}", flush=True)

    def _send(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self._status = status
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _backend(self, method: str, path: str, body: bytes | None, headers: dict[str, str]):
        conn = http.client.HTTPConnection(self.server.backend.hostname, self.server.backend.port, timeout=30)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, response.getheaders(), data

    def _forward_headers(self) -> dict[str, str]:
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-For"] = self.client_address[0]
        return headers

    def _gate_ok(self) -> bool:
        headers = {"Cookie": self.headers.get("Cookie", "")} if self.headers.get("Cookie") else {}
        status, _, _ = self._backend("GET", "/api/v1/auth/gate", None, headers)
        return status == 204

    def _static(self, path: str) -> None:
        rel = posixpath.normpath(path[len(PREFIX):].lstrip("/")) or "index.html"
        if rel.startswith(".."):
            return self._send(400, [], b"bad path")
        target = self.server.dist / rel
        if not target.is_file():
            if rel.startswith("assets/"):
                return self._send(404, [], b"not found")
            target = self.server.dist / "index.html"  # SPA fallback
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return self._send(200, [("Content-Type", ctype), ("Cache-Control", "no-store")], target.read_bytes())

    def _handle(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        if path == PREFIX:
            return self._send(301, [("Location", f"{PREFIX}/")], b"")
        if path.startswith(f"{PREFIX}/api/"):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            backend_path = path[len(PREFIX):] + (f"?{url.query}" if url.query else "")
            status, headers, data = self._backend(self.command, backend_path, body, self._forward_headers())
            return self._send(status, [(k, v) for k, v in headers if k.lower() not in HOP], data)
        if path.startswith(f"{PREFIX}/"):
            if self.server.gate and not self._gate_ok():
                start = f"{PREFIX}/api/v1/auth/google/start?return_to={urllib.parse.quote(self.path, safe='/')}"
                return self._send(302, [("Location", start), ("Cache-Control", "no-store")], b"")
            return self._static(path)
        return self._send(404, [("Content-Type", "text/plain")], b"not the AI Career path")

    do_GET = do_POST = do_HEAD = do_PUT = do_PATCH = do_DELETE = _handle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--backend", default="http://127.0.0.1:9102")
    parser.add_argument("--dist", required=True)
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Proxy)
    server.backend = urllib.parse.urlsplit(args.backend)
    server.dist = Path(args.dist).resolve()
    server.gate = args.gate
    print(f"proxy on http://localhost:{args.port}{PREFIX}/ gate={args.gate}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
