"""T73 unit checks without a database: retention cutoff, execution guards, evidence shape, failure handling.

The guard is exercised with real values (env, URL, identity row); there is no test-only bypass in app code.
"""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from app import behavior_data
from app.behavior_data import (
    MARKER_PREFIX, UnsafePurgeTarget, check_purge_environment, ensure_write_allowed, purge_expired, retention_cutoff,
)

AS_OF = datetime(2026, 11, 10, tzinfo=UTC)
TOKEN = "t73-unit-token-abcdefghij"
SAFE_URL = "postgresql://u@127.0.0.1:55473/t16_profile_test"
SAFE_ENV = {"APP_ENV": "test", "BEHAVIOR_PURGE_DISPOSABLE_DB": "YES", "BEHAVIOR_PURGE_DISPOSABLE_TOKEN": TOKEN}
SAFE_IDENTITY = {"db": "t16_profile_test", "server_addr": "127.0.0.1", "marker": MARKER_PREFIX + TOKEN}


def test_cutoff_never_precedes_collection_time_retention():
    # 수집 시각은 event_at보다 최대 7일 늦다 → event_at 기준 cutoff는 보존 기간 + 7일 전
    assert retention_cutoff(AS_OF, 180) == AS_OF - timedelta(days=187)
    with pytest.raises(ValueError):
        retention_cutoff(AS_OF, 0)
    with pytest.raises(ValueError):
        retention_cutoff(datetime(2026, 11, 10), 180)


# ------------------------------------------------------------------------------- P1-01 pre-connect guard

@pytest.mark.parametrize("env_patch,url,reason", [
    ({"APP_ENV": None}, SAFE_URL, "UNSAFE_APP_ENV"),
    ({"APP_ENV": "staging"}, SAFE_URL, "UNSAFE_APP_ENV"),
    ({"APP_ENV": "production"}, SAFE_URL, "UNSAFE_APP_ENV"),
    ({"APP_ENV": "local-dev"}, SAFE_URL, "UNSAFE_APP_ENV"),                     # 일반 로컬 개발 환경도 차단
    ({"BEHAVIOR_PURGE_DISPOSABLE_DB": None}, SAFE_URL, "UNSAFE_NO_DISPOSABLE_APPROVAL"),
    ({"BEHAVIOR_PURGE_DISPOSABLE_DB": "yes"}, SAFE_URL, "UNSAFE_NO_DISPOSABLE_APPROVAL"),
    ({"BEHAVIOR_PURGE_DISPOSABLE_TOKEN": None}, SAFE_URL, "UNSAFE_NO_DISPOSABLE_TOKEN"),
    ({"BEHAVIOR_PURGE_DISPOSABLE_TOKEN": "short"}, SAFE_URL, "UNSAFE_NO_DISPOSABLE_TOKEN"),
    ({}, "postgresql://u@203.0.113.10/t16_profile_test", "UNSAFE_NON_LOOPBACK"),
    ({}, "postgresql://u@db.example.com/t16_profile_test", "UNSAFE_NON_LOOPBACK"),
    ({}, "postgresql://u@127.0.0.1:6543/ai_career_poc", "UNSAFE_DB_NAME"),      # SSH -L 로 연 공유 DB 모양
    ({}, "postgresql://u@localhost:25432/career_dev", "UNSAFE_DB_NAME"),         # 일반 로컬 개발 DB
    ({}, "postgresql://u@127.0.0.1/t16_staging_test", "UNSAFE_DB_NAME"),
    ({}, "postgresql://u@127.0.0.1/t16_prod_copy_test", "UNSAFE_DB_NAME"),
    ({}, "postgresql://u@127.0.0.1/", "UNSAFE_DB_NAME"),
    ({}, "sqlite:///t16_profile_test", "UNSAFE_UNKNOWN_TARGET"),
    ({}, None, "UNSAFE_UNKNOWN_TARGET"),
])
def test_pre_connect_guard_blocks_everything_but_a_disposable_test_db(env_patch, url, reason):
    env = {**SAFE_ENV, **env_patch}
    env = {k: v for k, v in env.items() if v is not None}
    with pytest.raises(UnsafePurgeTarget) as exc:
        check_purge_environment(url, env)
    assert str(exc.value) == reason
    with pytest.raises(SystemExit):
        ensure_write_allowed(url, env)


