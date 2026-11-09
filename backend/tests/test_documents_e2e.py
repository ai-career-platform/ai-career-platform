"""Actual HTTP + PostgreSQL + directory E2E, no dependency overrides.

Requires a disposable local database named t49_e2e*, explicit reset opt-in,
and an explicitly configured private upload directory. Never point this at shared infrastructure.
"""
from concurrent.futures import ThreadPoolExecutor
import io
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import UUID, uuid4
import zipfile

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.services.document_validation import DOCX, PDF, MAX_FILE_BYTES

DB_URL = os.environ.get("T49_E2E_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="T49_E2E_DATABASE_URL not set")
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
BASE = "/api/v1/documents"


def pdf(extra=b""):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
    result, offsets = b"%PDF-1.7\n", [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 4\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return result + b"trailer\n<< /Size 4 /Root 1 0 R >>\n" + extra + f"\nstartxref\n{start}\n%%EOF".encode()


def docx(extras=(), document=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", document or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic resume</w:t></w:r></w:p></w:body></w:document>')
        for name, data in extras:
            archive.writestr(name, data)
    return output.getvalue()



@pytest.fixture(scope="module")
def live(tmp_path_factory):
    url = make_url(DB_URL)
    if (os.environ.get("T49_E2E_ALLOW_RESET") != "YES" or url.host not in {"127.0.0.1", "localhost"}
            or not (url.database or "").startswith("t49_e2e")):
        pytest.fail("Requires explicit reset opt-in and disposable local t49_e2e database")
    engine = create_engine(url.set(drivername="postgresql+psycopg"), hide_parameters=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA career")
        for source in [ROOT / "database/migrations/0001_initial_schema.sql", ROOT / "database/seeds/0001_initial_seed.sql"]:
            connection.exec_driver_sql(source.read_text().replace("%", "%%"))
        connection.exec_driver_sql("INSERT INTO career.consent_policies (policy_code, version, is_required, content_url, effective_at) VALUES ('terms', '2026-11', true, 'https://example.invalid/terms', '2026-11-06'), ('privacy', '2026-11', true, 'https://example.invalid/privacy', '2026-11-06')")
        # Exercise the API with CRUD privileges, without schema/table ownership.
        connection.exec_driver_sql("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='t49_e2e_app') THEN CREATE ROLE t49_e2e_app LOGIN PASSWORD 'synthetic-e2e-app-only'; END IF; END $$")
        connection.exec_driver_sql("GRANT USAGE ON SCHEMA career TO t49_e2e_app")
        connection.exec_driver_sql("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA career TO t49_e2e_app")
    temp = tmp_path_factory.mktemp("t49-http-e2e")
    files = temp / "documents"
    files.mkdir(mode=0o700)
    env = {**os.environ, "APP_ENV": "test", "DATABASE_URL": url.set(username="t49_e2e_app", password="synthetic-e2e-app-only").render_as_string(hide_password=False),
           "DOCUMENT_STORAGE_ROOT": str(files), "JWT_SECRET": secrets.token_hex(32), "AUTH_COOKIE_SECURE": "false",
           "SIGNUP_IP_MAX_ATTEMPTS": "100"}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (temp / "api.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                    "--port", str(port), "--no-access-log"], cwd=BACKEND, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if client.get("/health/db").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail("Real API did not start; inspect isolated api.log")
                    time.sleep(0.1)
                yield client, engine, files, env, temp
        finally:
            process.terminate()
            process.wait(timeout=10)
            engine.dispose()


def signup(client):
    response = client.post("/api/v1/auth/signup", headers={"X-CSRF-TOKEN": "1"}, json={"email": f"e2e-{uuid4().hex}@example.com",
        "password": "synthetic-e2e-password-1", "display_name": "E2E synthetic",
        "consents": [{"policy_code": code, "policy_version": "2026-11", "granted": True} for code in ("terms", "privacy")]})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def upload(client, headers, data=None, name="resume.pdf", mime=PDF):
    return client.post(BASE, headers=headers, data={"kind": "resume"}, files={"file": (name, data if data is not None else pdf(), mime)})


def worker(env, expected=0):
    result = subprocess.run([sys.executable, "-m", "app.document_worker"], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == expected, "Worker exit status mismatch: " + result.stderr


def test_live_pdf_docx_lifecycle_and_cascade(live):
    client, engine, files, env, _ = live
    headers = signup(client)
    ids = []
    originals = [pdf(), docx()]
    for name, mime, content in [("이력서.PDF", PDF, originals[0]), ("resume.docx", DOCX, originals[1])]:
        response = upload(client, headers, content, name, mime)
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "scanning"
        path = response.headers["Location"]
        ids.append(UUID(response.json()["document_id"]))
        assert client.get(path + "/file", headers=headers).status_code == 409
    worker(env)
    for document_id, original in zip(ids, originals):
        response = client.get(f"{BASE}/{document_id}/file", headers=headers)
        assert response.status_code == 200 and response.content == original
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "private, no-store"
        assert client.get(f"{BASE}/{document_id}", headers=headers).json()["status"] == "ready"
    with engine.begin() as connection:
        owner = connection.scalar(text("SELECT owner_user_id FROM career.user_documents WHERE document_id=:id"), {"id": ids[0]})
        chunk = connection.scalar(text("INSERT INTO career.document_chunks (document_id, chunk_index, content_hash) VALUES (:id, 0, :hash) RETURNING chunk_id"), {"id": ids[0], "hash": "a" * 64})
        model = connection.scalar(text("INSERT INTO career.model_versions (model_code, version, kind) VALUES ('t49-e2e', '1', 'llm') RETURNING model_version_id"))
        analysis = connection.scalar(text("INSERT INTO career.document_analyses (document_id, model_version_id, analysis_type) VALUES (:id, :model, 'summary') RETURNING analysis_id"), {"id": ids[0], "model": model})
        retrieval = connection.scalar(text("INSERT INTO career.retrieval_runs (user_id, query_hash) VALUES (:owner, :hash) RETURNING retrieval_run_id"), {"owner": owner, "hash": "b" * 64})
        connection.execute(text("INSERT INTO career.retrieval_citations (retrieval_run_id, chunk_id, rank) VALUES (:run, :chunk, 1)"), {"run": retrieval, "chunk": chunk})
    for document_id in ids:
        assert client.delete(f"{BASE}/{document_id}", headers=headers).status_code == 202
        assert client.get(f"{BASE}/{document_id}/file", headers=headers).status_code == 409
    worker(env)
    for document_id in ids:
        assert client.get(f"{BASE}/{document_id}", headers=headers).status_code == 404
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM career.document_analyses WHERE analysis_id=:id"), {"id": analysis}) == 0
        assert connection.scalar(text("SELECT count(*) FROM career.document_chunks WHERE chunk_id=:id"), {"id": chunk}) == 0
        assert connection.scalar(text("SELECT count(*) FROM career.retrieval_citations WHERE chunk_id=:id"), {"id": chunk}) == 0
    assert list(files.iterdir()) == []


@pytest.mark.parametrize("name,mime,content,status", [
    ("shell.php", "application/x-php", b"<?php system($_GET['cmd']); ?>", 415),
    ("shell.php.pdf", PDF, b"<?php system($_GET['cmd']); ?>", 415),
    ("shell.sh", PDF, b"#!/bin/sh\nprintf T49_EXECUTED", 415),
    ("resume.pdf.exe", PDF, pdf(), 415),
    ("resume.pdf", PDF, b"MZ executable", 415),
    ("resume.pdf", PDF, b"<svg onload='alert(1)'/>", 415),
    ("resume.pdf", "text/html", pdf(), 415),
    ("../../escaped.pdf", PDF, pdf(), 422),
    ("..\\escaped.pdf", PDF, pdf(), 422),
    (".pdf", PDF, b"", 422),
    ("resume.pdf", PDF, b"A" * (MAX_FILE_BYTES + 1), 413),
    ("resume.docx", DOCX, b"PKbadzip", 415),
    ("resume.docx", DOCX, docx([("../escaped", b"x")]), 415),
    ("resume.docx", DOCX, docx([("word/vbaProject.bin", b"macro")]), 415),
    ("resume.docx", DOCX, docx([("word/bomb.xml", b"x" * (MAX_FILE_BYTES + 1))]), 415),
    ("resume.docx", DOCX, docx(document='<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">&xxe;</w:document>'), 415),
], ids=["php-webshell", "php-disguised-as-pdf", "shell-script", "executable-double-extension",
        "pe-disguised-as-pdf", "svg-disguised-as-pdf", "mismatched-mime", "posix-traversal",
        "windows-traversal", "empty-file", "file-too-large", "corrupt-docx", "zip-slip",
        "macro", "zip-bomb", "xxe"])
def test_live_upload_attacks_rejected(live, name, mime, content, status):
    client, _, files, _, _ = live
    headers = signup(client)
    before = set(files.iterdir())
    response = upload(client, headers, content, name, mime)
    assert response.status_code == status, response.text
    assert set(response.json()) == {"code", "status", "message"}
    assert set(files.iterdir()) == before


def test_live_ownership_auth(live):
    client, _, files, env, _ = live
    a, b = signup(client), signup(client)
    response = upload(client, a)
    assert response.status_code == 202
    path = response.headers["Location"]
    for method, suffix in [("get", ""), ("get", "/file"), ("delete", "")]:
        assert getattr(client, method)(path + suffix, headers=b).status_code == 404
        assert getattr(client, method)(path + suffix).status_code == 401
    assert client.post(BASE, files={"file": ("shell.php", b"<?php ?>")}).status_code == 401
    worker(env)
    assert client.get(path, headers=a).json()["status"] == "ready"
    assert client.get(path + "/file", headers=b).status_code == 404
    assert client.delete(path, headers=a).status_code == 202
    worker(env)
    assert not list(files.iterdir())


def test_live_shell_execution_attempts(live):
    client, _, files, env, temp = live
    headers = signup(client)
    marker = temp / "UPLOAD_SHELL_EXECUTED"
    # Shell command + loopback-only callback are bounded execution sentinels.
    # No interactive shell, persistence, external target or real malware.
    callback = socket.socket()
    callback.bind(("127.0.0.1", 0))
    callback.listen(1)
    callback.settimeout(0.2)
    callback_port = callback.getsockname()[1]
    php = f"<?php system('touch {marker}'); $s=fsockopen('127.0.0.1',{callback_port}); ?>".encode()
    assert upload(client, headers, php, "shell.php", "application/x-php").status_code == 415
    assert upload(client, headers, b"#!/bin/sh\ntouch " + str(marker).encode(), "shell.sh", PDF).status_code == 415
    names = ["$(touch T49_FILENAME_EXECUTED).pdf", "x;touch T49_FILENAME_EXECUTED;.pdf", "shell.php.pdf"]
    paths = []
    for name in names:
        response = upload(client, headers, pdf(php), name, PDF)
        assert response.status_code == 202, response.text
        paths.append(response.headers["Location"])
    worker(env)
    for path in paths:
        response = client.get(path + "/file?cmd=printf%20T49_UPLOAD_EXECUTED", headers=headers)
        assert response.status_code == 200
        assert response.content == pdf(php)  # inert attachment bytes, no evaluation
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("attachment;")
    for file in files.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
        for path in (f"/uploads/{file.name}", f"/static/{file.name}", f"/documents/{file.name}"):
            assert client.get(path + "?cmd=printf%20T49_UPLOAD_EXECUTED").status_code == 404
    assert not marker.exists()
    assert not (BACKEND / "T49_FILENAME_EXECUTED").exists()
    assert not (files / "T49_FILENAME_EXECUTED").exists()
    try:
        with pytest.raises(socket.timeout):
            callback.accept()
    finally:
        callback.close()
    for path in paths:
        client.delete(path, headers=headers)
    worker(env)


def test_live_duplicate_fields_and_chunked_limit(live):
    client, _, files, _, _ = live
    headers = signup(client)
    before = set(files.iterdir())
    duplicate = client.post(BASE, headers=headers, data={"kind": "resume"}, files=[
        ("file", ("a.pdf", pdf(), PDF)), ("file", ("b.pdf", pdf(), PDF))])
    assert duplicate.status_code == 422
    raw_headers = {**headers, "Content-Type": "multipart/form-data; boundary=t49"}
    body = (b'--t49\r\nContent-Disposition: form-data; name="kind"\r\n\r\nresume\r\n'
            b'--t49\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n')
    def chunks():
        yield body
        for _ in range(162):
            yield b"A" * 65536
        yield b"\r\n--t49--\r\n"
    assert client.post(BASE, headers=raw_headers, content=chunks()).status_code == 413
    assert set(files.iterdir()) == before
    assert client.get("/health/db").status_code == 200


def test_live_symlink_read_and_overwrite_protection(live):
    client, engine, files, env, temp = live
    headers = signup(client)
    paths = [upload(client, headers).headers["Location"] for _ in range(2)]
    worker(env)
    with engine.connect() as connection:
        keys = [connection.scalar(text("SELECT storage_key FROM career.user_documents WHERE document_id=:id"),
                                  {"id": UUID(path.rsplit("/", 1)[1])}) for path in paths]
    assert keys[0] != keys[1]
    target = temp / "outside-private-file"
    target.write_bytes(b"synthetic outside file; must not be exposed or deleted")
    (files / keys[0]).unlink()
    (files / keys[0]).symlink_to(target)
    denied = client.get(paths[0] + "/file", headers=headers)
    assert denied.status_code == 503 and target.read_bytes() not in denied.content
    assert client.get(paths[1] + "/file", headers=headers).content == pdf()
    for path in paths:
        client.delete(path, headers=headers)
    worker(env)
    assert target.exists()
    assert not list(files.iterdir())



def test_live_verify_delete_race(live):
    client, _, _, env, _ = live
    headers = signup(client)
    path = upload(client, headers).headers["Location"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        verifying = executor.submit(worker, env)
        deleting = executor.submit(client.delete, path, headers=headers)
        assert deleting.result(timeout=90).status_code == 202
        verifying.result(timeout=180)
    current = client.get(path, headers=headers)
    # The concurrent batch may already have observed deleting and purged it.
    assert current.status_code == 404 or current.json()["status"] == "deleting"
    assert client.get(path + "/file", headers=headers).status_code in (404, 409)
    worker(env)
    assert client.get(path, headers=headers).status_code == 404


def test_live_private_permissions_random_names_and_no_leak(live):
    client, engine, files, env, _ = live
    headers = signup(client)
    paths, observed = [], set()
    for _ in range(12):
        response = upload(client, headers, name="same-original.pdf")
        assert response.status_code == 202
        path = response.headers["Location"]
        paths.append(path)
        with engine.connect() as connection:
            key = connection.scalar(text("SELECT storage_key FROM career.user_documents WHERE document_id=:id"),
                                    {"id": UUID(response.json()["document_id"])})
        assert re.fullmatch(r"[0-9a-f]{64}", key)
        assert key not in observed and key != response.json()["document_id"].replace("-", "")
        observed.add(key)
        assert (files / key).parent == files
        assert (files / key).stat().st_mode & 0o777 == 0o600
        assert (files / key).stat().st_mode & 0o111 == 0
        assert files.stat().st_mode & 0o777 == 0o700
        for exposed in (response, client.get(path, headers=headers), client.get(BASE, headers=headers)):
            visible = exposed.text + str(exposed.headers)
            assert key not in visible and str(files) not in visible
            assert "storage_key" not in visible and "checksum_sha256" not in visible
        assert client.get(f"{BASE}/{key}/file", headers=headers).status_code == 422
        assert client.get(f"/uploads/{key}", headers=headers).status_code == 404
    worker(env)
    for path in paths:
        response = client.get(path + "/file", headers=headers)
        assert response.status_code == 200
        assert all(key not in str(response.headers) for key in observed)
        client.delete(path, headers=headers)
    worker(env)
    assert not list(files.iterdir())


def test_live_directory_configuration_and_header_input(live):
    client, _, files, _, _ = live
    headers = signup(client)
    files.chmod(0o755)
    try:
        denied = upload(client, headers)
        assert denied.status_code == 503
        assert str(files) not in denied.text
    finally:
        files.chmod(0o700)
    raw = (b'--t49\r\nContent-Disposition: form-data; name="kind"\r\n\r\nresume\r\n'
           b'--t49\r\nContent-Disposition: form-data; name="file"; filename="bad\x00.pdf"\r\n'
           b'Content-Type: application/pdf\r\n\r\n' + pdf() + b'\r\n--t49--\r\n')
    assert client.post(BASE, headers={**headers, "Content-Type": "multipart/form-data; boundary=t49"}, content=raw).status_code == 422
    assert not list(files.iterdir())
