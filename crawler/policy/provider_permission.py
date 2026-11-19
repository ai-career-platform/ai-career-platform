"""T61 shared policy: the external provider's permission, checked separately from the PM's internal approval.

Policy: docs/data/T61_PM_APPROVAL_POLICY.md. A LIVE request needs BOTH
  1. the PM's internal approval record (``source_approval_gate.check_collection_permission``) and
  2. this provider permission record: proof that JobKorea itself allows the collection and storage.
The PM approval alone allows internal development and tests (fixtures, offline parsing), never LIVE requests.

The provider record is a private JSON file outside Git, referenced from the PM approval file by
``provider_permission_file``. It describes evidence kept privately (signed letter, contract, API terms) by
reference and SHA-256; this module cannot verify the document itself, so a record is only as good as the
person who wrote it (the PM, from evidence they hold). Pure functions: no network, no DB.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

PERMISSION_TYPES = ('WRITTEN_PERMISSION', 'API_CONTRACT', 'LICENSE_AGREEMENT')
PM_POLICY_MAX_ITEMS = 1000          # PM decision 2026-11-17: at most 1,000 postings per approval
_SHA256 = re.compile(r'^[0-9a-f]{64}$')


class ProviderReason(str, Enum):
    ALLOWED = 'ALLOWED'
    PROVIDER_PERMISSION_MISSING = 'PROVIDER_PERMISSION_MISSING'
    PROVIDER_EVIDENCE_MISSING = 'PROVIDER_EVIDENCE_MISSING'
    PROVIDER_NOT_YET_VALID = 'PROVIDER_NOT_YET_VALID'
    PROVIDER_EXPIRED = 'PROVIDER_EXPIRED'
    PM_WINDOW_EXCEEDS_PROVIDER = 'PM_WINDOW_EXCEEDS_PROVIDER'
    PROVIDER_OUT_OF_SCOPE = 'PROVIDER_OUT_OF_SCOPE'
    PROVIDER_STORAGE_NOT_ALLOWED = 'PROVIDER_STORAGE_NOT_ALLOWED'
    PROVIDER_REQUEST_LIMIT = 'PROVIDER_REQUEST_LIMIT'
    ITEM_LIMIT = 'ITEM_LIMIT'


@dataclass(frozen=True)
class ProviderPermission:
    source_code: str
    provider: str                         # who granted it (the provider, never the PM approver)
    permission_type: str                  # one of PERMISSION_TYPES
    granted_to: str
    evidence_ref: str                     # private location of the evidence document
    evidence_sha256: str                  # hash of that document
    valid_from_utc: datetime
    valid_until_utc: datetime
    allowed_methods: tuple[str, ...]
    allowed_purposes: tuple[str, ...]
    allowed_url_prefixes: tuple[str, ...]
    max_requests_per_day: int
    storage_allowed: bool
    max_items: int | None = None


def load_provider_permission(path):
    """Private JSON -> ProviderPermission, or None when absent/invalid. Never raises."""
    try:
        values = {k: v for k, v in dict(json.loads(Path(path).read_text(encoding='utf-8'))).items()
                  if not k.startswith('_')}
        for key in ('valid_from_utc', 'valid_until_utc'):
            values[key] = datetime.fromisoformat(values[key].replace('Z', '+00:00'))
        for key in ('allowed_methods', 'allowed_purposes', 'allowed_url_prefixes'):
            values[key] = tuple(values[key])
        return ProviderPermission(**values)
    except Exception:
        return None


def _aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _read_only_probe(intent):
    """PM decision 2026-11-19: a single official-API probe that stores nothing needs API permission, not storage.
    The probe's no-write guarantee is enforced by the caller (``jobkorea_api`` read-only source)."""
    from crawler.policy.source_approval_gate import API_PROBE_MAX_REQUESTS, API_PROBE_PURPOSE
    return (getattr(intent, 'method', None) == 'API' and getattr(intent, 'purpose', None) == API_PROBE_PURPOSE
            and getattr(intent, 'requested_calls', None) == API_PROBE_MAX_REQUESTS)


def check_provider_permission(permission, approval, intent):
    """ProviderReason for one proposed LIVE request (``intent``) under the PM ``approval``."""
    if not isinstance(permission, ProviderPermission):
        return ProviderReason.PROVIDER_PERMISSION_MISSING
    texts = (permission.provider, permission.granted_to, permission.evidence_ref)
    if (permission.source_code != getattr(approval, 'source_code', None)
            or permission.permission_type not in PERMISSION_TYPES
            or any(not isinstance(t, str) or not t.strip() for t in texts)
            or not isinstance(permission.evidence_sha256, str) or not _SHA256.match(permission.evidence_sha256)
            # the PM cannot issue the provider's permission to itself
            or permission.provider.strip().lower() == str(getattr(approval, 'approved_by', '') or '').strip().lower()):
        return ProviderReason.PROVIDER_EVIDENCE_MISSING
    if not (_aware(permission.valid_from_utc) and _aware(permission.valid_until_utc) and _aware(intent.at_utc)):
        return ProviderReason.PROVIDER_EVIDENCE_MISSING
    now = intent.at_utc.astimezone(timezone.utc)
    if now < permission.valid_from_utc:
        return ProviderReason.PROVIDER_NOT_YET_VALID
    if now >= permission.valid_until_utc:
        return ProviderReason.PROVIDER_EXPIRED
    due = getattr(approval, 'review_due_utc', None)
    if not _aware(due) or due > permission.valid_until_utc:
        return ProviderReason.PM_WINDOW_EXCEEDS_PROVIDER
    if (intent.method not in permission.allowed_methods or intent.purpose not in permission.allowed_purposes
            or not any(isinstance(p, str) and p and intent.url.startswith(p) for p in permission.allowed_url_prefixes)):
        return ProviderReason.PROVIDER_OUT_OF_SCOPE
    if permission.storage_allowed is not True and not _read_only_probe(intent):
        return ProviderReason.PROVIDER_STORAGE_NOT_ALLOWED
    limit = permission.max_requests_per_day
    pm_requests = getattr(approval, 'max_requests', None)
    if (type(limit) is not int or limit < 1 or type(intent.requested_calls) is not int
            or intent.requested_calls > limit or type(pm_requests) is not int or pm_requests > limit):
        return ProviderReason.PROVIDER_REQUEST_LIMIT
    items = getattr(approval, 'max_harvest_details', 0) or 0
    cap = PM_POLICY_MAX_ITEMS if permission.max_items is None else min(PM_POLICY_MAX_ITEMS, permission.max_items)
    if type(items) is not int or items > cap:
        return ProviderReason.ITEM_LIMIT
    return ProviderReason.ALLOWED
