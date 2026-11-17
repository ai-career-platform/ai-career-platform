"""GOAL_3 (AI_CAREER_CRAWLER_LIVE_GCP_1000): paginated keyword harvest toward 1,000 new postings/day.

The night collector (``night_crawl``) reads the first search page of six keywords and at most five
details per keyword (30 details, 126 requests per night), so it can never reach 1,000 new postings
a day. A harvest run instead:

1. pages through each keyword's search results (round-robin by page level, ``max_pages``);
2. takes the posting id from each result link (``/Recruit/GI_Read/<id>``) before any detail request;
3. looks the ids up in the DB in one query per page and drops ids already seen in this run
   (cross-keyword duplicates), so known postings cost no detail request;
4. fetches NEW postings first (``max_new_details``), then re-checks known postings that appeared
   again and were not checked for ``revisit_after_hours`` (``max_revisits``, oldest first);
5. stops paginating a keyword after an empty page or ``known_page_stop`` pages with nothing new,
   and stops all paging when the remaining request budget is needed for the planned details;
6. records per page (links/new/known/cross-duplicate), per keyword (new-discovery rate) and per
   posting (decision + inserted/updated/unchanged/failed) in ``crawler_training.harvest_*``.

Modes:
- ``fixture``: pages and details come from a local fixture directory; writes ``source_code =
  jobkorea_harvest_fixture``; sends no HTTP request.
- ``live``: needs ``CRAWLER_LIVE_SCHEDULE_APPROVED=1`` and a private T61 approval file whose purpose
  list contains ``harvest_collection`` and that sets ``max_search_pages``/``max_harvest_details``.
  Every search page and every discovered detail URL is checked by ``check_collection_permission``
  before it is requested (robots.txt, >= 2 s spacing, no redirects, stop on 401/403/429/challenge,
  request budget, approval expiry and a wall-clock deadline). Without approval nothing is sent.

A harvest holds the dispatcher advisory lock (642, 0), so it never overlaps the fixture scheduler,
a manual run or a night step. Usage::

    python -m crawler.jobs.harvest fixture --fixture-dir DIR [--pages 5 --new 1000 ...]
    python -m crawler.jobs.harvest live --policy-file FILE --check     # preflight, no network
    python -m crawler.jobs.harvest live --policy-file FILE [...]       # approved run only
    python -m crawler.jobs.harvest report [--days 7]
"""
from __future__ import annotations

import argparse
import json
import os
import time as clock
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_html, parse_jobkorea_result_page
from crawler.jobs.import_jobkorea_html import (FetchBlocked, FetchError, _fetch_allowed, _get, _permit,
                                               load_approval_file)
from crawler.policy.source_approval_gate import (HARVEST_PURPOSE, MAX_HARVEST_DETAILS, MAX_SEARCH_PAGES,
                                                 CollectionIntent, check_collection_permission,
                                                 paged_search_url)

KST = timezone(timedelta(hours=9))
SOURCE_CODES = {'fixture': 'jobkorea_harvest_fixture', 'live': 'jobkorea_live'}
DISPATCHER_LOCK = (642, 0)
DAILY_TARGET = 1000
STALE_MARGIN = timedelta(minutes=10)


def search_url(keyword):
    from crawler.jobs.night_crawl import search_url as night_search_url
    return night_search_url(keyword)


