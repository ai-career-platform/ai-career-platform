"""Durable T64 policy/store. No schema creation, HTTP, or process execution."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import os
import json
from crawler.jobs.offline_schedule import KST
from crawler.jobs.run_state import RunRecord,RunStatus,_utc
from crawler.jobs.offline_recovery import retry_decision,RecoveryDecision,RecoveryPolicy
from crawler.policy.source_approval_gate import SourceApproval,CollectionIntent,check_collection_permission,_canonical_jobkorea


def next_daily(now, local_time):
    if local_time.tzinfo is not None:
        raise ValueError('Use timezone-naive KST local time')
    local=_utc(now).astimezone(KST)
    candidate=datetime.combine(local.date(),local_time,tzinfo=KST)
    if candidate<=local:
        candidate+=timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def retry_at(code,attempt,now):
    if retry_decision(error_code=code,attempt=attempt,policy=RecoveryPolicy())!=RecoveryDecision.RETRY_ELIGIBLE:
        return None
    return _utc(now)+timedelta(seconds=min(60*2**(attempt-1),300))


def schedule_approval(schedule):
    """The schedule's stored T61 approval record as a SourceApproval (raises if malformed)."""
    values=dict(schedule['approval'])
    for key in ('valid_from_utc','review_due_utc'):
        values[key]=datetime.fromisoformat(values[key].replace('Z','+00:00'))
    for key in ('allowed_urls','allowed_purposes'):
        values[key]=tuple(values[key])
    return SourceApproval(**values)


def eligible(schedule,now,*,manual_fixture=False):
    if manual_fixture:
        return (True,'FIXTURE') if schedule['mode']=='fixture' else (False,'MANUAL_FIXTURE_ONLY')
    if not schedule['enabled']:
        return False,'DISABLED'
    if schedule['mode']=='fixture':
        return True,'FIXTURE'
    if os.environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED')!='1':
        return False,'PM_ACTIVATION_REQUIRED'
    try:
        urls=schedule['target_urls']
        # Daily live targets are explicit detail pages only; a search URL (CRAWLER_NIGHT_09) is not a target.
        if not isinstance(urls,list) or not 1<=len(urls)<=5 or len(set(urls))!=len(urls) or not all(_canonical_jobkorea(u) for u in urls):
            return False,'INVALID_TARGETS'
        approval=schedule_approval(schedule)
        for url in urls:
            decision=check_collection_permission(approval,CollectionIntent('jobkorea',url,'WEB','scheduled_collection',len(urls)+1,_utc(now)))
            if not decision.allowed:
                return False,decision.reason.value
    except (TypeError,ValueError,KeyError,AttributeError):
        return False,'UNAPPROVED_SOURCE'
    return True,'ALLOWED'


