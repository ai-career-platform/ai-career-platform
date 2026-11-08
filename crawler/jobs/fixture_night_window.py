"""T154 STEP21: conservative KST night-slot gate for explicit synthetic Fixture.

Does not install/activate a schedule, start processes, or enforce hard stop on
an already running worker. Intended for separate future timer/service wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date,datetime,time,timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from crawler.jobs.fixture_manual_retry import execute_manual_fixture_attempt

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

    def reserve(self,*,job_id,now:datetime) -> NightSlot | None:
        """One committed reservation per slot, one job per night.

        Caller MUST use an independent connection with no enclosing
        transaction. A slot remains spent even if its worker fails.
        """
        slot=night_slot(now)
        if slot is None:return None
        job_uuid=UUID(str(job_id))
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.fixture_night_slots
                    (night_date,slot_index,job_id)
                    SELECT %s,%s,j.job_id
                    FROM crawler_training.keyword_jobs j
                    JOIN crawler_training.fixture_job_payloads p
                      ON p.job_id=j.job_id
                    WHERE j.job_id=%s AND j.status='PENDING'
                    ON CONFLICT DO NOTHING RETURNING slot_index""",
                    (slot.night_date,slot.slot_index,job_uuid))
                row=cur.fetchone()
                return slot if row else None


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
    slot=NightSlotStore(slot_connection).reserve(job_id=job_id,now=now)
    if slot is None:
        raise NightSlotUnavailable("Outside KST window or slot/job already used")
    return execute_manual_fixture_attempt(
        attempt_connection=attempt_connection,
        worker_connection=worker_connection,
        files=files,job_id=job_id,failure_error_code=failure_error_code,
    )
