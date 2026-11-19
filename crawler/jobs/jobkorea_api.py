"""JobKorea official XML API collection (guide V4.1): T61-gated, ledgered, at most 1,000 postings in total.

Replaces HTML scraping for JobKorea. The HTML adapter and harvest stay in the repository, unused by this path.

What one run does:
1. checks the T61 policy for the API (PM approval with ``collection_method='API'`` AND the provider's
   permission, ``crawler.policy.provider_permission``) before every request, plus the request budget, the
   approval window and a wall-clock deadline;
2. checks once that this PC's outbound IP is one of the IPs registered with JobKorea (live mode only);
3. requests ``Keyword`` result pages round-robin by page level (``Size`` <= 100, ``Page``, ``Ob=1`` =
   registration order as the guide recommends), at least 2 s apart, and only while new postings are needed;
4. drops ids already stored (``jobkorea_api`` or ``jobkorea_live``) and ids seen earlier in the run;
5. inserts new postings until ``target_new`` or the cumulative cap (1,000 JobKorea postings) is reached;
6. records the run, every page and every new posting in ``crawler_training.harvest_*`` (the harvest ledger).

It never requests HTML pages. A 401/403/429, a redirect, a network error or a response that is not a
JobKorea DataList page stops the whole run at once (no retry).

Secrets: the full endpoint URLs (with the account parameters JobKorea issued) and the registered IPs live in
a private JSON file outside Git (``--api-config``). Only the endpoint's public form (scheme, host, path) is
printed, logged or stored. Usage::

    python -m crawler.jobs.jobkorea_api fixture --fixture-dir DIR [--new 100 ...]
    python -m crawler.jobs.jobkorea_api live --policy-file FILE --api-config FILE --check   # no JobKorea request
    python -m crawler.jobs.jobkorea_api live --policy-file FILE --api-config FILE --probe   # 1 small request, no writes
    python -m crawler.jobs.jobkorea_api live --policy-file FILE --api-config FILE [--new 100]
"""
from __future__ import annotations

import argparse
import json
import os
import time as clock
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from crawler.adapters.jobkorea_api_xml import (MAX_PAGE_SIZE, MAX_RESPONSE_BYTES, MAX_TOTAL_RESULTS,
                                               ApiResponseError, InvalidPosting, item_posting_id,
                                               parse_api_response, to_posting)
from crawler.jobs.harvest import HarvestStore, Item, _code
from crawler.jobs.import_jobkorea_html import USER_AGENT, FetchBlocked, FetchError, load_approval_file
from crawler.policy.provider_permission import PM_POLICY_MAX_ITEMS
from crawler.policy.source_approval_gate import API_PURPOSE, CollectionIntent, public_api_endpoint

SOURCE_CODES = {'fixture': 'jobkorea_api_fixture', 'live': 'jobkorea_api'}
# Every stored JobKorea posting counts toward the PM's 1,000 cap and as an existing duplicate.
JOBKOREA_LIVE_SOURCES = ('jobkorea_api', 'jobkorea_live')
MIN_SPACING_SECONDS = 2.0
IP_ECHO_URL = 'https://api.ipify.org'


@dataclass(frozen=True)
class ApiLimits:
    target_new: int = 100            # new postings to insert in this run
    page_size: int = 100             # guide: Size 1..100
    max_pages: int = 5               # per keyword; TotalSumCnt is capped at 500 = 5 pages of 100
    max_requests: int = 30           # JobKorea API requests in this run
    deadline_seconds: int = 1800
    order: str = '1'                 # Ob: 1 = registration date (guide recommendation)

    def __post_init__(self):
        checks = {
            'target_new': 1 <= self.target_new <= PM_POLICY_MAX_ITEMS,
            'page_size': 1 <= self.page_size <= MAX_PAGE_SIZE,
            'max_pages': 1 <= self.max_pages <= MAX_TOTAL_RESULTS,
            'max_requests': 1 <= self.max_requests <= 500,
            'deadline_seconds': 60 <= self.deadline_seconds <= 4 * 3600,
        }
        for name, ok in checks.items():
            if type(getattr(self, name)) is not int or not ok:
                raise ValueError(f'invalid api limit: {name}')
        if self.order not in ('1', '2', '3'):
            raise ValueError('invalid api limit: order')