class SchedulerStore:
    def __init__(self,connection):
        self.connection=connection
        self.last_decision='NOT_DUE_OR_DISABLED'
        # Runtime operations use short explicit transactions. Session advisory
        # locks survive commits and are released automatically on disconnect.
        connection.autocommit=True
        with connection.cursor() as c:
            c.execute("SET statement_timeout='15s'")
            c.execute("SET lock_timeout='5s'")

    def lock(self,key):
        with self.connection.cursor() as c:
            c.execute('SELECT pg_try_advisory_lock(642,%s)',(key,))
            return c.fetchone()[0]

    def unlock(self,key):
        with self.connection.cursor() as c:
            c.execute('SELECT pg_advisory_unlock(642,%s)',(key,))

    def schedule(self,schedule_id='jobkorea-daily'):
        from psycopg.rows import dict_row
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute('SELECT * FROM crawler_training.schedules WHERE schedule_id=%s',(schedule_id,))
            return c.fetchone()

    def configure(self,*,enabled=False,local_time,mode='fixture',target_urls=None,approval=None,now=None):
        if type(enabled) is not bool or mode not in ('fixture','live'):
            raise ValueError('Invalid schedule configuration')
        due=next_daily(now or datetime.now(timezone.utc),local_time)
        with self.connection.cursor() as c:
            c.execute('''UPDATE crawler_training.schedules SET enabled=%s,local_time=%s,mode=%s,
                target_urls=%s::jsonb,approval=%s::jsonb,next_run_at=%s,updated_at=now()
                WHERE schedule_id='jobkorea-daily' ''',
                (enabled,local_time,mode,json.dumps(target_urls or []),json.dumps(approval),due))
            if c.rowcount!=1:raise ValueError('Apply the approved migration first')

    def event(self,run_id,kind,level='INFO'):
        # All messages are fixed program codes; never raw worker output.
        with self.connection.cursor() as c:
            c.execute('''INSERT INTO crawler_training.run_events(run_id,level,event_type,safe_message)
                VALUES (%s,%s,%s,%s)''',(run_id,level,kind,kind))

    def finish(self,run_id,status,*,metrics=None,error=None,now=None):
        now=_utc(now or datetime.now(timezone.utc))
        with self.connection.transaction():
            with self.connection.cursor() as c:
                c.execute('SELECT source_id,started_at,attempt,status FROM crawler_training.runs WHERE run_id=%s FOR UPDATE',(run_id,))
                row=c.fetchone()
                if not row or row[3]!='RUNNING':return False
                record=RunRecord.pending(run_id=str(run_id),source_id=row[0],requested_at=row[1]).transition(RunStatus.RUNNING,at=row[1])
                record.transition(RunStatus(status),at=now,counters=metrics,error_code=error)
                # Manual one-shot runs are never auto-retried by the dispatcher.
                retry=retry_at(error,row[2],now) if status=='FAILED' and not self.is_manual(run_id) else None
                m=metrics or {}
                c.execute('''UPDATE crawler_training.runs SET status=%s,ended_at=%s,heartbeat_at=%s,
                    retry_at=%s,error_code=%s,fetched_count=%s,inserted_count=%s,updated_count=%s,
                    duplicate_count=%s,failed_count=%s WHERE run_id=%s''',
                    (status,now,now,retry,error,m.get('fetched'),m.get('inserted'),m.get('updated'),
                     m.get('unchanged',0)+m.get('duplicates',0) if metrics is not None else None,m.get('invalid'),run_id))
            self.event(run_id,error or status,'ERROR' if status=='FAILED' else 'INFO')
            return True

    def recover(self,now):
        # A stale heartbeat alone is NOT enough: an orphan worker may still
        # own the source lock. Never release its claim while it can write.
        if not self.lock(1):return 0
        try:
            with self.connection.cursor() as c:
                c.execute("SELECT run_id FROM crawler_training.runs WHERE status='RUNNING' AND heartbeat_at<=%s",(now-timedelta(minutes=5),))
                ids=[r[0] for r in c.fetchall()]
            return sum(self.finish(r,'FAILED',error='HEARTBEAT_TIMEOUT',now=now) for r in ids)
        finally:self.unlock(1)

    def claim(self,now=None):
        self.last_decision='NOT_DUE_OR_DISABLED'
        now=_utc(now or datetime.now(timezone.utc))
        self.recover(now)
        from psycopg.rows import dict_row
        with self.connection.transaction():
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute('''SELECT * FROM crawler_training.schedules s WHERE enabled AND
                    (next_run_at<=%s OR EXISTS(SELECT 1 FROM crawler_training.runs r
                    WHERE r.schedule_id=s.schedule_id AND r.retry_at<=%s))
                    FOR UPDATE SKIP LOCKED''',(now,now))
                s=c.fetchone()
                if not s:return None
                allowed,reason=eligible(s,now)
                if not allowed:
                    self.last_decision=reason
                    return None
                c.execute("SELECT 1 FROM crawler_training.runs WHERE source_id=%s AND status='RUNNING'",(s['source_id'],))
                if c.fetchone():return None
                c.execute('''SELECT run_id,scheduled_for,attempt FROM crawler_training.runs
                    WHERE schedule_id=%s AND retry_at<=%s ORDER BY ended_at DESC LIMIT 1 FOR UPDATE''',(s['schedule_id'],now))
                previous=c.fetchone()
                if previous:
                    slot,attempt,trigger=previous['scheduled_for'],previous['attempt']+1,'retry'
                    c.execute('UPDATE crawler_training.runs SET retry_at=NULL WHERE run_id=%s',(previous['run_id'],))
                else:
                    slot,attempt,trigger=s['next_run_at'],1,'scheduled'
                    c.execute('UPDATE crawler_training.schedules SET next_run_at=%s WHERE schedule_id=%s',(next_daily(now,s['local_time']),s['schedule_id']))
                run_id=uuid4()
                c.execute('''INSERT INTO crawler_training.runs
                    (run_id,schedule_id,source_id,trigger,mode,scheduled_for,attempt,status,started_at,heartbeat_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'RUNNING',%s,%s)''',
                    (run_id,s['schedule_id'],s['source_id'],trigger,s['mode'],slot,attempt,now,now))
                c.execute('UPDATE crawler_training.schedules SET last_run_at=%s,updated_at=%s WHERE schedule_id=%s',(now,now,s['schedule_id']))
            self.event(run_id,'CLAIMED')
            return str(run_id)

    def is_manual(self,run_id):
        with self.connection.cursor() as c:
            c.execute("SELECT 1 FROM crawler_training.run_events WHERE run_id=%s AND event_type='MANUAL_RUN' LIMIT 1",(run_id,))
            return c.fetchone() is not None

    def claim_manual(self,now=None,schedule_id='jobkorea-daily'):
        """One operator-requested FIXTURE run outside the daily slot.

        Reuses the schedule row lock, eligibility gate and single-RUNNING rule. It never moves
        next_run_at/last_run_at, so the 03:00 KST slot is unchanged. runs.trigger only allows
        'scheduled'/'retry' (0002 CHECK); without a migration the run is stored as 'scheduled'
        at the request time and marked by a MANUAL_RUN event written before CLAIMED.
        """
        self.last_decision='NOT_DUE_OR_DISABLED'
        now=_utc(now or datetime.now(timezone.utc))
        self.recover(now)
        from psycopg.rows import dict_row
        with self.connection.transaction():
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute('SELECT * FROM crawler_training.schedules WHERE schedule_id=%s FOR UPDATE',(schedule_id,))
                s=c.fetchone()
                if not s:
                    self.last_decision='SCHEDULE_MISSING';return None
                if s['mode']!='fixture':
                    self.last_decision='MANUAL_FIXTURE_ONLY';return None
                allowed,reason=eligible(s,now,manual_fixture=True)
                if not allowed:
                    self.last_decision=reason;return None
                c.execute("SELECT 1 FROM crawler_training.runs WHERE source_id=%s AND status='RUNNING'",(s['source_id'],))
                if c.fetchone():
                    self.last_decision='ALREADY_RUNNING';return None
                run_id=uuid4()
                c.execute('''INSERT INTO crawler_training.runs
                    (run_id,schedule_id,source_id,trigger,mode,scheduled_for,attempt,status,started_at,heartbeat_at)
                    VALUES (%s,%s,%s,'scheduled','fixture',%s,1,'RUNNING',%s,%s)''',
                    (run_id,s['schedule_id'],s['source_id'],now,now,now))
                c.execute('''INSERT INTO crawler_training.run_events(run_id,level,event_type,safe_message)
                    VALUES (%s,'INFO','MANUAL_RUN','MANUAL_RUN')''',(run_id,))
            self.event(run_id,'CLAIMED')
            return str(run_id)

    def heartbeat(self,run_id):
        with self.connection.cursor() as c:
            c.execute("UPDATE crawler_training.runs SET heartbeat_at=clock_timestamp() WHERE run_id=%s AND status='RUNNING'",(run_id,))

    def read(self,kind,run_id=None,limit=20):
        from psycopg.rows import dict_row
        queries={
            'schedules':('SELECT schedule_id,source_id,enabled,timezone,local_time,next_run_at,last_run_at,updated_at,mode FROM crawler_training.schedules',()),
            'runs':('SELECT * FROM crawler_training.runs ORDER BY started_at DESC LIMIT %s',(limit,)),
            'events':('SELECT * FROM crawler_training.run_events WHERE run_id=%s ORDER BY event_id LIMIT %s',(run_id,limit)),
            'run':('SELECT * FROM crawler_training.runs WHERE run_id=%s',(run_id,))}
        query,params=queries[kind]
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(query,params);return c.fetchall()
