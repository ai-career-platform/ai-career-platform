"""Slack run notice: config, format, transport, de-duplication and dispatcher wiring (no real Slack)."""
import http.server
import json
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from crawler.jobs.dispatcher import dispatch
from crawler.notifications.slack import (FAILED_EVENT, MANUAL_EVENT, SENT_EVENT, format_message, notify_run, send,
                                         webhook_config)

HOOK = 'https://hooks.slack.com/services/T000/B000/SECRETTOKEN123'
OTHER = 'https://hooks.slack.com/services/T000/B000/OTHERTOKEN456'


def run_row(status='SUCCEEDED', **extra):
    row = dict(run_id='11111111-2222-3333-4444-555555555555', status=status, mode='fixture', trigger='scheduled',
               started_at=datetime(2026, 11, 12, 18, 0, 0, tzinfo=timezone.utc),
               ended_at=datetime(2026, 11, 12, 18, 0, 1, tzinfo=timezone.utc),
               fetched_count=2, inserted_count=0, updated_count=0, duplicate_count=2, failed_count=0, error_code=None)
    row.update(extra)
    return row


class FakeStore:
    """Minimal SchedulerStore double: read('run'/'events') + event()."""

    def __init__(self, row, events=()):
        self.row, self.events = row, [{'event_type': kind} for kind in events]
        self.written = []

    def read(self, kind, run_id=None, limit=20):
        return [self.row] if kind == 'run' else list(self.events)

    def event(self, run_id, kind, level='INFO'):
        self.written.append((kind, level))
        self.events.append({'event_type': kind})


class Hook(http.server.BaseHTTPRequestHandler):
    status = 200
    bodies = []

    def do_POST(self):
        self.bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(self.status)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


class WebhookConfigTests(unittest.TestCase):
    def test_priority_fallback_and_conflict(self):
        self.assertEqual(webhook_config({'SLACK_WEBHOOK_RUL': HOOK})[0], HOOK)
        url, status = webhook_config({'SLACK_WEBHOOK_URL': HOOK, 'SLACK_WEBHOOK_RUL': OTHER})
        self.assertEqual(url, HOOK)
        self.assertEqual(status, {'configured': True, 'source': 'SLACK_WEBHOOK_URL', 'conflict': True})
        self.assertFalse(webhook_config({'SLACK_WEBHOOK_URL': HOOK, 'SLACK_WEBHOOK_RUL': HOOK})[1]['conflict'])

    def test_empty_means_disabled(self):
        for env in ({}, {'SLACK_WEBHOOK_URL': '  '}, {'SLACK_WEBHOOK_RUL': ''}):
            self.assertEqual(webhook_config(env), (None, {'configured': False, 'reason': 'NOT_CONFIGURED'}))

    def test_only_slack_https_webhooks_are_accepted(self):
        for bad in ('http://hooks.slack.com/services/x', 'https://evil.example/services/x',
                    'https://hooks.slack.com.evil.example/services/x', 'https://hooks.slack.com/api/x',
                    'https://user:pw@hooks.slack.com/services/x', 'https://hooks.slack.com:8443/services/x'):
            url, status = webhook_config({'SLACK_WEBHOOK_URL': bad})
            self.assertIsNone(url)
            self.assertEqual(status['reason'], 'INVALID_WEBHOOK')
            self.assertNotIn(bad, json.dumps(status))

    def test_status_never_contains_secret(self):
        self.assertNotIn('SECRETTOKEN', json.dumps(webhook_config({'SLACK_WEBHOOK_URL': HOOK})[1]))


class MessageTests(unittest.TestCase):
    def test_success_message_uses_db_counts_and_kst(self):
        text = format_message(run_row(), manual=True)['text']
        for part in ('SUCCEEDED', 'Staging', 'MANUAL', 'FIXTURE', '11111111-2222-3333-4444-555555555555',
                     '2026-11-13 03:00:00 KST', 'Fetched 2', 'Inserted 0', 'Updated 0', 'Duplicate/unchanged 2',
                     'Failed 0'):
            self.assertIn(part, text)
        self.assertNotIn('Error code', text)

    def test_failed_and_partial(self):
        text = format_message(run_row('FAILED', error_code='WORKER_TIMEOUT', fetched_count=None), manual=False)['text']
        self.assertIn('SCHEDULED', text)
        self.assertIn('`WORKER_TIMEOUT`', text)
        self.assertIn('Fetched -', text)
        self.assertIn('Warning: partial', format_message(run_row('PARTIAL', failed_count=1), manual=False)['text'])

    def test_unexpected_error_text_is_not_forwarded(self):
        text = format_message(run_row('FAILED', error_code='boom postgres://user:pw@db/x'), manual=False)['text']
        self.assertNotIn('postgres://', text)
        self.assertIn('UNKNOWN', text)


