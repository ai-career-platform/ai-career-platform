"""공통 에러 응답 DTO.

클라이언트에 나가는 오류 본문은 `code`, `status`, `message` 세 개뿐입니다 (Content-Type: application/json).
계약: docs/API_CONTRACT.md §1.4, docs/api/openapi.yaml `components.schemas.ErrorResponse`.
메시지 원본: app/core/errors.py `ERROR_CATALOG`.
"""

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """모든 오류 응답의 본문. 입력값·내부 정보·스택트레이스는 넣지 않습니다."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$", description="화면이 분기에 쓰는 고정 코드", examples=["EMAIL_TAKEN"])
    status: int = Field(ge=400, le=599, description="HTTP 상태 코드와 같은 값", examples=[409])
    message: str = Field(description="사용자에게 그대로 보여 줄 수 있는 안내 문구", examples=["이미 가입된 이메일입니다."])
