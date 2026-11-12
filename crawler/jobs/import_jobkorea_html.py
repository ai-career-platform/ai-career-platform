"""Small manual HTML/HTTP batch, reusing JSON-LD normalization and local upsert.

Imported HTML is labeled separately from live HTTP results. Only use inputs
and URLs whose collection, storage and display are permitted by the provider.
No live compatibility is implied by constructed HTML tests.

Every live HTTP path goes through ``fetch_pages``, which checks each target URL against the
caller-supplied T61 approval (``check_collection_permission``) before any network request,
including detail URLs discovered on a search page (checked one by one, with ``discovered_from``
set to the search page). Without an ALLOWED decision it raises
``FetchBlocked('UNAPPROVED_SOURCE')`` and sends nothing.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import time
from urllib.robotparser import RobotFileParser
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from datetime import datetime, timezone

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_html, parse_jobkorea_list_html, _source_id
from crawler.storage.postgres import connect_local_training_db, PostgresPostingStore
from crawler.storage.staging import connect_configured_database
from crawler.policy.source_approval_gate import CollectionIntent, SourceApproval, check_collection_permission

USER_AGENT = 'AICareerPlatform-Learning/1.0'
MAX_BYTES = 2_000_000


class FetchError(RuntimeError):
    def __init__(self, reason, *, http_status=None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status

    def to_dict(self):
        return {'reason': self.reason, 'http_status': self.http_status}


class FetchBlocked(FetchError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url):
    try:
        with build_opener(_NoRedirect()).open(Request(url, headers={'User-Agent': USER_AGENT}), timeout=15) as response:
            if response.status != 200:
                raise FetchError('UNEXPECTED_HTTP_STATUS', http_status=response.status)
            allowed_types = {'text/html', 'application/xhtml+xml'}
            if url.endswith('/robots.txt'):
                allowed_types.add('text/plain')
            if response.headers.get_content_type() not in allowed_types:
                raise FetchError('NON_HTML_RESPONSE')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError('RESPONSE_TOO_LARGE')
            return data.decode(response.headers.get_content_charset() or 'utf-8', errors='strict')
    except HTTPError as exc:
        error = FetchBlocked if 300 <= exc.code < 400 or exc.code in (401, 403, 429) else FetchError
        raise error(f'HTTP_{exc.code}', http_status=exc.code) from None
    except (TimeoutError, URLError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, 'reason', None), TimeoutError)
        raise FetchError('TIMEOUT' if timed_out else 'NETWORK_ERROR') from None
    except UnicodeError:
        raise FetchError('INVALID_ENCODING') from None


def _fetch_allowed(url, robots):
    if not robots.can_fetch(USER_AGENT, url):
        raise FetchBlocked('ROBOTS_DISALLOW')
    time.sleep(max(2, robots.crawl_delay(USER_AGENT) or 0))
    html = _get(url)
    if any(marker in html.lower() for marker in ('captcha', 'access denied')):
        raise FetchBlocked('ACCESS_CHALLENGE')
    return html


def load_approval_file(path):
    """Private T61 approval JSON -> SourceApproval, or None when absent/invalid. Never raises."""
    try:
        values = dict(json.loads(Path(path).read_text(encoding='utf-8')))
        for key in ('valid_from_utc', 'review_due_utc'):
            values[key] = datetime.fromisoformat(values[key].replace('Z', '+00:00'))
        for key in ('allowed_urls', 'allowed_purposes'):
            values[key] = tuple(values[key])
        return SourceApproval(**values)
    except Exception:
        return None


def _permit(approval, purpose, url, calls, now, discovered_from=None):
    decision = check_collection_permission(approval, CollectionIntent('jobkorea', url, 'WEB', purpose or '', calls, now,
                                                                      discovered_from=discovered_from))
    if not decision.allowed:
        raise FetchBlocked('UNAPPROVED_SOURCE')


def fetch_pages(urls=None, *, list_url=None, limit=10, approval=None, purpose=None, now=None):
    """One optional public search page, then at most ten explicit detail URLs.

    T61 gate: ``approval`` (SourceApproval) and ``purpose`` must admit every URL before it is
    requested; robots.txt is the one compliance request counted in the budget, not a target.
    """
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('limit must be between 1 and 10')
    urls = urls or []
    if list_url:
        parts = urlsplit(list_url)
        if (urls or parts.scheme != 'https' or parts.hostname != 'www.jobkorea.co.kr'
                or parts.username or parts.password or parts.port or parts.fragment
                or parts.path not in ('/Search', '/Search/')):
            raise ValueError('Provide one public www.jobkorea.co.kr/Search URL')
    elif not 1 <= len(urls) <= limit:
        raise ValueError('Provide 1 to 10 URLs')
    for url in urls:
        _source_id(url)
        if urlsplit(url).hostname != 'www.jobkorea.co.kr':
            raise ValueError('Live fetch requires the www.jobkorea.co.kr origin')
    now = now or datetime.now(timezone.utc)
    calls = 1 + (1 + limit if list_url else len(urls))
    for target in [list_url] if list_url else urls:
        _permit(approval, purpose, target, calls, now)
    robots = RobotFileParser()
    robots_text = _get('https://www.jobkorea.co.kr/robots.txt')
    if 'user-agent:' not in robots_text.lower():
        raise FetchBlocked('INVALID_ROBOTS_RESPONSE')
    robots.parse(robots_text.splitlines())
    if list_url:
        urls = parse_jobkorea_list_html(_fetch_allowed(list_url, robots), limit=limit)
        if not urls:
            raise FetchError('NO_POSTING_LINKS')
        for url in urls:
            # Each discovered link is checked on its own; an approved search page does not
            # approve its links wholesale (exact listing, or the approval's bounded discovery scope).
            _permit(approval, purpose, url, calls, now, discovered_from=list_url)
    for url in dict.fromkeys(urls):
        try:
            yield url, _fetch_allowed(url, robots)
        except FetchBlocked:
            raise
        except FetchError as exc:
            yield url, exc
        except OSError:
            yield url, FetchError('NETWORK_ERROR')


def import_pages(pages, store, *, live=False):
    if isinstance(pages, (list, tuple)) and len(pages) > 10:
        raise ValueError('At most 10 pages per batch')
    report = dict(inserted=0, updated=0, unchanged=0, invalid=0, duplicates=0, errors=[])
    seen = set()
    iterator = iter(pages)
    for count in range(1, 11):
        try:
            url, html = next(iterator)
        except StopIteration:
            break
        except FetchError as exc:
            report['stopped'] = exc.to_dict()
            break
        stage = 'fetch' if isinstance(html, FetchError) else 'parse'
        try:
            if isinstance(html, FetchError):
                raise html
            posting = replace(parse_jobkorea_html(html=html, source_url=url).normalized(),
                              source_code='jobkorea_live' if live else 'jobkorea_imported')
            key = (posting.source_code, posting.external_posting_id)
            if key in seen:
                report['duplicates'] += 1
                continue
            stage = 'store'
            result = store.upsert(posting)
            seen.add(key)
            report[result] += 1
        except Exception as exc:
            report['invalid'] += 1
            error = exc.to_dict() if isinstance(exc, FetchError) else {'reason': type(exc).__name__}
            report['errors'].append({'item': count, 'stage': stage, **error})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', action='append', help='Explicit permitted JobKorea detail URL, maximum 10')
    parser.add_argument('--list-html', help='Extract up to ten canonical detail URLs from saved list HTML; no HTTP or DB')
    parser.add_argument('--list-url', help='Permitted public search URL; fetch then follow up to --limit detail links')
    parser.add_argument('--limit', type=int, default=10, choices=range(1, 11))
    parser.add_argument('--html', action='append', help='Permitted UTF-8 HTML files, one per URL; omitted: live HTTP')
    parser.add_argument('--policy-file', help='Private T61 approval JSON; required for live HTTP (checked per URL)')
    args = parser.parse_args()
    if args.list_html:
        if args.url or args.html or args.list_url:
            parser.error('--list-html is an offline URL extraction mode; do not combine with --url/--html')
        path = Path(args.list_html)
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError('HTML exceeds size limit')
            print(json.dumps({'mode': 'offline_list_html', 'urls': parse_jobkorea_list_html(path.read_text(encoding='utf-8'))}))
            return 0
        except (OSError, ValueError) as exc:
            print(json.dumps({'status': 'STOPPED', 'reason': type(exc).__name__}))
            return 2
    if args.list_url and (args.url or args.html):
        parser.error('--list-url cannot be combined with --url/--html')
    if not args.list_url and (not args.url or not 1 <= len(args.url) <= args.limit or args.html and len(args.html) != len(args.url)):
        parser.error('Provide 1–10 URLs and matching HTML files')
    try:
        if args.html:
            pages = []
            for url, name in zip(args.url, args.html):
                path = Path(name)
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('HTML exceeds size limit')
                pages.append((url, path.read_text(encoding='utf-8')))
        else:
            approval = load_approval_file(args.policy_file) if args.policy_file else None
            pages = fetch_pages(args.url, list_url=args.list_url, limit=args.limit,
                                approval=approval, purpose='manual_collection')
        with connect_configured_database() as connection:
            report = import_pages(pages, PostgresPostingStore(connection), live=not args.html)
        print(json.dumps({'mode': 'imported_html' if args.html else 'live_http', **report}))
        return 2 if report.get('stopped') else 1 if report['invalid'] else 0
    except Exception as exc:
        error = exc.to_dict() if isinstance(exc, FetchError) else {'reason': type(exc).__name__}
        print(json.dumps({'status': 'STOPPED', **error}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
