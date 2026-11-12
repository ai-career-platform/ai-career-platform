"""CRAWLER_NIGHT_01: keyword-sliced JobKorea night collection, 21:00-08:00 KST, fail-closed.

Runs from the existing 5-minute dispatcher timer, only after the daily dispatch returned IDLE
and while holding the same dispatcher advisory lock, so it never overlaps the 03:00 fixture run,
a manual fixture run or another night step. Each poll starts at most ONE keyword job.

Reused: T154 ``night_slot`` window, T151 ``keyword_jobs``/discoveries, T154 checkpoints,
T61 ``check_collection_permission``, #85 ``fetch_pages``/``import_pages`` (robots, >=2 s spacing,
15 s timeout, stop on redirect/401/403/429/challenge), ``PostgresPostingStore.upsert``
(inserted/updated/unchanged), T64 retry policy and the #250 Slack transport.

Nothing runs unless ``CRAWLER_NIGHT_ENABLED=1``. Live HTTP additionally needs
``CRAWLER_LIVE_SCHEDULE_APPROVED=1`` and a private T61 approval file
(``CRAWLER_NIGHT_POLICY_FILE``) that lists the exact keyword search URL (CRAWLER_NIGHT_09) and
either lists each detail URL or sets ``max_discovered_details`` (1..5) for details found on that
search page. No such approval exists while T61 is HOLD, so live stays BLOCKED. Blocked steps
write nothing.
"""
from __future__ import annotations

import time as clock
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote

from crawler.jobs.fixture_night_window import KST, night_slot
from crawler.jobs.import_jobkorea_html import FetchError, fetch_pages, import_pages, load_approval_file
from crawler.jobs.incremental_checkpoint import KeywordCheckpointStore
from crawler.jobs.keyword_management import KeywordStore, normalize_keyword
from crawler.jobs.offline_recovery import RETRYABLE_CODES, STOP_CODES
from crawler.jobs.scheduled_worker import failure_code
from crawler.jobs.scheduler import retry_at
from crawler.policy.source_approval_gate import CollectionIntent, check_collection_permission

NIGHT_KEYWORDS = ('AX', '데이터 분석', '빅데이터', 'AI 엔지니어', '머신러닝', '딥러닝')
LAST_START_MINUTE = 10 * 60 + 45   # 07:45 KST: no new job after this point
DETAIL_LIMIT = 5                   # detail pages per keyword job
JOB_DEADLINE_SECONDS = 150         # below the dispatcher unit's TimeoutStartSec=180
STALE_RUNNING = timedelta(minutes=10)
MAX_ATTEMPTS = 3
PURPOSE = 'night_keyword_collection'
SUMMARY_UNTIL = time(12, 0)        # summary for the night that just ended, sent 08:00-11:59 KST


@dataclass(frozen=True)
class Choice:
    keyword_id: int
    keyword: str
    attempt: int


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware datetime required')
    return value


