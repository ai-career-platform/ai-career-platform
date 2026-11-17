"""T61 shared approval policy (docs/data/T61_PM_APPROVAL_POLICY.md): PM approval vs provider permission.

No network: the HTTP function is replaced by one that fails the test when called.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from crawler.jobs import import_jobkorea_html as ij
from crawler.policy import provider_permission as pp
from crawler.policy import source_approval_gate as gate
from crawler.tests.provider_fixture import provider, provider_json

NOW = datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)
AX = 'https://www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit'
DETAIL = 'https://www.jobkorea.co.kr/Recruit/GI_Read/50300001'


def pm(**over):
    base = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='PM',
                evidence_ref='private:PM-2026-11-17', valid_from_utc=NOW - timedelta(days=1),
                review_due_utc=NOW + timedelta(days=1), collection_method='WEB', allowed_urls=(AX,),
                allowed_purposes=(gate.HARVEST_PURPOSE,), max_requests=106, retention_days=30, stop_on_block=True,
                max_search_pages=5, max_harvest_details=100)
    base.update(over)
    return gate.SourceApproval(**base)


def intent(url=AX, calls=106,     # harvest run bound: 1 + 5 pages x 1 url + 100 details
            at=NOW, purpose=gate.HARVEST_PURPOSE, discovered_from=None):
    return gate.CollectionIntent('jobkorea', url, 'WEB', purpose, calls, at, discovered_from=discovered_from)


def reason(approval, it=None):
    return ij.live_permission_reason(approval, it or intent())


class SharedPolicyTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ij, '_get', side_effect=AssertionError('no network in policy tests'))
        patcher.start()
        self.addCleanup(patcher.stop)

    # 1. PM approval only: internal development allowed, LIVE blocked
    def test_pm_approval_only_allows_internal_checks_but_blocks_live(self):
        approval = pm()
        self.assertEqual(gate.check_collection_permission(approval, intent()).reason, gate.GateReason.ALLOWED)
        self.assertEqual(reason(approval), 'PROVIDER_PERMISSION_MISSING')
        with self.assertRaises(ij.FetchBlocked) as blocked:
            ij._permit(approval, gate.HARVEST_PURPOSE, AX, 106, NOW)
        self.assertEqual(blocked.exception.reason, 'PROVIDER_PERMISSION_MISSING')

    # 2. both valid: allowed within scope
    def test_pm_approval_and_provider_permission_allow_live_within_scope(self):
        approval = pm(provider_permission=provider())
        self.assertEqual(reason(approval), 'ALLOWED')
        ij._permit(approval, gate.HARVEST_PURPOSE, AX, 106, NOW)                    # no exception
        ij._permit(approval, gate.HARVEST_PURPOSE, DETAIL, 106, NOW, discovered_from=AX)

    # 3. expiry (provider, PM, PM window longer than the provider's)
    def test_expired_permissions_block(self):
        self.assertEqual(reason(pm(provider_permission=provider(valid_until_utc=NOW))), 'PROVIDER_EXPIRED')
        self.assertEqual(reason(pm(provider_permission=provider(valid_from_utc=NOW + timedelta(hours=1)))),
                         'PROVIDER_NOT_YET_VALID')
        self.assertEqual(reason(pm(provider_permission=provider(), review_due_utc=NOW)), 'EXPIRED')
        short = provider(valid_until_utc=NOW + timedelta(hours=1))           # PM approval runs 1 day
        self.assertEqual(reason(pm(provider_permission=short)), 'PM_WINDOW_EXCEEDS_PROVIDER')

    # 4. request / item limits
    def test_request_and_item_limits_block(self):
        tight = provider(max_requests_per_day=100)
        self.assertEqual(reason(pm(provider_permission=tight, max_requests=100), intent(calls=100)), 'ALLOWED')
        self.assertEqual(reason(pm(provider_permission=tight)), 'PROVIDER_REQUEST_LIMIT')          # PM 106 > 100
        self.assertEqual(reason(pm(provider_permission=provider()), intent(calls=107)), 'OUT_OF_SCOPE')  # PM gate
        self.assertEqual(reason(pm(provider_permission=provider(), max_harvest_details=1001)), 'ITEM_LIMIT')
        self.assertEqual(reason(pm(provider_permission=provider(max_items=50))), 'ITEM_LIMIT')       # 100 > 50

    # 5. approval files missing
    def test_missing_files_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ij.load_approval_file(os.path.join(tmp, 'absent.json')))
            with self.assertRaises(ij.FetchBlocked):
                ij._permit(None, gate.HARVEST_PURPOSE, AX, 106, NOW)
            record = {k: (v.isoformat() if isinstance(v, datetime) else list(v) if isinstance(v, tuple) else v)
                      for k, v in pm().__dict__.items() if k != 'provider_permission'}
            path = os.path.join(tmp, 'approval.json')
            # provider file referenced but absent -> loaded without permission -> LIVE blocked
            record['provider_permission_file'] = os.path.join(tmp, 'provider-absent.json')
            json.dump(record, open(path, 'w', encoding='utf-8'))
            loaded = ij.load_approval_file(path)
            self.assertIsNotNone(loaded)
            self.assertEqual(reason(loaded), 'PROVIDER_PERMISSION_MISSING')
            # inline provider_permission in the PM file is ignored: only the referenced private file counts
            record.pop('provider_permission_file')
            record['provider_permission'] = {'provider': 'JobKorea'}
            json.dump(record, open(path, 'w', encoding='utf-8'))
            self.assertEqual(reason(ij.load_approval_file(path)), 'PROVIDER_PERMISSION_MISSING')
            # a valid referenced file is loaded and admits the request
            record.pop('provider_permission')
            record['provider_permission_file'] = provider_json(os.path.join(tmp, 'provider.json'))
            json.dump(record, open(path, 'w', encoding='utf-8'))
            self.assertEqual(reason(ij.load_approval_file(path)), 'ALLOWED')

    # 6. URLs outside the approved scope
    def test_unapproved_urls_block(self):
        approval = pm(provider_permission=provider())
        other = 'https://www.jobkorea.co.kr/Search/?stext=Python&tabType=recruit'
        self.assertEqual(reason(approval, intent(url=other)), 'OUT_OF_SCOPE')                     # PM scope
        narrow = pm(provider_permission=provider(allowed_url_prefixes=('https://www.jobkorea.co.kr/Recruit/',)))
        self.assertEqual(reason(narrow), 'PROVIDER_OUT_OF_SCOPE')                                 # provider scope
        self.assertEqual(reason(pm(provider_permission=provider(allowed_purposes=('test',)))), 'PROVIDER_OUT_OF_SCOPE')

    def test_evidence_and_storage_requirements(self):
        self.assertEqual(reason(pm(provider_permission=provider(provider='PM'))), 'PROVIDER_EVIDENCE_MISSING')  # self-issued
        self.assertEqual(reason(pm(provider_permission=provider(evidence_sha256='abc'))), 'PROVIDER_EVIDENCE_MISSING')
        self.assertEqual(reason(pm(provider_permission=provider(evidence_ref=' '))), 'PROVIDER_EVIDENCE_MISSING')
        self.assertEqual(reason(pm(provider_permission=provider(permission_type='EMAIL'))), 'PROVIDER_EVIDENCE_MISSING')
        self.assertEqual(reason(pm(provider_permission=provider(storage_allowed=False))), 'PROVIDER_STORAGE_NOT_ALLOWED')

    def test_repository_provider_form_never_admits_a_request(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / 'scripts/windows/templates'
        form = pp.load_provider_permission(root / 't61-provider-permission.REQUEST.json')
        self.assertIsNotNone(form)                                   # parses (annotation ignored) ...
        at = form.valid_from_utc + timedelta(minutes=1)
        approval = pm(provider_permission=form, valid_from_utc=at - timedelta(hours=1), review_due_utc=form.valid_until_utc)
        self.assertEqual(reason(approval, intent(at=at)), 'PROVIDER_EVIDENCE_MISSING')   # ... but empty evidence

    def test_policy_constants(self):
        self.assertEqual(pp.PM_POLICY_MAX_ITEMS, 1000)
        self.assertIsNone(pp.load_provider_permission('does-not-exist.json'))


if __name__ == '__main__':
    unittest.main()
