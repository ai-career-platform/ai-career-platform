"""T84 운영 감사·AI 사용량 조회 응답 모델.

- `AuditEvent`, `AuditEventPage`, `AiUsageBucket`: **확정 계약**(docs/api/openapi.yaml)과 같은 모양. HTTP 응답에 쓴다.
- `AuditEventView`, `AiUsageReport` 등: docs/security/t84_openapi_proposal.yaml 의 **PROPOSED(미승인)** 모양.
  서비스·직렬화 테스트에서만 쓰고, PM 승인(D2·D3)과 T06 계약 반영 전에는 어떤 HTTP 경로에도 연결하지 않는다.
"""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- 확정 계약
class AuditEvent(_Strict):
    audit_event_id: UUID
    actor_user_id: UUID | None
    action_code: str
    resource_type: str
    resource_id: UUID | None
    request_id: str | None
    occurred_at: datetime


class AuditEventPage(_Strict):
    items: list[AuditEvent]
    next_cursor: str | None


class AiUsageBucket(_Strict):
    key: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    request_count: int = Field(ge=0)


# ---------------------------------------------------------------- PROPOSED (미승인, HTTP 미연결)
MASKED_UUID_PATTERN = r"^[0-9a-f]{8}-\*{4}-\*{4}-\*{4}-\*{8}[0-9a-f]{4}$"


class AuditEventView(_Strict):
    """D3 제안: 사용자 ID 마스킹. 마스킹 값은 **익명정보가 아니다**(앞 8·끝 4자리로 대조 가능)."""

    audit_event_id: UUID
    actor_user_id_masked: str | None = Field(pattern=MASKED_UUID_PATTERN)
    action_code: str
    resource_type: str
    resource_id: str | None
    resource_id_masked: bool
    request_id: str | None
    occurred_at: datetime


class AuditEventViewPage(_Strict):
    items: list[AuditEventView] = Field(max_length=100)
    next_cursor: str | None


class AiUsageAmounts(_Strict):
    request_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: float | None = Field(ge=0)
    unpriced_request_count: int = Field(ge=0)


class AiUsageReportBucket(AiUsageAmounts):
    key: str
    request_count: int = Field(ge=1)


class AiUsageReport(_Strict):
    from_: date = Field(alias="from")
    to: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    group_by: Literal["day", "feature_code", "provider_model"]
    currency: Literal["USD"] = "USD"
    cost_is_estimate: Literal[True] = True
    buckets: list[AiUsageReportBucket] = Field(max_length=200)
    totals: AiUsageAmounts

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