@dataclass(frozen=True)
class HarvestLimits:
    max_pages: int = 1                 # result pages per keyword
    max_new_details: int = 30          # detail requests for postings not in the DB
    max_revisits: int = 0              # detail requests re-checking known postings
    revisit_after_hours: int = 72
    known_page_stop: int = 2           # consecutive pages without a new id end a keyword
    max_requests: int = 126            # every HTTP request including robots.txt
    deadline_seconds: int = 3600

    def __post_init__(self):
        checks = {
            'max_pages': 1 <= self.max_pages <= MAX_SEARCH_PAGES,
            'max_new_details': 0 <= self.max_new_details <= MAX_HARVEST_DETAILS,
            'max_revisits': 0 <= self.max_revisits <= MAX_HARVEST_DETAILS,
            'revisit_after_hours': 1 <= self.revisit_after_hours <= 24 * 90,
            'known_page_stop': 1 <= self.known_page_stop <= MAX_SEARCH_PAGES,
            'max_requests': 1 <= self.max_requests <= 1 + MAX_SEARCH_PAGES * 50 + 2 * MAX_HARVEST_DETAILS,
            'deadline_seconds': 60 <= self.deadline_seconds <= 11 * 3600,
        }
        for name, ok in checks.items():
            if type(getattr(self, name)) is not int or not ok:
                raise ValueError(f'invalid harvest limit: {name}')
        if self.max_new_details + self.max_revisits > MAX_HARVEST_DETAILS:
            raise ValueError('invalid harvest limit: details')


def posting_id(url):
    return url.rsplit('/', 1)[1]


# ---------------------------------------------------------------- page sources
class FixtureSource:
    """Offline pages: {(keyword, page): html} and {external_id: detail html}. Counts requests."""

    live = False

    def __init__(self, pages, details):
        self.pages, self.details, self.requests = pages, details, 0

    @classmethod
    def from_dir(cls, path):
        """``keywords.json`` (list), ``search/<n>-p<page>.html`` (n = keyword index), ``detail/<id>.html``."""
        root = Path(path)
        keywords = json.loads((root / 'keywords.json').read_text(encoding='utf-8'))
        pages = {}
        for file in (root / 'search').glob('*-p*.html'):
            index, page = file.stem.split('-p')
            pages[(keywords[int(index)], int(page))] = file.read_text(encoding='utf-8')
        details = {f.stem: f.read_text(encoding='utf-8') for f in (root / 'detail').glob('*.html')}
        return keywords, cls(pages, details)

    def search(self, keyword, page):
        self.requests += 1
        html = self.pages.get((keyword, page), '')
        return paged_search_url(search_url(keyword), page), parse_jobkorea_result_page(html)

    def detail(self, url, page_url):
        self.requests += 1
        html = self.details.get(posting_id(url))
        if html is None:
            raise FetchError('HTTP_404', http_status=404)
        return html


class LiveSource:
    """T61-gated JobKorea access. Every URL is permitted by the approval before it is requested."""

    live = True

    def __init__(self, approval, limits, *, now_utc=None, now_mono=clock.monotonic, deadline=None):
        self.approval, self.limits, self.requests, self.details = approval, limits, 0, 0
        self.now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.now_mono = now_mono
        self.deadline = deadline if deadline is not None else now_mono() + limits.deadline_seconds
        self._robots = None

    def _before_request(self):
        if self.now_utc() >= self.approval.review_due_utc:
            raise FetchBlocked('UNAPPROVED_SOURCE')
        if self.now_mono() >= self.deadline:
            raise FetchBlocked('TIMEOUT')
        if self.requests >= self.limits.max_requests:
            raise FetchBlocked('REQUEST_BUDGET')
        self.requests += 1

    def _permit(self, url, discovered_from=None):
        _permit(self.approval, HARVEST_PURPOSE, url, self.limits.max_requests, self.now_utc(), discovered_from)

    def robots(self):
        if self._robots is None:
            from urllib.robotparser import RobotFileParser
            self._before_request()
            text = _get('https://www.jobkorea.co.kr/robots.txt')
            if 'user-agent:' not in text.lower():
                raise FetchBlocked('INVALID_ROBOTS_RESPONSE')
            robots = RobotFileParser()
            robots.parse(text.splitlines())
            self._robots = robots
        return self._robots

    def search(self, keyword, page):
        url = paged_search_url(search_url(keyword), page)
        self._permit(url)
        html = _fetch_allowed(url, self.robots(), self._before_request)
        return url, parse_jobkorea_result_page(html)

    def detail(self, url, page_url):
        self._permit(url, discovered_from=page_url)
        if self.details >= self.approval.max_harvest_details:  # runtime cap, independent of preflight
            raise FetchBlocked('DETAIL_BUDGET')
        self.details += 1
        try:
            return _fetch_allowed(url, self.robots(), self._before_request)
        except FetchBlocked:
            raise
        except OSError:
            raise FetchError('NETWORK_ERROR') from None


