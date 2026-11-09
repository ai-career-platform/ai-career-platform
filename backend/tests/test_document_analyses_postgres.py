"""T51 opt-in PostgreSQL E2E. Destroys career schema ONLY in disposable T15_TEST_DATABASE_URL.

Never point T15_TEST_DATABASE_URL to Staging. Synthetic users/files only; Mock provider only.
"""
import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.document_worker import DatabaseDerivativePurger, run_batch
from app.repositories.document_analyses import SqlAnalysisRepository
from app.services.analysis_provider import MockAnalysisProvider
from app.services.document_analyses import AnalysisWorker
from tests.conftest import bearer
from tests.test_auth_postgres import engine, pg_client, pytestmark, signup_body  # noqa: F401

API = "/api/v1"
LLM = {"policy_code": "llm_processing", "policy_version": "2026-11"}
CONTENT = b"%PDF-1.7\n% synthetic only\n%%EOF"


class MemoryStorage:
    """Platform-independent stand-in for the POSIX-only T49 DirectoryDocumentStorage."""
    def __init__(self):
        self.files = {}

    def put(self, key, content):
        self.files[key] = content

    def read(self, key):
        return self.files[key]

    def delete(self, key):
        self.files.pop(key, None)


def setup_user(client, engine, storage, email):
    headers = bearer(client.post(API + "/auth/signup", json=signup_body(email)).json()["access_token"])
    user_id = UUID(client.get(API + "/me", headers=headers).json()["user_id"])
    document_id, key, now = uuid4(), secrets.token_hex(32), datetime.now(UTC)
    storage.put(key, CONTENT)
    with Session(engine) as db, db.begin():  # synthetic T49 row already verified (status=ready)
        db.execute(text("""INSERT INTO career.user_documents (document_id, owner_user_id, kind, original_filename,
            mime_type, size_bytes, storage_key, checksum_sha256, status, created_at, updated_at)
            VALUES (:d, :u, 'resume', 'synthetic.pdf', 'application/pdf', :n, :k, :c, 'ready', :t, :t)"""),
            {"d": document_id, "u": user_id, "n": len(CONTENT), "k": key,
             "c": hashlib.sha256(CONTENT).hexdigest(), "t": now})
    return headers, str(document_id)


def analysis_worker(engine, storage, **kw):
    session = Session(engine)
    return session, AnalysisWorker(SqlAnalysisRepository(session), storage, MockAnalysisProvider(), **kw)


