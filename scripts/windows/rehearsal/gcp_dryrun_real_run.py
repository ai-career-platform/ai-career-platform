"""MIGRATION_UNBLOCK rehearsal: plan the real LIVE run against a GCP-like TLS target that already holds a
Staging-written copy of one posting. DISPOSABLE target only (loopback, never port 5432, never Cloud SQL).

Source: this PC's real crawler DB, READ ONLY as crawler_local (connect_local_source), LIVE run id given.
Target: rehearsal ai_career_poc on the disposable cluster (rehearse-gcp-sync.ps1 built it: career schema,
career_sync, TLS 'gcp-sync-rehearsal.local'). The script (re)seeds the target as the PM-reported state:
posting <shared id> already present for 'jobkorea_live' plus one ingestion run of the old Staging code
(error_summary without 'source').

Steps: dry-run (plan: INSERT vs duplicate/update, other writers) -> run without cutover (must refuse,
no write) -> prints one JSON document. Passwords come from the disposable cluster's pgpass / a freshly
generated rehearsal value and are never printed.
"""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-port', type=int, required=True)
    ap.add_argument('--ca', required=True)
    ap.add_argument('--live-run-id', required=True)
    ap.add_argument('--shared-id', default='50350626')
    ap.add_argument('--target-passfile', required=True, help="the disposable cluster's pgpass (postgres entry)")
    args = ap.parse_args()
    if args.target_port == 5432:
        print(json.dumps({'status': 'REFUSED', 'reason': 'MAIN_CLUSTER_PORT'}))
        return 2
    import psycopg
    from psycopg import sql
    from crawler.jobs import gcp_sync as g
    pw = secrets.token_urlsafe(24)
    base = dict(host='127.0.0.1', hostaddr='127.0.0.1', port=args.target_port, user='postgres', connect_timeout=5,
                passfile=args.target_passfile)
    with psycopg.connect(dbname='ai_career_poc', autocommit=True, **base) as owner:
        owner.execute(sql.SQL('ALTER ROLE career_sync PASSWORD {}').format(sql.Literal(pw)))
        # reset the rehearsal target to the reported production shape for this posting
        owner.execute("DELETE FROM career.job_postings p USING career.data_sources s"
                      " WHERE p.source_id = s.source_id AND s.code = 'jobkorea_live'")
        owner.execute("DELETE FROM career.companies c USING career.data_sources s"
                      " WHERE c.source_id = s.source_id AND s.code = 'jobkorea_live'")
        owner.execute("DELETE FROM career.ingestion_runs i USING career.data_sources s"
                      " WHERE i.source_id = s.source_id AND s.code = 'jobkorea_live'")
        sid = owner.execute("SELECT source_id FROM career.data_sources WHERE code = 'jobkorea_live'").fetchone()[0]
        cid = owner.execute("INSERT INTO career.companies (name, source_id) VALUES ('㈜보령', %s) RETURNING company_id",
                            (sid,)).fetchone()[0]
        pid = owner.execute(
            "INSERT INTO career.job_postings (company_id, source_id, title, employment_type, location_text, source_url,"
            " status, published_at, expires_at) VALUES (%s, %s, '[보령] 전사 AX추진 팀원', 'full_time',"
            " '대한민국 서울특별시 종로구 창경궁로 136', %s, 'draft', '2026-11-10 15:00+00', '2026-11-29 15:00+00')"
            " RETURNING job_posting_id",
            (cid, sid, f'https://www.jobkorea.co.kr/Recruit/GI_Read/{args.shared_id}')).fetchone()[0]
        owner.execute("INSERT INTO career.job_posting_external_refs (source_id, external_id, job_posting_id, first_seen_at,"
                      " last_seen_at) VALUES (%s, %s, %s, now() - interval '9 hours', now() - interval '9 hours')",
                      (sid, args.shared_id, pid))
        owner.execute("INSERT INTO career.ingestion_runs (source_id, status, started_at, ended_at, fetched_count, error_summary)"
                      " VALUES (%s, 'succeeded', now() - interval '9 hours', now() - interval '9 hours', 59, %s)",
                      (sid, json.dumps({'mode': 'scheduled', 'source_code': 'jobkorea_live', 'publish': False,
                                        'result': 'SUCCEEDED', 'inserted': 1})))  # old code: no 'source' key
        before = owner.execute("SELECT count(*) FROM career.job_posting_external_refs r JOIN career.data_sources s"
                               " USING (source_id) WHERE s.code = 'jobkorea_live'").fetchone()[0]
    environ = {'GCP_SYNC_TARGET_HOST': 'gcp-sync-rehearsal.local', 'GCP_SYNC_TARGET_HOSTADDR': '127.0.0.1',
               'GCP_SYNC_TARGET_PORT': str(args.target_port), 'GCP_SYNC_TARGET_DB': 'ai_career_poc',
               'GCP_SYNC_TARGET_USER': 'career_sync', 'GCP_SYNC_TARGET_PASSWORD': pw,
               'GCP_SYNC_TARGET_SSLROOTCERT': args.ca}
    out = {'target': f'127.0.0.1:{args.target_port}/ai_career_poc (disposable rehearsal, TLS verify-full)',
           'target_refs_before': before}
    for mode in ('dry-run', 'run'):
        src = g.connect_local_source(os.environ)
        tgt = g.connect_target(environ)
        try:
            r = g.run_sync(src, tgt, mode=mode, live_run_ids=[args.live_run_id])
        finally:
            src.close()
            tgt.close()
        out[mode] = {k: r.get(k) for k in ('status', 'error_code', 'source', 'fetched', 'inserted', 'updated',
                                           'duplicate', 'skipped', 'failed', 'already_in_target', 'other_writers',
                                           'skipped_reasons')}
    with psycopg.connect(dbname='ai_career_poc', autocommit=True, **base) as owner:
        out['target_refs_after'] = owner.execute(
            "SELECT count(*) FROM career.job_posting_external_refs r JOIN career.data_sources s USING (source_id)"
            " WHERE s.code = 'jobkorea_live'").fetchone()[0]
    print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