def preflight(approval, limits, keywords, *, now=None):
    """No-network check that an approval admits this exact harvest. Returns (ok, problems, urls)."""
    now = now or datetime.now(timezone.utc)
    problems = []
    if approval is None:
        return False, ['APPROVAL_FILE_MISSING_OR_INVALID'], []
    if limits.max_pages > approval.max_search_pages:
        problems.append('PAGES_EXCEED_APPROVAL')
    if limits.max_new_details + limits.max_revisits > approval.max_harvest_details:
        problems.append('DETAILS_EXCEED_APPROVAL')
    if type(approval.max_requests) is not int or limits.max_requests > approval.max_requests:
        problems.append('REQUESTS_EXCEED_APPROVAL')
    urls = []
    for keyword in keywords:
        for page in sorted({1, limits.max_pages}):
            url = paged_search_url(search_url(keyword), page)
            # PM approval AND the provider's permission (T61 shared policy), same check as every LIVE request
            from crawler.jobs.import_jobkorea_html import live_permission_reason
            reason = live_permission_reason(approval, CollectionIntent(
                'jobkorea', url, 'WEB', HARVEST_PURPOSE, limits.max_requests, now))
            if reason != 'ALLOWED':
                problems.append(f'{reason}:{keyword}:p{page}')
            if page == 1:
                urls.append(url)
    return not problems, sorted(set(problems)), urls


