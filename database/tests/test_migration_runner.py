"""T08 migration runner tests.

Unit tests (no DB) always run. Integration tests need a DISPOSABLE PostgreSQL
superuser connection and are skipped unless MIGRATION_TEST_ADMIN_PSQL is set, e.g.

    MIGRATION_TEST_ADMIN_PSQL="psql -h localhost -U postgres" \
        python3 -m unittest database/tests/test_migration_runner.py -v

Every integration test creates and drops its own database. Never point this at Staging.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "database" / "migrate.py"
sys.path.insert(0, str(RUNNER.parent))
import migrate  # noqa: E402

ADMIN = os.environ.get("MIGRATION_TEST_ADMIN_PSQL")
HEADER = "-- Purpose: test fixture\n-- Recovery: forward fix or restore from backup\n"


def write(directory: Path, name: str, body: str, header: str = HEADER) -> Path:
    path = directory / name
    path.write_text(header + textwrap.dedent(body), encoding="utf-8")
    return path


class LintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assertLintFails(self, fragment: str):
        with self.assertRaises(migrate.MigrationError) as ctx:
            migrate.load_migrations(self.dir)
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_files_sorted_and_drafts_ignored(self):
        write(self.dir, "0002_b.sql", "CREATE TABLE career.b (id int);")
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        (self.dir / "DRAFT_0001_initial_schema.sql").write_text("BEGIN; nonsense; COMMIT;")
        (self.dir / "README.md").write_text("# doc")
        self.assertEqual([m.version for m in migrate.load_migrations(self.dir)], ["0001", "0002"])

    def test_crlf_and_lf_have_same_checksum(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);\n")
        lf = migrate.load_migrations(self.dir)[0].checksum
        path = self.dir / "0001_a.sql"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(migrate.load_migrations(self.dir)[0].checksum, lf)

    def test_bad_name(self):
        write(self.dir, "2-add-table.sql", "SELECT 1;")
        self.assertLintFails("name must look like")

    def test_duplicate_version(self):
        write(self.dir, "0001_a.sql", "SELECT 1;")
        write(self.dir, "0001_b.sql", "SELECT 1;")
        self.assertLintFails("duplicate version 0001")

    def test_version_zero(self):
        write(self.dir, "0000_a.sql", "SELECT 1;")
        self.assertLintFails("versions start at 0001")

    def test_missing_headers(self):
        write(self.dir, "0001_a.sql", "SELECT 1;", header="")
        self.assertLintFails("-- Recovery:")

    def test_transaction_control_rejected(self):
        write(self.dir, "0001_a.sql", "BEGIN;\nSELECT 1;\nCOMMIT;")
        self.assertLintFails("transaction control")

    def test_plpgsql_begin_end_allowed(self):
        write(self.dir, "0001_a.sql", "DO $$\nBEGIN\n  PERFORM 1;\nEND;\n$$;")
        self.assertEqual(len(migrate.load_migrations(self.dir)), 1)

    def test_commented_out_statements_ignored(self):
        write(self.dir, "0001_a.sql", "-- BEGIN;\n/* DROP TABLE x; */\nSELECT 1;")
        self.assertEqual(len(migrate.load_migrations(self.dir)), 1)

    def test_concurrently_password_role_rejected(self):
        write(self.dir, "0001_a.sql", "CREATE INDEX CONCURRENTLY i ON t (c);")
        write(self.dir, "0002_b.sql", "CREATE ROLE x LOGIN PASSWORD 'secret';")
        write(self.dir, "0003_c.sql", "SET ROLE postgres;")
        with self.assertRaises(migrate.MigrationError) as ctx:
            migrate.load_migrations(self.dir)
        message = str(ctx.exception)
        for fragment in ("CONCURRENTLY", "passwords", "role switching"):
            self.assertIn(fragment, message)

    def test_destructive_needs_approval_header(self):
        write(self.dir, "0001_a.sql", "DROP TABLE career.a;")
        self.assertLintFails("Destructive-Approval")
        write(self.dir, "0001_a.sql", "DROP TABLE career.a;",
              header=HEADER + "-- Destructive-Approval: REDMINE-1600\n")
        self.assertEqual(len(migrate.load_migrations(self.dir)), 1)

    def test_password_hash_column_is_fine(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (password_hash text);")
        self.assertEqual(len(migrate.load_migrations(self.dir)), 1)

    def test_repository_migrations_pass_lint(self):
        self.assertEqual(migrate.main(["lint"]), 0)


@unittest.skipUnless(ADMIN, "set MIGRATION_TEST_ADMIN_PSQL to a disposable PostgreSQL superuser")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = f"t08_{uuid.uuid4().hex[:10]}"
        self.admin(f'CREATE DATABASE "{self.db}";', db="postgres")
        self.addCleanup(self.admin, f'DROP DATABASE IF EXISTS "{self.db}" WITH (FORCE);', "postgres")
        for bootstrap in ("DRAFT_00_create_roles_schema.sql", "DRAFT_01_migration_history.sql"):
            self.admin((ROOT / "database" / "security" / bootstrap).read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    # helpers -----------------------------------------------------------------
    def admin(self, sql: str, db: str = None) -> str:
        cmd = shlex.split(ADMIN) + ["-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", db or self.db, "-f", "-"]
        result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def run_cli(self, *args: str, env_extra: dict = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        env.update(env_extra or {})
        cmd = [sys.executable, str(RUNNER), "--dir", str(self.dir),
               "--psql", f"{ADMIN} -d {self.db}", *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def ledger(self) -> list:
        out = self.admin("SELECT version FROM career_migration.schema_migrations ORDER BY version;")
        return out.split() if out else []

    def table_exists(self, name: str) -> bool:
        return self.admin(f"SELECT to_regclass('career.{name}') IS NOT NULL;") == "t"

    # tests -------------------------------------------------------------------
    def test_fresh_install_applies_draft_schema_with_privileges(self):
        draft = (ROOT / "database" / "migrations" / "DRAFT_0001_initial_schema.sql").read_text(encoding="utf-8")
        body = re.sub(r"^\s*(BEGIN|COMMIT);\s*$", "", draft, flags=re.M)
        write(self.dir, "0001_initial_schema.sql", body)
        write(self.dir, "0002_add_note.sql", "ALTER TABLE career.users ADD COLUMN note text;")
        result = self.run_cli("apply", "--target", "local")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APPLY=PASS count=2", result.stdout)
        self.assertEqual(self.ledger(), ["0001", "0002"])
        tables = self.admin("SELECT count(*) FROM information_schema.tables "
                            "WHERE table_schema='career' AND table_type='BASE TABLE';")
        self.assertEqual(tables, "10")
        owner = self.admin("SELECT tableowner FROM pg_tables WHERE schemaname='career' AND tablename='users';")
        self.assertEqual(owner, "career_migrator")
        privs = self.admin("SELECT has_table_privilege('career_app','career.users','INSERT'), "
                           "has_table_privilege('career_app','career_migration.schema_migrations','SELECT'), "
                           "has_table_privilege('career_reader','career_migration.schema_migrations','SELECT');")
        self.assertEqual(privs, "t|f|t")

    def test_rerun_is_noop(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        self.assertEqual(self.run_cli("apply", "--target", "local").returncode, 0)
        again = self.run_cli("apply", "--target", "local")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("nothing to apply", again.stdout)
        self.assertEqual(self.ledger(), ["0001"])

    def test_failure_rolls_back_and_stops(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        write(self.dir, "0002_broken.sql",
              "CREATE TABLE career.half_done (id int);\nINSERT INTO career.missing VALUES (1);")
        write(self.dir, "0003_c.sql", "CREATE TABLE career.c (id int);")
        result = self.run_cli("apply", "--target", "local")
        self.assertEqual(result.returncode, 1)
        self.assertIn("0002_broken.sql failed and was rolled back", result.stderr)
        self.assertEqual(self.ledger(), ["0001"])
        self.assertFalse(self.table_exists("half_done"))
        self.assertFalse(self.table_exists("c"))

    def test_checksum_drift_blocks_apply_and_verify(self):
        path = write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        self.assertEqual(self.run_cli("apply", "--target", "local").returncode, 0)
        path.write_text(HEADER + "CREATE TABLE career.a (id bigint);", encoding="utf-8")
        write(self.dir, "0002_b.sql", "CREATE TABLE career.b (id int);")
        verify = self.run_cli("verify")
        self.assertEqual(verify.returncode, 1)
        self.assertIn("file changed after it was applied", verify.stderr)
        apply = self.run_cli("apply", "--target", "local")
        self.assertEqual(apply.returncode, 1)
        self.assertFalse(self.table_exists("b"))

    def test_out_of_order_rejected(self):
        write(self.dir, "0002_b.sql", "CREATE TABLE career.b (id int);")
        self.assertEqual(self.run_cli("apply", "--target", "local").returncode, 0)
        write(self.dir, "0001_late.sql", "CREATE TABLE career.late (id int);")
        result = self.run_cli("apply", "--target", "local")
        self.assertEqual(result.returncode, 1)
        self.assertIn("out-of-order", result.stderr)
        self.assertFalse(self.table_exists("late"))

    def test_apply_to_and_dry_run(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        write(self.dir, "0002_b.sql", "CREATE TABLE career.b (id int);")
        dry = self.run_cli("apply", "--target", "local", "--dry-run")
        self.assertIn("DRY-RUN would apply 0002_b.sql", dry.stdout)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.run_cli("apply", "--target", "local", "--to", "0001").returncode, 0)
        self.assertEqual(self.ledger(), ["0001"])
        status = self.run_cli("status")
        self.assertIn("0002 pending", status.stdout)

    def test_already_applied_guard_inside_transaction(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        migration = migrate.load_migrations(self.dir)[0]
        script = migrate.build_apply_script(migration, "local", None)
        self.admin('SET ROLE career_migrator;\n' + script)
        with self.assertRaises(AssertionError) as ctx:  # second concurrent-style run
            self.admin('SET ROLE career_migrator;\n' + script)
        self.assertIn("already applied", str(ctx.exception))
        self.assertEqual(self.ledger(), ["0001"])

    def test_staging_guards(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        no_approval = self.run_cli("apply", "--target", "staging", "--confirm-db", self.db)
        self.assertIn("requires --approval", no_approval.stderr)
        wrong_db = self.run_cli("apply", "--target", "staging", "--approval", "REDMINE-1", "--confirm-db", "x")
        self.assertIn("requires --confirm-db", wrong_db.stderr)
        from_ci = self.run_cli("apply", "--target", "staging", "--approval", "REDMINE-1",
                               "--confirm-db", self.db, env_extra={"GITHUB_ACTIONS": "true"})
        self.assertIn("refusing staging migration from CI", from_ci.stderr)
        self.assertEqual(self.ledger(), [])
        ok = self.run_cli("apply", "--target", "staging", "--approval", "REDMINE-1", "--confirm-db", self.db)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.admin("SELECT target_env, approval_ref FROM career_migration.schema_migrations;"),
                         "staging|REDMINE-1")

    def test_missing_ledger_explains_bootstrap(self):
        self.admin("DROP SCHEMA career_migration CASCADE;")
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        result = self.run_cli("status")
        self.assertEqual(result.returncode, 1)
        self.assertIn("DRAFT_01_migration_history.sql", result.stderr)

    def test_app_role_cannot_tamper_with_ledger(self):
        write(self.dir, "0001_a.sql", "CREATE TABLE career.a (id int);")
        self.assertEqual(self.run_cli("apply", "--target", "local").returncode, 0)
        with self.assertRaises(AssertionError) as ctx:
            self.admin("SET ROLE career_app; DELETE FROM career_migration.schema_migrations;")
        self.assertIn("permission denied", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
