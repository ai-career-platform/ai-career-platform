"""T93 비밀번호 재설정 (확정 계약: POST /auth/password-reset-requests, POST /auth/password-resets).

보안 규칙
- 계정 열거 방지: 가입 여부·상태와 관계없이 같은 202(본문 없음). 메일 공급자가 없으면 **모두** 같은 503.
- 토큰: 32바이트 난수(urlsafe), DB 에는 sha256 만, 30분 유효(DB CHECK 와 같음), 한 번만 사용.
- 재설정 성공: 비밀번호 해시 교체 + 남은 토큰 모두 무효 + **모든 세션 종료** + 감사 기록(auth.password.reset) — 한 트랜잭션.
- 실패 응답은 원인(없음·사용됨·만료·비활성)과 관계없이 같은 400 INVALID_RESET_TOKEN.
- 요청 빈도 제한: 이메일·IP 별(429 + Retry-After). 값은 운영 기본값 제안(미승인 — 문서 §5).
- 메일 발송 실패: 즉시 최대 2회 재시도, 모두 실패하면 토큰을 저장하지 않고(롤백) 같은 202 — 사용자는 다시 요청.
- 로그: 이메일·토큰·링크·비밀번호를 남기지 않습니다.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import AttemptLimiter
from app.core.security import canonical_email, hash_password
from app.repositories.account_recovery import RecoveryRepository
from app.services.mail import MailDeliveryError, MailSender, OutgoingMail

logger = logging.getLogger(__name__)

TOKEN_TTL = timedelta(minutes=30)            # 확정 계약·DB CHECK
SEND_ATTEMPTS = 3                            # 첫 시도 + 재시도 2회
REQUEST_PER_EMAIL = (3, 3600)               # 제안: 이메일당 1시간 3회
REQUEST_PER_IP = (10, 3600)                 # 제안: IP 당 1시간 10회
RESET_PER_IP = (10, 900)                    # 제안: IP 당 15분 10회 (토큰 추측 방지)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountRecoveryService:
    def __init__(self, repo: RecoveryRepository, mail: MailSender, limiter: AttemptLimiter, link_base: str,
                 clock=lambda: datetime.now(UTC)) -> None:
        self.repo, self.mail, self.limiter, self.link_base, self.clock = repo, mail, limiter, link_base, clock

    def _limit(self, key: str, rule: tuple[int, int]) -> None:
        if wait := self.limiter.retry_after(key):
            raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)
        if wait := self.limiter.hit(key, rule[0] + 1, rule[1]):
            raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)

    # ------------------------------------------------------------ POST /auth/password-reset-requests
    def request_reset(self, email: str, client_ip: str) -> None:
        if not self.mail.available:
            # 발송할 수 없으면 가입 여부를 보기 전에 모두에게 같은 503 (열거 방지 + 거짓 접수 방지)
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="password reset: mail provider not configured")
        canonical = canonical_email(email)
        self._limit(f"pwreset-ip:{client_ip}", REQUEST_PER_IP)
        self._limit("pwreset-email:" + hashlib.sha256(canonical.encode()).hexdigest(), REQUEST_PER_EMAIL)
        token = secrets.token_urlsafe(32)
        try:
            user_id = self.repo.find_active_local_user(canonical)
            if user_id is None:
                return   # 같은 202 — 없는 계정·비활성 계정에는 아무것도 하지 않음
            now = self.clock()
            self.repo.create_token(user_id, token_hash(token), now, now + TOKEN_TTL)
            link = f"{self.link_base}?token={quote(token)}"
            for attempt in range(1, SEND_ATTEMPTS + 1):
                try:
                    self.mail.send(OutgoingMail(to=email, template="password_reset", link=link))
                    break
                except MailDeliveryError:
                    logger.warning("password reset mail delivery failed attempt=%d/%d", attempt, SEND_ATTEMPTS)
            else:
                self.repo.rollback()      # 보내지 못한 토큰은 남기지 않음
                logger.error("password reset mail not delivered after %d attempts", SEND_ATTEMPTS)
                return
            self.repo.commit()
        except OperationalError as exc:
            self.repo.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except SQLAlchemyError:
            self.repo.rollback()
            raise

    # ------------------------------------------------------------ POST /auth/password-resets
    def reset_password(self, token: str, new_password: str, client_ip: str, request_id: str | None) -> int:
        self._limit(f"pwreset-use-ip:{client_ip}", RESET_PER_IP)
        invalid = AppError(ErrorCode.INVALID_RESET_TOKEN, log_detail="reset token unknown, used, expired or user inactive")
        try:
            found = self.repo.lock_token(token_hash(token))
            now = self.clock()
            if found is None or found.used_at is not None or found.expires_at <= now or found.user_status != "active":
                self.repo.rollback()
                raise invalid
            revoked = self.repo.consume(found, hash_password(new_password), now, request_id)
            self.repo.commit()
            return revoked
        except AppError:
            raise
        except OperationalError as exc:
            self.repo.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except SQLAlchemyError:
            self.repo.rollback()
            raise
