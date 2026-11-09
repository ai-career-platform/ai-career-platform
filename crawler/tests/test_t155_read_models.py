"""T155 STEP02 non-HTTP read-store contract: select-only and bounded inputs."""
import unittest
from uuid import UUID
from crawler.admin.read_models import CrawlerAdminReadStore


class Cursor:
    def __init__(self,conn):self.conn=conn
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params):
        assert sql.lstrip().startswith("SELECT")
        assert isinstance(params,tuple)
        self.conn.calls.append((sql,params))
    def fetchall(self):return []


class Connection:
    def __init__(self):self.calls=[]
    def cursor(self,**kwargs):return Cursor(self)


class ReadStoreTests(unittest.TestCase):
    def setUp(self):
        self.conn=Connection()
        self.store=CrawlerAdminReadStore(self.conn)

    def test_all_queries_are_select_only_and_do_not_open_network(self):
        self.store.keywords()
        self.store.jobs()
        self.store.schedules()
        self.store.runs()
        self.store.events(run_id="00000000-0000-4000-8000-000000000001")
        self.store.keyword_stats()
        self.assertEqual(len(self.conn.calls),6)
        self.assertTrue(all(sql.lstrip().startswith("SELECT") for sql,_ in self.conn.calls))

    def test_pagination_rejects_bool_and_out_of_range(self):
        for fn in (self.store.keywords,self.store.jobs,self.store.schedules,
                   self.store.runs,self.store.keyword_stats):
            for value in (0,101,True,-1):
                with self.assertRaises(ValueError):
                    fn(limit=value)
            for value in (-1,100001,True):
                with self.assertRaises(ValueError):
                    fn(offset=value)
        self.assertEqual(self.conn.calls,[])

    def test_job_filter_validates_and_binds_parameters(self):
        self.store.jobs(keyword_id=3,status="PENDING",limit=10,offset=20)
        sql,params=self.conn.calls[-1]
        self.assertEqual(params,(3,3,"PENDING","PENDING",10,20))
        self.assertNotIn("PENDING",sql)
        for kw in (True,0,"3",-1):
            with self.assertRaises(ValueError):self.store.jobs(keyword_id=kw)
        for status in ("new","PENDING' OR TRUE",""):
            with self.assertRaises(ValueError):self.store.jobs(status=status)

    def test_events_valid_uuid_and_missing_uuid(self):
        run_id="00000000-0000-4000-8000-000000000001"
        self.store.events(run_id=run_id,limit=2)
        self.assertEqual(self.conn.calls[-1][1],(UUID(run_id),2,0))
        for bad in (None,"not-a-uuid",[],42):
            with self.assertRaises(ValueError):self.store.events(run_id=bad)

    def test_no_raw_payload_approval_or_credentials_selected(self):
        for invoke in (
            self.store.keywords,self.store.jobs,self.store.schedules,
            self.store.runs,self.store.keyword_stats,
        ):
            invoke()
        self.store.events(run_id="00000000-0000-4000-8000-000000000001")
        for sql,_ in self.conn.calls:
            upper=sql.upper()
            for forbidden in ("RAW_ARTIFACTS", "STORAGE_KEY","PASSWORD",
                              "TARGET_URLS","APPROVAL","PAYLOAD","BEARER"):
                self.assertNotIn(forbidden,upper)

    def test_not_mounted_as_api(self):
        from pathlib import Path
        main=(Path(__file__).resolve().parents[2]/"backend"/"app"/"routers"/"api_v1.py").read_text()
        self.assertNotIn("CrawlerAdminReadStore",main)
        self.assertNotIn("admin/crawler",main)


if __name__=="__main__":
    unittest.main()
