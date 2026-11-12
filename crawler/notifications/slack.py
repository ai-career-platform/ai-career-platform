"""Slack Incoming Webhook notice for finished T64 crawler runs (stdlib only).

Safety contract:
- The webhook URL is read from the environment only (``SLACK_WEBHOOK_URL``, then the legacy
  spelling ``SLACK_WEBHOOK_RUL``) and is never returned, logged or put in a message.
- Only ``https://hooks.slack.com/services/...`` is accepted, so this is the only new egress.
- One POST with a short timeout, no redirects, no retry loop. Failures return a fixed code;
  exception text (which may contain the URL) is never surfaced.
- Message values come from the stored ``crawler_training.runs`` row, after the run is final.
- ``run_events`` is the de-duplication ledger: a run with ``SLACK_NOTIFIED`` or
  ``SLACK_NOTIFY_FAILED`` is never notified again. Notification problems never change the run.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import timezone, timedelta
from urllib.parse import urlparse

WEBHOOK_ENV_NAMES = ('SLACK_WEBHOOK_URL', 'SLACK_WEBHOOK_RUL')
SENT_EVENT = 'SLACK_NOTIFIED'
FAILED_EVENT = 'SLACK_NOTIFY_FAILED'
MANUAL_EVENT = 'MANUAL_RUN'
FINAL_STATUSES = ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')
TIMEOUT_SECONDS = 5
KST = timezone(timedelta(hours=9), 'KST')
_SAFE_CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,63}$')


def webhook_config(environ):
    """Return (url or None, status). ``status`` never contains the URL."""
    found = [(name, (environ.get(name) or '').strip()) for name in WEBHOOK_ENV_NAMES]
    found = [(name, value) for name, value in found if value]
    if not found:
        return None, {'configured': False, 'reason': 'NOT_CONFIGURED'}
    source, url = found[0]
    status = {'configured': True, 'source': source, 'conflict': len({value for _, value in found}) > 1}
    parts = urlparse(url)
    if (parts.scheme != 'https' or parts.hostname != 'hooks.slack.com' or parts.port not in (None, 443)
            or not parts.path.startswith('/services/') or parts.username or parts.password):
        return None, {'configured': False, 'reason': 'INVALID_WEBHOOK', 'source': source}
    return url, status


def _kst(value):
    return value.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S KST') if value else '-'


def _count(value):
    return '-' if value is None else str(value)


def format_message(run, *, manual):
    """Plain-text Slack payload built only from the stored run row."""
    status = run['status']
    icon = {'SUCCEEDED': ':white_check_mark:', 'PARTIAL': ':warning:', 'FAILED': ':x:'}.get(status, ':grey_question:')
    error = run.get('error_code')
    lines = [
        f"{icon} *AI Career Platform crawler {status}* (Staging)",
        f"Trigger: {'MANUAL' if manual else 'SCHEDULED'} · Mode: {str(run['mode']).upper()}",
        f"Run ID: `{run['run_id']}`",
        f"Start: {_kst(run.get('started_at'))} · End: {_kst(run.get('ended_at'))}",
        (f"Fetched {_count(run.get('fetched_count'))} · Inserted {_count(run.get('inserted_count'))}"
         f" · Updated {_count(run.get('updated_count'))} · Duplicate/unchanged {_count(run.get('duplicate_count'))}"
         f" · Failed {_count(run.get('failed_count'))}"),
    ]
    if error:
        lines.append(f"Error code: `{error if _SAFE_CODE.match(str(error)) else 'UNKNOWN'}`")
    if status == 'PARTIAL':
        lines.append('Warning: partial result - check run events.')
    return {'text': '\n'.join(lines)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def send(url, payload, *, timeout=TIMEOUT_SECONDS):
    """POST once. Returns (accepted, http_status or None, code); never raises, never echoes the URL."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), method='POST',
                                     headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    except Exception:  # URLError, timeout, TLS, DNS: details may embed the URL
        return False, None, 'NETWORK_ERROR'
    return (200 <= status < 300), status, ('OK' if 200 <= status < 300 else 'HTTP_ERROR')