# ---------------------------------------------------------------- private API configuration
@dataclass(frozen=True)
class ApiConfig:
    endpoint_url: str                     # full URL incl. account parameters: never printed or stored
    registered_ips: tuple[str, ...]

    @property
    def public_url(self):
        parts = urlsplit(self.endpoint_url)
        return f'{parts.scheme}://{parts.hostname}{parts.path}'

    def request_url(self, *, keyword, page, size, order):
        # Keyword must be EUC-KR percent-encoded (guide ⑦); the account parameters come first, as issued.
        params = (f'Size={size}&Page={page}&Ob={order}'
                  + (f'&Keyword={quote(keyword, safe="", encoding="cp949")}' if keyword else ''))
        return self.endpoint_url + ('&' if urlsplit(self.endpoint_url).query else '?') + params


def load_api_config(path, *, endpoint='all'):
    """Private JSON {"endpoints": {"all": URL, "starter": URL}, "registered_ips": [...]} -> ApiConfig or None."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        url = data['endpoints'][endpoint]
        ips = tuple(str(ip).strip() for ip in data['registered_ips'])
        parts = urlsplit(url)
        public = f'{parts.scheme}://{parts.hostname}{parts.path}'
        if (not isinstance(url, str) or parts.username or parts.password or parts.port or parts.fragment
                or not public_api_endpoint(public) or not ips or not all(ips)):
            return None
        return ApiConfig(url, ips)
    except Exception:
        return None


# ---------------------------------------------------------------- sources
class FixtureApiSource:
    """Offline responses: {(keyword, page): bytes}. Sends nothing; counts reads."""

    live = False

    def __init__(self, responses):
        self.responses, self.requests = responses, 0

    @classmethod
    def from_dir(cls, path):
        """``keywords.json`` (list) and ``pages/<n>-p<page>.xml`` (n = keyword index, raw bytes)."""
        root = Path(path)
        keywords = json.loads((root / 'keywords.json').read_text(encoding='utf-8'))
        responses = {}
        for file in (root / 'pages').glob('*-p*.xml'):
            index, page = file.stem.split('-p')
            responses[(keywords[int(index)], int(page))] = file.read_bytes()
        return keywords, cls(responses)

    def fetch(self, keyword, page, size, order):
        self.requests += 1
        data = self.responses.get((keyword, page))
        if data is None:
            raise FetchError('HTTP_404', http_status=404)
        return data


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _http_get(url, *, timeout=15):
    """GET -> body bytes. Errors carry a code only: the URL (with the API identifier) never leaves here."""
    try:
        request = Request(url, headers={'User-Agent': USER_AGENT})
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise FetchBlocked('UNEXPECTED_HTTP_STATUS', http_status=response.status)
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise FetchBlocked('RESPONSE_TOO_LARGE')
            return data
    except HTTPError as exc:
        raise FetchBlocked(f'HTTP_{exc.code}', http_status=exc.code) from None
    except (TimeoutError, URLError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, 'reason', None), TimeoutError)
        raise FetchBlocked('TIMEOUT' if timed_out else 'NETWORK_ERROR') from None
    except OSError:
        raise FetchBlocked('NETWORK_ERROR') from None


def egress_ip(get=_http_get):
    """This PC's public IP as seen by an IP echo service (one request, not to JobKorea)."""
    text = get(IP_ECHO_URL).decode('ascii', errors='strict').strip()
    if not text or len(text) > 45 or any(c not in '0123456789abcdef.:ABCDEF' for c in text):
        raise FetchBlocked('IP_CHECK_FAILED')
    return text


class LiveApiSource:
    """T61-gated official API access. Every request is permitted by the approval before it is sent."""

    live = True

    def __init__(self, approval, config, limits, *, get=_http_get, sleep=clock.sleep, now_mono=clock.monotonic,
                 now_utc=None, ip_lookup=None):
        self.approval, self.config, self.limits = approval, config, limits
        self.get, self.sleep, self.now_mono = get, sleep, now_mono
        self.now_utc = now_utc or (lambda: datetime.now(timezone.utc))
        self.ip_lookup = ip_lookup or (lambda: egress_ip(get))
        self.requests, self.ip_checked, self._last = 0, False, None
        self.deadline = now_mono() + limits.deadline_seconds

    def _check_ip(self):
        if not self.ip_checked:
            ip = self.ip_lookup()
            if ip not in self.config.registered_ips:
                raise FetchBlocked('SOURCE_IP_NOT_REGISTERED')
            self.ip_checked = True

    def fetch(self, keyword, page, size, order):
        from crawler.jobs.import_jobkorea_html import live_permission_reason
        reason = live_permission_reason(self.approval, CollectionIntent(
            'jobkorea', self.config.public_url, 'API', API_PURPOSE, self.limits.max_requests, self.now_utc()))
        if reason != 'ALLOWED':
            raise FetchBlocked(reason if reason.startswith(('PROVIDER', 'PM_WINDOW', 'ITEM')) else 'UNAPPROVED_SOURCE')
        if self.requests >= self.limits.max_requests:
            raise FetchBlocked('REQUEST_BUDGET')
        if self.now_mono() >= self.deadline:
            raise FetchBlocked('TIMEOUT')
        self._check_ip()
        if self._last is not None:
            wait = MIN_SPACING_SECONDS - (self.now_mono() - self._last)
            if wait > 0:
                self.sleep(wait)
        self.requests += 1
        self._last = self.now_mono()
        return self.get(self.config.request_url(keyword=keyword, page=page, size=size, order=order))


