"""Analyze the output of staging_readonly_check.sh (v3+) — offline, no network, no DB.

    python poc/staging/automation/safety/analyze_staging_check.py staging-check-YYYYMMDD-HHMMSS.txt [--json out.json]

Every jobkorea_live row gets exactly one class:

  VERIFIED_APPROVED    8b evidence LIVE_JOB_LINKED (finished night job, HTTP > 0, inside its own night).
                       Night jobs exist only after night_crawl.live_gate() returned ALLOWED, so the job is
                       code-level approval evidence. approval_basis says whether a covering T61 approval
                       file was also found (8c) or only the gate-enforced job ("PM confirms the record").
  VERIFIED_UNAPPROVED  no gate-approved job AND section 10 shows the posting id in a live import result
                       (the pre-#254 CLI path that did not consult T61).
  VERIFIED_FIXTURE     JOB_LINKED_SYNTHETIC_CLOCK, or the id appears in deployed fixture/test files (9).
  UNVERIFIED_ORIGIN    everything else (no job, failed job, no discovery, no import evidence).

Only VERIFIED_APPROVED rows are listed as migratable. If the class totals differ from the number of
jobkorea_live rows (8b row count and the section 8 source count) the result is INCONSISTENT (exit 2).
Missing sections make the result INCOMPLETE (exit 2). Nothing is guessed when a section is absent.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

SECTION = re.compile(r'^===== (.+?) =====\s*$')


def sections(text):
    out, name = {}, None
    for line in text.splitlines():
        m = SECTION.match(line)
        if m:
            name = m.group(1)
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return out


def find(secs, prefix):
    for name, lines in secs.items():
        if name.startswith(prefix):
            return lines
    return None


def psql_tables(lines):
    """All aligned psql tables in a section: [{'columns': [...], 'rows': [[...], ...]}]."""
    tables, i = [], 0
    while i < len(lines):
        line = lines[i]
        if '|' in line and i + 1 < len(lines) and re.match(r'^-+(\+-+)*$', lines[i + 1].strip()):
            cols = [c.strip() for c in line.split('|')]
            rows, j = [], i + 2
            while j < len(lines) and not re.match(r'^\(\d+ rows?\)$', lines[j].strip()):
                if '|' in lines[j]:
                    rows.append([c.strip() for c in lines[j].split('|')])
                j += 1
            tables.append({'columns': cols, 'rows': rows})
            i = j
        i += 1
    return tables


def ts(value):
    """psql timestamptz ('2026-11-12 22:00:00+09' / '+05:30') or ISO 'Z' -> aware datetime; None if empty."""
    if not value:
        return None
    v = value.strip().replace('Z', '+00:00')
    if re.search(r'[+-]\d\d$', v):
        v += ':00'
    return datetime.fromisoformat(v)


def kv(lines, key):
    for line in lines or ():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return None


def analyze(text):
    secs = sections(text)
    problems = []
    required = {'4.': 'cron', '5.': 'gcp-sync env', '6.': 'sync history', '8.': 'crawler DB', '8b.': 'provenance',
                '8c.': 'approvals', '9.': 'fixture match'}
    for prefix, label in required.items():
        if find(secs, prefix) is None:
            problems.append(f'MISSING_SECTION:{prefix} {label}')

    # cron / publish / versions / history
    cron = find(secs, '4.') or []
    env5 = find(secs, '5.') or []
    ver = find(secs, '2.') or []
    hist = find(secs, '6.') or []
    # crontab lines only: section 4 lists the crontab before '--- cron executions' (journal/syslog lines after
    # it also mention run_gcp_sync and must not count as an enabled cron entry)
    crontab_part = cron[:next((i for i, l in enumerate(cron) if l.startswith('--- cron executions')), len(cron))]
    cron_lines = [l for l in crontab_part if 'run_gcp_sync.sh' in l and not l.startswith(('user_', 'system_', '/etc/'))]
    active_lines = [l for l in cron_lines if not l.lstrip().startswith('#')]
    publish = kv(env5, 'GCP_SYNC_PUBLISH_value')
    runs = []
    for line in hist:
        m = re.match(r'^\d+: (\{.*\})$', line)
        if m:
            try:
                runs.append(json.loads(m.group(1)))
            except ValueError:
                pass
    sync_runs = [r for r in runs if 'status' in r]
    gcp = {
        'cron_daemon_active': kv(cron, 'cron_daemon_active'),
        'cron_registered': bool(cron_lines), 'cron_enabled': bool(active_lines),
        'cron_schedule': ' '.join(active_lines[0].split()[:5]) if active_lines else None,
        'publish': {'1': True, '0': False}.get(publish) if publish is not None else None,
        'gcp_sync_env_present': not any('NO_GCP_SYNC_ENV_FILE' in l for l in env5),
        'target_user_is_career_sync': kv(env5, 'target_user_is_career_sync'),
        'deployed_fail_closed_guard': kv(ver, 'fail_closed_guard_present'),
        'deployed_local_source_mode': kv(ver, 'local_source_mode_present'),
        'sync_runs_logged': len(sync_runs),
        'last_sync_run': sync_runs[-1] if sync_runs else None,
        'process_running': None,
    }
    if hist:
        after = hist[hist.index(next((l for l in hist if l.startswith('--- running')), hist[-1])):]
        gcp['process_running'] = any(l.strip() and l.strip() != 'none' and not l.startswith('---') for l in after)

    # totals from section 8
    total_db = None
    for t in psql_tables(find(secs, '8.') or []):
        if t['columns'][:2] == ['source_code', 'count']:
            for r in t['rows']:
                if r[0] == 'jobkorea_live':
                    total_db = int(r[1])
            if total_db is None:
                total_db = 0

    # approvals (8c)
    approvals, approvals_readable = [], False
    for line in find(secs, '8c.') or []:
        if line.startswith('policy_dir='):
            approvals_readable = True
        if line.startswith('{"file"'):
            try:
                approvals.append(json.loads(line))
            except ValueError:
                pass

    def covering(start):
        for a in approvals:
            try:
                ok = (a.get('approval_status') == 'APPROVED' and a.get('enabled') is True
                      and 'night_keyword_collection' in (a.get('allowed_purposes') or [])
                      and a.get('approved_by_set') and a.get('evidence_ref_set')
                      and ts(a['valid_from_utc']) <= start < ts(a['review_due_utc']))
            except (KeyError, TypeError, ValueError):
                ok = False
            if ok:
                return a['file']
        return None

    # fixture matches (9) and import evidence (10)
    fixture_ids = set()
    for line in find(secs, '9.') or []:
        m = re.match(r'^id=(\S+) fixture_or_test_files_mentioning=(\d+)', line)
        if m and int(m.group(2)) > 0:
            fixture_ids.add(m.group(1))
    evidence10 = '\n'.join(find(secs, '10.') or [])

    # per-posting classification (8b)
    rows = []
    tables8b = [t for t in psql_tables(find(secs, '8b.') or []) if 'evidence' in t['columns']
                and 'external_posting_id' in t['columns']]
    if tables8b:
        t = tables8b[0]
        idx = {c: i for i, c in enumerate(t['columns'])}
        for r in t['rows']:
            get = lambda c: r[idx[c]] if c in idx and idx[c] < len(r) else ''
            pid, ev = get('external_posting_id'), get('evidence')
            item = {'external_posting_id': pid, 'evidence': ev, 'keyword': get('keyword') or None,
                    'updated_at': get('updated_at'), 'job_id': get('job_id') or None,
                    'job_started_at': get('started_at') or None}
            # An approved night job outranks an id match in test files: real posting ids (e.g. ones a user
            # saved as samples) also appear in fixtures, and the sync filter admits them by the job alone.
            if ev == 'LIVE_JOB_LINKED':
                file = covering(ts(get('started_at'))) if approvals_readable and get('started_at') else None
                item['class'] = 'VERIFIED_APPROVED'
                item['approval_basis'] = f'approval_file:{file}' if file else 'gate_enforced_night_job'
                if pid in fixture_ids:
                    item['note'] = 'id_also_in_test_files'
            elif ev == 'JOB_LINKED_SYNTHETIC_CLOCK' or pid in fixture_ids:
                item['class'] = 'VERIFIED_FIXTURE'
            elif pid and any(pid in line and ('import_jobkorea_html' in line or 'live_http' in line)
                             for line in evidence10.splitlines()):
                # the import CLI prints counts only, so an id appears only in a recorded command line
                # (shell history: --url .../GI_Read/<id>) of the pre-#254 path that never consulted T61
                item['class'] = 'VERIFIED_UNAPPROVED'
            else:
                item['class'] = 'UNVERIFIED_ORIGIN'
            rows.append(item)
    counts = {c: sum(1 for r in rows if r['class'] == c)
              for c in ('VERIFIED_APPROVED', 'VERIFIED_UNAPPROVED', 'VERIFIED_FIXTURE', 'UNVERIFIED_ORIGIN')}
    if not tables8b and find(secs, '8b.') is not None and (total_db is None or total_db > 0):
        problems.append('MISSING_8B_TABLE: the provenance query produced no table (SQL error?)')
    if tables8b and total_db is not None and len(rows) != total_db:
        problems.append(f'INCONSISTENT: 8b rows {len(rows)} != section 8 jobkorea_live {total_db}')
    if sum(counts.values()) != len(rows):
        problems.append('INCONSISTENT: class totals do not add up')
    status = 'OK' if not problems else ('INCONSISTENT' if any(p.startswith('INCONSISTENT') for p in problems)
                                        else 'INCOMPLETE')
    return {'status': status, 'problems': problems, 'staging_jobkorea_live_rows': total_db,
            'classified_rows': len(rows), 'class_counts': counts, 'gcp_sync': gcp,
            'approval_files_read': len(approvals) if approvals_readable else None,
            'migratable_ids': sorted(r['external_posting_id'] for r in rows if r['class'] == 'VERIFIED_APPROVED'),
            'gate_only_approvals': sorted(r['external_posting_id'] for r in rows
                                          if r.get('approval_basis') == 'gate_enforced_night_job'),
            'rows': rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('output_file')
    ap.add_argument('--json', help='also write the full result here')
    args = ap.parse_args(argv)
    with open(args.output_file, encoding='utf-8', errors='replace') as fh:
        result = analyze(fh.read())
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1, default=str)
    summary = {k: v for k, v in result.items() if k != 'rows'}
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    return 0 if result['status'] == 'OK' else 2


if __name__ == '__main__':
    sys.exit(main())
