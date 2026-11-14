"""#344 GCP migration rehearsal on DISPOSABLE PostgreSQL (CI: postgres:18.3, same minor as Cloud SQL).

Reproduces the GCP Cloud SQL state of database ai_career_poc and rehearses the planned procedure:

* GCP-like start: owner role ai_career_poc (NOLOGIN), app roles career_app / career_reader / career_sync,
  0001 applied outside the runner, synthetic T10 seed, NO migration ledger.
* The operator is a non-superuser LOGIN member of ai_career_poc (like the Cloud SQL postgres user).
* database/security/GCP_01_migration_history_bootstrap.sql records 0001 as a baseline,
  then database/migrate.py --role ai_career_poc applies 0002 and 0003 with the staging guards.
* Reference schema: a second database built purely by the runner (DRAFT_00 + DRAFT_01 + 0001..0003).

Synthetic fixtures only. No production data, secrets or cloud connections. Every database is created
and dropped by this test. Skipped unless MIGRATION_TEST_ADMIN_PSQL points at a disposable superuser:

    MIGRATION_TEST_ADMIN_PSQL="psql -h localhost -U postgres" \
        python3 -m unittest database/tests/test_t344_gcp_pg18_rehearsal.py -v

Set T344_EXPECT_PG=18.3 to fail when the server is not that version (CI does).
"""
from __future__ import annotations

import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "database" / "migrate.py"
sys.path.insert(0, str(RUNNER.parent))
import migrate  # noqa: E402

ADMIN = os.environ.get("MIGRATION_TEST_ADMIN_PSQL")
EXPECT_PG = os.environ.get("T344_EXPECT_PG")
DB = "ai_career_poc"                      # the runner's staging guard keys on this exact name
OPERATOR = "t344_operator"
APPROVAL = "GCP-PROD-344-CI-REHEARSAL"
BOOTSTRAP = ROOT / "database" / "security" / "GCP_01_migration_history_bootstrap.sql"
SECURITY = ROOT / "database" / "security"
MIGRATIONS = {m.version: m for m in migrate.load_migrations(migrate.DEFAULT_DIR)}
MARKET_TABLES = ("market_observations", "market_forecasts")   # 0003 adds a column, so row text changes
SEP = "\x1f"

EVIDENCE: dict = {}


def _psql(sql: str, db: str, user: str = None, password: str = None, check: bool = True,
          app_name: str = None) -> subprocess.CompletedProcess:
    cmd = shlex.split(ADMIN) + (["-U", user] if user else []) + [
        "-X", "-q", "-At", "-F", SEP, "-v", "ON_ERROR_STOP=1", "-d", db, "-f", "-"]
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    if app_name:
        env["PGAPPNAME"] = app_name
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, encoding="utf-8", env=env)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    return result


def admin(sql: str, db: str = DB) -> str:
    return _psql(sql, db).stdout.strip()


def rows(sql: str, db: str = DB) -> set:
    # Not admin(): str.strip() treats SEP (\x1f) as whitespace and would drop a trailing empty field.
    return {tuple(line.split(SEP)) for line in _psql(sql, db).stdout.splitlines() if line}


