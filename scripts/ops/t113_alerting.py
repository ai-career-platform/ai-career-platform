#!/usr/bin/env python3
"""T113 경보 규칙 평가·중복 억제·에스컬레이션 — **Mock 채널 전용**(실제 메일·메신저 발송 없음).

입력은 T112 관측 계약의 값이다.
- 요청 지표: RequestMetrics.snapshot() 과 같은 모양(requests_total, by_status_class, latency_buckets_ms)
- 상태 확인: /health, /health/db 응답 코드
- 오류 코드 수: app.errors 로그의 code(DEPENDENCY_UNAVAILABLE·DEPENDENCY_TIMEOUT 등)
- AI 비용: career.ai_usage_records.estimated_cost_usd 합계(월)
- 백업 신선도: T114 freshness 결과

규칙 정의는 docs/ops/alerting/alert_rules.yaml (PROPOSED 임계값).
운영 알림 채널·수신자는 승인 전이라 정의하지 않는다(채널 이름만, 전송은 MockChannel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "docs" / "ops" / "alerting" / "alert_rules.yaml"
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True)
class Observation:
    at: datetime
    requests_total: int = 0
    status_5xx: int = 0
    p95_ms: float | None = None
    health: int | None = None          # /health
    health_db: int | None = None       # /health/db
    dependency_errors: int = 0         # DEPENDENCY_UNAVAILABLE + DEPENDENCY_TIMEOUT
    ai_cost_month_usd: float = 0.0
    ai_budget_month_usd: float | None = None
    backup_age_hours: float | None = None


def p95_from_buckets(buckets: dict[str, int]) -> float | None:
    """구간 지표에서 p95 상한을 고른다(구간 상한값, 'inf' 는 무한대)."""
    total = sum(buckets.values())
    if total == 0:
        return None
    target, running = 0.95 * total, 0
    for key in sorted(buckets, key=lambda k: float("inf") if k == "inf" else float(k)):
        running += buckets[key]
        if running >= target:
            return float("inf") if key == "inf" else float(key)
    return float("inf")


def observation_from_snapshot(at: datetime, snapshot: dict, **extra) -> Observation:
    classes = snapshot.get("by_status_class", {})
    return Observation(at=at, requests_total=snapshot.get("requests_total", 0), status_5xx=classes.get("5xx", 0),
                       p95_ms=p95_from_buckets(snapshot.get("latency_buckets_ms", {})), **extra)


def load_rules(path: Path = RULES_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]


def condition(rule: dict, obs: Observation) -> tuple[bool, str]:
    kind, p = rule["kind"], rule["params"]
    if kind == "health_down":
        value = getattr(obs, p["probe"])
        return (value is not None and value != 200), f"{p['probe']}={value}"
    if kind == "error_rate":
        if obs.requests_total < p["min_requests"]:
            return False, f"requests={obs.requests_total}<{p['min_requests']}"
        rate = obs.status_5xx / obs.requests_total
        return rate > p["threshold"], f"5xx_rate={rate:.3f}"
    if kind == "latency":
        if obs.requests_total < p["min_requests"] or obs.p95_ms is None:
            return False, "insufficient"
        return obs.p95_ms > p["p95_ms"], f"p95_ms={obs.p95_ms}"
    if kind == "count":
        value = getattr(obs, p["field"])
        return value >= p["threshold"], f"{p['field']}={value}"
    if kind == "budget":
        if not obs.ai_budget_month_usd:
            return False, "no budget"
        ratio = obs.ai_cost_month_usd / obs.ai_budget_month_usd
        return ratio >= p["ratio"], f"budget_ratio={ratio:.2f}"
    if kind == "staleness":
        age = obs.backup_age_hours
        return (age is None or age > p["max_age_hours"]), f"backup_age_hours={age}"
    raise ValueError(f"unknown rule kind {kind}")


@dataclass
class AlertState:
    consecutive: int = 0
    firing: bool = False
    fired_at: datetime | None = None
    last_notified: datetime | None = None
    acknowledged: bool = False
    escalated: bool = False


@dataclass
class MockChannel:
    """전송 대신 기록만 한다. 운영 채널·수신자는 승인 전."""

    name: str
    sent: list[dict] = field(default_factory=list)

    def send(self, message: dict) -> None:
        self.sent.append({**message, "channel": self.name})


class AlertEngine:
    def __init__(self, rules: list[dict], primary: MockChannel, secondary: MockChannel,
                 suppress: timedelta = timedelta(minutes=30), escalate_after: timedelta = timedelta(minutes=15)):
        self.rules = rules
        self.primary, self.secondary = primary, secondary
        self.suppress, self.escalate_after = suppress, escalate_after
        self.state: dict[str, AlertState] = {r["id"]: AlertState() for r in rules}
        self.timeline: list[dict] = []

    def _note(self, at: datetime, rule: dict, event: str, detail: str) -> dict:
        entry = {"at": at.isoformat(), "rule": rule["id"], "severity": rule["severity"], "event": event,
                 "detail": detail, "runbook": rule["runbook"]}
        self.timeline.append(entry)
        return entry

    def evaluate(self, obs: Observation) -> None:
        for rule in self.rules:
            st = self.state[rule["id"]]
            hit, detail = condition(rule, obs)
            st.consecutive = st.consecutive + 1 if hit else 0
            needed = rule.get("for_checks", 1)
            inhibitors = [i for i in rule.get("inhibited_by", []) if self.state[i].firing]
            if hit and st.consecutive >= needed and inhibitors:
                # 원인 경보가 이미 울리는 중이면 파생 경보는 알리지 않는다(같은 장애 중복 알림 억제)
                if not st.firing:
                    self._note(obs.at, rule, "INHIBITED", f"{detail}; by {','.join(inhibitors)}")
                continue
            if hit and st.consecutive >= needed:
                if not st.firing:
                    st.firing, st.fired_at, st.acknowledged, st.escalated = True, obs.at, False, False
                    st.last_notified = obs.at
                    self.primary.send(self._note(obs.at, rule, "FIRING", detail))
                elif obs.at - st.last_notified >= self.suppress:
                    st.last_notified = obs.at
                    self.primary.send(self._note(obs.at, rule, "REPEAT", detail))
                else:
                    self._note(obs.at, rule, "SUPPRESSED", detail)
                if (rule["severity"] == "critical" and not st.acknowledged and not st.escalated
                        and obs.at - st.fired_at >= self.escalate_after):
                    st.escalated = True
                    self.secondary.send(self._note(obs.at, rule, "ESCALATED", detail))
            elif not hit and st.firing:
                st.firing = False
                self.primary.send(self._note(obs.at, rule, "RESOLVED", detail))

    def acknowledge(self, rule_id: str, at: datetime, by: str) -> None:
        st = self.state[rule_id]
        if st.firing:
            st.acknowledged = True
            self.timeline.append({"at": at.isoformat(), "rule": rule_id, "event": "ACKNOWLEDGED", "by": by})


def postmortem(timeline: list[dict], rule_id: str) -> dict[str, Any]:
    events = [e for e in timeline if e["rule"] == rule_id]
    fired = next((e for e in events if e["event"] == "FIRING"), None)
    resolved = next((e for e in events if e["event"] == "RESOLVED"), None)
    ack = next((e for e in events if e["event"] == "ACKNOWLEDGED"), None)
    duration = None
    if fired and resolved:
        duration = (datetime.fromisoformat(resolved["at"]) - datetime.fromisoformat(fired["at"])).total_seconds() / 60
    return {"rule": rule_id, "detected_at": fired and fired["at"], "acknowledged_at": ack and ack["at"],
            "resolved_at": resolved and resolved["at"], "duration_minutes": duration,
            "notifications": sum(e["event"] in {"FIRING", "REPEAT", "ESCALATED", "RESOLVED"} for e in events),
            "suppressed": sum(e["event"] == "SUPPRESSED" for e in events),
            "inhibited": sum(e["event"] == "INHIBITED" for e in events),
            "sections": ["영향(사용자·기간)", "탐지 경로", "원인", "완화·복구", "재발 방지", "남은 위험"]}


# ---------------------------------------------------------------- 모의 훈련(합성 시계열, 결정적)
def rehearse(start: datetime) -> dict[str, Any]:
    """장애 4종을 분 단위 합성 관측으로 재생한다. 실제 서비스·채널에 접근하지 않는다."""
    rules = load_rules()
    primary, secondary = MockChannel("mock-primary"), MockChannel("mock-secondary")
    engine = AlertEngine(rules, primary, secondary)
    minute = timedelta(minutes=1)
    t = start
    healthy = dict(requests_total=200, status_5xx=1, p95_ms=250.0, health=200, health_db=200,
                   ai_cost_month_usd=10.0, ai_budget_month_usd=50.0, backup_age_hours=3.0)
    script = []
    script += [dict(healthy)] * 3
    script += [dict(healthy, health_db=503, requests_total=200, status_5xx=150)] * 20    # R1 DB 장애 20분
    script += [dict(healthy)] * 5                                                         # 복구
    script += [dict(healthy, dependency_errors=7)] * 3                                    # R3 AI 공급자 오류
    script += [dict(healthy)] * 2
    script += [dict(healthy, ai_cost_month_usd=41.0)] * 2                                 # R4 예산 82%
    script += [dict(healthy, ai_cost_month_usd=50.5)] * 2                                 # 예산 101%
    script += [dict(healthy, backup_age_hours=30.0)] * 2                                  # R5 백업 지연
    script += [dict(healthy)] * 2
    for i, values in enumerate(script):
        engine.evaluate(Observation(at=t, **values))
        if i == 3 + 17:                                   # DB 장애 17분째 운영자 확인(에스컬레이션 뒤)
            engine.acknowledge("A-DB-DOWN", t, "on-call(mock)")
        t += minute
    reports = {rid: postmortem(engine.timeline, rid) for rid in
               ("A-DB-DOWN", "A-API-5XX", "A-AI-PROVIDER", "A-AI-BUDGET-80", "A-AI-BUDGET-100", "A-BACKUP-STALE")}
    return {"timeline": engine.timeline, "primary_sent": len(primary.sent), "secondary_sent": len(secondary.sent),
            "postmortems": reports}


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="T113 alert rehearsal (mock channels only)")
    parser.add_argument("command", choices=["rehearse"])
    parser.add_argument("--start", default="2026-11-11T01:00:00+00:00")
    parser.add_argument("--out")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = rehearse(datetime.fromisoformat(args.start))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "timeline"}, ensure_ascii=False, indent=2))
