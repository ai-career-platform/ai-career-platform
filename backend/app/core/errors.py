"""공통 에러 코드 · 메시지 카탈로그 · 애플리케이션 예외.

오류 메시지는 **이 파일 한 곳**에서만 관리합니다.
서비스·라우터는 코드만 골라 raise 하고, 상태와 메시지는 카탈로그에서 정해집니다.

    from app.core.errors import AppError, ErrorCode
    raise AppError(ErrorCode.EMAIL_TAKEN)
    # → 409 {"code": "EMAIL_TAKEN", "status": 409, "message": "이미 가입된 이메일입니다."}

규칙
- 호출하는 쪽에서 메시지 문자열을 직접 쓰지 않습니다. 새 문구가 필요하면 새 코드를 추가합니다.
- 메시지는 사용자에게 그대로 보여 줄 수 있는 문장이어야 합니다. 내부 정보(경로, SQL, 예외 내용)는 넣지 않습니다.
- 개발자용 원인은 `log_detail=`로 넘기면 서버 로그에만 남고 응답에는 나가지 않습니다.
- 코드를 추가·변경하면 docs/API_CONTRACT.md §1.4 표도 같이 고칩니다 (tests/test_errors.py가 불일치를 잡습니다).
"""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """클라이언트가 분기에 쓰는 고정 코드. 한 번 공개한 코드는 바꾸지 않습니다."""

    # 400
    BAD_REQUEST = "BAD_REQUEST"
    MALFORMED_JSON = "MALFORMED_JSON"
    NO_USER_SKILLS = "NO_USER_SKILLS"
    NOT_A_TARGET_ROLE = "NOT_A_TARGET_ROLE"
    INVALID_CURSOR = "INVALID_CURSOR"
    INVALID_RESET_TOKEN = (
        "INVALID_RESET_TOKEN"  # secret-scan: allow — 공개 API 오류 코드
    )
    # 401
    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # secret-scan: allow — 공개 API 오류 코드
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    # 403
    FORBIDDEN = "FORBIDDEN"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    # 404 / 405
    NOT_FOUND = "NOT_FOUND"
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


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str


# 코드 → (HTTP 상태, 사용자에게 보여 줄 메시지). 화면 문구를 바꿀 때는 여기만 고칩니다.
ERROR_CATALOG: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.BAD_REQUEST: ErrorSpec(400, "요청을 처리할 수 없습니다."),
    ErrorCode.MALFORMED_JSON: ErrorSpec(400, "요청 형식이 올바르지 않습니다."),
    ErrorCode.NO_USER_SKILLS: ErrorSpec(
        400, "먼저 보유 기술을 1개 이상 등록해 주세요."
    ),
    ErrorCode.NOT_A_TARGET_ROLE: ErrorSpec(400, "목표 직무로 등록한 직무가 아닙니다."),
    ErrorCode.INVALID_CURSOR: ErrorSpec(
        400, "목록 정보가 만료되었습니다. 처음부터 다시 조회해 주세요."
    ),
    ErrorCode.INVALID_RESET_TOKEN: ErrorSpec(
        400, "비밀번호 재설정 링크가 유효하지 않거나 만료되었습니다."
    ),
    ErrorCode.UNAUTHENTICATED: ErrorSpec(401, "로그인이 필요합니다."),
    ErrorCode.TOKEN_EXPIRED: ErrorSpec(
        401, "로그인이 만료되었습니다. 다시 로그인해 주세요."
    ),
    ErrorCode.INVALID_CREDENTIALS: ErrorSpec(
        401, "이메일 또는 비밀번호가 올바르지 않습니다."
    ),
    ErrorCode.FORBIDDEN: ErrorSpec(403, "접근 권한이 없습니다."),
    ErrorCode.CONSENT_REQUIRED: ErrorSpec(
        403, "이 기능을 사용하려면 동의가 필요합니다."
    ),
    ErrorCode.NOT_FOUND: ErrorSpec(404, "요청한 정보를 찾을 수 없습니다."),
    ErrorCode.METHOD_NOT_ALLOWED: ErrorSpec(405, "지원하지 않는 요청입니다."),
    ErrorCode.CONFLICT: ErrorSpec(409, "현재 상태에서는 처리할 수 없습니다."),
    ErrorCode.EMAIL_TAKEN: ErrorSpec(409, "이미 가입된 이메일입니다."),
    ErrorCode.DELETION_ALREADY_REQUESTED: ErrorSpec(
        409, "이미 탈퇴 요청이 접수되었습니다."
    ),
    ErrorCode.DOCUMENT_NOT_READY: ErrorSpec(
        409, "문서를 아직 사용할 수 없습니다. 검사가 끝난 뒤 다시 시도해 주세요."
    ),
    ErrorCode.APPROVAL_CLOSED: ErrorSpec(409, "이미 처리되었거나 만료된 요청입니다."),
    ErrorCode.LAST_ADMIN: ErrorSpec(409, "관리자는 최소 1명 이상 있어야 합니다."),
    ErrorCode.FILE_TOO_LARGE: ErrorSpec(413, "파일은 10MB 이하만 올릴 수 있습니다."),
    ErrorCode.UNSUPPORTED_FILE_TYPE: ErrorSpec(
        415, "PDF 또는 DOCX 파일만 올릴 수 있습니다."
    ),
    ErrorCode.VALIDATION_FAILED: ErrorSpec(422, "입력값을 확인해 주세요."),
    ErrorCode.DUPLICATE_SKILL: ErrorSpec(422, "같은 기술이 중복으로 들어 있습니다."),
    ErrorCode.RATE_LIMITED: ErrorSpec(
        429, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        500, "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    ),
    ErrorCode.DEPENDENCY_UNAVAILABLE: ErrorSpec(
        503, "서비스를 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    ),
    ErrorCode.DEPENDENCY_TIMEOUT: ErrorSpec(
        504, "응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요."
    ),
}


class AppError(Exception):
    """모든 애플리케이션 오류. 코드만 받고 상태·메시지는 카탈로그에서 가져옵니다.

    - retry_after: 429/503에서 `Retry-After` 헤더(초)
    - log_detail: 서버 로그에만 남길 개발자용 설명 (응답에는 절대 포함되지 않음)
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        retry_after: int | None = None,
        log_detail: str | None = None,
    ) -> None:
        spec = ERROR_CATALOG[code]
        self.code = code
        self.status = spec.status
        self.message = spec.message
        self.log_detail = log_detail
        self.headers: dict[str, str] = {}
        if spec.status == 401:
            self.headers["WWW-Authenticate"] = "Bearer"
        if retry_after is not None:
            self.headers["Retry-After"] = str(retry_after)
        super().__init__(f"{self.status} {self.code}")
