"""T56 opt-in PostgreSQL E2E. Destroys career schema ONLY in disposable T15_TEST_DATABASE_URL.

Never point T15_TEST_DATABASE_URL to Staging. Synthetic users/documents/chunks only; mock retriever and
extractive mock generator only (no LLM, no external call). Real signup/login token, real get_db Session.
"""

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import bearer
from tests.test_auth_postgres import engine, pg_client, pytestmark, signup_body  # noqa: F401

API = "/api/v1"
QUESTION = "백엔드 신입에게 요구되는 기술은 Python SQL 중 무엇인가요?"


class DictSource:
    def __init__(self):
        self.text: dict[UUID, str] = {}

    def read(self, chunk):
        return self.text.get(chunk.chunk_id)


def user(client, email):
    headers = bearer(client.post(API + "/auth/signup", json=signup_body(email)).json()["access_token"])
    return headers, UUID(client.get(API + "/me", headers=headers).json()["user_id"])


def add_document(engine, source, owner, title, chunks, visibility="private", status="ready"):
    doc, now = uuid4(), datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.execute(text("""INSERT INTO career.user_documents (document_id, owner_user_id, kind, original_filename,
            mime_type, size_bytes, storage_key, checksum_sha256, visibility, status, created_at, updated_at)
            VALUES (:d, :u, :k, :t, 'application/pdf', 100, :s, :c, :v, :st, :n, :n)"""),
            {"d": doc, "u": owner, "k": "career_guide" if visibility == "shared" else "resume", "t": title,
             "s": secrets.token_hex(32), "c": "0" * 64, "v": visibility, "st": status, "n": now})
        for i, body in enumerate(chunks):
            cid = db.execute(text("""INSERT INTO career.document_chunks (document_id, chunk_index, content_hash)
                VALUES (:d, :i, :h) RETURNING chunk_id"""),
                {"d": doc, "i": i, "h": hashlib.sha256(body.encode()).hexdigest()}).scalar_one()
            source.text[cid] = body
    return doc


def ask(client, headers, **body):
    return client.post(API + "/knowledge/answers", headers=headers, json={"question": QUESTION, **body})


def test_t56_postgres_answer_acl_citations_and_hash_only(pg_client, engine):
    source = DictSource()
    pg_client.app.state.knowledge_text_source = source
    a_headers, a = user(pg_client, "t56-a@example.com")
    b_headers, b = user(pg_client, "t56-b@example.com")
    mine = add_document(engine, source, a, "내 이력서.pdf", ["저는 Python과 SQL로 백엔드 API를 개발했습니다."])
    shared = add_document(engine, source, b, "백엔드 가이드.pdf",
                          ["백엔드 신입에게는 Python과 SQL이 가장 자주 요구됩니다."], visibility="shared")
    b_private = add_document(engine, source, b, "B 이력서.pdf", ["백엔드 신입 Python SQL 기술 요구 비밀 메모"])
    add_document(engine, source, a, "검사중.pdf", ["백엔드 신입 Python SQL 기술"], status="scanning")

    r = ask(pg_client, a_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered" and body["answer"]
    cited_docs = {c["document_id"] for c in body["citations"]}
    assert cited_docs and cited_docs <= {str(mine), str(shared)}
    assert "비밀 메모" not in r.text and str(b_private) not in r.text

    with Session(engine) as db:
        run = db.execute(text("""SELECT r.user_id, r.status, r.query_hash, m.kind, m.model_code
            FROM career.retrieval_runs r LEFT JOIN career.model_versions m USING (model_version_id)
            WHERE r.retrieval_run_id = :id"""), {"id": body["retrieval_run_id"]}).one()
        assert (run.user_id, run.status, run.kind, run.model_code) == (a, "answered", "rule", "knowledge_answer_mock")
        assert run.query_hash == hashlib.sha256(QUESTION.encode()).hexdigest()
        rows = db.execute(text("""SELECT c.rank, ch.document_id FROM career.retrieval_citations c
            JOIN career.document_chunks ch USING (chunk_id) WHERE c.retrieval_run_id = :id ORDER BY c.rank"""),
            {"id": body["retrieval_run_id"]}).all()
        assert [r.rank for r in rows] == list(range(1, len(body["citations"]) + 1))
        assert {str(r.document_id) for r in rows} == cited_docs
        # 질문 원문은 어떤 컬럼에도 저장되지 않는다 (해시만)
        assert db.scalar(text("SELECT count(*) FROM career.retrieval_runs WHERE query_hash = :q"), {"q": QUESTION}) == 0

    # 남의 비공개 문서를 지정해도 근거로 쓰지 않는다
    leaked = ask(pg_client, a_headers, document_ids=[str(b_private)]).json()
    assert leaked["status"] == "no_evidence" and "비밀 메모" not in str(leaked)

    # B는 A의 비공개 문서를 근거로 못 쓴다 (공용 문서와 자기 문서만)
    b_body = ask(pg_client, b_headers).json()
    assert str(mine) not in {c["document_id"] for c in b_body["citations"]}

    assert pg_client.post(API + "/knowledge/answers", json={"question": QUESTION}).status_code == 401


def test_t56_postgres_no_evidence_records_run_without_model(pg_client, engine):
    source = DictSource()
    pg_client.app.state.knowledge_text_source = source
    headers, me = user(pg_client, "t56-none@example.com")
    add_document(engine, source, me, "무관.pdf", ["취미는 등산과 독서입니다."])
    body = ask(pg_client, headers).json()
    assert body["status"] == "no_evidence" and body["answer"] is None and body["citations"] == []
    with Session(engine) as db:
        status, model_id, ended = db.execute(text("""SELECT status, model_version_id, ended_at
            FROM career.retrieval_runs WHERE retrieval_run_id = :id"""), {"id": body["retrieval_run_id"]}).one()
        assert (status, model_id) == ("no_evidence", None) and ended is not None
        assert db.scalar(text("SELECT count(*) FROM career.retrieval_citations")) == 0
