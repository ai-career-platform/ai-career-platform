"""T66 시장 관측 지표 집계 — 한 번 실행하고 끝나는 배치 (스케줄은 외부에서, 별도 승인 후).

    python -m app.market_aggregation --source jobkorea --period week
    python -m app.market_aggregation --source t65_fixture --period week --as-of 2026-11-10T09:00:00+09:00 --dry-run

계약: docs/data/MARKET_METRICS_CONTRACT.md (T65)

- 값 계산은 T65 검산 SQL(`app/sql/market_reference_metrics.sql`)을 그대로 쓴다. 따라서 적재 결과는
  같은 `as_of`의 검산 결과와 차이가 0이다.
- 매 실행은 최근 `lookback`개(기본 2) 완료 구간만 다시 계산한다. 그 이전 구간은 고정한다(계약 §4).
  처음 적재하거나 오래된 구간을 고칠 때만 `--backfill-from`으로 범위를 넓힌다.
- 다시 계산하는 구간의 기존 행을 (출처, 기간 종류, 구간 범위) 단위로 지우고 같은 트랜잭션에서 다시 넣는다.
  전체 시장(job_role_id NULL) 행은 DB UNIQUE가 중복을 막지 못하므로 ON CONFLICT를 쓰지 않는다(계약 §5).
- 같은 출처·기간 종류에 대한 동시 실행은 트랜잭션 advisory lock으로 직렬화한다.
- 로그에는 출처 코드·구간·건수만 남긴다. 공고 내용·URL·DB 접속 정보는 남기지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9), "KST")  # 서머타임 없음
PERIODS = ("day", "week", "month")
DEFAULT_LOOKBACK = 2
MAX_LOOKBACK = 400  # 일 단위 1년 남짓. 실수로 전체 이력을 매번 다시 쓰지 않도록 상한을 둔다
MIN_SAMPLE = 5
SAFE_ENVS = ("local-dev", "test")

REFERENCE_SQL = (Path(__file__).with_name("sql") / "market_reference_metrics.sql").read_text(encoding="utf-8")

_DELETE = text(
    "DELETE FROM career.market_observations "
    "WHERE source_id = :source_id AND period = :period "
    "AND observed_on >= :range_start AND observed_on < :range_end"
)
_COUNT = text(
    "SELECT count(*) FROM career.market_observations "
    "WHERE source_id = :source_id AND period = :period "
    "AND observed_on >= :range_start AND observed_on < :range_end"
)
_INSERT = text(
    "INSERT INTO career.market_observations "
    "(source_id, job_role_id, skill_id, observed_on, period, metric_code, metric_value) "
    "VALUES (:source_id, :job_role_id, :skill_id, :observed_on, :period, :metric_code, :metric_value)"
)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtext('t66.market_aggregation'), hashtext(:key))")


@dataclass(frozen=True)
class AggregationResult:
    source_code: str
    period: str
    range_start: date
    range_end: date
    as_of: datetime
    deleted: int
    inserted: int
    dry_run: bool

    def summary(self) -> str:
        mode = "DRY_RUN" if self.dry_run else "APPLIED"
        return (f"MARKET_AGGREGATION={mode} source={self.source_code} period={self.period} "
                f"range=[{self.range_start},{self.range_end}) as_of={self.as_of.isoformat()} "
                f"deleted={self.deleted} inserted={self.inserted}")


def period_start(day: date, period: str) -> date:
    """KST 날짜가 속한 구간의 시작일 (주=월요일, 월=1일)."""
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    raise ValueError(f"period must be one of {PERIODS}")


def shift_periods(start: date, period: str, n: int) -> date:
    if period == "day":
        return start + timedelta(days=n)
    if period == "week":
        return start + timedelta(weeks=n)
    if period == "month":
        months = start.year * 12 + (start.month - 1) + n
        return date(months // 12, months % 12 + 1, 1)
    raise ValueError(f"period must be one of {PERIODS}")


def recompute_window(as_of: datetime, period: str, lookback: int = DEFAULT_LOOKBACK,
                     backfill_from: date | None = None) -> tuple[date, date]:
    """다시 계산할 [시작, 끝). 끝 = as_of가 속한(아직 진행 중인) 구간의 시작일."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not 1 <= lookback <= MAX_LOOKBACK:
        raise ValueError(f"lookback must be between 1 and {MAX_LOOKBACK}")
    end = period_start(as_of.astimezone(KST).date(), period)
    start = shift_periods(end, period, -lookback)
    if backfill_from is not None:
        start = min(start, period_start(backfill_from, period))
    return start, end


