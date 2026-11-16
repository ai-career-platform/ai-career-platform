"""GOAL_2 rehearsal: build a GCP-like TLS target and a LIVE-shaped local source on a DISPOSABLE cluster.

Used only by scripts/windows/rehearse-gcp-sync.ps1. Refuses port 5432 (this PC's real crawler DB).
Target: database ai_career_poc on the same disposable server, real career schema
(database/migrations 0001-0003), create_career_sync_role.sql + target_grants.sql, data source
'jobkorea_live'. Source: crawler_training on the disposable training DB with
  * one REHEARSAL "live" harvest run (synthetic payloads, http_requests=1) -> the only eligible run,
  * one fixture run and ledger-less 'jobkorea_live' rows as decoys that must never be copied.
The rehearsal "live" run is synthetic: it is NOT evidence of a real collection.

Args: --port N --sync-password-file PATH --rows N. Prints one JSON line (ids, counts); no secrets.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def payload(n):
    return {'source_code': 'jobkorea', 'external_posting_id': str(n),
            'source_url': f'https://www.jobkorea.co.kr/Recruit/GI_Read/{n}', 'title': f'[리허설] 데이터 엔지니어 {n}',
            'company_name': f'리허설회사{n % 97}', 'location_text': '서울', 'employment_type': 'full_time',
            'published_on': '2026-11-10', 'expires_on': '2026-12-31', 'status': 'published'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--sync-password-file', required=True)
    ap.add_argument('--rows', type=int, default=1050)
    args = ap.parse_args()
    if args.port == 5432:
        print(json.dumps({'status': 'REFUSED', 'reason': 'MAIN_CLUSTER_PORT'}))
        return 2
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    password = Path(args.sync_password_file).read_text(encoding='ascii').strip()
    base = dict(host='127.0.0.1', hostaddr='127.0.0.1', port=args.port, connect_timeout=5)
    with psycopg.connect(dbname='postgres', user='postgres', autocommit=True, **base) as admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname='ai_career_poc'").fetchone():
            admin.execute('CREATE DATABASE ai_career_poc')
    with psycopg.connect(dbname='ai_career_poc', user='postgres', autocommit=True, **base) as owner:
        fresh = owner.execute("SELECT to_regnamespace('career') IS NULL").fetchone()[0]
        if fresh:
            owner.execute('CREATE SCHEMA career')
            for name in ('0001_initial_schema.sql', '0002_deletion_request_unscheduled.sql',
                         '0003_market_metric_skill_dimension.sql'):
                owner.execute((ROOT / 'database/migrations' / name).read_text(encoding='utf-8'))
            owner.execute("INSERT INTO career.data_sources (code, name, license_ref, retention_days)"
                          " VALUES ('jobkorea_live', 'JobKorea live', 'REHEARSAL ONLY', 30)")
        owner.execute((ROOT / 'poc/staging/automation/gcp-sync/create_career_sync_role.sql').read_text(encoding='utf-8'))
        owner.execute(sql.SQL('ALTER ROLE career_sync PASSWORD {}').format(sql.Literal(password)))
        owner.execute((ROOT / 'poc/staging/automation/gcp-sync/target_grants.sql').read_text(encoding='utf-8'))
        role = owner.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit"
                             " FROM pg_roles WHERE rolname='career_sync'").fetchone()
    live_run, fixture_run = str(uuid.uuid4()), str(uuid.uuid4())
    first = 4_000_000_000 + uuid.uuid4().int % 1_000_000 * 10_000
    with psycopg.connect(dbname='ai_career_crawler_training', user='crawler_student', autocommit=True, **base) as src:
        with src.transaction():
            src.execute("INSERT INTO crawler_training.harvest_runs (run_id, mode, source_code, status, limits, http_requests,"
                        " ended_at) VALUES (%s, 'live', 'jobkorea_live', 'SUCCEEDED', %s, 1, now() + interval '1 minute'),"
                        " (%s, 'fixture', 'jobkorea_live', 'SUCCEEDED', %s, 0, now() + interval '1 minute')",
                        (live_run, Jsonb({'rehearsal': True}), fixture_run, Jsonb({'rehearsal': True})))
            with src.cursor() as cur:
                cur.executemany('INSERT INTO crawler_training.postings (source_code, external_posting_id, payload)'
                                " VALUES ('jobkorea_live', %s, %s)",
                                [(str(n), Jsonb(payload(n))) for n in range(first, first + args.rows + 7)])
                cur.executemany("INSERT INTO crawler_training.harvest_items (run_id, source_code, external_posting_id,"
                                " keyword, page_no, decision, outcome, checked_at)"
                                " VALUES (%s, 'jobkorea_live', %s, 'REHEARSAL', 1, 'new', 'inserted', now())",
                                [(live_run, str(n)) for n in range(first, first + args.rows)]
                                + [(fixture_run, str(n)) for n in range(first + args.rows, first + args.rows + 4)])
    print(json.dumps({'status': 'READY', 'live_run_id': live_run, 'fixture_run_id': fixture_run,
                      'live_rows': args.rows, 'decoy_fixture_rows': 4, 'decoy_ledgerless_rows': 3,
                      'first_id': first, 'career_sync_flags': list(role)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
