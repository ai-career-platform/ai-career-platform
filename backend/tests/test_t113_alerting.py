"""T113 장애 대응 — 경보 규칙·중복 억제·에스컬레이션·복구 알림(Mock 채널)과 실제 앱 관측 재현.

실제 메일·메신저 전송 없음. DB 장애는 닫힌 포트로, 복구는 일회용 PostgreSQL(T16 변수 있을 때)로 재현한다.
"""

import importlib.util
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("t113_alerting", ROOT / "scripts" / "ops" / "t113_alerting.py")
al = importlib.util.module_from_spec(_spec)
sys.modules["t113_alerting"] = al
_spec.loader.exec_module(al)

T0 = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
RULES = al.load_rules()
OK = dict(requests_total=200, status_5xx=0, p95_ms=200.0, health=200, health_db=200,
          ai_cost_month_usd=1.0, ai_budget_month_usd=50.0, backup_age_hours=1.0)


def engine():
    return al.AlertEngine(RULES, al.MockChannel("p"), al.MockChannel("s"))


def run(e, frames, start=T0):
    t = start
    for frame in frames:
        e.evaluate(al.Observation(at=t, **frame))
        t += MIN
    return t


def events(e, rule):
    return [x["event"] for x in e.timeline if x["rule"] == rule]


# ------------------------------------------------------------------ 규칙 정의
def test_rules_cover_db_api_ai_budget_backup_and_point_at_runbook_sections():
    ids = {r["id"] for r in RULES}
    assert {"A-DB-DOWN", "A-API-DOWN", "A-API-5XX", "A-API-LATENCY", "A-AI-PROVIDER", "A-AI-BUDGET-80",
            "A-AI-BUDGET-100", "A-BACKUP-STALE"} == ids
    runbook = (ROOT / "docs" / "ops" / "INCIDENT_RUNBOOK.md").read_text(encoding="utf-8")
    for rule in RULES:
        anchor = rule["runbook"].split("#", 1)[1]
        assert f'<a id="{anchor}"></a>' in runbook, rule["id"]
        assert rule["severity"] in al.SEVERITY_ORDER


def test_rules_reference_only_t112_observable_fields():
    obs_fields = set(al.Observation.__dataclass_fields__)
    for rule in RULES:
        for key in ("probe", "field"):
            if key in rule["params"]:
                assert rule["params"][key] in obs_fields, rule["id"]


# ------------------------------------------------------------------ 탐지·억제·에스컬레이션·복구
def test_single_blip_does_not_fire_db_alert():
    e = engine()
    run(e, [OK, dict(OK, health_db=503), OK, OK])
    assert "FIRING" not in events(e, "A-DB-DOWN") and e.primary.sent == []


def test_db_outage_fires_once_suppresses_escalates_and_resolves():
    e = engine()
    t = run(e, [dict(OK, health_db=503)] * 17)   # 2분째 FIRING, 그 뒤 15분 미확인 → 에스컬레이션
    ev = events(e, "A-DB-DOWN")
    assert ev.count("FIRING") == 1 and ev.count("SUPPRESSED") >= 10 and "ESCALATED" in ev
    assert [m["event"] for m in e.secondary.sent] == ["ESCALATED"]
    run(e, [OK], start=t)
    assert events(e, "A-DB-DOWN")[-1] == "RESOLVED"
    assert [m["event"] for m in e.primary.sent if m["rule"] == "A-DB-DOWN"] == ["FIRING", "RESOLVED"]


def test_acknowledged_critical_alert_is_not_escalated():
    e = engine()
    t = run(e, [dict(OK, health_db=503)] * 3)
    e.acknowledge("A-DB-DOWN", t, "on-call")
    run(e, [dict(OK, health_db=503)] * 20, start=t)
    assert e.secondary.sent == []


def test_long_outage_repeats_after_suppression_window():
    e = engine()
    run(e, [dict(OK, health_db=503)] * 40)
    ev = [m["event"] for m in e.primary.sent if m["rule"] == "A-DB-DOWN"]
    assert ev == ["FIRING", "REPEAT"]


def test_5xx_alert_is_inhibited_while_db_alert_fires_then_fires_alone():
    e = engine()
    t = run(e, [dict(OK, health_db=503, status_5xx=150)] * 6)
    assert "INHIBITED" in events(e, "A-API-5XX") and "FIRING" not in events(e, "A-API-5XX")
    run(e, [dict(OK, status_5xx=150)] * 4, start=t)       # DB 는 복구, 5xx 는 계속(다른 원인)
    assert "FIRING" in events(e, "A-API-5XX")


@pytest.mark.parametrize(("frame", "rule", "fires"), [
    (dict(OK, requests_total=10, status_5xx=10), "A-API-5XX", False),        # 표본 부족
    (dict(OK, requests_total=100, status_5xx=5), "A-API-5XX", False),        # 5% 경계(초과 아님)
    (dict(OK, requests_total=100, status_5xx=6), "A-API-5XX", True),
    (dict(OK, p95_ms=1000.0), "A-API-LATENCY", False),
    (dict(OK, p95_ms=2500.0), "A-API-LATENCY", True),
    (dict(OK, dependency_errors=4), "A-AI-PROVIDER", False),
    (dict(OK, dependency_errors=5), "A-AI-PROVIDER", True),
    (dict(OK, ai_cost_month_usd=39.9), "A-AI-BUDGET-80", False),
    (dict(OK, ai_cost_month_usd=40.0), "A-AI-BUDGET-80", True),
    (dict(OK, ai_cost_month_usd=50.0), "A-AI-BUDGET-100", True),
    (dict(OK, ai_budget_month_usd=None, ai_cost_month_usd=999), "A-AI-BUDGET-100", False),
    (dict(OK, backup_age_hours=24.0), "A-BACKUP-STALE", False),
    (dict(OK, backup_age_hours=24.5), "A-BACKUP-STALE", True),
    (dict(OK, backup_age_hours=None), "A-BACKUP-STALE", True),               # 백업 없음
])
def test_thresholds_and_boundaries(frame, rule, fires):
    e = engine()
    run(e, [frame] * 6)
    assert ("FIRING" in events(e, rule)) is fires


