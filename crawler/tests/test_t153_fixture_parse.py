"""T153 first fixture parse stage: real T152 file bytes, no DB or network."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from crawler.jobs.raw_artifact_store import RawArtifactStore
from crawler.jobs.fixture_parse_pipeline import parse_stored_detail, process_stored_details
from crawler.storage.memory import MemoryPostingStore

URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/111"

def detail(title):
    return ('<script type="application/ld+json">' + json.dumps({
        "@type":"JobPosting", "title":title,
        "hiringOrganization":{"name":"Synthetic Example"},
        "identifier":{"value":"111"}, "url":URL,
    }) + '</script>').encode("utf-8")


class FixtureParseTests(unittest.TestCase):
    def test_raw_unchanged_then_parse_and_idempotent_upsert(self):
        with TemporaryDirectory() as tmp:
            files=RawArtifactStore(Path(tmp))
            receipt=files.save(kind="detail", source_url=URL, body=detail("Python engineer"))
            rows=[dict(artifact_id=receipt.artifact_id,kind="detail",
                       source_url=URL,storage_key=receipt.storage_key,sha256=receipt.sha256)]
            db=MemoryPostingStore()
            r1=process_stored_details(artifacts=rows,files=files,posting_store=db)
            r2=process_stored_details(artifacts=rows,files=files,posting_store=db)
            self.assertEqual((r1["inserted"],r2["unchanged"]), (1,1))
            self.assertEqual(len(db),1)
            self.assertEqual(db.get("jobkorea_imported","111").title,"Python engineer")
            self.assertEqual(files.read_verified(receipt.storage_key,receipt.sha256),detail("Python engineer"))

    def test_changed_html_updates_existing_identity(self):
        with TemporaryDirectory() as tmp:
            files,db=RawArtifactStore(Path(tmp)),MemoryPostingStore()
            for title in ("Original","Changed"):
                receipt=files.save(kind="detail",source_url=URL,body=detail(title))
                rows=[dict(artifact_id=receipt.artifact_id,kind="detail",
                           source_url=URL,storage_key=receipt.storage_key,sha256=receipt.sha256)]
                report=process_stored_details(artifacts=rows,files=files,posting_store=db)
            self.assertEqual(report["updated"],1)
            self.assertEqual(db.get("jobkorea_imported","111").title,"Changed")

    def test_invalid_page_is_quarantined_in_result(self):
        with TemporaryDirectory() as tmp:
            files,db=RawArtifactStore(Path(tmp)),MemoryPostingStore()
            receipt=files.save(kind="detail",source_url=URL,body=b"<html>no jsonld</html>")
            result=parse_stored_detail(artifact_id=receipt.artifact_id,
                                       source_url=URL,storage_key=receipt.storage_key,
                                       sha256=receipt.sha256,files=files)
            self.assertEqual(result.status,"INVALID")
            self.assertEqual(result.error_code,"INVALID_METADATA")
            self.assertIsNone(result.posting)
            self.assertEqual(len(db),0)

    def test_no_posting_created_from_list_raw(self):
        with TemporaryDirectory() as tmp:
            files=RawArtifactStore(Path(tmp))
            receipt=files.save(kind="list",source_url="https://www.jobkorea.co.kr/Search/?stext=AI",body=b"<html>synthetic list</html>")
            rows=[dict(artifact_id=receipt.artifact_id,kind="list",
                       source_url=receipt.source_url,storage_key=receipt.storage_key,sha256=receipt.sha256)]
            report=process_stored_details(artifacts=rows,files=files,posting_store=MemoryPostingStore())
            self.assertEqual(report["valid"],0)
            self.assertEqual(report["results"],[])


if __name__=="__main__":
    unittest.main()
