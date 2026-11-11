"""T152 read-only reconcile/retention against isolated PostgreSQL (0002..0010 applied).

Runs only under explicit CRAWLER_NIGHT_PG_TEST=1 as crawler_staging, like local_t155_admin_read_pg.
Inserts one synthetic fixture metadata row (crawler_staging has INSERT on raw_artifacts by design of 0005),
then proves load_rows() runs in a READ ONLY transaction and changes no table counts.
No HTTP, no staging access, nothing deleted.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from crawler.jobs.raw_artifact_audit import load_rows, reconcile, retention_plan
from crawler.jobs.raw_artifact_store import RawArtifactMetadata, RawArtifactStore

DETAIL_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/15200001"


@unittest.skipUnless(os.environ.get("CRAWLER_NIGHT_PG_TEST") == "1",
                     "Only in opt-in disposable PostgreSQL CI")
class T152AuditPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.connection = psycopg.connect(os.environ["CRAWLER_NIGHT_TEST_DSN"])
        self.connection.autocommit = True
        self.assertEqual(self.connection.execute("SELECT current_user").fetchone()[0], "crawler_staging")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.connection.close()

    def _counts(self):
        return tuple(self.connection.execute(f"SELECT count(*) FROM crawler_training.{t}").fetchone()[0]
                     for t in ("raw_artifacts", "raw_parse_results", "search_keywords", "keyword_jobs"))

    def test_reconcile_and_plan_on_real_metadata_are_read_only(self):
        store = RawArtifactStore(Path(self.tmp.name))
        kept = store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>T152 audit synthetic kept</p>")
        orphan = store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>T152 audit synthetic orphan</p>")
        keyword_id = self.connection.execute(
            "SELECT keyword_id FROM crawler_training.search_keywords ORDER BY keyword_id LIMIT 1").fetchone()[0]
        artifact_id = RawArtifactMetadata(self.connection).insert(receipt=kept, keyword_id=keyword_id)
        before = self._counts()
        rows, lineage = load_rows(self.connection)
        self.assertEqual(self._counts(), before)                               # read only
        self.assertIn(str(artifact_id), {r.artifact_id for r in rows})
        report = reconcile(Path(self.tmp.name), rows)
        self.assertIn(orphan.storage_key, report.orphan_files)
        self.assertNotIn(kept.storage_key, report.missing_files)
        self.assertNotIn(kept.storage_key, report.hash_mismatch + report.size_mismatch)
        # rows written by other tests point at other roots → reported missing here, never "fixed"
        self.assertEqual(set(report.missing_files), {r.storage_key for r in rows} - {kept.storage_key}
                         - set(report.orphan_files))
        plan = retention_plan(rows, lineage, now=datetime.now(timezone.utc), keep_days=30)
        self.assertNotIn(kept.storage_key, plan.eligible_files)                 # captured just now
        self.assertTrue((Path(self.tmp.name) / orphan.storage_key).exists())    # nothing deleted

    def test_read_only_transaction_rejects_writes(self):
        import psycopg
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with self.connection.transaction():
                self.connection.execute("SET TRANSACTION READ ONLY")
                self.connection.execute("UPDATE crawler_training.raw_artifacts SET http_status = 200 WHERE false")


if __name__ == "__main__":
    unittest.main()