def aggregate(session: Session, *, source_code: str, period: str, as_of: datetime,
              lookback: int = DEFAULT_LOOKBACK, backfill_from: date | None = None,
              min_sample: int = MIN_SAMPLE, dry_run: bool = False) -> AggregationResult:
    """호출한 쪽의 트랜잭션 안에서 한 출처·한 기간 종류를 다시 계산해 적재한다. commit은 호출자가 한다."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    if min_sample < 1:
        raise ValueError("min_sample must be positive")
    range_start, range_end = recompute_window(as_of, period, lookback, backfill_from)

    source_id = session.execute(
        text("SELECT source_id FROM career.data_sources WHERE code = :code"), {"code": source_code}
    ).scalar_one_or_none()
    if source_id is None:
        raise ValueError("unknown data source code")

    session.execute(_LOCK, {"key": f"{source_id}:{period}"})
    window = {"source_id": source_id, "period": period, "range_start": range_start, "range_end": range_end}
    rows = session.execute(text(REFERENCE_SQL), {**window, "as_of": as_of, "min_sample": min_sample}).mappings().all()

    if dry_run:
        existing = session.execute(_COUNT, window).scalar_one()
        return AggregationResult(source_code, period, range_start, range_end, as_of, existing, len(rows), True)

    deleted = session.execute(_DELETE, window).rowcount
    if rows:
        session.execute(_INSERT, [
            {k: r[k] for k in ("source_id", "job_role_id", "skill_id", "observed_on", "period",
                               "metric_code", "metric_value")}
            for r in rows
        ])
    return AggregationResult(source_code, period, range_start, range_end, as_of, deleted, len(rows), False)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.market_aggregation", description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="data_sources.code (예: jobkorea, t65_fixture)")
    parser.add_argument("--period", choices=PERIODS, default="week")
    parser.add_argument("--as-of", type=datetime.fromisoformat, default=None,
                        help="기준 시각 ISO 8601 (시간대 필수). 생략하면 현재 시각")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    parser.add_argument("--backfill-from", type=date.fromisoformat, default=None)
    parser.add_argument("--min-sample", type=int, default=MIN_SAMPLE)
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 쓰지 않는다")
    parser.add_argument("--approval", default=None,
                        help="APP_ENV가 local-dev/test가 아닐 때 필요한 승인 번호 (예: REDMINE-1598)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from app.core.config import get_settings
    from app.db import create_db_engine, create_session_factory

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args(argv)
    as_of = args.as_of or datetime.now(timezone.utc)
    app_env = os.environ.get("APP_ENV", "local-dev")
    if app_env not in SAFE_ENVS and not args.dry_run and not args.approval:
        # 공유 Staging·운영 DB 쓰기는 승인 후에만 (작업지시서 §5: 무승인 Staging 정기 작업 금지)
        raise SystemExit(f"APP_ENV={app_env}: writing requires --approval (or use --dry-run)")

    settings = get_settings()
    if settings.database is None:
        raise SystemExit("DATABASE_URL is required")
    engine = create_db_engine(settings.database)
    try:
        with create_session_factory(engine)() as session:
            try:
                result = aggregate(session, source_code=args.source, period=args.period, as_of=as_of,
                                   lookback=args.lookback, backfill_from=args.backfill_from,
                                   min_sample=args.min_sample, dry_run=args.dry_run)
            except Exception:
                session.rollback()
                raise
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    finally:
        engine.dispose()
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
