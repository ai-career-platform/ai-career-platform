"""T115 migration 안전 게이트 시험.

단위(항상): PR 규칙 G1~G7, Staging 사전점검.
통합(일회용 PostgreSQL, MIGRATION_TEST_ADMIN_PSQL 설정 시): 실패 migration 원자 롤백·수정 후 재적용,
승인된 파괴적 migration 뒤 백업 복원 리허설(pg_dump 주 버전이 서버 이상일 때).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "database" / "gate"))
import t115_migration_gate as gate  # noqa: E402

ADMIN = os.environ.get("MIGRATION_TEST_ADMIN_PSQL")
H = "-- Purpose: t115 fixture\n-- Recovery: forward fix or restore from backup\n"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)


def files(**named):
    return {f"{k[1:5]}_{k[6:]}.sql" if k.startswith("m") else k: v for k, v in named.items()}


BASE = {"0001_init.sql": H + "CREATE TABLE career.a (id int);\n", "0002_more.sql": H + "CREATE TABLE career.b (id int);\n"}


class PrRuleTests(unittest.TestCase):
    def head(self, **extra):
        return {**BASE, **extra}

    def assertProblem(self, problems, code, text=""):
        self.assertTrue(any(p.startswith(code) and text in p for p in problems), problems)

    # G1
    def test_modifying_or_removing_an_applied_migration_fails(self):
        changed = self.head(**{"0001_init.sql": H + "CREATE TABLE career.a (id bigint);\n"})
        self.assertProblem(gate.check_files(BASE, changed), "G1", "modified")
        removed = {"0002_more.sql": BASE["0002_more.sql"]}
        self.assertProblem(gate.check_files(BASE, removed), "G1", "removed")

    def test_line_ending_only_change_is_not_a_modification(self):
        crlf = self.head(**{"0001_init.sql": BASE["0001_init.sql"].replace("\n", "\r\n")})
        self.assertEqual(gate.check_files(BASE, crlf), [])

    # G2
    def test_new_number_must_follow_base_without_gaps_or_duplicates(self):
        self.assertEqual(gate.check_files(BASE, self.head(**{"0003_c.sql": H + "SELECT 1;\n"})), [])
        self.assertProblem(gate.check_files(BASE, self.head(**{"0005_c.sql": H + "SELECT 1;\n"})), "G2", "expected 0003")
        dup = self.head(**{"0002_other.sql": H + "SELECT 1;\n"})
        problems = gate.check_files(BASE, dup)
        self.assertProblem(problems, "G2", "duplicate")
        self.assertProblem(problems, "G2", "greater than base max")

    # G4
    def test_breaking_ddl_needs_compatibility_header(self):
        cases = {
            "ALTER TABLE career.a DROP COLUMN id;": "drop column",
            "ALTER TABLE career.a RENAME COLUMN id TO aid;": "rename column",
            "ALTER TABLE career.a RENAME TO a2;": "rename table",
            "ALTER TABLE career.a ALTER COLUMN id TYPE bigint;": "change column type",
            "ALTER TABLE career.a ALTER COLUMN id SET NOT NULL;": "set not null",
            "ALTER TABLE career.a ADD COLUMN note text NOT NULL;": "add NOT NULL column without default",
        }
        for sql, label in cases.items():
            with self.subTest(label=label):
                problems = gate.check_files(BASE, self.head(**{"0003_c.sql": H + sql + "\n"}))
                self.assertProblem(problems, "G4", label)
                ok = H + "-- Compatibility: contract — app v2 deployed first, reads both columns\n" + sql + "\n"
                self.assertEqual([p for p in gate.check_files(BASE, self.head(**{"0003_c.sql": ok})) if p.startswith("G4")], [])

    def test_additive_changes_need_no_compatibility_header(self):
        for sql in ("ALTER TABLE career.a ADD COLUMN note text;",
                    "ALTER TABLE career.a ADD COLUMN flag boolean NOT NULL DEFAULT false;",
                    "CREATE INDEX ix_a ON career.a (id);", "ALTER TABLE career.a ALTER COLUMN id DROP NOT NULL;"):
            with self.subTest(sql=sql):
                self.assertEqual(gate.check_files(BASE, self.head(**{"0003_c.sql": H + sql + "\n"})), [])

    def test_header_in_a_comment_body_does_not_count(self):
        sql = H + "ALTER TABLE career.a DROP COLUMN id; -- Compatibility: contract\n"
        self.assertProblem(gate.check_files(BASE, self.head(**{"0003_c.sql": sql})), "G4")

    # G5
    def test_data_changes_need_data_impact_header(self):
        for sql in ("UPDATE career.a SET id = id + 1;", "DELETE FROM career.a WHERE id < 0;",
                    "INSERT INTO career.b (id) SELECT id FROM career.a;"):
            with self.subTest(sql=sql):
                self.assertProblem(gate.check_files(BASE, self.head(**{"0003_c.sql": H + sql + "\n"})), "G5")
                ok = H + "-- Data-Impact: career.a all rows (~2k), rollback via backup\n" + sql + "\n"
                self.assertEqual(gate.check_files(BASE, self.head(**{"0003_c.sql": ok})), [])
        self.assertEqual(gate.check_files(BASE, self.head(**{"0003_c.sql": H + "INSERT INTO career.a VALUES (1);\n"})), [])

    # G3
    def test_runner_lint_runs_on_new_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / gate.MIGRATIONS).mkdir(parents=True)
            (root / gate.MIGRATIONS / "0003_bad.sql").write_text("DROP TABLE career.a;\n", encoding="utf-8")
            problems = gate.lint_new(root, ["0003_bad.sql"])
        self.assertTrue(any("Purpose" in p for p in problems) and any("Destructive-Approval" in p for p in problems),
                        problems)

    # G6, G7
    def test_application_ddl_and_automatic_apply_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backend" / "app").mkdir(parents=True)
            (root / "backend" / "app" / "bad.py").write_text('session.execute(text("ALTER TABLE career.a ADD x int"))\n',
                                                             encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "deploy.yml").write_text(
                "steps:\n  - run: python database/migrate.py apply --target staging\n", encoding="utf-8")
            self.assertEqual(len(gate.check_app_ddl(root)), 1)
            self.assertEqual(len(gate.check_auto_apply(root)), 1)

    def test_repository_has_no_app_ddl_and_no_automatic_apply(self):
        self.assertEqual(gate.check_app_ddl(), [])
        self.assertEqual(gate.check_auto_apply(), [])

    def test_repository_migrations_pass_against_their_introducing_commits(self):
        if shutil.which("git") is None:
            self.skipTest("git unavailable")
        try:
            problems = gate.pr_gate("HEAD")
        except subprocess.CalledProcessError:
            self.skipTest("git history unavailable")
        self.assertEqual(problems, [])


class PreflightTests(unittest.TestCase):
    MANIFEST = {"file": "staging_career_20261111T020000Z.dump", "created_at": "2026-11-11T02:00:00+00:00"}
    VERIFY = {"verdict": "PASS", "manifest": "staging_career_20261111T020000Z.manifest.json"}

    def run_pf(self, **over):
        args = dict(target="staging", approval="REDMINE-1522", confirm_db="career", connected_db="career",
                    verify_result=self.VERIFY, backup_manifest=self.MANIFEST, pending=["0004"], now=NOW)
        args.update(over)
        return gate.preflight(**args)

    def test_ready_when_everything_checks_out(self):
        result = self.run_pf()
        self.assertTrue(result["ready"], result)
        self.assertIn("사람이", result["next"])

    def test_each_failure_blocks(self):
        cases = {
            "no approval": dict(approval=None),
            "bad approval": dict(approval="x"),
            "wrong db": dict(confirm_db="career_old"),
            "nothing pending": dict(pending=[]),
            "no backup": dict(backup_manifest=None),
            "old backup": dict(now=NOW + timedelta(hours=26)),
            "restore failed": dict(verify_result={"verdict": "FAIL", "manifest": self.VERIFY["manifest"]}),
            "verify of another backup": dict(verify_result={"verdict": "PASS", "manifest": "other.manifest.json"}),
            "not staging": dict(target="local"),
        }
        for label, over in cases.items():
            with self.subTest(label=label):
                self.assertFalse(self.run_pf(**over)["ready"])


@unittest.skipUnless(ADMIN, "set MIGRATION_TEST_ADMIN_PSQL to a disposable PostgreSQL superuser")
class IsolatedRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.db = f"t115_{uuid.uuid4().hex[:10]}"
        self.admin(f'CREATE DATABASE "{self.db}";', db="postgres")
        self.addCleanup(self.admin, f'DROP DATABASE IF EXISTS "{self.db}" WITH (FORCE);', "postgres")
        for bootstrap in ("DRAFT_00_create_roles_schema.sql", "DRAFT_01_migration_history.sql"):
            self.admin((ROOT / "database" / "security" / bootstrap).read_text(encoding="utf-8"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def admin(self, sql: str, db: str | None = None) -> str:
        cmd = shlex.split(ADMIN) + ["-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", db or self.db, "-f", "-"]
        result = subprocess.run(cmd, input=sql, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    def apply(self) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        cmd = [sys.executable, str(ROOT / "database" / "migrate.py"), "--dir", str(self.dir),
               "--psql", f"{ADMIN} -d {self.db}", "apply", "--target", "local"]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def write(self, name: str, body: str, header: str = H) -> None:
        (self.dir / name).write_text(header + body, encoding="utf-8")

    def ledger(self) -> list[str]:
        out = self.admin("SELECT version FROM career_migration.schema_migrations ORDER BY version;")
        return out.split() if out else []

    def test_failed_migration_rolls_back_atomically_and_fix_forward_applies(self):
        self.write("0001_base.sql", "CREATE TABLE career.t115 (id int PRIMARY KEY, note text);\n"
                                    "INSERT INTO career.t115 VALUES (1, 'keep');\n")
        self.assertEqual(self.apply().returncode, 0)
        self.write("0002_half.sql", "CREATE TABLE career.t115_new (id int);\nINSERT INTO career.t115 VALUES (1, 'dup');\n")
        self.write("0003_after.sql", "CREATE TABLE career.t115_later (id int);\n")
        failed = self.apply()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.ledger(), ["0001"])
        self.assertEqual(self.admin("SELECT to_regclass('career.t115_new') IS NULL, "
                                    "to_regclass('career.t115_later') IS NULL;"), "t|t")
        self.assertEqual(self.admin("SELECT string_agg(note, ',') FROM career.t115;"), "keep")
        # 아직 적용되지 않은 파일이므로 고쳐서 다시 적용(Forward fix)
        self.write("0002_half.sql", "CREATE TABLE career.t115_new (id int);\nINSERT INTO career.t115 VALUES (2, 'new');\n")
        self.assertEqual(self.apply().returncode, 0)
        self.assertEqual(self.ledger(), ["0001", "0002", "0003"])

    def _pg_dump(self) -> list[str] | None:
        parts = shlex.split(ADMIN)
        candidate = Path(parts[0]).with_name("pg_dump" + Path(parts[0]).suffix)
        exe = str(candidate) if candidate.exists() else shutil.which("pg_dump")
        if not exe:
            return None
        client = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
        server = self.admin("SHOW server_version_num;")
        if int(client.split()[-1].split(".")[0]) < int(server) // 10000:
            return None
        return [exe, *parts[1:]]

    def test_destructive_migration_rehearsal_restores_from_backup(self):
        dump_cmd = self._pg_dump()
        if dump_cmd is None:
            self.skipTest("pg_dump missing or older than the server")
        self.write("0001_base.sql", "CREATE TABLE career.t115 (id int PRIMARY KEY, note text);\n"
                                    "INSERT INTO career.t115 SELECT g, 'row ' || g FROM generate_series(1, 50) g;\n")
        self.assertEqual(self.apply().returncode, 0)
        dump_dir = tempfile.TemporaryDirectory()          # migration 폴더 밖(러너는 폴더 안 모든 파일을 검사)
        self.addCleanup(dump_dir.cleanup)
        dump = Path(dump_dir.name) / "before.dump"
        subprocess.run([*dump_cmd, "-Fc", "--no-owner", "--no-privileges", "-d", self.db, "-f", str(dump)], check=True)
        approved = H + "-- Destructive-Approval: REHEARSAL-T115\n-- Compatibility: contract — rehearsal only\n"
        self.write("0002_drop.sql", "ALTER TABLE career.t115 DROP COLUMN note;\n", header=approved)
        self.assertEqual(self.apply().returncode, 0)
        self.assertEqual(self.admin("SELECT count(*) FROM information_schema.columns "
                                    "WHERE table_schema='career' AND table_name='t115' AND column_name='note';"), "0")
        restored = f"{self.db}_r"
        self.admin(f'CREATE DATABASE "{restored}";', db="postgres")
        self.addCleanup(self.admin, f'DROP DATABASE IF EXISTS "{restored}" WITH (FORCE);', "postgres")
        restore = [dump_cmd[0].replace("pg_dump", "pg_restore"), *dump_cmd[1:]]
        subprocess.run([*restore, "--no-owner", "--no-privileges", "--exit-on-error", "-d", restored, str(dump)],
                       check=True)
        self.assertEqual(self.admin("SELECT count(*), count(note) FROM career.t115;", db=restored), "50|50")
        self.assertEqual(self.admin("SELECT string_agg(version, ',') FROM career_migration.schema_migrations;",
                                    db=restored), "0001")


if __name__ == "__main__":
    unittest.main()
