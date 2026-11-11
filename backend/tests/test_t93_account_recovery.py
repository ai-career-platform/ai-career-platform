"""T93 비밀번호 재설정 서비스 단위 시험 (메모리 저장소·메모리 메일, DB·실제 메일 없음)."""
import hashlib
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.core.rate_limit import AttemptLimiter
from app.core.security import verify_password
from app.repositories.account_recovery import ResetToken
from app.services.account_recovery import TOKEN_TTL, AccountRecoveryService, token_hash
from app.services.mail import MemoryMailSender, UnavailableMailSender

NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
ALICE = uuid.UUID(int=0x93A)
EMAIL = "t93-alice@example.com"
NEW_PASSWORD = "new-correct-horse-93"


class FakeRepo:
    def __init__(self):
        self.users = {EMAIL: (ALICE, "active"), "t93-disabled@example.com": (uuid.UUID(int=0x93B), "disabled")}
        self.tokens: dict[str, ResetToken] = {}
        self.pending: dict[str, ResetToken] = {}
        self.password_hash: dict[uuid.UUID, str] = {}
        self.sessions_open = {ALICE: 2}
        self.audit: list[tuple] = []
        self.commits = 0

    def find_active_local_user(self, email_canonical):
        found = self.users.get(email_canonical)
        return found[0] if found and found[1] == "active" else None

    def create_token(self, user_id, token_hash_, now, expires_at):
        self.pending[token_hash_] = ResetToken(uuid.uuid4(), user_id, expires_at, None, "active")

    def lock_token(self, token_hash_):
        return self.tokens.get(token_hash_)

    def consume(self, token, password_hash, now, request_id):
        self.password_hash[token.user_id] = password_hash
        for key, value in list(self.tokens.items()):
            if value.user_id == token.user_id and value.used_at is None:
                self.tokens[key] = replace(value, used_at=now)
        revoked, self.sessions_open[token.user_id] = self.sessions_open.get(token.user_id, 0), 0
        self.audit.append(("auth.password.reset", token.user_id, request_id))
        return revoked

    def commit(self):
        self.tokens.update(self.pending)
        self.pending.clear()
        self.commits += 1

    def rollback(self):
        self.pending.clear()


@pytest.fixture
def env():
    repo, mail = FakeRepo(), MemoryMailSender()
    return repo, mail, AccountRecoveryService(repo, mail, AttemptLimiter(), "/password-reset", clock=lambda: NOW)


def token_from(mail) -> str:
    return mail.outbox[-1].link.split("token=", 1)[1]


# ---------------------------------------------------------------- request
def test_same_result_for_existing_unknown_and_disabled_accounts(env):
    repo, mail, service = env
    for i, email in enumerate([EMAIL, "nobody@example.com", "t93-disabled@example.com"]):
        assert service.request_reset(email, f"203.0.113.{i}") is None
    assert len(mail.outbox) == 1 and mail.outbox[0].to == EMAIL
    assert len(repo.tokens) == 1


def test_only_the_hash_is_stored_and_the_link_has_the_raw_token(env):
    repo, mail, service = env
    service.request_reset(EMAIL, "203.0.113.1")
    raw = token_from(mail)
    (stored,) = repo.tokens
    assert stored == hashlib.sha256(raw.encode()).hexdigest() and raw not in stored
    assert len(raw) >= 40 and mail.outbox[0].link.startswith("/password-reset?token=")
    assert repo.tokens[stored].expires_at == NOW + TOKEN_TTL == NOW + timedelta(minutes=30)


def test_no_mail_provider_gives_everyone_the_same_503(env):
    repo, _, _ = env
    service = AccountRecoveryService(repo, UnavailableMailSender(), AttemptLimiter(), "/password-reset", clock=lambda: NOW)
    codes = set()
    for email in (EMAIL, "nobody@example.com"):
        with pytest.raises(AppError) as err:
            service.request_reset(email, "203.0.113.1")
        codes.add((err.value.status, err.value.code))
    assert codes == {(503, "DEPENDENCY_UNAVAILABLE")} and repo.tokens == {}


