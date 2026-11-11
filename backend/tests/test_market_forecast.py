"""T69 채용시장 추세 예측 Baseline 테스트 — 합성 데이터만 사용 (DB·API·외부 호출 없음)."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.services.market_forecast import (
    MODEL_CODE,
    MODEL_KIND,
    MODELS,
    ForecastError,
    LeakageError,
    Observation,
    Series,
    backtest,
    drift,
    fingerprint,
    forecast,
    history_as_of,
    mae,
    moving_average,
    naive,
    seasonal_naive,
    smape,
    to_forecast_rows,
    validate_series,
    wape,
)
from app.services.market_forecast_synthetic import random_walk, weekly_postings

START = date(2025, 11, 3)


def series(values, period="week", start=START):
    obs, d = [], start
    for v in values:
        obs.append(Observation(d, v))
        if period == "week":
            d += timedelta(weeks=1)
        elif period == "day":
            d += timedelta(days=1)
        else:
            d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    return Series("posting_count", period, tuple(obs), "SYNTH")


# ---------------------------------------------------------------- 기준 모델 계산

def test_naive_repeats_last_value():
    assert naive([1, 2, 7], 3) == [7, 7, 7]


def test_seasonal_naive_repeats_last_season_and_falls_back():
    assert seasonal_naive([1, 2, 3, 4, 5, 6, 7, 8], 6, season=4) == [5, 6, 7, 8, 5, 6]
    assert seasonal_naive([1, 2], 2, season=4) == [2, 2]  # 한 주기보다 짧으면 naive


def test_moving_average_uses_last_window():
    assert moving_average([10, 20, 30, 40, 50], 2, window=4) == [35.0, 35.0]
    assert moving_average([10], 1, window=4) == [10.0]


def test_drift_extends_slope_and_never_goes_negative():
    assert drift([10, 20, 30], 2) == [40.0, 50.0]
    assert drift([30, 20, 10], 5) == [0.0, 0.0, 0.0, 0.0, 0.0]
    assert drift([5], 2) == [5, 5]


# ---------------------------------------------------------------- 지표

def test_metrics_values():
    actual, pred = [100, 200, 0], [110, 180, 0]
    assert mae(actual, pred) == pytest.approx(10.0)
    assert wape(actual, pred) == pytest.approx(30 / 300)
    assert smape(actual, pred) == pytest.approx((2 * 10 / 210 + 2 * 20 / 380 + 0) / 3)


def test_metrics_zero_and_empty_rules():
    assert wape([0, 0], [1, 2]) is None  # 실제 합 0 → 정의 불가
    assert smape([0], [0]) == 0.0
    assert smape([0], [5]) == pytest.approx(2.0)
    assert mae([], []) is None and wape([], []) is None and smape([], []) is None


# ---------------------------------------------------------------- 입력 계약

@pytest.mark.parametrize("bad, msg", [
    (Series("", "week", (Observation(START, 1.0),)), "metric_code"),
    (Series("posting_count", "year", (Observation(START, 1.0),)), "period"),
    (Series("posting_count", "week", ()), "관측이 없습니다"),
])
def test_validate_rejects_bad_metadata(bad, msg):
    with pytest.raises(ForecastError, match=msg):
        validate_series(bad)


def test_validate_rejects_gaps_duplicates_and_disorder():
    s = series([1.0, 2.0, 3.0])
    gap = Series(s.metric_code, "week", (s.observations[0], s.observations[2]))
    dup = Series(s.metric_code, "week", (s.observations[0], s.observations[0]))
    rev = Series(s.metric_code, "week", tuple(reversed(s.observations)))
    for bad in (gap, dup, rev):
        with pytest.raises(ForecastError, match="빈틈"):
            validate_series(bad)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), "10", True])
def test_validate_rejects_bad_values(value):
    with pytest.raises(ForecastError, match="0 이상의 유한한 숫자"):
        validate_series(series([1.0, value]))


def test_month_series_must_use_first_day():
    validate_series(series([1.0, 2.0, 3.0], period="month", start=date(2025, 11, 1)))
    with pytest.raises(ForecastError, match="1일"):
        validate_series(series([1.0, 2.0], period="month", start=date(2025, 11, 15)))


def test_missing_values_are_allowed_as_empty_periods():
    validate_series(series([1.0, None, 3.0]))


# ---------------------------------------------------------------- 예측

def test_forecast_dates_follow_period_and_bounds_bracket_point():
    s = weekly_postings()
    pts = forecast(s, s.observations[-1].observed_on, 3, "seasonal_naive")
    last = s.observations[-1].observed_on
    assert [p.forecast_for for p in pts] == [last + timedelta(weeks=i) for i in (1, 2, 3)]
    for p in pts:
        assert 0 <= p.lower_bound <= p.predicted_value <= p.upper_bound
    widths = [p.upper_bound - p.lower_bound for p in pts]
    assert widths == sorted(widths)  # 멀리 볼수록 범위가 넓어진다


def test_forecast_monthly_dates_roll_over_year():
    s = series([10.0, 11.0, 12.0], period="month", start=date(2025, 10, 1))
    pts = forecast(s, date(2025, 12, 1), 2, "naive")
    assert [p.forecast_for for p in pts] == [date(2026, 1, 1), date(2026, 2, 1)]


def test_forecast_lower_bound_never_negative():
    s = series([0.0, 30.0, 0.0, 30.0, 0.0, 30.0])
    for p in forecast(s, s.observations[-1].observed_on, 3, "naive"):
        assert p.lower_bound >= 0


@pytest.mark.parametrize("kwargs, msg", [({"model": "lstm"}, "알 수 없는 모델"), ({"horizon": 0}, "horizon"),
                                          ({"horizon": 53}, "horizon"), ({"horizon": 2.0}, "horizon")])
def test_forecast_rejects_bad_arguments(kwargs, msg):
    s = weekly_postings(weeks=10)
    args = {"horizon": 2, "model": "naive", **kwargs}
    with pytest.raises(ForecastError, match=msg):
        forecast(s, s.observations[-1].observed_on, args["horizon"], args["model"])


def test_forecast_requires_some_observed_value():
    with pytest.raises(ForecastError, match="사용할 관측이 없습니다"):
        forecast(series([None, None]), START + timedelta(weeks=1), 1, "naive")


# ---------------------------------------------------------------- 누수 방지

def test_future_observation_in_training_input_is_rejected():
    s = weekly_postings(weeks=20)
    as_of = s.observations[9].observed_on
    with pytest.raises(LeakageError):
        forecast(s, as_of, 2, "naive")  # 전체 시리즈(미래 포함)를 그대로 넣음
    forecast(history_as_of(s, as_of), as_of, 2, "naive")  # 잘라 넣으면 통과


@pytest.mark.parametrize("model", list(MODELS))
def test_forecast_is_unaffected_by_future_values(model):
    """판단 시점 이후 값을 아무리 바꿔도 그 시점의 예측은 같아야 한다."""
    s = weekly_postings(weeks=30)
    as_of = s.observations[19].observed_on
    tampered = Series(s.metric_code, s.period, s.observations[:20] + tuple(
        Observation(o.observed_on, 99999.0) for o in s.observations[20:]), s.job_role_code)
    a = forecast(history_as_of(s, as_of), as_of, 4, model)
    b = forecast(history_as_of(tampered, as_of), as_of, 4, model)
    assert a == b


def test_backtest_fold_results_do_not_change_when_only_last_value_changes_training():
    """마지막 관측을 바꾸면, 그 값이 학습에 쓰이지 않는 이전 fold의 예측은 그대로여야 한다."""
    s = weekly_postings(weeks=30)
    as_of = s.observations[15].observed_on
    changed = Series(s.metric_code, s.period, s.observations[:-1] + (Observation(s.observations[-1].observed_on, 0.0),),
                     s.job_role_code)
    assert forecast(history_as_of(s, as_of), as_of, 4, "drift") == forecast(history_as_of(changed, as_of), as_of, 4, "drift")


# ---------------------------------------------------------------- 백테스트·판정

def test_seasonal_data_passes_with_seasonal_model():
    r = backtest(weekly_postings())
    scores = {s.model: s for s in r.scores}
    assert r.verdict == "PASS" and r.reasons == ()
    assert r.best_model == "seasonal_naive"
    assert scores["seasonal_naive"].mae < scores["naive"].mae
    assert r.improvement_vs_naive >= 0.05
    assert r.folds == 52 - 12 - 4 + 1
    assert r.model_version["selected_model"] == "seasonal_naive"


def test_random_walk_is_hold_because_naive_is_not_beaten():
    r = backtest(random_walk())
    assert r.verdict == "HOLD"
    assert r.model_version["selected_model"] is None
    assert any("naive" in reason for reason in r.reasons)


def test_too_little_data_is_hold():
    r = backtest(weekly_postings(weeks=14))
    assert r.verdict == "HOLD" and r.folds == 0
    assert any("데이터 부족" in reason for reason in r.reasons)
    assert all(s.mae is None for s in r.scores)


def test_missing_periods_are_skipped_not_counted_as_zero():
    full = backtest(weekly_postings())
    holes = backtest(weekly_postings(missing=(20, 21, 35)))
    assert holes.verdict in ("PASS", "HOLD")
    assert all(s.mae is not None for s in holes.scores)
    assert holes.scores != full.scores  # 빈 구간이 실제로 반영됨 (0으로 채우지 않음)


def test_backtest_rejects_too_short_min_train():
    with pytest.raises(ForecastError, match="min_train"):
        backtest(weekly_postings(), min_train=3, season=4)


def test_backtest_is_reproducible_and_fingerprinted():
    a, b = backtest(weekly_postings()), backtest(weekly_postings())
    assert a == b
    assert a.model_version["dataset_sha256"] == fingerprint(weekly_postings())
    assert len(a.model_version["dataset_sha256"]) == 64
    other = backtest(weekly_postings(seed=70))
    assert other.model_version["dataset_sha256"] != a.model_version["dataset_sha256"]


def test_model_version_metadata_and_limitation():
    r = backtest(weekly_postings())
    v = r.model_version
    assert (v["model_code"], v["kind"]) == (MODEL_CODE, MODEL_KIND)
    assert v["config"]["horizon"] == 4 and v["config"]["min_improvement"] == 0.05
    assert "확정된 시장 전망" in r.limitation


def test_stricter_threshold_turns_pass_into_hold():
    r = backtest(weekly_postings(), min_improvement=0.99)
    assert r.verdict == "HOLD"


# ---------------------------------------------------------------- 저장 형태 변환

def test_to_forecast_rows_matches_market_forecasts_shape():
    s = weekly_postings()
    pts = forecast(s, s.observations[-1].observed_on, 2, "seasonal_naive")
    rows = to_forecast_rows(pts, s, "00000000-0000-4000-8000-000000000069")
    assert set(rows[0]) == {"model_version_id", "job_role_code", "forecast_for", "metric_code",
                            "predicted_value", "lower_bound", "upper_bound"}
    assert rows[0]["lower_bound"] <= rows[0]["predicted_value"] <= rows[0]["upper_bound"]


def test_committed_validation_report_matches_code():
    """docs/T69_VALIDATION_REPORT.md가 현재 코드로 다시 만든 결과와 같은지 (보고서와 코드 불일치 방지)."""
    from pathlib import Path

    from app.services.market_forecast_report import render

    committed = (Path(__file__).resolve().parents[1] / "docs" / "T69_VALIDATION_REPORT.md").read_text(encoding="utf-8")
    assert committed.strip() == render().strip()


def test_synthetic_generator_is_deterministic_and_non_negative():
    a, b = weekly_postings(), weekly_postings()
    assert a == b
    assert all(o.value >= 0 for o in a.observations)
    assert replace(a, job_role_code="X") != a
