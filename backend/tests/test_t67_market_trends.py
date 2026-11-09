"""T67 `GET /api/v1/market-trends` — 메모리 저장소로 하는 서비스·HTTP·계약 테스트 (DB 없음)."""

import uuid
from datetime import date
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from app.core.config import API_V1_PREFIX
from app.core.errors import AppError, ErrorCode
from app.repositories.market_trends import SeriesKey, SourceRef
from app.routers.market_trends import get_market_trend_service
from app.schemas.market_trends import (
    MarketJobRole, MarketPoint, MarketSkill, MarketSource, MetricCode, ModelVersionRef, Period,
)
from app.services.market_trends import MarketTrendService
from tests.conftest import bearer, signup

URL = f"{API_V1_PREFIX}/market-trends"
BACKEND = MarketJobRole(job_role_id=uuid.UUID(int=1), code="BACKEND_ENGINEER", name="백엔드 개발자")
PYTHON = MarketSkill(skill_id=uuid.UUID(int=2), code="PYTHON", name="Python")
JOBKOREA = SourceRef(uuid.UUID(int=10), MarketSource(code="jobkorea", name="잡코리아"))
OTHER = SourceRef(uuid.UUID(int=11), MarketSource(code="other", name="다른 출처"))
MODEL = (uuid.UUID(int=20), ModelVersionRef(model_code="market_naive", version="1", kind="rule"))


class MemoryRepo:
    """(source_id, metric, period, role, skill) → {date: value} 저장소."""

    def __init__(self):
        self.sources = {s.ref.code: s for s in (JOBKOREA, OTHER)}
        self.obs: dict[tuple, dict[date, float]] = {}
        self.fc: list[tuple] = []  # (metric, role, skill, date, value, lo, hi)
        self.calls: list[str] = []

    def add(self, source, metric, day, value, *, period="week", role=None, skill=None):
        self.obs.setdefault((source.source_id, metric, period, role, skill), {})[day] = value

    def find_source(self, code):
        return self.sources.get(code)

    def get_job_role(self, job_role_id):
        return BACKEND if job_role_id == BACKEND.job_role_id else None

    def get_skill(self, skill_id):
        return PYTHON if skill_id == PYTHON.skill_id else None

    def _points(self, source_id, key: SeriesKey, period):
        series = self.obs.get((source_id, key.metric_code, period, key.job_role_id, key.skill_id), {})
        return sorted((d, v) for d, v in series.items() if key.from_date <= d <= key.to_date)

    def sources_with_observations(self, key, period):
        return [s for s in self.sources.values() if self._points(s.source_id, key, period)]

    def observations(self, source_id, key, period):
        self.calls.append("observations")
        return [MarketPoint(date=d, value=v) for d, v in self._points(source_id, key, period)]

    def _fc(self, key):
        return [f for f in self.fc if (f[0], f[1], f[2]) == (key.metric_code, key.job_role_id, key.skill_id)
                and key.from_date <= f[3] <= key.to_date]

    def latest_forecast_model(self, key):
        return MODEL if self._fc(key) else None

    def forecasts(self, model_version_id, key):
        return [MarketPoint(date=d, value=v, lower_bound=lo, upper_bound=hi) for _, _, _, d, v, lo, hi in self._fc(key)]


@pytest.fixture
def market_repo():  # conftest의 `repo`(인증 저장소)와 이름이 겹치지 않게 market_repo로 둔다
    return MemoryRepo()


@pytest.fixture
def service(market_repo):
    return MarketTrendService(market_repo)


@pytest.fixture
def http(app, client, market_repo):
    app.dependency_overrides[get_market_trend_service] = lambda: MarketTrendService(market_repo)
    token = signup(client).json()["access_token"]
    return client, bearer(token)


def trend(service, **kw):
    params = {"metric_code": MetricCode.POSTING_COUNT, "from_date": date(2026, 10, 1), "to_date": date(2026, 11, 30)}
    return service.get_trend(**{**params, **kw})


