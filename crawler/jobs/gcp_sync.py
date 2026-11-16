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

Local Windows source (GOAL_2, one-shot only)::

    GCP_SYNC_SOURCE=local python -m crawler.jobs.gcp_sync dry-run --live-run-id <harvest run id>
    GCP_SYNC_SOURCE=local python -m crawler.jobs.gcp_sync run     --live-run-id <harvest run id>
    GCP_SYNC_SOURCE=local python -m crawler.jobs.gcp_sync verify  --live-run-id <harvest run id>

The local source is the loopback ``crawler_local`` connection (``CRAWLER_LOCAL_DATABASE_URL``,
validated by ``validate_local_dsn``), READ ONLY. Only postings written by the named LIVE harvest
runs are selected (``crawler_training.harvest_items``, run ``mode='live'`` with real HTTP requests),
so fixture rows and rows written by mocked-HTTP tests can never be copied. ``scheduled`` is refused.
``verify`` is read-only on both sides and compares every selected source row with the target.
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
SKIPPED_ITEMS_LIMIT = 50  # per-record skip evidence kept in ingestion_runs.error_summary
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
    # MIGRATION_UNBLOCK: False when the row's origin is not proven (Staging source without a
    # gate-approved night job behind it). plan() skips such rows as PROVENANCE_UNVERIFIED.
    provenance_ok: bool = True


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
    skipped_sources: dict = field(default_factory=dict)  # {reason: {source_code: n}} (#369)
    selected_changed: int = 0  # selected rows whose source updated_at is after the previous sync (#366)

    def skip(self, row, reason):
        self.skipped.append((row.external_posting_id, reason))
        by_source = self.skipped_sources.setdefault(reason, {})
        by_source[row.source_code] = by_source.get(row.source_code, 0) + 1

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


def plan(rows, *, source_code, source_id, refs, url_owners, publish, last_synced_at=None):
    """Decide INSERT / UPDATE / DUPLICATE / SKIP / FAIL per source row. Pure; no I/O.

    refs: {external_id: Existing} for this data source.
    url_owners: {source_url: [(job_posting_id, source_id), ...]} for every target posting.
    last_synced_at: start of the previous successful sync; only used to count source changes.
    """
    result = Plan()
    batch_urls = set()
    for row in rows:
        key = row.external_posting_id
        if row.source_code != source_code:
            result.skip(row, 'SOURCE_NOT_SELECTED')
            continue
        if not row.provenance_ok:
            result.skip(row, 'PROVENANCE_UNVERIFIED')
            continue
        if last_synced_at is None or row.updated_at > last_synced_at:
            result.selected_changed += 1
        try:
            values = map_row(row, publish=publish)
        except InvalidPosting as error:
            result.skip(row, f'INVALID: {error}')
            continue
        if values['source_url'] in batch_urls:
            result.skip(row, 'DUPLICATE_URL_IN_SOURCE')
            continue
        batch_urls.add(values['source_url'])
        existing = refs.get(key)
        owners = url_owners.get(values['source_url'], [])
        if existing is None:
            published = _effective_published(values, row.updated_at)
            if values['expires_at'] is not None and values['expires_at'] < published:
                result.skip(row, 'INVALID: Expiry precedes publish time')
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
            result.skip(row, 'INVALID: Expiry precedes publish time')
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


def source_kind(environ):
    kind = (environ.get('GCP_SYNC_SOURCE') or 'staging').strip()
    if kind not in ('staging', 'local'):
        raise SyncError('SOURCE_KIND_INVALID')
    return kind


def connect_local_source(environ):
    """Loopback crawler_local connection (validate_local_dsn), READ ONLY."""
    from crawler.storage.postgres import connect_local_training_db
    from crawler.storage.staging import using_staging
    if using_staging():
        raise SyncError('SOURCE_NOT_LOCAL')
    try:
        connection = connect_local_training_db(environ.get('CRAWLER_LOCAL_DATABASE_URL', ''))
    except Exception as error:
        raise _classify(error, 'SOURCE') from None
    connection.read_only = True
    return connection


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


LIVE_RUN_FINISHED = ('SUCCEEDED', 'PARTIAL', 'STOPPED')
LIVE_ITEM_OUTCOMES = ['inserted', 'updated', 'unchanged']


