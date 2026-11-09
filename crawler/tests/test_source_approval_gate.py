"""T61 STEP 08: approval policy is synthetic; never calls live website."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from crawler.policy.source_approval_gate import (
    CollectionIntent, GateReason, SourceApproval, check_collection_permission,
)

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/50246410"


def synthetic_approval(**patch):
    """Invented APPROVED case for fail-closed unit testing ONLY."""
    values = dict(
        source_code="jobkorea", approval_status="APPROVED", enabled=True,
        approved_by="synthetic-fixture-reviewer",
        evidence_ref="synthetic-not-real-approval",
        valid_from_utc=NOW - timedelta(days=1),
        review_due_utc=NOW + timedelta(days=1),
        collection_method="WEB", allowed_urls=(URL,),
        allowed_purposes=("internal_accuracy_validation",),
        max_requests=1, retention_days=1, stop_on_block=True,
    )
    values.update(patch)
    return SourceApproval(**values)


def intent(**patch):
    values = dict(source_code="jobkorea", url=URL, method="WEB",
                  purpose="internal_accuracy_validation",
                  requested_calls=1, at_utc=NOW)
    values.update(patch)
    return CollectionIntent(**values)


class TestSourceApprovalGate(unittest.TestCase):
    def check_denied(self, expected, approval, request=None):
        result = check_collection_permission(approval, request or intent())
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, expected)

    def test_no_record_fails_closed(self):
        self.check_denied(GateReason.NOT_APPROVED, None)

    def test_hold_fails_closed(self):
        self.check_denied(GateReason.NOT_APPROVED, synthetic_approval(approval_status="HOLD"))

    def test_denied_fails_closed(self):
        self.check_denied(GateReason.NOT_APPROVED, synthetic_approval(approval_status="DENIED"))

    def test_disabled_fails_closed(self):
        self.check_denied(GateReason.DISABLED, synthetic_approval(enabled=False))

    def test_evidence_missing(self):
        self.check_denied(GateReason.MISSING_EVIDENCE, synthetic_approval(evidence_ref=None))

    def test_approver_missing(self):
        self.check_denied(GateReason.MISSING_EVIDENCE, synthetic_approval(approved_by=" "))

    def test_expired_fails_closed(self):
        self.check_denied(GateReason.EXPIRED, synthetic_approval(review_due_utc=NOW))

    def test_future_approval_fails_closed(self):
        self.check_denied(GateReason.NOT_YET_VALID, synthetic_approval(valid_from_utc=NOW+timedelta(seconds=1)))

    def test_inverted_dates_invalid(self):
        self.check_denied(GateReason.INVALID_POLICY, synthetic_approval(review_due_utc=NOW-timedelta(days=2)))

    def test_naive_dates_invalid(self):
        self.check_denied(GateReason.INVALID_POLICY, synthetic_approval(valid_from_utc=datetime(2026,11,1)))

    def test_wrong_host_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url="https://example.org/Recruit/GI_Read/50246410"))

    def test_other_posting_id_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url=URL.replace("50246410", "88888")))

    def test_similar_domain_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url="https://www.jobkorea.co.kr.evil.org/Recruit/GI_Read/50246410"))

    def test_login_url_rejected(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url="https://www.jobkorea.co.kr/User/Login"))

    def test_url_query_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url=URL+"?extra=1"))

    def test_wrong_purpose_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(purpose="redistribution"))

    def test_wrong_method_denied(self):
        self.check_denied(GateReason.METHOD_NOT_ALLOWED, synthetic_approval(), intent(method="API"))

    def test_missing_call_limit_denied(self):
        self.check_denied(GateReason.MISSING_USAGE_POLICY, synthetic_approval(max_requests=None))

    def test_no_stop_policy_denied(self):
        self.check_denied(GateReason.MISSING_USAGE_POLICY, synthetic_approval(stop_on_block=False))

    def test_missing_retention_denied(self):
        self.check_denied(GateReason.MISSING_USAGE_POLICY, synthetic_approval(retention_days=None))

    def test_more_calls_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(requested_calls=2))

    def test_zero_calls_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(requested_calls=0))

    def test_bool_not_accepted_as_call_limit(self):
        self.check_denied(GateReason.MISSING_USAGE_POLICY, synthetic_approval(max_requests=True))

    def test_only_synthetic_approved_fixture_can_pass(self):
        result = check_collection_permission(synthetic_approval(), intent())
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, GateReason.ALLOWED)

    def test_invalid_approved_url_scope_fails(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(allowed_urls=(URL, "http://example.org/")))

    def test_other_source_denied(self):
        self.check_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(source_code="saramin"))


if __name__ == "__main__":
    unittest.main()
