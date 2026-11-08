"""T151 internal keyword and job metadata store; no network, scheduler, or DDL.

Only run after the manual 0003 migration has been reviewed/applied in a dedicated
crawler_training database. Calls are parameterized; no admin HTTP endpoints.
"""
from __future__ import annotations
from dataclasses import dataclass
from uuid import uuid4
import unicodedata

DEFAULT_KEYWORDS = ("AI", "Python", "데이터 분석", "LLM", "업무 자동화", "AI 엔지니어")
TERMINAL_STATUSES = frozenset({"FAILED", "COMPLETED", "CANCELLED"})
VALID_STATUSES = frozenset({"PENDING", "RUNNING", "FETCHED", *TERMINAL_STATUSES})
TRANSITIONS = {
    "PENDING": {"RUNNING", "CANCELLED"},
    "RUNNING": {"FETCHED", "FAILED", "CANCELLED"},
    "FETCHED": {"COMPLETED", "FAILED", "CANCELLED"},
    "FAILED": set(),
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def normalize_keyword(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("keyword must be text")
    display = " ".join(unicodedata.normalize("NFKC", value).split())
    key = display.casefold()
    if not 1 <= len(display) <= 100:
        raise ValueError("keyword length must be 1..100")
    return display, key


def check_priority(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 9999:
        raise ValueError("priority must be an integer between 1 and 9999")
    return value


def check_idempotency(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or value != value.strip():
        raise ValueError("idempotency key length must be 1..200 without outer spaces")
    return value


@dataclass(frozen=True)
class Keyword:
    keyword_id: int
    keyword: str
    enabled: bool
    priority: int


class KeywordStore:
    """psycopg-compatible connection; manages metadata, never starts a worker."""

    def __init__(self, connection):
        self.connection = connection

    def list_keywords(self, *, include_deleted: bool = False):
        from psycopg.rows import dict_row
        sql = """SELECT keyword_id,keyword,enabled,priority
                 FROM crawler_training.search_keywords"""
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY priority, keyword_id"
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall()

    def add_keyword(self, value: str, *, priority: int = 100):
        display, normalized = normalize_keyword(value)
        check_priority(priority)
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.search_keywords
                    (keyword,normalized_keyword,priority)
                    VALUES (%s,%s,%s) RETURNING keyword_id""",
                    (display, normalized, priority))
                return cur.fetchone()[0]

    def edit_keyword(self, keyword_id: int, value: str, *, priority: int):
        display, normalized = normalize_keyword(value)
        check_priority(priority)
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.search_keywords
                    SET keyword=%s, normalized_keyword=%s, priority=%s,updated_at=now()
                    WHERE keyword_id=%s AND deleted_at IS NULL
                    RETURNING keyword_id""",
                    (display, normalized, priority, keyword_id))
                return cur.fetchone() is not None

    def set_enabled(self, keyword_id: int, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("enabled must be bool")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.search_keywords
                    SET enabled=%s,updated_at=now()
                    WHERE keyword_id=%s AND deleted_at IS NULL
                    RETURNING keyword_id""", (enabled, keyword_id))
                return cur.fetchone() is not None

    def soft_delete(self, keyword_id: int):
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.search_keywords
                    SET enabled=false,deleted_at=now(),updated_at=now()
                    WHERE keyword_id=%s AND deleted_at IS NULL
                    RETURNING keyword_id""", (keyword_id,))
                return cur.fetchone() is not None

    def create_job(self, keyword_id: int, idempotency_key: str):
        """Create metadata-only job. Does NOT enqueue or dispatch a worker."""
        check_idempotency(idempotency_key)
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.keyword_jobs
                    (job_id,keyword_id,idempotency_key)
                    SELECT %s,keyword_id,%s FROM crawler_training.search_keywords
                    WHERE keyword_id=%s AND enabled=true AND deleted_at IS NULL
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING job_id""", (uuid4(), idempotency_key, keyword_id))
                row = cur.fetchone()
                if row:
                    return row[0]
                cur.execute("""SELECT job_id,keyword_id FROM crawler_training.keyword_jobs
                    WHERE idempotency_key=%s""", (idempotency_key,))
                existing = cur.fetchone()
                if existing:
                    if existing[1] != keyword_id:
                        raise ValueError("idempotency key belongs to another keyword")
                    return existing[0]
                raise ValueError("keyword inactive or missing")

    def transition(self, job_id, from_status: str, to_status: str):
        """Compare-and-swap transition with allowed edges, never launches a worker."""
        if to_status not in TRANSITIONS.get(from_status, set()):
            raise ValueError("invalid state transition")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.keyword_jobs SET status=%s,
                  started_at=CASE WHEN %s='RUNNING' THEN now() ELSE started_at END,
                  ended_at=CASE WHEN %s IN ('FAILED','COMPLETED','CANCELLED')
                    THEN now() ELSE ended_at END
                  WHERE job_id=%s AND status=%s RETURNING job_id""",
                    (to_status,to_status,to_status,job_id,from_status))
                return cur.fetchone() is not None

    def record_discovery(self, keyword_id: int, source_code: str, external_posting_id: str):
        """Only call after posting exists; FK guards dangling discoveries."""
        if not source_code or not external_posting_id:
            raise ValueError("posting identity required")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.keyword_posting_discoveries
                  (keyword_id,source_code,external_posting_id)
                  VALUES (%s,%s,%s)
                  ON CONFLICT (keyword_id,source_code,external_posting_id)
                  DO UPDATE SET last_seen_at=now()""",
                  (keyword_id,source_code,external_posting_id))