# ---------------------------------------------------------------- persistence helpers
def existing_ids(connection, ids, source_code):
    """Ids already stored by this source or as JobKorea postings (API or earlier live HTML collection)."""
    if not ids:
        return set()
    rows = connection.execute(
        """SELECT DISTINCT external_posting_id FROM crawler_training.postings
           WHERE source_code = ANY(%s) AND external_posting_id = ANY(%s)""",
        (list(dict.fromkeys((source_code,) + JOBKOREA_LIVE_SOURCES)), list(ids))).fetchall()
    return {r[0] for r in rows}


def stored_total(connection):
    return connection.execute('SELECT count(*) FROM crawler_training.postings WHERE source_code = ANY(%s)',
                              (list(JOBKOREA_LIVE_SOURCES),)).fetchone()[0]


def _counter():
    return dict(pages=0, links=0, new=0, known=0, cross_dup=0, inserted=0, updated=0, unchanged=0, failed=0)


def keyword_index(keywords, keyword):
    return keywords.index(keyword)


# ---------------------------------------------------------------- runner
def run_api_collection(connection, source, *, keywords, limits, now_mono=clock.monotonic):
    """One API run. Returns a secret-free summary dict. Never raises after the run row exists."""
    if not getattr(connection, 'autocommit', False):
        return {'status': 'BLOCKED', 'reason': 'AUTOCOMMIT_REQUIRED'}
    store = HarvestStore(connection)
    if not store.available():
        return {'status': 'BLOCKED', 'reason': 'MIGRATION_REQUIRED'}
    if not store.lock():
        return {'status': 'SKIPPED', 'reason': 'DISPATCHER_LOCKED'}
    try:
        return _locked_run(store, source, keywords=list(dict.fromkeys(keywords)), limits=limits, now_mono=now_mono)
    finally:
        store.unlock()


