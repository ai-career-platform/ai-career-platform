"""Offline analyzer for staging_readonly_check.sh output. Synthetic input in the script's own format."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('analyzer', ROOT / 'poc/staging/automation/safety/analyze_staging_check.py')
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)

COLS = ('external_posting_id', 'updated_at', 'insert_xid', 'keyword', 'first_seen_at', 'last_seen_at', 'job_id',
        'night_date', 'attempt', 'started_at', 'ended_at', 'outcome', 'http_requests', 'inserted',
        'window_consistent', 'evidence', 'evidence_total')


def table(cols, rows):
    out = [' | '.join(cols), '-+-'.join('-' * max(3, len(c)) for c in cols)]
    out += [' | '.join(r) for r in rows]
    return out + [f'({len(rows)} rows)']


def row(pid, evidence, started='', job=''):
    return (pid, '2026-11-12 22:00:30+09', '100', 'AX' if evidence != 'NO_DISCOVERY' else '', '', '', job,
            '2026-11-12' if job else '', '1' if job else '', started, '', 'SUCCEEDED' if job else '', '7' if job else '',
            '1' if job else '', 't' if job else '', evidence, '1')


def sample(total=6, extra_rows=()):
    rows = [row('50000001', 'LIVE_JOB_LINKED', '2026-11-12 22:00:00+09', 'j1'),
            row('50000002', 'LIVE_JOB_LINKED', '2026-11-14 22:00:00+09', 'j2'),
            row('50000003', 'NO_DISCOVERY'),
            row('50000004', 'NO_DISCOVERY'),
            row('10097100000', 'JOB_LINKED_SYNTHETIC_CLOCK', '2026-11-16 12:59:30+09', 'j3'),
            row('50000006', 'DISCOVERY_WITHOUT_JOB')] + list(extra_rows)
    lines = ['===== 2. deployed code version =====', 'fail_closed_guard_present=0', 'local_source_mode_present=0',
             '===== 4. GCP sync cron =====', 'cron_daemon_active=active', 'user_crontab_lines_with_run_gcp_sync=1',
             'user_crontab_commented_lines=0',
             '5 23 * * * /home/kant/ai-career-staging-poc/gcp-sync/run_gcp_sync.sh scheduled >> log 2>&1',
             'system_cron_files_with_gcp_sync=0',
             '===== 5. gcp-sync directory (existence/mode only) =====', 'gcp_sync_env_mode=600',
             'GCP_SYNC_PUBLISH_value=0', 'target_user_is_career_sync=1',
             '===== 6. GCP sync history (log: status fields only) =====', 'log_lines=4', 'wrapper_starts=2',
             '1: {"wrapper_start": "2026-11-15T23:05:01Z", "mode": "scheduled"}',
             '2: {"mode": "scheduled", "status": "SUCCEEDED", "run_id": "045e68d4", "inserted": 1, "duplicate": 28}',
             '--- running sync / crawler processes', 'none', 'none',
             '===== 8. crawler DB (READ ONLY) =====']
    lines += table(('source_code', 'count', 'min', 'max'), [('jobkorea', '2', 'a', 'b'), ('jobkorea_live', str(total), 'a', 'b')])
    lines += ['===== 8b. per-posting provenance (every jobkorea_live row exactly once) =====']
    lines += table(COLS, rows)
    lines += ['===== 8c. T61 approval files (non-secret fields only) =====', 'policy_dir=/policy',
              '{"file": "jobkorea-t61-night-20261113.json", "approval_status": "APPROVED", "enabled": true,'
              ' "valid_from_utc": "2026-11-12T12:00:00Z", "review_due_utc": "2026-11-12T23:00:00Z",'
              ' "allowed_purposes": ["night_keyword_collection"], "allowed_urls_count": 6, "max_requests": 126,'
              ' "max_discovered_details": 5, "approved_by_set": true, "evidence_ref_set": true}',
              '===== 9. fixture/test match of the jobkorea_live ids (deployed image files) =====',
              'id=50000001 fixture_or_test_files_mentioning=0', 'id=50000006 fixture_or_test_files_mentioning=2',
              '===== 10. evidence of the 2026-11-08 import (read only) =====',
              '412:docker compose exec backend python -m crawler.jobs.import_jobkorea_html --url https://www.jobkorea.co.kr/Recruit/GI_Read/50000003',
              '===== done =====']
    return '\n'.join(lines)


class AnalyzerTest(unittest.TestCase):
    def test_every_row_gets_exactly_one_class_and_only_approved_rows_migrate(self):
        r = analyzer.analyze(sample())
        self.assertEqual((r['status'], r['staging_jobkorea_live_rows'], r['classified_rows']), ('OK', 6, 6))
        self.assertEqual(r['class_counts'], {'VERIFIED_APPROVED': 2, 'VERIFIED_UNAPPROVED': 1,
                                             'VERIFIED_FIXTURE': 2, 'UNVERIFIED_ORIGIN': 1})
        by = {x['external_posting_id']: x for x in r['rows']}
        self.assertEqual(by['50000001']['approval_basis'], 'approval_file:jobkorea-t61-night-20261113.json')
        self.assertEqual(by['50000002']['approval_basis'], 'gate_enforced_night_job')  # no covering file kept
        self.assertEqual(by['50000003']['class'], 'VERIFIED_UNAPPROVED')                # CLI import of that id
        self.assertEqual(by['50000004']['class'], 'UNVERIFIED_ORIGIN')
        self.assertEqual(by['50000006']['class'], 'VERIFIED_FIXTURE')                   # id in deployed test files
        self.assertEqual(r['migratable_ids'], ['50000001', '50000002'])
        self.assertEqual(r['gate_only_approvals'], ['50000002'])

    def test_gcp_sync_state_is_read(self):
        g = analyzer.analyze(sample())['gcp_sync']
        self.assertEqual((g['cron_registered'], g['cron_enabled'], g['cron_schedule'], g['publish']),
                         (True, True, '5 23 * * *', False))
        self.assertEqual((g['last_sync_run']['run_id'], g['process_running'], g['deployed_fail_closed_guard']),
                         ('045e68d4', False, '0'))

    def test_count_mismatch_and_missing_sections_are_errors_not_guesses(self):
        self.assertEqual(analyzer.analyze(sample(total=7))['status'], 'INCONSISTENT')
        partial = analyzer.analyze(sample().split('===== 8c.')[0])
        self.assertEqual(partial['status'], 'INCOMPLETE')
        self.assertTrue(any('8c.' in p for p in partial['problems']))
        empty = analyzer.analyze('')
        self.assertEqual((empty['status'], empty['classified_rows'], empty['migratable_ids']), ('INCOMPLETE', 0, []))

    def test_commented_cron_line_is_registered_but_not_enabled(self):
        text = sample().replace('5 23 * * * /home', '# 5 23 * * * /home')
        g = analyzer.analyze(text)['gcp_sync']
        self.assertEqual((g['cron_registered'], g['cron_enabled']), (True, False))


if __name__ == '__main__':
    unittest.main()
