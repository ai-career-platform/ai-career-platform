"""T114 백업·복원 검증 도구 시험.

- 단위(항상 실행): 보존 계획, RPO 신선도 경보, 안전 거부(원격 호스트·승인 없는 DB), manifest 변조 탐지.
- 통합(격리 PostgreSQL): `T114_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/postgres` 가 있고 pg_dump 주 버전이
  서버 이상일 때만. 실제 pg_dump → 복원 → 지문 비교, 손상·잘린 덤프·지문 불일치 FAIL, 읽기 전용 백업 역할.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("t114_backup", ROOT / "database" / "backup" / "t114_backup.py")
bk = importlib.util.module_from_spec(_spec)
sys.modules["t114_backup"] = bk
_spec.loader.exec_module(bk)

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
LOCAL = "postgresql://drill@127.0.0.1:5432/postgres"


def refs(*hours_ago: float) -> list:
    return [bk.BackupRef(f"b{i}.dump", NOW - timedelta(hours=h)) for i, h in enumerate(hours_ago)]


# ------------------------------------------------------------------ 보존 계획(삭제 안 함)
def test_retention_keeps_latest_per_day_week_month_and_expires_the_rest():
    daily = [bk.BackupRef(f"d{d:02d}.dump", NOW - timedelta(days=d)) for d in range(0, 120)]
    plan = bk.retention_plan(daily, NOW)
    kept_days = sorted(int(n[1:3]) for n in plan["keep"])
    assert kept_days[:7] == [0, 1, 2, 3, 4, 5, 6]
    assert len(plan["keep"]) <= 7 + 4 + 3 and len(plan["keep"]) >= 7
    assert set(plan["keep"]) | set(plan["expire"]) == {r.name for r in daily}
    assert not set(plan["keep"]) & set(plan["expire"])
    assert "d119.dump" in plan["expire"]


def test_retention_keeps_multiple_same_day_backups_only_once():
    same_day = [bk.BackupRef(f"s{h}.dump", NOW - timedelta(hours=h)) for h in (0, 1, 2)]
    plan = bk.retention_plan(same_day, NOW)
    assert plan["keep"] == ["s0.dump"] and plan["expire"] == ["s1.dump", "s2.dump"]


def test_retention_never_expires_backups_from_the_future():
    future = [bk.BackupRef("future.dump", NOW + timedelta(days=2)), *refs(0)]
    plan = bk.retention_plan(future, NOW)
    assert "future.dump" in plan["keep"] and plan["clock_skew"] == ["future.dump"]


def test_retention_plan_cli_does_not_delete_files(tmp_path, capsys):
    for i in range(10):
        created = NOW - timedelta(days=i * 3)
        (tmp_path / f"x{i}.dump").write_bytes(b"x")
        (tmp_path / f"x{i}.manifest.json").write_text(json.dumps(
            {"format": bk.MANIFEST_FORMAT, "file": f"x{i}.dump", "created_at": created.isoformat()}), encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    assert bk.main(["retention-plan", "--dir", str(tmp_path), "--now", NOW.isoformat()]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert json.loads(capsys.readouterr().out)["expire"]


# ------------------------------------------------------------------ RPO 신선도 경보
@pytest.mark.parametrize(("ages", "alert", "reason"), [
    ((), True, "no backup"),
    ((1, 30), False, "ok"),
    ((24.5, 48), True, "older than RPO"),
    ((24,), False, "ok"),
])
def test_freshness_alerts_when_newest_backup_is_older_than_rpo(ages, alert, reason):
    result = bk.freshness(refs(*ages), NOW, rpo_hours=24)
    assert (result["alert"], result["reason"]) == (alert, reason)


def test_freshness_cli_exit_code_signals_alert(tmp_path, capsys):
    assert bk.main(["freshness", "--dir", str(tmp_path), "--now", NOW.isoformat()]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "no backup"


# ------------------------------------------------------------------ 안전 거부
@pytest.mark.parametrize("url", ["postgresql://u@192.0.2.10:5432/postgres", "postgresql://u@db:5432/postgres",
                                 "postgresql://u@staging.example.org/postgres"])
def test_remote_hosts_are_refused_before_any_connection(url, tmp_path):
    with pytest.raises(bk.Refused):
        bk.backup(url, "t114_src", tmp_path, "x")
    with pytest.raises(bk.Refused):
        bk.verify(url, tmp_path / "missing.manifest.json")


@pytest.mark.parametrize("approval", [None, "", "   "])
def test_non_drill_database_needs_an_approval_record(approval, tmp_path):
    with pytest.raises(bk.Refused, match="approval"):
        bk.backup(LOCAL, "career", tmp_path, "staging", approval)
    assert list(tmp_path.iterdir()) == []


def test_cli_reports_refusal_with_exit_3(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("T114_ADMIN_URL", "postgresql://u@192.0.2.11/postgres")
    assert bk.main(["backup", "--db", "t114_src", "--out-dir", str(tmp_path)]) == 3
    assert "refused" in capsys.readouterr().out


# ------------------------------------------------------------------ manifest 변조(복원 전 차단)
def _fake(tmp_path, **override):
    dump = tmp_path / "local_t114_src_20261111T030000Z.dump"
    dump.write_bytes(b"PGDMP-synthetic")
    manifest = {"format": bk.MANIFEST_FORMAT, "file": dump.name, "sha256": bk.sha256_file(dump), "toc_entries": 1,
                "created_at": NOW.isoformat(), "fingerprint": {"tables": {}, "objects": {}}, "migrations": []}
    manifest.update(override)
    path = bk.manifest_path(dump)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return dump, path


@pytest.mark.parametrize(("override", "reason"), [
    ({"format": "other/1"}, "unknown manifest format"),
    ({"sha256": "0" * 64}, "sha256 mismatch"),
    ({"file": "missing.dump"}, "dump file missing"),
])
def test_tampered_manifest_fails_before_restore(tmp_path, override, reason):
    _, path = _fake(tmp_path, **override)
    with pytest.raises(bk.VerifyFailed, match=reason):
        bk.verify(LOCAL, path)


def test_modified_dump_bytes_fail_the_checksum(tmp_path):
    dump, path = _fake(tmp_path)
    dump.write_bytes(b"PGDMP-synthetic-modified")
    with pytest.raises(bk.VerifyFailed, match="sha256"):
        bk.verify(LOCAL, path)


# ------------------------------------------------------------------ 격리 PostgreSQL 통합
ADMIN = os.environ.get("T114_ADMIN_URL", "")


def _major(text: str) -> int:
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in text).split()
    return int(digits[0].split(".")[0]) if digits else 0


def _pg_ready() -> str | None:
    if not ADMIN:
        return "T114_ADMIN_URL not set (isolated PostgreSQL only)"
    if shutil.which(bk.tool("pg_dump")) is None and not Path(bk.tool("pg_dump")).exists():
        return "pg_dump not found"
    import psycopg
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        server = conn.execute("SHOW server_version").fetchone()[0]
    client = subprocess.run([bk.tool("pg_dump"), "--version"], capture_output=True, text=True).stdout
    if _major(client) < _major(server):
        return f"pg_dump {client.strip()} older than server {server}"
    return None


pg = pytest.mark.skipif(_pg_ready() is not None if ADMIN else True, reason=_pg_ready() or "isolated PostgreSQL")


@pytest.fixture
def source_db():
    import psycopg
    from psycopg.conninfo import make_conninfo
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute('DROP DATABASE IF EXISTS "t114_src" WITH (FORCE)')
        admin.execute('CREATE DATABASE "t114_src"')
    with psycopg.connect(make_conninfo(ADMIN, dbname="t114_src"), autocommit=True) as conn:
        bk.t90.seed_source(conn)
    yield "t114_src"
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute('DROP DATABASE IF EXISTS "t114_src" WITH (FORCE)')
        leftovers = admin.execute("SELECT datname FROM pg_database WHERE datname LIKE 't114_verify_%'").fetchall()
    assert leftovers == [], "verify databases must always be dropped"


@pg
def test_backup_then_isolated_restore_matches_fingerprint(source_db, tmp_path):
    manifest = bk.backup(ADMIN, source_db, tmp_path, "drill", now=NOW)
    assert manifest["bytes"] > 0 and manifest["toc_entries"] > 100 and manifest["encrypted"] is False
    text = bk.manifest_path(tmp_path / manifest["file"]).read_text(encoding="utf-8")
    assert "@example.invalid" not in text, "manifest holds hashes and counts only, not row data"
    result = bk.verify(ADMIN, bk.manifest_path(tmp_path / manifest["file"]))
    assert result["verdict"] == "PASS" and result["table_mismatches"] == [] and result["objects_equal"]
    assert result["rows"] == sum(v["rows"] for v in manifest["fingerprint"]["tables"].values()) > 1000


@pg
def test_corrupted_dump_fails_restore_and_leaves_no_database(source_db, tmp_path):
    manifest = bk.backup(ADMIN, source_db, tmp_path, "drill", now=NOW)
    dump = tmp_path / manifest["file"]
    data = bytearray(dump.read_bytes())
    data[len(data) // 2: len(data) // 2 + 4096] = b"\x00" * 4096
    dump.write_bytes(bytes(data))
    meta = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    meta["sha256"] = bk.sha256_file(dump)            # 체크섬까지 맞춘 손상 — 복원 단계에서 잡아야 함
    bk.manifest_path(dump).write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(bk.VerifyFailed):
        bk.verify(ADMIN, bk.manifest_path(dump))


@pg
def test_truncated_dump_is_rejected(source_db, tmp_path):
    manifest = bk.backup(ADMIN, source_db, tmp_path, "drill", now=NOW)
    dump = tmp_path / manifest["file"]
    dump.write_bytes(dump.read_bytes()[: manifest["bytes"] // 3])
    meta = json.loads(bk.manifest_path(dump).read_text(encoding="utf-8"))
    meta["sha256"] = bk.sha256_file(dump)
    bk.manifest_path(dump).write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(bk.VerifyFailed):
        bk.verify(ADMIN, bk.manifest_path(dump))


@pg
def test_fingerprint_mismatch_fails(source_db, tmp_path):
    manifest = bk.backup(ADMIN, source_db, tmp_path, "drill", now=NOW)
    path = bk.manifest_path(tmp_path / manifest["file"])
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["fingerprint"]["tables"]["users"]["rows"] += 1
    path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(bk.VerifyFailed, match="differs"):
        bk.verify(ADMIN, path)


@pg
def test_read_only_backup_role_can_dump_but_not_write(source_db, tmp_path):
    import psycopg
    from psycopg.conninfo import make_conninfo
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute("DROP ROLE IF EXISTS t114_backup_ro")
        admin.execute("CREATE ROLE t114_backup_ro LOGIN")
        admin.execute("GRANT pg_read_all_data TO t114_backup_ro")
    try:
        ro_url = make_conninfo(ADMIN, user="t114_backup_ro")
        manifest = bk.backup(ro_url, source_db, tmp_path, "ro", now=NOW)
        assert manifest["bytes"] > 0
        with psycopg.connect(make_conninfo(ro_url, dbname=source_db)) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO career.ai_usage_records (provider_model, feature_code, input_tokens,"
                             " output_tokens) VALUES ('x', 'agent', 1, 1)")
            conn.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("DELETE FROM career.users")
        assert bk.verify(ADMIN, bk.manifest_path(tmp_path / manifest["file"]))["verdict"] == "PASS"
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            admin.execute("DROP ROLE IF EXISTS t114_backup_ro")


@pg
def test_approved_non_drill_backup_records_the_approval(tmp_path):
    import psycopg
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute('DROP DATABASE IF EXISTS "drill_named_db" WITH (FORCE)')
        admin.execute('CREATE DATABASE "drill_named_db"')
    try:
        manifest = bk.backup(ADMIN, "drill_named_db", tmp_path, "approved", approval="PM-T114-synthetic", now=NOW)
        assert manifest["approval"] == "PM-T114-synthetic"
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as admin:
            admin.execute('DROP DATABASE IF EXISTS "drill_named_db" WITH (FORCE)')
