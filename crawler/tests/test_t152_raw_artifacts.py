"""T152 raw HTML fixture storage tests: no HTTP, DB, or runtime effects."""
import tempfile
import unittest
from pathlib import Path
from crawler.jobs.raw_artifact_store import RawArtifactStore, RawArtifactError, validate_page

DETAIL_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/12345678"
LIST_URL = "https://www.jobkorea.co.kr/Search/?stext=Python"


class RawArtifactsTests(unittest.TestCase):
    def test_list_and_detail_stored_as_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawArtifactStore(Path(tmp))
            a = store.save(kind="list", source_url=LIST_URL, body=b"<a>test</a>")
            b = store.save(kind="detail", source_url=DETAIL_URL, body=b"<script>ok</script>")
            self.assertEqual(store.read_verified(a.storage_key,a.sha256), b"<a>test</a>")
            self.assertEqual(store.read_verified(b.storage_key,b.sha256), b"<script>ok</script>")
            self.assertNotEqual(a.storage_key,b.storage_key)
    def test_idempotent_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawArtifactStore(Path(tmp))
            a = store.save(kind="detail", source_url=DETAIL_URL, body=b"same")
            b = store.save(kind="detail", source_url=DETAIL_URL, body=b"same")
            self.assertEqual(a.storage_key,b.storage_key)
            self.assertNotEqual(a.artifact_id,b.artifact_id)
    def test_reject_unsafe_inputs(self):
        cases = [
            ("wrong", DETAIL_URL, b"test", "text/html"),
            ("detail", "https://evil.example/Recruit/GI_Read/1", b"test", "text/html"),
            ("detail", DETAIL_URL, b"", "text/html"),
            ("list", LIST_URL, b"x" * 2000001, "text/html"),
            ("list", LIST_URL, b"test", "text/plain"),
        ]
        for kind,url,body,ctype in cases:
            with self.subTest(kind=kind,url=url),self.assertRaises((RawArtifactError, ValueError)):
                validate_page(kind,url,body,ctype)
    def test_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawArtifactStore(Path(tmp))
            receipt = store.save(kind="detail", source_url=DETAIL_URL, body=b"original")
            (Path(tmp)/receipt.storage_key).write_bytes(b"tampered")
            with self.assertRaises(RawArtifactError):
                store.read_verified(receipt.storage_key, receipt.sha256)
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RawArtifactStore(Path(tmp))
            with self.assertRaises(RawArtifactError):
                store.read_verified("../secrets", "0"*64)
    def test_migration_is_isolated(self):
        sql = (Path(__file__).resolve().parents[1]/"storage"/"migrations"/"0005_raw_artifacts.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'",sql)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"),1)
        self.assertNotIn("ALTER TABLE",sql)


class _FakeRawConnection:
    """Minimal duplicate/PK checks to regress cross-keyword receipt reuse offline."""
    def __init__(self):
        self.by_id = {}
        self.by_composite = {}
        self.result = None

    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        if "INSERT INTO crawler_training.raw_artifacts" in query:
            artifact_id, keyword_id, _, kind, url, _, _, _, digest, storage_key = params
            composite = (keyword_id,kind,url,digest)
            if artifact_id in self.by_id:
                raise AssertionError("raw_artifacts_pkey UniqueViolation")
            if composite in self.by_composite:
                self.result = None
            else:
                self.by_id[artifact_id] = storage_key
                self.by_composite[composite] = (artifact_id,storage_key)
                self.result = (artifact_id,)
        elif "SELECT artifact_id,storage_key" in query:
            self.result = self.by_composite.get(tuple(params))
        else:
            raise AssertionError("Unexpected SQL")

    def fetchone(self):
        return self.result


class MultiKeywordMetadataTests(unittest.TestCase):
    def test_same_receipt_two_keywords_distinct_ids_repeat_idempotent(self):
        from crawler.jobs.raw_artifact_store import RawArtifactMetadata, RawReceipt
        conn = _FakeRawConnection()
        metadata = RawArtifactMetadata(conn)
        digest = "a" * 64
        receipt = RawReceipt("00000000-0000-4000-8000-000000000001",
                             "detail", DETAIL_URL, digest, 5, "aa/" + digest + ".html")
        first = metadata.insert(receipt=receipt,keyword_id=1)
        second = metadata.insert(receipt=receipt,keyword_id=2)
        repeated = metadata.insert(receipt=receipt,keyword_id=1)
        self.assertNotEqual(first, second)
        self.assertEqual(first, repeated)
        self.assertEqual(len(conn.by_id), 2)
        self.assertEqual(len(conn.by_composite), 2)
        self.assertEqual({key for key in conn.by_id.values()}, {receipt.storage_key})


if __name__ == "__main__":
    unittest.main()
