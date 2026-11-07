"""Deterministic *offline* retry/stop policy exercises; never performs HTTP.

The caller injects a fake request function and a fake sleep recorder. This is
not wired to the CLI or to the actual JobKorea website.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MockResponse:
    status_code: int


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 4.0
    min_interval_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not (1 <= self.max_attempts <= 5):
            raise ValueError("max_attempts must be between 1 and 5")
        if self.base_backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("backoff delays must be non-negative")
        if self.min_interval_seconds < 0:
            raise ValueError("minimum interval must be non-negative")


class MockRequestStopped(RuntimeError):
    """An unsafe/non-retryable response stopped this training sequence."""

    def __init__(self, reason: str, attempts: int) -> None:
        self.reason = reason
        self.attempts = attempts
        super().__init__(reason)


class MockRetriesExhausted(RuntimeError):
    """Transient failures did not recover inside the bounded budget."""

    def __init__(self, attempts: int) -> None:
        self.attempts = attempts
        super().__init__("retry budget exhausted")


def exercise_offline_retry(
    request: Callable[[], MockResponse],
    sleep: Callable[[float], None],
    policy: RetryPolicy = RetryPolicy(),
) -> tuple[MockResponse, int]:
    """Run a supplied fake request with deterministic bounded retry behavior.

    No network library is imported. The caller must provide a mock request.
    HTTP 403/429 are stop signals, never bypassed or retried here.
    HTTP 5xx, timeout and connection failures may retry within a hard budget.
    The mock sleep callback records requested delays; it need not actually wait.
    """
    for attempt in range(1, policy.max_attempts + 1):
        if attempt > 1:
            # One pause satisfies both the retry backoff and minimum spacing.
            delay = min(
                policy.base_backoff_seconds * (2 ** (attempt - 2)),
                policy.max_backoff_seconds,
            )
            sleep(max(policy.min_interval_seconds, delay))
        try:
            response = request()
        except (TimeoutError, ConnectionError):
            if attempt == policy.max_attempts:
                raise MockRetriesExhausted(attempt) from None
            continue

        if not isinstance(response, MockResponse):
            raise TypeError("mock request must return MockResponse")

        status = response.status_code
        if status in (403, 429):
            raise MockRequestStopped(f"http_{status}_stop", attempt)
        if 500 <= status <= 599:
            if attempt == policy.max_attempts:
                raise MockRetriesExhausted(attempt)
            continue
        if 200 <= status <= 299:
            return response, attempt
        raise MockRequestStopped(f"http_{status}_not_retryable", attempt)

    raise AssertionError("unreachable")
