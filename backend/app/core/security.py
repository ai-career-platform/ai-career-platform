"""비밀번호 해시, 비교용 이메일, 토큰 발급·검증.

- 비밀번호: Argon2id (argon2-cffi 기본값). 원문은 어디에도 저장·기록하지 않는다.
- access token: JWT(HS256), 클레임 `sub`(user_id), `sid`(session_id), `roles`, `typ=access`.
- refresh token: 불투명 난수 문자열. DB에는 SHA-256 hex(64자)만 저장한다.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import APP_NAME

JWT_ALGORITHM = "HS256"
_hasher = PasswordHasher()
# 존재하지 않는 계정에도 같은 시간만큼 검증하도록 쓰는 더미 해시 (계정 존재 여부 추측 방지).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def canonical_email(email: str) -> str:
    """API_CONTRACT §1.2 비교용 이메일 규칙."""
    value = email.strip().lower()
    local, sep, domain = value.rpartition("@")
    if not sep:
        return value
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    roles: tuple[str, ...]


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


def issue_access_token(
    secret: str, user_id: uuid.UUID, session_id: uuid.UUID, roles: list[str], ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "iss": APP_NAME,
        "sub": str(user_id),
        "sid": str(session_id),
        "roles": sorted(roles),
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(secret: str, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], issuer=APP_NAME,
            options={"require": ["exp", "iat", "sub", "sid", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpired() from None
    except jwt.PyJWTError:
        raise TokenInvalid() from None
    if payload.get("typ") != "access":
        raise TokenInvalid()
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            roles=tuple(payload.get("roles") or ()),
        )
    except (ValueError, TypeError):
        raise TokenInvalid() from None
