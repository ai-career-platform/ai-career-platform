"""Problem responses scoped to T16; never serialize input values or exceptions."""

from collections.abc import Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute


class ProfileProblem(Exception):
    def __init__(self, status: int, code: str, title: str):
        self.status = status
        self.code = code
        self.title = title


class ProfileRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except (ProfileProblem, RequestValidationError) as exc:
                validation = isinstance(exc, RequestValidationError)
                status = 422 if validation else exc.status
                code = "VALIDATION_FAILED" if validation else exc.code
                title = "Validation failed" if validation else exc.title
                # Generate locally: a supplied request ID may itself contain PII.
                request_id = "req-" + uuid4().hex
                body = {"type": "https://docs.ai-career.invalid/problems/" + code.lower().replace("_", "-"),
                        "title": title, "status": status, "code": code, "request_id": request_id}
                if validation:
                    body["errors"] = [{"field": "body", "code": "INVALID"}]
                headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
                if status == 401:
                    headers["WWW-Authenticate"] = "Bearer"
                return JSONResponse(body, status_code=status,
                                    media_type="application/problem+json", headers=headers)

        return handler
