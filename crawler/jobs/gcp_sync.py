"""Copy crawled postings to the GCP service database once a day (#337).

One-way and additive: new postings are INSERTed, existing ones get only the fields that
actually changed, identical rows are not written and nothing is ever deleted.

- Source: the existing crawler connection (``connect_configured_database``, validator
  unchanged) inside the Staging backend container, READ ONLY.
- Target: ``career`` schema of ``ai_career_poc`` over TLS ``verify-full`` with a dedicated
  role (no DELETE, no DDL). Identity: ``job_posting_external_refs (source_id, external_id)``.
- Run history: the existing ``career.ingestion_runs`` table (counters in ``error_summary``).

This module never starts a crawl and sends no HTTP request except the optional Slack notice.
Secrets come from the environment only and are never printed; errors are reported as codes.

Usage (inside the backend container)::

    python -m crawler.jobs.gcp_sync dry-run     # plan only, no writes
    python -m crawler.jobs.gcp_sync run         # manual run (worker guard, no time guard)
    python -m crawler.jobs.gcp_sync scheduled   # daily timer: time/worker/once-a-day guards
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from crawler.normalizer import InvalidPosting, normalize

KST = ZoneInfo('Asia/Seoul')
TARGET_DB = 'ai_career_poc'
LOCK_KEY = 337001  # target session advisory lock: one sync at a time
DEFAULT_SOURCE_CODE = 'jobkorea_live'
NIGHT_START, NIGHT_END = dtime(21, 0), dtime(8, 0)  # crawler night window, Asia/Seoul
STALE_AFTER = timedelta(hours=1)
LIMITS = {'external_posting_id': 240, 'title': 240, 'company_name': 200, 'location_text': 120}
COMPARED = ('company_name', 'title', 'employment_type', 'location_text', 'source_url', 'status',
            'published_at', 'expires_at')
RETRY_DELAYS = (60, 120)  # at most 3 attempts, connection/network errors only
REFUSED_USERS = {'postgres', 'cloudsqlsuperuser', 'cloudsqladmin'}


class SyncError(Exception):
    """A failure with a fixed, secret-free code."""

    def __init__(self, code, *, retryable=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


# ---------------------------------------------------------------- mapping and planning
@dataclass(frozen=True)
class SourceRow:
    source_code: str
    external_posting_id: str
    payload: dict
    updated_at: datetime


@dataclass(frozen=True)
class Existing:
    job_posting_id: object
    source_id: object
    values: dict  # COMPARED fields as stored in the target


@dataclass
class Plan:
    inserts: list = field(default_factory=list)   # [(external_id, values, seen_at)]
    updates: list = field(default_factory=list)   # [(Existing, changes, seen_at)]
    duplicate: int = 0
    skipped: list = field(default_factory=list)   # [(external_id, reason)]
    failed: list = field(default_factory=list)    # [(external_id, reason)]

    def counts(self):
        return {'inserted': len(self.inserts), 'updated': len(self.updates), 'duplicate': self.duplicate,
                'skipped': len(self.skipped), 'failed': len(self.failed)}


def _kst_midnight(day):
    return datetime.combine(day, dtime(0), KST).astimezone(timezone.utc)


def map_row(row, *, publish):
    """Validate with the existing crawler normalizer and map to target column values.

    ``published_at`` is None when the source has no publish date; the caller then keeps the
    stored value (update) or uses the first-seen time (insert). ``expires_at`` is the start of
    the day after ``expires_on`` (KST), so a posting stays open through its last day.
    """
    posting = normalize(row.payload)
    if posting.external_posting_id != row.external_posting_id:
        raise InvalidPosting('External id does not match the source key')
    values = {
        'company_name': posting.company_name,
        'title': posting.title,
        'employment_type': posting.employment_type,
        'location_text': posting.location_text,
        'source_url': posting.source_url,
        'status': posting.status if publish else 'draft',
        'published_at': _kst_midnight(date.fromisoformat(posting.published_on)) if posting.published_on else None,
        'expires_at': (_kst_midnight(date.fromisoformat(posting.expires_on) + timedelta(days=1))
                       if posting.expires_on else None),
    }
    probe = dict(values, external_posting_id=row.external_posting_id)
    for key, limit in LIMITS.items():
        if probe[key] is not None and len(probe[key]) > limit:
            raise InvalidPosting(f'Field too long: {key}')
    return values


def _effective_published(values, fallback):
    return values['published_at'] if values['published_at'] is not None else fallback


def plan(rows, *, source_code, source_id, refs, url_owners, publish):
    """Decide INSERT / UPDATE / DUPLICATE / SKIP / FAIL per source row. Pure; no I/O.

    refs: {external_id: Existing} for this data source.
    url_owners: {source_url: [(job_posting_id, source_id), ...]} for every target posting.
    """
    result = Plan()
    batch_urls = set()
    for row in rows:
        key = row.external_posting_id
        if row.source_code != source_code:
            result.skipped.append((key, 'SOURCE_NOT_SELECTED'))
            continue
        try:
            values = map_row(row, publish=publish)
        except InvalidPosting as error:
            result.skipped.append((key, f'INVALID: {error}'))
            continue
        if values['source_url'] in batch_urls:
            result.skipped.append((key, 'DUPLICATE_URL_IN_SOURCE'))
            continue
        batch_urls.add(values['source_url'])
        existing = refs.get(key)
        owners = url_owners.get(values['source_url'], [])
        if existing is None:
            published = _effective_published(values, row.updated_at)
            if values['expires_at'] is not None and values['expires_at'] < published:
                result.skipped.append((key, 'INVALID: Expiry precedes publish time'))
            elif owners:
                result.failed.append((key, 'URL_CONFLICT'))
            else:
                result.inserts.append((key, dict(values, published_at=published), row.updated_at))
            continue
        if existing.source_id != source_id:
            result.failed.append((key, 'SOURCE_CONFLICT'))
            continue
        if any(owner != existing.job_posting_id for owner, _ in owners):
            result.failed.append((key, 'URL_CONFLICT'))
            continue
        desired = dict(values, published_at=_effective_published(values, existing.values['published_at']))
        if desired['expires_at'] is not None and desired['published_at'] is not None \
                and desired['expires_at'] < desired['published_at']:
            result.skipped.append((key, 'INVALID: Expiry precedes publish time'))
            continue
        changes = {k: desired[k] for k in COMPARED if desired[k] != existing.values[k]}
        if changes:
            result.updates.append((existing, changes, row.updated_at))
        else:
            result.duplicate += 1
    return result


# ---------------------------------------------------------------- connections
def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def target_settings(environ):
    """Read and validate target settings. TLS verify-full is fixed in code, not configurable."""
    host = (environ.get('GCP_SYNC_TARGET_HOST') or '').strip()
    hostaddr = (environ.get('GCP_SYNC_TARGET_HOSTADDR') or '').strip()
    user = (environ.get('GCP_SYNC_TARGET_USER') or '').strip()
    password = environ.get('GCP_SYNC_TARGET_PASSWORD') or ''
    dbname = (environ.get('GCP_SYNC_TARGET_DB') or TARGET_DB).strip()
    cert_path = (environ.get('GCP_SYNC_TARGET_SSLROOTCERT') or '').strip()
    cert_pem = environ.get('GCP_SYNC_TARGET_SSLROOTCERT_PEM') or ''
    if not host or _is_ip(host):
        raise SyncError('TARGET_HOST_MUST_BE_CERT_NAME')  # verify-full checks this name
    if not _is_ip(hostaddr):
        raise SyncError('TARGET_HOSTADDR_REQUIRED')
    if dbname != TARGET_DB:
        raise SyncError('TARGET_DB_MISMATCH')
    if not user or user in REFUSED_USERS:
        raise SyncError('TARGET_USER_NOT_ALLOWED')
    if not password:
        raise SyncError('TARGET_PASSWORD_MISSING')
    if not cert_path and '-----BEGIN CERTIFICATE-----' not in cert_pem:
        raise SyncError('TARGET_CA_MISSING')
    try:
        port = int(environ.get('GCP_SYNC_TARGET_PORT') or 5432)
    except ValueError:
        raise SyncError('TARGET_PORT_INVALID') from None
    return {'host': host, 'hostaddr': hostaddr, 'port': port, 'dbname': dbname, 'user': user,
            'password': password, 'sslmode': 'verify-full', 'cert_path': cert_path, 'cert_pem': cert_pem}


def _classify(error, side):
    text = str(error).lower()
    if side == 'TARGET' and any(word in text for word in ('certificate', 'ssl', 'tls')):
        return SyncError('TARGET_TLS_FAILED')  # not retried: configuration problem
    return SyncError(f'{side}_CONNECT_FAILED', retryable=True)


def connect_target(environ, *, connect=None):
    settings = target_settings(environ)
    if connect is None:
        import psycopg
        connect = psycopg.connect
    cert_file = None
    try:
        cert_path = settings['cert_path']
        if not cert_path:
            fd, cert_file = tempfile.mkstemp(prefix='gcp-sync-ca-', suffix='.pem')
            with os.fdopen(fd, 'w', encoding='ascii') as handle:
                handle.write(settings['cert_pem'])
            cert_path = cert_file
        try:
            connection = connect(host=settings['host'], hostaddr=settings['hostaddr'], port=settings['port'],
                                 dbname=settings['dbname'], user=settings['user'], password=settings['password'],
                                 sslmode='verify-full', sslrootcert=cert_path, connect_timeout=10,
                                 application_name='career-gcp-sync')
        except Exception as error:
            raise _classify(error, 'TARGET') from None
    finally:
        if cert_file:
            os.unlink(cert_file)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database(), current_user, '
                           '(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), '
                           '(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)')
            identity = cursor.fetchone()
        connection.commit()
        if identity != (TARGET_DB, settings['user'], True, False):
            raise SyncError('TARGET_IDENTITY_MISMATCH')
        return connection
    except Exception:
        connection.close()
        raise


def connect_source():
    from crawler.storage.staging import connect_configured_database, using_staging
    if not using_staging():
        raise SyncError('SOURCE_NOT_STAGING')
    try:
        connection = connect_configured_database()
    except Exception as error:
        raise _classify(error, 'SOURCE') from None
    connection.read_only = True
    return connection


# ---------------------------------------------------------------- source side
def in_night_window(now):
    local = now.astimezone(KST).time()
    return local >= NIGHT_START or local < NIGHT_END


def read_source(connection):
    """Busy check and posting snapshot in one READ ONLY transaction (no writes to the source)."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute("SELECT (SELECT count(*) FROM crawler_training.runs WHERE status = 'RUNNING'),"
                           " (SELECT count(*) FROM crawler_training.keyword_jobs WHERE status = 'RUNNING'),"
                           " to_regclass('crawler_training.night_job_results') IS NOT NULL")
            runs, jobs, has_night = cursor.fetchone()
            night = 0
            if has_night:
                cursor.execute("SELECT count(*) FROM crawler_training.night_job_results WHERE outcome = 'RUNNING'")
                night = cursor.fetchone()[0]
            busy = {'runs': runs, 'keyword_jobs': jobs, 'night_jobs': night}
            if any(busy.values()):
                return busy, []
            cursor.execute('SELECT source_code, external_posting_id, payload, updated_at'
                           ' FROM crawler_training.postings ORDER BY source_code, external_posting_id')
            rows = [SourceRow(*record) for record in cursor.fetchall()]
    return busy, rows