def _locked_run(store, source, *, keywords, limits, now_mono):
    from crawler.storage.postgres import PostgresPostingStore
    mode = 'live' if source.live else 'fixture'
    source_code = SOURCE_CODES[mode]
    store.recover_stale()
    before_total = stored_total(store.connection) if source.live else 0
    target = min(limits.target_new, max(PM_POLICY_MAX_ITEMS - before_total, 0)) if source.live else limits.target_new
    run_id = store.start(mode, source_code, limits)
    started = now_mono()
    deadline = started + limits.deadline_seconds
    stats = {k: _counter() for k in keywords}
    totals = _counter() | {'planned': 0}
    status, stop_reason = 'SUCCEEDED', None
    seen, results, encoding = set(), {}, None
    postings = PostgresPostingStore(store.connection)
    inserted = 0
    try:
        if target <= 0:
            raise FetchBlocked('CUMULATIVE_LIMIT')
        active = list(keywords)
        previous = {}
        for page in range(1, limits.max_pages + 1):
            for keyword in list(active):
                if inserted >= target:
                    active = []
                    break
                if now_mono() >= deadline:
                    raise FetchBlocked('TIMEOUT')
                data = source.fetch(keyword, page, limits.page_size, limits.order)
                try:
                    parsed = parse_api_response(data, require_total=False)
                except ApiResponseError as exc:
                    # Not a DataList page (authentication error, maintenance page, ...): stop the whole run.
                    store.record_page(run_id, keyword, page, dict(links=0, new=0, known=0, cross_dup=0),
                                      _code(exc.code))
                    raise FetchBlocked(exc.code) from None
                encoding = parsed.encoding
                results.setdefault(keyword, parsed.total_results)
                ids = [item_posting_id(item) for item in parsed.items]
                if ids and previous.get(keyword) == ids:
                    store.record_page(run_id, keyword, page, dict(links=len(ids), new=0, known=0,
                                                                  cross_dup=len(ids)), 'PAGE_REPEATED')
                    stats[keyword]['pages'] += 1
                    stats[keyword]['links'] += len(ids)
                    stats[keyword]['cross_dup'] += len(ids)
                    active.remove(keyword)
                    continue
                previous[keyword] = ids
                fresh = [(i, item) for i, item in zip(ids, parsed.items) if i is None or i not in seen]
                known = existing_ids(store.connection, [i for i, _ in fresh if i is not None], source_code)
                counts = dict(links=len(ids), new=0, known=0, cross_dup=len(ids) - len(fresh))
                stats[keyword]['pages'] += 1
                for position, (external_id, item) in enumerate(fresh, 1):
                    if external_id is not None:
                        seen.add(external_id)
                    if external_id in known:
                        counts['known'] += 1
                        continue
                    counts['new'] += 1
                    if inserted >= target:
                        continue                      # found, but beyond this run's target: not stored
                    entry = Item(external_id or f'invalid-{keyword_index(keywords, keyword)}-p{page}-{position}',
                                 '', keyword, page, '', 'new')
                    store.record_item(run_id, source_code, entry)
                    totals['planned'] += 1
                    try:
                        outcome = postings.upsert(to_posting(item, source_code=source_code))
                    except InvalidPosting:
                        store.item_outcome(run_id, source_code, entry.external_id, 'failed', 'INVALID_POSTING')
                        stats[keyword]['failed'] += 1
                        continue
                    except Exception as exc:
                        store.item_outcome(run_id, source_code, entry.external_id, 'failed',
                                           _code('STORE_' + type(exc).__name__.upper()))
                        stats[keyword]['failed'] += 1
                        continue
                    store.item_outcome(run_id, source_code, entry.external_id, outcome)
                    stats[keyword][outcome] += 1
                    if outcome == 'inserted':
                        inserted += 1
                store.record_page(run_id, keyword, page, counts)
                for key in ('links', 'new', 'known', 'cross_dup'):
                    stats[keyword][key] += counts[key]
                # TotalSumCnt (at most 500) bounds the pages; the 신입공채 XML has none, so only a short page ends it.
                last_page = (limits.max_pages if parsed.total_results is None
                             else -(-min(parsed.total_results, MAX_TOTAL_RESULTS) // limits.page_size))
                if not parsed.items or len(parsed.items) < limits.page_size or page >= last_page:
                    active.remove(keyword)
            if not active:
                break
        if any(row['failed'] for row in stats.values()):
            status = 'PARTIAL'
    except FetchBlocked as exc:
        status, stop_reason = 'STOPPED', _code(exc.reason)
    except FetchError as exc:
        status, stop_reason = 'STOPPED', _code(exc.reason)
    except Exception as exc:  # never leave the run RUNNING
        status, stop_reason = 'FAILED', _code('WORKER_' + type(exc).__name__.upper())
    for keyword, row in stats.items():
        row['new_rate'] = round(row['new'] / row['links'], 4) if row['links'] else None
        row['total_results'] = results.get(keyword)
        for key in ('pages', 'links', 'new', 'known', 'cross_dup', 'inserted', 'updated', 'unchanged', 'failed'):
            totals[key] += row[key]
    if status == 'SUCCEEDED' and totals['inserted'] < target:
        stop_reason = 'SUPPLY_EXHAUSTED'              # every page needed was read; fewer new postings exist
    requests = source.requests if source.live else 0
    store.finish(run_id, status, stop_reason, totals, stats, requests)
    return {'status': status, 'stop_reason': stop_reason, 'run_id': str(run_id), 'mode': mode,
            'source_code': source_code, 'api_requests': requests,
            'fixture_reads': 0 if source.live else source.requests, 'encoding': encoding,
            'target_new': target, 'stored_before': before_total if source.live else None,
            'elapsed_seconds': round(max(now_mono() - started, 0), 3), **totals, 'keywords': stats}


# ---------------------------------------------------------------- preflight and probe
def preflight(approval, config, limits, *, now=None):
    """No-network check that the approval and the private config admit this run. (ok, problems)."""
    from crawler.jobs.import_jobkorea_html import live_permission_reason
    now = now or datetime.now(timezone.utc)
    problems = []
    if approval is None:
        problems.append('APPROVAL_FILE_MISSING_OR_INVALID')
    if config is None:
        problems.append('API_CONFIG_MISSING_OR_INVALID')
    if problems:
        return False, problems
    reason = live_permission_reason(approval, CollectionIntent(
        'jobkorea', config.public_url, 'API', API_PURPOSE, limits.max_requests, now))
    if reason != 'ALLOWED':
        problems.append(reason)
    if limits.target_new > (approval.max_harvest_details or 0):
        problems.append('TARGET_EXCEEDS_APPROVAL')
    return not problems, problems


def probe(source, keyword, *, size=5):
    """One small request: status of the XML, encoding and the first ids/titles. Writes nothing."""
    page = parse_api_response(source.fetch(keyword, 1, size, '1'), require_total=False)
    sample = [{'GI_No': item_posting_id(i), 'GI_Subject': (i.get('GI_Subject') or '')[:80]} for i in page.items[:3]]
    return {'encoding': page.encoding, 'total_results': page.total_results, 'page_count': page.page_count,
            'items': len(page.items), 'sample': sample}


# ---------------------------------------------------------------- CLI
def _connect():
    from crawler.storage.staging import connect_configured_database
    connection = connect_configured_database()
    connection.autocommit = True
    return connection


def main(argv=None, *, environ=None):
    from crawler.jobs.night_crawl import NIGHT_KEYWORDS
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('fixture', 'live'):
        p = sub.add_parser(name)
        p.add_argument('--new', type=int, default=100)
        p.add_argument('--size', type=int, default=100)
        p.add_argument('--pages', type=int, default=5)
        p.add_argument('--max-requests', type=int, default=30)
        p.add_argument('--deadline-seconds', type=int, default=1800)
        p.add_argument('--keyword', action='append', help='default: the six T61 keywords')
    sub.choices['fixture'].add_argument('--fixture-dir', required=True)
    live = sub.choices['live']
    live.add_argument('--policy-file', required=True, help='Private T61 PM approval JSON (collection_method API)')
    live.add_argument('--api-config', required=True, help='Private API config JSON (endpoint URLs, registered IPs)')
    live.add_argument('--endpoint', choices=('all', 'starter'), default='all')
    live.add_argument('--check', action='store_true', help='Preflight + IP check only; no JobKorea request')
    live.add_argument('--probe', action='store_true', help='One request with Size=5; no DB write')
    args = parser.parse_args(argv)
    try:
        limits = ApiLimits(target_new=args.new, page_size=args.size, max_pages=args.pages,
                           max_requests=args.max_requests, deadline_seconds=args.deadline_seconds)
        keywords = args.keyword or list(NIGHT_KEYWORDS)
        if args.command == 'fixture':
            fixture_keywords, source = FixtureApiSource.from_dir(args.fixture_dir)
            keywords = args.keyword or fixture_keywords
        else:
            approval = load_approval_file(args.policy_file)
            config = load_api_config(args.api_config, endpoint=args.endpoint)
            ok, problems = preflight(approval, config, limits)
            report = {'command': 'api-preflight', 'ok': ok, 'problems': problems, 'keywords': keywords,
                      'endpoint': config.public_url if config else None, 'limits': asdict(limits),
                      'jobkorea_requests': 0}
            if not ok:
                print(json.dumps(report, ensure_ascii=False))
                return 2
            if args.check:
                ip = egress_ip()
                report.update(ip_check_requests=1, source_ip_registered=ip in config.registered_ips)
                print(json.dumps(report, ensure_ascii=False))
                return 0 if report['source_ip_registered'] else 2
            if environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
                print(json.dumps({'status': 'BLOCKED', 'reason': 'PM_ACTIVATION_REQUIRED', 'jobkorea_requests': 0}))
                return 2
            source = LiveApiSource(approval, config, limits)
            if args.probe:
                result = probe(source, keywords[0])
                print(json.dumps({'command': 'api-probe', 'jobkorea_requests': source.requests, **result},
                                 ensure_ascii=False))
                return 0
        with _connect() as connection:
            result = run_api_collection(connection, source, keywords=keywords, limits=limits)
    except ApiResponseError as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': exc.code}))
        return 2
    except FetchError as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': exc.reason, 'http_status': exc.http_status}))
        return 2
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': type(exc).__name__}))
        return 2
    except Exception as exc:  # e.g. a DB error: one JSON line, never a secret-bearing traceback
        print(json.dumps({'status': 'FAILED', 'reason': type(exc).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result['status'] in ('SUCCEEDED', 'PARTIAL', 'SKIPPED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
