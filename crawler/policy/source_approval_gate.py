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
import re
import unicodedata
from urllib.parse import parse_qsl, quote, urlsplit

SEARCH_HOST = "www.jobkorea.co.kr"
SEARCH_PATH = "/Search/"
SEARCH_TAB = "recruit"
MAX_SEARCH_TEXT = 100
MAX_DISCOVERED_DETAILS = 5
# The one spelling the list parser emits; discovered links must match it exactly.
_STRICT_DETAIL = re.compile(r"https://www\.jobkorea\.co\.kr/Recruit/GI_Read/[0-9]+")


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
    # CRAWLER_NIGHT_09: opt-in. 0 keeps the original rule (every detail URL listed exactly).
    # 1..5 also admits /Recruit/GI_Read/<id> pages discovered on a search page that is itself
    # listed exactly in allowed_urls, at most this many per search (bounded by requested_calls).
    max_discovered_details: int = 0


@dataclass(frozen=True)
class CollectionIntent:
    source_code: str
    url: str
    method: str
    purpose: str
    requested_calls: int
    at_utc: datetime
    # Set only by the fetcher, for a detail link it extracted from this (already permitted) search page.
    discovered_from: str | None = None


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


def _canonical_jobkorea_search(url: object) -> bool:
    """Exactly https://www.jobkorea.co.kr/Search/?stext=<quoted keyword>[&tabType=recruit].

    One spelling per keyword: the raw query must equal its own canonical re-encoding, so
    percent-encoding tricks, '+', repeated or extra parameters and other tabs never match.
    """
    if not isinstance(url, str) or not url.isascii() or "#" in url:
        return False
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https" or parsed.hostname != SEARCH_HOST or parsed.netloc != SEARCH_HOST
            or parsed.path != SEARCH_PATH or parsed.fragment or not parsed.query
        ):
            return False
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    keys = [k for k, _ in pairs]
    if keys not in (["stext"], ["stext", "tabType"]):
        return False
    values = dict(pairs)
    text = values["stext"]
    if not _visible_keyword(text):
        return False
    if "tabType" in values and values["tabType"] != SEARCH_TAB:
        return False
    canonical = "stext=" + quote(text) + ("&tabType=" + SEARCH_TAB if "tabType" in values else "")
    return parsed.query == canonical


def _visible_keyword(text: str) -> bool:
    """1..100 chars, at least one visible character; no control, format (zero-width),
    private-use, unassigned or replacement characters."""
    return (
        0 < len(text) <= MAX_SEARCH_TEXT
        and any(not c.isspace() for c in text)
        and "�" not in text
        and all(c == " " or unicodedata.category(c) not in {"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"}
                for c in text)
    )


def _approvable(url: object) -> bool:
    return _canonical_jobkorea(url) or _canonical_jobkorea_search(url)


def _in_scope(approval: SourceApproval, intent: CollectionIntent) -> bool:
    """URL-type scope. Exact listing always works; discovery is a narrow, opt-in extension."""
    limit = approval.max_discovered_details
    # robots + search page + at most `limit` discovered details
    within_discovery = type(intent.requested_calls) is int and intent.requested_calls <= 2 + limit
    if intent.discovered_from is None:
        if not (_approvable(intent.url) and intent.url in approval.allowed_urls):
            return False
        # With discovery on, a search job larger than the discovery budget is refused up front,
        # before robots.txt or the search page is requested.
        return not (limit and _canonical_jobkorea_search(intent.url)) or within_discovery
    # A discovered link: its search page must itself be listed, and the link must be a detail page
    # in the exact form the list parser emits. ``discovered_from`` is trusted from the caller: only
    # fetch_pages sets it, for links it extracted from that already-permitted page.
    if not (
        _canonical_jobkorea_search(intent.discovered_from)
        and intent.discovered_from in approval.allowed_urls
        and isinstance(intent.url, str) and _STRICT_DETAIL.fullmatch(intent.url)
    ):
        return False
    if intent.url in approval.allowed_urls:
        return True  # listed exactly, as before
    return 1 <= limit <= MAX_DISCOVERED_DETAILS and within_discovery


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
    limit = approval.max_discovered_details
    if type(limit) is not int or not 0 <= limit <= MAX_DISCOVERED_DETAILS:
        return GateDecision(False, GateReason.INVALID_POLICY)
    if (
        approval.source_code != "jobkorea"
        or intent.source_code != approval.source_code
        or any(not _approvable(u) for u in approval.allowed_urls)
        or not _in_scope(approval, intent)
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