# ---------------------------------------------------------------- target side
def load_target(cursor, source_code, urls):
    cursor.execute('SELECT source_id FROM career.data_sources WHERE code = %s AND is_active', (source_code,))
    found = cursor.fetchone()
    if found is None:
        raise SyncError('TARGET_SOURCE_MISSING')
    source_id = found[0]
    cursor.execute(
        'SELECT r.external_id, p.job_posting_id, p.source_id, c.name, p.title, p.employment_type,'
        ' p.location_text, p.source_url, p.status, p.published_at, p.expires_at'
        ' FROM career.job_posting_external_refs r'
        ' JOIN career.job_postings p ON p.job_posting_id = r.job_posting_id'
        ' JOIN career.companies c ON c.company_id = p.company_id'
        ' WHERE r.source_id = %s', (source_id,))
    refs = {rec[0]: Existing(rec[1], rec[2], dict(zip(COMPARED, rec[3:]))) for rec in cursor.fetchall()}
    cursor.execute('SELECT source_url, job_posting_id, source_id FROM career.job_postings'
                   ' WHERE source_url = ANY(%s)', (list(urls),))
    owners = {}
    for url, posting_id, owner_source in cursor.fetchall():
        owners.setdefault(url, []).append((posting_id, owner_source))
    cursor.execute('SELECT lower(name), company_id FROM career.companies WHERE source_id = %s'
                   ' ORDER BY created_at, company_id', (source_id,))
    companies = {}
    for name, company_id in cursor.fetchall():
        companies.setdefault(name, company_id)
    return source_id, refs, owners, companies


