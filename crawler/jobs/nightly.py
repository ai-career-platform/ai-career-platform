"""Nightly JobKorea harvest orchestration (21:00-08:00 KST) with Slack reports.

One invocation per night (Windows task ``AICP-JobKorea-Nightly``). It repeats the existing T61-gated
``harvest.run_harvest`` in chunks until the night's NEW INSERT target is reached, the window ends,
supply runs out or a stop signal (403/429/CAPTCHA/budget/approval expiry) arrives.

Safety:
- ``live`` needs a valid T61 harvest approval file AND ``CRAWLER_LIVE_SCHEDULE_APPROVED=1``; otherwise the
  run is BLOCKED before any request. Every chunk's ``deadline_seconds`` ends at 08:00 KST, and the harvest's
  LiveSource refuses a request after its deadline, so no external HTTP is sent after 08:00.
- ``test`` sends no external HTTP and writes nothing to PostgreSQL (window, lock and counters only).
- NEW INSERTs are counted from ``harvest_items.outcome = 'inserted'`` of LIVE runs with real HTTP and an
  existing posting row (``INSERT ... ON CONFLICT DO NOTHING RETURNING`` decided the outcome). Fixture
  runs, updates and duplicates are never counted.
- Slack: start / hourly progress / target reached / end / failure / blocked. Each message key is sent at
  most once per night (ledger file); a value that was not measured is shown as NOT_RUN or UNVERIFIED,
  never as 0. Slack failures never change the crawl. The webhook URL is never printed or logged.

Usage::

    python -m crawler.jobs.nightly window [--now ISO]
    python -m crawler.jobs.nightly run --mode test|live [--policy-file F] [--state-dir D] [--now ISO]
    python -m crawler.jobs.nightly count [--hours 24]
    python -m crawler.jobs.nightly slack-test --state-dir D
"""
from __future__ import annotations

import argparse
import json
import os
import time as clock
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
START, END = time(21, 0), time(8, 0)
TARGET = 1000
LIVE_SOURCE = 'jobkorea_live'
SITE = 'https://slatech.co.kr/career/job-postings'
MIN_CHUNK_SECONDS = 60
NOT_RUN, UNVERIFIED = 'NOT_RUN', 'UNVERIFIED'


# ---------------------------------------------------------------- window
@dataclass(frozen=True)
class Window:
    night_date: date          # the date the night started (21:00)
    start: datetime
    end: datetime
    inside: bool

    def seconds_left(self, now):
        return max(0, int((self.end - now).total_seconds()))


def night_window(now):
    """Window that contains ``now`` (21:00 -> next 08:00 KST), else the next one (inside=False)."""
    local = now.astimezone(KST)
    if local.time() >= START:
        night = local.date()
    elif local.time() < END:
        night = local.date() - timedelta(days=1)
    else:
        night = local.date()                     # daytime: the coming night, not open yet
    start = datetime.combine(night, START, KST)
    end = datetime.combine(night + timedelta(days=1), END, KST)
    return Window(night, start, end, start <= local < end)


# ---------------------------------------------------------------- counters (read only)
NEW_INSERT_SQL = """
SELECT count(DISTINCT (i.source_code, i.external_posting_id))
FROM crawler_training.harvest_items i
JOIN crawler_training.harvest_runs r ON r.run_id = i.run_id
WHERE r.mode = 'live' AND r.http_requests > 0 AND r.source_code = %(source)s
  AND i.outcome = 'inserted' AND i.checked_at >= %(since)s AND i.checked_at < %(until)s
  AND EXISTS (SELECT 1 FROM crawler_training.postings p
              WHERE p.source_code = i.source_code AND p.external_posting_id = i.external_posting_id)
"""
NIGHT_RUNS_SQL = """
SELECT run_id::text, status, coalesce(stop_reason, ''), http_requests, links_seen, new_found, known_found,
       cross_duplicates, inserted, updated, unchanged, failed, started_at, ended_at
FROM crawler_training.harvest_runs
WHERE mode = 'live' AND source_code = %(source)s AND started_at >= %(since)s AND started_at < %(until)s
ORDER BY started_at
"""


def new_inserts(connection, since, until, source=LIVE_SOURCE):
    return connection.execute(NEW_INSERT_SQL, {'source': source, 'since': since, 'until': until}).fetchone()[0]


