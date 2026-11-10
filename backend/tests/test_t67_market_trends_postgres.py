"""T67 `/market-trends` — 실제 PostgreSQL로 SQL 저장소를 검증한다.

일회용 DB에 migration 0001~·Seed·T65 fixture를 넣고, T65 검산 SQL 결과를 market_observations에 적재한 뒤
API 응답이 T65 손 계산 정답(t65_expected.json)과 같은지 확인한다. 인증 자체는 test_t67_market_trends.py에서 검증하므로
여기서는 로그인 사용자 의존성만 고정값으로 바꾼다.

T15_TEST_DATABASE_URL에 **일회용** PostgreSQL URL을 지정한다(career 스키마를 지우고 다시 만든다).
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import API_V1_PREFIX, DatabaseSettings, get_settings
from app.db import create_db_engine
from app.dependencies.auth import get_current_user
from app.main import create_app
from app.services.auth import CurrentUser
from tests.conftest import TEST_SECRET

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("T15_TEST_DATABASE_URL")
MIGRATIONS = sorted((REPO / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
SEED_SQL = REPO / "database/seeds/0001_initial_seed.sql"
METRICS = REPO / "database/market_metrics"
REFERENCE_SQL = (METRICS / "reference_metrics.sql").read_text(encoding="utf-8")
EXPECTED = json.loads((METRICS / "t65_expected.json").read_text(encoding="utf-8"))
URL = f"{API_V1_PREFIX}/market-trends"

pytestmark = pytest.mark.skipif(not DB_URL, reason="T15_TEST_DATABASE_URL not set")


def _load(conn, scenario):
    """T65 검산 SQL 결과를 그대로 적재 (T66 job과 같은 값)."""
    src = conn.execute(text("SELECT source_id FROM career.data_sources WHERE code = 't65_fixture'")).scalar_one()
    rows = conn.execute(text(REFERENCE_SQL), {
        "source_id": src, "period": scenario["period"], "range_start": date.fromisoformat(scenario["range_start"]),
        "range_end": date.fromisoformat(scenario["range_end"]), "as_of": datetime.fromisoformat(scenario["as_of"]),
        "min_sample": EXPECTED["min_sample"]}).mappings().all()
    conn.execute(text(
        "INSERT INTO career.market_observations (source_id, job_role_id, skill_id, observed_on, period, metric_code, metric_value) "
        "VALUES (:source_id, :job_role_id, :skill_id, :observed_on, :period, :metric_code, :metric_value)"),
        [dict(r) for r in rows])


@pytest.fixture(scope="module")
def ids():
    engine = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=2, timeout=5))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for f in [*MIGRATIONS, SEED_SQL, METRICS / "t65_fixture.sql"]:
            conn.exec_driver_sql(f.read_text(encoding="utf-8").replace("%", "%%"))
    with engine.begin() as conn:
        _load(conn, EXPECTED["scenarios"][1])  # 주간 S2
        _load(conn, EXPECTED["scenarios"][2])  # 월간 S3
        roles = dict(conn.execute(text("SELECT code, job_role_id FROM career.job_roles")).all())
        skills = dict(conn.execute(text("SELECT code, skill_id FROM career.skills")).all())
        # 같은 지표에 두 번째 출처(관측 1건)와 예측 모델 2개(나중 것이 최신)를 추가
        conn.execute(text("INSERT INTO career.data_sources (source_id, code, name, license_ref) "
                          "VALUES (md5('t67:source2')::uuid, 't67_second', 'T67 두 번째 출처', 'synthetic-test-only')"))
        conn.execute(text("INSERT INTO career.market_observations (source_id, observed_on, period, metric_code, metric_value) "
                          "VALUES (md5('t67:source2')::uuid, '2026-10-05', 'week', 'posting_count', 3)"))
        conn.execute(text(
            "INSERT INTO career.model_versions (model_version_id, model_code, version, kind) VALUES "
            "(md5('t67:mv1')::uuid, 'market_naive', '1', 'rule'), (md5('t67:mv2')::uuid, 'market_naive', '2', 'rule')"))
        conn.execute(text(
            "INSERT INTO career.market_forecasts (model_version_id, job_role_id, skill_id, forecast_for, metric_code, "
            "predicted_value, lower_bound, upper_bound, created_at) VALUES "
            "(md5('t67:mv1')::uuid, NULL, NULL, '2026-11-09', 'posting_count', 1, 0, 2, '2026-11-01'), "
            "(md5('t67:mv2')::uuid, NULL, NULL, '2026-11-09', 'posting_count', 2.5, 1.5, 3.5, '2026-11-08'), "
            "(md5('t67:mv2')::uuid, NULL, NULL, '2026-11-16', 'posting_count', 2.4, NULL, NULL, '2026-11-08'), "
            "(md5('t67:mv2')::uuid, :b, :py, '2026-11-09', 'skill_demand_share', 0.7, 0.6, 0.8, '2026-11-08')"),
            {"b": roles["BACKEND_ENGINEER"], "py": skills["PYTHON"]})
    engine.dispose()
    return {"roles": roles, "skills": skills}


@pytest.fixture
def client(monkeypatch, ids):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uuid.uuid4(), uuid.uuid4(), frozenset({"job_seeker"}), frozenset())
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c
    finally:
        get_settings.cache_clear()


def _expected(index, metric, role=None, skill=None):
    return [(d, float(v)) for d, m, r, s, v in EXPECTED["scenarios"][index]["rows"]
            if m == metric and r == role and s == skill]


def _points(body):
    return [(p["date"], p["value"]) for p in body["observations"]]


def get(client, **params):
    return client.get(URL, params={"from": "2026-10-01", "to": "2026-11-30", "source": "t65_fixture", **params})


def test_all_market_weekly_matches_t65_expected(client):
    res = get(client, metric_code="posting_count")
    assert res.status_code == 200
    body = res.json()
    assert _points(body) == _expected(1, "posting_count")
    assert body["source"] == {"code": "t65_fixture", "name": "T65 합성 지표 fixture"} and body["unit"] == "count"


def test_role_weekly_and_monthly(client, ids):
    backend = str(ids["roles"]["BACKEND_ENGINEER"])
    assert _points(get(client, metric_code="posting_count", job_role_id=backend).json()) == \
        _expected(1, "posting_count", "BACKEND_ENGINEER")
    monthly = get(client, metric_code="posting_count", job_role_id=backend, period="month").json()
    assert _points(monthly) == _expected(2, "posting_count", "BACKEND_ENGINEER")


def test_skill_share_with_separate_forecast(client, ids):
    body = get(client, metric_code="skill_demand_share", job_role_id=str(ids["roles"]["BACKEND_ENGINEER"]),
               skill_id=str(ids["skills"]["PYTHON"])).json()
    assert _points(body) == _expected(1, "skill_demand_share", "BACKEND_ENGINEER", "PYTHON")
    assert body["unit"] == "ratio" and body["skill"]["code"] == "PYTHON" and body["job_role"]["code"] == "BACKEND_ENGINEER"
    assert body["forecasts"] == [{"date": "2026-11-09", "value": 0.7, "lower_bound": 0.6, "upper_bound": 0.8}]


def test_latest_forecast_model_only(client):
    body = get(client, metric_code="posting_count").json()
    assert body["forecast_model"] == {"model_code": "market_naive", "version": "2", "kind": "rule"}
    assert [(p["date"], p["value"], p["lower_bound"]) for p in body["forecasts"]] == [
        ("2026-11-09", 2.5, 1.5), ("2026-11-16", 2.4, None)]


def test_range_filter_and_empty_result(client):
    body = get(client, metric_code="posting_count", **{"from": "2026-10-12", "to": "2026-10-19"}).json()
    assert [d for d, _ in _points(body)] == ["2026-10-12", "2026-10-19"]
    empty = get(client, metric_code="posting_count", **{"from": "2025-01-01", "to": "2025-01-31"}).json()
    assert empty["observations"] == [] and empty["forecasts"] == [] and empty["source"]["code"] == "t65_fixture"


def test_source_auto_selection_and_ambiguity(client):
    # 10-05 주에는 두 출처 모두 관측값이 있어 출처 지정이 필요하다
    ambiguous = client.get(URL, params={"metric_code": "posting_count", "from": "2026-10-05", "to": "2026-10-11"})
    assert ambiguous.status_code == 422
    # 10-12 이후에는 t65_fixture만 있으므로 자동 선택
    auto = client.get(URL, params={"metric_code": "posting_count", "from": "2026-10-12", "to": "2026-10-31"})
    assert auto.status_code == 200 and auto.json()["source"]["code"] == "t65_fixture"
    second = get(client, metric_code="posting_count", source="t67_second").json()
    assert _points(second) == [("2026-10-05", 3.0)]


def test_unknown_role_and_source_are_404(client):
    assert get(client, metric_code="posting_count", job_role_id=str(uuid.uuid4())).status_code == 404
    assert get(client, metric_code="posting_count", source="nope").status_code == 404