# ------------------------------------------------------------------ service
def test_observations_are_returned_in_order_with_gaps_kept(service, market_repo):
    market_repo.add(JOBKOREA, "posting_count", date(2026, 10, 19), 0)
    market_repo.add(JOBKOREA, "posting_count", date(2026, 10, 5), 7)
    # 10-12 구간은 행이 없음 → 응답에도 없음(0으로 채우지 않음)
    result = trend(service)
    assert [(p.date, p.value) for p in result.observations] == [(date(2026, 10, 5), 7.0), (date(2026, 10, 19), 0.0)]
    assert result.source == JOBKOREA.ref and result.unit == "count" and result.job_role is None
    assert result.forecasts == [] and result.forecast_model is None


def test_filters_by_role_skill_period_and_range(service, market_repo):
    market_repo.add(JOBKOREA, "skill_demand_share", date(2026, 10, 5), 0.8, role=BACKEND.job_role_id, skill=PYTHON.skill_id)
    market_repo.add(JOBKOREA, "skill_demand_share", date(2026, 10, 5), 0.7, skill=PYTHON.skill_id)            # 전체 시장
    market_repo.add(JOBKOREA, "skill_demand_share", date(2026, 10, 1), 0.5, role=BACKEND.job_role_id,
                    skill=PYTHON.skill_id, period="month")
    market_repo.add(JOBKOREA, "skill_demand_share", date(2026, 12, 7), 0.9, role=BACKEND.job_role_id, skill=PYTHON.skill_id)
    result = trend(service, metric_code=MetricCode.SKILL_DEMAND_SHARE, job_role_id=BACKEND.job_role_id, skill_id=PYTHON.skill_id)
    assert [(p.date, p.value) for p in result.observations] == [(date(2026, 10, 5), 0.8)]
    assert result.unit == "ratio" and result.job_role == BACKEND and result.skill == PYTHON


def test_empty_result_is_200_with_null_source(service):
    result = trend(service)
    assert result.observations == [] and result.forecasts == [] and result.source is None


def test_forecasts_are_separate_with_bounds_and_model(service, market_repo):
    market_repo.add(JOBKOREA, "posting_count", date(2026, 10, 5), 7)
    market_repo.fc.append(("posting_count", None, None, date(2026, 11, 9), 6.5, 5.0, 8.0))
    result = trend(service)
    assert [p.value for p in result.observations] == [7.0]
    assert [(p.date, p.value, p.lower_bound, p.upper_bound) for p in result.forecasts] == [(date(2026, 11, 9), 6.5, 5.0, 8.0)]
    assert result.forecast_model == MODEL[1]


def test_several_sources_need_explicit_source(service, market_repo):
    market_repo.add(JOBKOREA, "posting_count", date(2026, 10, 5), 7)
    market_repo.add(OTHER, "posting_count", date(2026, 10, 5), 3)
    with pytest.raises(AppError) as err:
        trend(service)
    assert err.value.code == ErrorCode.VALIDATION_FAILED
    assert [p.value for p in trend(service, source="other").observations] == [3.0]


@pytest.mark.parametrize("kw", [
    {"from_date": date(2026, 11, 2), "to_date": date(2026, 11, 1)},                              # 거꾸로
    {"period": Period.DAY, "from_date": date(2026, 1, 1), "to_date": date(2027, 1, 2)},          # 367일
    {"period": Period.WEEK, "from_date": date(2026, 1, 5), "to_date": date(2029, 1, 8)},         # 158주
    {"period": Period.MONTH, "from_date": date(2021, 1, 1), "to_date": date(2026, 1, 1)},        # 61개월
    {"metric_code": MetricCode.SKILL_DEMAND_SHARE},                                              # skill_id 없음
    {"skill_id": PYTHON.skill_id},                                                               # posting_count에 skill
])
def test_invalid_requests_are_422(service, kw):
    with pytest.raises(AppError) as err:
        trend(service, **kw)
    assert err.value.code == ErrorCode.VALIDATION_FAILED


def test_longest_allowed_ranges_pass(service):
    trend(service, period=Period.DAY, from_date=date(2026, 1, 1), to_date=date(2026, 12, 31))  # 365일
    trend(service, period=Period.MONTH, from_date=date(2021, 1, 1), to_date=date(2025, 12, 31))  # 60개월
    trend(service, period=Period.WEEK, from_date=date(2026, 1, 5), to_date=date(2029, 1, 7))     # 157주 (월요일~일요일)


