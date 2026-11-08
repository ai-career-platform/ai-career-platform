"""T153 parse lineage static and offline tests. Full PostgreSQL E2E in Codex."""
import unittest
from pathlib import Path
from crawler.jobs.fixture_parse_pipeline import PARSER_VERSION
from crawler.jobs.raw_parse_ledger import RawParseLedger


class LedgerContractTests(unittest.TestCase):
    def test_parser_version_is_explicit(self):
        self.assertEqual(PARSER_VERSION,"jobkorea-jsonld-v1")

    def test_invalid_parser_version_rejected_before_db(self):
        ledger=RawParseLedger(None,None)
        for value in ("", "x"*101, None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                ledger.process("unused",parser_version=value)


    def test_runtime_select_uses_advisory_lock_not_row_update(self):
        from unittest.mock import Mock
        from contextlib import nullcontext
        from uuid import UUID

        class Cursor:
            def __init__(self):
                self.sql = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params):
                self.sql.append(query)
            def fetchone(self):
                return None

        cursor = Cursor()
        conn = Mock()
        conn.transaction.return_value = nullcontext()
        conn.cursor.return_value = cursor
        ledger = RawParseLedger(conn,None)
        with self.assertRaisesRegex(ValueError,"Unknown raw artifact"):
            ledger.process("00000000-0000-4000-8000-000000000001")
        self.assertIn("pg_advisory_xact_lock",cursor.sql[0])
        self.assertIn("FROM crawler_training.raw_artifacts",cursor.sql[1])
        self.assertTrue(all("FOR UPDATE" not in sql for sql in cursor.sql))
        self.assertEqual(len(cursor.sql),2)

    def test_invalid_artifact_uuid_rejected_before_db(self):
        ledger = RawParseLedger(None,None)
        with self.assertRaises(ValueError):
            ledger.process("not-a-uuid")

    def test_isolated_migration_and_lineage_fk(self):
        sql=(Path(__file__).resolve().parents[1]/"storage"/"migrations"/"0006_raw_parse_results.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'",sql)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"),1)
        self.assertIn("REFERENCES crawler_training.raw_artifacts(artifact_id)",sql)
        self.assertIn("REFERENCES crawler_training.postings(source_code,external_posting_id)",sql)
        self.assertIn("UNIQUE(artifact_id,parser_version)",sql)
        self.assertNotIn("ALTER TABLE",sql)


if __name__=="__main__":
    unittest.main()
