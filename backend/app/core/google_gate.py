"""#328 Google 게이트 미들웨어 (`GOOGLE_GATE_ENFORCED=1` 일 때만 설치).

- `/api/v1` 아래 모든 요청에 서명된 `career_gate` 쿠키를 요구한다. 서명·만료·purpose + Allowlist 를 매번 확인한다.
- Bearer 토큰만 있어도 통과시키지 않는다(1차 게이트는 앱 로그인과 독립). 실패하면 401 `EDGE_AUTH_REQUIRED`.
- 예외는 인증 수행에 필요한 정확한 경로만(`routers.google_auth.GATE_EXEMPT_PATHS`). `/health`·`/version` 은
  `/api/v1` 밖이라 영향이 없다(Auto-CD·컨테이너 헬스체크 유지).
- LAN `:18080` 직통 요청은 브라우저가 `/career/` Path 쿠키를 보내지 않으므로 401 이 된다. 다만 이것은 API 차단일 뿐
  포트의 네트워크 노출 자체를 없애지는 않는다(정적 SPA 셸은 여전히 보임 → #266 에서 loopback 바인딩).
"""

from __future__ import annotations

from http.cookies import CookieError, SimpleCookie

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import API_V1_PREFIX
from app.core.errors import ErrorCode
from app.core.exception_handlers import error_response


def _gate_cookie(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == b"cookie":
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except CookieError:
                return None
            if name in jar:
                return jar[name].value
    return None


def _normalized(path: str) -> str:
    # '//api/v1/me', '/api/v1/auth/google/start/' 같은 '/' 변형으로 보호 범위를 좁히거나 예외를 넓히지 않도록
    # 연속 '/' 를 하나로 줄이고 끝 '/' 를 지운 값으로 비교한다.
    while "//" in path:
        path = path.replace("//", "/")
    return path.rstrip("/") or "/"


class GoogleGateMiddleware:
    def __init__(self, app: ASGIApp, exempt_paths: frozenset[str], cookie_name: str) -> None:
        self.app = app
        self.exempt = frozenset(_normalized(p) for p in exempt_paths)
        self.cookie_name = cookie_name

    def _protected(self, path: str) -> bool:
        normalized = _normalized(path)
        if normalized != API_V1_PREFIX and not normalized.startswith(f"{API_V1_PREFIX}/"):
            return False
        return normalized not in self.exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        runtime = scope["app"].state.google
        if runtime.gate_claims(_gate_cookie(scope, self.cookie_name)) is not None:
            await self.app(scope, receive, send)
            return
        response = error_response(Request(scope), ErrorCode.EDGE_AUTH_REQUIRED, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)