# ---------------------------------------------------------------- persistence
class HarvestStore:
    def __init__(self, connection):
        self.connection = connection

    def available(self):
        row = self.connection.execute("SELECT to_regclass('crawler_training.harvest_items') IS NOT NULL").fetchone()
        return bool(row and row[0])

    def lock(self):
        return self.connection.execute('SELECT pg_try_advisory_lock(%s,%s)', DISPATCHER_LOCK).fetchone()[0]

    def unlock(self):
        self.connection.execute('SELECT pg_advisory_unlock(%s,%s)', DISPATCHER_LOCK)

    def recover_stale(self):
        return self.connection.execute(
            """UPDATE crawler_training.harvest_runs SET status='FAILED', stop_reason='HEARTBEAT_TIMEOUT',
               ended_at=now() WHERE status='RUNNING'
               AND started_at + make_interval(secs => (limits->>'deadline_seconds')::int) + %s < now()""",
            (STALE_MARGIN,)).rowcount

    def start(self, mode, source_code, limits):
        return self.connection.execute(
            """INSERT INTO crawler_training.harvest_runs (mode, source_code, limits)
               VALUES (%s, %s, %s::jsonb) RETURNING run_id""",
            (mode, source_code, json.dumps(asdict(limits)))).fetchone()[0]

    def known(self, source_code, ids):
        """{external_id: last time the posting was written or checked} for ids already stored."""
        if not ids:
            return {}
        rows = self.connection.execute(
            """SELECT p.external_posting_id,
                      greatest(p.updated_at, (SELECT max(i.checked_at) FROM crawler_training.harvest_items i
                               WHERE i.source_code = p.source_code AND i.external_posting_id = p.external_posting_id
                               AND i.outcome <> 'failed'))
               FROM crawler_training.postings p
               WHERE p.source_code = %s AND p.external_posting_id = ANY(%s)""",
            (source_code, list(ids))).fetchall()
        return dict(rows)

    def record_page(self, run_id, keyword, page, counts, error_code=None):
        self.connection.execute(
            """INSERT INTO crawler_training.harvest_pages
               (run_id, keyword, page_no, links, new_ids, known_ids, cross_duplicates, error_code)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, keyword, page, counts['links'], counts['new'], counts['known'], counts['cross_dup'], error_code))

    def record_item(self, run_id, source_code, item):
        self.connection.execute(
            """INSERT INTO crawler_training.harvest_items
               (run_id, source_code, external_posting_id, keyword, page_no, decision)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (run_id, source_code, item.external_id, item.keyword, item.page, item.decision))

    def item_outcome(self, run_id, source_code, external_id, outcome, error_code=None):
        self.connection.execute(
            """UPDATE crawler_training.harvest_items SET outcome=%s, error_code=%s, checked_at=now()
               WHERE run_id=%s AND source_code=%s AND external_posting_id=%s""",
            (outcome, error_code, run_id, source_code, external_id))

    def finish(self, run_id, status, stop_reason, totals, keyword_stats, http_requests):
        self.connection.execute(
            """UPDATE crawler_training.harvest_runs SET status=%s, stop_reason=%s, ended_at=now(),
               http_requests=%s, search_pages=%s, links_seen=%s, new_found=%s, known_found=%s,
               cross_duplicates=%s, details_planned=%s, inserted=%s, updated=%s, unchanged=%s, failed=%s,
               keyword_stats=%s::jsonb WHERE run_id=%s AND status='RUNNING'""",
            (status, stop_reason, http_requests, totals['pages'], totals['links'], totals['new'], totals['known'],
             totals['cross_dup'], totals['planned'], totals['inserted'], totals['updated'], totals['unchanged'],
             totals['failed'], json.dumps(keyword_stats, ensure_ascii=False), run_id))

    def keyword_ids(self):
        from crawler.jobs.keyword_management import normalize_keyword
        rows = self.connection.execute("""SELECT normalized_keyword, keyword_id FROM crawler_training.search_keywords
            WHERE enabled AND deleted_at IS NULL""").fetchall()
        by_norm = dict(rows)
        return lambda keyword: by_norm.get(normalize_keyword(keyword)[1])



@dataclass(frozen=True)
class Item:
    external_id: str
    url: str
    keyword: str
    page: int
    page_url: str
    decision: str          # 'new' | 'revisit'
    last_checked: datetime | None = None


def _counter():
    return dict(pages=0, links=0, new=0, known=0, cross_dup=0, inserted=0, updated=0, unchanged=0, failed=0)


# ---------------------------------------------------------------- runner
def run_harvest(connection, source, *, keywords, limits, now_mono=clock.monotonic, now_utc=None):
    """One harvest run. Returns a secret-free summary dict. Never raises after the run row exists."""
    if not getattr(connection, 'autocommit', False):
        return {'status': 'BLOCKED', 'reason': 'AUTOCOMMIT_REQUIRED'}
    store = HarvestStore(connection)
    if not store.available():
        return {'status': 'BLOCKED', 'reason': 'MIGRATION_REQUIRED'}
    if not store.lock():
        return {'status': 'SKIPPED', 'reason': 'DISPATCHER_LOCKED'}
    try:
        return _locked_run(store, source, keywords=list(dict.fromkeys(keywords)), limits=limits,
                           now_mono=now_mono, now_utc=now_utc or (lambda: datetime.now(timezone.utc)))
    finally:
        store.unlock()