def test_t51_postgres_request_worker_apply_and_isolation(pg_client, engine):
    storage = MemoryStorage()
    headers, document_id = setup_user(pg_client, engine, storage, "t51-owner@example.com")
    other, _ = setup_user(pg_client, engine, storage, "t51-other@example.com")
    url = f"{API}/documents/{document_id}/analyses"

    assert pg_client.post(url, headers=headers, json={"analysis_type": "skill_extraction"}).status_code == 403
    assert pg_client.post(API + "/me/consents", headers=headers, json={**LLM, "granted": True}).status_code in (200, 201)
    assert pg_client.post(url, headers=other, json={"analysis_type": "skill_extraction"}).status_code == 404
    created = pg_client.post(url, headers=headers, json={"analysis_type": "skill_extraction"})
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["status"] == "queued" and body["model_version"] == {
        "model_code": "resume_analysis_mock", "version": "mock-fixture-v1", "kind": "rule"}
    assert pg_client.post(url, headers=headers, json={"analysis_type": "skill_extraction"}).json()["analysis_id"] \
        == body["analysis_id"]
    location = created.headers["Location"]
    assert pg_client.get(location, headers=headers).json()["status"] == "queued"  # GET does not run it
    assert pg_client.get(location, headers=other).status_code == 404

    # Existing skill must survive apply.
    with Session(engine) as db:
        java_id = db.scalar(text("SELECT skill_id FROM career.skills WHERE code='JAVA'"))
    assert pg_client.put(API + "/me/skills", headers=headers,
                         json={"items": [{"skill_id": str(java_id), "proficiency": 4}]}).status_code == 200

    session, worker = analysis_worker(engine, storage)
    with session:
        summary = worker.run()
    assert summary.succeeded == 1
    done = pg_client.get(location, headers=headers).json()
    assert done["status"] == "succeeded" and done["completed_at"] is not None
    codes = [s["skill"]["code"] for s in done["result"]["skills"]]
    assert codes == ["PYTHON", "SQL"]
    for leaked in ("storage_key", "checksum", "synthetic only"):
        assert leaked not in str(done)

    python_id = done["result"]["skills"][0]["skill"]["skill_id"]
    assert pg_client.post(location + "/apply", headers=headers,
                          json={"skills": [{"skill_id": str(java_id), "proficiency": 3}]}).status_code == 422
    applied = pg_client.post(location + "/apply", headers=headers,
                             json={"skills": [{"skill_id": python_id, "proficiency": 2}]})
    assert applied.status_code == 200, applied.text
    assert {(s["skill"]["code"], s["proficiency"]) for s in applied.json()} == {("JAVA", 4), ("PYTHON", 2)}
    with Session(engine) as db:
        assert db.scalar(text("SELECT count(*) FROM career.ai_usage_records")) == 0  # no fabricated usage
        assert db.scalar(text("SELECT approved_at FROM career.model_versions "
                              "WHERE model_code='resume_analysis_mock'")) is None

    # Consent revoked: new requests blocked, queued jobs fail without result.
    queued = pg_client.post(url, headers=headers, json={"analysis_type": "summary"}).json()
    assert pg_client.post(API + "/me/consents", headers=headers, json={**LLM, "granted": False}).status_code in (200, 201)
    assert pg_client.post(url, headers=headers, json={"analysis_type": "skill_extraction"}).status_code == 403
    session, worker = analysis_worker(engine, storage)
    with session:
        worker.run()
    revoked = pg_client.get(f"{API}/document-analyses/{queued['analysis_id']}", headers=headers).json()
    assert revoked["status"] == "failed" and revoked["result"] is None

    # Document deletion hides analyses, T49 purge cascades them away.
    assert pg_client.delete(f"{API}/documents/{document_id}", headers=headers).status_code == 202
    assert pg_client.get(location, headers=headers).status_code == 404
    assert pg_client.post(url, headers=headers, json={"analysis_type": "summary"}).status_code in (404, 409)
    with Session(engine) as db:
        run_batch(db, storage, DatabaseDerivativePurger(db))
        assert db.scalar(text("SELECT count(*) FROM career.document_analyses WHERE document_id=:d"),
                         {"d": UUID(document_id)}) == 0


def test_t51_postgres_concurrent_claims_skip_locked(pg_client, engine):
    storage = MemoryStorage()
    headers, document_id = setup_user(pg_client, engine, storage, "t51-claim@example.com")
    assert pg_client.post(API + "/me/consents", headers=headers, json={**LLM, "granted": True}).status_code in (200, 201)
    ids = {pg_client.post(f"{API}/documents/{document_id}/analyses", headers=headers,
                          json={"analysis_type": t}).json()["analysis_id"] for t in ("skill_extraction", "summary")}
    first, second = Session(engine), Session(engine)
    try:
        a = SqlAnalysisRepository(first).claim_next()   # row lock held (transaction open)
        b = SqlAnalysisRepository(second).claim_next()  # must skip the locked row
        assert a is not None and b is not None and a.analysis_id != b.analysis_id
        assert {str(a.analysis_id), str(b.analysis_id)} == ids
        first.commit()
        second.commit()
        third = Session(engine)
        with third:
            assert SqlAnalysisRepository(third).claim_next() is None
        with Session(engine) as db:
            assert db.scalar(text("SELECT count(*) FROM career.document_analyses WHERE status='running'")) == 2
    finally:
        first.close()
        second.close()
