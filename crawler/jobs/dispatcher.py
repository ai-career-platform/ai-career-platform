"""One-shot DB dispatcher/internal inspection CLI. No HTTP admin endpoints."""
import argparse
from datetime import datetime,time,timezone
import json
import os
import signal
import subprocess
import sys
import time as clock
from crawler.storage.staging import connect_configured_database
from crawler.jobs.scheduler import SchedulerStore
from crawler.notifications.slack import notify_run


def stop_worker(process):
    if process.poll() is not None:return
    if os.name=='posix':os.killpg(process.pid,signal.SIGTERM)
    else:process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
        else:process.kill()
        process.wait(timeout=5)


def dispatch(store,*,timeout=120,heartbeat_seconds=10,worker_command=None,manual=False,environ=None,notifier=notify_run):
    """Claim and run at most one job. ``manual`` runs one FIXTURE job now, outside the slot.

    After the final run row is stored, a Slack notice is attempted once (see
    crawler.notifications.slack); its outcome never changes the run or the exit status.
    """
    if not store.lock(0):return {'status':'LOCKED'}
    process=None;run_id=None
    try:
        run_id=store.claim_manual() if manual else store.claim()
        if not run_id:
            if manual:
                return {'status':'REFUSED','reason':store.last_decision,'external_requests':0}
            return {'status':'IDLE' if store.last_decision=='NOT_DUE_OR_DISABLED' else 'BLOCKED',
                    'reason':store.last_decision,'external_requests':0}
        command=worker_command or [sys.executable,'-m','crawler.jobs.scheduled_worker','--run-id',run_id]
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=os.name=='posix')
        deadline=clock.monotonic()+timeout
        while process.poll() is None:
            remaining=deadline-clock.monotonic()
            if remaining<=0:
                stop_worker(process)
                store.finish(run_id,'FAILED',error='WORKER_TIMEOUT')
                break
            try:process.wait(timeout=min(heartbeat_seconds,remaining))
            except subprocess.TimeoutExpired:store.heartbeat(run_id)
        rows=store.read('run',run_id)
        if rows and rows[0]['status']=='RUNNING':store.finish(run_id,'FAILED',error='WORKER_CRASH')
        record=store.read('run',run_id)[0]
        notice=notifier(store,run_id,os.environ if environ is None else environ)
        return {'run_id':run_id,'status':record['status'],'worker_exit':process.returncode,
                'manual':manual,'slack':notice.get('slack'),'slack_http_status':notice.get('http_status')}
    except BaseException:
        if process is not None:stop_worker(process)
        if run_id is not None:
            try:store.finish(run_id,'FAILED',error='WORKER_CRASH')
            except Exception:pass
        raise
    finally:store.unlock(0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('dispatch')
    sub.add_parser('manual-fixture',help='Run exactly one FIXTURE job now (no HTTP, slot unchanged, no auto-retry)')
    sub.add_parser('slack-status',help='Show whether a Slack webhook is configured (never prints it)')
    for name in ('schedules','runs','events','run'):
        p=sub.add_parser(name)
        if name in ('events','run'):p.add_argument('--run-id',required=True)
    p=sub.add_parser('configure')
    p.add_argument('--time',default='03:00')
    p.add_argument('--enabled',action='store_true',help='Internal operator only; never enable staging without PM approval')
    p.add_argument('--mode',choices=['fixture','live'],default='fixture')
    p.add_argument('--policy-file',help='Private JSON containing target_urls and the existing T61 approval record')
    args=parser.parse_args()
    if args.action=='slack-status':
        from crawler.notifications.slack import webhook_config
        print(json.dumps(webhook_config(os.environ)[1]));return 0
    try:
        with connect_configured_database() as connection:
            store=SchedulerStore(connection)
            if args.action=='dispatch':
                result=dispatch(store)
                print(json.dumps(result));return 0 if result['status'] in ('IDLE','LOCKED','SUCCEEDED') else 1
            if args.action=='manual-fixture':
                result=dispatch(store,manual=True)
                print(json.dumps(result));return 0 if result['status']=='SUCCEEDED' else 1
            if args.action=='configure':
                from pathlib import Path
                policy=json.loads(Path(args.policy_file).read_text(encoding='utf-8')) if args.policy_file else {}
                store.configure(enabled=args.enabled,local_time=time.fromisoformat(args.time),mode=args.mode,
                                target_urls=policy.get('target_urls'),approval=policy.get('approval'))
                result={'status':'CONFIGURED','enabled':args.enabled}
            else:result=store.read(args.action,getattr(args,'run_id',None))
            print(json.dumps(result,default=str));return 0
    except Exception:
        print(json.dumps({'status':'FAILED','error_code':'DISPATCHER_UNAVAILABLE'}));return 2


if __name__=='__main__':raise SystemExit(main())