def night_totals(connection, window, source=LIVE_SOURCE):
    rows = connection.execute(NIGHT_RUNS_SQL, {'source': source, 'since': window.start, 'until': window.end}).fetchall()
    keys = ('http_requests', 'links_seen', 'new_found', 'known_found', 'cross_duplicates', 'inserted', 'updated',
            'unchanged', 'failed')
    totals = {k: sum(r[3 + n] for r in rows) for n, k in enumerate(keys)}
    totals['runs'] = [{'run_id': r[0], 'status': r[1], 'stop_reason': r[2] or None} for r in rows]
    totals['verified_new_inserts'] = new_inserts(connection, window.start, window.end, source)
    return totals


# ---------------------------------------------------------------- Slack
def _pct(value, target):
    return f'{value / target * 100:.1f}%' if isinstance(value, int) and target else UNVERIFIED


def _n(value):
    return f'{value:,}건' if isinstance(value, int) else str(value)


def format_report(kind, *, window, totals=None, target=TARGET, status=None, error=None, gcp=NOT_RUN,
                  gcp_inserts=NOT_RUN, site=NOT_RUN, site_count=NOT_RUN, mode='live', now=None):
    """Korean plain-text message. ``totals`` None -> every count is NOT_RUN (nothing measured)."""
    title = {'start': '야간 크롤링 시작', 'progress': '야간 크롤링 진행', 'target': '신규 1,000건 목표 달성',
             'end': '야간 크롤링 결과', 'failure': '야간 크롤링 비정상 종료', 'blocked': '야간 크롤링 미실행 (차단)',
             'test': 'Slack 알림 연결 테스트'}[kind]
    lines = [f'[AI Career Platform] {title}']
    if kind == 'test':
        lines += ['- 유형: TEST', '- 상태: 연결 확인', '- 실제 크롤링 실행: 없음', '- GCP 데이터 변경: 없음']
        return {'text': '\n'.join(lines)}
    t = totals or {}
    get = (lambda k: t[k]) if totals is not None else (lambda k: NOT_RUN)
    inserted = t.get('verified_new_inserts', NOT_RUN) if totals is not None else NOT_RUN
    lines += [
        f"- 실행: {window.start:%Y-%m-%d %H:%M} ~ {window.end:%Y-%m-%d %H:%M} KST"
        + (f" (보고 시각 {now.astimezone(KST):%H:%M})" if now else ''),
        f'- 수집원: JobKorea ({mode.upper()})',
        f"- Run ID: {', '.join(r['run_id'][:8] for r in t.get('runs', [])) or NOT_RUN}",
        f"- 검색 결과 링크: {_n(get('links_seen'))} · 신규 후보: {_n(get('new_found'))}",
        f"- 기존 공고 중복: {_n(get('known_found'))} · 키워드 간 중복: {_n(get('cross_duplicates'))}",
        f"- 신규 PostgreSQL INSERT(행 검증): {_n(inserted)} · 업데이트: {_n(get('updated'))}",
        f"- INSERT 실패: {_n(get('failed'))} · HTTP 요청: {_n(get('http_requests'))}",
        f'- 목표: 신규 {target:,}건 · 달성률: {_pct(inserted, target)}',
        f'- GCP 이관: {gcp} · GCP 신규 INSERT: {_n(gcp_inserts)}',
        f'- 웹사이트 표시: {site} · 확인 공고: {_n(site_count)} ({SITE})',
    ]
    if error:
        lines.append(f'- 오류 요약: {error}')
    if status:
        lines.append(f'- 최종 상태: {status}')
    return {'text': '\n'.join(lines)}


def format_gcp(window, result):
    """Korean GCP transfer report built only from the sync's own JSON result (or a BLOCKED/NOT_RUN record)."""
    status = str(result.get('status') or UNVERIFIED)
    lines = [f'[AI Career Platform] GCP 운영 DB 이관 결과 (야간 {window.night_date})',
             f'- 상태: {status}']
    if result.get('reason') or result.get('error_code'):
        lines.append(f"- 사유: {result.get('reason') or result.get('error_code')}")
    if status in ('SUCCEEDED', 'PARTIAL', 'DRY_RUN', 'VERIFIED', 'FAILED'):
        lines += [f"- 대상 LIVE Run: {', '.join(r[:8] for r in result.get('live_run_ids') or []) or UNVERIFIED}",
                  f"- 원본 공고: {_n(result.get('fetched', UNVERIFIED))}",
                  f"- GCP 신규 INSERT: {_n(result.get('inserted', UNVERIFIED))} · 업데이트: {_n(result.get('updated', UNVERIFIED))}",
                  f"- 중복: {_n(result.get('duplicate', UNVERIFIED))} · 건너뜀: {_n(result.get('skipped', UNVERIFIED))}"
                  f" · 실패: {_n(result.get('failed', UNVERIFIED))}",
                  f"- 게시 상태: {'published' if result.get('publish') else 'draft (웹사이트 비노출)'}"]
    return {'text': '\n'.join(lines)}


