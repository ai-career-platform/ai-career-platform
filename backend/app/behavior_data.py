"""T73 행동 데이터 품질 검사와 보존 기간 만료 삭제 — 한 번 실행하고 끝나는 배치 (스케줄 연결은 별도 승인).

    python -m app.behavior_data quality [--as-of 2026-11-10T00:00:00+00:00]
    python -m app.behavior_data purge --retention-days 180 --as-of 2026-11-10T00:00:00+00:00          # dry-run
    APP_ENV=test python -m app.behavior_data purge --retention-days 180 --as-of ... --execute          # 격리 DB만

계약: docs/data/BEHAVIOR_EVENT_CONTRACT.md (T71, DRAFT·미승인), T72 수집 경로(app/services/behavior_events.py).

- 품질 검사는 **읽기 전용**이다. 유형별 건수만 돌려주고 user_id·metadata 원본은 내보내지 않는다.
  허용 목록·값 규칙은 T72 DTO(app/schemas/behavior_events.py)를 그대로 쓴다.
- 7일 수집 창은 수집 시점 규칙이라 과거에 정상 저장된 행에 적용하지 않는다. 미래 시각만 검사한다.
- 동의는 "이벤트 시각 기준 유효 동의"(수집 당시)와 "현재 철회됐는데 남은 행"(삭제 상태)을 따로 센다.
- 보존 기간은 T71 가안(180일)이며 **운영값이 아니다**. 기본값을 두지 않고 호출자가 명시해야 한다.
- 0001 `behavior_events`에는 `retain_until`·저장 시각이 없어 `event_at`만 쓸 수 있다. T72는 수집 시각보다
  최대 7일 이른 `event_at`을 받으므로, 계약(수집 시각 + 보존 기간)보다 먼저 지우지 않도록
  `event_at < as_of - retention_days - 7일`인 행만 대상으로 삼는다(최대 7일 늦게 지워질 수 있음).
- 실제 삭제는 `--execute` + APP_ENV=local-dev/test + loopback PostgreSQL에서만. 기본은 dry-run.
- 삭제와 감사 기록(`career.audit_events`, action_code `system.behavior.purge`)은 한 트랜잭션이다.
  감사 기록이 실패하면 삭제도 롤백되고 FAIL로 보고한다(감사 없는 삭제를 성공으로 보고하지 않음).
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.schemas.behavior_events import (
    ALLOWED_KEYS, ID_OR_CODE, MAX_METADATA_BYTES, MAX_METADATA_KEYS, TRACKING_EVENTS, TRACKING_POLICY,
)

SAFE_ENVS = ("local-dev", "test")
LOOPBACK = ("localhost", "127.0.0.1", "::1")
COLLECTION_LAG = timedelta(days=7)   # T72: event_at은 수집 시각보다 최대 7일 이를 수 있다
FUTURE_SKEW = timedelta(minutes=5)   # T72: event_at은 수집 시각보다 최대 5분 늦을 수 있다
AUDIT_ACTION = "system.behavior.purge"
AUDIT_RESOURCE = "behavior_event"


def _jsonb_allowlist() -> str:
    return json.dumps({code: sorted(keys) for code, keys in ALLOWED_KEYS.items()})


# ------------------------------------------------------------------------------------------- quality

# DB가 막는 항목(기본키·NOT NULL·FK·jsonb 형식)과 애플리케이션 계약 위반을 구분해 센다.
_QUALITY_SQL = text("""
WITH allow AS (SELECT CAST(:allow AS jsonb) AS doc),
ev AS (
    SELECT e.event_id, e.user_id, e.event_code, e.event_at, e.metadata,
           (SELECT c.granted FROM career.user_consents c
             WHERE c.user_id = e.user_id AND c.policy_code = :policy AND c.recorded_at <= e.event_at
             ORDER BY c.recorded_at DESC, c.consent_id DESC LIMIT 1) AS granted_at_event,
           (SELECT c.granted FROM career.user_consents c
             WHERE c.user_id = e.user_id AND c.policy_code = :policy
             ORDER BY c.recorded_at DESC, c.consent_id DESC LIMIT 1) AS granted_now
    FROM career.behavior_events e
),
meta AS (
    SELECT ev.event_id,
           bool_or(NOT ((SELECT doc FROM allow) -> ev.event_code ? kv.key)) AS bad_key,
           bool_or(NOT (jsonb_typeof(kv.value) IN ('number', 'boolean')
                        OR (jsonb_typeof(kv.value) = 'string' AND (kv.value #>> '{}') ~ :id_or_code))) AS bad_value,
           count(*) AS key_count
    FROM ev CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(ev.metadata) = 'object'
                                               THEN ev.metadata ELSE '{}'::jsonb END) kv
    GROUP BY ev.event_id
)
SELECT
    (SELECT count(*) FROM ev) AS total_events,
    (SELECT count(*) - count(DISTINCT event_id) FROM ev) AS duplicate_storage_key,
    (SELECT count(*) FROM ev WHERE event_id IS NULL OR user_id IS NULL OR event_code IS NULL OR event_at IS NULL)
        AS missing_required,
    (SELECT count(*) FROM ev LEFT JOIN career.users u ON u.user_id = ev.user_id WHERE u.user_id IS NULL)
        AS orphan_user,
    (SELECT count(*) FROM ev WHERE NOT ((SELECT doc FROM allow) ? ev.event_code)) AS unknown_event_code,
    (SELECT count(*) FROM ev WHERE (SELECT doc FROM allow) ? ev.event_code
                              AND NOT (ev.event_code = ANY(CAST(:tracking AS text[])))) AS unapproved_event_code,
    (SELECT count(*) FROM ev WHERE ev.metadata IS NOT NULL AND jsonb_typeof(ev.metadata) <> 'object')
        AS metadata_not_object,
    (SELECT count(*) FROM meta WHERE bad_key) AS metadata_key_not_allowed,
    (SELECT count(*) FROM meta WHERE bad_value) AS metadata_value_invalid,
    (SELECT count(*) FROM meta WHERE key_count > :max_keys) AS metadata_too_many_keys,
    (SELECT count(*) FROM ev WHERE octet_length(ev.metadata::text) > :max_bytes) AS metadata_too_large,
    (SELECT count(*) FROM ev WHERE ev.metadata = '{}'::jsonb) AS metadata_empty_object,
    (SELECT count(*) FROM ev WHERE ev.event_at > CAST(:as_of AS timestamptz) + CAST(:skew AS interval))
        AS event_at_future,
    (SELECT count(*) FROM ev WHERE ev.event_code = ANY(CAST(:tracking AS text[]))
                              AND ev.granted_at_event IS NOT TRUE) AS no_consent_at_event_time,
    (SELECT count(*) FROM ev WHERE ev.event_code = ANY(CAST(:tracking AS text[]))
                              AND ev.granted_now IS NOT TRUE) AS retained_without_current_consent,
    (SELECT count(*) FROM (SELECT 1 FROM ev GROUP BY user_id, event_code, event_at, metadata
                           HAVING count(*) > 1) d) AS same_payload_groups
""")

# 오류로 세는 항목. same_payload_groups는 같은 화면을 같은 시각에 두 번 본 정상 사례일 수 있어 경고만.
QUALITY_ERRORS = (
    "duplicate_storage_key", "missing_required", "orphan_user", "unknown_event_code", "unapproved_event_code",
    "metadata_not_object", "metadata_key_not_allowed", "metadata_value_invalid", "metadata_too_many_keys",
    "metadata_too_large", "metadata_empty_object", "event_at_future", "no_consent_at_event_time",
    "retained_without_current_consent",
)
DB_ENFORCED = ("duplicate_storage_key", "missing_required", "orphan_user")  # PK·NOT NULL·FK로 0이어야 정상
QUALITY_WARNINGS = ("same_payload_groups",)


@dataclass(frozen=True)
class QualityReport:
    as_of: str
    counts: dict[str, int]
    errors: int
    status: str
    db_enforced: tuple[str, ...] = DB_ENFORCED
    warnings: tuple[str, ...] = QUALITY_WARNINGS

    def to_json(self) -> str:
        return json.dumps({"task": "T73", "check": "behavior_quality", **asdict(self)}, ensure_ascii=False)


def run_quality_check(session: Session, *, as_of: datetime) -> QualityReport:
    """읽기 전용. 트랜잭션을 READ ONLY로 열고 끝나면 롤백한다."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    session.execute(text("SET TRANSACTION READ ONLY"))
    try:
        row = session.execute(_QUALITY_SQL, {
            "allow": _jsonb_allowlist(), "policy": TRACKING_POLICY, "id_or_code": ID_OR_CODE.pattern,
            "tracking": sorted(TRACKING_EVENTS), "max_keys": MAX_METADATA_KEYS, "max_bytes": MAX_METADATA_BYTES,
            "as_of": as_of, "skew": f"{int(FUTURE_SKEW.total_seconds())} seconds",
        }).mappings().one()
    finally:
        session.rollback()
    counts = {k: int(v) for k, v in row.items()}
    errors = sum(counts[k] for k in QUALITY_ERRORS)
    return QualityReport(as_of=as_of.isoformat(), counts=counts, errors=errors, status="PASS" if errors == 0 else "FAIL")


# ------------------------------------------------------------------------------------------- retention

@dataclass
class PurgeResult:
    run_id: str
    operation: str
    dry_run: bool
    as_of: str
    retention_days: int
    cutoff: str
    target: int = 0
    deleted: int = 0
    remaining_expired: int = 0
    audit_recorded: bool = False
    status: str = "FAIL"
    reason_code: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({"task": "T73", **asdict(self)}, ensure_ascii=False)


def retention_cutoff(as_of: datetime, retention_days: int) -> datetime:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    return as_of - timedelta(days=retention_days) - COLLECTION_LAG


_COUNT_EXPIRED = text("SELECT count(*) FROM career.behavior_events WHERE event_at < :cutoff")
_DELETE_EXPIRED = text("DELETE FROM career.behavior_events WHERE event_at < :cutoff")
_AUDIT = text("""
INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, request_id)
VALUES (NULL, :action, :resource, :run_id, :request_id)
""")


def purge_expired(session: Session, *, as_of: datetime, retention_days: int, dry_run: bool = True,
                  run_id: uuid.UUID | None = None) -> PurgeResult:
    """보존 기간이 지난 행동 이벤트를 찾고(dry-run) 지운다. 호출자가 실행 환경을 검증해야 한다(main 참고).

    한 트랜잭션: 대상 계산 → 삭제 → 감사 기록 → 잔존 확인 → 커밋. 어느 단계든 실패하면 전부 롤백한다.
    """
    run_id = run_id or uuid.uuid4()
    cutoff = retention_cutoff(as_of, retention_days)
    result = PurgeResult(run_id=str(run_id), operation="behavior_retention_purge", dry_run=dry_run,
                         as_of=as_of.isoformat(), retention_days=retention_days, cutoff=cutoff.isoformat())
    params = {"cutoff": cutoff}
    try:
        result.target = int(session.execute(_COUNT_EXPIRED, params).scalar_one())
        if dry_run:
            session.rollback()
            result.remaining_expired = result.target
            result.status = "PASS"
            result.notes.append("dry-run: nothing deleted, no audit row written")
            return result
        deleted = session.execute(_DELETE_EXPIRED, params).rowcount
        session.execute(_AUDIT, {"action": AUDIT_ACTION, "resource": AUDIT_RESOURCE, "run_id": run_id,
                                 "request_id": f"t73-purge:{run_id}"})
        remaining = int(session.execute(_COUNT_EXPIRED, params).scalar_one())
        if remaining:
            raise RuntimeError("REMAINING_AFTER_DELETE")
        session.commit()
        result.deleted, result.remaining_expired, result.audit_recorded = int(deleted), 0, True
        result.status = "PASS"
    except Exception as exc:  # 원인 코드만 남긴다 (SQL·값은 남기지 않음)
        session.rollback()
        result.deleted, result.audit_recorded = 0, False
        result.reason_code = str(exc) if str(exc) == "REMAINING_AFTER_DELETE" else f"PURGE_FAILED_{type(exc).__name__}"
        try:
            result.remaining_expired = int(session.execute(_COUNT_EXPIRED, params).scalar_one())
            session.rollback()
        except Exception:  # noqa: BLE001 - 상태를 다시 읽지 못하면 -1로 표시
            result.remaining_expired = -1
        result.status = "FAIL"
    return result


# ------------------------------------------------------------------------------------------- CLI

def ensure_write_allowed(database_url: str, app_env: str | None) -> None:
    """실제 삭제는 명시적인 로컬 개발/테스트 환경 + loopback PostgreSQL에서만 (fail closed)."""
    if app_env not in SAFE_ENVS:
        raise SystemExit("Shared or unset APP_ENV: behavior purge --execute is allowed only in local-dev/test")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or url.host not in LOOPBACK:
        raise SystemExit("behavior purge --execute requires a loopback PostgreSQL target")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.behavior_data", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    quality = sub.add_parser("quality", help="읽기 전용 품질 검사 (유형별 건수)")
    quality.add_argument("--as-of", type=datetime.fromisoformat, default=None, help="기준 시각 (시간대 필수)")
    purge = sub.add_parser("purge", help="보존 기간 만료 삭제 (기본 dry-run)")
    purge.add_argument("--retention-days", type=int, required=True, help="승인된 보존 일수 (기본값 없음)")
    purge.add_argument("--as-of", type=datetime.fromisoformat, required=True, help="기준 시각 (시간대 필수)")
    purge.add_argument("--execute", action="store_true", help="실제 삭제 (격리 DB 전용)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from app.core.config import get_settings
    from app.db import create_db_engine, create_session_factory

    args = _parse_args(argv)
    settings = get_settings()
    if settings.database is None:
        raise SystemExit("DATABASE_URL is required")
    if args.command == "purge" and args.execute:
        ensure_write_allowed(settings.database.url, os.environ.get("APP_ENV"))
    engine = create_db_engine(settings.database)
    try:
        with create_session_factory(engine)() as session:
            if args.command == "quality":
                report = run_quality_check(session, as_of=args.as_of or datetime.now(timezone.utc))
                print(report.to_json())
                return 0 if report.status == "PASS" else 1
            result = purge_expired(session, as_of=args.as_of, retention_days=args.retention_days,
                                   dry_run=not args.execute)
            print(result.to_json())
            return 0 if result.status == "PASS" else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