def _parse_run_ids(values):
    import uuid
    ids = []
    for value in values or ():
        for part in str(value).split(','):
            if part.strip():
                try:
                    ids.append(str(uuid.UUID(part.strip())))
                except ValueError:
                    raise SyncError('LIVE_RUN_ID_INVALID') from None
    return sorted(set(ids))


# Staging source provenance (MIGRATION_UNBLOCK). A row is proven when a discovery of it (first or last
# seen) falls inside a finished night job with real HTTP requests whose start lies inside its own night
# (21:00 KST night_date .. 08:00 KST next day), and the stored payload was last written no later than
# that job ended (a later overwrite, e.g. a test or a CLI import reusing the id, is not proven). Night jobs are created only after live_gate() returned
# ALLOWED for a valid T61 approval (night_crawl.run_night_step), so such a job is code-level evidence
# that the fetch was approved. Rows without it (e.g. the 2026-11-08 CLI imports, clock-injected test
# jobs) are skipped as PROVENANCE_UNVERIFIED instead of blocking the whole sync.
STAGING_PROVENANCE_SQL = """
SELECT p.source_code, p.external_posting_id, p.payload, p.updated_at,
       EXISTS (
         SELECT 1 FROM crawler_training.keyword_posting_discoveries d
           JOIN crawler_training.night_job_results r ON r.keyword_id = d.keyword_id
          WHERE d.source_code = p.source_code AND d.external_posting_id = p.external_posting_id
            AND r.http_requests > 0 AND r.outcome IN ('SUCCEEDED', 'PARTIAL')
            AND r.started_at >= (r.night_date + time '21:00') AT TIME ZONE 'Asia/Seoul'
            AND r.started_at < (r.night_date + 1 + time '08:00') AT TIME ZONE 'Asia/Seoul'
            AND (d.first_seen_at BETWEEN r.started_at - interval '1 minute'
                                     AND coalesce(r.ended_at, r.started_at + interval '15 minutes') + interval '1 minute'
                 OR d.last_seen_at BETWEEN r.started_at - interval '1 minute'
                                       AND coalesce(r.ended_at, r.started_at + interval '15 minutes') + interval '1 minute')
            -- the stored payload is the one that job fetched or confirmed: nothing wrote it afterwards
            AND p.updated_at <= coalesce(r.ended_at, r.started_at + interval '15 minutes') + interval '1 minute'
       ) AS provenance_ok
  FROM crawler_training.postings p ORDER BY p.source_code, p.external_posting_id"""


