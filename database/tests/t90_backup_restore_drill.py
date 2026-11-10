"""T90 PostgreSQL 백업·복원 훈련 — **로컬 일회용 클러스터 전용**.

    T90_DRILL_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/postgres PG_BIN=<pg_dump·pg_restore 경로> \
      python database/tests/t90_backup_restore_drill.py --out result.json

- 접속 대상이 loopback 이 아니거나, 만들 DB 이름이 `t90_` 로 시작하지 않으면 거부합니다. Staging·운영 DB·볼륨 접근 없음.
- 원본 DB(t90_source): Migration 0001~0003 + Seed + 합성 개인 데이터 → `pg_dump -Fc` → 새 DB(t90_restore)에 `pg_restore`.
- 검증: 표마다 행 수와 내용 md5, 제약·인덱스·함수·트리거 수, 시퀀스 없음 확인, 복원본에 앱을 붙여 `/health/db`·공개 조회 200.
- 끝나면 두 DB 를 지웁니다(덤프 파일은 --keep-dump 일 때만 남김). 덤프에는 합성 데이터만 들어 있습니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE, RESTORE = "t90_source", "t90_restore"


def guard(url: str) -> dict:
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(url)
    if options.get("host") not in {"127.0.0.1", "localhost"}:
        raise SystemExit("refused: loopback disposable cluster only")
    for name in (SOURCE, RESTORE):
        if not name.startswith("t90_"):
            raise SystemExit("refused: drill databases must start with t90_")
    return options


def fingerprint(conn) -> dict:
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='career' ORDER BY tablename").fetchall()]
    rows = {}
    for table in tables:
        count, digest = conn.execute(
            f'SELECT count(*), md5(coalesce(string_agg(t::text, \',\' ORDER BY t::text), \'\')) FROM career."{table}" t').fetchone()
        rows[table] = {"rows": count, "md5": digest}
    objects = {
        "constraints": conn.execute("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
                                    "WHERE n.nspname='career'").fetchone()[0],
        "indexes": conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='career'").fetchone()[0],
        "functions": conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                  "WHERE n.nspname='career'").fetchone()[0],
        "triggers": conn.execute("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n "
                                 "ON n.oid=c.relnamespace WHERE n.nspname='career' AND NOT t.tgisinternal").fetchone()[0],
        "foreign_keys": conn.execute("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
                                     "WHERE n.nspname='career' AND c.contype='f'").fetchone()[0],
    }
    return {"tables": rows, "objects": objects}


def seed_source(conn) -> None:
    conn.execute("CREATE SCHEMA career")
    for path in sorted((ROOT / "database/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
    conn.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
    # 합성 개인 데이터(사용자·동의·경험·감사·사용량) — 복원 후 내용 일치 확인용
    conn.execute("""INSERT INTO career.users (email, email_canonical, display_name)
                    SELECT 't90-' || g || '@example.invalid', 't90-' || g || '@example.invalid', '합성 ' || g
                    FROM generate_series(1, 200) g""")
    conn.execute("""INSERT INTO career.user_experiences (user_id, organization, title)
                    SELECT user_id, '합성 기관', '직무' FROM career.users WHERE email LIKE 't90-%'""")
    conn.execute("""INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, request_id)
                    SELECT user_id, 'user.profile.update', 'user_profile', 'req-t90-' || left(user_id::text, 8)
                    FROM career.users WHERE email LIKE 't90-%'""")
    conn.execute("""INSERT INTO career.ai_usage_records (provider_model, feature_code, input_tokens, output_tokens)
                    SELECT 'mock', 'agent', g, g FROM generate_series(1, 500) g""")


def app_smoke(url: str) -> dict:
    """복원된 DB 에 실제 앱(create_app)을 붙여 DB 연결·공개 조회가 되는지."""
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.update({"APP_ENV": "test", "DATABASE_URL": url, "JWT_SECRET": "t90-drill-secret-0123456789-abcdefghij"})
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_app
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        health = client.get("/health/db")
        roles = client.get("/api/v1/job-roles", params={"limit": 5})
        return {"health_db": health.status_code, "job_roles": roles.status_code,
                "job_roles_items": len(roles.json().get("items", [])) if roles.status_code == 200 else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--keep-dump", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    admin_url = os.environ["T90_DRILL_ADMIN_URL"]
    options = guard(admin_url)
    pg_bin = Path(os.environ.get("PG_BIN", ""))
    tool = lambda name: str(pg_bin / name) if pg_bin.parts else name  # noqa: E731
    import psycopg
    from psycopg.conninfo import make_conninfo

    def db_url(name):
        return make_conninfo(admin_url, dbname=name)

    with psycopg.connect(admin_url, autocommit=True) as admin:
        for name in (SOURCE, RESTORE):
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.execute(f'CREATE DATABASE "{SOURCE}"')
        server_version = admin.execute("SHOW server_version").fetchone()[0]
    result: dict = {"generated_at": datetime.now(UTC).isoformat(), "server_version": server_version,
                    "pg_dump_version": subprocess.run([tool("pg_dump"), "--version"], capture_output=True, text=True).stdout.strip()}
    dump_dir = tempfile.mkdtemp(prefix="t90_drill_")
    dump = Path(dump_dir) / "t90_source.dump"
    try:
        with psycopg.connect(db_url(SOURCE), autocommit=True) as src:
            seed_source(src)
            before = fingerprint(src)
        env = {**os.environ, "PGHOST": options["host"], "PGPORT": str(options.get("port", 5432)),
               "PGUSER": options.get("user", "")}
        started = time.perf_counter()
        subprocess.run([tool("pg_dump"), "-Fc", "--no-owner", "--no-privileges", "-d", SOURCE, "-f", str(dump)],
                       check=True, env=env)
        result["dump_s"] = round(time.perf_counter() - started, 3)
        result["dump_bytes"] = dump.stat().st_size
        result["dump_sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
        listing = subprocess.run([tool("pg_restore"), "--list", str(dump)], capture_output=True, text=True, check=True).stdout
        result["archive_toc_entries"] = sum(1 for line in listing.splitlines() if line and not line.startswith(";"))
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{RESTORE}"')
        started = time.perf_counter()
        subprocess.run([tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "-d", RESTORE, str(dump)],
                       check=True, env=env)
        result["restore_s"] = round(time.perf_counter() - started, 3)
        with psycopg.connect(db_url(RESTORE), autocommit=True) as dst:
            after = fingerprint(dst)
        mismatched = [t for t in before["tables"] if before["tables"][t] != after["tables"].get(t)]
        result.update({
            "tables": len(before["tables"]),
            "total_rows": sum(v["rows"] for v in before["tables"].values()),
            "table_mismatches": mismatched,
            "missing_tables": sorted(set(before["tables"]) - set(after["tables"])),
            "objects_source": before["objects"], "objects_restore": after["objects"],
            "objects_equal": before["objects"] == after["objects"],
            "app_smoke": app_smoke(f"postgresql://{options.get('user', '')}@{options['host']}:{options.get('port', 5432)}/{RESTORE}"),
        })
        result["verdict"] = "PASS" if (not mismatched and result["objects_equal"] and not result["missing_tables"]
                                       and result["app_smoke"]["health_db"] == 200
                                       and result["app_smoke"]["job_roles"] == 200) else "FAIL"
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            for name in (SOURCE, RESTORE):
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        if not args.keep_dump:
            dump.unlink(missing_ok=True)
            Path(dump_dir).rmdir()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
