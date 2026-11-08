"""T154 STEP21: conservative KST night-slot gate for explicit synthetic Fixture.

Does not install/activate a schedule, start processes, or enforce hard stop on
an already running worker. Intended for separate future timer/service wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date,datetime,time,timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from crawler.jobs.fixture_manual_retry import _execute_reserved_fixture_attempt
from crawler.jobs.fixture_retry_budget import DurableFixtureAttemptStore
from crawler.jobs.offline_recovery import RETRYABLE_CODES, STOP_CODES

KST=ZoneInfo("Asia/Seoul")
START=time(21,0)
END=time(8,0)
SLOT_MINUTES=30
MAX_SLOTS=22


@dataclass(frozen=True)
class NightSlot:
    night_date: date
    slot_index: int
    expires_at: datetime


def night_slot(at:datetime) -> NightSlot | None:
    """Determine the current half-hour slot, no late/catch-up slots.

    Evening 21:00..23:59 belongs to today; 00:00..07:59 to yesterday.
    Exactly 08:00 is outside. DST irrelevant in KST. Requires aware time.
    """
    if not isinstance(at,datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    local=at.astimezone(KST)
    minute=local.hour*60+local.minute
    if minute>=21*60:
        index=(minute-21*60)//SLOT_MINUTES
        night_date=local.date()
    elif minute<8*60:
        index=(minute+3*60)//SLOT_MINUTES
        night_date=local.date()-timedelta(days=1)
    else:
        return None
    if index<0 or index>=MAX_SLOTS:
        return None
    # Boundaries are strictly KST; no ambiguity at 08:00.
    midnight=datetime.combine(night_date+timedelta(days=1),time(0),KST)
    expires=midnight+timedelta(minutes=(index-6+1)*SLOT_MINUTES)
    return NightSlot(night_date,index,expires)


class NightSlotUnavailable(RuntimeError):
    pass


class NightSlotStore:
    def __init__(self,connection):
        self.connection=connection

    def reserve(self, *, job_id, now: datetime) -> NightSlot | None:
        """Compatibility slot-only reservation, with atomic eligibility check."""
        result = self._reserve(job_id=job_id, now=now, with_attempt=False)
        return result[0] if result else None

    def reserve_execution(self, *, job_id, now: datetime):
        """Commit Slot + Attempt together, or neither, before Worker starts.

        Use an independent autocommit connection; never an enclosing transaction.
        The job NOWAIT row lock serializes this with manual attempts and Workers.
        """
        return self._reserve(job_id=job_id, now=now, with_attempt=True)

    def _reserve(self, *, job_id, now, with_attempt):
        slot = night_slot(now)
        if slot is None:
            return None
        job_uuid = UUID(str(job_id))
        # Production psycopg connections must be idle/autocommit: nested outer
        # transactions would hide the claimed slot/attempt from the Worker.
        if hasattr(self.connection, "info"):
            from psycopg.pq import TransactionStatus
            if (not self.connection.autocommit or
                    self.connection.info.transaction_status != TransactionStatus.IDLE):
                raise ValueError("Independent idle autocommit slot connection required")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""SELECT j.job_id FROM crawler_training.keyword_jobs j
                    JOIN crawler_training.fixture_job_payloads p ON p.job_id=j.job_id
                    WHERE j.job_id=%s AND j.status='PENDING'
                    FOR UPDATE OF j NOWAIT""", (job_uuid,))
                if cur.fetchone() is None:
                    return None
                cur.execute("""SELECT attempt_count,state
                    FROM crawler_training.fixture_job_attempts
                    WHERE job_id=%s FOR UPDATE""", (job_uuid,))
                attempt = cur.fetchone()
                if attempt and (attempt[1] != "RETRYABLE" or attempt[0] >= 3):
                    return None
                cur.execute("""INSERT INTO crawler_training.fixture_night_slots
                    (night_date,slot_index,job_id) VALUES (%s,%s,%s)
                    ON CONFLICT DO NOTHING RETURNING slot_index""",
                    (slot.night_date, slot.slot_index, job_uuid))
                if cur.fetchone() is None:
                    return None
                reservation = None
                if with_attempt:
                    reservation = DurableFixtureAttemptStore(self.connection).reserve(job_uuid)
                    if reservation is None:
                        # Roll back the slot too; never consume a rejected attempt.
                        raise NightSlotUnavailable("Attempt changed during slot claim")
                return slot, reservation


def execute_night_fixture_once(
    *, slot_connection,attempt_connection,worker_connection,files,job_id,
    now:datetime,failure_error_code:str|None=None,
):
    """One explicit one-shot invocation; no timer or loop.

    The three DB connections must be separate. A slot is consumed even if
    attempt reservation or Worker fails. Does not guarantee an in-flight
    job terminates at 08:00: an external OS-enforced stop is still required.
    """
    if len({id(slot_connection),id(attempt_connection),id(worker_connection)})!=3:
        raise ValueError("Three distinct PostgreSQL connections required")
    if failure_error_code is not None and failure_error_code not in RETRYABLE_CODES | STOP_CODES:
        raise ValueError("Unknown failure code")
    claim=NightSlotStore(slot_connection).reserve_execution(job_id=job_id,now=now)
    if claim is None:
        raise NightSlotUnavailable("Outside KST window or slot/job already used")
    return _execute_reserved_fixture_attempt(
        attempt_connection=attempt_connection,
        worker_connection=worker_connection,
        files=files,job_id=job_id,reservation=claim[1],failure_error_code=failure_error_code,
    )