NIGHT_RUN_IDS_SQL = """
SELECT run_id::text FROM crawler_training.harvest_runs
WHERE mode = 'live' AND source_code = %(source)s AND http_requests > 0
  AND status IN ('SUCCEEDED', 'PARTIAL', 'STOPPED') AND started_at >= %(since)s AND started_at < %(until)s
ORDER BY started_at
"""


class SlackLedger:
    """At most one message per (night, key). Stored in a small JSON file; never holds the webhook."""

    def __init__(self, state_dir, night):
        import threading
        self.path = Path(state_dir) / f'nightly-slack-{night.isoformat()}.json'
        self.lock = threading.Lock()
        try:
            self.sent = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.sent = {}

    def notify(self, key, payload, environ, *, sender=None):
        with self.lock:              # the progress thread and the main loop share one ledger
            return self._notify(key, payload, environ, sender)

    def _notify(self, key, payload, environ, sender):
        from crawler.notifications import slack
        if key in self.sent:
            return {'slack': 'DUPLICATE_SKIPPED', 'key': key}
        url, config = slack.webhook_config(environ)
        if not url:
            return {'slack': config['reason'], 'key': key}
        send = sender or slack.send
        accepted, status, code = send(url, payload)
        if not accepted and (status is None or status >= 500):      # one bounded retry for transient errors
            clock.sleep(2)
            accepted, status, code = send(url, payload)
        self.sent[key] = {'at': datetime.now(timezone.utc).isoformat(), 'accepted': accepted, 'http_status': status}
        tmp = self.path.with_suffix('.tmp')
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self.sent, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)
        return {'slack': 'SENT' if accepted else 'FAILED', 'http_status': status, 'code': code, 'key': key}


# ---------------------------------------------------------------- run
@dataclass(frozen=True)
class NightConfig:
    target: int = TARGET
    chunk_new: int = TARGET         # new-posting details per harvest run (one run per night by default)
    pages: int = 15                 # result pages per keyword per run
    max_requests: int = 1300        # per run, including robots.txt (must not exceed the approval's max_requests)
    night_max_requests: int = 1300  # all runs of one night together (the approval's per-run cap is not a night cap)
    progress_minutes: int = 60


CHUNK_END_REASONS = ('REQUEST_BUDGET', 'DETAIL_BUDGET')       # this chunk is used up; the night may continue


def _limits(config, remaining_new, seconds_left, remaining_requests=None):
    from crawler.jobs.harvest import HarvestLimits
    requests = config.max_requests if remaining_requests is None else min(config.max_requests, remaining_requests)
    # known_page_stop = pages: a later chunk starts again at page 1, whose postings the earlier chunk stored;
    # stopping after 2 known pages would end the night although deeper pages still hold new postings.
    return HarvestLimits(max_pages=config.pages, max_new_details=max(1, min(config.chunk_new, remaining_new)),
                         known_page_stop=config.pages, max_requests=max(1, requests),
                         deadline_seconds=min(seconds_left, 11 * 3600))


class ProgressReporter:
    """Hourly progress message from a separate thread with its own read-only DB connection."""

    def __init__(self, interval_seconds, report):
        import threading
        self.interval, self.report = interval_seconds, report
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name='nightly-progress', daemon=True)
        self.sent = []

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.sent.append(self.report())
            except Exception as exc:   # progress must never disturb the crawl
                self.sent.append({'slack': 'PROGRESS_ERROR', 'reason': type(exc).__name__})

    def __enter__(self):
        if self.report is not None:
            self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=30)