def _locked_run(store, source, *, keywords, limits, now_mono, now_utc):
    from crawler.storage.postgres import PostgresPostingStore
    mode = 'live' if source.live else 'fixture'
    source_code = SOURCE_CODES[mode]
    store.recover_stale()
    keyword_id = store.keyword_ids()
    revisit_before = now_utc() - timedelta(hours=limits.revisit_after_hours)
    run_id = store.start(mode, source_code, limits)
    started = now_mono()
    deadline = started + limits.deadline_seconds
    stats = {k: _counter() for k in keywords}
    totals = _counter() | {'planned': 0}
    status, stop_reason = 'SUCCEEDED', None
    seen = set()
    new_items, revisit_items = [], []
    try:
        # ---- phase 1: result pages, round-robin by page level
        active, quiet = list(keywords), {k: 0 for k in keywords}
        previous_links = {}   # keyword -> link list of its previous page (pagination-not-advancing guard)
        for page in range(1, limits.max_pages + 1):
            for keyword in list(active):
                planned = min(len(new_items), limits.max_new_details) + min(len(revisit_items), limits.max_revisits)
                # Keep budget for robots + every planned detail; stop paging once both queues are full.
                # With no detail budget at all (--new 0 --revisits 0) the run is a supply measurement:
                # it pages through the results and only counts new/known/duplicate ids.
                details_wanted = limits.max_new_details + limits.max_revisits
                if source.requests + 2 + planned > limits.max_requests or details_wanted and (
                        len(new_items) >= limits.max_new_details and len(revisit_items) >= limits.max_revisits):
                    active = []
                    break
                if now_mono() >= deadline:
                    raise FetchBlocked('TIMEOUT')
                try:
                    page_url, urls = source.search(keyword, page)
                except FetchBlocked:
                    raise
                except FetchError as exc:
                    store.record_page(run_id, keyword, page, dict(links=0, new=0, known=0, cross_dup=0),
                                      _code(exc.reason))
                    active.remove(keyword)
                    continue
                if urls and previous_links.get(keyword) == urls:
                    # The site ignored the page parameter (e.g. Page_No unsupported) and served the previous page
                    # again: every further page would cost a request for nothing. Stop this keyword now.
                    store.record_page(run_id, keyword, page, dict(links=len(urls), new=0, known=0,
                                                                  cross_dup=len(urls)), 'PAGE_REPEATED')
                    stats[keyword]['pages'] += 1
                    stats[keyword]['links'] += len(urls)
                    stats[keyword]['cross_dup'] += len(urls)
                    active.remove(keyword)
                    continue
                previous_links[keyword] = urls
                fresh = [u for u in urls if posting_id(u) not in seen]
                known = store.known(source_code, [posting_id(u) for u in fresh])
                counts = dict(links=len(urls), new=0, known=0, cross_dup=len(urls) - len(fresh))
                for url in fresh:
                    external_id = posting_id(url)
                    seen.add(external_id)
                    if external_id in known:
                        counts['known'] += 1
                        last = known[external_id]
                        if limits.max_revisits and last is not None and last < revisit_before:
                            revisit_items.append(Item(external_id, url, keyword, page, page_url, 'revisit', last))
                    else:
                        counts['new'] += 1
                        new_items.append(Item(external_id, url, keyword, page, page_url, 'new'))
                store.record_page(run_id, keyword, page, counts)
                for key in ('links', 'new', 'known', 'cross_dup'):
                    stats[keyword][key] += counts[key]
                stats[keyword]['pages'] += 1
                if not urls:
                    active.remove(keyword)
                elif counts['new'] == 0:
                    quiet[keyword] += 1
                    if quiet[keyword] >= limits.known_page_stop:
                        active.remove(keyword)
                else:
                    quiet[keyword] = 0
            if not active:
                break
        # ---- phase 2: details, new postings first, then the oldest-checked known postings
        revisit_items.sort(key=lambda item: item.last_checked)
        plan = new_items[:limits.max_new_details] + revisit_items[:limits.max_revisits]
        totals['planned'] = len(plan)
        postings = PostgresPostingStore(store.connection)
        from crawler.jobs.keyword_management import KeywordStore
        discoveries = KeywordStore(store.connection)
        failures = 0
        for item in plan:
            if now_mono() >= deadline:
                raise FetchBlocked('TIMEOUT')
            store.record_item(run_id, source_code, item)
            try:
                html = source.detail(item.url, item.page_url)
                posting = replace(parse_jobkorea_html(html=html, source_url=item.url).normalized(),
                                  source_code=source_code)
                outcome = postings.upsert(posting)
            except FetchBlocked as exc:
                store.item_outcome(run_id, source_code, item.external_id, 'failed', _code(exc.reason))
                raise
            except Exception as exc:
                reason = exc.reason if isinstance(exc, FetchError) else type(exc).__name__
                store.item_outcome(run_id, source_code, item.external_id, 'failed', _code(reason))
                stats[item.keyword]['failed'] += 1
                failures += 1
                continue
            store.item_outcome(run_id, source_code, item.external_id, outcome)
            stats[item.keyword][outcome] += 1
            kid = keyword_id(item.keyword)
            if kid is not None:
                discoveries.record_discovery(kid, source_code, item.external_id)
        if failures:
            status = 'PARTIAL'
    except FetchBlocked as exc:
        status, stop_reason = 'STOPPED', _code(exc.reason)
    except Exception as exc:  # never leave the run RUNNING
        status, stop_reason = 'FAILED', _code('WORKER_' + type(exc).__name__.upper())
    for keyword, row in stats.items():
        row['new_rate'] = round(row['new'] / row['links'], 4) if row['links'] else None
        for key in ('pages', 'links', 'new', 'known', 'cross_dup', 'inserted', 'updated', 'unchanged', 'failed'):
            totals[key] += row[key]
    elapsed = max(now_mono() - started, 1e-9)
    # harvest_runs.http_requests counts real HTTP only; fixture page reads are reported, not stored as HTTP.
    store.finish(run_id, status, stop_reason, totals, stats, source.requests if source.live else 0)
    return {'status': status, 'stop_reason': stop_reason, 'run_id': str(run_id), 'mode': mode,
            'source_code': source_code, 'http_requests': source.requests if source.live else 0,
            'fixture_requests': 0 if source.live else source.requests, 'elapsed_seconds': round(elapsed, 3),
            'inserts_per_second': round(totals['inserted'] / elapsed, 1), **totals, 'keywords': stats}



