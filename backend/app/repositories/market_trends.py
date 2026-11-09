"""T67 채용시장 지표 읽기 전용 DB 접근 (스키마 `career`, migration 0001 + 0003).

- 서비스는 `MarketTrendRepository` 프로토콜에만 의존한다. 단위 테스트는 메모리 구현을 쓴다.
- 공유 ORM 모델을 만들지 않고 쓰는 컬럼만 `table()`로 적는다. SELECT만 한다.
- `job_role_id`·`skill_id`가 None이면 그 컬럼이 NULL인 행(전체 시장 / 기술 무관 지표)만 고른다.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy import Date, DateTime, Numeric, String, Uuid, column, desc, select, table
from sqlalchemy.orm import Session

from app.schemas.market_trends import MarketJobRole, MarketPoint, MarketSkill, MarketSource, ModelVersionRef


@dataclass(frozen=True)
class SeriesKey:
    metric_code: str
    job_role_id: UUID | None
    skill_id: UUID | None
    from_date: date
    to_date: date


@dataclass(frozen=True)
class SourceRef:
    source_id: UUID
    ref: MarketSource


class MarketTrendRepository(Protocol):
    def find_source(self, code: str) -> SourceRef | None: ...

    def get_job_role(self, job_role_id: UUID) -> MarketJobRole | None: ...

    def get_skill(self, skill_id: UUID) -> MarketSkill | None: ...

    def sources_with_observations(self, key: SeriesKey, period: str) -> list[SourceRef]:
        """조건에 맞는 관측값이 한 건이라도 있는 출처 (code 순)."""

    def observations(self, source_id: UUID, key: SeriesKey, period: str) -> list[MarketPoint]:
        """observed_on 오름차순."""

    def latest_forecast_model(self, key: SeriesKey) -> tuple[UUID, ModelVersionRef] | None:
        """조건에 맞는 예측 중 가장 최근에 만든 예측의 모델 버전."""

    def forecasts(self, model_version_id: UUID, key: SeriesKey) -> list[MarketPoint]:
        """forecast_for 오름차순."""


_S = "career"
observations_t = table(
    "market_observations", column("source_id", Uuid), column("job_role_id", Uuid), column("skill_id", Uuid),
    column("observed_on", Date), column("period", String), column("metric_code", String),
    column("metric_value", Numeric), schema=_S,
)
forecasts_t = table(
    "market_forecasts", column("model_version_id", Uuid), column("job_role_id", Uuid), column("skill_id", Uuid),
    column("forecast_for", Date), column("metric_code", String), column("predicted_value", Numeric),
    column("lower_bound", Numeric), column("upper_bound", Numeric), column("created_at", DateTime), schema=_S,
)
model_versions_t = table(
    "model_versions", column("model_version_id", Uuid), column("model_code", String),
    column("version", String), column("kind", String), schema=_S,
)
data_sources_t = table("data_sources", column("source_id", Uuid), column("code", String), column("name", String), schema=_S)
job_roles_t = table("job_roles", column("job_role_id", Uuid), column("code", String), column("name", String), schema=_S)
skills_t = table("skills", column("skill_id", Uuid), column("code", String), column("name", String), schema=_S)


def _match(col, value):
    return col.is_(None) if value is None else col == value


def _num(value) -> float | None:
    return None if value is None else float(value)


class SqlMarketTrendRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    def find_source(self, code: str) -> SourceRef | None:
        s = data_sources_t.c
        row = self._db.execute(select(s.source_id, s.code, s.name).where(s.code == code)).one_or_none()
        return None if row is None else SourceRef(row.source_id, MarketSource(code=row.code, name=row.name))

    def get_job_role(self, job_role_id: UUID) -> MarketJobRole | None:
        r = job_roles_t.c
        row = self._db.execute(select(r.job_role_id, r.code, r.name).where(r.job_role_id == job_role_id)).mappings().one_or_none()
        return None if row is None else MarketJobRole.model_validate(dict(row))

    def get_skill(self, skill_id: UUID) -> MarketSkill | None:
        k = skills_t.c
        row = self._db.execute(select(k.skill_id, k.code, k.name).where(k.skill_id == skill_id)).mappings().one_or_none()
        return None if row is None else MarketSkill.model_validate(dict(row))

    def _series_filter(self, key: SeriesKey, period: str):
        o = observations_t.c
        return (o.metric_code == key.metric_code, o.period == period, _match(o.job_role_id, key.job_role_id),
                _match(o.skill_id, key.skill_id), o.observed_on.between(key.from_date, key.to_date))

    def sources_with_observations(self, key: SeriesKey, period: str) -> list[SourceRef]:
        o, s = observations_t.c, data_sources_t.c
        stmt = (select(s.source_id, s.code, s.name).distinct()
                .join_from(observations_t, data_sources_t, o.source_id == s.source_id)
                .where(*self._series_filter(key, period)).order_by(s.code))
        return [SourceRef(r.source_id, MarketSource(code=r.code, name=r.name)) for r in self._db.execute(stmt)]

    def observations(self, source_id: UUID, key: SeriesKey, period: str) -> list[MarketPoint]:
        o = observations_t.c
        stmt = (select(o.observed_on, o.metric_value)
                .where(o.source_id == source_id, *self._series_filter(key, period)).order_by(o.observed_on))
        return [MarketPoint(date=r.observed_on, value=float(r.metric_value)) for r in self._db.execute(stmt)]

    def _forecast_filter(self, key: SeriesKey):
        f = forecasts_t.c
        return (f.metric_code == key.metric_code, _match(f.job_role_id, key.job_role_id),
                _match(f.skill_id, key.skill_id), f.forecast_for.between(key.from_date, key.to_date))

    def latest_forecast_model(self, key: SeriesKey) -> tuple[UUID, ModelVersionRef] | None:
        f, m = forecasts_t.c, model_versions_t.c
        stmt = (select(m.model_version_id, m.model_code, m.version, m.kind)
                .join_from(forecasts_t, model_versions_t, f.model_version_id == m.model_version_id)
                .where(*self._forecast_filter(key)).order_by(desc(f.created_at), m.model_version_id).limit(1))
        row = self._db.execute(stmt).one_or_none()
        if row is None:
            return None
        return row.model_version_id, ModelVersionRef(model_code=row.model_code, version=row.version, kind=row.kind)

    def forecasts(self, model_version_id: UUID, key: SeriesKey) -> list[MarketPoint]:
        f = forecasts_t.c
        stmt = (select(f.forecast_for, f.predicted_value, f.lower_bound, f.upper_bound)
                .where(f.model_version_id == model_version_id, *self._forecast_filter(key)).order_by(f.forecast_for))
        return [MarketPoint(date=r.forecast_for, value=float(r.predicted_value),
                            lower_bound=_num(r.lower_bound), upper_bound=_num(r.upper_bound))
                for r in self._db.execute(stmt)]
