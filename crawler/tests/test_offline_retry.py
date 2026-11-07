"""Offline-only retry, spacing, and blocking regression tests."""
import unittest

from crawler.adapters.offline_retry import (
    MockRequestStopped,
    MockResponse,
    MockRetriesExhausted,
    RetryPolicy,
    exercise_offline_retry,
)


class TestOfflineRetryPolicy(unittest.TestCase):
    def simulate(self, events, policy=RetryPolicy()):
        received = iter(events)
        attempts = []
        delays = []

        def fake_request():
            attempts.append("called")
            outcome = next(received)
            if isinstance(outcome, BaseException):
                raise outcome
            return MockResponse(outcome)

        def fake_sleep(seconds):
            delays.append(seconds)

        return fake_request, fake_sleep, attempts, delays

    def test_success_does_not_retry(self):
        req, pause, attempts, delays = self.simulate([200])
        response, count = exercise_offline_retry(req, pause)
        self.assertEqual((response.status_code, count, len(attempts), delays), (200, 1, 1, []))

    def test_500_then_success_retries_with_delay(self):
        req, pause, attempts, delays = self.simulate([500, 200])
        response, count = exercise_offline_retry(req, pause)
        self.assertEqual((response.status_code, count, len(attempts)), (200, 2, 2))
        self.assertEqual(delays, [1.0])

    def test_bounded_exponential_backoff(self):
        policy = RetryPolicy(max_attempts=4, base_backoff_seconds=2, max_backoff_seconds=3)
        req, pause, attempts, delays = self.simulate([503, 502, 500, 200], policy)
        response, count = exercise_offline_retry(req, pause, policy)
        self.assertEqual((response.status_code, count, len(attempts)), (200, 4, 4))
        self.assertEqual(delays, [2, 3, 3])

    def test_timeout_then_success(self):
        req, pause, attempts, delays = self.simulate([TimeoutError(), 200])
        _, count = exercise_offline_retry(req, pause)
        self.assertEqual((count, len(attempts), delays), (2, 2, [1.0]))

    def test_connection_failure_then_success(self):
        req, pause, attempts, _ = self.simulate([ConnectionError(), 200])
        _, count = exercise_offline_retry(req, pause)
        self.assertEqual((count, len(attempts)), (2, 2))

    def test_transient_failure_exhausted(self):
        req, pause, attempts, delays = self.simulate([503, 503, 503])
        with self.assertRaises(MockRetriesExhausted) as caught:
            exercise_offline_retry(req, pause)
        self.assertEqual(caught.exception.attempts, 3)
        self.assertEqual((len(attempts), delays), (3, [1.0, 2.0]))

    def test_timeout_exhausted(self):
        req, pause, attempts, _ = self.simulate([TimeoutError(), TimeoutError(), TimeoutError()])
        with self.assertRaises(MockRetriesExhausted):
            exercise_offline_retry(req, pause)
        self.assertEqual(len(attempts), 3)

    def test_http_403_stop_no_retry(self):
        req, pause, attempts, delays = self.simulate([403, 200])
        with self.assertRaises(MockRequestStopped) as caught:
            exercise_offline_retry(req, pause)
        self.assertEqual((caught.exception.reason, caught.exception.attempts), ("http_403_stop", 1))
        self.assertEqual((len(attempts), delays), (1, []))

    def test_http_429_stop_no_retry(self):
        req, pause, attempts, delays = self.simulate([429, 200])
        with self.assertRaises(MockRequestStopped) as caught:
            exercise_offline_retry(req, pause)
        self.assertEqual((caught.exception.reason, caught.exception.attempts), ("http_429_stop", 1))
        self.assertEqual((len(attempts), delays), (1, []))

    def test_404_stop_no_retry(self):
        req, pause, attempts, delays = self.simulate([404, 200])
        with self.assertRaises(MockRequestStopped):
            exercise_offline_retry(req, pause)
        self.assertEqual((len(attempts), delays), (1, []))

    def test_minimum_spacing_dominates_small_backoff(self):
        policy = RetryPolicy(base_backoff_seconds=0.1, min_interval_seconds=1)
        req, pause, _, delays = self.simulate([500, 200], policy)
        exercise_offline_retry(req, pause, policy)
        self.assertEqual(delays, [1])

    def test_policy_rejects_bad_attempt_counts(self):
        for count in (0, 6):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    RetryPolicy(max_attempts=count)

    def test_policy_rejects_negative_delays(self):
        for kwargs in (
            {"base_backoff_seconds": -1},
            {"max_backoff_seconds": -1},
            {"min_interval_seconds": -1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    RetryPolicy(**kwargs)

    def test_mock_contract_rejects_unexpected_result(self):
        with self.assertRaises(TypeError):
            exercise_offline_retry(lambda: {"status_code": 200}, lambda _: None)

    def test_non_2xx_non_5xx_stops(self):
        req, pause, attempts, _ = self.simulate([301, 200])
        with self.assertRaises(MockRequestStopped) as caught:
            exercise_offline_retry(req, pause)
        self.assertEqual(caught.exception.reason, "http_301_not_retryable")
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