def _code(reason):
    import re
    text = re.sub(r'[^A-Z0-9_]', '_', str(reason).upper())[:64] or 'UNKNOWN'
    return text if text[0].isalpha() else 'E_' + text[:62]


# ---------------------------------------------------------------- daily monitoring
def daily_report(connection, *, days=7):
    """Per KST day: harvest runs, new unique inserts (live vs fixture), updates, requests, target progress."""
    rows = connection.execute(
        """SELECT (r.started_at AT TIME ZONE 'Asia/Seoul')::date AS day, r.mode, count(*) AS runs,
                  sum(r.inserted), sum(r.updated), sum(r.unchanged), sum(r.failed), sum(r.http_requests),
                  sum(r.search_pages), sum(r.links_seen), sum(r.new_found), sum(r.cross_duplicates),
                  count(*) FILTER (WHERE r.status IN ('STOPPED','FAILED'))
           FROM crawler_training.harvest_runs r
           WHERE r.started_at >= now() - make_interval(days => %s) AND r.started_at <= now()
           GROUP BY 1, 2 ORDER BY 1, 2""", (days,)).fetchall()
    night = connection.execute(
        """SELECT night_date, coalesce(sum(inserted),0), coalesce(sum(updated),0), coalesce(sum(http_requests),0)
           FROM crawler_training.night_job_results
           WHERE night_date BETWEEN (now() AT TIME ZONE 'Asia/Seoul')::date - %s AND (now() AT TIME ZONE 'Asia/Seoul')::date
           GROUP BY 1 ORDER BY 1""", (days,)).fetchall() if connection.execute(
        "SELECT to_regclass('crawler_training.night_job_results') IS NOT NULL").fetchone()[0] else []
    out = []
    for day, mode, runs, ins, upd, unch, failed, http, pages, links, new, dup, bad in rows:
        out.append({'day': str(day), 'mode': mode, 'runs': runs, 'inserted': ins, 'updated': upd, 'unchanged': unch,
                    'failed': failed, 'http_requests': http, 'search_pages': pages, 'links_seen': links,
                    'new_found': new, 'cross_duplicates': dup, 'stopped_or_failed_runs': bad,
                    'target': DAILY_TARGET if mode == 'live' else None,
                    'target_met': (ins >= DAILY_TARGET) if mode == 'live' else None})
    return {'harvest_by_day': out,
            'night_by_day': [{'night_date': str(d), 'inserted': i, 'updated': u, 'http_requests': h}
                             for d, i, u, h in night]}


