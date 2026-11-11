"""T119 운영 품질 점검표 — 분포 변화(PSI)·판정·측정 누락 처리·임계값 근거 표시, 일회용 PostgreSQL 실측."""

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("t119_scorecard", ROOT / "scripts" / "ops" / "t119_scorecard.py")
sc = importlib.util.module_from_spec(_spec)
sys.modules["t119_scorecard"] = sc
_spec.loader.exec_module(sc)

CHECKS = yaml.safe_load(sc.THRESHOLDS.read_text(encoding="utf-8"))["checks"]
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)


# ------------------------------------------------------------------ PSI
def test_psi_is_zero_for_identical_and_grows_with_shift():
    base = {"full_time": 0.6, "contract": 0.3, "intern": 0.1}
    assert sc.psi(base, base) == 0
    small = sc.psi(base, {"full_time": 0.55, "contract": 0.35, "intern": 0.1})
    large = sc.psi(base, {"full_time": 0.2, "contract": 0.7, "intern": 0.1})
    assert 0 < small < 0.1 < 0.25 < large


def test_psi_handles_new_and_missing_categories():
    assert sc.psi({"a": 1.0}, {"a": 0.5, "b": 0.5}) > 0.25
    assert sc.shares({"a": 3, "b": 1}) == {"a": 0.75, "b": 0.25} and sc.shares({}) == {}


# ------------------------------------------------------------------ 판정
@pytest.mark.parametrize(("direction", "value", "expected"), [
    ("above", 0.05, "ok"), ("above", 0.21, "warn"), ("above", 0.5, "breach"), ("above", 0.4, "warn"),
    ("below", 0.999, "ok"), ("below", 0.992, "warn"), ("below", 0.98, "breach"),
])
def test_classify_boundaries(direction, value, expected):
    check = {"direction": direction, "warn": 0.2 if direction == "above" else 0.995,
             "breach": 0.4 if direction == "above" else 0.99}
    assert sc.classify(check, value) == expected


def test_missing_value_is_not_measured_and_missing_threshold_is_flagged():
    assert sc.classify({"direction": "above", "warn": 1, "breach": 2}, None) == "not_measured"
    assert sc.classify({"direction": "above", "warn": None, "breach": None}, 3) == "no_threshold"


def test_without_metrics_or_budget_slo_and_cost_are_not_measured_never_ok():
    card = sc.build({"rows": 0}, None, None, None, CHECKS, NOW, "test")
    by_id = {c["id"]: c for c in card["checks"]}
    for check_id in ("SLO-AVAILABILITY", "SLO-P95", "COST-AI-BUDGET", "AI-RANKING-QUALITY", "DQ-DRIFT-EMPLOYMENT"):
        assert by_id[check_id]["status"] == "not_measured", check_id
    assert "ok" not in card["summary"] or card["summary"]["ok"] == 0


def test_slo_from_t112_snapshot():
    metrics = {"requests_total": 1000, "by_status_class": {"2xx": 990, "5xx": 10},
               "latency_buckets_ms": {"50": 900, "100": 80, "250": 20, "inf": 0}}
    card = sc.build({}, None, metrics, None, CHECKS, NOW, "test")
    by_id = {c["id"]: c for c in card["checks"]}
    assert by_id["SLO-AVAILABILITY"]["value"] == 0.99 and by_id["SLO-AVAILABILITY"]["status"] == "warn"
    assert by_id["SLO-P95"]["value"] == 100.0 and by_id["SLO-P95"]["status"] == "ok"


# ------------------------------------------------------------------ 임계값 정직성
def test_thresholds_declare_their_basis_and_ai_quality_has_none():
    assert {c["basis"] for c in CHECKS} <= {"measured", "candidate", "synthetic", "none"}
    assert not [c for c in CHECKS if c["basis"] == "measured"], "실측 기준선이 없는데 measured 로 표시하면 안 됨"
    for check in CHECKS:
        if check["basis"] == "none":
            assert check.get("note"), check["id"]
    ai = next(c for c in CHECKS if c["id"] == "AI-RANKING-QUALITY")
    assert ai["warn"] is None and ai["breach"] is None


def test_committed_synthetic_runs_are_labelled_and_show_drift():
    run1 = json.loads((ROOT / "docs/ops/quality/T119_SCORECARD_SYNTHETIC_RUN1.json").read_text(encoding="utf-8"))
    run2 = json.loads((ROOT / "docs/ops/quality/T119_SCORECARD_SYNTHETIC_RUN2.json").read_text(encoding="utf-8"))
    assert "synthetic" in run1["source"] and "synthetic" in run2["source"]
    drift = next(c for c in run2["checks"] if c["id"] == "DQ-DRIFT-EMPLOYMENT")
    assert drift["status"] == "breach" and drift["value"] > 0.25
    assert next(c for c in run1["checks"] if c["id"] == "AI-RANKING-QUALITY")["status"] == "not_measured"


def test_remote_database_is_refused():
    with pytest.raises(SystemExit, match="loopback"):
        sc.measure_db("postgresql://u@192.0.2.20:5432/career", NOW)


# ------------------------------------------------------------------ 일회용 PostgreSQL 실측
from tests.security.security_pg import disposable_pg, requires_pg  # noqa: E402


@pytest.fixture
def pg(monkeypatch):
    import os
    for ctx in disposable_pg(monkeypatch, write_tables=(), migrations=("0001", "0002", "0003")):
        yield ctx.db, os.environ["T16_TEST_ADMIN_URL"]


@requires_pg
def test_measure_db_reports_rates_and_detects_added_duplicates_and_stale_rows(pg):
    db, url = pg
    source = db.execute("SELECT source_id FROM career.data_sources LIMIT 1").fetchone()[0]
    company = db.execute("INSERT INTO career.companies (name, source_id) VALUES ('T119 합성', %s) RETURNING company_id",
                         (source,)).fetchone()[0]
    for title, expires in [("중복 공고", NOW + timedelta(days=5)), ("중복 공고", NOW + timedelta(days=5)),
                           ("마감 지난 공고", NOW - timedelta(days=2))]:
        db.execute("""INSERT INTO career.job_postings (company_id, source_id, title, status, published_at, expires_at)
                      VALUES (%s, %s, %s, 'published', %s, %s)""", (company, source, title, NOW - timedelta(days=3), expires))
    before = db.execute("SELECT count(*) FROM career.job_postings").fetchone()[0]
    measured = sc.measure_db(url, NOW)
    assert db.execute("SELECT count(*) FROM career.job_postings").fetchone()[0] == before   # 읽기 전용
    assert measured["rows"] >= 3
    assert measured["duplicate_rate"] >= 1 / measured["rows"]
    assert measured["stale_published_rate"] >= 1 / measured["rows"]
    for key in ("null_rate.title", "null_rate.employment_type", "null_rate.location_text", "null_rate.expires_at"):
        assert 0 <= measured[key] <= 1, key
    assert measured["freshness_hours"] is not None and measured["freshness_hours"] >= 72
