"""T47 추천 피드백 DTO (docs/api/openapi.yaml `RecommendationFeedbackInput`, `RecommendationFeedback`).

- 두 스키마 모두 openapi.yaml의 `additionalProperties: false`와 맞춰 알 수 없는 필드는 422.
- `feedback` 값은 계약 enum(liked / not_interested / cleared)만 허용한다.
- 사용자 ID는 받지 않는다. 토큰의 `sub`로만 정한다 (API_CONTRACT §1.3).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

FeedbackValue = Literal["liked", "not_interested", "cleared"]
# RecommendationItem.feedback(T45)에 쓰는 값. cleared는 "피드백 없음"(null)으로 보인다.
CurrentFeedback = Literal["liked", "not_interested"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecommendationFeedbackInput(_Strict):
    # 생략 가능(계약상 required 아님). 주면 그 추천 실행에 해당 공고가 있어야 한다.
    # None은 "생략"을 뜻하는 내부 기본값일 뿐이다. 계약 타입이 Uuid(nullable 아님)라 명시적 null은 422 (MePatch와 같은 방식).
    recommendation_run_id: UUID = Field(default=None)
    job_posting_id: UUID
    feedback: FeedbackValue


class RecommendationFeedback(_Strict):
    feedback_id: UUID
    job_posting_id: UUID
    feedback: FeedbackValue
    created_at: datetime
