"""T31 consent/deletion DTOs; purge date remains unknown until policy approval."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.base import ORMModel

class OptionalConsentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy_code: Literal["llm_processing", "behavior_tracking"]
    policy_version: str = Field(min_length=1, max_length=40)
    granted: bool

class Consent(ORMModel):
    consent_id: UUID
    is_required: bool
    policy_code: str
    policy_version: str
    granted: bool
    recorded_at: datetime

class DeletionRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: Literal["DELETE"]

class DeletionRequest(ORMModel):
    request_id: UUID
    status: Literal["requested", "cancelled", "completed"]
    requested_at: datetime
    scheduled_purge_at: datetime | None
    completed_at: datetime | None
