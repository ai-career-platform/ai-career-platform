"""Test-only provider permission (T61 shared policy). Never a real grant: it exists so tests of the LIVE code
paths (fake HTTP) can model the 'PM approval + provider permission' case. Real files live outside Git."""
import json
from datetime import datetime, timezone

from crawler.policy.provider_permission import ProviderPermission

PURPOSES = ('test', 'night_keyword_collection', 'harvest_collection', 'manual_collection', 'scheduled_collection')


def provider(**over):
    values = dict(source_code='jobkorea', provider='JobKorea (test fixture, not a real grant)',
                  permission_type='WRITTEN_PERMISSION', granted_to='AI Career Platform',
                  evidence_ref='test-only', evidence_sha256='0' * 64,
                  valid_from_utc=datetime(2000, 1, 1, tzinfo=timezone.utc),
                  valid_until_utc=datetime(2100, 1, 1, tzinfo=timezone.utc),
                  allowed_methods=('WEB',), allowed_purposes=PURPOSES,
                  allowed_url_prefixes=('https://www.jobkorea.co.kr/', 'https://jobkorea.co.kr/'),
                  max_requests_per_day=1_000_000, storage_allowed=True, max_items=None)
    values.update(over)
    return ProviderPermission(**values)


def provider_json(path, **over):
    """Write the provider record as the private JSON file the approval file references."""
    p = provider(**over)
    data = {k: (v.isoformat() if isinstance(v, datetime) else list(v) if isinstance(v, tuple) else v)
            for k, v in p.__dict__.items()}
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh)
    return path