def apply_plan(cursor, result, *, source_id, companies):
    """Write the plan inside the caller's transaction. Any unexpected state raises (rollback)."""
    created = 0

    def company(name):
        nonlocal created
        key = name.lower()
        if key not in companies:
            cursor.execute('INSERT INTO career.companies (name, source_id) VALUES (%s, %s) RETURNING company_id',
                           (name, source_id))
            companies[key] = cursor.fetchone()[0]
            created += 1
        return companies[key]

    for external_id, values, seen_at in result.inserts:
        cursor.execute(
            'INSERT INTO career.job_postings (company_id, source_id, title, employment_type, location_text,'
            ' source_url, status, published_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)'
            ' RETURNING job_posting_id',
            (company(values['company_name']), source_id, values['title'], values['employment_type'],
             values['location_text'], values['source_url'], values['status'], values['published_at'],
             values['expires_at']))
        posting_id = cursor.fetchone()[0]
        cursor.execute('INSERT INTO career.job_posting_external_refs'
                       ' (source_id, external_id, job_posting_id, first_seen_at, last_seen_at)'
                       ' VALUES (%s, %s, %s, %s, %s)', (source_id, external_id, posting_id, seen_at, seen_at))
    for existing, changes, seen_at in result.updates:
        columns = dict(changes)
        if 'company_name' in columns:
            columns['company_id'] = company(columns.pop('company_name'))
        assignments = ', '.join(f'{name} = %s' for name in columns)  # names come from COMPARED only
        cursor.execute(f'UPDATE career.job_postings SET {assignments}, updated_at = now()'
                       ' WHERE job_posting_id = %s AND source_id = %s',
                       (*columns.values(), existing.job_posting_id, source_id))
        if cursor.rowcount != 1:
            raise SyncError('UPDATE_CONFLICT')
        cursor.execute('UPDATE career.job_posting_external_refs SET last_seen_at = %s'
                       ' WHERE source_id = %s AND job_posting_id = %s', (seen_at, source_id, existing.job_posting_id))
    return created


