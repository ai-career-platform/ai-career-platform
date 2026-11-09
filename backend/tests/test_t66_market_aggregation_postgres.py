"""T66 시장 관측 지표 집계 Pipeline — 실제 PostgreSQL 테스트.

T65 fixture(database/market_metrics/t65_fixture.sql)에 집계 job을 돌린 뒤
1) 적재 결과가 T65 손 계산 정답과 같은지, 2) 검산 SQL(verify_observations.sql)이 차이 0인지,
3) 재실행·늦은 데이터·취소·기존 중복에서도 중복 0인지 확인한다.

T15_TEST_DATABASE_URL에 **일회용** PostgreSQL URL을 지정한다(career 스키마를 지우고 다시 만든다).
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app import market_aggregation as agg
from app.core.config import DatabaseSettings, get_settings
from app.db import create_db_engine

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("T15_TEST_DATABASE_URL")
MIGRATIONS = sorted((REPO / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
SEED_SQL = REPO / "database/seeds/0001_initial_seed.sql"
METRICS_DIR = REPO / "database/market_metrics"
FIXTURE_SQL = METRICS_DIR / "t65_fixture.sql"
VERIFY_SQL = (METRICS_DIR / "verify_observations.sql").read_text(encoding="utf-8")
EXPECTED = json.loads((METRICS_DIR / "t65_expected.json").read_text(encoding="utf-8"))
SOURCE = EXPECTED["source_code"]

pytestmark = pytest.mark.skipif(not DB_URL, reason="T15_TEST_DATABASE_URL not set")

AS_OF_S1 = datetime.fromisoformat("2026-11-02T09:00:00+09:00")
AS_OF_S2 = datetime.fromisoformat("2026-11-10T09:00:00+09:00")


@pytest.fixture
def engine() -> Engine:
    """테스트마다 스키마를 새로 만든다 (공고를 바꾸는 테스트가 있어 서로 영향을 주지 않게)."""
    eng = create_db_engine(DatabaseSettings(url=DB_URL, pool_size=2, timeout=5))
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for sql_file in [*MIGRATIONS, SEED_SQL, FIXTURE_SQL]:
            conn.exec_driver_sql(sql_file.read_text(encoding="utf-8").replace("%", "%%"))
    yield eng
    eng.dispose()


def run(engine, **kwargs) -> agg.AggregationResult:
    with Session(engine) as session, session.begin():
        return agg.aggregate(session, source_code=SOURCE, period=kwargs.pop("period", "week"), **kwargs)


def source_id(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT source_id FROM career.data_sources WHERE code = :c"), {"c": SOURCE}).scalar_one()


def stored(engine, period="week") -> list[tuple]:
    """적재된 행을 (observed_on, metric, role_code, skill_code, value) 목록으로."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT o.observed_on, o.metric_code, r.code AS role, s.code AS skill, o.metric_value "
            "FROM career.market_observations o "
            "LEFT JOIN career.job_roles r ON r.job_role_id = o.job_role_id "
            "LEFT JOIN career.skills s ON s.skill_id = o.skill_id "
            "WHERE o.period = :p ORDER BY 1, 2, 3 NULLS FIRST, 4 NULLS FIRST"), {"p": period}).all()
    return [(d.isoformat(), m, role, skill, v) for d, m, role, skill, v in rows]


def expected(index: int) -> list[tuple]:
    rows = [(d, m, role, skill, Decimal(v)) for d, m, role, skill, v in EXPECTED["scenarios"][index]["rows"]]
    return sorted(rows, key=lambda r: (r[0], r[1], r[2] or "", r[3] or ""))


def verify(engine, *, period="week", range_start, range_end, as_of) -> list:
    with engine.connect() as conn:
        return conn.execute(text(VERIFY_SQL), {
            "source_id": source_id(engine), "period": period, "range_start": range_start,
            "range_end": range_end, "as_of": as_of, "min_sample": agg.MIN_SAMPLE,
        }).all()


def count_rows(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM career.market_observations")).scalar_one()


def test_backfill_matches_hand_calculated_and_verify_is_zero(engine):
    result = run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
    assert (result.range_start, result.range_end) == (date(2026, 10, 5), date(2026, 11, 9))
    assert result.inserted == len(EXPECTED["scenarios"][1]["rows"]) and result.deleted == 0
    assert stored(engine) == expected(1)
    assert verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=AS_OF_S2) == []


def test_monthly_backfill_matches_hand_calculated(engine):
    run(engine, period="month", as_of=AS_OF_S2, lookback=1)  # 10월 한 구간
    assert stored(engine, "month") == expected(2)
    assert verify(engine, period="month", range_start=date(2026, 10, 1), range_end=date(2026, 11, 1), as_of=AS_OF_S2) == []


def test_rerun_three_times_creates_no_duplicates(engine):
    first = run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
    snapshot = stored(engine)
    for _ in range(2):
        again = run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
        assert (again.deleted, again.inserted) == (first.inserted, first.inserted)
    assert stored(engine) == snapshot and count_rows(engine) == first.inserted
    dups = [r for r in verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=AS_OF_S2)
            if r.check_name == "duplicate_key"]
    assert dups == []


