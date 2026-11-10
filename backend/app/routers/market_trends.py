"""T67 `GET /market-trends` (openapi.yaml tag `insights`, FR-ANL-005, UI-024).

로그인 사용자만 조회한다(API_CONTRACT: 인증 필요). 권한 구분은 없다. 계약: docs/data/MARKET_METRICS_CONTRACT.md
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.market_trends import SqlMarketTrendRepository
from app.schemas.market_trends import MarketTrend, MetricCode, Period
from app.services.market_trends import MarketTrendService


def get_market_trend_service(session: Annotated[Session, Depends(get_db)]) -> MarketTrendService:
    # Staging에 T65 migration 0003이 없는 기간에는 SQL의 undefined_column(500)을
    # 유발하지 않고, 이 엔드포인트만 안전하게 503으로 응답한다.
    found = session.execute(text(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'career' AND table_name IN ('market_observations', 'market_forecasts') "
        "AND column_name = 'skill_id'"
    )).scalar_one()
    if found != 2:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="T67 requires migration 0003")
    return MarketTrendService(SqlMarketTrendRepository(session))


router = APIRouter(tags=["insights"], responses=error_responses(503))


@router.get(
    "/market-trends", response_model=MarketTrend, response_model_by_alias=True,
    operation_id="getMarketTrends", summary="채용시장 지표 관측값 + 예측값",
    responses=error_responses(401, 404),
)
def get_market_trends(
    _user: CurrentUserDep,
    service: Annotated[MarketTrendService, Depends(get_market_trend_service)],
    metric_code: Annotated[MetricCode, Query(description="posting_count = 신규 게시 공고 수(건), "
                                                         "skill_demand_share = 기술 요구 비율(0~1)")],
    from_date: Annotated[date, Query(alias="from", description="시작일 (포함, 구간 시작일 기준)")],
    to_date: Annotated[date, Query(alias="to", description="종료일 (포함)")],
    period: Annotated[Period, Query(description="집계 단위 (KST)")] = Period.WEEK,
    job_role_id: Annotated[UUID | None, Query(description="없으면 전체 시장")] = None,
    skill_id: Annotated[UUID | None, Query(description="skill_demand_share일 때 필수")] = None,
    source: Annotated[str | None, Query(min_length=1, max_length=80,
                                        description="출처 코드. 없으면 데이터가 있는 출처가 하나일 때 자동 선택")] = None,
) -> MarketTrend:
    return service.get_trend(metric_code=metric_code, from_date=from_date, to_date=to_date, period=period,
                             job_role_id=job_role_id, skill_id=skill_id, source=source)
