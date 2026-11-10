"""T73 행동 데이터 품질 검사와 보존 기간 만료 삭제 — 한 번 실행하고 끝나는 배치 (스케줄 연결은 별도 승인).

    python -m app.behavior_data quality [--as-of 2026-11-10T00:00:00+00:00]
    python -m app.behavior_data purge --retention-days 180 --as-of 2026-11-10T00:00:00+00:00          # dry-run
    APP_ENV=test BEHAVIOR_PURGE_DISPOSABLE_DB=YES BEHAVIOR_PURGE_DISPOSABLE_TOKEN=<token> \
      python -m app.behavior_data purge --retention-days 180 --as-of ... --execute    # 일회용 DB만 (DB 주석 표식 필요)

계약: docs/data/BEHAVIOR_EVENT_CONTRACT.md (T71, DRAFT·미승인), T72 수집 경로(app/services/behavior_events.py).

- 품질 검사는 **읽기 전용**이다. 유형별 건수만 돌려주고 user_id·metadata 원본은 내보내지 않는다.
  허용 목록·값 규칙은 T72 DTO(app/schemas/behavior_events.py)를 그대로 쓴다.
- 7일 수집 창은 수집 시점 규칙이라 과거에 정상 저장된 행에 적용하지 않는다. 미래 시각만 검사한다.
- 동의는 "이벤트 시각 기준 유효 동의"(수집 당시)와 "현재 철회됐는데 남은 행"(삭제 상태)을 따로 센다.
- 보존 기간은 T71 가안(180일)이며 **운영값이 아니다**. 기본값을 두지 않고 호출자가 명시해야 한다.
- 0001 `behavior_events`에는 `retain_until`·저장 시각이 없어 `event_at`만 쓸 수 있다. T72는 수집 시각보다
  최대 7일 이른 `event_at`을 받으므로, 계약(수집 시각 + 보존 기간)보다 먼저 지우지 않도록
  `event_at < as_of - retention_days - 7일`인 행만 대상으로 삼는다(최대 7일 늦게 지워질 수 있음).
- 실제 삭제는 **일회용 테스트 DB에서만** 된다. 기본은 dry-run. 연결 전·후 증거를 모두 요구한다(§ 안전장치).
  CLI와 `purge_expired(dry_run=False)` 직접 호출에 같은 규칙을 적용하고, 하나라도 어긋나면 DELETE 없이 FAIL.
- 삭제와 감사 기록(`career.audit_events`, action_code `system.behavior.purge`)은 한 트랜잭션이다.
  감사 기록이 실패하면 삭제도 롤백되고 FAIL로 보고한다(감사 없는 삭제를 성공으로 보고하지 않음).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.schemas.behavior_events import (
    ALLOWED_KEYS, ID_OR_CODE, MAX_METADATA_BYTES, MAX_METADATA_KEYS, TRACKING_EVENTS, TRACKING_POLICY,
)

LOOPBACK = ("localhost", "127.0.0.1", "::1")
# ---- 삭제 안전장치 (일회용 테스트 DB 식별 증거; T16 격리 DB 규칙과 같은 방식)
PURGE_APP_ENV = "test"                                  # local-dev(일반 로컬 DB)도 허용하지 않는다
DISPOSABLE_FLAG = "BEHAVIOR_PURGE_DISPOSABLE_DB"        # 명시적 승인: 값이 정확히 "YES"
DISPOSABLE_TOKEN = "BEHAVIOR_PURGE_DISPOSABLE_TOKEN"    # 실행마다 정하는 토큰. DB 주석 표식과 같아야 함
MARKER_PREFIX = "ai-career-disposable-test:"            # COMMENT ON DATABASE <db> IS '<prefix><token>'
DISPOSABLE_DB_NAME = re.compile(r"^t[0-9]{2,3}_[a-z0-9_]*test$")   # 예: t16_profile_test
FORBIDDEN_DB_NAME = re.compile(r"staging|stage|prod|live|poc|shared|main")
TOKEN_FORMAT = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
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


class UnsafePurgeTarget(Exception):
    """삭제 대상이 일회용 테스트 DB라는 증거가 부족함. args[0]은 사유 코드."""


def check_purge_environment(database_url: object, environ: Mapping[str, str]) -> URL:
    """연결 전 검사. 환경·승인 플래그·토큰 형식·loopback·DB 이름을 교차 확인한다 (fail closed).

    localhost/loopback만으로는 안전하다고 보지 않는다: SSH 포트포워딩(-L)한 공유 DB도 localhost로 보인다.
    그래서 DB 이름 규칙과 연결 후 검사(verify_connected_target)를 함께 요구한다.
    """
    if environ.get("APP_ENV") != PURGE_APP_ENV:
        raise UnsafePurgeTarget("UNSAFE_APP_ENV")
    if environ.get(DISPOSABLE_FLAG) != "YES":
        raise UnsafePurgeTarget("UNSAFE_NO_DISPOSABLE_APPROVAL")
    if not TOKEN_FORMAT.fullmatch(environ.get(DISPOSABLE_TOKEN, "")):
        raise UnsafePurgeTarget("UNSAFE_NO_DISPOSABLE_TOKEN")
    try:
        url = database_url if isinstance(database_url, URL) else make_url(str(database_url))
    except Exception:  # noqa: BLE001 - 식별할 수 없는 대상
        raise UnsafePurgeTarget("UNSAFE_UNKNOWN_TARGET") from None
    if not isinstance(database_url, (str, URL)) or url.get_backend_name() != "postgresql":
        raise UnsafePurgeTarget("UNSAFE_UNKNOWN_TARGET")
    if url.host not in LOOPBACK:
        raise UnsafePurgeTarget("UNSAFE_NON_LOOPBACK")
    name = url.database or ""
    if not DISPOSABLE_DB_NAME.fullmatch(name) or FORBIDDEN_DB_NAME.search(name):
        raise UnsafePurgeTarget("UNSAFE_DB_NAME")
    return url


_IDENTITY = text("""
SELECT current_database() AS db, host(inet_server_addr()) AS server_addr,
       shobj_description(d.oid, 'pg_database') AS marker