# ---------------------------------------------------------------- CLI
def _limits(args):
    return HarvestLimits(max_pages=args.pages, max_new_details=args.new, max_revisits=args.revisits,
                         revisit_after_hours=args.revisit_after_hours, known_page_stop=args.known_page_stop,
                         max_requests=args.max_requests, deadline_seconds=args.deadline_seconds)


def _connect():
    from crawler.storage.staging import connect_configured_database
    connection = connect_configured_database()
    connection.autocommit = True
    return connection


def main(argv=None, *, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('fixture', 'live'):
        p = sub.add_parser(name)
        p.add_argument('--pages', type=int, default=1)
        p.add_argument('--new', type=int, default=30)
        p.add_argument('--revisits', type=int, default=0)
        p.add_argument('--revisit-after-hours', type=int, default=72)
        p.add_argument('--known-page-stop', type=int, default=2)
        p.add_argument('--max-requests', type=int, default=126)
        p.add_argument('--deadline-seconds', type=int, default=3600)
        p.add_argument('--keyword', action='append',
                       help='live default: the six T61 night keywords (never the DB list, which may hold test rows)')
    sub.choices['fixture'].add_argument('--fixture-dir', required=True)
    sub.choices['live'].add_argument('--policy-file', required=True, help='Private T61 approval JSON')
    sub.choices['live'].add_argument('--check', action='store_true', help='Preflight only: no network, no writes')
    report = sub.add_parser('report')
    report.add_argument('--days', type=int, default=7)
    args = parser.parse_args(argv)
    try:
        if args.command == 'report':
            with _connect() as connection:
                result = daily_report(connection, days=args.days)
            print(json.dumps(result, ensure_ascii=False, default=str))
            return 0
        limits = _limits(args)
        if args.command == 'fixture':
            keywords, source = FixtureSource.from_dir(args.fixture_dir)
            keywords = args.keyword or keywords
        else:
            from crawler.jobs.night_crawl import NIGHT_KEYWORDS
            approval = load_approval_file(args.policy_file)
            keywords = args.keyword or list(NIGHT_KEYWORDS)
            ok, problems, urls = preflight(approval, limits, keywords)
            if args.check or not ok:
                print(json.dumps({'command': 'live-preflight', 'ok': ok, 'problems': problems,
                                  'keywords': keywords, 'first_page_urls': urls, 'limits': asdict(limits),
                                  'external_requests': 0}, ensure_ascii=False))
                return 0 if ok else 2
            if environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
                print(json.dumps({'status': 'BLOCKED', 'reason': 'PM_ACTIVATION_REQUIRED', 'external_requests': 0}))
                return 2
            source = LiveSource(approval, limits)
        with _connect() as connection:
            result = run_harvest(connection, source, keywords=keywords, limits=limits)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': type(exc).__name__, 'detail': str(exc)[:200]}))
        return 2
    except Exception as exc:  # e.g. a DB error: still one JSON line, never a secret-bearing traceback
        print(json.dumps({'status': 'FAILED', 'reason': type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result['status'] in ('SUCCEEDED', 'PARTIAL', 'SKIPPED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