class TransportTests(unittest.TestCase):
    def serve(self, status):
        Hook.status, Hook.bodies = status, []
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Hook)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}/services/SECRETTOKEN123'

    def test_success_2xx(self):
        url = self.serve(200)
        self.assertEqual(send(url, {'text': 'hi'}), (True, 200, 'OK'))
        self.assertEqual(Hook.bodies, [{'text': 'hi'}])

    def test_http_error_is_reported_not_raised(self):
        self.assertEqual(send(self.serve(500), {'text': 'x'}), (False, 500, 'HTTP_ERROR'))
        self.assertEqual(send(self.serve(404), {'text': 'x'}), (False, 404, 'HTTP_ERROR'))

    def test_network_error_hides_url(self):
        result = send('http://127.0.0.1:1/services/SECRETTOKEN123', {'text': 'x'}, timeout=1)
        self.assertEqual(result, (False, None, 'NETWORK_ERROR'))
        self.assertNotIn('SECRETTOKEN', repr(result))


class NotifyRunTests(unittest.TestCase):
    def test_sends_once_and_records_event(self):
        store = FakeStore(run_row())
        calls = []
        sender = lambda url, payload: calls.append(payload) or (True, 200, 'OK')
        first = notify_run(store, 'r', {'SLACK_WEBHOOK_RUL': HOOK}, sender=sender)
        second = notify_run(store, 'r', {'SLACK_WEBHOOK_RUL': HOOK}, sender=sender)
        self.assertEqual(first['slack'], 'SENT')
        self.assertEqual(first['source'], 'SLACK_WEBHOOK_RUL')
        self.assertEqual(second, {'slack': 'DUPLICATE_SKIPPED'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.written, [(SENT_EVENT, 'INFO')])
        self.assertNotIn('SECRETTOKEN', json.dumps(first))

    def test_failure_is_recorded_once_and_not_retried(self):
        store = FakeStore(run_row())
        sender = lambda url, payload: (False, 500, 'HTTP_ERROR')
        self.assertEqual(notify_run(store, 'r', {'SLACK_WEBHOOK_URL': HOOK}, sender=sender)['slack'], 'FAILED')
        self.assertEqual(notify_run(store, 'r', {'SLACK_WEBHOOK_URL': HOOK}, sender=sender)['slack'], 'DUPLICATE_SKIPPED')
        self.assertEqual(store.written, [(FAILED_EVENT, 'WARNING')])
        self.assertEqual(store.row['status'], 'SUCCEEDED')

    def test_manual_marker_disabled_running_and_exceptions(self):
        payloads = []
        store = FakeStore(run_row(), events=[MANUAL_EVENT, 'CLAIMED'])
        notify_run(store, 'r', {'SLACK_WEBHOOK_URL': HOOK}, sender=lambda u, p: payloads.append(p) or (True, 200, 'OK'))
        self.assertIn('Trigger: MANUAL', payloads[0]['text'])
        self.assertEqual(notify_run(FakeStore(run_row()), 'r', {})['slack'], 'DISABLED')
        self.assertEqual(notify_run(FakeStore(run_row('RUNNING')), 'r', {'SLACK_WEBHOOK_URL': HOOK})['slack'],
                         'SKIPPED_NOT_FINAL')

        def boom(url, payload):
            raise RuntimeError(url)
        self.assertEqual(notify_run(FakeStore(run_row()), 'r', {'SLACK_WEBHOOK_URL': HOOK}, sender=boom),
                         {'slack': 'ERROR'})


class DispatchWiringTests(unittest.TestCase):
    """dispatch() notifies after the final row is stored; IDLE/REFUSED never notify."""

    class Store:
        def __init__(self, claim=None):
            self.claimed, self.calls, self.last_decision = claim, [], 'NOT_DUE_OR_DISABLED'

        def lock(self, key): return True

        def unlock(self, key): pass

        def claim(self): self.calls.append('claim'); return self.claimed

        def claim_manual(self):
            self.calls.append('claim_manual')
            self.last_decision = 'MANUAL_FIXTURE_ONLY'
            return self.claimed

        def heartbeat(self, run_id): pass

        def finish(self, *a, **k): self.calls.append('finish')

        def read(self, kind, run_id=None, limit=20): return [{'status': 'SUCCEEDED'}]

    def test_success_path_notifies_after_final_read(self):
        store = self.Store('run-1')
        seen = []
        result = dispatch(store, worker_command=['python', '-c', 'pass'], manual=True, environ={},
                          notifier=lambda s, r, e: seen.append(r) or {'slack': 'DISABLED'})
        self.assertEqual(seen, ['run-1'])
        self.assertEqual(store.calls, ['claim_manual'])
        self.assertEqual((result['status'], result['manual'], result['slack']), ('SUCCEEDED', True, 'DISABLED'))

    def test_idle_and_refused_do_not_notify(self):
        notifier = lambda *a: self.fail('must not notify')
        with patch('subprocess.Popen') as spawn:
            self.assertEqual(dispatch(self.Store(), notifier=notifier)['status'], 'IDLE')
            refused = dispatch(self.Store(), manual=True, notifier=notifier)
        spawn.assert_not_called()
        self.assertEqual(refused, {'status': 'REFUSED', 'reason': 'MANUAL_FIXTURE_ONLY', 'external_requests': 0})


if __name__ == '__main__':
    unittest.main()
