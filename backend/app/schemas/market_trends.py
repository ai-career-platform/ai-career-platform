"""T67 `/market-trends` DTO (openapi.yaml `MarketTrend`, `MarketPoint`). 계약: docs/data/MARKET_METRICS_CONTRACT.md"""

import datetime as dt
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MarketModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricCode(StrEnum):
    POSTING_COUNT = "posting_count"
    SKILL_DEMAND_SHARE = "skill_demand_share"


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class MetricUnit(StrEnum):
    COUNT = "count"
    RATIO = "ratio"


# T65 계약 §1 지표 카탈로그
METRIC_UNITS: dict[MetricCode, MetricUnit] = {
    MetricCode.POSTING_COUNT: MetricUnit.COUNT,
    MetricCode.SKILL_DEMAND_SHARE: MetricUnit.RATIO,
}


class MarketPoint(MarketModel):
    date: dt.date = Field(description="집계 구간 시작일 (KST, 주=월요일, 월=1일)")
    value: float
    lower_bound: float | None = None
    upper_bound: float | None = None


class MarketSource(MarketModel):
    code: str
    name: str


class MarketJobRole(MarketModel):
    job_role_id: UUID
    code: str
    name: str


class MarketSkill(MarketModel):
    skill_id: UUID
    code: str
    name: str


class ModelVersionRef(MarketModel):
    model_code: str
    version: str
    kind: str


class MarketTrend(MarketModel):
    metric_code: MetricCode
    unit: MetricUnit = Field(description="count = 건, ratio = 0~1 비율")
    period: Period
    from_date: dt.date = Field(alias="from", serialization_alias="from")
    to_date: dt.date = Field(alias="to", serialization_alias="to")
    source: MarketSource | None = Field(description="관측값 출처. 관측값이 없으면 null")
    job_role: MarketJobRole | None = Field(description="null = 전체 시장")
    skill: MarketSkill | None = Field(description="skill_demand_share일 때 대상 기술")
    observations: list[MarketPoint] = Field(
        description="관측값. 데이터가 없는 구간은 포함하지 않는다(0으로 채우지 않음)")
    forecasts: list[MarketPoint] = Field(description="예측값. 관측과 구분해 표시. 범위(lower/upper) 포함")
    forecast_model: ModelVersionRef | None

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
