"""T61 STEP 10: immutable, offline inquiry-evidence review ledger.

This is NOT a permission authority. No stage can approve live collection.
Only metadata references are accepted; raw emails/HTML must stay in authorized
private storage, never in the public GitHub repository.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum


class InquiryStage(str, Enum):
    DRAFT_NOT_SENT = "DRAFT_NOT_SENT"
    SENT = "SENT"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"


class ReviewOutcome(str, Enum):
    HOLD = "HOLD"
    DENIED = "DENIED"
    CANDIDATE_FOR_PM_REVIEW = "CANDIDATE_FOR_PM_REVIEW"


@dataclass(frozen=True)
class InquiryRecord:
    source_code: str = "jobkorea"
    inquiry_id: str = "T61-JOBKOREA-ONE-POSTING"
    stage: InquiryStage = InquiryStage.DRAFT_NOT_SENT
    sent_at_utc: datetime | None = None
    sent_evidence_ref: str | None = None
    response_at_utc: datetime | None = None
    response_evidence_ref: str | None = None
    reviewer: str | None = None
    reviewed_at_utc: datetime | None = None
    outcome: ReviewOutcome = ReviewOutcome.HOLD

    @property
    def collection_approved(self) -> bool:
        """A review record NEVER authorizes live collection."""
        return False

    def public_summary(self) -> dict:
        """Do not reveal correspondence text, reviewer, contact, or evidence IDs."""
        return {
            "source_code": self.source_code,
            "stage": self.stage.value,
            "review_outcome": self.outcome.value,
            "live_collection_approved": False,
        }


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")
    return value.astimezone(timezone.utc)


def _ref(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("A short private evidence reference is required")
    # This is an opaque token, not a URL or a message body.
    if any(ch.isspace() for ch in value) or any(ch in value for ch in "@:/\\<>"):
        raise ValueError("Evidence references must be opaque identifiers, not messages or URLs")
    return value


def record_sent(record: InquiryRecord, *, at_utc: datetime, evidence_ref: str) -> InquiryRecord:
    if record.stage != InquiryStage.DRAFT_NOT_SENT:
        raise ValueError("Inquiry can only be sent once")
    return replace(record, stage=InquiryStage.SENT, sent_at_utc=_utc(at_utc),
                   sent_evidence_ref=_ref(evidence_ref))


def record_response(record: InquiryRecord, *, at_utc: datetime, evidence_ref: str) -> InquiryRecord:
    if record.stage not in (InquiryStage.SENT, InquiryStage.NEEDS_CLARIFICATION):
        raise ValueError("Only sent inquiries can receive responses")
    at = _utc(at_utc)
    if record.sent_at_utc is None or at < record.sent_at_utc:
        raise ValueError("Response cannot predate inquiry")
    return replace(record, stage=InquiryStage.RESPONSE_RECEIVED,
                   response_at_utc=at, response_evidence_ref=_ref(evidence_ref),
                   reviewer=None, reviewed_at_utc=None, outcome=ReviewOutcome.HOLD)


def review_response(record: InquiryRecord, *, reviewer: str, at_utc: datetime,
                    outcome: ReviewOutcome) -> InquiryRecord:
    if record.stage != InquiryStage.RESPONSE_RECEIVED or not record.response_evidence_ref:
        raise ValueError("Response evidence is required before review")
    if not isinstance(outcome, ReviewOutcome):
        raise ValueError("Explicit review outcome required")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer is required")
    at = _utc(at_utc)
    if record.response_at_utc is None or at < record.response_at_utc:
        raise ValueError("Review cannot predate response")
    stage = (InquiryStage.NEEDS_CLARIFICATION if outcome == ReviewOutcome.HOLD
             else InquiryStage.REVIEW_COMPLETE)
    return replace(record, stage=stage, reviewer=reviewer.strip(),
                   reviewed_at_utc=at, outcome=outcome)
