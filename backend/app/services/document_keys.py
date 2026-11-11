"""T144 문서 저장 암호화 키 관리 계약 (PROPOSED, 미연결).

현재 운영 경로(`routers/documents.py` → `DirectoryDocumentStorage`)는 **평문 저장**이다.
이 모듈은 봉투 암호화(envelope encryption) 계약을 코드와 시험으로 고정하기 위한 것으로,
라우터·설정·환경변수에 연결하지 않았다. 연결은 PM 승인과 승인된 암호 라이브러리(AES-256-GCM)가
T118 공급망 게이트를 통과한 뒤 별도 PR에서 한다.

구조
- KEK(Key Encryption Key): `kek_id`로 식별. 상태 active → decrypt_only → retired.
  active는 항상 하나. 새 객체는 active KEK로만 감싼다.
- DEK(Data Encryption Key): 객체마다 새로 만드는 32바이트 키. KEK로 감싸 객체 머리에 둔다.
- 본문 AAD는 객체 머리의 `object_id`라서 KEK 회전(rewrap) 때 본문 암호문은 그대로 두고 DEK만 다시 감싼다.
- 객체 바꿔치기는 `DocumentService.download`의 크기·SHA-256 검사(DB 메타데이터)로 막힌다.
- 오류는 키 id·저장 키·내용을 담지 않은 `AppError(DEPENDENCY_UNAVAILABLE)`로만 올린다.

암호 구현(Cipher)은 주입한다. 운영 승인 알고리즘은 `APPROVED_ALGORITHMS`뿐이며,
시험용 구현은 `allow_simulation=True`일 때만 받는다.
"""
from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from app.core.errors import AppError, ErrorCode
from app.services.document_storage import DocumentStorage

MAGIC = b"AICPENC1"
FORMAT_VERSION = 1
DEK_BYTES = 32
APPROVED_ALGORITHMS = frozenset({"AES-256-GCM"})
_MAX_HEADER = 4096


class CipherError(ValueError):
    """인증 실패·형식 오류. 메시지에 키·평문을 넣지 않는다."""


class Cipher(Protocol):
    algorithm: str

    def seal(self, key: bytes, plaintext: bytes, aad: bytes) -> bytes: ...
    def open(self, key: bytes, sealed: bytes, aad: bytes) -> bytes: ...


class KeyState(str, Enum):
    ACTIVE = "active"
    DECRYPT_ONLY = "decrypt_only"
    RETIRED = "retired"


class KeyUnavailable(Exception):
    """KEK가 없거나 폐기됨. 호출부는 fail-closed 한다."""


@dataclass
class _Kek:
    kek_id: str
    material: bytes = field(repr=False)
    state: KeyState


def _check_kek_id(kek_id: str) -> str:
    if not isinstance(kek_id, str) or not (1 <= len(kek_id) <= 64) or not all(
            c.isalnum() or c in "-_." for c in kek_id):
        raise ValueError("invalid kek_id")
    return kek_id


class KeyRing:
    """KEK 목록과 상태. 실제 키 원본은 외부 KMS/Secret 저장소에서 주입한다(이 계약의 범위 밖)."""

    def __init__(self) -> None:
        self._keys: dict[str, _Kek] = {}
        self._active: str | None = None

    def __repr__(self) -> str:  # 키 원본이 로그에 남지 않게 한다.
        return f"KeyRing(active={self._active!r}, keys={[(k, v.state.value) for k, v in self._keys.items()]})"

    @property
    def active_id(self) -> str:
        if self._active is None:
            raise KeyUnavailable()
        return self._active

    def state(self, kek_id: str) -> KeyState | None:
        entry = self._keys.get(kek_id)
        return entry.state if entry else None

    def add_active(self, kek_id: str, material: bytes) -> None:
        """새 KEK를 active로 올리고 이전 active는 decrypt_only로 내린다(회전)."""
        _check_kek_id(kek_id)
        if not isinstance(material, bytes) or len(material) < 32:
            raise ValueError("KEK material must be at least 32 bytes")
        if kek_id in self._keys:
            raise ValueError("kek_id already used; ids are never reused")
        if self._active is not None:
            self._keys[self._active].state = KeyState.DECRYPT_ONLY
        self._keys[kek_id] = _Kek(kek_id, material, KeyState.ACTIVE)
        self._active = kek_id

    def retire(self, kek_id: str, *, remaining_references: int) -> None:
        """참조하는 객체가 0일 때만 폐기한다. 폐기 후 키 원본은 버린다(복구 불가)."""
        entry = self._keys.get(kek_id)
        if entry is None:
            raise KeyUnavailable()
        if entry.state is KeyState.ACTIVE:
            raise ValueError("cannot retire the active KEK; rotate first")
        if remaining_references != 0:
            raise ValueError("KEK still referenced by stored objects; rewrap first")
        entry.state, entry.material = KeyState.RETIRED, b""

    def material_for_wrap(self) -> tuple[str, bytes]:
        entry = self._keys[self.active_id]
        return entry.kek_id, entry.material

    def material_for_unwrap(self, kek_id: str) -> bytes:
        entry = self._keys.get(kek_id)
        if entry is None or entry.state is KeyState.RETIRED:
            raise KeyUnavailable()
        return entry.material


def _unavailable() -> AppError:
    return AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


@dataclass(frozen=True)
class EnvelopeHeader:
    kek_id: str
    object_id: str
    algorithm: str
    wrapped_dek: bytes


def _dek_aad(kek_id: str, object_id: str) -> bytes:
    return f"aicp-dek:v{FORMAT_VERSION}:{kek_id}:{object_id}".encode()


def _body_aad(object_id: str) -> bytes:
    return f"aicp-doc:v{FORMAT_VERSION}:{object_id}".encode()