def read_source(connection, live_run_ids=None, source_code=DEFAULT_SOURCE_CODE, require_provenance=False):
    """Busy check and posting snapshot in one READ ONLY transaction (no writes to the source).

    ``require_provenance`` (Staging source via ``execute``): every row carries ``provenance_ok``
    (STAGING_PROVENANCE_SQL); unproven rows are skipped by plan(), proven ones sync as before.

    ``live_run_ids`` (local source): only postings written or re-checked by those LIVE harvest
    runs. Every run must exist, be finished, be ``mode='live'`` for ``source_code`` and have made
    real HTTP requests; otherwise nothing is selected (``LIVE_RUN_NOT_ELIGIBLE``).
    """
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute("SELECT (SELECT count(*) FROM crawler_training.runs WHERE status = 'RUNNING'),"
                           " (SELECT count(*) FROM crawler_training.keyword_jobs WHERE status = 'RUNNING'),"
                           " to_regclass('crawler_training.night_job_results') IS NOT NULL,"
                           " to_regclass('crawler_training.harvest_runs') IS NOT NULL")
            runs, jobs, has_night, has_harvest = cursor.fetchone()
            night = harvest = 0
            if has_night:
                cursor.execute("SELECT count(*) FROM crawler_training.night_job_results WHERE outcome = 'RUNNING'")
                night = cursor.fetchone()[0]
            if has_harvest:
                cursor.execute("SELECT count(*) FROM crawler_training.harvest_runs WHERE status = 'RUNNING'")
                harvest = cursor.fetchone()[0]
            busy = {'runs': runs, 'keyword_jobs': jobs, 'night_jobs': night}
            if has_harvest:
                busy['harvest_runs'] = harvest
            if any(busy.values()):
                return busy, []
            if live_run_ids is None and require_provenance:
                cursor.execute("SELECT to_regclass('crawler_training.keyword_posting_discoveries') IS NOT NULL")
                if not (has_night and cursor.fetchone()[0]):
                    cursor.execute('SELECT source_code, external_posting_id, payload, updated_at, false'
                                   ' FROM crawler_training.postings ORDER BY source_code, external_posting_id')
                else:
                    cursor.execute(STAGING_PROVENANCE_SQL)
                return busy, [SourceRow(*record) for record in cursor.fetchall()]
            if live_run_ids is None:
                cursor.execute('SELECT source_code, external_posting_id, payload, updated_at'
                               ' FROM crawler_training.postings ORDER BY source_code, external_posting_id')
                return busy, [SourceRow(*record) for record in cursor.fetchall()]
            if not live_run_ids:
                raise SyncError('LIVE_RUN_ID_REQUIRED')
            if not has_harvest:
                raise SyncError('LIVE_RUN_NOT_ELIGIBLE')
            cursor.execute('SELECT count(*) FROM crawler_training.harvest_runs WHERE run_id = ANY(%s::uuid[])'
                           " AND mode = 'live' AND source_code = %s AND status = ANY(%s) AND http_requests > 0",
                           (list(live_run_ids), source_code, list(LIVE_RUN_FINISHED)))
            if cursor.fetchone()[0] != len(live_run_ids):
                raise SyncError('LIVE_RUN_NOT_ELIGIBLE')
            cursor.execute('SELECT p.source_code, p.external_posting_id, p.payload, p.updated_at'
                           ' FROM crawler_training.postings p WHERE p.source_code = %s AND EXISTS ('
                           ' SELECT 1 FROM crawler_training.harvest_items i'
                           ' JOIN crawler_training.harvest_runs r ON r.run_id = i.run_id'
                           ' WHERE i.run_id = ANY(%s::uuid[]) AND i.source_code = p.source_code'
                           ' AND i.external_posting_id = p.external_posting_id AND i.outcome = ANY(%s)'
                           # a later write (e.g. a mocked-HTTP test reusing the id) is not this run's data
                           ' AND p.updated_at <= r.ended_at)'
                           ' ORDER BY p.external_posting_id',
                           (source_code, list(live_run_ids), LIVE_ITEM_OUTCOMES))
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
    # SOURCE_NOT_SELECTED is fully explained by its source_code tally; every other skip is listed
    # per record so each one can be traced from the run row (#369).
    items = [f'{k}:{r}' for k, r in result.skipped if r != 'SOURCE_NOT_SELECTED']
    return dict(extra, **result.counts(), skipped_reasons=tally(result.skipped),
                skipped_by_source=result.skipped_sources, skipped_items=items[:SKIPPED_ITEMS_LIMIT],
                skipped_items_truncated=len(items) > SKIPPED_ITEMS_LIMIT,
                source_changed_since_last_sync=result.selected_changed,
                failed_items=[f'{k}:{r}' for k, r in result.failed[:20]])


def verify_target(cursor, rows, *, source_code, publish):
    """Read-only comparison of every selected source row with its target posting."""
    source_id, refs, _, _ = load_target(cursor, source_code, ())
    matched, missing, mismatched = 0, [], []
    for row in rows:
        try:
            values = map_row(row, publish=publish)
        except InvalidPosting:
            continue
        existing = refs.get(row.external_posting_id)
        if existing is None:
            missing.append(row.external_posting_id)
            continue
        desired = dict(values, published_at=values['published_at'] or existing.values['published_at'])
        diff = sorted(k for k in COMPARED if desired[k] != existing.values[k])
        if diff:
            mismatched.append(f"{row.external_posting_id}:{'|'.join(diff)}")
        else:
            matched += 1
    return {'source_rows': len(rows), 'target_matched': matched, 'target_missing': len(missing),
            'target_mismatched': len(mismatched), 'missing_items': missing[:20], 'mismatched_items': mismatched[:20],
            'source_target_match': bool(rows) and matched == len(rows)}