def test_incremental_run_touches_only_last_two_weeks(engine):
    """11-02 기준 초기 적재 후 11-10 기준 정기 실행 = 11-10 기준 전체 계산 (계약 §4, 1~3주차 고정)."""
    run(engine, as_of=AS_OF_S1, backfill_from=date(2026, 10, 5))
    assert stored(engine) == expected(0)
    incremental = run(engine, as_of=AS_OF_S2)
    assert (incremental.range_start, incremental.range_end) == (date(2026, 10, 26), date(2026, 11, 9))
    assert incremental.deleted == 0  # 4주차는 S1 때 빈 구간이라 행이 없었다
    assert stored(engine) == expected(1)
    assert verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=AS_OF_S2) == []


def _add_late_posting(engine):
    """1주차(10-06)에 게시됐지만 11-11에야 수집된 공고. 정기 재계산 창(최근 2주) 밖이다."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO career.job_postings (job_posting_id, company_id, job_role_id, source_id, title, status, "
            "published_at, created_at, updated_at) "
            "SELECT md5('t66:late')::uuid, md5('t65:company')::uuid, NULL, md5('t65:source')::uuid, 'T66 late', "
            "'published', '2026-10-06 10:00+09', '2026-11-11 09:00+09', '2026-11-11 09:00+09'"))


def test_late_data_outside_window_stays_frozen_until_backfill(engine):
    run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
    _add_late_posting(engine)
    as_of = datetime.fromisoformat("2026-11-12T09:00:00+09:00")
    run(engine, as_of=as_of)  # 창: [10-26, 11-09)
    assert ("2026-10-05", "posting_count", None, None, Decimal(7)) in stored(engine)  # 고정
    assert verify(engine, range_start=date(2026, 10, 26), range_end=date(2026, 11, 9), as_of=as_of) == []

    # 같은 as_of로 전체를 검산하면 고정된 1주차의 차이를 찾아낸다
    diff = verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=as_of)
    assert {(r.check_name, r.observed_on, r.job_role_id) for r in diff
            if r.check_name == "posting_count_mismatch"} == {("posting_count_mismatch", date(2026, 10, 5), None)}

    run(engine, as_of=as_of, backfill_from=date(2026, 10, 5))  # 운영자가 명시적으로 다시 계산
    assert ("2026-10-05", "posting_count", None, None, Decimal(8)) in stored(engine)
    assert verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=as_of) == []


def test_cancelled_posting_inside_window_is_removed_on_next_run(engine):
    run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
    with engine.begin() as conn:  # p10이 게시 취소되어 작성 중(draft)으로 돌아감
        conn.execute(text("UPDATE career.job_postings SET status = 'draft' WHERE job_posting_id = md5('t65:posting:p10')::uuid"))
    run(engine, as_of=AS_OF_S2)
    rows = stored(engine)
    assert ("2026-11-02", "posting_count", None, None, Decimal(1)) in rows
    assert ("2026-11-02", "posting_count", "BACKEND_ENGINEER", None, Decimal(0)) in rows
    assert verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=AS_OF_S2) == []


def test_existing_null_role_duplicates_are_cleaned(engine):
    """DB가 막지 못하는 전체 시장 NULL 중복(계약 §5)이 이미 있어도 재계산 후에는 1행만 남는다."""
    run(engine, as_of=AS_OF_S2, backfill_from=date(2026, 10, 5))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO career.market_observations (source_id, observed_on, period, metric_code, metric_value) "
            "VALUES (md5('t65:source')::uuid, '2026-11-02', 'week', 'posting_count', 99)"))
    dup = verify(engine, range_start=date(2026, 10, 26), range_end=date(2026, 11, 9), as_of=AS_OF_S2)
    assert {r.check_name for r in dup} == {"duplicate_key", "posting_count_mismatch"}
    run(engine, as_of=AS_OF_S2)
    assert stored(engine) == expected(1)
    assert verify(engine, range_start=date(2026, 10, 5), range_end=date(2026, 11, 9), as_of=AS_OF_S2) == []


def test_dry_run_writes_nothing(engine):
    with Session(engine) as session:
        result = agg.aggregate(session, source_code=SOURCE, period="week", as_of=AS_OF_S2,
                               backfill_from=date(2026, 10, 5), dry_run=True)
        session.rollback()
    assert result.dry_run and result.inserted == len(EXPECTED["scenarios"][1]["rows"])
    assert count_rows(engine) == 0


def test_unknown_source_is_rejected(engine):
    with Session(engine) as session, pytest.raises(ValueError, match="unknown data source"):
        agg.aggregate(session, source_code="no_such_source", period="week", as_of=AS_OF_S2)


def test_cli_end_to_end(engine, monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    try:
        assert agg.main(["--source", SOURCE, "--as-of", "2026-11-10T09:00:00+09:00", "--backfill-from", "2026-10-05"]) == 0
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert "MARKET_AGGREGATION=APPLIED source=t65_fixture period=week range=[2026-10-05,2026-11-09)" in out
    assert "postgresql://" not in out
    assert stored(engine) == expected(1)
