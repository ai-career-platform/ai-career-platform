"""T151 STEP04 audit contract tests; strictly offline, no live DB or HTTP."""
import unittest
from pathlib import Path
from crawler.jobs.keyword_management import KeywordStore


class AuditContracts(unittest.TestCase):
    def test_actor_validation(self):
        self.assertEqual(KeywordStore._check_actor("admin:123"), "admin:123")
        for value in ("", " ", " admin", "admin ", "x"*129, 42, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                KeywordStore._check_actor(value)

    def test_migration_is_isolated_and_explicit(self):
        path = Path(__file__).resolve().parents[1] / "storage" / "migrations" / "0004_keyword_audit.sql"
        sql = path.read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS crawler_training.keyword_audit_events", sql)
        self.assertIn("REFERENCES crawler_training.search_keywords(keyword_id)", sql)
        self.assertNotIn("ALTER TABLE crawler_training.", sql)
        self.assertNotIn("UPDATE crawler_training.", sql)

    def test_actions_are_validated_by_db(self):
        path = Path(__file__).resolve().parents[1] / "storage" / "migrations" / "0004_keyword_audit.sql"
        sql = path.read_text(encoding="utf-8")
        for action in ("CREATE", "EDIT", "SET_ENABLED", "SOFT_DELETE"):
            self.assertIn("'"+action+"'", sql)


if __name__ == "__main__":
    unittest.main()
