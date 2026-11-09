from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

DocumentKind = Literal["resume", "portfolio"]
DocumentStatus = Literal["uploaded", "scanning", "ready", "rejected", "deleting"]


class Document(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    kind: Literal["resume", "portfolio", "career_guide"]
    original_filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime


class DocumentPage(BaseModel):
    items: list[Document]
    next_cursor: str | None