def run_night(connection, *, source_factory, config, environ, ledger, keywords, now_utc=None, harvest=None,
              mode='live', progress_connect=None):
    """Chunked harvest inside the current window. Returns a summary dict (never raises)."""
    from crawler.jobs import harvest as h
    now_utc = now_utc or (lambda: datetime.now(timezone.utc))
    harvest = harvest or h.run_harvest
    window = night_window(now_utc())
    out = {'night_date': str(window.night_date), 'window_end': window.end.isoformat(), 'chunks': [], 'slack': []}
    if not window.inside:
        out.update(status='SKIPPED', reason='OUTSIDE_NIGHT_WINDOW')
        return out
    out['slack'].append(ledger.notify('start', format_report('start', window=window, mode=mode, now=now_utc()),
                                      environ))
    status, reason = 'SUCCEEDED', None

    def progress():
        with progress_connect() as conn:
            totals = night_totals(conn, window)
        return ledger.notify(f'progress-{now_utc().astimezone(KST):%Y%m%dT%H}', format_report(
            'progress', window=window, totals=totals, mode=mode, now=now_utc()), environ)
    reporter = ProgressReporter(config.progress_minutes * 60, progress if progress_connect else None)
    try:
        reporter.__enter__()
        while True:
            done = new_inserts(connection, window.start, window.end)
            used = night_totals(connection, window)['http_requests']
            seconds_left = window.seconds_left(now_utc())
            if done >= config.target:
                reason = 'TARGET_REACHED'
                break
            if seconds_left < MIN_CHUNK_SECONDS:
                reason = 'WINDOW_ENDED'
                break
            # a chunk needs robots.txt + at least one page + one detail
            if config.night_max_requests - used < 3:
                reason = 'NIGHT_REQUEST_BUDGET'
                break
            limits = _limits(config, config.target - done, seconds_left, config.night_max_requests - used)
            result = harvest(connection, source_factory(limits), keywords=keywords, limits=limits)
            out['chunks'].append({k: result.get(k) for k in ('status', 'stop_reason', 'run_id', 'inserted',
                                                            'new', 'http_requests')})
            if result.get('status') in ('BLOCKED', 'SKIPPED'):
                status, reason = 'BLOCKED', result.get('reason')
                break
            stop = result.get('stop_reason')
            if result.get('status') in ('STOPPED', 'FAILED') and stop not in CHUNK_END_REASONS:
                if stop == 'TIMEOUT':                           # 08:00 reached inside the chunk
                    reason = 'WINDOW_ENDED'
                else:                                           # 401/403/429/challenge, approval expiry, crash
                    status, reason = 'FAILED', stop
                break
            if not result.get('new'):   # run_harvest reports new ids found while paging as 'new'
                reason = 'NO_NEW_SUPPLY'
                break
    except Exception as exc:  # never leave without a report
        status, reason = 'FAILED', 'WORKER_' + type(exc).__name__.upper()
    finally:
        reporter.__exit__(None, None, None)
        out['slack'] += reporter.sent
    totals = night_totals(connection, window)
    out.update(status=status, reason=reason, totals=totals)
    if totals['verified_new_inserts'] >= config.target:
        out['slack'].append(ledger.notify('target', format_report('target', window=window, totals=totals, mode=mode,
                                                                  status='PASS', now=now_utc()), environ))
    if status == 'FAILED':
        out['slack'].append(ledger.notify('failure', format_report(
            'failure', window=window, totals=totals, mode=mode, error=reason, status='FAILED', now=now_utc()), environ))
    final = 'PASS' if totals['verified_new_inserts'] >= config.target else (
        status if status in ('FAILED', 'BLOCKED') else 'PARTIAL')
    out['slack'].append(ledger.notify('end', format_report(
        'end', window=window, totals=totals, mode=mode, error=reason if reason not in (None, 'TARGET_REACHED') else None,
        status=final + ' (GCP·웹사이트 단계 별도)', now=now_utc()), environ))
    return out


def test_run(connection, *, now):
    """No external HTTP, no writes: window, harvest lock availability, stale runs, 24 h counter."""
    window = night_window(now)
    locked = connection.execute('SELECT pg_try_advisory_lock(642, 0)').fetchone()[0]
    if locked:
        connection.execute('SELECT pg_advisory_unlock(642, 0)')
    running = connection.execute("SELECT count(*) FROM crawler_training.harvest_runs WHERE status = 'RUNNING'").fetchone()[0]
    return {'mode': 'test', 'now_kst': now.astimezone(KST).isoformat(), 'night_date': str(window.night_date),
            'inside_window': window.inside, 'window_start': window.start.isoformat(), 'window_end': window.end.isoformat(),
            'seconds_until_end': window.seconds_left(now) if window.inside else None,
            'harvest_lock_free': bool(locked), 'running_harvest_rows': running,
            'live_new_inserts_24h': new_inserts(connection, now - timedelta(hours=24), now),
            'external_requests': 0, 'db_writes': 0}


# ---------------------------------------------------------------- CLI
def _connect():
    from crawler.storage.staging import connect_configured_database
    connection = connect_configured_database()
    connection.autocommit = True
    return connection


