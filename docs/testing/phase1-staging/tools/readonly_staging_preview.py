"""Read-only local preview of the React app against the real Staging backend (S12 stop-gap).

Until PR #247 is merged and deployed, Staging serves the PoC status page at "/". This serves a locally
built React bundle (same VITE_* flags as poc/staging/frontend/Dockerfile.integrated) and forwards
/api/** unchanged to the Staging nginx gateway. It is NOT a Staging deployment.

Safety: every non-GET/HEAD request to /api is refused here with 403, so login, sign-up, saves and
uploads can never reach the shared Staging DB. Static paths follow the nginx.conf rules
(SPA fallback, /assets/ 404, no-cache index).

  python readonly_staging_preview.py <dist dir> http://<staging-host>:18080 18098
  -> open http://127.0.0.1:18098/   (staging host: docs/STAGING.md "환경")
"""
import http.server
import mimetypes
import pathlib
import sys
import urllib.error
import urllib.request

DIST = pathlib.Path(sys.argv[1]).resolve()
STAGING = sys.argv[2].rstrip('/')
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 18098
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
HOP = {'connection', 'keep-alive', 'transfer-encoding', 'te', 'trailer', 'upgrade', 'proxy-authorization',
       'proxy-authenticate', 'host', 'content-length'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
mimetypes.add_type('application/javascript', '.js')


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (self.command, self.path.split('?')[0]))

    def _send(self, code, data, ctype, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        headers = {'Content-Security-Policy': CSP, 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff'}
        for key, value in {**headers, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _proxy(self):
        if self.command not in ('GET', 'HEAD'):
            return self._send(403, b'read-only preview: non-GET requests to Staging are blocked', 'text/plain')
        req = urllib.request.Request(STAGING + self.path, method=self.command,
                                     headers={k: v for k, v in self.headers.items() if k.lower() not in HOP})
        try:
            resp = OPENER.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            resp = error
        data = resp.read()
        self.send_response(getattr(resp, 'status', None) or resp.code)
        for key, value in resp.headers.items():
            if key.lower() not in HOP:
                self.send_header(key, value)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def _static(self):
        if self.command not in ('GET', 'HEAD'):
            return self._send(405, b'', 'text/plain')
        rel = self.path.split('?')[0].lstrip('/')
        target = (DIST / rel).resolve() if rel else None
        inside = target is not None and DIST in target.parents
        if rel.startswith('assets/') and not (inside and target.is_file()):
            return self._send(404, b'not found', 'text/plain')
        if not (inside and target.is_file()):
            target = DIST / 'index.html'
        extra = {'Cache-Control': 'no-cache'} if target.name == 'index.html' else (
            {'Cache-Control': 'public, max-age=31536000, immutable'} if rel.startswith('assets/') else {})
        self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream', extra)

    def _route(self):
        return self._proxy() if self.path.startswith('/api/') else self._static()

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _route


if __name__ == '__main__':
    print(f'read-only preview on http://127.0.0.1:{PORT}/ -> API {STAGING} (GET only)')
    http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