def _summary_obj(summary):
    """error_summary is a text column: a JSON object, legacy text, NULL or malformed. Never raises."""
    try:
        value = json.loads(summary) if summary else None
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def other_writers(cursor, source_id, writer, now):
    """Other sync writers of this data source that have not been retired by a cutover (single writer).

    Every run of any status counts (a PARTIAL run is stored as 'failed' but has written rows). Each run
    records its writer in error_summary['source'] ('local'/'staging') from the moment its row is
    inserted; rows of the older deployed code carry no such key and count as 'staging'. A writer is
    retired once this writer completed a cutover-confirmed run after that writer's last run. A 'running'
    row older than STALE_AFTER is a crashed run: it still marks activity but not a sync in progress.
    """
    cursor.execute('SELECT error_summary, status, started_at FROM career.ingestion_runs WHERE source_id = %s',
                   (source_id,))
    seen, my_cutover = {}, None
    for summary, status, started in cursor.fetchall():
        obj = _summary_obj(summary)
        who = obj.get('source') if isinstance(obj.get('source'), str) else 'staging'
        if who == writer:
            cut = obj.get('cutover')
            if status == 'succeeded' and isinstance(cut, dict) and cut.get('confirmed') is True:
                my_cutover = started if my_cutover is None else max(my_cutover, started)
            continue
        entry = seen.setdefault(who, {'last_run_at': started, 'running': False})
        entry['last_run_at'] = max(entry['last_run_at'], started)
        entry['running'] = entry['running'] or (status == 'running' and started > now - STALE_AFTER)
    return {k: {'last_run_at': v['last_run_at'].isoformat(), 'running': v['running']} for k, v in seen.items()
            if my_cutover is None or v['last_run_at'] >= my_cutover}


# A confirmed cutover is accepted only when the other writer has been quiet for longer than its daily
# schedule (08:05 KST cron + margin): GCP_SYNC_CUTOVER_CONFIRMED=1 alone does not prove the cron stopped.
CUTOVER_QUIET = timedelta(hours=26)


def cutover_refusal(others, now, *, confirmed, evidence):
    """None when a second writer may proceed, else the refusal code (checked in this order)."""
    if not confirmed:
        return 'OTHER_SYNC_SOURCE_ACTIVE'
    if any(o['running'] for o in others.values()):
        return 'OTHER_SYNC_RUNNING'
    if any(now - datetime.fromisoformat(o['last_run_at']) < CUTOVER_QUIET for o in others.values()):
        return 'OTHER_SYNC_RECENT'
    if not evidence:
        return 'CUTOVER_EVIDENCE_REQUIRED'
    return None


def check_accounting(fetched, result):
    """fetched = inserted + updated + duplicate + skipped + failed; every row in exactly one bucket."""
    counts = result.counts()
    return fetched == sum(counts.values())


def run_sync(source_connection, target_connection, *, mode, source_code=DEFAULT_SOURCE_CODE,
             publish=False, now=None, live_run_ids=None, require_provenance=False, cutover_confirmed=False,
             cutover_evidence=None):
    """One sync. Returns a secret-free result dict; raises SyncError on connection-level failures."""
    now = now or datetime.now(timezone.utc)
    base = {'mode': mode, 'source_code': source_code, 'publish': publish,
            'source': 'local' if live_run_ids is not None else 'staging'}
    if live_run_ids is not None:
        base['live_run_ids'] = list(live_run_ids)
        if mode == 'scheduled':
            return dict(base, status='FAILED', error_code='LOCAL_SOURCE_ONE_SHOT_ONLY')
    elif require_provenance:
        base['provenance'] = 'night_job_required'
    if mode == 'scheduled' and in_night_window(now):
        return dict(base, status='SKIPPED', reason='NIGHT_WINDOW_OPEN')
    busy, rows = read_source(source_connection, live_run_ids, source_code) if live_run_ids is not None \
        else read_source(source_connection, require_provenance=require_provenance)
    if any(busy.values()):
        return dict(base, status='SKIPPED', reason='CRAWLER_BUSY', busy=busy)
    target = target_connection
    if mode == 'verify':
        try:
            with target.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                return dict(base, status='VERIFIED', **verify_target(cursor, rows, source_code=source_code,
                                                                      publish=publish))
        finally:
            target.rollback()
    with target.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
        locked = cursor.fetchone()[0]
    target.commit()
    if not locked:
        return dict(base, status='SKIPPED', reason='SYNC_IN_PROGRESS')
    try:
        return _locked_sync(target, rows, base, now, mode=mode, source_code=source_code, publish=publish,
                            cutover_confirmed=cutover_confirmed, cutover_evidence=cutover_evidence)
    finally:
        target.rollback()
        with target.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        target.commit()


