"""T69 채용시장 추세 예측 Baseline — 순수 계산 모듈 (DB·API·외부 호출 없음).

FR-ANL-005 / F-024 / AI_SYSTEM_ARCHITECTURE ML05.
선행 T65(지표 계약)·T66(집계 Pipeline)이 아직 없어 **합성 시계열**로만 검증한다(mock 범위).

구성
- 기준 모델 4종: naive(직전 값), seasonal_naive(한 주기 전 값), moving_average(최근 k개 평균), drift(첫·끝 기울기)
- rolling-origin 백테스트: 각 기준 시점(origin)마다 그 시점 **이하** 관측만으로 학습하고 다음 h개를 예측
- 지표: MAE, WAPE, sMAPE (0 처리 규칙 포함)
- 판정: 후보 모델이 naive 기준선을 정해진 비율 이상 이기지 못하거나, 데이터·fold가 부족하면 HOLD
- 재현성: 같은 입력이면 같은 결과, 입력 지문(sha256)과 설정을 모델 버전 정보에 남김

누수 방지: 모든 예측 함수는 `as_of`(판단 시점)를 받고, 그 이후 날짜의 관측이 섞여 들어오면 LeakageError.
예측은 합성 데이터 기준 단순 기준선이며 **장기 고용 전망이나 확정 사실이 아니다**(T69 §5).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

MODEL_CODE = "market_trend_baseline"
MODEL_VERSION = "t69-baseline-1"
MODEL_KIND = "rule"
LIMITATION = "합성 데이터로 검증한 단순 기준선 예측이며, 확정된 시장 전망이나 채용 보장이 아닙니다."
PERIODS = {"day": 1, "week": 7}  # month는 길이가 달라 별도 처리
INTERVAL_Z = 1.2816  # 약 80% 범위(정규 근사). 보장값이 아니라 표시용 범위.


class ForecastError(ValueError):
    """입력이 계약을 어김."""


class LeakageError(ForecastError):
    """판단 시점 이후의 관측이 학습 입력에 들어옴."""


@dataclass(frozen=True)
class Observation:
    observed_on: date
    value: float | None  # None = 데이터 없는 구간 (FR-ANL-005 수용 기준 3)


@dataclass(frozen=True)
class Series:
    metric_code: str
    period: str  # day / week / month
    observations: tuple[Observation, ...]
    job_role_code: str | None = None  # None = 전체 시장

    def values(self) -> list[float | None]:
        return [o.value for o in self.observations]

    def dates(self) -> list[date]:
        return [o.observed_on for o in self.observations]


@dataclass(frozen=True)
class ForecastPoint:
    forecast_for: date
    predicted_value: float
    lower_bound: float | None
    upper_bound: float | None


@dataclass(frozen=True)
class ModelScore:
    model: str
    folds: int
    mae: float | None
    wape: float | None
    smape: float | None


@dataclass(frozen=True)
class EvaluationReport:
    metric_code: str
    period: str
    job_role_code: str | None
    horizon: int
    min_train: int
    folds: int
    scores: tuple[ModelScore, ...]
    best_model: str | None
    improvement_vs_naive: float | None  # (naive MAE - best MAE) / naive MAE
    verdict: str  # PASS / HOLD
    reasons: tuple[str, ...]
    model_version: dict = field(default_factory=dict)
    limitation: str = LIMITATION


# ---------------------------------------------------------------- 입력 검증

def _next_date(d: date, period: str) -> date:
    if period == "month":
        return date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    return d + timedelta(days=PERIODS[period])


def validate_series(series: Series) -> None:
    if not isinstance(series.metric_code, str) or not series.metric_code.strip():
        raise ForecastError("metric_code가 비어 있습니다")
    if series.period not in ("day", "week", "month"):
        raise ForecastError("period는 day/week/month 중 하나여야 합니다")
    obs = series.observations
    if not obs:
        raise ForecastError("관측이 없습니다")
    for prev, cur in zip(obs, obs[1:]):
        if cur.observed_on != _next_date(prev.observed_on, series.period):
            raise ForecastError("관측 날짜는 빈틈·중복 없이 period 간격으로 정렬돼야 합니다 (빈 구간은 value=None)")
    if series.period == "month" and any(o.observed_on.day != 1 for o in obs):
        raise ForecastError("month 관측은 매월 1일 기준이어야 합니다")
    for o in obs:
        if o.value is None:
            continue
        if isinstance(o.value, bool) or not isinstance(o.value, (int, float)) or not math.isfinite(o.value) or o.value < 0:
            raise ForecastError("관측값은 0 이상의 유한한 숫자여야 합니다")


def history_as_of(series: Series, as_of: date) -> Series:
    """판단 시점(as_of) 이하의 관측만 남긴 사본."""
    return Series(series.metric_code, series.period,
                  tuple(o for o in series.observations if o.observed_on <= as_of), series.job_role_code)


def _guard(history: Series, as_of: date) -> list[float]:
    if any(o.observed_on > as_of for o in history.observations):
        raise LeakageError(f"as_of {as_of} 이후 관측이 학습 입력에 포함됐습니다")
    vals = [v for v in history.values() if v is not None]
    if not vals:
        raise ForecastError("as_of 이전에 사용할 관측이 없습니다")
    return vals


# ---------------------------------------------------------------- 기준 모델 (값 목록 → h개 점예측)

def naive(vals: Sequence[float], h: int, **_) -> list[float]:
    return [vals[-1]] * h


def seasonal_naive(vals: Sequence[float], h: int, season: int = 4, **_) -> list[float]:
    if len(vals) < season:
        return naive(vals, h)
    last = list(vals[-season:])
    return [last[i % season] for i in range(h)]


def moving_average(vals: Sequence[float], h: int, window: int = 4, **_) -> list[float]:
    w = list(vals[-window:])
    return [sum(w) / len(w)] * h


def drift(vals: Sequence[float], h: int, **_) -> list[float]:
    if len(vals) < 2:
        return naive(vals, h)
    slope = (vals[-1] - vals[0]) / (len(vals) - 1)
    return [max(0.0, vals[-1] + slope * (i + 1)) for i in range(h)]


MODELS: dict[str, Callable[..., list[float]]] = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "moving_average": moving_average,
    "drift": drift,
}


def forecast(history: Series, as_of: date, horizon: int, model: str = "seasonal_naive",
             season: int = 4, window: int = 4) -> list[ForecastPoint]:
    """as_of까지의 관측만으로 다음 horizon개 기간을 예측. 범위는 1-step 잔차 기반 근사(약 80%)."""
    if model not in MODELS:
        raise ForecastError(f"알 수 없는 모델: {model}")
    if type(horizon) is not int or not 1 <= horizon <= 52:
        raise ForecastError("horizon은 1~52 정수여야 합니다")
    validate_series(history)
    vals = _guard(history, as_of)
    fn = MODELS[model]
    points = fn(vals, horizon, season=season, window=window)
    # 학습 구간 안에서의 1-step 예측 잔차로 범위 폭 추정 (미래 값 사용 안 함)
    residuals = [vals[i] - fn(vals[:i], 1, season=season, window=window)[0] for i in range(1, len(vals))]
    sigma = math.sqrt(sum(r * r for r in residuals) / len(residuals)) if residuals else None
    last = max(o.observed_on for o in history.observations)
    out, d = [], last
    for step, p in enumerate(points, start=1):
        d = _next_date(d, history.period)
        if sigma is None:
            lo = hi = None
        else:
            width = INTERVAL_Z * sigma * math.sqrt(step)
            lo, hi = max(0.0, p - width), p + width
        out.append(ForecastPoint(d, round(p, 6), None if lo is None else round(lo, 6), None if hi is None else round(hi, 6)))
    return out


# ---------------------------------------------------------------- 지표

def mae(actual: Sequence[float], pred: Sequence[float]) -> float | None:
    pairs = list(zip(actual, pred))
    return sum(abs(a - p) for a, p in pairs) / len(pairs) if pairs else None


def wape(actual: Sequence[float], pred: Sequence[float]) -> float | None:
    """Σ|오차| / Σ|실제|. 실제 합이 0이면 정의 불가 → None."""
    denom = sum(abs(a) for a in actual)
    if not actual or denom == 0:
        return None
    return sum(abs(a - p) for a, p in zip(actual, pred)) / denom


def smape(actual: Sequence[float], pred: Sequence[float]) -> float | None:
    """평균 2|a-p|/(|a|+|p|). 둘 다 0인 항은 오차 0으로 본다. 범위 0~2."""
    if not actual:
        return None
    terms = [0.0 if a == 0 and p == 0 else 2 * abs(a - p) / (abs(a) + abs(p)) for a, p in zip(actual, pred)]
    return sum(terms) / len(terms)


# ---------------------------------------------------------------- 백테스트·판정

def fingerprint(series: Series) -> str:
    payload = json.dumps([series.metric_code, series.period, series.job_role_code,
                          [[o.observed_on.isoformat(), o.value] for o in series.observations]],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def backtest(series: Series, horizon: int = 4, min_train: int = 12, season: int = 4, window: int = 4,
             min_folds: int = 3, min_improvement: float = 0.05) -> EvaluationReport:
    """rolling-origin 평가. 각 fold의 학습 입력은 origin 이하 관측만(history_as_of) 사용한다."""
    validate_series(series)
    if type(min_train) is not int or min_train < max(2, season):
        raise ForecastError("min_train은 계절 주기 이상이어야 합니다")
    obs = series.observations
    actual_by_model: dict[str, list[float]] = {m: [] for m in MODELS}
    pred_by_model: dict[str, list[float]] = {m: [] for m in MODELS}
    folds = 0
    for origin_idx in range(min_train - 1, len(obs) - horizon):
        as_of = obs[origin_idx].observed_on
        train = history_as_of(series, as_of)
        test = obs[origin_idx + 1: origin_idx + 1 + horizon]
        if max(train.dates()) >= min(o.observed_on for o in test):  # 시간 역전 방지
            raise LeakageError("학습 구간이 평가 구간과 겹칩니다")
        if not [v for v in train.values() if v is not None]:
            continue
        counted = False
        for m in MODELS:
            pts = forecast(train, as_of, horizon, m, season=season, window=window)
            for o, p in zip(test, pts):
                if o.value is None:  # 빈 구간은 평가에서 제외
                    continue
                actual_by_model[m].append(o.value)
                pred_by_model[m].append(p.predicted_value)
                counted = True
        folds += counted

    scores = tuple(ModelScore(m, folds, _r(mae(actual_by_model[m], pred_by_model[m])),
                              _r(wape(actual_by_model[m], pred_by_model[m])),
                              _r(smape(actual_by_model[m], pred_by_model[m]))) for m in MODELS)
    reasons: list[str] = []
    best, improvement = None, None
    by_name = {s.model: s for s in scores}
    if folds < min_folds:
        reasons.append(f"평가 fold {folds}개 < 최소 {min_folds}개 (데이터 부족)")
    elif by_name["naive"].mae is None:
        reasons.append("평가할 실제값이 없습니다")
    else:
        candidates = [s for s in scores if s.model != "naive" and s.mae is not None]
        best_score = min(candidates, key=lambda s: (s.mae, s.model))
        best = best_score.model
        naive_mae = by_name["naive"].mae
        improvement = _r((naive_mae - best_score.mae) / naive_mae) if naive_mae else None
        if improvement is None or improvement < min_improvement:
            reasons.append(f"최선 후보 {best}가 naive 대비 MAE {min_improvement:.0%} 이상 개선하지 못함")
    verdict = "HOLD" if reasons else "PASS"
    version = {
        "model_code": MODEL_CODE, "version": MODEL_VERSION, "kind": MODEL_KIND,
        "selected_model": best if verdict == "PASS" else None,
        "config": {"horizon": horizon, "min_train": min_train, "season": season, "window": window,
                   "min_folds": min_folds, "min_improvement": min_improvement, "interval_z": INTERVAL_Z},
        "dataset_sha256": fingerprint(series),
    }
    return EvaluationReport(series.metric_code, series.period, series.job_role_code, horizon, min_train,
                            folds, scores, best, improvement, verdict, tuple(reasons), version)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def to_forecast_rows(points: Sequence[ForecastPoint], series: Series, model_version_id: str) -> list[dict]:
    """market_forecasts(F06) 행 모양으로 변환. 저장은 하지 않는다 (T66/T67 연동 후)."""
    return [{"model_version_id": model_version_id, "job_role_code": series.job_role_code,
             "forecast_for": p.forecast_for.isoformat(), "metric_code": series.metric_code,
             "predicted_value": p.predicted_value, "lower_bound": p.lower_bound, "upper_bound": p.upper_bound}
            for p in points]


def report_dict(report: EvaluationReport) -> dict:
    return asdict(report)
