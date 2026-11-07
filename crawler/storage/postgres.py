"""Explicit opt-in PostgreSQL storage for isolated local training only.

Requires a pre-created local-only DB and table, never creates schemas/tables.
psycopg is imported lazily so offline training and tests need no dependencies.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from crawler.normalizer import NormalizedPosting
from crawler.storage.memory import WriteResult


class UnsafeDatabaseTarget(ValueError):
    """DB target does not meet the strictly local training contract."""


def validate_local_dsn(dsn: str) -> None:
    """Fail closed unless an explicitly named local test database is selected."""
    if not dsn:
        raise UnsafeDatabaseTarget("CRAWLER_LOCAL_DATABASE_URL is required")
    parts = urlsplit(dsn)
    if parts.query or parts.fragment:\n        raise UnsafeDatabaseTarget("URL options and fragments are not permitted")\n    if parts.scheme not in {"postgresql", "postgres"}:
        raise UnsafeDatabaseTarget("Use a postgres:// or postgresql:// URL")
    if parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise UnsafeDatabaseTarget("Only a local PostgreSQL host is permitted")
    if parts.path != "/ai_career_crawler_training":
        raise UnsafeDatabaseTarget("DB must be ai_career_crawler_training")
    if parts.username in {None, "", "postgres", "ai_career_poc"}:
        raise UnsafeDatabaseTarget("Use a dedicated non-superuser training role")


class PostgresPostingStore:
    """Sequential single-process upsert against an isolated training table.

    Calls do not change the application's career schema. Writes are transactional
    per posting. A UNIQUE key guards against duplicate inserts.
    """

    def __init__(self, connection) -> None:
        self.connection = connection

    def upsert(self, posting: NormalizedPosting) -> WriteResult:
        payload = json.dumps(posting.to_dict(), ensure_ascii=False, sort_keys=True)
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute(
                    """INSERT INTO crawler_training.postings
                       (source_code, external_posting_id, payload)
                       VALUES (%s, %s, %s::jsonb)
                       ON CONFLICT (source_code, external_posting_id)
                       DO NOTHING RETURNING external_posting_id""",
                    (posting.source_code, posting.external_posting_id, payload),
                )
                if cur.fetchone() is not None:
                    return "inserted"
                cur.execute(
                    """SELECT payload FROM crawler_training.postings
                       WHERE source_code = %s AND external_posting_id = %s
                       FOR UPDATE""",
                    (posting.source_code, posting.external_posting_id),
                )
                existing = cur.fetchone()
                if existing is None:
                    raise RuntimeError("Conflicting row disappeared during upsert")
                old_payload = existing[0]
                if isinstance(old_payload, str):
                    old_payload = json.loads(old_payload)
                if old_payload == posting.to_dict():
                    return "unchanged"
                cur.execute(
                    """UPDATE crawler_training.postings
                       SET payload = %s::jsonb, updated_at = now()
                       WHERE source_code = %s AND external_posting_id = %s""",
                    (payload, posting.source_code, posting.external_posting_id),
                )
                return "updated"


def connect_local_training_db(dsn: str):
    """Connect only after validating host, DB name, role and provided credentials."""
    validate_local_dsn(dsn)
    import psycopg

    # No implicit schema creation. Local access only.
    return psycopg.connect(dsn, hostaddr="127.0.0.1", connect_timeout=5)
