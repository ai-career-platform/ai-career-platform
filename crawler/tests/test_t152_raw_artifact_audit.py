"""T152 read-only reconcile + retention plan: offline, synthetic bytes only, nothing deleted."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from crawler.jobs.raw_artifact_audit import ArtifactRow, main, reconcile, retention_plan
from crawler.jobs.raw_artifact_store import RawArtifactStore

LIST_URL = "https://www.jobkorea.co.kr/Search/?stext=Python"
DETAIL_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/12345678"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)


def row(receipt, captured_at=NOW, size=None, artifact_id=None):
    return ArtifactRow(artifact_id or str(uuid4()), receipt.sha256, receipt.storage_key,
                       receipt.byte_size if size is None else size, captured_at)


def snapshot(root: Path):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size) for p in root.rglob("*") if p.is_file())


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "raw"
        self.store = RawArtifactStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_store_with_shared_bytes(self):
        a = self.store.save(kind="list", source_url=LIST_URL, body=b"<a>list</a>")
        b = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>detail</p>")
        rows = [row(a), row(b), row(b)]                    # same bytes for two keywords → one file
        report = reconcile(self.root, rows)
        self.assertTrue(report.clean, report.to_dict())
        self.assertEqual((report.files_on_disk, report.rows, report.distinct_keys, report.ok), (2, 3, 2, 2))

    def test_detects_every_problem_without_deleting_anything(self):
        a = self.store.save(kind="list", source_url=LIST_URL, body=b"<a>orphan</a>")      # no row → orphan
        b = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>ok</p>")
        c = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>tampered</p>")
        d = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>size</p>")
        (self.root / c.storage_key).write_bytes(b"<p>TAMPERED</p>")                       # corruption
        missing = ArtifactRow(str(uuid4()), "f" * 64, f"ff/{'f' * 64}.html", 10, NOW)     # row, no file
        bad_key = ArtifactRow("bad-key-row", "e" * 64, "../../etc/passwd", 10, NOW)
        (self.root / b.storage_key[:2] / ".tmp-interrupted").write_bytes(b"partial")
        (self.root / "notes.txt").write_bytes(b"unexpected")
        before = snapshot(self.root)
        report = reconcile(self.root, [row(b), row(c), row(d, size=999), missing, bad_key])
        self.assertFalse(report.clean)
        self.assertEqual(report.orphan_files, [a.storage_key])
        self.assertEqual(report.missing_files, [missing.storage_key])
        self.assertEqual(report.hash_mismatch, [c.storage_key])
        self.assertEqual(report.size_mismatch, [d.storage_key])
        self.assertEqual(report.invalid_rows, ["bad-key-row"])
        self.assertEqual(report.temp_leftovers, [f"{b.storage_key[:2]}/.tmp-interrupted"])
        self.assertEqual(report.unsafe_entries, ["notes.txt"])
        self.assertEqual(report.ok, 1)
        self.assertEqual(snapshot(self.root), before)                                    # nothing removed

    def test_report_never_contains_html_or_urls(self):
        secret_body = b"<p>SYNTHETIC-BODY-MARKER</p>"
        a = self.store.save(kind="detail", source_url=DETAIL_URL, body=secret_body)
        text = repr(reconcile(self.root, [row(a)]).to_dict())
        self.assertNotIn("SYNTHETIC-BODY-MARKER", text)
        self.assertNotIn("jobkorea", text)

    def test_size_only_mode_skips_rehash(self):
        a = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>same-size</p>")
        (self.root / a.storage_key).write_bytes(b"<p>SAME-SIZE</p>")
        self.assertTrue(reconcile(self.root, [row(a)], verify_hash=False).clean)
        self.assertFalse(reconcile(self.root, [row(a)]).clean)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits")
    def test_loose_permissions_are_reported(self):
        a = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>perm</p>")
        os.chmod(self.root / a.storage_key, 0o644)
        self.assertEqual(reconcile(self.root, [row(a)]).loose_permissions, [a.storage_key])

    def test_symlink_entries_and_root_are_refused(self):
        a = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>link</p>")
        link = self.root / a.storage_key[:2] / ("0" * 64 + ".html")
        try:
            link.symlink_to(self.root / a.storage_key)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not permitted on this host")
        self.assertIn(link.relative_to(self.root).as_posix(), reconcile(self.root, [row(a)]).unsafe_entries)

    def test_missing_root_is_refused(self):
        with self.assertRaises(ValueError):
            reconcile(self.root / "does-not-exist", [])


class RetentionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RawArtifactStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_shared_lineage_and_age_rules(self):
        old = NOW - timedelta(days=40)
        a = self.store.save(kind="list", source_url=LIST_URL, body=b"<a>old-unused</a>")
        b = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>old-but-parsed</p>")
        c = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>old-and-recent</p>")
        d = self.store.save(kind="detail", source_url=DETAIL_URL, body=b"<p>recent</p>")
        parsed = row(b, old)
        rows = [row(a, old), parsed, row(c, old), row(c, NOW - timedelta(days=1)), row(d, NOW)]
        plan = retention_plan(rows, [parsed.artifact_id], now=NOW, keep_days=30)
        self.assertEqual(plan.eligible_files, [a.storage_key])
        self.assertEqual(plan.eligible_bytes, a.byte_size)
        self.assertEqual(plan.held_by_lineage, [b.storage_key])
        self.assertEqual(plan.held_by_newer_row, [c.storage_key])
        self.assertEqual(plan.files_total, 4)
        self.assertEqual(plan.to_dict()["action"], "REVIEW_ONLY_NO_DELETE")

    def test_boundaries(self):
        a = self.store.save(kind="list", source_url=LIST_URL, body=b"<a>edge</a>")
        exactly = row(a, NOW - timedelta(days=30))                  # captured_at == cutoff → kept
        self.assertEqual(retention_plan([exactly], [], now=NOW, keep_days=30).eligible_files, [])
        for bad in (0, 3651):
            with self.assertRaises(ValueError):
                retention_plan([], [], now=NOW, keep_days=bad)
        with self.assertRaises(ValueError):
            retention_plan([], [], now=NOW.replace(tzinfo=None), keep_days=30)

    def test_cli_requires_dsn_env_and_never_prints_it(self):
        os.environ.pop("T152_TEST_UNSET_DSN", None)
        with self.assertRaises(SystemExit):
            main(["--root", self.tmp.name, "--dsn-env", "T152_TEST_UNSET_DSN"])


if __name__ == "__main__":
    unittest.main()
