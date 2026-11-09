"""Real T15 authentication + SQL repository (isolated SQLite) + directory storage.

No real user documents, network scanners, shared DBs or deployment changes.
"""
import io
import os
import zipfile
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.errors import AppError, ErrorCode
from app.models.documents import UserDocument
from app.repositories.documents import SqlDocumentRepository
from app.routers.documents import get_document_service
from app.services.document_storage import DirectoryDocumentStorage, UnavailableDocumentStorage
from app.services.document_validation import MAX_FILE_BYTES, PDF, DOCX, validate_document
from app.services.documents import DocumentService
from app.services.job_postings import ListCursor
from tests.conftest import signup, bearer

BASE = "/api/v1/documents"
SAMPLE = b"%PDF-1.7\nsynthetic fixture\n%%EOF"


@pytest.fixture
def docs(app, tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS career")
        conn.commit()
    UserDocument.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    service = DocumentService(SqlDocumentRepository(session), DirectoryDocumentStorage(str(tmp_path / "files")),
                              ListCursor(b"d" * 32))
    app.dependency_overrides[get_document_service] = lambda: service
    yield service
    session.close()
    engine.dispose()


def login(client, email="doc@example.com"):
    response = signup(client, email=email)
    return bearer(response.json()["access_token"]), None


def upload(client, headers, content=SAMPLE, filename="이력서.pdf", mime=PDF, kind="resume"):
    return client.post(BASE, headers=headers, data={"kind": kind}, files={"file": (filename, content, mime)})


class Purger:
    def purge(self, document_id): pass


def owner(docs, document_id):
    return docs.repo.session.get(UserDocument, UUID(document_id)).owner_user_id


def test_full_lifecycle(client, docs):
    headers, _ = login(client)
    response = upload(client, headers)
    assert response.status_code == 202, response.text
    item = response.json()
    document_id = item["document_id"]
    path = f"{BASE}/{document_id}"
    assert response.headers["Location"] == path
    assert response.headers["Retry-After"] == "3"
    assert item["status"] == "scanning"
    assert set(item) == {"document_id", "kind", "original_filename", "mime_type", "size_bytes", "status", "created_at"}
    assert client.get(path + "/file", headers=headers).status_code == 409
    assert len(client.get(BASE, headers=headers).json()["items"]) == 1
    files = list(docs.storage.root.iterdir())
    assert len(files) == 1 and len(files[0].name) == 64
    assert files[0].stat().st_mode & 0o777 == 0o600
    user = owner(docs, document_id)
    docs.verify(user, UUID(document_id))
    downloaded = client.get(path + "/file", headers=headers)
    assert downloaded.content == SAMPLE
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert downloaded.headers["cache-control"] == "private, no-store"
    for _ in range(2):
        assert client.delete(path, headers=headers).json()["status"] == "deleting"
    docs.verify(user, UUID(document_id))  # cannot resurrect deletion
    assert client.get(path + "/file", headers=headers).status_code == 409
    docs.purge(user, UUID(document_id), Purger())
    docs.purge(user, UUID(document_id), Purger())
    assert client.get(path, headers=headers).status_code == 404
    assert not list(docs.storage.root.iterdir())


def test_ownership_and_cursors(client, docs):
    a, _ = login(client)
    ids = [upload(client, a).json()["document_id"] for _ in range(3)]
    b, _ = login(client, "other-doc@example.com")
    for suffix in ("", "/file"):
        assert client.get(f"{BASE}/{ids[0]}{suffix}", headers=b).status_code == 404
    assert client.delete(f"{BASE}/{ids[0]}", headers=b).status_code == 404
    assert client.get(BASE, headers=b).json()["items"] == []
    first = client.get(BASE + "?limit=2", headers=a).json()
    second = client.get(BASE, params={"limit": 2, "cursor": first["next_cursor"]}, headers=a).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    assert len({x["document_id"] for x in first["items"] + second["items"]}) == 3
    assert client.get(BASE, params={"cursor": first["next_cursor"]}, headers=b).status_code == 400
    assert client.get(BASE + "?cursor=tampered", headers=a).status_code == 400
    assert client.get(BASE + "?limit=101", headers=a).status_code == 422


@pytest.mark.parametrize("filename,mime,content,kind,status", [
    ("x.exe", PDF, SAMPLE, "resume", 415),
    ("x.pdf", PDF, b"MZ executable", "resume", 415),
    ("x.pdf", "text/plain", SAMPLE, "resume", 415),
    ("../x.pdf", PDF, SAMPLE, "resume", 422),
    ("x.pdf", PDF, b"", "resume", 422),
    ("x.pdf", PDF, SAMPLE, "career_guide", 422),
    ("x.pdf", PDF, b"a" * (MAX_FILE_BYTES + 1), "resume", 413),
    ("x.pdf", PDF, b"a" * (MAX_FILE_BYTES + 65537), "resume", 413),
    ("x.docx", DOCX, b"PKfake", "resume", 415),
])
def test_upload_validation(client, docs, filename, mime, content, kind, status):
    headers, _ = login(client)
    result = upload(client, headers, content, filename, mime, kind)
    assert result.status_code == status, result.text
    assert not list(docs.storage.root.iterdir())
    assert client.get(BASE, headers=headers).json()["items"] == []


def test_auth_before_body_and_dependencies(client, app):
    def forbidden(): raise AssertionError("must authenticate first")
    app.dependency_overrides[get_document_service] = forbidden
    for method, path in [("get", BASE), ("post", BASE), ("get", BASE + "/" + str(uuid4())),
                         ("delete", BASE + "/" + str(uuid4())), ("get", BASE + "/" + str(uuid4()) + "/file")]:
        assert getattr(client, method)(path).status_code == 401


def test_rejected_integrity(client, docs):
    headers, _ = login(client)
    document_id = UUID(upload(client, headers).json()["document_id"])
    user = owner(docs, str(document_id))
    next(docs.storage.root.iterdir()).write_bytes(b"corrupted")
    docs.verify(user, document_id)
    assert docs.get(user, document_id).status == "rejected"
    assert client.get(f"{BASE}/{document_id}/file", headers=headers).status_code == 409


def test_purge_failure_retry(client, docs):
    headers, _ = login(client)
    document_id = UUID(upload(client, headers).json()["document_id"])
    user = owner(docs, str(document_id))
    docs.delete(user, document_id)
    class BrokenPurger:
        def purge(self, _): raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    with pytest.raises(AppError): docs.purge(user, document_id, BrokenPurger())
    assert docs.get(user, document_id).status == "deleting"
    assert list(docs.storage.root.iterdir())
    docs.purge(user, document_id, Purger())


def test_failed_metadata_write_removes_file(client, docs, monkeypatch):
    headers, _ = login(client)
    def fail(_): raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    monkeypatch.setattr(docs.repo, "add", fail)
    assert upload(client, headers).status_code == 503
    assert not list(docs.storage.root.iterdir())


def test_directory_security(tmp_path):
    storage = DirectoryDocumentStorage(str(tmp_path / "private"))
    with pytest.raises(AppError): storage.put("../escape", b"x")
    key = "a" * 64
    storage.put(key, b"original")
    with pytest.raises(AppError): storage.put(key, b"overwrite")
    assert storage.read(key) == b"original"
    storage.delete(key)
    os.symlink(tmp_path / "outside", storage.root / key)
    with pytest.raises(AppError): storage.read(key)
    for method, args in [("put", (key, b"x")), ("read", (key,)), ("delete", (key,))]:
        with pytest.raises(AppError): getattr(UnavailableDocumentStorage(), method)(*args)


def test_docx_structure():
    def build(macro=False):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("[Content_Types].xml", '<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
            if macro: archive.writestr("word/vbaProject.bin", b"macro")
        return output.getvalue()
    validate_document("x.docx", DOCX, build())
    with pytest.raises(AppError): validate_document("x.docx", DOCX, build(True))


def test_worker_verifies_then_purges(client, docs):
    from app.document_worker import run_batch
    headers, _ = login(client)
    document_id = UUID(upload(client, headers).json()["document_id"])
    user = owner(docs, str(document_id))
    assert run_batch(docs.repo.session, docs.storage, Purger()) == 0
    assert docs.get(user, document_id).status == "ready"
    docs.delete(user, document_id)
    assert run_batch(docs.repo.session, docs.storage, Purger()) == 0
    assert not list(docs.storage.root.iterdir())


def test_storage_failure_stays_pending(client, docs, monkeypatch):
    from app.document_worker import run_batch
    headers, _ = login(client)
    document_id = UUID(upload(client, headers).json()["document_id"])
    user = owner(docs, str(document_id))
    def unavailable(*args, **kwargs): raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    monkeypatch.setattr(docs.storage, "read", unavailable)
    assert run_batch(docs.repo.session, docs.storage, Purger()) == 1
    assert docs.get(user, document_id).status == "scanning"


def test_integrity_and_malformed_form(client, docs):
    headers, _ = login(client)
    document_id = UUID(upload(client, headers).json()["document_id"])
    user = owner(docs, str(document_id))
    docs.verify(user, document_id)
    file = next(docs.storage.root.iterdir())
    file.write_bytes(b"corrupted")
    assert client.get(f"{BASE}/{document_id}/file", headers=headers).status_code == 503
    assert client.post(BASE, headers=headers, json={"kind": "resume"}).status_code == 422
    assert client.post(BASE, headers={**headers, "Content-Type": "multipart/form-data"}, content=b"bad").status_code == 422
    assert client.post(BASE, headers=headers, data={"kind": "resume", "user_id": str(user)},
                       files={"file": ("x.pdf", SAMPLE, PDF)}).status_code == 422
    assert client.post(BASE, headers=headers, data={"kind": "resume"},
                       files=[("file", ("x.pdf", SAMPLE, PDF)), ("file", ("y.pdf", SAMPLE, PDF))]).status_code == 422
