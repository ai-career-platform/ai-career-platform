"""Offline lifecycle classification for normalized synthetic JobKorea postings.

This quality check is read-only. It does not update DB status or call websites.
Pass an explicit evaluation date to make results deterministic.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from crawler.normalizer import NormalizedPosting


class Lifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    DRAFT = "DRAFT"


def classify_posting(posting: NormalizedPosting, *, as_of: date) -> Lifecycle:
    """Classify using explicit status first, then expiration date.

    The expiration date is treated as inclusive: expires_on == as_of remains
    active. An absent expiration date does not imply a closure.
    A source-declared closed/draft status takes precedence over the date.
    This is a training policy, not a verified JobKorea semantic guarantee.
    """
    if not isinstance(posting, NormalizedPosting):
        raise TypeError("posting must be NormalizedPosting")
    if not isinstance(as_of, date) or isinstance(as_of, __import__("datetime").datetime):
        raise TypeError("as_of must be a date, not a datetime")
    if posting.status == "closed":
        return Lifecycle.CLOSED
    if posting.status == "draft":
        return Lifecycle.DRAFT
    if posting.status != "published":
        raise ValueError("Unsupported posting status")
    if posting.expires_on is not None and date.fromisoformat(posting.expires_on) < as_of:
        return Lifecycle.EXPIRED
    return Lifecycle.ACTIVE
