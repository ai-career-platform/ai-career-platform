"""T56 DTOs — openapi.yaml `KnowledgeQuestion`, `KnowledgeAnswer`, `Citation` (FR-AI-003)."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(min_length=2, max_length=1000, description="원문은 저장하지 않음 (해시만)")
    document_ids: list[UUID] | None = Field(default=None, max_length=20,
                                            description="생략 시 내 문서 전체 + 공용 자료")

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("question must have at least 2 visible characters")
        return value

    @field_validator("document_ids", mode="before")
    @classmethod
    def parse_ids(cls, value):
        # strict 모드에서도 JSON 문자열 UUID를 받기 위해 변환
        if isinstance(value, list):
            return [UUID(v) if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if self.document_ids is not None and len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must be unique")
        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    document_id: UUID
    document_title: str
    chunk_index: int = Field(ge=0)
    score: float | None


class KnowledgeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_run_id: UUID
    status: Literal["answered", "no_evidence"]
    answer: str | None
    citations: list[Citation]
    limitations: list[str]