@unittest.skipUnless(ADMIN, "set MIGRATION_TEST_ADMIN_PSQL to a disposable PostgreSQL superuser")
class GcpPg18Rehearsal(unittest.TestCase):
    """Ordered steps (test_01 .. test_15) sharing one rehearsal database."""

    @classmethod
    def setUpClass(cls):
        cls.ref_db = f"t344ref_{uuid.uuid4().hex[:10]}"
        cls.op_password = secrets.token_urlsafe(24)   # disposable, never printed
        if admin(f"SELECT count(*) FROM pg_database WHERE datname = '{DB}';", "postgres") != "0":
            raise unittest.SkipTest(f"database {DB} already exists here; this test needs a disposable server")
        cls.addClassCleanup(cls._cleanup)
        cls._build_gcp_like()
        cls._build_reference()
        cls.before = cls._table_fingerprints()

    @classmethod
    def _cleanup(cls):
        for db in (DB, cls.ref_db):
            _psql(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);', "postgres", check=False)
        _psql(f"DROP ROLE IF EXISTS {OPERATOR};", "postgres", check=False)
        lines = [f"| {k} | {v} |" for k, v in EVIDENCE.items()]
        print("T344_EVIDENCE " + json.dumps(EVIDENCE, ensure_ascii=False, sort_keys=True))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("### #344 GCP-like PostgreSQL rehearsal\n\n| step | evidence |\n|---|---|\n"
                         + "\n".join(lines) + "\n\n")

    @classmethod
    def _build_gcp_like(cls):
        admin("""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_career_poc') THEN CREATE ROLE ai_career_poc NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN CREATE ROLE career_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN CREATE ROLE career_reader NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_sync') THEN CREATE ROLE career_sync NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't344_operator') THEN CREATE ROLE t344_operator NOLOGIN; END IF;
END $$;""", "postgres")
        _psql(f"ALTER ROLE {OPERATOR} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '{cls.op_password}';\n"
              f"GRANT ai_career_poc TO {OPERATOR};", "postgres")
        admin(f"CREATE DATABASE {DB} OWNER ai_career_poc;", "postgres")
        schema = MIGRATIONS["0001"].sql
        admin("SET ROLE ai_career_poc;\nCREATE SCHEMA career AUTHORIZATION ai_career_poc;\n" + schema + """
GRANT USAGE ON SCHEMA career TO career_app, career_reader, career_sync;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA career TO career_app;
GRANT SELECT ON ALL TABLES IN SCHEMA career TO career_reader;
""")
        admin((ROOT / "database" / "seeds" / "0001_initial_seed.sql").read_text(encoding="utf-8"))

    @classmethod
    def _build_reference(cls):
        admin(f'CREATE DATABASE "{cls.ref_db}";', "postgres")
        for name in ("DRAFT_00_create_roles_schema.sql", "DRAFT_01_migration_history.sql"):
            admin((SECURITY / name).read_text(encoding="utf-8"), cls.ref_db)
        result = cls._runner(cls.ref_db, "career_migrator", "apply", "--target", "local", user=None)
        if result.returncode != 0:
            raise AssertionError("reference build failed: " + result.stderr)

    @classmethod
    def _runner(cls, db: str, role: str, *args: str, user: str = OPERATOR) -> subprocess.CompletedProcess:
        # The runner refuses --target staging when CI/GITHUB_ACTIONS is set (no auto-migration from CI).
        # Removing them here simulates the manual operator run that the procedure prescribes.
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        psql_cmd = f"{ADMIN} -d {db}"
        if user:
            psql_cmd = f"{ADMIN} -U {user} -d {db}"
            env["PGPASSWORD"] = cls.op_password
        return subprocess.run([sys.executable, "-B", str(RUNNER), "--psql", psql_cmd, "--role", role, *args],
                              capture_output=True, text=True, encoding="utf-8", env=env)

    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return self._runner(DB, "ai_career_poc", *args)

    def bootstrap(self, db: str = DB, checksum: str = None, approval: str = APPROVAL) -> subprocess.CompletedProcess:
        checksum = MIGRATIONS["0001"].checksum if checksum is None else checksum
        sql = BOOTSTRAP.read_text(encoding="utf-8")
        cmd_vars = f"\\set baseline_checksum {checksum}\n\\set approval {approval}\n" if checksum else ""
        return _psql(cmd_vars + sql, db, user=OPERATOR, password=self.op_password, check=False)

    @classmethod
    def _table_fingerprints(cls) -> dict:
        tables = admin("SELECT tablename FROM pg_tables WHERE schemaname = 'career' ORDER BY 1;").split()
        out = {}
        for t in tables:
            if t in MARKET_TABLES:
                out[t] = admin(f"SELECT count(*) FROM career.{t};")
            else:
                out[t] = admin(f"SELECT count(*) || ':' || md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) "
                               f"FROM career.{t} x;")
        return out

    def skill_id_columns(self) -> str:
        return admin("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'career' "
                     "AND column_name = 'skill_id' AND table_name IN ('market_observations', 'market_forecasts');")

    def ledger(self) -> str:
        return admin("SELECT string_agg(version, ',' ORDER BY version) FROM career_migration.schema_migrations;")

    @staticmethod
    def signature(db: str) -> dict:
        schemas = "('career', 'career_migration')"
        return {
            "tables": rows(f"SELECT n.nspname || '.' || c.relname, c.relkind FROM pg_class c "
                           f"JOIN pg_namespace n ON n.oid = c.relnamespace "
                           f"WHERE n.nspname IN {schemas} AND c.relkind IN ('r','p','v','m','S')", db),
            "columns": rows(f"SELECT table_schema || '.' || table_name, column_name, data_type, is_nullable, "
                            f"coalesce(column_default, '') FROM information_schema.columns "
                            f"WHERE table_schema IN {schemas}", db),
            "constraints": rows(f"SELECT n.nspname || '.' || t.relname, con.conname, con.contype, "
                                f"pg_get_constraintdef(con.oid) FROM pg_constraint con "
                                f"JOIN pg_class t ON t.oid = con.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
                                f"WHERE n.nspname IN {schemas}", db),
            "indexes": rows(f"SELECT schemaname || '.' || tablename, indexname, indexdef FROM pg_indexes "
                            f"WHERE schemaname IN {schemas}", db),
            "comments": rows(f"SELECT c.relname, a.attname, col_description(c.oid, a.attnum) FROM pg_attribute a "
                             f"JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                             f"WHERE n.nspname = 'career' AND a.attnum > 0 AND col_description(c.oid, a.attnum) IS NOT NULL",
                             db),
        }

    # ------------------------------------------------------------------ steps
    def test_01_server_version(self):
        version = admin("SHOW server_version;")
        EVIDENCE["01_server_version"] = version
        if EXPECT_PG:
            self.assertEqual(version.split()[0], EXPECT_PG, "rehearsal must run on the Cloud SQL minor version")

    def test_02_gcp_like_state_without_ledger(self):
        self.assertEqual(admin("SELECT to_regclass('career_migration.schema_migrations') IS NULL;"), "t")
        owners = admin("SELECT string_agg(DISTINCT pg_get_userbyid(relowner), ',') FROM pg_class c "
                       "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'career' AND relkind = 'r';")
        self.assertEqual(owners, "ai_career_poc")
        self.assertEqual(admin(f"SELECT rolsuper FROM pg_roles WHERE rolname = '{OPERATOR}';"), "f")
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 1)
        self.assertIn("ledger table career_migration.schema_migrations not found", status.stderr)
        tables = admin("SELECT count(*) FROM pg_tables WHERE schemaname = 'career';")
        postings = admin("SELECT count(*) FROM career.job_postings;")
        EVIDENCE["02_gcp_like_start"] = f"tables={tables} owner={owners} seed_postings={postings} ledger=absent runner=refuses"

    def test_03_bootstrap_guards(self):
        wrong_db = self.bootstrap(db=self.ref_db)
        self.assertNotEqual(wrong_db.returncode, 0)
        self.assertIn("wrong database", wrong_db.stderr)
        no_vars = self.bootstrap(checksum="")
        self.assertNotEqual(no_vars.returncode, 0)
        admin("ALTER TABLE career.account_deletion_requests ALTER COLUMN scheduled_purge_at DROP NOT NULL;")
        try:
            not_pristine = self.bootstrap()
        finally:
            admin("ALTER TABLE career.account_deletion_requests ALTER COLUMN scheduled_purge_at SET NOT NULL;")
        self.assertNotEqual(not_pristine.returncode, 0)
        self.assertIn("0002 already present", not_pristine.stderr)
        self.assertEqual(admin("SELECT to_regnamespace('career_migration') IS NULL;"), "t", "guard must roll back")
        EVIDENCE["03_bootstrap_guards"] = "wrong_db=refused missing_vars=refused 0002_present=refused(rolled back)"

    def test_04_bootstrap_and_baseline_idempotent(self):
        for attempt in (1, 2):
            result = self.bootstrap()
            self.assertEqual(result.returncode, 0, f"attempt {attempt}: {result.stderr}")
        row = admin("SELECT version, name, checksum, target_env, approval_ref, execution_ms, runner_version, applied_by "
                    "FROM career_migration.schema_migrations;").split(SEP)
        expected = ["0001", "initial_schema", MIGRATIONS["0001"].checksum, "staging", APPROVAL, "0", "baseline", OPERATOR]
        self.assertEqual(row, expected)
        owner = admin("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'career_migration.schema_migrations'::regclass;")
        self.assertEqual(owner, "ai_career_poc")
        denied = _psql("SET ROLE career_app; SELECT 1 FROM career_migration.schema_migrations;", DB, check=False)
        self.assertIn("permission denied", denied.stderr)
        self.assertEqual(admin("SET ROLE career_reader; SELECT count(*) FROM career_migration.schema_migrations;"), "1")
        EVIDENCE["04_bootstrap_baseline"] = (f"runs=2 rows=1 checksum={MIGRATIONS['0001'].checksum[:12]} "
                                            f"owner={owner} app=denied reader=select")

    def test_05_verify_baseline_checksum(self):
        verify = self.run_cli("verify")
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertIn("VERIFY=PASS applied=1 pending=2", verify.stdout)
        status = self.run_cli("status")
        self.assertIn("0001 applied", status.stdout)
        self.assertIn("0002 pending", status.stdout)
        EVIDENCE["05_verify_baseline"] = verify.stdout.strip()

    def test_06_runner_guards_and_dry_run(self):
        local = self.run_cli("apply", "--target", "local", "--to", "0002")
        self.assertIn("use --target staging", local.stderr)
        no_approval = self.run_cli("apply", "--target", "staging", "--confirm-db", DB, "--to", "0002")
        self.assertIn("requires --approval", no_approval.stderr)
        wrong_db = self.run_cli("apply", "--target", "staging", "--approval", APPROVAL, "--confirm-db", "x", "--to", "0002")
        self.assertIn("requires --confirm-db", wrong_db.stderr)
        dry = self.run_cli("apply", "--target", "staging", "--approval", APPROVAL, "--confirm-db", DB, "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        for v in ("0002", "0003"):
            self.assertIn(f"{MIGRATIONS[v].path.name} checksum={MIGRATIONS[v].checksum[:12]}", dry.stdout)
        self.assertEqual(self.ledger(), "0001")
        EVIDENCE["06_runner_guards"] = (f"local/no-approval/wrong-db=refused dry_run 0002={MIGRATIONS['0002'].checksum[:12]} "
                                       f"0003={MIGRATIONS['0003'].checksum[:12]}")

    def apply(self, *extra: str) -> tuple:
        started = time.monotonic()
        result = self.run_cli("apply", "--target", "staging", "--approval", APPROVAL, "--confirm-db", DB, *extra)
        return result, time.monotonic() - started

    def test_07_apply_0002(self):
        result, took = self.apply("--to", "0002")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APPLIED 0002_deletion_request_unscheduled.sql", result.stdout)
        nullable = admin("SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'career' "
                         "AND table_name = 'account_deletion_requests' AND column_name = 'scheduled_purge_at';")
        self.assertEqual(nullable, "YES")
        insert = _psql("BEGIN; SET LOCAL ROLE career_app;\n"
                       "INSERT INTO career.account_deletion_requests (user_id, status, requested_at, scheduled_purge_at) "
                       "SELECT user_id, 'requested', now(), NULL FROM career.users ORDER BY user_id LIMIT 1;\nROLLBACK;",
                       DB, check=False)
        self.assertEqual(insert.returncode, 0, insert.stderr)
        self.assertEqual(self.ledger(), "0001,0002")
        EVIDENCE["07_apply_0002"] = f"{took:.2f}s scheduled_purge_at nullable=YES app_insert_null=ok(rolled back)"

    def test_08_0003_constraint_violation_rolls_back(self):
        index_before = admin("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_market_observations_1';")
        admin("INSERT INTO career.market_observations (source_id, observed_on, period, metric_code, metric_value) "
              "SELECT source_id, current_date, 'week', 'posting_count', 1.5 FROM career.data_sources LIMIT 1;")
        try:
            result, _ = self.apply()
        finally:
            admin("DELETE FROM career.market_observations;")
        self.assertEqual(result.returncode, 1)
        self.assertIn("0003_market_metric_skill_dimension.sql failed and was rolled back", result.stderr)
        self.assertIn("check constraint", result.stderr)
        self.assertEqual(self.skill_id_columns(), "0")
        self.assertEqual(admin("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_market_observations_1';"), index_before)
        self.assertEqual(self.ledger(), "0001,0002")
        EVIDENCE["08_check_violation_rollback"] = "0003 failed -> skill_id cols=0, ix_market_observations_1 unchanged, ledger=0001,0002"

    def test_09_0003_lock_timeout_rolls_back(self):
        holder_cmd = shlex.split(ADMIN) + ["-X", "-q", "-d", DB, "-c",
                                           "BEGIN; LOCK TABLE career.market_observations IN ACCESS SHARE MODE; "
                                           "SELECT pg_sleep(120); COMMIT;"]
        holder = subprocess.Popen(holder_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  env=dict(os.environ, PGAPPNAME="t344_lock_holder"))
        try:
            for _ in range(100):
                held = admin("SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) "
                             "WHERE a.application_name = 't344_lock_holder' AND l.granted "
                             "AND l.relation = 'career.market_observations'::regclass;")
                if held == "1":
                    break
                time.sleep(0.1)
            self.assertEqual(held, "1", "lock holder did not start")
            result, waited = self.apply()
        finally:
            admin("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 't344_lock_holder';")
            holder.wait(timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("lock timeout", result.stderr)
        self.assertGreaterEqual(waited, 9.5)
        self.assertLess(waited, 30)
        self.assertEqual(self.skill_id_columns(), "0")
        self.assertEqual(self.ledger(), "0001,0002")
        EVIDENCE["09_lock_timeout_rollback"] = f"cancelled after {waited:.1f}s (lock_timeout=10s), skill_id cols=0, ledger=0001,0002"

    def test_10_apply_0003_and_verify(self):
        result, took = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APPLIED 0003_market_metric_skill_dimension.sql", result.stdout)
        self.assertEqual(self.skill_id_columns(), "2")
        verify = self.run_cli("verify")
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertIn("VERIFY=PASS applied=3 pending=0", verify.stdout)
        self.assertEqual(admin("SET ROLE career_app; SELECT count(skill_id) FROM career.market_observations;"), "0")
        EVIDENCE["10_apply_0003"] = f"{took:.2f}s skill_id cols=2 app_select_new_column=ok {verify.stdout.strip()}"

    def test_11_ledger_contents(self):
        got = admin("SELECT version, checksum, target_env, approval_ref, runner_version, applied_by "
                    "FROM career_migration.schema_migrations ORDER BY version;").splitlines()
        expected = [SEP.join(["0001", MIGRATIONS["0001"].checksum, "staging", APPROVAL, "baseline", OPERATOR])] + [
            SEP.join([v, MIGRATIONS[v].checksum, "staging", APPROVAL, migrate.RUNNER_VERSION, OPERATOR])
            for v in ("0002", "0003")]
        self.assertEqual(got, expected)
        EVIDENCE["11_ledger"] = f"rows=3 checksums=match target_env=staging approval_ref={APPROVAL} applied_by=non-superuser operator"

    def test_12_rerun_is_safe(self):
        snapshot = admin("SELECT string_agg(version || checksum || applied_at, ',' ORDER BY version) "
                         "FROM career_migration.schema_migrations;")
        again, _ = self.apply()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("nothing to apply", again.stdout)
        boot = self.bootstrap()
        self.assertEqual(boot.returncode, 0, boot.stderr)
        script = migrate.build_apply_script(MIGRATIONS["0002"], "staging", APPROVAL)
        direct = _psql('SET ROLE "ai_career_poc";\n' + script, DB, user=OPERATOR, password=self.op_password, check=False)
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn("migration 0002 is already applied", direct.stderr)
        self.assertEqual(admin("SELECT string_agg(version || checksum || applied_at, ',' ORDER BY version) "
                               "FROM career_migration.schema_migrations;"), snapshot)
        EVIDENCE["12_rerun_safety"] = "apply=nothing to apply, bootstrap re-run=no-op, direct 0002 re-run=refused, ledger unchanged"

    def test_13_schema_signature_matches_runner_reference(self):
        mine, ref = self.signature(DB), self.signature(self.ref_db)
        diff = {k: (sorted(mine[k] - ref[k])[:5], sorted(ref[k] - mine[k])[:5]) for k in mine if mine[k] != ref[k]}
        self.assertEqual(diff, {}, "rehearsal schema differs from the runner-built 0001..0003 reference")
        owners = admin("SELECT string_agg(DISTINCT n.nspname || '=' || pg_get_userbyid(c.relowner), ',') FROM pg_class c "
                       "JOIN pg_namespace n ON n.oid = c.relnamespace "
                       "WHERE n.nspname IN ('career', 'career_migration') AND c.relkind IN ('r', 'i');")
        self.assertEqual(owners, "career=ai_career_poc,career_migration=ai_career_poc")
        counts = " ".join(f"{k}={len(v)}" for k, v in mine.items())
        EVIDENCE["13_schema_signature"] = f"identical to runner reference ({counts}); owners {owners}"

    def test_14_existing_data_preserved(self):
        after = self._table_fingerprints()
        self.assertEqual(after, self.before)
        EVIDENCE["14_data_preserved"] = (f"{len(after)} tables: row count + md5 of row text unchanged "
                                        f"(market_* count only: 0003 adds a column)")


if __name__ == "__main__":
    unittest.main()