def test_pre_connect_guard_allows_verified_disposable_name():
    assert check_purge_environment(SAFE_URL, SAFE_ENV).database == "t16_profile_test"
    ensure_write_allowed(SAFE_URL, SAFE_ENV)


def test_cli_requires_explicit_retention_and_as_of_and_defaults_to_dry_run():
    with pytest.raises(SystemExit):
        behavior_data._parse_args(["purge", "--as-of", AS_OF.isoformat()])
    with pytest.raises(SystemExit):
        behavior_data._parse_args(["purge", "--retention-days", "180"])
    args = behavior_data._parse_args(["purge", "--retention-days", "180", "--as-of", AS_OF.isoformat()])
    assert args.execute is False


@pytest.mark.parametrize("env", [
    {"APP_ENV": "staging", "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/x"},
    {**SAFE_ENV, "DATABASE_URL": "postgresql://u:p@127.0.0.1:6543/ai_career_poc"},   # 터널된 공유 DB 모양
])
def test_cli_execute_with_unsafe_target_stops_before_connecting(monkeypatch, env):
    for key in ("BEHAVIOR_PURGE_DISPOSABLE_DB", "BEHAVIOR_PURGE_DISPOSABLE_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings
    get_settings.cache_clear()
    engine_factory = MagicMock()
    monkeypatch.setattr("app.db.create_db_engine", engine_factory)
    try:
        with pytest.raises(SystemExit):
            behavior_data.main(["purge", "--retention-days", "180", "--as-of", AS_OF.isoformat(), "--execute"])
    finally:
        get_settings.cache_clear()
    engine_factory.assert_not_called()


# ------------------------------------------------------------------------------- P1-02 direct-call guard

def _session(target=3, deleted=3, remaining=0, fail_on=None, url=SAFE_URL, identity=SAFE_IDENTITY):
    session = MagicMock()
    session.get_bind.return_value.url = make_url(url) if url else None
    counts = iter([target, remaining, remaining])

    def execute(stmt, params=None):
        sql = str(stmt)
        if fail_on and fail_on in sql:
            raise ProgrammingError(sql, params, RuntimeError("synthetic"))
        result = MagicMock()
        if "current_database()" in sql:
            result.mappings.return_value.one.return_value = identity
        elif sql.startswith("SELECT count"):
            result.scalar_one.return_value = next(counts)
        else:
            result.rowcount = deleted
        return result

    session.execute.side_effect = execute
    return session


def _executed(session):
    return [str(c.args[0]).split()[0] for c in session.execute.call_args_list]


def test_dry_run_counts_only_and_writes_nothing():
    session = _session(target=4)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, environ={})
    assert (result.dry_run, result.target, result.deleted, result.status) == (True, 4, 0, "PASS")
    assert not {"DELETE", "INSERT"} & set(_executed(session))
    session.commit.assert_not_called()


def test_execute_on_verified_disposable_db_deletes_audits_and_commits_once():
    run_id = uuid4()
    session = _session(target=2, deleted=2)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, run_id=run_id, environ=SAFE_ENV)
    assert (result.target, result.deleted, result.remaining_expired, result.audit_recorded, result.status) == (2, 2, 0, True, "PASS")
    assert _executed(session) == ["SELECT", "SELECT", "DELETE", "INSERT", "SELECT"]   # 식별 → 대상 → 삭제 → 감사 → 잔존
    session.commit.assert_called_once()


