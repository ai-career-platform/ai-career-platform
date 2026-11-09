"""Same-origin API의 쿠키 인증 요청 보호 (OWASP custom-header 방식).

이 값은 비밀 토큰이 아니다. 외부 페이지의 HTML form은 이 헤더를 보낼 수 없고,
외부 Origin의 JS 요청은 CORS preflight에서 차단된다. 인증 경로에 외부 Origin을
허용하는 CORS 설정을 추가하지 않아야 한다.
"""

from typing import Annotated

from fastapi import Header, Request

from app.core.errors import AppError, ErrorCode


def require_csrf_protection(
    request: Request,
    x_csrf_token: Annotated[
        str | None, Header(alias="X-CSRF-TOKEN", description="인증 변경 요청에 필수: 1 (same-origin CSRF 보호)")
    ] = None,
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # same-site도 허용하지 않는다: 다른 서브도메인에서 온 요청일 수 있다.
    fetch_site = request.headers.get("sec-fetch-site")
    if x_csrf_token != "1" or (fetch_site is not None and fetch_site != "same-origin"):
        raise AppError(ErrorCode.FORBIDDEN)
