"""T65 채용시장 지표 계약 재현 테스트 (실제 PostgreSQL 전용).

일회용 DB에 migration 0001~ 전체와 T10 Seed, T65 fixture를 넣고
`database/market_metrics/reference_metrics.sql`(검산 SQL)의 결과가
`t65_expected.json`(손 계산 정답)과 같은지 확인한다. 계약: docs/data/MARKET_METRICS_CONTRACT.md

실행: T15_TEST_DATABASE_URL에 **일회용** PostgreSQL URL을 지정한다(career 스키마를 지우고 다시 만든다).
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import DatabaseSettings
from app.db import create_db_engine

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("T15_TEST_DATABASE_URL")
MIGRATIONS = sorted((REPO / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
SEED_SQL = REPO / "database/seeds/0001_initial_seed.sql"
METRICS_DIR = REPO / "database/market_metrics"
REFERENCE_SQL = (METRICS_DIR / "reference_metrics.sql").read_text(encoding="utf-8")
FIXTURE_SQL = METRICS_DIR / "t65_fixture.sql"
EXPECTED = json.loads((METRICS_DIR / "t65_expected.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(not DB_URL, reason="T15_TEST_DATABASE_URL not set")


@pytest.fixture(scope="module")
def engine() -> Engine:
    eng = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=2, timeout=5))
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for sql_file in [*MIGRATIONS, SEED_SQL, FIXTURE_SQL]:
            conn.exec_driver_sql(sql_file.read_text(encoding="utf-8").replace("%", "%%"))
    yield eng
    eng.dispose()


def _source_id(conn, code: str):
    return conn.execute(text("SELECT source_id FROM career.data_sources WHERE code = :c"), {"c": code}).scalar_one()


def _compute(engine: Engine, scenario: dict, source_code: str = EXPECTED["source_code"]) -> list[tuple]:
    """검산 SQL을 돌려 (observed_on, metric, role_code, skill_code, value) 목록으로 바꾼다."""
    with engine.connect() as conn:
        params = {
            "source_id": _source_id(conn, source_code),
            "period": scenario["period"],
            "range_start": date.fromisoformat(scenario["range_start"]),
            "range_end": date.fromisoformat(scenario["range_end"]),
            "as_of": datetime.fromisoformat(scenario["as_of"]),
            "min_sample": EXPECTED["min_sample"],
        }
        rows = conn.execute(text(REFERENCE_SQL), params).mappings().all()
        roles = dict(conn.execute(text("SELECT job_role_id, code FROM career.job_roles")).all())
        skills = dict(conn.execute(text("SELECT skill_id, code FROM career.skills")).all())
    assert all(r["period"] == scenario["period"] for r in rows)
    return [
        (r["observed_on"].isoformat(), r["metric_code"], roles.get(r["job_role_id"]),
         skills.get(r["skill_id"]), r["metric_value"])
        for r in rows
    ]


def _expected(scenario: dict) -> list[tuple]:
    return [(d, m, role, skill, Decimal(v)) for d, m, role, skill, v in scenario["rows"]]


def _key(row: tuple) -> tuple:
    return (row[0], row[1], row[2] or "", row[3] or "")


@pytest.mark.parametrize("scenario", EXPECTED["scenarios"], ids=lambda s: s["name"].split()[0])
def test_reference_sql_matches_hand_calculated_expected(engine, scenario):
    actual = sorted(_compute(engine, scenario), key=_key)
    expected = sorted(_expected(scenario), key=_key)
    assert actual == expected


def test_rerun_gives_identical_result(engine):
    scenario = EXPECTED["scenarios"][1]
    assert _compute(engine, scenario) == _compute(engine, scenario)


def test_late_posting_changes_only_its_own_week(engine):
    """E7: 늦게 들어온 p9는 4주차만 새로 만들고 1~3주차 값은 바꾸지 않는다."""
    before = {_key(r): r for r in _compute(engine, EXPECTED["scenarios"][0])}
    after = {_key(r): r for r in _compute(engine, EXPECTED["scenarios"][1])}
    assert all(after[k] == v for k, v in before.items())
    assert {k[0] for k in after.keys() - before.keys()} == {"2026-10-26", "2026-11-02"}


def test_partial_range_equals_full_range_for_same_buckets(engine):
    """§3.3: 직무 목록이 조회 구간에 따라 바뀌지 않으므로, 최근 구간만 계산해도 전체 계산과 같다 (T66 재계산 창 전제)."""
    full = EXPECTED["scenarios"][1]
    partial = {**full, "range_start": "2026-10-26"}
    full_rows = [r for r in _compute(engine, full) if r[0] >= "2026-10-26"]
    assert sorted(_compute(engine, partial), key=_key) == sorted(full_rows, key=_key)


def test_other_sources_are_not_mixed_in(engine):
    """Seed의 synthetic_seed 공고 100건은 t65_fixture 결과에 섞이지 않는다 (§3.5 출처별 집계)."""
    scenario = {**EXPECTED["scenarios"][2], "range_start": "2026-01-01", "range_end": "2026-12-01",
                "as_of": "2026-12-05T09:00:00+09:00"}
    fixture_total = sum(r[4] for r in _compute(engine, scenario)
                        if r[1] == "posting_count" and r[2] is None)
    assert fixture_total == 12  # p1~p11 + c1 (draft d1 제외)


def _insert_observation(engine, **values):
    defaults = {"job_role_id": None, "skill_id": None, "period": "week", "observed_on": date(2026, 10, 5)}
    row = {**defaults, **values}
    with engine.begin() as conn:
        row.setdefault("source_id", _source_id(conn, EXPECTED["source_code"]))
        conn.execute(text(
            "INSERT INTO career.market_observations "
            "(source_id, job_role_id, skill_id, observed_on, period, metric_code, metric_value) "
            "VALUES (:source_id, :job_role_id, :skill_id, :observed_on, :period, :metric_code, :metric_value)"
        ), row)


def _code_id(engine, table: str, code: str):
    column = {"job_roles": "job_role_id", "skills": "skill_id"}[table]
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT {column} FROM career.{table} WHERE code = :c"), {"c": code}).scalar_one()


def test_migration_0003_constraints(engine):
    backend = _code_id(engine, "job_roles", "BACKEND_ENGINEER")
    python = _code_id(engine, "skills", "PYTHON")
    java = _code_id(engine, "skills", "JAVA")

    # 같은 직무·기간에 기술별로 여러 행을 저장할 수 있다
    _insert_observation(engine, job_role_id=backend, skill_id=python, metric_code="skill_demand_share", metric_value=Decimal("0.8"))
    _insert_observation(engine, job_role_id=backend, skill_id=java, metric_code="skill_demand_share", metric_value=Decimal("0.4"))
    _insert_observation(engine, job_role_id=backend, metric_code="posting_count", metric_value=5)

    rejected = [
        # 같은 키 중복
        dict(job_role_id=backend, skill_id=python, metric_code="skill_demand_share", metric_value=Decimal("0.5")),
        dict(job_role_id=backend, metric_code="posting_count", metric_value=6),
        # 기술 차원 짝 규칙
        dict(metric_code="skill_demand_share", metric_value=Decimal("0.5")),
        dict(skill_id=python, metric_code="posting_count", metric_value=1),
        # 값 범위
        dict(metric_code="posting_count", metric_value=Decimal("1.5")),
        dict(metric_code="posting_count", metric_value=-1),
        dict(skill_id=python, metric_code="skill_demand_share", metric_value=Decimal("1.0001")),
    ]
    for values in rejected:
        with pytest.raises(IntegrityError):
            _insert_observation(engine, **values)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM career.market_observations"))


def test_null_role_duplicates_are_left_as_is(engine):
    """PM 결정(2026-11-09): 전체 시장(job_role_id NULL) 행의 UNIQUE 중복 허용은 바꾸지 않는다.
    DB가 막지 않으므로 적재(T66)가 같은 키를 지우고 다시 넣어야 한다는 계약 §5를 고정해 둔다."""
    _insert_observation(engine, metric_code="posting_count", metric_value=1)
    _insert_observation(engine, metric_code="posting_count", metric_value=1)
    with engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM career.market_observations WHERE job_role_id IS NULL")).scalar_one()
        conn.execute(text("DELETE FROM career.market_observations"))
    assert n == 2
