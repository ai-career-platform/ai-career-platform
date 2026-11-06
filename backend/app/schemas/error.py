"""공통 에러 응답 DTO.

모든 오류 응답 본문은 이 형식이며 Content-Type은 `application/problem+json`입니다.
계약: docs/API_CONTRACT.md §1.4, docs/api/openapi.yaml `components.schemas.Problem`.
"""

from pydantic import BaseModel, ConfigDict, Field


class FieldError(BaseModel):
    """요청 값 검증 실패 1건 (422)."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="오류 위치. 예: `email`, `items[0].proficiency`")
    code: str = Field(description="고정 오류 코드. 예: `REQUIRED`, `OUT_OF_RANGE`")


class ProblemDetail(BaseModel):
    """RFC 9457 problem details + `code` + `request_id`.

    비밀번호·토큰·이메일·문서 내용·입력값·스택트레이스는 넣지 않습니다.
    """

    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="오류 종류 문서 URL")
    title: str = Field(description="사람이 읽는 짧은 제목")
    status: int = Field(ge=400, le=599, description="HTTP 상태 코드")
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$", description="화면이 분기에 쓰는 고정 코드")
    detail: str | None = Field(default=None, description="사람이 읽는 추가 설명 (선택)")
    request_id: str = Field(description="요청 추적 ID. 응답 헤더 X-Request-ID와 같음")
    errors: list[FieldError] | None = Field(default=None, description="422에서만 사용")