@pytest.mark.parametrize("kw", [
    {"job_role_id": uuid.UUID(int=99)},
    {"metric_code": MetricCode.SKILL_DEMAND_SHARE, "skill_id": uuid.UUID(int=99)},
    {"source": "no_such_source"},
])
def test_unknown_references_are_404(service, kw):
    with pytest.raises(AppError) as err:
        trend(service, **kw)
    assert err.value.code == ErrorCode.NOT_FOUND


# ------------------------------------------------------------------ HTTP
def test_http_requires_login(app, client, market_repo):
    app.dependency_overrides[get_market_trend_service] = lambda: MarketTrendService(market_repo)
    res = client.get(URL, params={"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31"})
    assert res.status_code == 401 and res.json()["code"] == "UNAUTHENTICATED"
    res = client.get(URL, params={"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31"},
                     headers=bearer("not-a-jwt"))
    assert res.status_code == 401
    assert market_repo.calls == []  # 인증 전에는 DB 조회 없음


def test_http_ok_body_shape(http, market_repo):
    client, auth = http
    market_repo.add(JOBKOREA, "posting_count", date(2026, 10, 5), 7)
    res = client.get(URL, params={"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31"}, headers=auth)
    assert res.status_code == 200
    assert res.json() == {
        "metric_code": "posting_count", "unit": "count", "period": "week", "from": "2026-10-01", "to": "2026-10-31",
        "source": {"code": "jobkorea", "name": "잡코리아"}, "job_role": None, "skill": None,
        "observations": [{"date": "2026-10-05", "value": 7.0, "lower_bound": None, "upper_bound": None}],
        "forecasts": [], "forecast_model": None,
    }


@pytest.mark.parametrize("params, status", [
    ({"metric_code": "posting_count", "from": "2026-10-01"}, 422),                          # to 없음
    ({"metric_code": "openings", "from": "2026-10-01", "to": "2026-10-31"}, 422),           # 없는 지표
    ({"metric_code": "posting_count", "from": "2026-10-31", "to": "2026-10-01"}, 422),
    ({"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31", "period": "year"}, 422),
    ({"metric_code": "posting_count", "from": "2026-13-01", "to": "2026-10-31"}, 422),
    ({"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31", "job_role_id": "x"}, 422),
    ({"metric_code": "skill_demand_share", "from": "2026-10-01", "to": "2026-10-31"}, 422),
    ({"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31", "job_role_id": str(uuid.UUID(int=99))}, 404),
])
def test_http_errors_use_team_error_body(http, params, status):
    client, auth = http
    res = client.get(URL, params=params, headers=auth)
    assert res.status_code == status
    assert set(res.json()) == {"code", "status", "message"}
    assert res.json()["status"] == status


def test_response_matches_openapi_contract(http, market_repo):
    client, auth = http
    market_repo.add(JOBKOREA, "skill_demand_share", date(2026, 10, 5), 0.8, role=BACKEND.job_role_id, skill=PYTHON.skill_id)
    market_repo.fc.append(("skill_demand_share", BACKEND.job_role_id, PYTHON.skill_id, date(2026, 11, 9), 0.75, None, None))
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    validator = Draft202012Validator({"$ref": "#/components/schemas/MarketTrend", "components": spec["components"]})
    for params in (
        {"metric_code": "skill_demand_share", "from": "2026-10-01", "to": "2026-11-30",
         "job_role_id": str(BACKEND.job_role_id), "skill_id": str(PYTHON.skill_id)},
        {"metric_code": "posting_count", "from": "2026-10-01", "to": "2026-10-31", "period": "month"},  # 빈 결과
    ):
        res = client.get(URL, params=params, headers=auth)
        assert res.status_code == 200
        validator.validate(res.json())

    operation = spec["paths"]["/market-trends"]["get"]
    assert {p["name"] for p in operation["parameters"]} == {
        "metric_code", "from", "to", "period", "job_role_id", "skill_id", "source"}
    assert set(operation["responses"]) == {"200", "401", "404", "422"}