def _locked_sync(target, rows, base, now, *, mode, source_code, publish, cutover_confirmed=False,
                 cutover_evidence=None):
    urls = {row.payload.get('source_url') for row in rows
            if row.source_code == source_code and isinstance(row.payload, dict) and row.payload.get('source_url')}
    with target.cursor() as cursor:
        source_id, refs, owners, companies = load_target(cursor, source_code, urls)
        others = other_writers(cursor, source_id, base['source'], now)
        if others:
            base = dict(base, other_writers=others)
            # Single writer: a run from a second source refuses until the PM confirms the cutover AND the
            # other writer is provably idle (nothing running, no run for CUTOVER_QUIET) AND an evidence
            # reference is given. dry-run and verify only report it.
            if mode in ('run', 'scheduled'):
                code = cutover_refusal(others, now, confirmed=cutover_confirmed, evidence=cutover_evidence)
                if code:
                    target.rollback()
                    return dict(base, status='SKIPPED' if mode == 'scheduled' else 'FAILED',
                                **({'reason': code} if mode == 'scheduled' else {'error_code': code}))
                base = dict(base, cutover={'confirmed': True, 'evidence': cutover_evidence})
        base = dict(base, already_in_target=sum(1 for r in rows if r.source_code == source_code
                                                and r.external_posting_id in refs))
        if mode == 'scheduled':
            day_start = datetime.combine(now.astimezone(KST).date(), NIGHT_END, KST)
            cursor.execute("SELECT count(*) FROM career.ingestion_runs WHERE source_id = %s"
                           " AND status = 'succeeded' AND started_at >= %s", (source_id, day_start))
            if cursor.fetchone()[0]:
                target.rollback()
                return dict(base, status='SKIPPED', reason='ALREADY_SYNCED_TODAY')
    with target.cursor() as cursor:
        cursor.execute("SELECT max(started_at) FROM career.ingestion_runs WHERE source_id = %s"
                       " AND status = 'succeeded'", (source_id,))
        last_synced_at = cursor.fetchone()[0]
    result = plan(rows, source_code=source_code, source_id=source_id, refs=refs, url_owners=owners,
                  publish=publish, last_synced_at=last_synced_at)
    if not check_accounting(len(rows), result):
        target.rollback()
        return dict(base, status='FAILED', error_code='COUNT_MISMATCH', fetched=len(rows), **result.counts())
    if mode == 'dry-run':
        target.rollback()
        return dict(base, status='DRY_RUN', fetched=len(rows), **_summary(result, {}))
    with target.cursor() as cursor:
        # close crashed runs, keeping their writer marker (the single-writer rule still sees them)
        cursor.execute("SELECT ingestion_run_id, error_summary FROM career.ingestion_runs WHERE source_id = %s"
                       " AND status = 'running' AND started_at < %s", (source_id, now - STALE_AFTER))
        crashed = cursor.fetchall()
        for crashed_id, crashed_summary in crashed:
            cursor.execute("UPDATE career.ingestion_runs SET status = 'failed', ended_at = now(), error_summary = %s"
                           " WHERE ingestion_run_id = %s AND status = 'running'",
                           (json.dumps(dict(_summary_obj(crashed_summary), error_code='STALE_RUN')), crashed_id))
        stale = len(crashed)
        # the writer marker is stored from the first moment, so a run killed now is still attributed
        cursor.execute("INSERT INTO career.ingestion_runs (source_id, status, fetched_count, error_summary)"
                       " VALUES (%s, 'running', %s, %s) RETURNING ingestion_run_id, started_at",
                       (source_id, len(rows), json.dumps({'source': base['source'], 'mode': mode})))
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
    extra = {}
    if 'live_run_ids' in base:  # local one-shot: evidence for a run-scoped rollback
        extra['inserted_external_ids'] = [external_id for external_id, _, _ in result.inserts]
    return dict(summary, status=status, run_id=str(run_id), fetched=len(rows),
                started_at=started_at.isoformat(), ended_at=ended_at.isoformat(), **extra)


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
        # Sync-stage counts only: this run copies existing crawler rows, it does not crawl (#366).
        lines.append(f"Source rows read {result.get('fetched', 0)} (all source codes) · selected `{result['source_code']}`"
                     f" changed since last sync {result.get('source_changed_since_last_sync', 'n/a')}")
        lines.append(f"Target: Inserted {result['inserted']} · Updated {result['updated']}"
                     f" · Unchanged (already synced) {result['duplicate']} · Skipped {result['skipped']}"
                     f" · Failed {result['failed']}")
        for reason, by_source in sorted((result.get('skipped_by_source') or {}).items()):
            detail = ', '.join(f'{code} {n}' for code, n in sorted(by_source.items()))
            lines.append(f"Skipped `{reason}`: {detail}")
    if result.get('error_code'):
        lines.append(f"Error code: `{result['error_code']}`")
    if result.get('reason'):
        lines.append(f"Reason: `{result['reason']}`")
    accepted, http_status, _ = send(url, {'text': '\n'.join(lines)})
    return {'slack': 'SENT' if accepted else 'FAILED', 'http_status': http_status}


