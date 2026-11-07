"""Offline safety and SQL contract tests; no local PostgreSQL needed."""
import unittest

from crawler.storage.postgres import UnsafeDatabaseTarget, validate_local_dsn
from crawler.normalizer import normalize
from crawler.storage.postgres import PostgresPostingStore
from crawler.jobs.run_crawler import DEFAULT_FIXTURE
import json


class TestLocalDSN(unittest.TestCase):
    def test_accepts_only_dedicated_local_db(self):
        validate_local_dsn("postgresql://crawler_student:secret@127.0.0.1:5432/ai_career_crawler_training")

    def test_denies_remote(self):
        with self.assertRaises(UnsafeDatabaseTarget):
            validate_local_dsn("postgresql://crawler_student:secret@db.example.com/ai_career_crawler_training")

    def test_denies_existing_app_db(self):
        with self.assertRaises(UnsafeDatabaseTarget):
            validate_local_dsn("postgresql://crawler_student:secret@localhost/ai_career_poc")

    def test_denies_postgres_superuser(self):
        with self.assertRaises(UnsafeDatabaseTarget):
            validate_local_dsn("postgresql://postgres:secret@localhost/ai_career_crawler_training")

    def test_denies_missing_credentials(self):
        with self.assertRaises(UnsafeDatabaseTarget):
            validate_local_dsn("postgresql://localhost/ai_career_crawler_training")

    def test_denies_non_postgres(self):
        with self.assertRaises(UnsafeDatabaseTarget):
            validate_local_dsn("sqlite:///ai_career_crawler_training")


class _FakeCursor:
    def __init__(self, existing=None):
        self.existing = existing
        self.commands = []
        self.fetch_counter = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.commands.append((sql, params))

    def fetchone(self):
        self.fetch_counter += 1
        if self.fetch_counter == 1:
            return ("new-id",) if self.existing == "new" else None
        return (self.existing,) if self.existing not in {"new", None} else None


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConn:
    def __init__(self, existing):
        self.cur = _FakeCursor(existing)

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return self.cur


class TestStoreSQLContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))[0]
        cls.posting = normalize(raw)

    def test_insert_path(self):
        conn = _FakeConn("new")
        self.assertEqual(PostgresPostingStore(conn).upsert(self.posting), "inserted")
        self.assertEqual(len(conn.cur.commands), 1)

    def test_unchanged_path(self):
        conn = _FakeConn(self.posting.to_dict())
        self.assertEqual(PostgresPostingStore(conn).upsert(self.posting), "unchanged")
        self.assertEqual(len(conn.cur.commands), 2)

    def test_update_path(self):
        conn = _FakeConn({"title": "old"})
        self.assertEqual(PostgresPostingStore(conn).upsert(self.posting), "updated")
        self.assertEqual(len(conn.cur.commands), 3)


if __name__ == "__main__":
    unittest.main()
