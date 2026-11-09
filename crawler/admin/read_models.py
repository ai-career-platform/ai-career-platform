"""T155 STEP02: private read-only crawler admin query service.

Not an HTTP router. No user identity is accepted, inferred, or authorized here.
Only a future T15-authenticated/authorized router may call this service.
All queries are SELECT-only and return metadata, never Raw HTML or credentials.
"""
from __future__ import annotations

from psycopg.rows import dict_row


def _pagination(limit: int, offset: int):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in 1..100")
    if type(offset) is not int or not 0 <= offset <= 100000:
        raise ValueError("offset must be an integer in 0..100000")
    return limit, offset


def _keyword_id(value):
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError("keyword_id must be a positive integer")
    return value


class CrawlerAdminReadStore:
    """Private metadata queries. Require a previously authorized caller.

    The supplied connection should be a read-only, dedicated crawler database
    connection at the integration boundary. This module does not connect or
    mutate the DB, start Workers, or access filesystem/HTTP.
    """

    def __init__(self, connection):
        self.connection = connection

    def _select(self, sql: str, params: tuple):
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def keywords(self, *, limit: int = 50, offset: int = 0):
        limit, offset = _pagination(limit, offset)
        return self._select(
            """SELECT keyword_id,keyword,enabled,priority,created_at,updated_at
               FROM crawler_training.search_keywords
               WHERE deleted_at IS NULL
               ORDER BY priority,keyword_id LIMIT %s OFFSET %s""",
            (limit, offset),
        )

    def jobs(self, *, limit: int = 50, offset: int = 0,
             keyword_id: int | None = None, status: str | None = None):
        limit, offset = _pagination(limit, offset)
        _keyword_id(keyword_id)
        allowed = {"PENDING", "RUNNING", "FETCHED", "FAILED", "COMPLETED", "CANCELLED"}
        if status is not None and status not in allowed:
            raise ValueError("unsupported job status")
        return self._select(
            """SELECT j.job_id,j.keyword_id,j.status,j.created_at,
                      j.started_at,j.ended_at,j.error_code,
                      a.attempt_count,a.state AS attempt_state
               FROM crawler_training.keyword_jobs j
               LEFT JOIN crawler_training.fixture_job_attempts a USING(job_id)
               WHERE (%s::bigint IS NULL OR j.keyword_id=%s::bigint)
                 AND (%s::text IS NULL OR j.status=%s::text)
               ORDER BY j.created_at DESC,j.job_id
               LIMIT %s OFFSET %s""",
            (keyword_id, keyword_id, status, status, limit, offset),
        )

    def schedules(self, *, limit: int = 20, offset: int = 0):
        limit, offset = _pagination(limit, offset)
        return self._select(
            """SELECT schedule_id,source_id,enabled,timezone,local_time,mode,
                      next_run_at,last_run_at,updated_at
               FROM crawler_training.schedules
               ORDER BY schedule_id LIMIT %s OFFSET %s""",
            (limit, offset),
        )

    def runs(self, *, limit: int = 50, offset: int = 0):
        limit, offset = _pagination(limit, offset)
        return self._select(
            """SELECT run_id,schedule_id,source_id,trigger,mode,scheduled_for,
                      attempt,status,started_at,ended_at,
                      fetched_count,inserted_count,updated_count,duplicate_count,
                      failed_count,error_code
               FROM crawler_training.runs
               ORDER BY started_at DESC,run_id LIMIT %s OFFSET %s""",
            (limit, offset),
        )

    def events(self, *, run_id, limit: int = 50, offset: int = 0):
        from uuid import UUID
        limit, offset = _pagination(limit, offset)
        try:
            uid = UUID(str(run_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("run_id must be UUID") from None
        return self._select(
            """SELECT event_id,run_id,occurred_at,level,event_type,safe_message
               FROM crawler_training.run_events
               WHERE run_id=%s
               ORDER BY event_id DESC LIMIT %s OFFSET %s""",
            (uid, limit, offset),
        )

    def keyword_stats(self, *, limit: int = 50, offset: int = 0):
        limit, offset = _pagination(limit, offset)
        return self._select(
            """SELECT k.keyword_id,k.keyword,k.enabled,k.priority,
                      (SELECT count(*) FROM crawler_training.keyword_jobs j
                       WHERE j.keyword_id=k.keyword_id) AS job_count,
                      (SELECT count(*) FROM crawler_training.keyword_posting_discoveries d
                       WHERE d.keyword_id=k.keyword_id) AS discovered_posting_count
               FROM crawler_training.search_keywords k
               WHERE k.deleted_at IS NULL
               ORDER BY k.priority,k.keyword_id LIMIT %s OFFSET %s""",
            (limit, offset),
        )
