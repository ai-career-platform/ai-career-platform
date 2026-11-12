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


SEARCH = "https://www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit"
DETAIL = "https://www.jobkorea.co.kr/Recruit/GI_Read/48123456"


def search_approval(**patch):
    """Synthetic approval listing one keyword search page with bounded discovery (test-only)."""
    values = dict(allowed_urls=(SEARCH,), allowed_purposes=("night_keyword_collection",),
                  max_requests=7, max_discovered_details=5)
    values.update(patch)
    return synthetic_approval(**values)


def search_intent(**patch):
    values = dict(url=SEARCH, purpose="night_keyword_collection", requested_calls=7)
    values.update(patch)
    return intent(**values)


def discovered(url=DETAIL, **patch):
    values = dict(url=url, discovered_from=SEARCH)
    values.update(patch)
    return search_intent(**values)


class TestSearchAndDiscoveredScope(unittest.TestCase):
    """CRAWLER_NIGHT_09: keyword search URL type + detail URLs discovered on it."""

    def assert_allowed(self, approval, request):
        result = check_collection_permission(approval, request)
        self.assertTrue(result.allowed, result.reason)

    def assert_denied(self, reason, approval, request):
        result = check_collection_permission(approval, request)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, reason)

    def test_01_approved_search_url_passes(self):
        self.assert_allowed(search_approval(), search_intent())
        bare = "https://www.jobkorea.co.kr/Search/?stext=AX"
        self.assert_allowed(search_approval(allowed_urls=(bare,)), search_intent(url=bare))
        korean = ("https://www.jobkorea.co.kr/Search/?stext="
                  "%EB%8D%B0%EC%9D%B4%ED%84%B0%20%EB%B6%84%EC%84%9D&tabType=recruit")
        self.assert_allowed(search_approval(allowed_urls=(korean,)), search_intent(url=korean))

    def test_02_unapproved_search_url_denied(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), search_intent(url=SEARCH.replace("AX", "LLM")))
        self.assert_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), search_intent())  # detail-only approval

    def test_03_exact_detail_listing_works_next_to_search(self):
        approval = search_approval(allowed_urls=(SEARCH, DETAIL), max_discovered_details=0)
        self.assert_allowed(approval, search_intent(url=DETAIL))
        # discovery off: a discovered link passes only if it is listed exactly, as before
        self.assert_allowed(approval, discovered())
        self.assert_denied(GateReason.OUT_OF_SCOPE, approval, discovered("https://www.jobkorea.co.kr/Recruit/GI_Read/1"))
        # and only when the page it came from is listed too
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(allowed_urls=(DETAIL,)), discovered())

    def test_04_discovered_detail_within_scope(self):
        self.assert_allowed(search_approval(), discovered())
        for bad in ("https://www.jobkorea.co.kr/Recruit/GI_Read/abc", "https://www.jobkorea.co.kr/User/Login",
                    DETAIL + "?x=1", "https://www.jobkorea.co.kr/Search/?stext=LLM&tabType=recruit",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/١٢"):
            with self.subTest(bad=bad):
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), discovered(bad))

    def test_04b_discovery_needs_opt_in_and_an_approved_source_page(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(max_discovered_details=0), discovered())
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(),
                           discovered(discovered_from=SEARCH.replace("AX", "LLM")))
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(allowed_urls=(DETAIL,)),
                           discovered("https://www.jobkorea.co.kr/Recruit/GI_Read/1", discovered_from=DETAIL))

    def test_04c_discovery_limit_is_bounded_and_validated(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(max_discovered_details=2), discovered())  # 7 > 2+2
        self.assert_allowed(search_approval(max_discovered_details=2), discovered(requested_calls=4))
        for bad in (6, -1, True, "5", None):
            with self.subTest(bad=bad):
                self.assert_denied(GateReason.INVALID_POLICY, search_approval(max_discovered_details=bad), discovered())

    def test_05_external_and_lookalike_hosts_denied(self):
        for url in ("https://example.org/Search/?stext=AX&tabType=recruit",
                    "https://www.jobkorea.co.kr.evil.org/Search/?stext=AX&tabType=recruit",
                    "https://jobkorea.co.kr/Search/?stext=AX&tabType=recruit",
                    "https://user@www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit",
                    "https://www.jobkorea.co.kr:443/Search/?stext=AX&tabType=recruit",
                    "http://www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit"):
            with self.subTest(url=url):
                # not even approvable: listing it invalidates the record's scope
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(allowed_urls=(SEARCH, url)), search_intent(url=url))
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), discovered("https://example.org/Recruit/GI_Read/1"))

    def test_06_invalid_posting_number_denied(self):
        for url in ("https://www.jobkorea.co.kr/Recruit/GI_Read/", "https://www.jobkorea.co.kr/Recruit/GI_Read/12a",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/1/2", "https://www.jobkorea.co.kr/Recruit/GI_Read/-1"):
            with self.subTest(url=url):
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), discovered(url))

    def test_07_extra_or_malformed_query_parameters_denied(self):
        base = "https://www.jobkorea.co.kr/Search/?"
        for url in (SEARCH + "&page=2", SEARCH + "#top", base + "stext=AX&stext=LLM",
                    base + "tabType=recruit&stext=AX", base + "stext=AX&tabType=corp",
                    base + "stext=&tabType=recruit", base + "stext=%20&tabType=recruit",
                    base + "stext=%41X&tabType=recruit",   # non-canonical spelling of AX
                    base + "stext=A+X&tabType=recruit", base + "stext=A%0AX&tabType=recruit",
                    base + "stext=" + "A" * 101, base + "stext=데이터&tabType=recruit",
                    "https://www.jobkorea.co.kr/Search?stext=AX&tabType=recruit",
                    "https://www.jobkorea.co.kr/search/?stext=AX&tabType=recruit",
                    "https://www.jobkorea.co.kr/Search/"):
            with self.subTest(url=url):
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(allowed_urls=(SEARCH, url)), search_intent(url=url))

    def test_08_expired_hold_or_disabled_still_fail_closed(self):
        for request in (search_intent(), discovered()):
            with self.subTest(url=request.url):
                self.assert_denied(GateReason.EXPIRED, search_approval(review_due_utc=NOW), request)
                self.assert_denied(GateReason.NOT_APPROVED, search_approval(approval_status="HOLD"), request)
                self.assert_denied(GateReason.DISABLED, search_approval(enabled=False), request)
                self.assert_denied(GateReason.NOT_APPROVED, None, request)

    def test_09_purpose_mismatch_denied(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), search_intent(purpose="manual_collection"))
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), discovered(purpose="redistribution"))

    def test_10_request_limit_exceeded_denied(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), search_intent(requested_calls=8))
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(max_requests=6), discovered())

    def test_11_search_job_larger_than_discovery_scope_is_refused_up_front(self):
        self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(max_discovered_details=3), search_intent())  # 7 > 2+3
        self.assert_allowed(search_approval(max_discovered_details=3), search_intent(requested_calls=5))
        # exact-listing mode (discovery off) keeps the old rule: only max_requests bounds the job
        self.assert_allowed(search_approval(max_discovered_details=0), search_intent())

    def test_12_discovered_link_must_be_in_parser_form(self):
        for url in ("https://jobkorea.co.kr/Recruit/GI_Read/1", "https://WWW.JOBKOREA.CO.KR/Recruit/GI_Read/1",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/1?", "https://www.jobkorea.co.kr/Recruit/GI_Read/1#",
                    "https://www.jobkorea.co.kr/Recruit/GI_Read/1\n"):
            with self.subTest(url=url):
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(), discovered(url))

    def test_12b_invisible_keywords_and_empty_fragment_denied(self):
        base = "https://www.jobkorea.co.kr/Search/?stext="
        for url in (SEARCH + "#", base + "%E2%80%8B", base + "%EF%BF%BD", base + "%C2%A0", base + "A%E2%80%8BX",
                    base + "%E3%80%80"):
            with self.subTest(url=url):
                self.assert_denied(GateReason.OUT_OF_SCOPE, search_approval(allowed_urls=(SEARCH, url)), search_intent(url=url))
        self.assert_allowed(search_approval(allowed_urls=(base + "AI%20%EC%97%94%EC%A7%80%EB%8B%88%EC%96%B4",)),
                            search_intent(url=base + "AI%20%EC%97%94%EC%A7%80%EB%8B%88%EC%96%B4"))

    def test_13_detail_only_records_behave_as_before(self):
        self.assertEqual(check_collection_permission(synthetic_approval(), intent()).reason, GateReason.ALLOWED)
        self.assert_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(url=URL.replace("50246410", "1")))
        self.assert_denied(GateReason.OUT_OF_SCOPE, synthetic_approval(), intent(discovered_from=SEARCH))


if __name__ == "__main__":
    unittest.main()
