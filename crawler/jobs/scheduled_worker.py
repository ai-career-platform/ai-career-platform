"""Independent T64 batch worker. No external requests in fixture mode."""
import argparse
import json
from datetime import datetime,timezone
from uuid import UUID
from crawler.storage.staging import connect_configured_database
from crawler.storage.postgres import PostgresPostingStore
from crawler.jobs.scheduler import SchedulerStore,eligible
from crawler.jobs.run_crawler import run,DEFAULT_FIXTURE
from crawler.jobs.import_jobkorea_html import fetch_pages,import_pages


def failure_code(report):
    errors=[report['stopped']] if report.get('stopped') else report.get('errors',[])
    for error in errors:
        if error.get('http_status') in (401,403):return 'ACCESS_FORBIDDEN'
        if error.get('http_status')==429:return 'RATE_LIMITED'
        if error.get('reason') in ('ROBOTS_DISALLOW','ACCESS_CHALLENGE','INVALID_ROBOTS_RESPONSE'):
            return 'ACCESS_FORBIDDEN'
        if error.get('reason')=='TIMEOUT':return 'WORKER_TIMEOUT'
        if error.get('reason')=='NETWORK_ERROR' or (error.get('http_status') or 0)>=500:return 'TEMPORARY_IO'
    return 'INVALID_CONTRACT'


def execute(run_id):
    with connect_configured_database() as connection:
        store=SchedulerStore(connection)
        if not store.lock(1):
            # This process does not own the source; it must not mutate the
            # legitimate owner's run, even when passed the same run_id.
            return 1
        try:
            rows=store.read('run',run_id)
            if not rows or rows[0]['status']!='RUNNING':return 1
            record=rows[0];schedule=store.schedule(record['schedule_id'])
            allowed,_=eligible(schedule,datetime.now(timezone.utc))
            if not allowed or schedule['mode']!=record['mode']:
                store.finish(run_id,'CANCELLED')
                return 1
            store.event(run_id,'WORKER_STARTED')
            repository=PostgresPostingStore(connection)
            if record['mode']=='fixture':
                report=run(source_id='jobkorea',run_id=str(run_id),fixture=DEFAULT_FIXTURE,store=repository)
            else:
                fetched=0
                def counted_pages():
                    nonlocal fetched
                    for url,html in fetch_pages(schedule['target_urls'],limit=5):
                        if isinstance(html,str):fetched+=1
                        yield url,html
                report=import_pages(counted_pages(),repository,live=True)
                report['fetched']=fetched
            metrics={key:report.get(key,0) for key in ('fetched','inserted','updated','unchanged','duplicates','invalid')}
            if report.get('stopped'):
                metrics['invalid']+=1
            successful=metrics['inserted']+metrics['updated']+metrics['unchanged']
            status='FAILED' if report.get('stopped') or metrics['invalid'] and not successful else 'PARTIAL' if metrics['invalid'] else 'SUCCEEDED'
            error=failure_code(report) if status=='FAILED' else None
            if not store.finish(run_id,status,metrics=metrics,error=error):return 1
            print(json.dumps({'run_id':str(run_id),'status':status,'mode':record['mode'],'counters':metrics,'error_code':error}))
            return 0 if status=='SUCCEEDED' else 1
        except Exception:
            # Connection failures may prevent finishing; dispatcher/lease recovery
            # records the failure later. Never log credentials or raw exceptions.
            try:store.finish(run_id,'FAILED',error='WORKER_CRASH')
            except Exception:pass
            return 1
        finally:
            try:store.unlock(1)
            except Exception:pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',type=UUID,required=True)
    args=parser.parse_args()
    try:return execute(args.run_id)
    except Exception:
        print(json.dumps({'status':'FAILED','error_code':'DATABASE_UNAVAILABLE'}));return 2


if __name__=='__main__':raise SystemExit(main())
