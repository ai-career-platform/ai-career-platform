"""T69 합성 시계열 생성기 — 실제 시장 데이터가 아니다(T65·T66 전 임시 검증용).

같은 seed면 항상 같은 값을 만든다(재현성). 값은 '주간 공고 수' 형태의 0 이상 정수.
"""

import math
import random
from datetime import date, timedelta

from app.services.market_forecast import Observation, Series

SYNTHETIC_SOURCE = "synthetic-t69-v1"


def weekly_postings(weeks: int = 52, start: date = date(2025, 11, 3), level: float = 120.0,
                    trend: float = 1.5, season_amp: float = 25.0, season: int = 4, noise: float = 6.0,
                    seed: int = 69, missing: tuple[int, ...] = (), metric_code: str = "posting_count",
                    job_role_code: str | None = "SYNTH_BACKEND") -> Series:
    """level + trend·t + 계절 패턴 + 잡음. missing에 있는 인덱스는 빈 구간(None)."""
    rng = random.Random(seed)
    obs = []
    for t in range(weeks):
        value = level + trend * t + season_amp * math.sin(2 * math.pi * t / season) + rng.gauss(0, noise)
        obs.append(Observation(start + timedelta(weeks=t), None if t in missing else float(max(0, round(value)))))
    return Series(metric_code, "week", tuple(obs), job_role_code)


def random_walk(weeks: int = 52, start: date = date(2025, 11, 3), level: float = 100.0, step: float = 8.0,
                seed: int = 7) -> Series:
    """계절·추세가 없는 무작위 걸음 — naive가 이기기 어려운 데이터 (HOLD 판정 확인용)."""
    rng = random.Random(seed)
    value, obs = level, []
    for t in range(weeks):
        value = max(0.0, value + rng.gauss(0, step))
        obs.append(Observation(start + timedelta(weeks=t), float(round(value))))
    return Series("posting_count", "week", tuple(obs), "SYNTH_RANDOM")
