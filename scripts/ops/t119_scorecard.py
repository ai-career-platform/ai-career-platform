#!/usr/bin/env python3
"""T119 운영 품질 점검표 — 데이터 품질·분포 변화·서비스 SLO·AI 품질·비용.

- 측정값이 없으면 **not_measured**(PASS 아님). 임계값이 없거나 근거(basis)가 none 이면 그 사실을 함께 표시한다.
- DB 측정은 읽기 전용 SELECT 만 한다(career.job_postings, career.ai_usage_records). loopback 만 허용.
- 재학습·재배포·롤백은 하지 않는다. 위반 시 할 일은 docs/ops/QUALITY_SCORECARD.md 의 플레이북.

    python scripts/ops/t119_scorecard.py --db-url postgresql://user@127.0.0.1:5432/db \
        [--previous previous.json] [--metrics t112_snapshot.json] [--budget-usd 50] --out scorecard.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS = ROOT / "docs" / "ops" / "quality" / "t119_thresholds.yaml"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def psi(expected: dict[str, float], actual: dict[str, float], floor: float = 1e-4) -> float:
    """Population Stability Index. 두 분포(비율 합 1)의 차이. 범주 합집합을 쓰고 0 은 floor 로 보정."""
    keys = set(expected) | set(actual)
    total = 0.0
    for key in keys:
        e = max(expected.get(key, 0.0), floor)
        a = max(actual.get(key, 0.0), floor)
        total += (a - e) * math.log(a / e)
    return round(total, 6)


def shares(counts: dict[str, int]) -> dict[str, float]:
    n = sum(counts.values())
    return {k: v / n for k, v in counts.items()} if n else {}


def p95_from_buckets(buckets: dict[str, int]) -> float | None:
    total = sum(buckets.values())
    if not total:
        return None
    running = 0
    for key in sorted(buckets, key=lambda k: float("inf") if k == "inf" else float(k)):
        running += buckets[key]
        if running >= 0.95 * total:
            return float("inf") if key == "inf" else float(key)
    return float("inf")


def classify(check: dict, value: float | None) -> str:
    if value is None:
        return "not_measured"
    warn, breach = check.get("warn"), check.get("breach")
    if warn is None or breach is None:
        return "no_threshold"
    above = check["direction"] == "above"
    if (value > breach) if above else (value < breach):
        return "breach"
    if (value > warn) if above else (value < warn):
        return "warn"
    return "ok"


def measure_db(url: str, now: datetime) -> dict:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    if conninfo_to_dict(url).get("host") not in LOOPBACK:
        raise SystemExit("refused: loopback (local copy or tunnel) only")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        row = conn.execute("""
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE title IS NULL OR btrim(title) = '') AS title_null,
                   count(*) FILTER (WHERE employment_type IS NULL) AS employment_null,
                   count(*) FILTER (WHERE location_text IS NULL OR btrim(location_text) = '') AS location_null,
                   count(*) FILTER (WHERE expires_at IS NULL) AS expires_null,
                   count(*) FILTER (WHERE status = 'published' AND expires_at IS NOT NULL AND expires_at < %s) AS stale,
                   max(published_at) AS latest
            FROM career.job_postings WHERE status IN ('published', 'closed')""", (now,)).fetchone()
        dupes = conn.execute("""
            SELECT coalesce(sum(c - 1), 0) FROM (
              SELECT count(*) AS c FROM career.job_postings WHERE status IN ('published', 'closed')
              GROUP BY company_id, lower(btrim(title)), date_trunc('day', published_at) HAVING count(*) > 1) d""").fetchone()[0]
        employment = dict(conn.execute("""
            SELECT coalesce(employment_type, '(null)'), count(*) FROM career.job_postings
            WHERE status IN ('published', 'closed') GROUP BY 1""").fetchall())
        cost = conn.execute("""SELECT coalesce(sum(estimated_cost_usd), 0) FROM career.ai_usage_records
                               WHERE occurred_at >= date_trunc('month', %s::timestamptz)""", (now,)).fetchone()[0]
    n, title_null, emp_null, loc_null, exp_null, stale, latest = row
    rate = (lambda x: round(x / n, 6)) if n else (lambda x: None)
    return {
        "rows": n,
        "null_rate.title": rate(title_null), "null_rate.employment_type": rate(emp_null),
        "null_rate.location_text": rate(loc_null), "null_rate.expires_at": rate(exp_null),
        "duplicate_rate": rate(int(dupes)), "stale_published_rate": rate(stale),
        "freshness_hours": round((now - latest).total_seconds() / 3600, 2) if latest else None,
        "distribution.employment_type": employment,
        "ai_cost_month_usd": float(cost),
    }


def build(measured: dict, previous: dict | None, metrics: dict | None, budget_usd: float | None,
          checks: list[dict], now: datetime, source: str) -> dict:
    values = dict(measured)
    if previous and previous.get("measured", {}).get("distribution.employment_type") and \
            measured.get("distribution.employment_type"):
        values["psi.employment_type"] = psi(shares(previous["measured"]["distribution.employment_type"]),
                                            shares(measured["distribution.employment_type"]))
    if metrics:
        total = metrics.get("requests_total") or 0
        errors = (metrics.get("by_status_class") or {}).get("5xx", 0)
        values["availability"] = round(1 - errors / total, 6) if total else None
        values["p95_ms"] = p95_from_buckets(metrics.get("latency_buckets_ms") or {})
    if budget_usd and "ai_cost_month_usd" in measured:
        values["ai_cost_budget_ratio"] = round(measured["ai_cost_month_usd"] / budget_usd, 4)
    rows = []
    for check in checks:
        value = values.get(check["metric"])
        rows.append({"id": check["id"], "area": check["area"], "metric": check["metric"], "value": value,
                     "status": classify(check, value), "basis": check["basis"], "warn": check.get("warn"),
                     "breach": check.get("breach")})
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"generated_at": now.isoformat(), "source": source, "summary": counts, "checks": rows, "measured": measured}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T119 operational quality scorecard (read-only)")
    parser.add_argument("--db-url")
    parser.add_argument("--previous")
    parser.add_argument("--metrics")
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--source", default="unspecified")
    parser.add_argument("--now")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
    checks = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))["checks"]
    measured = measure_db(args.db_url, now) if args.db_url else {}
    load = lambda p: json.loads(Path(p).read_text(encoding="utf-8")) if p else None  # noqa: E731
    card = build(measured, load(args.previous), load(args.metrics), args.budget_usd, checks, now, args.source)
    text = json.dumps(card, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"summary": card["summary"]}, ensure_ascii=False))
    return 2 if card["summary"].get("breach") else 0


if __name__ == "__main__":
    raise SystemExit(main())
