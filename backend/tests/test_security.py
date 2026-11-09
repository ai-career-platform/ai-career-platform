"""비교용 이메일·비밀번호 해시·시도 제한 단위 테스트."""

import pytest

from app.core.rate_limit import AttemptLimiter
from app.core.security import canonical_email, hash_password, verify_password


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Seeker@Example.com ", "seeker@example.com"),
        ("crasnec+box@gmail.com", "crasnec@gmail.com"),
        ("Cras.Nec@googlemail.com", "crasnec@gmail.com"),
        ("first.last+tag@company.co.kr", "first.last@company.co.kr"),
    ],
)
def test_canonical_email(raw, expected):
    assert canonical_email(raw) == expected


def test_password_hash_roundtrip_and_no_plaintext():
    hashed = hash_password("correct-horse-battery-1")
    assert hashed.startswith("$argon2id$") and "correct-horse" not in hashed
    assert verify_password(hashed, "correct-horse-battery-1")
    assert not verify_password(hashed, "wrong")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


def test_limiter_locks_and_expires():
    now = [0.0]
    limiter = AttemptLimiter(clock=lambda: now[0])
    assert limiter.hit("k", limit=3, window=60, lock_seconds=30) == 0
    assert limiter.hit("k", limit=3, window=60, lock_seconds=30) == 0
    assert limiter.hit("k", limit=3, window=60, lock_seconds=30) == 30
    now[0] = 10
    assert limiter.retry_after("k") == 20
    now[0] = 31
    assert limiter.retry_after("k") == 0


def test_limiter_window_slides():
    now = [0.0]
    limiter = AttemptLimiter(clock=lambda: now[0])
    limiter.hit("k", limit=2, window=60)
    now[0] = 61
    assert limiter.hit("k", limit=2, window=60) == 0
