"""T66 집계 job의 DB 없는 단위 테스트: 재계산 창, 입력 검증, 실행 안전장치."""

import pathlib
from datetime import date, datetime, timezone

import pytest

from app import market_aggregation as agg

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_app_sql_is_identical_to_t65_reference_sql():
    """job이 쓰는 SQL은 T65 검산 SQL 사본이다. 한쪽만 고치면 실패한다."""
    app_sql = (REPO / "backend/app/sql/market_reference_metrics.sql").read_bytes().replace(b"\r\n", b"\n")
    ref_sql = (REPO / "database/market_metrics/reference_metrics.sql").read_bytes().replace(b"\r\n", b"\n")
    assert app_sql == ref_sql


@pytest.mark.parametrize("day, period, expected", [
    (date(2026, 11, 9), "week", date(2026, 11, 9)),     # 월요일
    (date(2026, 11, 15), "week", date(2026, 11, 9)),    # 일요일
    (date(2026, 11, 15), "month", date(2026, 11, 1)),
    (date(2026, 11, 15), "day", date(2026, 11, 15)),
])
def test_period_start(day, period, expected):
    assert agg.period_start(day, period) == expected


def test_shift_months_across_year():
    assert agg.shift_periods(date(2026, 1, 1), "month", -2) == date(2025, 11, 1)
    assert agg.shift_periods(date(2025, 12, 1), "month", 1) == date(2026, 1, 1)


def test_window_uses_kst_and_excludes_running_period():
    # 2026-11-09 00:30 KST = 2026-11-08 15:30 UTC. KST로는 11-09(월) 주가 진행 중이다
    as_of = datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc)
    assert agg.recompute_window(as_of, "week") == (date(2026, 10, 26), date(2026, 11, 9))
    assert agg.recompute_window(as_of, "month") == (date(2026, 9, 1), date(2026, 11, 1))


def test_window_backfill_extends_only_backwards():
    as_of = datetime(2026, 11, 10, 9, tzinfo=agg.KST)
    assert agg.recompute_window(as_of, "week", backfill_from=date(2026, 10, 7)) == (date(2026, 10, 5), date(2026, 11, 9))
    assert agg.recompute_window(as_of, "week", backfill_from=date(2026, 11, 5)) == (date(2026, 10, 26), date(2026, 11, 9))


@pytest.mark.parametrize("kwargs", [
    {"as_of": datetime(2026, 11, 10, 9)},                                   # 시간대 없음
    {"as_of": datetime(2026, 11, 10, 9, tzinfo=agg.KST), "lookback": 0},
    {"as_of": datetime(2026, 11, 10, 9, tzinfo=agg.KST), "lookback": agg.MAX_LOOKBACK + 1},
])
def test_window_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        agg.recompute_window(period="week", **kwargs)


def test_cli_refuses_shared_env_writes_without_approval(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging-poc")
    with pytest.raises(SystemExit, match="--approval"):
        agg.main(["--source", "jobkorea", "--period", "week"])
