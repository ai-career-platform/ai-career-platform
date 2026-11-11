"""T145 PostgreSQL JobStore (PROPOSED 표 `database/proposed/T145_background_jobs.sql` 전용, 미연결).

- claim: `FOR UPDATE SKIP LOCKED`로 대상 행을 잠그고, 같은 트랜잭션에서 상태·lease·fencing token을 갱신한다.
  여러 Worker가 동시에 claim해도 한 작업은 한 Worker에게만 간다.
- save: `WHERE lease_token = expected` 조건부 UPDATE. 0행이면 LeaseLost(옛 Worker의 늦은 보고 거부).
- 이력은 append-only 표에 새 항목만 추가한다.
연결은 호출부가 주입한다(일회용 DB 시험 전용). 운영 DB 연결·Timer 없음.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.services.background_jobs import (
    KINDS, HistoryEntry, Job, JobKindSpec, JobStatus, LeaseLost, _claim_one, _utc,
)

_COLUMNS = ("job_id, kind, idempotency_key, payload_ref, status, attempts, max_attempts, next_attempt_at, "
            "correlation_id, created_at, lease_owner, lease_until, lease_token, cancel_requested, last_error")


class PostgresJobStore:
    def __init__(self, connect, schema: str = "career") -> None:
        """connect: 새 psycopg 연결을 돌려주는 함수(Worker마다 별도 연결)."""
        if not schema.isidentifier():
            raise ValueError("invalid schema")
        self._connect, self._s = connect, schema

    def _history(self, cur, job_id: UUID) -> tuple[HistoryEntry, ...]:
        cur.execute(f"SELECT at, from_status, to_status, reason, worker_id, correlation_id, attempt "
                    f"FROM {self._s}.background_job_history WHERE job_id = %s ORDER BY seq", (job_id,))
        return tuple(HistoryEntry(r[0], JobStatus(r[1]) if r[1] else None, JobStatus(r[2]), r[3], r[4], r[5], r[6])
                     for r in cur.fetchall())

    def _row(self, cur, row) -> Job:
        (job_id, kind, key, ref, status, attempts, max_attempts, next_at, cid, created, owner, until, token,
         cancel, error) = row
        return Job(job_id, kind, key, ref, JobStatus(status), attempts, max_attempts, next_at, cid, created,
                   owner, until, token, cancel, error, self._history(cur, job_id))

    def _append_history(self, cur, job: Job) -> None:
        cur.execute(f"SELECT count(*) FROM {self._s}.background_job_history WHERE job_id = %s", (job.job_id,))
        stored = cur.fetchone()[0]
        for seq, h in enumerate(job.history[stored:], start=stored):
            cur.execute(f"INSERT INTO {self._s}.background_job_history VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (job.job_id, seq, h.at, h.from_status.value if h.from_status else None, h.to_status.value,
                         h.reason, h.worker_id, h.correlation_id, h.attempt))

    def _write(self, cur, job: Job) -> None:
        cur.execute(
            f"UPDATE {self._s}.background_jobs SET status=%s, attempts=%s, next_attempt_at=%s, lease_owner=%s, "
            f"lease_until=%s, lease_token=%s, cancel_requested=%s, last_error=%s WHERE job_id=%s",
            (job.status.value, job.attempts, job.next_attempt_at, job.lease_owner, job.lease_until,
             job.lease_token, job.cancel_requested, job.last_error, job.job_id))
        self._append_history(cur, job)

    def enqueue(self, job: Job) -> tuple[Job, bool]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._s}.background_jobs ({_COLUMNS}) VALUES "
                f"(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (kind, idempotency_key) DO NOTHING",
                (job.job_id, job.kind, job.idempotency_key, job.payload_ref, job.status.value, job.attempts,
                 job.max_attempts, job.next_attempt_at, job.correlation_id, job.created_at, job.lease_owner,
                 job.lease_until, job.lease_token, job.cancel_requested, job.last_error))
            created = cur.rowcount == 1
            if created:
                self._append_history(cur, job)
                return job, True
            cur.execute(f"SELECT {_COLUMNS} FROM {self._s}.background_jobs WHERE kind=%s AND idempotency_key=%s",
                        (job.kind, job.idempotency_key))
            return self._row(cur, cur.fetchone()), False

    def claim(self, *, now: datetime, worker_id: str, limit: int,
              kinds: Mapping[str, JobKindSpec] = KINDS) -> list[Job]:
        now = _utc(now)
        executable = [k for k, s in kinds.items() if s.executable]
        if not executable:
            return []
        out: list[Job] = []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM {self._s}.background_jobs WHERE kind = ANY(%s) AND ("
                f"(status IN ('queued','failed') AND next_attempt_at <= %s) OR "
                f"(status = 'running' AND lease_until <= %s)) "
                f"ORDER BY next_attempt_at, job_id LIMIT %s FOR UPDATE SKIP LOCKED",
                (executable, now, now, limit))
            rows = cur.fetchall()
            for row in rows:
                job = self._row(cur, row)
                moved = _claim_one(job, now=now, worker_id=worker_id, spec=kinds[job.kind])
                if moved is None:
                    continue
                self._write(cur, moved)
                if moved.status is JobStatus.RUNNING:
                    out.append(moved)
        return out

    def get(self, job_id: UUID) -> Job | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM {self._s}.background_jobs WHERE job_id=%s", (job_id,))
            row = cur.fetchone()
            return self._row(cur, row) if row else None

    def save(self, job: Job, *, expected_token: int | None) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT lease_token FROM {self._s}.background_jobs WHERE job_id=%s FOR UPDATE",
                        (job.job_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(job.job_id)
            if expected_token is not None and row[0] != expected_token:
                raise LeaseLost(str(job.job_id))
            self._write(cur, job)