def test_p95_from_t112_buckets():
    assert al.p95_from_buckets({"50": 90, "100": 5, "250": 5, "inf": 0}) == 100.0
    assert al.p95_from_buckets({"50": 1, "inf": 99}) == float("inf")
    assert al.p95_from_buckets({}) is None


def test_messages_carry_runbook_and_no_secrets():
    e = engine()
    run(e, [dict(OK, health_db=503)] * 3)
    message = e.primary.sent[0]
    assert message["runbook"].startswith("docs/ops/INCIDENT_RUNBOOK.md#") and message["channel"] == "p"
    assert set(message) == {"at", "rule", "severity", "event", "detail", "runbook", "channel"}


# ------------------------------------------------------------------ 실제 앱 관측 → 경보
@pytest.fixture
def app_factory(monkeypatch):
    def make(database_url=None):
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("JWT_SECRET", "t113-synthetic-secret-0123456789-abcdefgh")
        monkeypatch.setenv("DB_TIMEOUT_SECONDS", "1")
        if database_url:
            monkeypatch.setenv("DATABASE_URL", database_url)
        else:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        get_settings.cache_clear()
        application = create_app()
        probe = APIRouter(prefix="/_probe")

        @probe.get("/boom")
        def boom() -> dict:
            raise RuntimeError("t113 simulated")

        application.include_router(probe, prefix=API_V1_PREFIX)
        return application
    yield make
    get_settings.cache_clear()


def test_real_app_db_unreachable_is_detected_by_health_db(app_factory):
    app = app_factory("postgresql://nobody:nopass@127.0.0.1:9/nodb")
    e = engine()
    with TestClient(app, raise_server_exceptions=False) as client:
        t = T0
        for _ in range(3):
            db = client.get("/health/db")
            assert db.status_code == 503 and db.json()["code"] == "DEPENDENCY_UNAVAILABLE"
            e.evaluate(al.Observation(at=t, health=client.get("/health").status_code, health_db=db.status_code))
            t += MIN
    assert events(e, "A-DB-DOWN")[:2] == ["FIRING", "SUPPRESSED"]
    assert "FIRING" not in events(e, "A-API-DOWN")      # 프로세스는 살아 있음 → DB 문제로 판단


@pytest.mark.skipif(os.environ.get("T16_ISOLATED_DB_TEST") != "YES", reason="isolated PostgreSQL only")
def test_real_app_db_recovery_resolves_the_alert(app_factory):
    e = engine()
    with TestClient(app_factory("postgresql://nobody:nopass@127.0.0.1:9/nodb"), raise_server_exceptions=False) as down:
        for i in range(3):
            e.evaluate(al.Observation(at=T0 + i * MIN, health=200, health_db=down.get("/health/db").status_code))
    with TestClient(app_factory(os.environ["T16_TEST_ADMIN_URL"]), raise_server_exceptions=False) as up:
        status = up.get("/health/db").status_code
        e.evaluate(al.Observation(at=T0 + 3 * MIN, health=200, health_db=status))
    assert status == 200 and events(e, "A-DB-DOWN")[-1] == "RESOLVED"


def test_real_app_5xx_metrics_feed_the_error_rate_rule(app_factory):
    app = app_factory()
    e = engine()
    with TestClient(app, raise_server_exceptions=False) as client:
        t = T0
        for _ in range(3):
            for _ in range(15):
                client.get(f"{API_V1_PREFIX}/_probe/boom")
            for _ in range(10):
                client.get("/health")
            e.evaluate(al.observation_from_snapshot(t, app.state.request_metrics.snapshot(), health=200, health_db=200))
            t += MIN
    assert "FIRING" in events(e, "A-API-5XX")


def test_rehearsal_evidence_matches_a_fresh_run():
    evidence = json.loads((ROOT / "docs" / "ops" / "T113_REHEARSAL_EVIDENCE.json").read_text(encoding="utf-8"))
    fresh = al.rehearse(datetime.fromisoformat("2026-11-11T01:00:00+00:00"))
    assert fresh == evidence
    pm = fresh["postmortems"]
    assert pm["A-DB-DOWN"]["detected_at"] and pm["A-DB-DOWN"]["resolved_at"] and pm["A-DB-DOWN"]["acknowledged_at"]
    assert pm["A-API-5XX"]["inhibited"] > 0 and pm["A-API-5XX"]["notifications"] == 0
    for rid in ("A-AI-PROVIDER", "A-AI-BUDGET-80", "A-AI-BUDGET-100", "A-BACKUP-STALE"):
        assert pm[rid]["detected_at"] and pm[rid]["resolved_at"], rid
