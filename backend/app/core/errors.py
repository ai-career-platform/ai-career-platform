"""공통 에러 코드와 애플리케이션 예외.

서비스·라우터는 HTTPException 대신 아래 예외를 raise 합니다.
글로벌 핸들러(app/core/exception_handlers.py)가 ProblemDetail 응답으로 바꿉니다.

    from app.core.errors import ConflictError, ErrorCode
    raise ConflictError(ErrorCode.EMAIL_TAKEN)
"""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """docs/API_CONTRACT.md §1.4의 code 목록. 새 코드는 계약서와 함께 추가합니다."""

    # 400
    BAD_REQUEST = "BAD_REQUEST"
    NO_USER_SKILLS = "NO_USER_SKILLS"
    NOT_A_TARGET_ROLE = "NOT_A_TARGET_ROLE"
    INVALID_CURSOR = "INVALID_CURSOR"
    INVALID_RESET_TOKEN = "INVALID_RESET_TOKEN"
    MALFORMED_JSON = "MALFORMED_JSON"
    # 401
    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    # 403
    FORBIDDEN = "FORBIDDEN"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    # 404
    NOT_FOUND = "NOT_FOUND"
    # 405
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    # 409
    CONFLICT = "CONFLICT"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    DELETION_ALREADY_REQUESTED = "DELETION_ALREADY_REQUESTED"
    DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"
    APPROVAL_CLOSED = "APPROVAL_CLOSED"
    LAST_ADMIN = "LAST_ADMIN"
    # 413 / 415
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    # 422
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DUPLICATE_SKILL = "DUPLICATE_SKILL"
    # 429
    RATE_LIMITED = "RATE_LIMITED"
    # 500 / 503 / 504
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    DEPENDENCY_TIMEOUT = "DEPENDENCY_TIMEOUT"


# 코드별 기본 제목. detail은 상황 설명이 필요할 때만 예외에서 넘깁니다.
DEFAULT_TITLES: dict[ErrorCode, str] = {
    ErrorCode.BAD_REQUEST: "Bad request",
    ErrorCode.NO_USER_SKILLS: "No skills registered",
    ErrorCode.NOT_A_TARGET_ROLE: "Not one of your target roles",
    ErrorCode.INVALID_CURSOR: "Invalid cursor",
    ErrorCode.INVALID_RESET_TOKEN: "Reset link is invalid or expired",
    ErrorCode.MALFORMED_JSON: "Malformed JSON body",
    ErrorCode.UNAUTHENTICATED: "Authentication required",
    ErrorCode.TOKEN_EXPIRED: "Access token expired",
    ErrorCode.INVALID_CREDENTIALS: "Invalid credentials",
    ErrorCode.FORBIDDEN: "Forbidden",
    ErrorCode.CONSENT_REQUIRED: "Consent required",
    ErrorCode.NOT_FOUND: "Not found",
    ErrorCode.METHOD_NOT_ALLOWED: "Method not allowed",
    ErrorCode.CONFLICT: "Conflict",
    ErrorCode.EMAIL_TAKEN: "Email already registered",
    ErrorCode.DELETION_ALREADY_REQUESTED: "Deletion already requested",
    ErrorCode.DOCUMENT_NOT_READY: "Document is not ready",
    ErrorCode.APPROVAL_CLOSED: "Approval already closed",
    ErrorCode.LAST_ADMIN: "At least one admin is required",
    ErrorCode.FILE_TOO_LARGE: "File too large",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "Unsupported file type",
    ErrorCode.VALIDATION_FAILED: "Validation failed",
    ErrorCode.DUPLICATE_SKILL: "Duplicate skill",
    ErrorCode.RATE_LIMITED: "Too many requests",
    ErrorCode.INTERNAL_ERROR: "Internal server error",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "Dependency unavailable",
    ErrorCode.DEPENDENCY_TIMEOUT: "Dependency timeout",
}


class AppError(Exception):
    """모든 애플리케이션 오류의 기반. 하위 클래스가 status와 기본 code를 정합니다."""

    status: int = 500
    default_code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        code: ErrorCode | None = None,
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.title = DEFAULT_TITLES[self.code]
        self.detail = detail
        self.headers = headers or {}
        self.errors = errors
        super().__init__(f"{self.status} {self.code}")


class BadRequestError(AppError):
    status, default_code = 400, ErrorCode.BAD_REQUEST


class UnauthorizedError(AppError):
    status, default_code = 401, ErrorCode.UNAUTHENTICATED

    def __init__(self, code: ErrorCode | None = None, **kwargs: Any) -> None:
        super().__init__(code, **kwargs)
        self.headers.setdefault("WWW-Authenticate", "Bearer")


class ForbiddenError(AppError):
    status, default_code = 403, ErrorCode.FORBIDDEN


class NotFoundError(AppError):
    """없음 또는 다른 사용자 소유 (존재 여부를 숨기려고 403 대신 404)."""

    status, default_code = 404, ErrorCode.NOT_FOUND


class ConflictError(AppError):
    status, default_code = 409, ErrorCode.CONFLICT


class PayloadTooLargeError(AppError):
    status, default_code = 413, ErrorCode.FILE_TOO_LARGE


class UnsupportedMediaTypeError(AppError):
    status, default_code = 415, ErrorCode.UNSUPPORTED_FILE_TYPE


class ValidationFailedError(AppError):
    """Pydantic 검증 밖에서 하는 업무 검증 실패 (예: 중복 기술). errors=[{field, code}]"""

    status, default_code = 422, ErrorCode.VALIDATION_FAILED


class _RetryAfterError(AppError):
    def __init__(self, code: ErrorCode | None = None, *, retry_after: int | None = None, **kwargs: Any) -> None:
        super().__init__(code, **kwargs)
        if retry_after is not None:
            self.headers["Retry-After"] = str(retry_after)


class RateLimitedError(_RetryAfterError):
    status, default_code = 429, ErrorCode.RATE_LIMITED


class DependencyUnavailableError(_RetryAfterError):
    status, default_code = 503, ErrorCode.DEPENDENCY_UNAVAILABLE


class DependencyTimeoutError(AppError):
    status, default_code = 504, ErrorCode.DEPENDENCY_TIMEOUT
