"""인증 업무 규칙: 가입·로그인·토큰 갱신·로그아웃·세션 관리 (FR-ACC-001~003, NFR-SEC-001)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.auth_config import AuthSettings
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import AttemptLimiter
from app.core.security import (
    canonical_email,
    hash_password,
    hash_token,
    issue_access_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.repositories.auth import AuthRepository, EmailTaken, NewUser, SessionRecord
from app.schemas.auth import ConsentPolicy, LoginRequest, SignupRequest

DEFAULT_ROLE = "job_seeker"
USER_AGENT_MAX = 300


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _rate_limited(seconds: int) -> AppError:
    # 남은 대기 시간은 Retry-After 헤더(초)로 알린다 (FR-ACC-002 예외 처리: 남은 대기 시간 안내).
    return AppError(ErrorCode.RATE_LIMITED, retry_after=seconds)


def _invalid_credentials() -> AppError:
    return AppError(ErrorCode.INVALID_CREDENTIALS)


def _unauthenticated(reason: str) -> AppError:
    return AppError(ErrorCode.UNAUTHENTICATED, log_detail=reason)


def is_session_active(session: SessionRecord | None, now: datetime) -> bool:
    return session is not None and session.revoked_at is None and session.expires_at > now


class AuthService:
    def __init__(self, repo: AuthRepository, settings: AuthSettings, limiter: AttemptLimiter) -> None:
        self.repo = repo
        self.settings = settings
        self.limiter = limiter

    # ---------------------------------------------------------------- policies
    def consent_policies(self) -> list[ConsentPolicy]:
        return [
            ConsentPolicy(
                policy_code=p.policy_code, version=p.version, is_required=p.is_required,
                content_url=p.content_url, effective_at=p.effective_at,
            )
            for p in self.repo.current_policies(_now())
        ]

    def _validate_consents(self, request: SignupRequest, now: datetime) -> list[tuple[str, str, bool]]:
        policies = {p.policy_code: p for p in self.repo.current_policies(now)}
        errors: list[str] = []
        seen: set[str] = set()
        for index, consent in enumerate(request.consents):
            field = f"consents[{index}]"
            policy = policies.get(consent.policy_code)
            if consent.policy_code in seen:
                errors.append(f"{field}:duplicate_policy")
            elif policy is None or policy.version != consent.policy_version:
                errors.append(f"{field}.policy_version:unknown_policy_version")
            seen.add(consent.policy_code)
        granted = {c.policy_code for c in request.consents if c.granted}
        for code, policy in sorted(policies.items()):
            if policy.is_required and code not in granted:
                errors.append(f"consents.{code}:required_consent_missing")
        if errors:
            # 응답은 공통 422 메시지만. 어떤 동의가 문제인지는 서버 로그에만 남긴다 (T06 공통 에러 계약).
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="consents: " + ", ".join(errors))
        return [(c.policy_code, c.policy_version, c.granted) for c in request.consents]

    # ---------------------------------------------------------------- sessions
    def _start_session(self, user_id: uuid.UUID, user_agent: str | None, now: datetime) -> IssuedTokens:
        refresh = new_refresh_token()
        expires_at = now + timedelta(seconds=self.settings.refresh_token_ttl_seconds)
        agent = user_agent[:USER_AGENT_MAX] if user_agent else None
        session_id = self.repo.create_session(user_id, hash_token(refresh), agent, now, expires_at)
        return self._tokens(user_id, session_id, refresh, now)

    def _tokens(self, user_id: uuid.UUID, session_id: uuid.UUID, refresh: str, now: datetime) -> IssuedTokens:
        ttl = self.settings.access_token_ttl_seconds
        access = issue_access_token(
            self.settings.jwt_secret, user_id, session_id, self.repo.role_codes(user_id), ttl, now=now,
        )
        return IssuedTokens(access_token=access, expires_in=ttl, refresh_token=refresh)

    # ---------------------------------------------------------------- signup / login
    def signup(self, request: SignupRequest, client_ip: str, user_agent: str | None) -> IssuedTokens:
        ip_key = f"signup-ip:{client_ip}"
        if wait := self.limiter.retry_after(ip_key):
            raise _rate_limited(wait)
        if wait := self.limiter.hit(ip_key, self.settings.signup_ip_max_attempts, 3600):
            raise _rate_limited(wait)

        now = _now()
        email_key = canonical_email(request.email)
        consents = self._validate_consents(request, now)
        if self.repo.email_exists(email_key):
            raise AppError(ErrorCode.EMAIL_TAKEN)
        try:
            user_id = self.repo.create_user(
                NewUser(
                    email=request.email, email_canonical=email_key, display_name=request.display_name,
                    password_hash=hash_password(request.password), consents=consents, role_code=DEFAULT_ROLE,
                ),
                now,
            )
            tokens = self._start_session(user_id, user_agent, now)
            self.repo.commit()
        except EmailTaken:
            raise AppError(ErrorCode.EMAIL_TAKEN) from None
        except Exception:
            self.repo.rollback()
            raise
        return tokens

    def login(self, request: LoginRequest, client_ip: str, user_agent: str | None) -> IssuedTokens:
        email_key = canonical_email(request.email)
        account_key = f"login-account:{email_key}"
        ip_key = f"login-ip:{client_ip}"
        if wait := max(self.limiter.retry_after(account_key), self.limiter.retry_after(ip_key)):
            raise _rate_limited(wait)
        if wait := self.limiter.hit(ip_key, self.settings.login_ip_max_attempts, self.settings.rate_window_seconds):
            raise _rate_limited(wait)

        identity = self.repo.find_local_identity(email_key)
        password_ok = verify_password(identity.password_hash if identity else None, request.password)
        # 탈퇴 요청·정지(disabled) 계정도 같은 401로 응답해 상태를 드러내지 않는다 (FR-ACC-002 기준 2·4).
        if identity is None or not password_ok or identity.status != "active":
            if wait := self.limiter.hit(
                account_key, self.settings.login_max_failures,
                self.settings.rate_window_seconds, self.settings.login_lock_seconds,
            ):
                raise _rate_limited(wait)
            raise _invalid_credentials()

        self.limiter.reset(account_key)
        now = _now()
        try:
            if identity.password_hash and password_needs_rehash(identity.password_hash):
                self.repo.update_password_hash(identity.user_id, hash_password(request.password), now)
            self.repo.touch_last_login(identity.user_id, now)
            tokens = self._start_session(identity.user_id, user_agent, now)
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            raise
        return tokens

    # ---------------------------------------------------------------- refresh / logout
    def _session_for_refresh(self, refresh_token: str | None, now: datetime) -> tuple[SessionRecord, str]:
        if not refresh_token:
            raise _unauthenticated("refresh cookie missing")
        old_hash = hash_token(refresh_token)
        session = self.repo.find_session_by_refresh(old_hash)
        if not is_session_active(session, now):
            raise _unauthenticated("refresh session not found, revoked or expired")
        user = self.repo.get_user(session.user_id)
        if user is None or user.status != "active":
            raise _unauthenticated("refresh user missing or disabled")
        return session, old_hash

    def refresh(self, refresh_token: str | None) -> IssuedTokens:
        now = _now()
        try:
            session, old_hash = self._session_for_refresh(refresh_token, now)
            new_refresh = new_refresh_token()
            if not self.repo.rotate_refresh(session.session_id, old_hash, hash_token(new_refresh)):
                raise _unauthenticated("refresh rotation lost a race")
            tokens = self._tokens(session.user_id, session.session_id, new_refresh, now)
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            raise
        return tokens

    def logout(self, refresh_token: str | None) -> None:
        now = _now()
        try:
            session, _ = self._session_for_refresh(refresh_token, now)
            self.repo.revoke_session(session.session_id, session.user_id, now)
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            raise

    # ---------------------------------------------------------------- my sessions
    def list_sessions(self, user_id: uuid.UUID) -> list[SessionRecord]:
        return self.repo.list_active_sessions(user_id, _now())

    def revoke_my_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        # 다른 사람 세션·없는 세션·이미 끝난 세션은 모두 404 (소유권 은닉, API_CONTRACT §1.3).
        try:
            if not self.repo.revoke_session(session_id, user_id, _now()):
                raise AppError(ErrorCode.NOT_FOUND)
            self.repo.commit()
        except Exception:
            self.repo.rollback()
            raise
