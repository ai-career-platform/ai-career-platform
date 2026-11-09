"""T67 채용시장 추세 조회. 계약: docs/data/MARKET_METRICS_CONTRACT.md §7·§8

- 관측값과 예측값을 나눠 돌려준다(FR-ANL-005 수용 기준 1). 관측이 없는 구간은 0으로 채우지 않는다(§3.4).
- 관측값은 출처별로만 보여준다(§3.5). `source`를 안 주면 데이터가 있는 출처가 하나일 때 그 출처를 쓰고,
  둘 이상이면 섞지 않도록 422로 출처 지정을 요구한다.
- 한 번에 돌려주는 점 수는 기간 길이 상한으로 제한한다(일 366일, 주 157주, 월 60개월). 시계열이라 cursor 대신 기간으로 나눠 조회한다.
"""

from datetime import date, timedelta
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.market_trends import MarketTrendRepository, SeriesKey, SourceRef
from app.schemas.market_trends import METRIC_UNITS, MarketTrend, MetricCode, Period

MAX_POINTS = {Period.DAY: 366, Period.WEEK: 157, Period.MONTH: 60}


def bucket_count(from_date: date, to_date: date, period: Period) -> int:
    """[from, to]가 걸치는 구간 수 (KST 날짜 기준, 주=월요일 시작)."""
    if period is Period.DAY:
        return (to_date - from_date).days + 1
    if period is Period.WEEK:
        monday = lambda d: d - timedelta(days=d.weekday())  # noqa: E731
        return (monday(to_date) - monday(from_date)).days // 7 + 1
    return (to_date.year * 12 + to_date.month) - (from_date.year * 12 + from_date.month) + 1


def _invalid(detail: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"market-trends: {detail}")


class MarketTrendService:
    def __init__(self, repo: MarketTrendRepository) -> None:
        self._repo = repo

    def get_trend(self, *, metric_code: MetricCode, from_date: date, to_date: date, period: Period = Period.WEEK,
                  job_role_id: UUID | None = None, skill_id: UUID | None = None,
                  source: str | None = None) -> MarketTrend:
        if from_date > to_date:
            raise _invalid("from after to")
        if bucket_count(from_date, to_date, period) > MAX_POINTS[period]:
            raise _invalid("range too long")
        if metric_code is MetricCode.SKILL_DEMAND_SHARE and skill_id is None:
            raise _invalid("skill_id required for skill_demand_share")
        if metric_code is not MetricCode.SKILL_DEMAND_SHARE and skill_id is not None:
            raise _invalid("skill_id only for skill_demand_share")

        job_role = None
        if job_role_id is not None and (job_role := self._repo.get_job_role(job_role_id)) is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="market-trends: job_role")
        skill = None
        if skill_id is not None and (skill := self._repo.get_skill(skill_id)) is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="market-trends: skill")

        key = SeriesKey(metric_code=metric_code.value, job_role_id=job_role_id, skill_id=skill_id,
                        from_date=from_date, to_date=to_date)
        chosen = self._resolve_source(source, key, period)
        observations = self._repo.observations(chosen.source_id, key, period.value) if chosen else []

        model = self._repo.latest_forecast_model(key)
        forecasts = self._repo.forecasts(model[0], key) if model else []

        return MarketTrend(
            metric_code=metric_code, unit=METRIC_UNITS[metric_code], period=period,
            from_date=from_date, to_date=to_date,
            source=chosen.ref if chosen else None, job_role=job_role, skill=skill,
            observations=observations, forecasts=forecasts, forecast_model=model[1] if model else None,
        )

    def _resolve_source(self, code: str | None, key: SeriesKey, period: Period) -> SourceRef | None:
        if code is not None:
            found = self._repo.find_source(code)
            if found is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="market-trends: source")
            return found
        candidates = self._repo.sources_with_observations(key, period.value)
        if len(candidates) > 1:
            raise _invalid("several sources; specify source")
        return candidates[0] if candidates else None
