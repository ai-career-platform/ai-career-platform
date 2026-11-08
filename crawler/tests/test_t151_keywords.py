"""T151 offline contract tests. Zero DB/HTTP and zero persistent changes."""
import unittest
from pathlib import Path
from crawler.jobs.keyword_management import (
    DEFAULT_KEYWORDS, TRANSITIONS, check_idempotency, check_priority,
    normalize_keyword
)


class KeywordContracts(unittest.TestCase):
    def test_defaults_and_normalization(self):
        self.assertEqual(len(DEFAULT_KEYWORDS), 6)
        self.assertEqual(len({normalize_keyword(k)[1] for k in DEFAULT_KEYWORDS}), 6)
        self.assertEqual(normalize_keyword("  Ｐｙｔｈｏｎ   "), ("Python", "python"))
        self.assertEqual(normalize_keyword("  데이터   분석  "), ("데이터 분석", "데이터 분석"))
        self.assertEqual(normalize_keyword("AI"), ("AI", "ai"))
    def test_invalid_keyword(self):
        for value in ("", "    ", "x" * 101, None, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_keyword(value)
    def test_valid_priority(self):
        self.assertEqual(check_priority(1), 1)
        for value in (0, 10000, True, 1.1, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_priority(value)
    def test_idempotency(self):
        self.assertEqual(check_idempotency("fixture:ai:001"), "fixture:ai:001")
        for value in ("", " a", "a ", "x"*201, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_idempotency(value)
    def test_transitions(self):
        self.assertIn("RUNNING", TRANSITIONS["PENDING"])
        self.assertNotIn("COMPLETED", TRANSITIONS["PENDING"])
        self.assertEqual(TRANSITIONS["COMPLETED"], set())
    def test_migration_is_isolated_and_disabled(self):
        script = (Path(__file__).resolve().parents[1] / "storage" / "migrations" / "0003_keywords_jobs.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'", script)
        self.assertIn("ON CONFLICT (normalized_keyword) DO NOTHING", script)
        self.assertEqual(script.count("CREATE TABLE IF NOT EXISTS"), 3)
        self.assertNotIn("ALTER TABLE crawler_training.schedules", script)
        self.assertNotIn("UPDATE crawler_training.schedules", script)
        self.assertNotIn("enabled=true", script)


if __name__ == "__main__":
    unittest.main()