def execute(mode, environ, *, connect_src=None, connect_tgt=connect_target, sleep=time.sleep, live_run_ids=None):
    source_code = (environ.get('GCP_SYNC_SOURCE_CODE') or DEFAULT_SOURCE_CODE).strip()
    publish = environ.get('GCP_SYNC_PUBLISH') == '1'
    try:
        local = source_kind(environ) == 'local'
        run_ids = _parse_run_ids(live_run_ids) if local else None
        if local and not run_ids:
            raise SyncError('LIVE_RUN_ID_REQUIRED')
        if local and mode == 'scheduled':
            raise SyncError('LOCAL_SOURCE_ONE_SHOT_ONLY')
        if not local and (mode == 'verify' or live_run_ids):
            raise SyncError('LIVE_RUN_ID_NEEDS_LOCAL_SOURCE')
        # MIGRATION_UNBLOCK (replaces the earlier blanket SOURCE_PROVENANCE_REQUIRED refusal, which also
        # blocked approved rows): the Staging source now syncs only rows proven by a gate-approved night
        # job (STAGING_PROVENANCE_SQL); every other row is skipped as PROVENANCE_UNVERIFIED.
    except SyncError as error:
        return {'mode': mode, 'status': 'FAILED', 'error_code': error.code, 'attempts': 0}
    if connect_src is None:
        connect_src = (lambda: connect_local_source(environ)) if local else connect_source
    attempts = len(RETRY_DELAYS) + 1 if mode == 'scheduled' else 1
    for attempt in range(1, attempts + 1):
        source = target = None
        try:
            source = connect_src()
            target = connect_tgt(environ)
            result = run_sync(source, target, mode=mode, source_code=source_code, publish=publish,
                              live_run_ids=run_ids, require_provenance=not local,
                              cutover_confirmed=environ.get('GCP_SYNC_CUTOVER_CONFIRMED') == '1',
                              cutover_evidence=(environ.get('GCP_SYNC_CUTOVER_EVIDENCE') or '').strip()[:200] or None)
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
    # a scheduled run stopped by the single-writer rule is reported too, so a halted sync is never silent
    refused = result['status'] == 'SKIPPED' and str(result.get('reason', '')).startswith(('OTHER_SYNC', 'CUTOVER'))
    if mode == 'scheduled' and (result['status'] in ('SUCCEEDED', 'PARTIAL', 'FAILED') or refused):
        notice = _notify(result, environ)  # never overwrite the run's own 'reason'
        result.update({('slack_reason' if k == 'reason' else k): v for k, v in notice.items()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['dry-run', 'run', 'scheduled', 'verify'])
    parser.add_argument('--live-run-id', action='append',
                        help='GCP_SYNC_SOURCE=local only: LIVE harvest run whose postings are copied (repeatable)')
    args = parser.parse_args(argv)
    result = execute(args.mode, os.environ, live_run_ids=args.live_run_id)
    print(json.dumps(result, default=str, ensure_ascii=False))
    if args.mode == 'verify':
        return 0 if result.get('source_target_match') else 1
    return 0 if result['status'] in ('SUCCEEDED', 'SKIPPED', 'DRY_RUN') else 1


if __name__ == '__main__':
    raise SystemExit(main())
