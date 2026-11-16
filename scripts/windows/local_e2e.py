"""Local E2E on the Windows crawler PC: fixture HTML -> parser -> normalizer -> PostgresPostingStore
-> local PostgreSQL -> REST API (uvicorn on 127.0.0.1) -> response check. Zero external requests.

    .venv\\Scripts\\python.exe scripts\\windows\\local_e2e.py

Run inside crawler-local-env.ps1 (runtime role crawler_local). Every crawler/API process is started
under scripts/windows/no_egress.py. HTML pages are derived from the repo fixture
crawler/fixtures/jobkorea_user_detail_jsonld.html with reserved synthetic posting IDs and a run
marker in the title, so the rows are clearly test data. Evidence JSON goes to
<AICP_DATA_ROOT>/logs/e2e-<stamp>/evidence.json.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from crawler.storage.postgres import connect_local_training_db

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FIXTURE = (ROOT / 'crawler/fixtures/jobkorea_user_detail_jsonld.html').read_text(encoding='utf-8')
DATA_ROOT = Path(os.environ.get('AICP_DATA_ROOT') or r'C:\dev\crawler-data')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')
OUT = DATA_ROOT / 'logs' / f'e2e-{STAMP}'
RUN = uuid.uuid4().hex[:8]
MARK = f'[LOCAL-E2E {RUN}]'
BASE_ID = 990000000 + int(RUN, 16) % 900000 * 10   # reserved synthetic range, unique per run
URL = 'https://www.jobkorea.co.kr/Recruit/GI_Read/{}'
PY = sys.executable
GUARD = str(HERE / 'no_egress.py')


def page(n, title='데이터 엔지니어', valid='2027-01-31T23:59'):
    pid = str(BASE_ID + n)
    html = (FIXTURE.replace('50242499', pid)
            .replace('2027 쿠도커뮤니케이션㈜ 신입/경력 공개채용', f'{MARK} {title} {n}')
            .replace('2026-11-15T23:59', valid))
    path = OUT / 'html' / f'{pid}-{abs(hash((title, valid))) % 10**6}.html'
    path.write_text(html, encoding='utf-8')
    return URL.format(pid), str(path)


def invalid_page(n):
    pid = str(BASE_ID + n)
    path = OUT / 'html' / f'{pid}-invalid.html'
    path.write_text('<html><body>no JobPosting JSON-LD here</body></html>', encoding='utf-8')
    return URL.format(pid), str(path)


def run_cli(name, pages):
    args = [PY, GUARD, '-m', 'crawler.jobs.import_jobkorea_html']
    for url, path in pages:
        args += ['--url', url, '--html', path]
    t = time.monotonic()
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (OUT / f'{name}.log').write_text(proc.stdout + proc.stderr, encoding='utf-8')
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    egress = [l for l in proc.stderr.splitlines() if l.startswith('EGRESS_ATTEMPTS=')]
    return {'command': 'python no_egress.py -m crawler.jobs.import_jobkorea_html ' + ' '.join(
                f'--url {u} --html <fixture>' for u, _ in pages),
            'exit_code': proc.returncode, 'seconds': round(time.monotonic() - t, 2),
            'egress': egress[-1] if egress else 'EGRESS_ATTEMPTS=?', 'report': report}


def rows():
    with connect_local_training_db(os.environ['CRAWLER_LOCAL_DATABASE_URL']) as c:
        return [{'source_code': r[0], 'external_posting_id': r[1], 'title': r[2], 'expires_on': r[3], 'updated_at': r[4]}
                for r in c.execute("SELECT source_code, external_posting_id, payload->>'title', payload->>'expires_on', updated_at::text"
                                   " FROM crawler_training.postings WHERE payload->>'title' LIKE %s ORDER BY external_posting_id",
                                   (MARK + '%',)).fetchall()]


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def api_check():
    port = free_port()
    log = open(OUT / 'uvicorn.log', 'w', encoding='utf-8')
    proc = subprocess.Popen([PY, GUARD, '-m', 'uvicorn', 'backend.training_jobs_api:app', '--host', '127.0.0.1',
                             '--port', str(port), '--log-level', 'info'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        url = f'http://127.0.0.1:{port}/jobs/collected?' + urllib.parse.urlencode({'title': MARK, 'limit': 20})
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            result = {'method': 'GET', 'url': url, 'status': resp.status, 'count': len(body),
                      'items': [{k: item.get(k) for k in ('external_posting_id', 'title', 'expires_on', 'source_code', 'evidence', 'collected_at')}
                                for item in body]}
        bad = urllib.parse.urlencode({'employment_type': 'not-a-type'})
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/jobs/collected?{bad}', timeout=10)
            result['invalid_query_status'] = 200
        except urllib.error.HTTPError as exc:
            result['invalid_query_status'] = exc.code
        return result
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        log.close()
        text = (OUT / 'uvicorn.log').read_text(encoding='utf-8', errors='replace')
        result_tail = [l for l in text.splitlines() if 'Traceback' in l or 'ERROR' in l]
        api_errors.extend(result_tail)


api_errors = []

if __name__ == '__main__':
    import urllib.parse  # noqa: E402
    import urllib.error  # noqa: E402
    (OUT / 'html').mkdir(parents=True, exist_ok=True)
    ev = {'run_marker': MARK, 'synthetic_posting_ids': [str(BASE_ID + n) for n in (1, 2, 3)], 'steps': {}}
    a1, b1 = page(1), page(2)
    ev['steps']['1_first_import'] = run_cli('r1', [a1, b1, invalid_page(3), a1])
    ev['steps']['1_rows'] = rows()
    ev['steps']['2_same_again'] = run_cli('r2', [a1, b1])
    ev['steps']['2_rows'] = rows()
    ev['steps']['3_title_and_deadline_changed'] = run_cli('r3', [page(1, title='시니어 데이터 엔지니어'), page(2, valid='2027-03-31T23:59')])
    ev['steps']['3_rows'] = rows()
    ev['steps']['4_api'] = api_check()
    ev['steps']['4_api_log_errors'] = api_errors
    r1, r2, r3 = (ev['steps'][k]['report'] for k in ('1_first_import', '2_same_again', '3_title_and_deadline_changed'))
    final = {r['external_posting_id']: r for r in ev['steps']['3_rows']}
    a_id, b_id = ev['synthetic_posting_ids'][:2]
    checks = {
        'insert_new_postings': (r1['inserted'], r1['duplicates'], r1['invalid']) == (2, 1, 1),
        'invalid_html_excluded_with_reason': [e.get('stage') for e in r1['errors']] == ['parse'] and len(ev['steps']['1_rows']) == 2,
        'rerun_no_duplicate_insert': (r2['inserted'], r2['unchanged']) == (0, 2) and len(ev['steps']['2_rows']) == 2,
        'title_change_updated': r3['updated'] == 2 and final[a_id]['title'].startswith(f'{MARK} 시니어'),
        'deadline_change_updated': final[b_id]['expires_on'] == '2027-03-31',
        'updated_at_advanced': all(x['updated_at'] < final[x['external_posting_id']]['updated_at'] for x in ev['steps']['2_rows']),
        'api_200_returns_db_rows': ev['steps']['4_api']['status'] == 200 and {i['external_posting_id'] for i in ev['steps']['4_api']['items']} == {a_id, b_id},
        'api_matches_db_titles': {i['external_posting_id']: i['title'] for i in ev['steps']['4_api']['items']} == {k: v['title'] for k, v in final.items()},
        'api_rejects_invalid_query': ev['steps']['4_api']['invalid_query_status'] == 422,
        'api_log_no_errors': not api_errors,
        'zero_egress': all(ev['steps'][k]['egress'] == 'EGRESS_ATTEMPTS=0' for k in ('1_first_import', '2_same_again', '3_title_and_deadline_changed')),
    }
    ev['checks'] = checks
    ev['status'] = 'PASS' if all(checks.values()) else 'FAIL'
    (OUT / 'evidence.json').write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'status': ev['status'], 'checks': checks, 'evidence': str(OUT / 'evidence.json')}, ensure_ascii=False, indent=1))
    raise SystemExit(0 if ev['status'] == 'PASS' else 1)