def night_position(now):
    """(night_date, minutes since 21:00 KST) inside 21:00-08:00, else None. Reuses T154 slots."""
    slot = night_slot(_aware(now))
    if slot is None:
        return None
    start = datetime.combine(slot.night_date, time(21), KST)
    return slot.night_date, int((now.astimezone(KST) - start).total_seconds() // 60)


def search_url(keyword):
    return 'https://www.jobkorea.co.kr/Search/?stext=' + quote(keyword) + '&tabType=recruit'


def plan_next(now, keywords, results):
    """Pick at most one keyword job. Pure.

    keywords: [(keyword_id, display)] in NIGHT_KEYWORDS order.
    results: tonight's rows as dicts (keyword_id, attempt, outcome, error_code, ended_at).
    Keyword i may start from 21:00 + i hours (one per hour); after its hour it stays eligible
    for bounded retries until 07:45. A stop code (403/429/robots/challenge/unapproved) halts the night.
    """
    position = night_position(now)
    if position is None:
        return None, 'OUTSIDE_WINDOW'
    if position[1] > LAST_START_MINUTE:
        return None, 'START_CUTOFF'
    if any(r['outcome'] == 'RUNNING' for r in results):
        return None, 'JOB_RUNNING'
    if any(r['error_code'] in STOP_CODES for r in results):
        return None, 'NIGHT_HALTED'
    hour_index = position[1] // 60
    for index, (keyword_id, keyword) in enumerate(keywords):
        if index > hour_index:
            break
        mine = sorted((r for r in results if r['keyword_id'] == keyword_id), key=lambda r: r['attempt'])
        if any(r['outcome'] in ('SUCCEEDED', 'PARTIAL') for r in mine):
            continue
        if not mine:
            return Choice(keyword_id, keyword, 1), 'DUE'
        last = mine[-1]
        if last['attempt'] >= MAX_ATTEMPTS or last['error_code'] not in RETRYABLE_CODES:
            continue
        due = retry_at(last['error_code'], last['attempt'], last['ended_at'])
        if due is not None and now >= due:
            return Choice(keyword_id, keyword, last['attempt'] + 1), 'RETRY'
    return None, 'NOTHING_DUE'


load_approval = load_approval_file  # shared with the import CLI


def live_gate(*, environ, keyword, now, approval_loader=load_approval):
    """Return ('ALLOWED', approval) or (reason code, None). Only IO: the private policy file.

    fetch_pages() re-checks every URL (search page and each discovered detail) with the same
    approval before requesting it, so this early check only avoids creating a doomed job.
    """
    if environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
        return 'PM_ACTIVATION_REQUIRED', None
    path = environ.get('CRAWLER_NIGHT_POLICY_FILE')
    approval = approval_loader(path) if path else None
    if approval is None:
        return 'UNAPPROVED_SOURCE', None
    decision = check_collection_permission(approval, CollectionIntent(
        'jobkorea', search_url(keyword), 'WEB', PURPOSE, DETAIL_LIMIT + 2, _aware(now)))
    return ('ALLOWED', approval) if decision.allowed else (decision.reason.value, None)


class _Recording:
    """PostingStore wrapper remembering identities written in this job (for discoveries)."""

    def __init__(self, store):
        self.store, self.keys = store, []

    def upsert(self, posting):
        result = self.store.upsert(posting)
        self.keys.append((posting.source_code, posting.external_posting_id))
        return result


def _bounded(pages, deadline, counter):
    """Stop pulling pages after the job deadline; count HTTP requests (robots + list on first pull)."""
    iterator = iter(pages)
    first = True
    while True:
        if clock.monotonic() >= deadline:
            raise FetchError('TIMEOUT')
        try:
            item = next(iterator)
        except StopIteration:
            counter[0] += 2 if first else 0
            return
        except Exception:
            # Upper bound (F-08): on the first pull the failure may come from robots, the list or the
            # first detail. Never under-count a request budget, so count all three.
            counter[0] += 3 if first else 1
            raise
        counter[0] += 3 if first else 1
        first = False
        yield item


class NightStore:
    def __init__(self, connection):
        self.connection = connection

    def available(self):
        row = self.connection.execute(
            "SELECT to_regclass('crawler_training.night_job_results') IS NOT NULL").fetchone()
        return bool(row and row[0])

    def night_keywords(self):
        wanted = [normalize_keyword(k)[1] for k in NIGHT_KEYWORDS]
        rows = self.connection.execute("""SELECT keyword_id,keyword,normalized_keyword
            FROM crawler_training.search_keywords
            WHERE enabled AND deleted_at IS NULL AND normalized_keyword = ANY(%s)""", (wanted,)).fetchall()
        by_norm = {r[2]: (r[0], r[1]) for r in rows}
        return [by_norm[n] for n in wanted if n in by_norm], [k for k, n in zip(NIGHT_KEYWORDS, wanted) if n not in by_norm]

    def results(self, night_date):
        from psycopg.rows import dict_row
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute("""SELECT r.*, k.keyword FROM crawler_training.night_job_results r
                JOIN crawler_training.search_keywords k USING (keyword_id)
                WHERE night_date=%s ORDER BY started_at""", (night_date,))
            return c.fetchall()

    def recover_stale(self, now):
        """A RUNNING row older than the job deadline means the process died (deploy/kill)."""
        rows = self.connection.execute("""SELECT job_id FROM crawler_training.night_job_results
            WHERE outcome='RUNNING' AND started_at <= %s""", (now - STALE_RUNNING,)).fetchall()
        for (job_id,) in rows:
            self.finish(job_id, 'FAILED', {}, 'HEARTBEAT_TIMEOUT', 0)
            for status in ('RUNNING', 'FETCHED'):
                KeywordStore(self.connection).transition(job_id, status, 'FAILED')
        return len(rows)

    def start(self, choice, night_date):
        keywords = KeywordStore(self.connection)
        job_id = keywords.create_job(choice.keyword_id, f'night:{night_date}:{choice.keyword_id}:{choice.attempt}')
        with self.connection.transaction():
            row = self.connection.execute("""INSERT INTO crawler_training.night_job_results
                (job_id,keyword_id,night_date,attempt,mode) VALUES (%s,%s,%s,%s,'live')
                ON CONFLICT DO NOTHING RETURNING job_id""",
                (job_id, choice.keyword_id, night_date, choice.attempt)).fetchone()
            if row is None or not keywords.transition(job_id, 'PENDING', 'RUNNING'):
                raise RuntimeError('Night job already started')
        return job_id

    def finish(self, job_id, outcome, report, error_code, http_requests):
        self.connection.execute("""UPDATE crawler_training.night_job_results SET outcome=%s,
            ended_at=now(),http_requests=%s,fetched=%s,inserted=%s,updated=%s,unchanged=%s,
            duplicates=%s,failed=%s,error_code=%s WHERE job_id=%s AND outcome='RUNNING'""",
            (outcome, http_requests, report.get('fetched'), report.get('inserted'), report.get('updated'),
             report.get('unchanged'), report.get('duplicates'), report.get('invalid'), error_code, job_id))

    def mark_notified(self, job_id):
        return self.connection.execute("""UPDATE crawler_training.night_job_results
            SET slack_notified_at=now() WHERE job_id=%s AND slack_notified_at IS NULL
            AND outcome<>'RUNNING' RETURNING job_id""", (job_id,)).fetchone() is not None

    def claim_summary(self, night_date):
        return self.connection.execute("""INSERT INTO crawler_training.night_summaries(night_date)
            VALUES (%s) ON CONFLICT DO NOTHING RETURNING night_date""", (night_date,)).fetchone() is not None

    def summary_status(self, night_date, http_status):
        self.connection.execute("UPDATE crawler_training.night_summaries SET http_status=%s WHERE night_date=%s",
                                (http_status, night_date))


def _outcome(report):
    ok = report['inserted'] + report['updated'] + report['unchanged']
    if report.get('stopped'):
        return 'FAILED', failure_code(report)
    if report['invalid'] and not ok:
        return 'FAILED', failure_code(report)
    return ('PARTIAL' if report['invalid'] else 'SUCCEEDED'), None


def run_job(store, choice, night_date, *, approval=None, fetcher=fetch_pages, now_mono=clock.monotonic):
    """Execute one keyword job; DB result is written before any notice. Never raises."""
    job_id = store.start(choice, night_date)
    counter = [0]
    keywords = KeywordStore(store.connection)
    try:
        from crawler.storage.postgres import PostgresPostingStore
        recorder = _Recording(PostgresPostingStore(store.connection))
        pages = fetcher(list_url=search_url(choice.keyword), limit=DETAIL_LIMIT, approval=approval, purpose=PURPOSE)
        report = import_pages(_bounded(pages, now_mono() + JOB_DEADLINE_SECONDS, counter), recorder, live=True)
        report['fetched'] = report['inserted'] + report['updated'] + report['unchanged'] + report['duplicates'] + report['invalid']
        outcome, error = _outcome(report)
        for source_code, external_id in dict.fromkeys(recorder.keys):
            keywords.record_discovery(choice.keyword_id, source_code, external_id)
        if outcome == 'FAILED':
            keywords.transition(job_id, 'RUNNING', 'FAILED')
        else:
            keywords.transition(job_id, 'RUNNING', 'FETCHED')
            keywords.transition(job_id, 'FETCHED', 'COMPLETED')
            # Use the job's own DB end time: a Python clock a few microseconds behind the
            # database would otherwise make mark_completed() silently refuse the checkpoint.
            ended_at = store.connection.execute('SELECT ended_at FROM crawler_training.keyword_jobs WHERE job_id=%s',
                                                (job_id,)).fetchone()[0]
            KeywordCheckpointStore(store.connection).mark_completed(
                keyword_id=choice.keyword_id, job_id=job_id, completed_at=ended_at)
        store.finish(job_id, outcome, report, error, counter[0])
    except Exception:
        report, outcome = {}, 'FAILED'
        try:
            store.finish(job_id, 'FAILED', {}, 'WORKER_CRASH', counter[0])
            keywords.transition(job_id, 'RUNNING', 'FAILED')
        except Exception:
            pass
    return job_id


def run_night_step(connection, *, environ, now=None, fetcher=fetch_pages, notify=None, approval_loader=load_approval):
    """One poll of the night collector. Returns a secret-free summary dict."""
    if environ.get('CRAWLER_NIGHT_ENABLED') != '1':
        return {'night': 'DISABLED'}
    now = _aware(now or datetime.now(timezone.utc))
    store = NightStore(connection)
    if not store.available():
        return {'night': 'BLOCKED', 'reason': 'MIGRATION_REQUIRED'}
    from crawler.notifications import slack
    notify = notify or slack.notify_night
    position = night_position(now)
    if position is None:
        local = now.astimezone(KST)
        if time(8) <= local.time() < SUMMARY_UNTIL:
            night_date = local.date() - timedelta(days=1)
            rows = store.results(night_date)
            if rows and store.claim_summary(night_date):
                planned, missing = store.night_keywords()
                store.summary_status(night_date, notify('summary', night_date, rows, environ, missing=missing,
                                                         planned=[k for _, k in planned]))
                return {'night': 'SUMMARY_SENT', 'night_date': str(night_date)}
        return {'night': 'IDLE', 'reason': 'OUTSIDE_WINDOW'}
    night_date = position[0]
    store.recover_stale(now)
    keywords, _ = store.night_keywords()
    choice, reason = plan_next(now, keywords, store.results(night_date))
    if choice is None:
        return {'night': 'IDLE', 'reason': reason}
    gate, approval = live_gate(environ=environ, keyword=choice.keyword, now=now, approval_loader=approval_loader)
    if gate != 'ALLOWED':
        return {'night': 'BLOCKED', 'reason': gate, 'external_requests': 0}
    try:
        job_id = run_job(store, choice, night_date, approval=approval, fetcher=fetcher)
    except Exception:
        return {'night': 'ERROR', 'reason': 'JOB_START_FAILED'}
    row = next(r for r in store.results(night_date) if r['job_id'] == job_id)
    if store.mark_notified(job_id):
        notify('job', night_date, [row], environ)
    return {'night': row['outcome'], 'job_id': str(job_id), 'keyword_id': choice.keyword_id,
            'attempt': choice.attempt, 'error_code': row['error_code'], 'http_requests': row['http_requests']}
