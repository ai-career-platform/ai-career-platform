"""Verify the isolated local crawler PostgreSQL and the crawler_local role. Prints JSON, never secrets.

Run inside a session prepared by scripts/windows/crawler-local-env.ps1:
    .venv\\Scripts\\python.exe scripts\\windows\\verify_local_db.py            # schema + permission probes
    .venv\\Scripts\\python.exe scripts\\windows\\verify_local_db.py --snapshot # row counts (restart persistence)

Connects only as the runtime role from CRAWLER_LOCAL_DATABASE_URL (loopback, pgpass auth) through the
crawler's own guarded connector. All probe writes are rolled back; nothing is left behind.
"""
import json
import os
import sys

import psycopg

from crawler.storage.postgres import connect_local_training_db

PORT = int(os.environ.get('AICP_PG_PORT') or 5432)


def denied(c, statement):
    try:
        with c.transaction(force_rollback=True):
            c.execute(statement)
        return False
    except psycopg.errors.InsufficientPrivilege:
        return True


def schema_and_permissions():
    out = {}
    with connect_local_training_db(os.environ['CRAWLER_LOCAL_DATABASE_URL']) as c:
        c.autocommit = True
        out['psycopg_impl'] = psycopg.pq.__impl__
        row = c.execute("SELECT current_setting('server_version'), current_database(), current_user, inet_server_addr()::text,"
                        " r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication, r.rolbypassrls"
                        " FROM pg_roles r WHERE r.rolname=current_user").fetchone()
        out.update(server_version=row[0], database=row[1], user=row[2], server_addr=row[3],
                   role_flags=dict(zip(['super', 'createdb', 'createrole', 'replication', 'bypassrls'], row[4:])))
        out['schema_exists'] = c.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='crawler_training')").fetchone()[0]
        out['tables'] = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='crawler_training' ORDER BY 1")]
        out['postings_columns'] = [f'{r[0]} {r[1]}' for r in c.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='crawler_training'"
            " AND table_name='postings' ORDER BY ordinal_position")]
        out['postings_keys'] = [f'{r[0]}: {r[1]}' for r in c.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='crawler_training.postings'::regclass AND contype IN ('p','u')")]
        out['constraints_pk_unique_total'] = c.execute(
            "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='crawler_training' AND contype IN ('p','u')").fetchone()[0]
        out['indexes_total'] = c.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='crawler_training'").fetchone()[0]
        out['run_history_tables'] = [t for t in ('runs', 'run_events', 'night_job_results', 'night_summaries') if t in out['tables']]
        probe = {}
        with c.transaction(force_rollback=True):
            c.execute("INSERT INTO crawler_training.postings(source_code, external_posting_id, payload) VALUES ('local_verify','probe-1','{\"title\":\"a\"}')")
            probe['insert'] = 'OK'
            probe['select_after_insert'] = c.execute("SELECT payload->>'title' FROM crawler_training.postings WHERE source_code='local_verify'").fetchone()[0]
            try:
                with c.transaction():
                    c.execute("INSERT INTO crawler_training.postings(source_code, external_posting_id, payload) VALUES ('local_verify','probe-1','{}')")
                probe['duplicate_key_rejected'] = False
            except psycopg.errors.UniqueViolation:
                probe['duplicate_key_rejected'] = True
            c.execute("UPDATE crawler_training.postings SET payload='{\"title\":\"b\"}' WHERE source_code='local_verify'")
            probe['select_after_update'] = c.execute("SELECT payload->>'title' FROM crawler_training.postings WHERE source_code='local_verify'").fetchone()[0]
        probe['rows_after_rollback'] = c.execute("SELECT count(*) FROM crawler_training.postings WHERE source_code='local_verify'").fetchone()[0]
        out['dml_probe'] = probe
        out['denied'] = {
            'create_table_in_crawler_training': denied(c, 'CREATE TABLE crawler_training.probe_ddl(id int)'),
            'create_table_in_public': denied(c, 'CREATE TABLE public.probe_ddl(id int)'),
            'create_schema': denied(c, 'CREATE SCHEMA probe_schema'),
            'drop_postings': denied(c, 'DROP TABLE crawler_training.postings'),
            'alter_postings': denied(c, 'ALTER TABLE crawler_training.postings ADD COLUMN probe int'),
            'truncate_postings': denied(c, 'TRUNCATE crawler_training.postings'),
            'delete_postings': denied(c, "DELETE FROM crawler_training.postings WHERE source_code='local_verify'"),
            'set_role_crawler_staging': denied(c, 'SET ROLE crawler_staging'),
            'create_role': denied(c, 'CREATE ROLE probe_role'),
        }
    other = {}
    user = os.environ['CRAWLER_LOCAL_DATABASE_URL'].split('//', 1)[1].split('@', 1)[0]
    for db in ('postgres', 'template1'):
        try:
            psycopg.connect(host='127.0.0.1', port=PORT, dbname=db, user=user, connect_timeout=5).close()
            other[db] = 'CONNECTED'
        except psycopg.OperationalError as exc:
            # Server messages may be localized (e.g. Korean); the privilege name CONNECT is not translated.
            other[db] = 'DENIED_NO_CONNECT_PRIVILEGE' if 'CONNECT' in str(exc) else 'ERROR'
    out['other_database_access'] = other
    return out


def snapshot():
    with connect_local_training_db(os.environ['CRAWLER_LOCAL_DATABASE_URL']) as c:
        tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='crawler_training' ORDER BY 1")]
        counts = {t: c.execute(f'SELECT count(*) FROM crawler_training."{t}"').fetchone()[0] for t in tables}
        started = c.execute('SELECT pg_postmaster_start_time()::text').fetchone()[0]
        digest = c.execute("SELECT md5(coalesce(string_agg(source_code||':'||external_posting_id||':'||payload::text, '|' ORDER BY source_code, external_posting_id), ''))"
                           ' FROM crawler_training.postings').fetchone()[0]
    return {'postmaster_started_at': started, 'row_counts': counts, 'postings_md5': digest}


def status():
    """Read-only operational metrics for crawler-status.ps1 (no secrets, no writes)."""
    q = {}
    with connect_local_training_db(os.environ['CRAWLER_LOCAL_DATABASE_URL']) as c:
        c.read_only = True
        cols = ['run_id', 'mode', 'trigger', 'status', 'started_at', 'ended_at', 'fetched_count', 'inserted_count',
                'updated_count', 'duplicate_count', 'failed_count', 'error_code']
        q['recent_runs'] = [dict(zip(cols, r)) for r in c.execute(
            'SELECT run_id::text, mode, trigger, status, started_at::text, ended_at::text, fetched_count, inserted_count,'
            ' updated_count, duplicate_count, failed_count, error_code FROM crawler_training.runs ORDER BY started_at DESC LIMIT 5')]
        row = c.execute("SELECT max(started_at) FILTER (WHERE status='SUCCEEDED')::text, max(started_at) FILTER (WHERE status IN ('FAILED','PARTIAL','CANCELLED'))::text,"
                        " count(*) FILTER (WHERE status='RUNNING'), count(*) FILTER (WHERE mode='live')"
                        ' FROM crawler_training.runs').fetchone()
        q.update(last_success_at=row[0], last_failure_at=row[1], runs_currently_running=row[2], live_runs_total=row[3])
        row = c.execute("SELECT count(*), coalesce(sum(inserted_count),0), coalesce(sum(updated_count),0), coalesce(sum(duplicate_count),0),"
                        " coalesce(sum(failed_count),0), count(*) FILTER (WHERE status<>'SUCCEEDED')"
                        " FROM crawler_training.runs WHERE started_at > now() - interval '24 hours'").fetchone()
        q['last_24h_runs'] = dict(zip(['runs', 'inserted', 'updated', 'duplicates', 'failed', 'not_succeeded'], row))
        q['last_24h_warning_error_events'] = {f'{r[0]}:{r[1]}': r[2] for r in c.execute(
            "SELECT level, event_type, count(*) FROM crawler_training.run_events WHERE level<>'INFO'"
            " AND occurred_at > now() - interval '24 hours' GROUP BY 1, 2 ORDER BY 3 DESC")}
        q['last_7d_night_outcomes'] = {f'{r[0]}:{r[1] or "-"}': r[2] for r in c.execute(
            "SELECT outcome, error_code, count(*) FROM crawler_training.night_job_results"
            " WHERE started_at > now() - interval '7 days' GROUP BY 1, 2 ORDER BY 3 DESC")}
        q['postings_by_source'] = {r[0]: r[1] for r in c.execute(
            'SELECT source_code, count(*) FROM crawler_training.postings GROUP BY 1 ORDER BY 1')}
        q['schedules'] = [{'id': r[0], 'mode': r[1], 'enabled': r[2]} for r in c.execute(
            'SELECT schedule_id, mode, enabled FROM crawler_training.schedules ORDER BY 1')]
        q['database_size_bytes'] = c.execute('SELECT pg_database_size(current_database())').fetchone()[0]
    return q


if __name__ == '__main__':
    if '--status' in sys.argv:
        result = status()
    elif '--snapshot' in sys.argv:
        result = snapshot()
    else:
        result = schema_and_permissions()
    print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
