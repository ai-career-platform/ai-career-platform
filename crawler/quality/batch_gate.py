"""Read-only offline quality gate for synthetic JobKorea batch records.

This module does not call external services, update PostgreSQL, or modify the
T62 worker. Review-required identity changes are excluded from accepted rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from crawler.normalizer import InvalidPosting, NormalizedPosting, normalize


class ReasonCode(str, Enum):
    MISSING_EXTERNAL_ID = "MISSING_EXTERNAL_ID"
    INVALID_REQUIRED_FIELD = "INVALID_REQUIRED_FIELD"
    INVALID_URL = "INVALID_URL"
    INVALID_DATE = "INVALID_DATE"
    INVALID_STATUS = "INVALID_STATUS"
    INVALID_EMPLOYMENT = "INVALID_EMPLOYMENT"
    INVALID_RECORD = "INVALID_RECORD"
    DUPLICATE_IN_BATCH = "DUPLICATE_IN_BATCH"
    REVIEW_IDENTITY_CHANGE = "REVIEW_IDENTITY_CHANGE"


@dataclass(frozen=True)
class QualityIssue:
    index: int
    reason: ReasonCode
    # Intentionally omit raw text, IDs, URLs, PII and source payloads.


@dataclass(frozen=True)
class QualityResult:
    accepted: tuple[NormalizedPosting, ...]
    issues: tuple[QualityIssue, ...]
    fetched: int
    invalid: int
    duplicate: int
    review: int

    def summary(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "accepted": len(self.accepted),
            "invalid": self.invalid,
            "duplicate": self.duplicate,
            "review": self.review,
        }


def _reason(exc: InvalidPosting) -> ReasonCode:
    message = str(exc)
    if message == "Missing or invalid field: external_posting_id":
        return ReasonCode.MISSING_EXTERNAL_ID
    if message == "Invalid JobKorea source URL":
        return ReasonCode.INVALID_URL
    if message.startswith("Invalid ISO date:") or message == "Expiry precedes publish date":
        return ReasonCode.INVALID_DATE
    if message == "Unsupported posting status":
        return ReasonCode.INVALID_STATUS
    if message == "Unsupported employment type":
        return ReasonCode.INVALID_EMPLOYMENT
    if message.startswith(("Missing or invalid field:", "Invalid field:")):
        return ReasonCode.INVALID_REQUIRED_FIELD
    return ReasonCode.INVALID_RECORD


def check_synthetic_batch(
    raw_records: Sequence[object],
    *,
    previous: Mapping[tuple[str, str], NormalizedPosting] | None = None,
) -> QualityResult:
    """Validate and select a single entry for each stable source/external ID.

    Only a matching key is used for identity. Company or title similarity does
    not merge records. A known ID with a different source URL is held for
    review (not silently treated as a repost or automatic update).
    A missing item from the current batch is not evidence of deletion.
    """
    if isinstance(raw_records, (str, bytes)) or not isinstance(raw_records, (list, tuple)):
        raise TypeError("raw_records must be a list or tuple of records")

    previous = previous if previous is not None else {}
    seen: set[tuple[str, str]] = set()
    accepted: list[NormalizedPosting] = []
    issues: list[QualityIssue] = []
    invalid = duplicate = review = 0

    for index, raw in enumerate(raw_records):
        try:
            item = normalize(raw)
        except InvalidPosting as exc:
            invalid += 1
            issues.append(QualityIssue(index, _reason(exc)))
            continue

        key = (item.source_code, item.external_posting_id)
        if key in seen:
            duplicate += 1
            issues.append(QualityIssue(index, ReasonCode.DUPLICATE_IN_BATCH))
            continue
        seen.add(key)

        prior = previous.get(key)
        if prior is not None:
            if not isinstance(prior, NormalizedPosting):
                raise TypeError("previous mapping values must be normalized postings")
            if prior.source_url != item.source_url:
                review += 1
                issues.append(QualityIssue(index, ReasonCode.REVIEW_IDENTITY_CHANGE))
                continue
        accepted.append(item)

    result = QualityResult(
        accepted=tuple(accepted),
        issues=tuple(issues),
        fetched=len(raw_records),
        invalid=invalid,
        duplicate=duplicate,
        review=review,
    )
    assert result.fetched == len(result.accepted) + invalid + duplicate + review
    return result
