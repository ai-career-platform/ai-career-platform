"""T73 unit checks without a database: retention cutoff, execution guards, evidence shape, failure handling."""
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import ProgrammingError

from app import behavior_data
from app.behavior_data import ensure_write_allowed, purge_expired, retention_cutoff

AS_OF = datetime(2026, 11, 10, tzinfo=UTC)


def test_cutoff_never_precedes_collection_time_retention():
    # 수집 시각은 event_at보다 최대 7일 늦다 → event_at 기준 cutoff는 보존 기간 + 7일 전
    assert retention_cutoff(AS_OF, 180) == AS_OF - timedelta(days=187)
    with pytest.raises(ValueError):
        retention_cutoff(AS_OF, 0)
    with pytest.raises(ValueError):
        retention_cutoff(datetime(2026, 11, 10), 180)


@pytest.mark.parametrize("app_env,url", [
    (None, "postgresql://u@127.0.0.1/db"),
    ("staging", "postgresql://u@127.0.0.1/db"),
    ("production", "postgresql://u@localhost/db"),
    ("test", "postgresql://u@203.0.113.10/ai_career_poc"),
    ("local-dev", "postgresql://u@db.example.com/db"),
    ("test", "sqlite:///tmp.db"),
])
def test_execute_is_blocked_outside_isolated_loopback_db(app_env, url):
    with pytest.raises(SystemExit):
        ensure_write_allowed(url, app_env)


@pytest.mark.parametrize("app_env,url", [("test", "postgresql://u@127.0.0.1:5432/t"), ("local-dev", "postgresql://u@localhost/t")])
def test_execute_is_allowed_only_for_local_envs(app_env, url):
    ensure_write_allowed(url, app_env)


def test_cli_requires_explicit_retention_and_as_of_and_defaults_to_dry_run():
    with pytest.raises(SystemExit):
        behavior_data._parse_args(["purge", "--as-of", AS_OF.isoformat()])
    with pytest.raises(SystemExit):
        behavior_data._parse_args(["purge", "--retention-days", "180"])
    args = behavior_data._parse_args(["purge", "--retention-days", "180", "--as-of", AS_OF.isoformat()])
    assert args.execute is False


def test_cli_execute_with_shared_env_stops_before_connecting(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:5432/x")
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


def _session(target=3, deleted=3, remaining=0, fail_on=None):
    session = MagicMock()
    counts = iter([target, remaining, remaining])

    def execute(stmt, params=None):
        sql = str(stmt)
        if fail_on and fail_on in sql:
            raise ProgrammingError(sql, params, RuntimeError("synthetic"))
        result = MagicMock()
        if sql.startswith("SELECT count"):
            result.scalar_one.return_value = next(counts)
        else:
            result.rowcount = deleted
        return result

    session.execute.side_effect = execute
    return session


def test_dry_run_counts_only_and_writes_nothing():
    session = _session(target=4)
    result = purge_expired(session, as_of=AS_OF, retention_days=180)
    assert (result.dry_run, result.target, result.deleted, result.status) == (True, 4, 0, "PASS")
    assert not any("DELETE" in str(c.args[0]) or "INSERT" in str(c.args[0]) for c in session.execute.call_args_list)
    session.commit.assert_not_called()


def test_execute_deletes_audits_and_commits_once():
    run_id = uuid4()
    session = _session(target=2, deleted=2)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False, run_id=run_id)
    assert (result.target, result.deleted, result.remaining_expired, result.audit_recorded, result.status) == (2, 2, 0, True, "PASS")
    statements = [str(c.args[0]).split()[0] for c in session.execute.call_args_list]
    assert statements == ["SELECT", "DELETE", "INSERT", "SELECT"]
    session.commit.assert_called_once()


@pytest.mark.parametrize("fail_on,reason", [
    ("INSERT INTO career.audit_events", "PURGE_FAILED_ProgrammingError"),
    ("DELETE FROM career.behavior_events", "PURGE_FAILED_ProgrammingError"),
])
def test_audit_or_delete_failure_rolls_back_and_is_not_success(fail_on, reason):
    session = _session(target=2, deleted=2, remaining=2, fail_on=fail_on)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False)
    assert (result.status, result.reason_code, result.deleted, result.audit_recorded) == ("FAIL", reason, 0, False)
    session.commit.assert_not_called()
    session.rollback.assert_called()


def test_rows_left_after_delete_fail_closed():
    session = _session(target=2, deleted=1, remaining=1)
    result = purge_expired(session, as_of=AS_OF, retention_days=180, dry_run=False)
    assert (result.status, result.reason_code, result.deleted) == ("FAIL", "REMAINING_AFTER_DELETE", 0)
    session.commit.assert_not_called()


def test_evidence_has_required_fields_and_no_personal_data():
    result = purge_expired(_session(target=1), as_of=AS_OF, retention_days=180)
    evidence = json.loads(result.to_json())
    for key in ("run_id", "operation", "dry_run", "as_of", "cutoff", "target", "deleted",
                "remaining_expired", "status", "reason_code", "audit_recorded"):
        assert key in evidence
    assert not {"user_id", "metadata", "email", "token"} & set(evidence)
