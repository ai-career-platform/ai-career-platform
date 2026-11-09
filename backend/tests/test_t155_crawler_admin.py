"""T155: T15 actual auth dependencies protect all crawler admin reads.

Tests use the T15 authenticated TestClient (real signed tokens + session/role
lookup) and override only the crawler DB read dependency with a fake store.
No real staging DB or crawler HTTP requests.
"""
from fastapi.testclient import TestClient

from app.routers.crawler_admin import get_crawler_admin_store
from tests.conftest import bearer, signup

BASE = "/api/v1/admin/crawler"
PATHS = [
    "/keywords", "/jobs", "/schedules", "/runs", "/stats/keywords",
    "/runs/00000000-0000-4000-8000-000000000001/events",
]


class Store:
    def __init__(self):
        self.calls = []

    def keywords(self, **kwargs):
        self.calls.append(("keywords",kwargs))
        return [{"keyword_id":1,"keyword":"AI","enabled":True,"priority":1}]

    def jobs(self, **kwargs):
        self.calls.append(("jobs",kwargs))
        return []

    def schedules(self, **kwargs):
        self.calls.append(("schedules",kwargs))
        return [{"schedule_id":"jobkorea-daily","mode":"fixture","enabled":False}]

    def runs(self, **kwargs):
        self.calls.append(("runs",kwargs))
        return []

    def events(self, **kwargs):
        self.calls.append(("events",kwargs))
        return []

    def keyword_stats(self, **kwargs):
        self.calls.append(("keyword_stats",kwargs))
        return [{"keyword_id":1,"job_count":0,"discovered_posting_count":0}]


def test_anonymous_all_paths_401_before_store_connection(client, app):
    def forbidden_store():
        raise AssertionError("Crawler store must not open before authentication")
    app.dependency_overrides[get_crawler_admin_store] = forbidden_store
    for suffix in PATHS:
        result=client.get(BASE+suffix)
        assert result.status_code == 401, result.text
        assert result.json()["code"] == "UNAUTHENTICATED"


def test_nonadmin_all_paths_403_before_store_connection(client,app):
    token=signup(client,email="user-t155@example.com").json()["access_token"]
    def forbidden_store():
        raise AssertionError("Crawler store must not open for nonadmin")
    app.dependency_overrides[get_crawler_admin_store] = forbidden_store
    for suffix in PATHS:
        result=client.get(BASE+suffix,headers=bearer(token))
        assert result.status_code == 403, result.text
        assert result.json()["code"] == "FORBIDDEN"


def test_admin_only_metadata_reads_and_query_bindings(client,app,repo):
    token=signup(client,email="admin-t155@example.com").json()["access_token"]
    from app.core.security import decode_access_token
    from tests.conftest import TEST_SECRET
    repo.grant_role(decode_access_token(TEST_SECRET,token).user_id,"admin")
    store=Store()
    app.dependency_overrides[get_crawler_admin_store] = lambda: store
    for suffix in PATHS:
        resp=client.get(BASE+suffix,headers=bearer(token))
        assert resp.status_code == 200, (suffix,resp.text)
        assert "storage_key" not in resp.text
        assert "target_urls" not in resp.text
        assert "approval" not in resp.text
    query=client.get(BASE+"/jobs?limit=2&offset=3&keyword_id=4&status=PENDING",headers=bearer(token))
    assert query.status_code==200
    assert store.calls[-1]==("jobs",{"limit":2,"offset":3,"keyword_id":4,"status":"PENDING"})
    assert client.get(BASE+"/keywords?limit=101",headers=bearer(token)).status_code==422
    assert client.get(BASE+"/jobs?status=INJECTED",headers=bearer(token)).status_code==422
    assert client.get(BASE+"/runs/not-a-uuid/events",headers=bearer(token)).status_code==422


def test_admin_role_revocation_immediately_rejects(client,app,repo):
    token=signup(client,email="revoke-t155@example.com").json()["access_token"]
    from app.core.security import decode_access_token
    from tests.conftest import TEST_SECRET
    user=decode_access_token(TEST_SECRET,token).user_id
    repo.grant_role(user,"admin")
    store=Store()
    app.dependency_overrides[get_crawler_admin_store]=lambda:store
    assert client.get(BASE+"/keywords",headers=bearer(token)).status_code==200
    repo.revoke_role(user,"admin")
    assert client.get(BASE+"/keywords",headers=bearer(token)).status_code==403
    assert len(store.calls)==1


def test_openapi_security_scheme(client):
    doc=client.get("/openapi.json").json()
    for suffix in PATHS:
        if "00000000" in suffix:
            path="/api/v1/admin/crawler/runs/{run_id}/events"
        else:
            path=BASE+suffix
        assert path in doc["paths"]
        assert doc["paths"][path]["get"]["security"]
    for verb in ("post","patch","put","delete"):
        assert verb not in doc["paths"][BASE+"/keywords"]
