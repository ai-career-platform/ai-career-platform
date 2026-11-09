"""Bounded, date-specific synthetic supply -> existing one-shot. No timer install."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import os,sys,time
from uuid import uuid4
from datetime import date,datetime,timedelta
import hashlib
import json
from pathlib import Path

from crawler.jobs.fixture_night_window import KST,night_slot
from crawler.jobs.fixture_night_executor import run_once,execution_budget
from crawler.jobs.keyword_management import KeywordStore
from crawler.jobs.fixture_payloads import FixturePayloadStore
from crawler.jobs.fixture_raw_batch import capture_fixture_batch
from crawler.jobs.raw_artifact_store import RawArtifactStore,RawArtifactMetadata
from crawler.adapters.jobkorea_html_offline import _source_id
from crawler.storage.staging import connect_configured_database

CALLER_LOCK=154250001


def allowed_slot(night_date,now):
    slot=night_slot(now)
    return slot if slot and slot.night_date==night_date else None


def load_input(path):
    path=Path(path)
    if not path.is_file():return []
    if path.stat().st_size>16384:raise ValueError('Input too large')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('mode')!='synthetic_fixture_only':
        raise ValueError('Synthetic input required')
    items=value.get('items')
    if not isinstance(items,list) or len(items)>10:raise ValueError('Invalid batch')
    for item in items:
        if not isinstance(item,dict) or set(item)!={'title','company'}:raise ValueError('Invalid item')
        if any(not isinstance(item[k],str) or not 1<=len(item[k])<=200 for k in item):raise ValueError('Invalid item')
    return items


def synthetic_ids(night,index,count):
    return tuple(str(880000000000000+int(hashlib.sha256(f'{night}:{index}:{i}'.encode()).hexdigest()[:12],16)%10000000000000) for i in range(count))


def _validate_job(c,job,keyword,files):
    p=FixturePayloadStore(c).read(job)
    if p.keyword_id!=keyword:raise ValueError('Keyword mismatch')
    rows=c.execute("""SELECT kind,source_url,storage_key,sha256,byte_size,mode
        FROM crawler_training.raw_artifacts WHERE job_id=%s AND keyword_id=%s""",(job,keyword)).fetchall()
    found=[]
    for kind,url,key,sha,size,mode in rows:
        if mode!='synthetic_fixture_only' or len(files.read_verified(key,sha))!=size:raise ValueError('Invalid Raw')
        if kind=='detail':found.append(_source_id(url))
    if len(found)!=len(p.posting_ids) or set(found)!=set(p.posting_ids):raise ValueError('Incomplete Raw')
    return p


def _prepare(c,slot,items,files):
    name='synthetic-night-'+str(slot.night_date)
    with c.transaction():
        c.execute("SET LOCAL statement_timeout='1500ms'")
        c.execute("SET LOCAL lock_timeout='200ms'")
        row=c.execute('SELECT keyword_id,enabled,deleted_at FROM crawler_training.search_keywords WHERE keyword=%s',(name,)).fetchone()
        if row and (not row[1] or row[2] is not None):return None,'KEYWORD_DISABLED'
        keyword=row[0] if row else None
        if keyword:
            # Interrupted/stopped work needs review, never a fresh job to bypass it.
            if c.execute("""SELECT 1 FROM crawler_training.keyword_jobs j JOIN crawler_training.fixture_job_attempts a USING(job_id)
                WHERE j.keyword_id=%s AND a.state IN ('IN_PROGRESS','STOPPED') LIMIT 1""",(keyword,)).fetchone():
                return None,'NIGHT_REQUIRES_REVIEW'
            job=c.execute("""SELECT j.job_id FROM crawler_training.keyword_jobs j
                JOIN crawler_training.fixture_job_payloads p USING(job_id)
                LEFT JOIN crawler_training.fixture_job_attempts a USING(job_id)
                WHERE j.keyword_id=%s AND j.status='PENDING'
                AND (a.job_id IS NULL OR (a.state='RETRYABLE' AND a.attempt_count<3))
                ORDER BY j.created_at,j.job_id LIMIT 1""",(keyword,)).fetchone()
            if job:
                _validate_job(c,job[0],keyword,files)
                return job[0],'EXISTING_PENDING'
        if not items:return None,'NO_INPUT'
        ids=synthetic_ids(str(slot.night_date),slot.slot_index,len(items))
        if len(set(ids))!=len(ids) or c.execute('SELECT 1 FROM crawler_training.postings WHERE external_posting_id=ANY(%s)',(list(ids),)).fetchone():
            return None,'SYNTHETIC_ID_COLLISION'
        if keyword is None:keyword=KeywordStore(c).add_keyword(name)
        job=KeywordStore(c).create_job(keyword,f'fixture:night:{slot.night_date}:{slot.slot_index}')
        status=c.execute('SELECT status FROM crawler_training.keyword_jobs WHERE job_id=%s',(job,)).fetchone()[0]
        if status!='PENDING':return None,'JOB_NOT_PENDING'
        FixturePayloadStore(c).register(job_id=job,keyword_id=keyword,posting_ids=ids)
        pages={}
        for i,item in zip(ids,items):
            url='https://www.jobkorea.co.kr/Recruit/GI_Read/'+i
            body={'@type':'JobPosting','title':item['title'],'hiringOrganization':{'name':item['company']},'identifier':{'value':i},'url':url}
            pages[url]=('<!-- Synthetic Fixture only; never fetched --><script type="application/ld+json">'+json.dumps(body,ensure_ascii=True)+'</script>').encode()
        listing=('<!-- Synthetic Fixture only -->'+''.join('<a href="'+u+'">Synthetic Fixture</a>' for u in pages)).encode()
        capture_fixture_batch(keyword_id=keyword,list_url='https://www.jobkorea.co.kr/Search/?stext=synthetic_fixture',list_html=listing,detail_pages=pages,files=files,metadata=RawArtifactMetadata(c),job_id=job,limit=10)
        _validate_job(c,job,keyword,files)
        return job,'NEW_SYNTHETIC'


def _log(path,result):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    result['ended_at']=datetime.now(KST).isoformat()
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(result)+'\n')
    return result


def call_once(*,night_date,input_file,raw_root,log_file,connector=connect_configured_database,clock=None,executor=run_once):
    clock=clock or (lambda:datetime.now(KST));now=clock();slot=allowed_slot(night_date,now)
    out={'event':'NIGHT_CALLER','night_date':str(night_date),'slot_index':slot.slot_index if slot else None,'started_at':now.isoformat(),'status':'IDLE','reason':None,'job_id':None,'processed_postings':0,'external_http_requests':0}
    # Supply is bounded small work; don't start it in the last three minutes.
    end=datetime.combine(night_date+timedelta(days=1),datetime.min.time(),KST).replace(hour=8)
    if slot is None or (end-now).total_seconds()<180:
        out['reason']='OUTSIDE_NIGHT_OR_INSUFFICIENT_TIME';return _log(log_file,out)
    try:
        items=load_input(input_file)
    except (ValueError,OSError):
        out.update(reason='INPUT_INVALID');return _log(log_file,out)
    try:
        with connector() as c:
            c.autocommit=True
            if not c.execute('SELECT pg_try_advisory_lock(%s)',(CALLER_LOCK,)).fetchone()[0]:
                out['reason']='CALLER_BUSY';return _log(log_file,out)
            if c.execute('SELECT 1 FROM crawler_training.fixture_night_slots WHERE night_date=%s AND slot_index=%s',(night_date,slot.slot_index)).fetchone():
                out['reason']='SLOT_ALREADY_USED';return _log(log_file,out)
            job,reason=_prepare(c,slot,items,RawArtifactStore(Path(raw_root)))
            out.update(reason=reason,job_id=str(job) if job else None)
            if job is None:return _log(log_file,out)
            current=clock()
            if allowed_slot(night_date,current)!=slot or execution_budget(current) is None:
                out['reason']='CLOCK_MOVED';return _log(log_file,out)
            workerlog=Path(log_file).with_name('worker.jsonl')
            # Recompute actual remaining deadline AFTER supply, never reuse old time.
            worker=executor(job_id=job,raw_root=raw_root,log_file=workerlog,now=current)
            out.update(worker);out['event']='NIGHT_CALLER';out['supply_reason']=reason;out['worker_log']=str(workerlog)
    except Exception:
        # No exception strings, SQL/DSN or stderr in public JSONL.
        out.update(status='UNRESOLVED',reason='CALLER_ERROR',requires_manual_review=True)
    return _log(log_file,out)


def marked_connection():
    c=connect_configured_database();c.autocommit=True
    token=os.environ.get('T154_GUARD_TOKEN','')
    if len(token)!=16 or any(x not in '0123456789abcdef' for x in token):
        c.close();raise ValueError('Guard token required')
    c.execute("SELECT set_config('application_name',%s,false)",('t154-caller:'+token,))
    return c


def marked_executor(**kwargs):
    return run_once(**kwargs,connector=marked_connection)


def guarded_once(*,night_date,input_file,raw_root,log_file,invocation_id=None,**kwargs):
    """Known per-invocation cancel/done handshake for final host archival."""
    token=invocation_id or uuid4().hex[:16]
    if len(token)!=16 or any(c not in '0123456789abcdef' for c in token):raise ValueError('Invalid invocation ID')
    folder=Path(raw_root).parent/'invocations';folder.mkdir(parents=True,exist_ok=True)
    cancel=folder/(token+'.cancel');done=folder/(token+'.done.json')
    result=None
    try:
        if cancel.exists():
            result=_log(log_file,{'event':'NIGHT_CALLER','status':'IDLE','reason':'CANCELLED_BEFORE_START','external_http_requests':0})
        else:
            result=_guarded_once(night_date=night_date,input_file=input_file,raw_root=raw_root,log_file=log_file,token=token,cancel_file=cancel,**kwargs)
        return result
    finally:
        # Emitted only after child reap, DB cleanup and final JSONL close.
        temporary=done.with_suffix('.tmp')
        temporary.write_text(json.dumps({'invocation_id':token,'state':'EXITED','status':result.get('status') if result else 'UNRESOLVED','finished_at':datetime.now(KST).isoformat()}))
        os.replace(temporary,done)


def _guarded_once(*,night_date,input_file,raw_root,log_file,connector=connect_configured_database,
                 now=None,command=None,maximum=140,cleanup_budget=3,grace=2,token=None,cancel_file=None):
    """Bound the ENTIRE caller, including preparation, before the worker guard.

    POSIX process-group TERM/KILL covers descendants. A pre-opened independent
    diagnostic connection cleans only this token's own-role DB sessions.
    """
    from crawler.jobs.fixture_night_executor import supervise,_termination_signals
    current=now or datetime.now(KST);slot=allowed_slot(night_date,current)
    end=datetime.combine(night_date+timedelta(days=1),datetime.min.time(),KST).replace(hour=8)
    if slot is None or (end-current).total_seconds()<180:
        return _log(log_file,{'event':'NIGHT_CALLER','status':'IDLE','reason':'OUTSIDE_NIGHT_OR_INSUFFICIENT_TIME','night_date':str(night_date),'job_id':None,'external_http_requests':0})
    token=token or uuid4().hex[:16];env=os.environ.copy();env['T154_GUARD_TOKEN']=token
    deadline=time.monotonic()+min(maximum,(end-current).total_seconds())
    result={'event':'NIGHT_CALLER_GUARD','status':'UNRESOLVED','reason':'CHILD_UNRESOLVED','guard_token':token,'external_http_requests':0}
    with connector() as diagnostic:
        diagnostic.autocommit=True
        argv=command or [sys.executable,'-m','crawler.jobs.fixture_night_caller','_guarded-child',
            '--night-date',str(night_date),'--input',str(input_file),'--raw-root',str(raw_root),'--log-file',str(log_file)]
        with _termination_signals() as stopped:
            class Cancellation:
                def is_set(self):return stopped.is_set() or bool(cancel_file and cancel_file.exists())
            outcome=supervise(argv,deadline=deadline-cleanup_budget,grace=grace,stop_event=Cancellation(),process_group=True,env=env)
            for line in outcome.stdout.splitlines():
                try:
                    value=json.loads(line)
                    if value.get('event')=='NIGHT_CALLER':result.update(value)
                except (ValueError,AttributeError):pass
            if outcome.returncode not in (0,None):result.update(status='UNRESOLVED',reason='CHILD_EXIT')
            if outcome.terminated:result.update(status='UNRESOLVED',reason='CALLER_TERMINATED',requires_manual_review=True)
            diagnostic.execute('SET statement_timeout=200')
            diagnostic.execute('SET lock_timeout=100')
            pids=[r[0] for r in diagnostic.execute("""SELECT pid FROM pg_stat_activity
                WHERE usename=current_user AND (application_name=%s OR application_name LIKE %s)""",
                ('t154-caller:'+token,'t154-night:'+token+':%'))]
            for pid in pids:diagnostic.execute('SELECT pg_terminate_backend(%s,100)',(pid,))
            remaining=diagnostic.execute("""SELECT count(*) FROM pg_stat_activity WHERE usename=current_user
                AND (application_name=%s OR application_name LIKE %s)""",('t154-caller:'+token,'t154-night:'+token+':%')).fetchone()[0]
            result['whole_caller_cleanup']='PASS' if remaining==0 and time.monotonic()<=deadline else 'NOT_VERIFIED'
            if result['whole_caller_cleanup']!='PASS':result.update(status='UNRESOLVED',requires_manual_review=True)
            result['caller_exit_code']=outcome.returncode
    return _log(Path(log_file).with_name('guard.jsonl'),result)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['once','_guarded-child'])
    p.add_argument('--night-date',type=date.fromisoformat,required=True)
    p.add_argument('--invocation-id');p.add_argument('--input',type=Path,required=True);p.add_argument('--raw-root',type=Path,required=True);p.add_argument('--log-file',type=Path,required=True)
    a=p.parse_args(argv)
    if a.action=='_guarded-child':
        r=call_once(night_date=a.night_date,input_file=a.input,raw_root=a.raw_root,log_file=a.log_file,connector=marked_connection,executor=marked_executor)
    else:
        r=guarded_once(night_date=a.night_date,input_file=a.input,raw_root=a.raw_root,log_file=a.log_file,invocation_id=a.invocation_id)
    print(json.dumps(r));return 0 if r['status'] in ('IDLE','COMPLETED') else 1

if __name__=='__main__':raise SystemExit(main())
