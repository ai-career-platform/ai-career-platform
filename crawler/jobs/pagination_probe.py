"""Read-only JobKorea pagination/supply probe: robots.txt + result pages 1 and 2 per keyword. No details, no writes.

    python -m crawler.jobs.pagination_probe --policy-file <T61 harvest approval> [--keyword K ...] [--out FILE]
    python -m crawler.jobs.pagination_probe --policy-file F --check        # preflight only, no network

Every request goes through the existing T61 path (``harvest.LiveSource``): approval scope per URL, robots.txt,
>= 2 s spacing (or crawl-delay), one request at a time, request budget, stop on 3xx/401/403/429/challenge.
At most 1 + 2 x keywords requests (13 for the six night keywords). Nothing is written to PostgreSQL; posting ids
are only *read* from the DB to count which candidates are already stored. The JSON result holds ids, counts,
HTTP status and timing only (no page HTML).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_result_page
from crawler.jobs import harvest as h
from crawler.jobs.import_jobkorea_html import FetchBlocked, FetchError, _fetch_allowed, load_approval_file
from crawler.policy.source_approval_gate import paged_search_url

# The result count printed on a search page. The markup is not documented: best effort, None when not found.
TOTAL_PATTERNS = (re.compile(r'총\s*(?:<[^>]{0,200}>\s*)*([\d,]{1,9})\s*(?:<[^>]{0,200}>\s*)*건'),
                  re.compile(r'"totalCount"\s*:\s*"?([\d,]{1,9})'))


def extract_total(html):
    for pattern in TOTAL_PATTERNS:
        match = pattern.search(html or '')
        if match:
            return int(match.group(1).replace(',', ''))
    return None


def limits_for(keywords):
    return h.HarvestLimits(max_pages=2, max_new_details=0, max_revisits=0, known_page_stop=2,
                           max_requests=1 + 2 * len(keywords), deadline_seconds=600)


def fetch_page(source, keyword, page):
    url = paged_search_url(h.search_url(keyword), page)
    source._permit(url)
    started = time.monotonic()
    html = _fetch_allowed(url, source.robots(), source._before_request)
    return {'page': page, 'url': url, 'http_status': 200, 'seconds': round(time.monotonic() - started, 2),
            'ids': [h.posting_id(u) for u in parse_jobkorea_result_page(html)], 'total_shown': extract_total(html)}


def probe(source, keywords, known_ids=lambda ids: set()):
    out = {'started_utc': datetime.now(timezone.utc).isoformat(), 'keywords': {}, 'stop_reason': None}
    try:
        for keyword in keywords:
            pages = []
            for page in (1, 2):
                try:
                    pages.append(fetch_page(source, keyword, page))
                except FetchBlocked:          # subclass of FetchError: a block signal must stop the whole probe
                    raise
                except FetchError as exc:
                    pages.append({'page': page, 'error': h._code(exc.reason),
                                  'http_status': getattr(exc, 'http_status', None)})
                    break
            p1 = pages[0].get('ids', [])
            p2 = pages[1].get('ids', []) if len(pages) > 1 else []
            out['keywords'][keyword] = {
                'pages': pages, 'page1_count': len(p1), 'page2_count': len(p2),
                'overlap_page1_page2': len(set(p1) & set(p2)),
                'page_repeated': bool(p1) and p1 == p2,
                'pagination_works': bool(p2) and not (set(p2) <= set(p1)),
                'total_shown': pages[0].get('total_shown')}
    except FetchBlocked as exc:          # 3xx/401/403/429/challenge/budget/expiry: stop everything
        out['stop_reason'] = h._code(exc.reason)
    all_ids = [i for k in out['keywords'].values() for p in k['pages'] for i in p.get('ids', [])]
    unique = set(all_ids)
    stored = known_ids(sorted(unique))
    checked = [k for k in out['keywords'].values() if k['page2_count']]
    out.update(http_requests=source.requests, ids_seen=len(all_ids), unique_ids=len(unique),
               cross_keyword_duplicates=len(all_ids) - len(unique), already_in_db=len(stored),
               new_candidates=len(unique - stored),
               pagination_live=('NOT_RUN' if not out['keywords'] else
                                'PASS' if checked and all(k['pagination_works'] for k in checked) else 'FAIL'),
               ended_utc=datetime.now(timezone.utc).isoformat())
    return out


def _known(ids):
    from crawler.jobs.nightly import _connect
    with _connect() as connection:
        connection.read_only = True
        rows = connection.execute("SELECT external_posting_id FROM crawler_training.postings"
                                  " WHERE source_code = 'jobkorea_live' AND external_posting_id = ANY(%s)",
                                  (list(ids),)).fetchall()
    return {r[0] for r in rows}


def main(argv=None):
    import os
    from crawler.jobs.night_crawl import NIGHT_KEYWORDS
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--policy-file', required=True)
    p.add_argument('--keyword', action='append')
    p.add_argument('--out')
    p.add_argument('--check', action='store_true')
    args = p.parse_args(argv)
    keywords = args.keyword or list(NIGHT_KEYWORDS)
    limits = limits_for(keywords)
    approval = load_approval_file(args.policy_file)
    ok, problems, urls = h.preflight(approval, limits, keywords)
    if args.check or not ok:
        print(json.dumps({'command': 'pagination-probe-preflight', 'ok': ok, 'problems': problems,
                          'limits': asdict(limits), 'external_requests': 0}, ensure_ascii=False))
        return 0 if ok else 2
    if os.environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
        print(json.dumps({'status': 'BLOCKED', 'reason': 'PM_ACTIVATION_REQUIRED', 'external_requests': 0}))
        return 2
    result = probe(h.LiveSource(approval, limits), keywords, _known)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text)
    print(text)
    return 0 if result['pagination_live'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
