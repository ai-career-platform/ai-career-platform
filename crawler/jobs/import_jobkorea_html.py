"""Small manual HTML/HTTP batch, reusing JSON-LD normalization and local upsert.

Imported HTML is labeled separately from live HTTP results. Only use inputs
and URLs whose collection, storage and display are permitted by the provider.
No live compatibility is implied by constructed HTML tests.
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
from urllib.error import HTTPError
from urllib.parse import urlsplit

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_html, _source_id
from crawler.storage.postgres import connect_local_training_db, PostgresPostingStore

USER_AGENT = 'AICareerPlatform-Learning/1.0'
MAX_BYTES = 2_000_000


class FetchBlocked(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url):
    try:
        with build_opener(_NoRedirect).open(Request(url, headers={'User-Agent': USER_AGENT}), timeout=15) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('Response exceeds size limit')
            return data.decode(response.headers.get_content_charset() or 'utf-8', errors='strict')
    except HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308, 401, 403, 429):
            raise FetchBlocked(f'Access stopped: HTTP {exc.code}') from None
        raise


def fetch_pages(urls):
    """At most ten explicit public URLs; no discovery, retry or redirects."""
    if not 1 <= len(urls) <= 10:
        raise ValueError('Provide 1 to 10 URLs')
    for url in urls:
        _source_id(url)
        if urlsplit(url).hostname != 'www.jobkorea.co.kr':
            raise ValueError('Live fetch requires the www.jobkorea.co.kr origin')
    robots = RobotFileParser()
    robots.parse(_get('https://www.jobkorea.co.kr/robots.txt').splitlines())
    for url in dict.fromkeys(urls):
        if not robots.can_fetch(USER_AGENT, url):
            raise FetchBlocked('robots.txt disallows this request')
        time.sleep(max(2, robots.crawl_delay(USER_AGENT) or 0))
        try:
            html = _get(url)
            if any(marker in html.lower() for marker in ('captcha', 'access denied')):
                raise FetchBlocked('Access challenge detected')
            yield url, html
        except FetchBlocked:
            raise
        except (OSError, ValueError):
            # Empty input produces a sanitized per-page parse failure.
            yield url, ''


def import_pages(pages, store, *, live=False):
    if isinstance(pages, (list, tuple)) and len(pages) > 10:
        raise ValueError('At most 10 pages per batch')
    report = dict(inserted=0, updated=0, unchanged=0, invalid=0, duplicates=0, errors=[])
    seen = set()
    for count, (url, html) in enumerate(pages, 1):
        if count > 10:
            raise ValueError('At most 10 pages per batch')
        try:
            posting = replace(parse_jobkorea_html(html=html, source_url=url).normalized(),
                              source_code='jobkorea_live' if live else 'jobkorea_imported')
            key = (posting.source_code, posting.external_posting_id)
            if key in seen:
                report['duplicates'] += 1
                continue
            result = store.upsert(posting)
            seen.add(key)
            report[result] += 1
        except Exception as exc:
            report['invalid'] += 1
            report['errors'].append({'item': count, 'reason': type(exc).__name__})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', action='append', required=True, help='Explicit permitted JobKorea detail URL, maximum 10')
    parser.add_argument('--html', action='append', help='Permitted UTF-8 HTML files, one per URL; omitted: live HTTP')
    args = parser.parse_args()
    if not 1 <= len(args.url) <= 10 or args.html and len(args.html) != len(args.url):
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
            pages = fetch_pages(args.url)
        with connect_local_training_db(os.environ.get('CRAWLER_LOCAL_DATABASE_URL', '')) as connection:
            report = import_pages(pages, PostgresPostingStore(connection), live=not args.html)
        print(json.dumps({'mode': 'imported_html' if args.html else 'live_http', **report}))
        return 1 if report['invalid'] else 0
    except Exception as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