def _summary(result, extra):
    def tally(items):
        out = {}
        for _, reason in items:
            out[reason] = out.get(reason, 0) + 1
        return out
    return dict(extra, **result.counts(), skipped_reasons=tally(result.skipped),
                failed_items=[f'{k}:{r}' for k, r in result.failed[:20]])


def run_sync(source_connection, target_connection, *, mode, source_code=DEFAULT_SOURCE_CODE,
             publish=False, now=None):
    """One sync. Returns a secret-free result dict; raises SyncError on connection-level failures."""
    now = now or datetime.now(timezone.utc)
    base = {'mode': mode, 'source_code': source_code, 'publish': publish}
    if mode == 'scheduled' and in_night_window(now):
        return dict(base, status='SKIPPED', reason='NIGHT_WINDOW_OPEN')
    busy, rows = read_source(source_connection)
    if any(busy.values()):
        return dict(base, status='SKIPPED', reason='CRAWLER_BUSY', busy=busy)
    target = target_connection
    with target.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
        locked = cursor.fetchone()[0]
    target.commit()
    if not locked:
        return dict(base, status='SKIPPED', reason='SYNC_IN_PROGRESS')
    try:
        return _locked_sync(target, rows, base, now, mode=mode, source_code=source_code, publish=publish)
    finally:
        target.rollback()
        with target.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        target.commit()


def _locked_sync(target, rows, base, now, *, mode, source_code, publish):
    urls = {row.payload.get('source_url') for row in rows
            if row.source_code == source_code and isinstance(row.payload, dict) and row.payload.get('source_url')}
    with target.cursor() as cursor:
        source_id, refs, owners, companies = load_target(cursor, source_code, urls)
        if mode == 'scheduled':
            day_start = datetime.combine(now.astimezone(KST).date(), NIGHT_END, KST)
            cursor.execute("SELECT count(*) FROM career.ingestion_runs WHERE source_id = %s"
                           " AND status = 'succeeded' AND started_at >= %s", (source_id, day_start))
            if cursor.fetchone()[0]:
                target.rollback()
                return dict(base, status='SKIPPED', reason='ALREADY_SYNCED_TODAY')
    result = plan(rows, source_code=source_code, source_id=source_id, refs=refs, url_owners=owners,
                  publish=publish)
    if mode == 'dry-run':
        target.rollback()
        return dict(base, status='DRY_RUN', fetched=len(rows), **_summary(result, {}))
    with target.cursor() as cursor:
        cursor.execute("UPDATE career.ingestion_runs SET status = 'failed', ended_at = now(),"
                       " error_summary = %s WHERE source_id = %s AND status = 'running' AND started_at < %s",
                       (json.dumps({'error_code': 'STALE_RUN'}), source_id, now - STALE_AFTER))
        stale = cursor.rowcount
        cursor.execute("INSERT INTO career.ingestion_runs (source_id, status, fetched_count) VALUES (%s, 'running', %s)"
                       ' RETURNING ingestion_run_id, started_at', (source_id, len(rows)))
        run_id, started_at = cursor.fetchone()
    target.commit()
    try:
        with target.cursor() as cursor:
            created = apply_plan(cursor, result, source_id=source_id, companies=dict(companies))
            status = 'PARTIAL' if result.failed else 'SUCCEEDED'
            summary = _summary(result, dict(base, result=status, companies_created=created, stale_runs_closed=stale))
            cursor.execute('UPDATE career.ingestion_runs SET status = %s, ended_at = now(), error_summary = %s'
                           ' WHERE ingestion_run_id = %s RETURNING ended_at',
                           ('failed' if result.failed else 'succeeded', json.dumps(summary), run_id))
            ended_at = cursor.fetchone()[0]
        target.commit()
    except Exception as error:
        target.rollback()
        code = error.code if isinstance(error, SyncError) else f'APPLY_{type(error).__name__}'
        with target.cursor() as cursor:
            cursor.execute("UPDATE career.ingestion_runs SET status = 'failed', ended_at = now(), error_summary = %s"
                           ' WHERE ingestion_run_id = %s', (json.dumps(dict(base, error_code=code)), run_id))
        target.commit()
        return dict(base, status='FAILED', error_code=code, run_id=str(run_id), fetched=len(rows))
    return dict(summary, status=status, run_id=str(run_id), fetched=len(rows),
                started_at=started_at.isoformat(), ended_at=ended_at.isoformat())