def test_mail_failure_is_retried_then_delivered(env):
    repo, _, _ = env
    mail = MemoryMailSender(fail_times=2)
    AccountRecoveryService(repo, mail, AttemptLimiter(), "/r", clock=lambda: NOW).request_reset(EMAIL, "203.0.113.1")
    assert mail.attempts == 3 and len(mail.outbox) == 1 and len(repo.tokens) == 1


def test_mail_failure_after_all_retries_keeps_no_token_and_answers_the_same(env):
    repo, _, _ = env
    mail = MemoryMailSender(fail_times=5)
    assert AccountRecoveryService(repo, mail, AttemptLimiter(), "/r", clock=lambda: NOW).request_reset(EMAIL, "203.0.113.1") is None
    assert mail.attempts == 3 and mail.outbox == [] and repo.tokens == {}


def test_request_rate_limits_per_email_and_per_ip(env):
    _, _, service = env
    for i in range(3):
        service.request_reset(EMAIL, f"198.51.100.{i}")
    with pytest.raises(AppError) as err:
        service.request_reset(EMAIL, "198.51.100.99")
    assert err.value.status == 429 and int(err.value.headers["Retry-After"]) > 0
    for i in range(10):
        service.request_reset(f"other{i}@example.com", "192.0.2.7")
    with pytest.raises(AppError):
        service.request_reset("other-x@example.com", "192.0.2.7")


def test_logs_never_contain_email_token_or_link(env, caplog):
    repo, _, _ = env
    mail = MemoryMailSender(fail_times=5)
    service = AccountRecoveryService(repo, mail, AttemptLimiter(), "/r", clock=lambda: NOW)
    with caplog.at_level(logging.DEBUG):
        service.request_reset(EMAIL, "203.0.113.1")
    assert caplog.records and EMAIL not in caplog.text and "token=" not in caplog.text


# ---------------------------------------------------------------- reset
def issue(env) -> str:
    _, mail, service = env
    service.request_reset(EMAIL, "203.0.113.1")
    return token_from(mail)


def test_valid_token_changes_password_revokes_sessions_and_audits(env):
    repo, _, service = env
    raw = issue(env)
    revoked = service.reset_password(raw, NEW_PASSWORD, "203.0.113.1", "req-t93-0001")
    assert revoked == 2 and repo.sessions_open[ALICE] == 0
    assert verify_password(repo.password_hash[ALICE], NEW_PASSWORD)
    assert repo.audit == [("auth.password.reset", ALICE, "req-t93-0001")]
    assert repo.tokens[token_hash(raw)].used_at == NOW


@pytest.mark.parametrize("case", ["reused", "expired", "unknown", "disabled_user", "older_token_after_newer_use"])
def test_every_invalid_token_gets_the_same_400(env, case):
    repo, mail, service = env
    raw = issue(env)
    if case == "reused":
        service.reset_password(raw, NEW_PASSWORD, "203.0.113.1", None)
    elif case == "expired":
        repo.tokens[token_hash(raw)] = replace(repo.tokens[token_hash(raw)], expires_at=NOW)
    elif case == "unknown":
        raw = "x" * 43
    elif case == "disabled_user":
        repo.tokens[token_hash(raw)] = replace(repo.tokens[token_hash(raw)], user_status="disabled")
    elif case == "older_token_after_newer_use":
        service.request_reset(EMAIL, "203.0.113.2")
        service.reset_password(token_from(mail), NEW_PASSWORD, "203.0.113.1", None)   # 새 토큰 사용 → 이전 토큰도 무효
    with pytest.raises(AppError) as err:
        service.reset_password(raw, "another-password-93", "203.0.113.1", None)
    assert (err.value.status, err.value.code) == (400, "INVALID_RESET_TOKEN")


def test_token_guessing_is_rate_limited_per_ip(env):
    _, _, service = env
    for _ in range(10):
        with pytest.raises(AppError) as err:
            service.reset_password("g" * 43, NEW_PASSWORD, "192.0.2.50", None)
        assert err.value.status == 400
    with pytest.raises(AppError) as err:
        service.reset_password("g" * 43, NEW_PASSWORD, "192.0.2.50", None)
    assert err.value.status == 429