@pytest.mark.parametrize("environ,url,identity,reason", [
    ({}, SAFE_URL, SAFE_IDENTITY, "UNSAFE_APP_ENV"),                                  # 직접 호출, 환경 없음
    ({**SAFE_ENV, "APP_ENV": "staging"}, SAFE_URL, SAFE_IDENTITY, "UNSAFE_APP_ENV"),
    (SAFE_ENV, "postgresql://u@127.0.0.1:6543/ai_career_poc", SAFE_IDENTITY, "UNSAFE_DB_NAME"),
    (SAFE_ENV, None, SAFE_IDENTITY, "UNSAFE_UNKNOWN_TARGET"),                           # 검증할 수 없는 Session
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "db": "ai_career_poc"}, "UNSAFE_DB_MISMATCH"),
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "server_addr": "172.18.0.3"}, "UNSAFE_SERVER_ADDR"),   # 터널 너머 컨테이너
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "server_addr": "10.2.0.4"}, "UNSAFE_SERVER_ADDR"),
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "server_addr": None}, "UNSAFE_SERVER_ADDR"),
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "marker": None}, "UNSAFE_NO_DISPOSABLE_MARKER"),       # 원격 localhost 터널
    (SAFE_ENV, SAFE_URL, {**SAFE_IDENTITY, "marker": MARKER_PREFIX + "other-token-klmnopqrst"}, "UNSAFE_NO_DISPOSABLE_MARKER"),
])
def test_direct_call_with_unverified_target_never_counts_or_deletes(environ, url, identity, reason):
    session = _session(target=2, deleted=2, url=url, identity=identity)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, environ=environ)
    assert (result.status, result.reason_code, result.deleted, result.target, result.audit_recorded) == ("FAIL", reason, 0, 0, False)
    assert not {"DELETE", "INSERT"} & set(_executed(session)) and "SELECT count" not in " ".join(
        str(c.args[0]) for c in session.execute.call_args_list)
    session.commit.assert_not_called()
    session.rollback.assert_called()


def test_direct_call_uses_process_environment_by_default(monkeypatch):
    for key in ("APP_ENV", "BEHAVIOR_PURGE_DISPOSABLE_DB", "BEHAVIOR_PURGE_DISPOSABLE_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    session = _session()
    assert purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False).reason_code == "UNSAFE_APP_ENV"
    assert "DELETE" not in _executed(session)


def test_identity_query_error_fails_closed():
    session = _session(fail_on="current_database()")
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, environ=SAFE_ENV)
    assert (result.status, result.reason_code) == ("FAIL", "UNSAFE_IDENTITY_CHECK_ProgrammingError")
    assert "DELETE" not in _executed(session)


# ------------------------------------------------------------------------------- rollback and evidence

@pytest.mark.parametrize("fail_on,reason", [
    ("INSERT INTO career.audit_events", "PURGE_FAILED_ProgrammingError"),
    ("DELETE FROM career.behavior_events", "PURGE_FAILED_ProgrammingError"),
])
def test_audit_or_delete_failure_rolls_back_and_is_not_success(fail_on, reason):
    session = _session(target=2, deleted=2, remaining=2, fail_on=fail_on)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, environ=SAFE_ENV)
    assert (result.status, result.reason_code, result.deleted, result.audit_recorded) == ("FAIL", reason, 0, False)
    session.commit.assert_not_called()
    session.rollback.assert_called()


def test_rows_left_after_delete_fail_closed():
    session = _session(target=2, deleted=1, remaining=1)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, environ=SAFE_ENV)
    assert (result.status, result.reason_code, result.deleted) == ("FAIL", "REMAINING_AFTER_DELETE", 0)
    session.commit.assert_not_called()


def test_evidence_has_required_fields_and_no_personal_data_or_token():
    result = purge_expired(_session(target=1), as_of=AS_OF, retention_days=180, dry_run=False, environ=SAFE_ENV)
    evidence = json.loads(result.to_json())
    for key in ("run_id", "operation", "dry_run", "as_of", "cutoff", "target", "deleted",
                "remaining_expired", "status", "reason_code", "audit_recorded"):
        assert key in evidence
    assert not {"user_id", "metadata", "email", "token"} & set(evidence)
    assert TOKEN not in result.to_json()