FROM pg_database d WHERE d.datname = current_database()
""")


def verify_connected_target(session: Session, environ: Mapping[str, str]) -> None:
    """연결 후 검사. 이 Session의 실제 연결이 일회용 테스트 DB인지 확인한다 (DELETE 전에 호출).

    - 연결된 DB 이름 = 설정 DB 이름 (다른 DB로 접속됐으면 거부)
    - 서버가 본 자기 주소가 loopback (SSH 터널·프록시로 원격 서버에 붙으면 서버 쪽 주소가 원격 IP)
    - DB 주석 표식 = MARKER_PREFIX + 토큰 (공유 DB에는 이 표식이 없다; 원격 서버의 localhost로 터널링해도 차단)
    """
    bind = session.get_bind()
    url = check_purge_environment(getattr(bind, "url", None), environ)
    row = session.execute(_IDENTITY).mappings().one()
    if row["db"] != url.database:
        raise UnsafePurgeTarget("UNSAFE_DB_MISMATCH")
    try:
        loopback = row["server_addr"] is not None and ipaddress.ip_address(row["server_addr"]).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise UnsafePurgeTarget("UNSAFE_SERVER_ADDR")
    if row["marker"] != MARKER_PREFIX + environ[DISPOSABLE_TOKEN]:
        raise UnsafePurgeTarget("UNSAFE_NO_DISPOSABLE_MARKER")


def purge_expired(session: Session, *, as_of: datetime, retention_days: int, dry_run: bool = True,
                  run_id: uuid.UUID | None = None, environ: Mapping[str, str] | None = None) -> PurgeResult:
    """보존 기간이 지난 행동 이벤트를 찾고(dry-run) 지운다.

    dry_run=False면 호출 경로(CLI·직접 호출)와 상관없이 이 함수 안에서 이 Session의 연결을 검증한다.
    검증에 실패하면 COUNT·DELETE 없이 FAIL(UNSAFE_*)을 돌려준다.
    한 트랜잭션: 대상 계산 → 삭제 → 감사 기록 → 잔존 확인 → 커밋. 어느 단계든 실패하면 전부 롤백한다.
    """
    run_id = run_id or uuid.uuid4()
    cutoff = retention_cutoff(as_of, retention_days)
    result = PurgeResult(run_id=str(run_id), operation="behavior_retention_purge", dry_run=dry_run,
                         as_of=as_of.isoformat(), retention_days=retention_days, cutoff=cutoff.isoformat())
    params = {"cutoff": cutoff}
    if not dry_run:
        try:
            verify_connected_target(session, os.environ if environ is None else environ)
        except UnsafePurgeTarget as exc:
            session.rollback()
            result.reason_code, result.remaining_expired = str(exc), -1
            result.notes.append("blocked before COUNT/DELETE: target is not a verified disposable test DB")
            return result
        except Exception as exc:  # noqa: BLE001 - 식별 실패도 차단
            session.rollback()
            result.reason_code, result.remaining_expired = f"UNSAFE_IDENTITY_CHECK_{type(exc).__name__}", -1
            return result
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

def ensure_write_allowed(database_url: str, environ: Mapping[str, str]) -> None:
    """CLI 연결 전 검사. 실패하면 DB에 연결하지 않고 종료한다 (연결 후 검사는 purge_expired 안에서)."""
    try:
        check_purge_environment(database_url, environ)
    except UnsafePurgeTarget as exc:
        raise SystemExit(f"behavior purge --execute refused ({exc}): only a verified disposable test DB "
                         f"(APP_ENV=test, {DISPOSABLE_FLAG}=YES, {DISPOSABLE_TOKEN}, loopback, tNN_*_test, "
                         f"database marker) is allowed") from None


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
        ensure_write_allowed(settings.database.url, os.environ)
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
