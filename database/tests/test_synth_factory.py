"""T147: unit tests for database/fixtures/synth_factory.py (no database needed).

Run: python3 -B -m unittest discover -s database/tests -p "test_synth_factory.py" -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "database" / "fixtures"))
import synth_factory as sf  # noqa: E402


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_output(self):
        a = sf.generate(147, 50, 10, 80)
        b = sf.generate(147, 50, 10, 80)
        self.assertEqual(sf.render_sql(a), sf.render_sql(b))
        self.assertEqual(sf.render_features(a), sf.render_features(b))

    def test_different_seed_different_output(self):
        self.assertNotEqual(sf.fingerprint(sf.render_sql(sf.generate(1, 50, 10, 80))),
                            sf.fingerprint(sf.render_sql(sf.generate(2, 50, 10, 80))))

    def test_requested_sizes(self):
        c = sf.counts(sf.generate(7, 120, 15, 200))
        self.assertEqual((c["users"], c["companies"], c["job_postings"]), (120, 15, 200))
        self.assertEqual(c["job_posting_skills"], 200 * 4)
        self.assertEqual(c["user_skills"], 120 * 3)


class IntegrityTest(unittest.TestCase):
    def setUp(self):
        self.ds = sf.generate(147, 100, 20, 150)
        self.t = self.ds.tables

    def test_foreign_keys_resolve(self):
        users = {u["user_id"] for u in self.t["users"]}
        postings = {p["job_posting_id"] for p in self.t["job_postings"]}
        companies = {c["company_id"] for c in self.t["companies"]}
        self.assertTrue(all(r["user_id"] in users for r in self.t["user_skills"]))
        self.assertTrue(all(r["job_posting_id"] in postings for r in self.t["user_job_bookmarks"]))
        self.assertTrue(all(p["company_id"] in companies for p in self.t["job_postings"]))

    def test_bookmarks_only_for_active_users_and_published_postings(self):
        active = {u["user_id"] for u in self.t["users"] if u["status"] == "active"}
        published = {p["job_posting_id"] for p in self.t["job_postings"] if p["status"] == "published"}
        for b in self.t["user_job_bookmarks"]:
            self.assertIn(b["user_id"], active)
            self.assertIn(b["job_posting_id"], published)

    def test_t05_rules(self):
        for u in self.t["users"]:
            self.assertEqual(u["email_canonical"], u["email"].lower())
            self.assertTrue(u["email"].endswith("@example.test"))
        for p in self.t["job_postings"]:
            if p["status"] == "published":
                self.assertIsNotNone(p["published_day"])
        self.assertTrue(all(1 <= r["required_level"] <= 5 for r in self.t["job_role_skills"]))

    def test_codes_do_not_collide_with_t10_reference_codes(self):
        self.assertTrue(all(r["code"].startswith("SYN_ROLE_") for r in self.t["job_roles"]))
        self.assertTrue(all(s["code"].startswith("SYN_SKILL_") for s in self.t["skills"]))


class RejectionTest(unittest.TestCase):
    def test_validator_rejects_orphan(self):
        ds = sf.generate(3, 10, 3, 10)
        ds.tables["user_skills"][0]["user_id"] = "00000000-0000-0000-0000-000000000000"
        with self.assertRaises(sf.FactoryError):
            sf.validate(ds)

    def test_validator_rejects_duplicate_email(self):
        ds = sf.generate(3, 10, 3, 10)
        ds.tables["users"][1]["email_canonical"] = ds.tables["users"][0]["email_canonical"]
        with self.assertRaises(sf.FactoryError):
            sf.validate(ds)

    def test_validator_rejects_sensitive_values(self):
        for bad in ("someone@gmail.com", "010-1234-5678", "900101-1234567", "1234-5678-9012-3456"):
            ds = sf.generate(3, 10, 3, 10)
            ds.tables["user_profiles"][0]["headline"] = f"연락처 {bad}"
            with self.assertRaises(sf.FactoryError, msg=bad):
                sf.validate(ds)

    def test_size_limits(self):
        for args in ((0, 1, 1), (5001, 1, 1), (1, 0, 1), (1, 1, 20001)):
            with self.assertRaises(sf.FactoryError, msg=args):
                sf.generate(1, *args)


class IsolationTest(unittest.TestCase):
    def test_target_env_allow_list(self):
        for env in ("local", "ci", "test"):
            sf.check_environment(env, environ={})
        for env in ("staging", "prod", "production", ""):
            with self.assertRaises(sf.FactoryError, msg=env):
                sf.check_environment(env, environ={})

    def test_career_env_blocks_shared_environments(self):
        for value in ("staging", "PRODUCTION", "stage-2", "live"):
            with self.assertRaises(sf.FactoryError, msg=value):
                sf.check_environment("local", environ={"CAREER_ENV": value})

    def test_sql_has_database_name_guard_first(self):
        sql = sf.render_sql(sf.generate(1, 5, 2, 5))
        guard = sql.index("current_database()")
        self.assertLess(guard, sql.index("BEGIN;"))
        self.assertIn("staging|stage|prod|live", sql)

    def test_cli_refuses_staging(self):
        with tempfile.TemporaryDirectory() as d:
            rc = sf.main(["--target-env", "staging", "--out-sql", str(Path(d) / "x.sql")])
            self.assertEqual(rc, 2)
            self.assertFalse((Path(d) / "x.sql").exists())

    def test_features_have_no_personal_fields(self):
        ds = sf.generate(5, 30, 5, 30)
        for line in sf.render_features(ds).splitlines():
            row = json.loads(line)
            self.assertEqual(set(row), {"entity_id", "target_role", "skills", "dataset_version", "source"})
            self.assertNotIn("@", line)


if __name__ == "__main__":
    unittest.main()
