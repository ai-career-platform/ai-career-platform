"""Test synthetic posting storage contract and cross-run idempotency."""
import json
import tempfile
import unittest
from pathlib import Path

from crawler.jobs.run_crawler import DEFAULT_FIXTURE, run
from crawler.normalizer import normalize
from crawler.storage.memory import MemoryPostingStore


class TestMemoryPostingStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))[0]

    def test_new_posting_inserted(self):
        store = MemoryPostingStore()
        self.assertEqual(store.upsert(normalize(self.raw)), "inserted")
        self.assertEqual(len(store), 1)

    def test_same_posting_unchanged(self):
        store = MemoryPostingStore()
        item = normalize(self.raw)
        store.upsert(item)
        self.assertEqual(store.upsert(item), "unchanged")
        self.assertEqual(len(store), 1)

    def test_changed_posting_updated(self):
        store = MemoryPostingStore()
        store.upsert(normalize(self.raw))
        changed = normalize({**self.raw, "title": "가상 공고 수정"})
        self.assertEqual(store.upsert(changed), "updated")
        self.assertEqual(store.get("jobkorea", changed.external_posting_id).title, "가상 공고 수정")
        self.assertEqual(len(store), 1)

    def test_key_scoped_by_source(self):
        from dataclasses import replace
        store = MemoryPostingStore()
        item = normalize(self.raw)
        store.upsert(item)
        store.upsert(replace(item, source_code="another_source"))
        self.assertEqual(len(store), 2)

    def test_cross_run_idempotency(self):
        store = MemoryPostingStore()
        first = run(source_id="jobkorea", run_id="run-1", fixture=DEFAULT_FIXTURE, store=store)
        second = run(source_id="jobkorea", run_id="run-2", fixture=DEFAULT_FIXTURE, store=store)
        self.assertEqual((first["inserted"], first["updated"], first["unchanged"]), (2, 0, 0))
        self.assertEqual((second["inserted"], second["updated"], second["unchanged"]), (0, 0, 2))
        self.assertEqual(len(store), 2)
        self.assertEqual((first["db_writes"], second["db_writes"]), (0, 0))

    def test_changed_fixture_updates_in_second_run(self):
        store = MemoryPostingStore()
        run(source_id="jobkorea", run_id="run-1", fixture=DEFAULT_FIXTURE, store=store)
        rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        rows[0]["title"] = "변경된 가상 공고"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "changed.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            result = run(source_id="jobkorea", run_id="run-2", fixture=path, store=store)
        self.assertEqual((result["inserted"], result["updated"], result["unchanged"]), (0, 1, 1))

    def test_duplicate_row_in_single_batch_not_overwritten(self):
        store = MemoryPostingStore()
        rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        rows.append({**rows[0], "title": "중복 행의 다른 제목"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "duplicate.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            result = run(source_id="jobkorea", run_id="run-1", fixture=path, store=store)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(store.get("jobkorea", rows[0]["external_posting_id"]).title, rows[0]["title"])


if __name__ == "__main__":
    unittest.main()