def encode_envelope(header: EnvelopeHeader, body: bytes) -> bytes:
    raw = json.dumps({"v": FORMAT_VERSION, "kek_id": header.kek_id, "object_id": header.object_id,
                      "alg": header.algorithm,
                      "dek": base64.b64encode(header.wrapped_dek).decode()}, separators=(",", ":")).encode()
    return MAGIC + len(raw).to_bytes(2, "big") + raw + body


def is_envelope(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def decode_envelope(blob: bytes) -> tuple[EnvelopeHeader, bytes]:
    if not is_envelope(blob) or len(blob) < len(MAGIC) + 2:
        raise CipherError("not an envelope")
    size = int.from_bytes(blob[len(MAGIC):len(MAGIC) + 2], "big")
    start = len(MAGIC) + 2
    if size == 0 or size > _MAX_HEADER or len(blob) < start + size:
        raise CipherError("bad header length")
    try:
        data = json.loads(blob[start:start + size])
        if data["v"] != FORMAT_VERSION:
            raise CipherError("unsupported version")
        header = EnvelopeHeader(_check_kek_id(data["kek_id"]), str(data["object_id"]), str(data["alg"]),
                                base64.b64decode(data["dek"], validate=True))
    except CipherError:
        raise
    except (ValueError, KeyError, TypeError):
        raise CipherError("bad header") from None
    return header, blob[start + size:]


class EncryptedDocumentStorage:
    """`DocumentStorage` 데코레이터. 내부 저장소에는 봉투 암호문만 쓴다.

    - put: 객체마다 새 DEK, active KEK로 감싼다.
    - read: 봉투가 아니면(기존 평문 객체) 기본 거부. 이행 기간에만 `allow_legacy_plaintext=True`.
    - 폐기(retired)되었거나 모르는 KEK, 변조, 다른 알고리즘 → fail-closed 503.
    """

    def __init__(self, inner: DocumentStorage, keyring: KeyRing, cipher: Cipher, *,
                 allow_simulation: bool = False, allow_legacy_plaintext: bool = False,
                 random_bytes: Callable[[int], bytes] = secrets.token_bytes) -> None:
        if cipher.algorithm not in APPROVED_ALGORITHMS and not allow_simulation:
            raise ValueError("cipher algorithm is not approved for document storage")
        self.inner, self.keyring, self.cipher = inner, keyring, cipher
        self.allow_legacy_plaintext = allow_legacy_plaintext
        self._random = random_bytes

    def _seal(self, content: bytes) -> bytes:
        object_id = self._random(16).hex()
        dek = self._random(DEK_BYTES)
        try:
            kek_id, kek = self.keyring.material_for_wrap()
        except KeyUnavailable:
            raise _unavailable() from None
        body = self.cipher.seal(dek, content, _body_aad(object_id))
        wrapped = self.cipher.seal(kek, dek, _dek_aad(kek_id, object_id))
        return encode_envelope(EnvelopeHeader(kek_id, object_id, self.cipher.algorithm, wrapped), body)

    def _unwrap(self, header: EnvelopeHeader) -> bytes:
        if header.algorithm != self.cipher.algorithm:
            raise CipherError("algorithm mismatch")
        kek = self.keyring.material_for_unwrap(header.kek_id)
        dek = self.cipher.open(kek, header.wrapped_dek, _dek_aad(header.kek_id, header.object_id))
        if len(dek) != DEK_BYTES:
            raise CipherError("bad dek")
        return dek

    def put(self, key: str, content: bytes) -> None:
        self.inner.put(key, self._seal(content))

    def read(self, key: str) -> bytes:
        blob = self.inner.read(key)
        if not is_envelope(blob):
            if self.allow_legacy_plaintext:
                return blob
            raise _unavailable()
        try:
            header, body = decode_envelope(blob)
            return self.cipher.open(self._unwrap(header), body, _body_aad(header.object_id))
        except (CipherError, KeyUnavailable):
            raise _unavailable() from None

    def delete(self, key: str) -> None:
        self.inner.delete(key)

    def kek_of(self, key: str) -> str | None:
        """재감싸기 대상 집계용. 평문 객체는 None."""
        blob = self.inner.read(key)
        if not is_envelope(blob):
            return None
        try:
            return decode_envelope(blob)[0].kek_id
        except CipherError:
            raise _unavailable() from None

    def rewrap_to(self, old_key: str, new_key: str) -> None:
        """KEK 회전. 본문 암호문은 바꾸지 않고 DEK만 active KEK로 다시 감싸 새 저장 키에 쓴다.

        저장소는 덮어쓰기를 허용하지 않으므로(copy-on-rewrap): 새 키에 쓰기 → DB `storage_key` 교체
        → 옛 객체 삭제 순서로 호출부(배치)가 처리한다. 중간 실패 시 옛 객체가 그대로 남아 읽을 수 있다.
        """
        blob = self.inner.read(old_key)
        try:
            header, body = decode_envelope(blob)
            dek = self._unwrap(header)
            kek_id, kek = self.keyring.material_for_wrap()
        except (CipherError, KeyUnavailable):
            raise _unavailable() from None
        wrapped = self.cipher.seal(kek, dek, _dek_aad(kek_id, header.object_id))
        self.inner.put(new_key, encode_envelope(
            EnvelopeHeader(kek_id, header.object_id, header.algorithm, wrapped), body))

    def migrate_plaintext(self, old_key: str, new_key: str) -> None:
        """기존 평문 객체를 암호화본으로 복사한다(이행 배치용). 이미 봉투면 거부."""
        blob = self.inner.read(old_key)
        if is_envelope(blob):
            raise _unavailable()
        self.put(new_key, blob)
