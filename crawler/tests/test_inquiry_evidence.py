"""Synthetic metadata only; never send emails or touch the live site."""
import unittest
from datetime import datetime, timedelta, timezone

from crawler.policy.inquiry_evidence import (
    InquiryRecord, InquiryStage, ReviewOutcome,
    record_response, record_sent, review_response,
)

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)


class TestInquiryEvidence(unittest.TestCase):
    def setUp(self):
        self.draft = InquiryRecord()
        self.sent = record_sent(self.draft, at_utc=NOW, evidence_ref="private-send-001")
        self.received = record_response(
            self.sent, at_utc=NOW + timedelta(minutes=10),
            evidence_ref="private-reply-001",
        )

    def test_initial_draft_never_approved(self):
        self.assertEqual(self.draft.stage, InquiryStage.DRAFT_NOT_SENT)
        self.assertFalse(self.draft.collection_approved)

    def test_sent_requires_real_recording_action(self):
        self.assertEqual(self.sent.stage, InquiryStage.SENT)
        self.assertEqual(self.draft.stage, InquiryStage.DRAFT_NOT_SENT)
        self.assertEqual(self.sent.sent_evidence_ref, "private-send-001")

    def test_cannot_record_reply_before_send(self):
        with self.assertRaises(ValueError):
            record_response(self.draft, at_utc=NOW, evidence_ref="private-reply-001")

    def test_cannot_mark_sent_twice(self):
        with self.assertRaises(ValueError):
            record_sent(self.sent, at_utc=NOW, evidence_ref="private-send-002")

    def test_response_evidence_required(self):
        with self.assertRaises(ValueError):
            record_response(self.sent, at_utc=NOW, evidence_ref="  ")

    def test_response_cannot_precede_send(self):
        with self.assertRaises(ValueError):
            record_response(self.sent, at_utc=NOW - timedelta(seconds=1),
                            evidence_ref="private-reply-002")

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            record_sent(self.draft, at_utc=datetime(2026, 11, 7), evidence_ref="private-send")

    def test_evidence_reference_is_not_email_or_url(self):
        for ref in ("https://example.org/file", "user@example.org", "raw email text", "x" * 201):
            with self.subTest(ref=ref[:25]), self.assertRaises(ValueError):
                record_sent(self.draft, at_utc=NOW, evidence_ref=ref)

    def test_received_defaults_hold(self):
        self.assertEqual(self.received.stage, InquiryStage.RESPONSE_RECEIVED)
        self.assertEqual(self.received.outcome, ReviewOutcome.HOLD)
        self.assertFalse(self.received.collection_approved)

    def test_cannot_review_without_response(self):
        with self.assertRaises(ValueError):
            review_response(self.sent, reviewer="sample", at_utc=NOW,
                            outcome=ReviewOutcome.DENIED)

    def test_reviewer_and_outcome_required(self):
        with self.assertRaises(ValueError):
            review_response(self.received, reviewer=" ", at_utc=NOW + timedelta(hours=1),
                            outcome=ReviewOutcome.DENIED)
        with self.assertRaises(ValueError):
            review_response(self.received, reviewer="sample",
                            at_utc=NOW + timedelta(hours=1), outcome="APPROVED")

    def test_denial_stays_non_approved(self):
        reviewed = review_response(self.received, reviewer="sample",
                                   at_utc=NOW + timedelta(hours=1),
                                   outcome=ReviewOutcome.DENIED)
        self.assertEqual(reviewed.stage, InquiryStage.REVIEW_COMPLETE)
        self.assertFalse(reviewed.collection_approved)

    def test_candidate_review_does_not_grant_collection(self):
        reviewed = review_response(self.received, reviewer="sample",
                                   at_utc=NOW + timedelta(hours=1),
                                   outcome=ReviewOutcome.CANDIDATE_FOR_PM_REVIEW)
        self.assertEqual(reviewed.stage, InquiryStage.REVIEW_COMPLETE)
        self.assertFalse(reviewed.collection_approved)

    def test_ambiguous_reply_requires_clarification(self):
        reviewed = review_response(self.received, reviewer="sample",
                                   at_utc=NOW + timedelta(hours=1),
                                   outcome=ReviewOutcome.HOLD)
        self.assertEqual(reviewed.stage, InquiryStage.NEEDS_CLARIFICATION)
        self.assertFalse(reviewed.collection_approved)

    def test_clarification_can_receive_later_response(self):
        reviewed = review_response(self.received, reviewer="sample",
                                   at_utc=NOW + timedelta(hours=1),
                                   outcome=ReviewOutcome.HOLD)
        next_reply = record_response(
            reviewed, at_utc=NOW + timedelta(hours=2),
            evidence_ref="private-reply-002",
        )
        self.assertEqual(next_reply.stage, InquiryStage.RESPONSE_RECEIVED)
        self.assertEqual(next_reply.outcome, ReviewOutcome.HOLD)
        self.assertIsNone(next_reply.reviewer)

    def test_cannot_review_before_receipt(self):
        with self.assertRaises(ValueError):
            review_response(self.received, reviewer="sample", at_utc=NOW,
                            outcome=ReviewOutcome.DENIED)

    def test_public_summary_excludes_private_metadata(self):
        reviewed = review_response(self.received, reviewer="sample",
                                   at_utc=NOW + timedelta(hours=1),
                                   outcome=ReviewOutcome.CANDIDATE_FOR_PM_REVIEW)
        summary = str(reviewed.public_summary())
        self.assertNotIn("private-reply", summary)
        self.assertNotIn("sample", summary)
        self.assertFalse(reviewed.public_summary()["live_collection_approved"])


if __name__ == "__main__":
    unittest.main()
