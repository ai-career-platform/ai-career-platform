"""T61 STEP 08 — pure fail-closed authorization policy evaluator.

This is NOT a permission grant or a live crawler. It checks caller-provided
approval records before any proposed collection action. The project currently
has no valid JobKorea approval record; do not synthesize one for production.
No network, file IO, database access, or side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit


class GateReason(str, Enum):
    NOT_APPROVED = "NOT_APPROVED"
    DISABLED = "DISABLED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    EXPIRED = "EXPIRED"
    NOT_YET_VALID = "NOT_YET_VALID"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    MISSING_USAGE_POLICY = "MISSING_USAGE_POLICY"
    INVALID_POLICY = "INVALID_POLICY"
    ALLOWED = "ALLOWED"


@dataclass(frozen=True)
class SourceApproval:
    """Explicit policy data, independently verified outside this evaluator.

    `approval_status='APPROVED'` is a *claim supplied by the caller*, not
    independent verification of the rights holder's authorization.
    """
    source_code: str
    approval_status: str
    enabled: bool
    approved_by: str | None = None
    evidence_ref: str | None = None
    valid_from_utc: datetime | None = None
    review_due_utc: datetime | None = None
    collection_method: str | None = None
    allowed_urls: tuple[str, ...] = ()
    allowed_purposes: tuple[str, ...] = ()
    max_requests: int | None = None
    retention_days: int | None = None
    stop_on_block: bool = False


@dataclass(frozen=True)
class CollectionIntent:
    source_code: str
    url: str
    method: str
    purpose: str
    requested_calls: int
    at_utc: datetime


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: GateReason


def _valid_time(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _canonical_jobkorea(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"jobkorea.co.kr", "www.jobkorea.co.kr"}
            and parsed.username is None and parsed.password is None
            and parsed.port is None
            and not parsed.query and not parsed.fragment
            and parsed.path.startswith("/Recruit/GI_Read/")
            and parsed.path[len("/Recruit/GI_Read/"):].isascii()
            and parsed.path[len("/Recruit/GI_Read/"):].isdigit()
        )
    except ValueError:
        return False


def check_collection_permission(
    approval: SourceApproval | None,
    intent: CollectionIntent,
) -> GateDecision:
    """Check a proposed collection; absent or incomplete approval denies.

    Even an ALLOWED return means *only* that supplied policy data passes
    validation. Operators must confirm real authorization/robots/site terms
    independently; it is NOT permission to run network collection.
    """
    if not isinstance(intent, CollectionIntent):
        raise TypeError("CollectionIntent required")
    if approval is None or not isinstance(approval, SourceApproval):
        return GateDecision(False, GateReason.NOT_APPROVED)
    if approval.approval_status != "APPROVED":
        return GateDecision(False, GateReason.NOT_APPROVED)
    if approval.enabled is not True:
        return GateDecision(False, GateReason.DISABLED)
    if not approval.approved_by or not approval.approved_by.strip() or not approval.evidence_ref or not approval.evidence_ref.strip():
        return GateDecision(False, GateReason.MISSING_EVIDENCE)
    if not _valid_time(intent.at_utc) or not _valid_time(approval.valid_from_utc) or not _valid_time(approval.review_due_utc):
        return GateDecision(False, GateReason.INVALID_POLICY)
    now = intent.at_utc.astimezone(timezone.utc)
    start = approval.valid_from_utc.astimezone(timezone.utc)
    end = approval.review_due_utc.astimezone(timezone.utc)
    if start >= end:
        return GateDecision(False, GateReason.INVALID_POLICY)
    if now < start:
        return GateDecision(False, GateReason.NOT_YET_VALID)
    if now >= end:
        return GateDecision(False, GateReason.EXPIRED)
    if not isinstance(approval.allowed_urls, tuple) or not isinstance(approval.allowed_purposes, tuple):
        return GateDecision(False, GateReason.INVALID_POLICY)
    if (
        approval.source_code != "jobkorea"
        or intent.source_code != approval.source_code
        or not _canonical_jobkorea(intent.url)
        or any(not _canonical_jobkorea(u) for u in approval.allowed_urls)
        or intent.url not in approval.allowed_urls
        or not intent.purpose or intent.purpose not in approval.allowed_purposes
    ):
        return GateDecision(False, GateReason.OUT_OF_SCOPE)
    if approval.collection_method != "WEB" or intent.method != approval.collection_method:
        return GateDecision(False, GateReason.METHOD_NOT_ALLOWED)
    if (
        type(approval.max_requests) is not int or approval.max_requests < 1
        or type(approval.retention_days) is not int or approval.retention_days < 0
        or approval.stop_on_block is not True
    ):
        return GateDecision(False, GateReason.MISSING_USAGE_POLICY)
    if type(intent.requested_calls) is not int or not 1 <= intent.requested_calls <= approval.max_requests:
        return GateDecision(False, GateReason.OUT_OF_SCOPE)
    return GateDecision(True, GateReason.ALLOWED)
