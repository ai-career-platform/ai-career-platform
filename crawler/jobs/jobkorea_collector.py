"""JobKorea official XML API -> GCP Cloud SQL (career schema), run on the GCP VM (registered egress IP).

One run:
1. reads the target data source and its known JobKorea ids READ ONLY (``career.job_posting_external_refs``);
   stops with no API request when the source row is missing or the 1,000-posting cumulative cap is reached;
2. requests keyword result pages (official XML API, ``crawler.jobs.jobkorea_api.LiveApiSource``: T61 check
   before every request incl. the provider's storage permission, registered IP, >= 2 s spacing, stop on any
   HTTP/XML error) only until enough NEW postings were seen, de-duplicating ids across keywords;
3. parses each ``<Items>`` with the PR #378 parser (``crawler.adapters.jobkorea_api_xml``);
4. plans and applies with the existing Cloud SQL writer (``crawler.jobs.gcp_sync.sync_rows``): identity
   ``job_posting_external_refs (source_id, external_id=GI_No)``, INSERT new postings, UPDATE only changed
   fields, no write for identical rows, an empty API value never clears a stored one, nothing deleted,
   one transaction per run (rollback on any error), run ledger in ``career.ingestion_runs``.

New postings are stored as ``draft`` (not shown on the website) unless ``JOBKOREA_COLLECTOR_PUBLISH=1``, which
the PM enables only after the JobKorea attribution is live on the website.

Modes::

    python -m crawler.jobs.jobkorea_collector dry-run --fixture-dir DIR                          # no API request
    python -m crawler.jobs.jobkorea_collector dry-run --policy-file F --api-config F [--new 100]  # API, no writes
    python -m crawler.jobs.jobkorea_collector run     --policy-file F --api-config F [--new 100]

Target connection: ``gcp_sync.connect_target`` (``GCP_SYNC_TARGET_*``: TLS verify-full, non-superuser role).
API URL/identifier: the private API config file. Neither is ever printed. Fixture data is never written to the
target by the CLI (``run`` refuses ``--fixture-dir``).
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from crawler.adapters.jobkorea_api_xml import (MAX_TOTAL_RESULTS, ApiResponseError, InvalidPosting, item_posting_id,
                                               parse_api_response, to_posting)
from crawler.jobs import gcp_sync as sync
from crawler.jobs.import_jobkorea_html import FetchBlocked, FetchError, load_approval_file
from crawler.jobs.jobkorea_api import ApiLimits, FixtureApiSource, LiveApiSource, load_api_config, preflight
from crawler.policy.provider_permission import PM_POLICY_MAX_ITEMS

DEFAULT_SOURCE_CODE = 'jobkorea_api'
WRITER = 'jobkorea_api'               # ingestion_runs.error_summary['source']: the single-writer marker
RUN_LOCK_KEY = 337002                 # one collector run at a time (held for the whole run)


@dataclass
class FetchStats:
    api_requests: int = 0
    pages: int = 0
    received: int = 0                 # <Items> elements in all responses
    parsed: int = 0                   # mapped onto a posting
    invalid: int = 0                  # missing required field (e.g. GI_No, title, company)
    cross_keyword_duplicates: int = 0
    known_in_target: int = 0
    new_candidates: int = 0
    total_results: dict = field(default_factory=dict)
    stop_reason: str | None = None


def collect_rows(source, *, keywords, limits, known_ids, want, source_code, seen_at):
    """API pages -> SourceRows (one per GI_No). Stops paging once ``want`` new ids were seen. Never writes."""
    stats, rows, seen, previous = FetchStats(), [], set(), {}
    active = list(dict.fromkeys(keywords))
    try:
        for page in range(1, limits.max_pages + 1):
            for keyword in list(active):
                if stats.new_candidates >= want:
                    return rows, stats
                data = source.fetch(keyword, page, limits.page_size, limits.order)
                try:
                    parsed = parse_api_response(data, require_total=False)
                except ApiResponseError as exc:
                    raise FetchBlocked(exc.code) from None
                stats.pages += 1
                stats.received += len(parsed.items)
                stats.total_results.setdefault(keyword, parsed.total_results)
                ids = [item_posting_id(item) for item in parsed.items]
                if ids and previous.get(keyword) == ids:
                    active.remove(keyword)          # the API served the same page again: stop this keyword
                    continue
                previous[keyword] = ids
                for external_id, item in zip(ids, parsed.items):
                    if external_id is not None and external_id in seen:
                        stats.cross_keyword_duplicates += 1
                        continue
                    try:
                        posting = to_posting(item, source_code=source_code)
                    except InvalidPosting:
                        stats.invalid += 1
                        continue
                    seen.add(external_id)
                    stats.parsed += 1
                    if external_id in known_ids:
                        stats.known_in_target += 1
                    else:
                        stats.new_candidates += 1
                    rows.append(sync.SourceRow(source_code, external_id, posting.to_dict(), seen_at))
                last_page = (limits.max_pages if parsed.total_results is None
                             else -(-min(parsed.total_results, MAX_TOTAL_RESULTS) // limits.page_size))
                if not parsed.items or len(parsed.items) < limits.page_size or page >= last_page:
                    active.remove(keyword)
            if not active:
                break
        stats.stop_reason = 'SUPPLY_EXHAUSTED' if stats.new_candidates < want else None
    except FetchError as exc:          # FetchBlocked included: stop at once, no retry
        stats.stop_reason = exc.reason
        raise
    finally:
        stats.api_requests = source.requests if getattr(source, 'live', False) else 0
    return rows, stats


def run_collector(target, source, *, mode, keywords, limits, source_code=DEFAULT_SOURCE_CODE, publish=False,
                  cap=PM_POLICY_MAX_ITEMS, now=None):
    """One collector run against an open target connection. Returns a secret-free result dict."""
    now = now or datetime.now(timezone.utc)
    base = {'mode': mode, 'source_code': source_code, 'publish': publish, 'source': WRITER,
            'api_source': 'live' if getattr(source, 'live', False) else 'fixture'}
    if mode not in ('dry-run', 'run'):
        return dict(base, status='FAILED', error_code='MODE_INVALID')
    with target.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', (RUN_LOCK_KEY,))
        locked = cursor.fetchone()[0]
    target.commit()
    if not locked:
        return dict(base, status='SKIPPED', reason='COLLECTOR_ALREADY_RUNNING', api_requests=0)
    try:
        try:
            with target.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                _, refs, _, _ = sync.load_target(cursor, source_code, ())
        except sync.SyncError as error:
            return dict(base, status='FAILED', error_code=error.code, api_requests=0)
        finally:
            target.rollback()
        remaining = max(cap - len(refs), 0)
        want = min(limits.target_new, remaining)
        if want <= 0:
            return dict(base, status='STOPPED', reason='CUMULATIVE_LIMIT', target_refs=len(refs), api_requests=0)
        try:
            rows, stats = collect_rows(source, keywords=keywords, limits=limits, known_ids=set(refs), want=want,
                                       source_code=source_code, seen_at=now)
        except FetchError as exc:
            # A block (403/429/redirect/T61) or a non-XML answer: nothing is written for this run.
            return dict(base, status='STOPPED', reason=exc.reason, http_status=exc.http_status,
                        api_requests=source.requests if getattr(source, 'live', False) else 0)
        base = dict(base, api=asdict(stats), want=want)
        result = sync.sync_rows(target, rows, base, now, mode=mode, source_code=source_code, publish=publish,
                                preserve_on_null=True, max_new=want, cumulative_cap=cap)
        result.setdefault('api', asdict(stats))
        return result
    finally:
        target.rollback()
        with target.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', (RUN_LOCK_KEY,))
        target.commit()


# ---------------------------------------------------------------- CLI
def main(argv=None, *, environ=None, connect_target=None):
    from crawler.jobs.night_crawl import NIGHT_KEYWORDS
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=('dry-run', 'run'))
    parser.add_argument('--fixture-dir', help='offline XML pages (dry-run only): no API request')
    parser.add_argument('--policy-file', help='private T61 PM approval (collection_method API, api_collection)')
    parser.add_argument('--api-config', help='private API config (endpoint URLs, registered IPs)')
    parser.add_argument('--new', type=int, default=100)
    parser.add_argument('--size', type=int, default=100)
    parser.add_argument('--pages', type=int, default=5)
    parser.add_argument('--max-requests', type=int, default=30)
    parser.add_argument('--deadline-seconds', type=int, default=1800)
    parser.add_argument('--keyword', action='append', help='default: the six T61 keywords')
    args = parser.parse_args(argv)
    source_code = (environ.get('JOBKOREA_COLLECTOR_SOURCE_CODE') or DEFAULT_SOURCE_CODE).strip()
    publish = environ.get('JOBKOREA_COLLECTOR_PUBLISH') == '1'
    try:
        limits = ApiLimits(target_new=args.new, page_size=args.size, max_pages=args.pages,
                           max_requests=args.max_requests, deadline_seconds=args.deadline_seconds)
        keywords = args.keyword or list(NIGHT_KEYWORDS)
        if args.fixture_dir:
            if args.mode != 'dry-run':
                print(json.dumps({'status': 'FAILED', 'error_code': 'FIXTURE_WRITE_REFUSED', 'api_requests': 0}))
                return 2
            fixture_keywords, source = FixtureApiSource.from_dir(args.fixture_dir)
            keywords = args.keyword or fixture_keywords
        else:
            approval = load_approval_file(args.policy_file) if args.policy_file else None
            config = load_api_config(args.api_config) if args.api_config else None
            ok, problems = preflight(approval, config, limits)
            if not ok:
                print(json.dumps({'status': 'BLOCKED', 'problems': problems, 'api_requests': 0}, ensure_ascii=False))
                return 2
            if environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
                print(json.dumps({'status': 'BLOCKED', 'reason': 'PM_ACTIVATION_REQUIRED', 'api_requests': 0}))
                return 2
            source = LiveApiSource(approval, config, limits)
        target = (connect_target or sync.connect_target)(environ)
        try:
            result = run_collector(target, source, mode=args.mode, keywords=keywords, limits=limits,
                                   source_code=source_code, publish=publish)
        finally:
            target.close()
    except sync.SyncError as error:
        result = {'status': 'FAILED', 'error_code': error.code, 'api_requests': 0}
    except (ValueError, OSError) as exc:
        result = {'status': 'FAILED', 'error_code': type(exc).__name__}
    except Exception as exc:  # one JSON line, never a secret-bearing traceback
        result = {'status': 'FAILED', 'error_code': f'RUN_{type(exc).__name__}'}
    print(json.dumps(result, default=str, ensure_ascii=False))
    return 0 if result.get('status') in ('SUCCEEDED', 'DRY_RUN', 'PARTIAL') else 1


if __name__ == '__main__':
    raise SystemExit(main())
