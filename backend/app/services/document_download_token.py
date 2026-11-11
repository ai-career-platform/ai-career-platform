"""T144 만료형 문서 다운로드 토큰 (PROPOSED, 라우터 미연결).

현재 다운로드는 `GET /api/v1/documents/{id}/file`(Bearer 인증 + 소유자 확인)뿐이며 서명 URL이나
공개 URL은 없다. 이 모듈은 나중에 "짧게 유효한 다운로드 링크"가 필요해질 때 지켜야 할 계약을 고정한다.

- 토큰은 (소유자, 문서, 만료, 용도)를 HMAC-SHA256으로 묶는다. 키는 `JWT_SECRET`에서 용도별 파생
  (`derive_key(secret, PURPOSE)`)하므로 새 Secret이 필요 없고 JWT 서명 키와 섞이지 않는다.
- 최대 수명 15분. 토큰만으로는 내려받을 수 없고, 사용 시점에 다시 DB에서 소유·상태(ready)를 확인해야 한다.
  그래서 문서 삭제(deleting) 뒤에는 남은 토큰도 쓸 수 없다.
- 실패 사유를 구분해 알려 주지 않는다(만료만 TOKEN_EXPIRED, 나머지는 NOT_FOUND).
"""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import secrets
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import AppError, ErrorCode

PURPOSE = "t144-document-download-v1"
VERSION = 1
DEFAULT_TTL_SECONDS = 300
MAX_TTL_SECONDS = 900
_SIG = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    raw = base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    if _b64(raw) != text:
        raise ValueError("non-canonical")
    return raw


class DownloadTokenSigner:
    def __init__(self, key: bytes, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("download token key must be at least 32 bytes")
        if not (1 <= ttl_seconds <= MAX_TTL_SECONDS):
            raise ValueError("ttl out of range")
        self._key, self.ttl = key, ttl_seconds

    def __repr__(self) -> str:
        return f"DownloadTokenSigner(ttl={self.ttl})"

    def issue(self, owner: UUID, document_id: UUID, *, now: datetime) -> str:
        exp = int(now.astimezone(UTC).timestamp()) + self.ttl
        payload = json.dumps([VERSION, str(owner), str(document_id), exp, secrets.token_hex(8)],
                             separators=(",", ":")).encode()
        return _b64(payload) + "." + _b64(hmac.digest(self._key, payload, "sha256"))

    def verify(self, token: str, owner: UUID, document_id: UUID, *, now: datetime) -> None:
        """서명·대상 확인. 통과해도 호출부는 DB 소유·상태 확인을 반드시 다시 한다."""
        try:
            if not isinstance(token, str) or len(token) > 400 or token.count(".") != 1:
                raise ValueError("shape")
            body, sig = token.split(".")
            payload, signature = _unb64(body), _unb64(sig)
            if len(signature) != _SIG or not hmac.compare_digest(
                    signature, hmac.digest(self._key, payload, "sha256")):
                raise ValueError("signature")
            version, tok_owner, tok_doc, exp, _nonce = json.loads(payload)
            if version != VERSION or tok_owner != str(owner) or tok_doc != str(document_id):
                raise ValueError("target")
            if type(exp) is not int:
                raise ValueError("exp")
        except (ValueError, TypeError, binascii.Error):
            raise AppError(ErrorCode.NOT_FOUND, log_detail="download token rejected") from None
        if int(now.astimezone(UTC).timestamp()) >= exp:
            raise AppError(ErrorCode.TOKEN_EXPIRED, log_detail="download token expired")