def notify_run(store, run_id, environ, *, sender=send):
    """Notify Slack once for a final run. Never raises; returns a secret-free summary."""
    try:
        rows = store.read('run', run_id)
        if not rows or rows[0]['status'] not in FINAL_STATUSES:
            return {'slack': 'SKIPPED_NOT_FINAL'}
        kinds = {event['event_type'] for event in store.read('events', run_id, limit=200)}
        if SENT_EVENT in kinds or FAILED_EVENT in kinds:
            return {'slack': 'DUPLICATE_SKIPPED'}
        url, config = webhook_config(environ)
        if url is None:
            return {'slack': 'DISABLED', 'reason': config['reason']}
        accepted, http_status, code = sender(url, format_message(rows[0], manual=MANUAL_EVENT in kinds))
        store.event(run_id, SENT_EVENT if accepted else FAILED_EVENT, 'INFO' if accepted else 'WARNING')
        return {'slack': 'SENT' if accepted else 'FAILED', 'http_status': http_status, 'code': code,
                'source': config['source'], 'conflict': config['conflict']}
    except Exception:
        return {'slack': 'ERROR'}


# ---- CRAWLER_NIGHT_01: night keyword jobs and the morning summary ----
def _n(value):
    return 0 if value is None else value


def format_night_job(row):
    status = row['outcome']
    icon = {'SUCCEEDED': ':white_check_mark:', 'PARTIAL': ':warning:', 'FAILED': ':x:'}.get(status, ':grey_question:')
    error = row.get('error_code')
    lines = [
        f"{icon} *AI Career Platform night crawl {status}* (Staging)",
        f"Keyword: {row.get('keyword', '-')} · Mode: {str(row['mode']).upper()} · Attempt {row['attempt']}",
        f"Job ID: `{row['job_id']}`",
        f"Start: {_kst(row.get('started_at'))} · End: {_kst(row.get('ended_at'))}",
        (f"Requests {_count(row.get('http_requests'))} · Fetched {_count(row.get('fetched'))}"
         f" · Inserted {_count(row.get('inserted'))} · Updated {_count(row.get('updated'))}"
         f" · Duplicate/unchanged {_n(row.get('unchanged')) + _n(row.get('duplicates'))}"
         f" · Failed {_count(row.get('failed'))}"),
    ]
    if error:
        lines.append(f"Error code: `{error if _SAFE_CODE.match(str(error)) else 'UNKNOWN'}`")
    return {'text': '\n'.join(lines)}


def format_night_summary(night_date, rows, *, planned, missing):
    finals = [r for r in rows if r['outcome'] != 'RUNNING']
    succeeded = {r['keyword_id'] for r in finals if r['outcome'] in ('SUCCEEDED', 'PARTIAL')}
    done = {r['keyword'] for r in finals if r['keyword_id'] in succeeded}
    unprocessed = [k for k in planned if k not in done] + list(missing)
    total = lambda key: sum(_n(r.get(key)) for r in finals)
    lines = [
        f":crescent_moon: *AI Career Platform night crawl summary* (Staging) · {night_date} 21:00 → 08:00 KST",
        (f"Jobs {len(finals)} · Succeeded {sum(r['outcome'] == 'SUCCEEDED' for r in finals)}"
         f" · Partial {sum(r['outcome'] == 'PARTIAL' for r in finals)}"
         f" · Failed {sum(r['outcome'] == 'FAILED' for r in finals)}"),
        (f"Requests {total('http_requests')} · Inserted {total('inserted')} · Updated {total('updated')}"
         f" · Duplicate/unchanged {total('unchanged') + total('duplicates')} · Failed items {total('failed')}"),
        f"Unprocessed keywords: {', '.join(unprocessed) if unprocessed else 'none'}",
    ]
    codes = sorted({r['error_code'] for r in finals if r.get('error_code') and _SAFE_CODE.match(str(r['error_code']))})
    if codes:
        lines.append('Error codes: ' + ', '.join(f'`{c}`' for c in codes))
    return {'text': '\n'.join(lines)}


def notify_night(kind, night_date, rows, environ, *, planned=(), missing=(), sender=send):
    """Send one night notice; returns the HTTP status or None. Never raises, never echoes the URL.

    De-duplication is done by the caller in the DB (slack_notified_at / night_summaries) before sending.
    """
    try:
        url, _ = webhook_config(environ)
        if url is None:
            return None
        payload = format_night_job(rows[0]) if kind == 'job' else format_night_summary(
            night_date, rows, planned=list(planned), missing=list(missing))
        return sender(url, payload)[1]
    except Exception:
        return None
