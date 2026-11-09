"""T152 STEP03 fixture-only raw capture E2E in a temporary filesystem.

Metadata spy intentionally has NO DB access. Real PostgreSQL verification is
a separate local integration step.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crawler.jobs.raw_artifact_store import RawArtifactStore, RawArtifactError
from crawler.jobs.fixture_raw_batch import capture_fixture_batch


LIST = "https://www.jobkorea.co.kr/Search/?stext=Python"
D1 = "https://www.jobkorea.co.kr/Recruit/GI_Read/1001"
D2 = "https://www.jobkorea.co.kr/Recruit/GI_Read/1002"
BODY = b'<a href="/Recruit/GI_Read/1001">one</a><a href="/Recruit/GI_Read/1002">two</a>'
DETAILS = {D1: b"<html>synthetic A</html>", D2: b"<html>synthetic B</html>"}


class MetadataSpy:
    def __init__(self):
        self.rows = {}
        self.calls = []

    def insert(self, *, receipt, keyword_id, job_id=None):
        key = (keyword_id,receipt.kind,receipt.source_url,receipt.sha256)
        self.calls.append((keyword_id,receipt.kind,receipt.source_url))
        if key not in self.rows:
            self.rows[key] = f"artifact-{len(self.rows)+1}"
        return self.rows[key]


class FixtureBatchTests(unittest.TestCase):
    def test_list_detail_order_exact_bytes_idempotency(self):
        with TemporaryDirectory() as root:
            files = RawArtifactStore(Path(root))
            meta = MetadataSpy()
            first = capture_fixture_batch(keyword_id=1,list_url=LIST,list_html=BODY,
                                          detail_pages=DETAILS,files=files,metadata=meta)
            second = capture_fixture_batch(keyword_id=1,list_url=LIST,list_html=BODY,
                                           detail_pages=DETAILS,files=files,metadata=meta)
            self.assertEqual(first,second)
            self.assertEqual(first.detail_urls,(D1,D2))
            self.assertEqual(len(meta.rows),3)
            self.assertEqual(len(list(Path(root).rglob("*.html"))),3)
            for kind,url,raw in [("list",LIST,BODY),("detail",D1,DETAILS[D1]),("detail",D2,DETAILS[D2])]:
                self.assertTrue(any(files.read_verified(p.parent.name+"/"+p.name, p.stem)==raw
                                    for p in Path(root).rglob("*.html") if p.read_bytes()==raw))

    def test_two_keywords_share_file_bytes_but_not_metadata_ids(self):
        with TemporaryDirectory() as root:
            files,meta=RawArtifactStore(Path(root)),MetadataSpy()
            a=capture_fixture_batch(keyword_id=1,list_url=LIST,list_html=BODY,
                                    detail_pages=DETAILS,files=files,metadata=meta)
            b=capture_fixture_batch(keyword_id=2,list_url=LIST,list_html=BODY,
                                    detail_pages=DETAILS,files=files,metadata=meta)
            self.assertNotEqual(a.list_artifact_id,b.list_artifact_id)
            self.assertEqual(len(meta.rows),6)
            self.assertEqual(len(list(Path(root).rglob("*.html"))),3)

    def test_missing_or_extra_detail_preflight_no_writes(self):
        with TemporaryDirectory() as root:
            files,meta=RawArtifactStore(Path(root)),MetadataSpy()
            for pages in ({D1:DETAILS[D1]},dict(DETAILS,**{"other":b"bad"})):
                with self.subTest(pages=pages),self.assertRaises(RawArtifactError):
                    capture_fixture_batch(keyword_id=1,list_url=LIST,list_html=BODY,
                                          detail_pages=pages,files=files,metadata=meta)
            self.assertEqual(meta.rows,{})
            self.assertEqual(list(Path(root).rglob("*.html")),[])

    def test_invalid_fixture_inputs(self):
        with TemporaryDirectory() as root:
            files,meta=RawArtifactStore(Path(root)),MetadataSpy()
            for kwargs in ({"keyword_id":0},{"limit":11},{"list_html":b"invalid"},
                           {"list_html":b"\xff"}):
                params=dict(keyword_id=1,list_url=LIST,list_html=BODY,
                            detail_pages=DETAILS,files=files,metadata=meta)
                params.update(kwargs)
                with self.subTest(kwargs=kwargs),self.assertRaises((RawArtifactError, ValueError)):
                    capture_fixture_batch(**params)
            self.assertEqual(meta.rows,{})


if __name__=="__main__":
    unittest.main()
