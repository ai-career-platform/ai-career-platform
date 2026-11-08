"""T152 isolated synthetic raw HTML storage. No network, parsing, or UPSERT.

Caller owns a dedicated directory and manually applied 0005 migration. Bytes are
stored by content hash; PostgreSQL stores metadata only. Not a live fetcher.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

from crawler.adapters.jobkorea_html_offline import _source_id

MAX_HTML_BYTES = 2_000_000
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


class RawArtifactError(ValueError):
    pass


def validate_page(kind: str, url: str, body: bytes, content_type: str) -> str:
    if kind not in ("list", "detail"):
        raise RawArtifactError("Unsupported raw page kind")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise RawArtifactError("Unsupported HTML content type")
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_HTML_BYTES:
        raise RawArtifactError("HTML body empty or too large")
    if not isinstance(url, str) or len(url) > 2048:
        raise RawArtifactError("Invalid source URL")
    try:
        if kind == "detail":
            _source_id(url)
        else:
            p = urlsplit(url)
            if (p.scheme != "https" or p.hostname != "www.jobkorea.co.kr"
                    or p.username or p.password or p.port or p.fragment
                    or p.path not in ("/Search", "/Search/")):
                raise RawArtifactError("Invalid list URL")
    except ValueError:
        raise RawArtifactError("Invalid source URL") from None
    # Raw artifacts are preserved as bytes; no HTML parsing in this layer.
    return sha256(body).hexdigest()


@dataclass(frozen=True)
class RawReceipt:
    artifact_id: str
    kind: str
    source_url: str
    sha256: str
    byte_size: int
    storage_key: str


class RawArtifactStore:
    """File-backed content-addressed storage and DB metadata.

    A file may remain if the DB insert fails; orphan reconciliation is explicit
    and must not delete any file automatically. No file contents in logs.
    """

    def __init__(self, root: Path):
        root = Path(root)
        if root.is_symlink():
            raise RawArtifactError("Symlink root is not allowed")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise RawArtifactError("Symlink root is not allowed")

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / (digest + ".html")

    def save(self, *, kind: str, source_url: str, body: bytes,
             content_type: str = "text/html") -> RawReceipt:
        digest = validate_page(kind, source_url, body, content_type)
        target = self._path(digest)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.is_symlink():
            raise RawArtifactError("Symlink artifact is not allowed")
        if target.exists():
            if target.read_bytes() != body:
                raise RawArtifactError("Existing artifact hash collision or corruption")
        else:
            fd, name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600) if hasattr(os, "fchmod") else None
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Unique digest path shared by repeated synthetic pages.
                if target.exists():
                    if target.read_bytes() != body:
                        raise RawArtifactError("Existing artifact corruption")
                else:
                    os.replace(name, target)
                    name = None
            finally:
                if name is not None:
                    Path(name).unlink(missing_ok=True)
        return RawReceipt(str(uuid4()), kind, source_url, digest, len(body),
                          digest[:2] + "/" + digest + ".html")

    def read_verified(self, storage_key: str, expected_sha256: str) -> bytes:
        if (not isinstance(storage_key, str) or
                not isinstance(expected_sha256, str) or
                len(expected_sha256) != 64 or
                storage_key != expected_sha256[:2] + "/" + expected_sha256 + ".html" or
                any(c not in "0123456789abcdef" for c in expected_sha256)):
            raise RawArtifactError("Invalid storage reference")
        target = self._path(expected_sha256)
        if target.is_symlink() or not target.is_file():
            raise RawArtifactError("Missing or unsafe artifact")
        data = target.read_bytes()
        if sha256(data).hexdigest() != expected_sha256:
            raise RawArtifactError("Artifact integrity check failed")
        return data


class RawArtifactMetadata:
    """Stores receipts against T151 keywords; no schema creation or worker launch."""

    def __init__(self, connection):
        self.connection = connection

    def insert(self, *, receipt: RawReceipt, keyword_id: int,
               job_id=None, http_status: int = 200, content_type: str = "text/html"):
        if not isinstance(receipt, RawReceipt):
            raise RawArtifactError("RawReceipt required")
        if type(http_status) is not int or http_status != 200:
            raise RawArtifactError("Only successful fixture capture is supported")
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise RawArtifactError("Invalid content type")
        # The receipt names shared bytes, not a keyword-specific metadata row.
        # Allocate a fresh DB primary key on every insert attempt; the composite
        # uniqueness constraint preserves idempotency for the same keyword.
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.raw_artifacts
                    (artifact_id,keyword_id,job_id,kind,source_url,http_status,
                     content_type,byte_size,sha256,storage_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (keyword_id,kind,source_url,sha256) DO NOTHING
                    RETURNING artifact_id""",
                    (uuid4(),keyword_id,job_id,receipt.kind,
                     receipt.source_url,http_status,content_type,
                     receipt.byte_size,receipt.sha256,receipt.storage_key))
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute("""SELECT artifact_id,storage_key FROM crawler_training.raw_artifacts
                    WHERE keyword_id=%s AND kind=%s AND source_url=%s AND sha256=%s""",
                    (keyword_id,receipt.kind,receipt.source_url,receipt.sha256))
                existing = cur.fetchone()
                if existing is None or existing[1] != receipt.storage_key:
                    raise RawArtifactError("Conflicting raw artifact metadata")
                return existing[0]
