"""요청마다 request_id를 정하고 응답 헤더 `X-Request-ID`에 넣는 미들웨어.

- 클라이언트·Nginx가 보낸 `X-Request-ID`가 안전한 형식이면 그대로 씁니다.
- 없거나 형식이 다르면 서버가 새로 만듭니다 (`req-` + 16자리 16진수).
- 오류 응답의 `request_id`, 로그, 감사 기록(audit_events.request_id)이 같은 값을 씁니다.
"""

import re
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def new_request_id() -> str:
    return f"req-{secrets.token_hex(8)}"


class RequestIdMiddleware:
    """순수 ASGI 미들웨어 (BaseHTTPMiddleware는 예외 처리 순서가 꼬일 수 있어 쓰지 않음)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(REQUEST_ID_HEADER.lower().encode())
        value = incoming.decode("latin-1") if incoming else ""
        request_id = value if _SAFE.match(value) else new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                if scope.get("path", "").rstrip("/") == "/api/v1/me":
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_header)