# ---------------------------------------------------------------- CLI
def _notify(result, environ):
    from crawler.notifications.slack import send, webhook_config
    url, config = webhook_config(environ)
    if url is None:
        return {'slack': 'DISABLED', 'reason': config['reason']}
    icon = {'SUCCEEDED': ':white_check_mark:', 'PARTIAL': ':warning:'}.get(result['status'], ':x:')
    lines = [f"{icon} *AI Career Platform GCP posting sync {result['status']}* (Staging → Cloud SQL)"]
    if 'run_id' in result:
        lines.append(f"Run ID: `{result['run_id']}`")
    if 'inserted' in result:
        lines.append(f"Fetched {result.get('fetched', 0)} · Inserted {result['inserted']} · Updated {result['updated']}"
                     f" · Duplicate/unchanged {result['duplicate']} · Skipped {result['skipped']}"
                     f" · Failed {result['failed']}")
    if result.get('error_code'):
        lines.append(f"Error code: `{result['error_code']}`")
    accepted, http_status, _ = send(url, {'text': '\n'.join(lines)})
    return {'slack': 'SENT' if accepted else 'FAILED', 'http_status': http_status}


def execute(mode, environ, *, connect_src=connect_source, connect_tgt=connect_target, sleep=time.sleep):
    source_code = (environ.get('GCP_SYNC_SOURCE_CODE') or DEFAULT_SOURCE_CODE).strip()
    publish = environ.get('GCP_SYNC_PUBLISH') == '1'
    attempts = len(RETRY_DELAYS) + 1 if mode == 'scheduled' else 1
    for attempt in range(1, attempts + 1):
        source = target = None
        try:
            source = connect_src()
            target = connect_tgt(environ)
            result = run_sync(source, target, mode=mode, source_code=source_code, publish=publish)
        except SyncError as error:
            result = {'mode': mode, 'status': 'FAILED', 'error_code': error.code}
            if error.retryable and attempt < attempts:
                sleep(RETRY_DELAYS[attempt - 1])
                continue
        except Exception as error:  # network drop mid-run: transaction already rolled back
            import psycopg
            retryable = isinstance(error, psycopg.OperationalError)
            result = {'mode': mode, 'status': 'FAILED', 'error_code': f'RUN_{type(error).__name__}'}
            if retryable and attempt < attempts:
                sleep(RETRY_DELAYS[attempt - 1])
                continue
        finally:
            for connection in (source, target):
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
        break
    result['attempts'] = attempt
    if mode == 'scheduled' and result['status'] in ('SUCCEEDED', 'PARTIAL', 'FAILED'):
        result.update(_notify(result, environ))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['dry-run', 'run', 'scheduled'])
    args = parser.parse_args(argv)
    result = execute(args.mode, os.environ)
    print(json.dumps(result, default=str, ensure_ascii=False))
    return 0 if result['status'] in ('SUCCEEDED', 'SKIPPED', 'DRY_RUN') else 1


if __name__ == '__main__':
    raise SystemExit(main())