def _now(value):
    return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)


def main(argv=None, *, environ=None):
    environ = os.environ if environ is None else environ
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    w = sub.add_parser('window'); w.add_argument('--now')
    r = sub.add_parser('run'); r.add_argument('--mode', choices=['test', 'live'], required=True)
    r.add_argument('--policy-file'); r.add_argument('--state-dir', required=True); r.add_argument('--now')
    r.add_argument('--config', help='JSON with NightConfig fields')
    c = sub.add_parser('count'); c.add_argument('--hours', type=int, default=24)
    s = sub.add_parser('slack-test'); s.add_argument('--state-dir', required=True)
    nr = sub.add_parser('night-runs', help='finished LIVE run ids of one night (for the GCP step)')
    nr.add_argument('--night', required=True, help='YYYY-MM-DD the night started')
    nt = sub.add_parser('notify', help='send the GCP step result once per night')
    nt.add_argument('--kind', choices=['gcp'], required=True); nt.add_argument('--night', required=True)
    nt.add_argument('--result-file', required=True); nt.add_argument('--state-dir', required=True)
    args = p.parse_args(argv)
    if args.command == 'notify':
        night = date.fromisoformat(args.night)
        window = night_window(datetime.combine(night, START, KST))
        try:
            result = json.loads(Path(args.result_file).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            result = {'status': UNVERIFIED, 'reason': 'RESULT_FILE_UNREADABLE'}
        print(json.dumps(SlackLedger(args.state_dir, night).notify('gcp', format_gcp(window, result), environ)))
        return 0
    if args.command == 'window':
        win = night_window(_now(args.now))
        print(json.dumps({'night_date': str(win.night_date), 'start': win.start.isoformat(), 'end': win.end.isoformat(),
                          'inside': win.inside}))
        return 0
    if args.command == 'slack-test':
        now = datetime.now(timezone.utc)
        ledger = SlackLedger(args.state_dir, now.astimezone(KST).date())
        result = ledger.notify(f'test-{now:%Y%m%dT%H%M}', format_report('test', window=night_window(now)), environ)
        print(json.dumps(result))
        return 0 if result['slack'] in ('SENT', 'DUPLICATE_SKIPPED') else 2
    with _connect() as connection:
        if args.command == 'night-runs':
            window = night_window(datetime.combine(date.fromisoformat(args.night), START, KST))
            ids = [r[0] for r in connection.execute(NIGHT_RUN_IDS_SQL, {'source': LIVE_SOURCE, 'since': window.start,
                                                                        'until': window.end}).fetchall()]
            print(json.dumps({'night_date': args.night, 'live_run_ids': ids}))
            return 0
        if args.command == 'count':
            now = datetime.now(timezone.utc)
            print(json.dumps({'live_new_inserts': new_inserts(connection, now - timedelta(hours=args.hours), now),
                              'hours': args.hours, 'source': LIVE_SOURCE}))
            return 0
        now = _now(args.now)
        if args.mode == 'test':
            print(json.dumps(test_run(connection, now=now), ensure_ascii=False))
            return 0
        config = NightConfig(**json.loads(Path(args.config).read_text(encoding='utf-8'))) if args.config else NightConfig()
        window = night_window(now)
        ledger = SlackLedger(args.state_dir, window.night_date)
        from crawler.jobs import harvest as h
        from crawler.jobs.import_jobkorea_html import load_approval_file
        from crawler.jobs.night_crawl import NIGHT_KEYWORDS
        approval = load_approval_file(args.policy_file) if args.policy_file else None
        probe = _limits(config, config.target, max(window.seconds_left(now), MIN_CHUNK_SECONDS))
        ok, problems, _ = h.preflight(approval, probe, list(NIGHT_KEYWORDS), now=now)
        if not ok or environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED') != '1':
            reason = 'PM_ACTIVATION_REQUIRED' if ok else 'APPROVAL:' + ','.join(problems)[:120]
            notice = ledger.notify('blocked', format_report('blocked', window=window, error=reason, status='BLOCKED',
                                                            now=now), environ) if window.inside else None
            print(json.dumps({'status': 'BLOCKED', 'reason': reason, 'external_requests': 0, 'slack': notice},
                             ensure_ascii=False))
            return 2
        result = run_night(connection, source_factory=lambda limits: h.LiveSource(approval, limits), config=config,
                           environ=environ, ledger=ledger, keywords=list(NIGHT_KEYWORDS), progress_connect=_connect)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result['status'] in ('SUCCEEDED', 'SKIPPED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
