"""T144 문서 스토리지 보안 회귀.

- 기존 T49 라우터·서비스의 ACL·삭제 후 차단·공개 URL 부재·경로 검사 회귀 (실제 T15 인증 + SQLite 저장소).
- 저장 시 암호화 상태 사실 확인: 현재 DirectoryDocumentStorage는 평문 저장 (FINDING F-1).
- 봉투 암호화 계약(`document_keys`)과 KEK 회전 시뮬레이션: **합성 키만** 사용. 실제 키를 만들거나 바꾸지 않는다.
- 만료형 다운로드 토큰(`document_download_token`) 계약.

SimulationCipher는 표준 라이브러리 HMAC-SHA256 기반 시험 전용 구현이다. 운영 승인 알고리즘이 아니며
`EncryptedDocumentStorage`는 `allow_simulation=True` 없이는 받지 않는다.
"""
import hashlib
import hmac
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.env_contract import CONTRACT
from app.core.errors import AppError, ErrorCode
from app.core.security import derive_key
from app.models.documents import UserDocument
from app.repositories.documents import SqlDocumentRepository
from app.routers.documents import get_document_service, get_document_storage
from app.services.document_download_token import MAX_TTL_SECONDS, PURPOSE, DownloadTokenSigner
from app.services.document_keys import (
    APPROVED_ALGORITHMS, CipherError, EncryptedDocumentStorage, KeyRing, KeyState, KeyUnavailable,
    decode_envelope, encode_envelope, is_envelope,
)
from dataclasses import replace
from app.services.document_storage import DirectoryDocumentStorage, UnavailableDocumentStorage
from app.services.document_validation import PDF
from app.services.documents import DocumentService
from app.services.job_postings import ListCursor
from tests.conftest import bearer, signup

BASE = "/api/v1/documents"
SAMPLE = b"%PDF-1.7\nT144 synthetic fixture\n%%EOF"
POSIX = hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and sys.platform != "win32"


# --------------------------------------------------------------------------- 시험 도구
class MemoryStorage:
    """DirectoryDocumentStorage와 같은 키 규칙·덮어쓰기 금지·멱등 삭제를 지키는 메모리 저장소."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, key, content):
        key = DirectoryDocumentStorage._key(key)
        if key in self.objects:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        self.objects[key] = bytes(content)

    def read(self, key):
        key = DirectoryDocumentStorage._key(key)
        if key not in self.objects:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        return self.objects[key]

    def delete(self, key):
        self.objects.pop(DirectoryDocumentStorage._key(key), None)


class SimulationCipher:
    """시험 전용: HMAC-SHA256 카운터 키스트림 + encrypt-then-MAC. 운영 사용 금지."""
    algorithm = "SIM-HMAC-SHA256-CTR"

    @staticmethod
    def _keys(key):
        return hmac.digest(key, b"enc", "sha256"), hmac.digest(key, b"mac", "sha256")

    @staticmethod
    def _stream(key, nonce, size):
        out = bytearray()
        counter = 0
        while len(out) < size:
            out += hmac.digest(key, nonce + counter.to_bytes(8, "big"), "sha256")
            counter += 1
        return bytes(out[:size])

    def seal(self, key, plaintext, aad):
        enc, mac = self._keys(key)
        nonce = secrets.token_bytes(16)
        ct = bytes(a ^ b for a, b in zip(plaintext, self._stream(enc, nonce, len(plaintext))))
        tag = hmac.digest(mac, nonce + len(aad).to_bytes(4, "big") + aad + ct, "sha256")
        return nonce + ct + tag

    def open(self, key, sealed, aad):
        if len(sealed) < 48:
            raise CipherError("short")
        enc, mac = self._keys(key)
        nonce, ct, tag = sealed[:16], sealed[16:-32], sealed[-32:]
        if not hmac.compare_digest(tag, hmac.digest(mac, nonce + len(aad).to_bytes(4, "big") + aad + ct, "sha256")):
            raise CipherError("auth")
        return bytes(a ^ b for a, b in zip(ct, self._stream(enc, nonce, len(ct))))


def synthetic_kek():
    return secrets.token_bytes(32)  # 실행마다 새로 만드는 합성 키. 저장·출력하지 않는다.


def key():
    return secrets.token_hex(32)


@pytest.fixture
def docs(app):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS career")
        conn.commit()
    UserDocument.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    service = DocumentService(SqlDocumentRepository(session), MemoryStorage(), ListCursor(b"d" * 32))
    app.dependency_overrides[get_document_service] = lambda: service
    yield service
    session.close()
    engine.dispose()


def login(client, email):
    return bearer(signup(client, email=email).json()["access_token"])


def upload(client, headers, content=SAMPLE):
    return client.post(BASE, headers=headers, data={"kind": "resume"},
                       files={"file": ("t144.pdf", content, PDF)})


def ready(client, docs, headers):
    response = upload(client, headers)
    assert response.status_code == 202, response.text
    doc_id = UUID(response.json()["document_id"])
    owner = docs.repo.session.get(UserDocument, doc_id).owner_user_id
    docs.verify(owner, doc_id)
    return doc_id, owner


# --------------------------------------------------------------------------- ACL 회귀 (T49)
def test_other_user_gets_404_on_every_document_route(client, docs):
    alice, bob = login(client, "t144-alice@example.com"), login(client, "t144-bob@example.com")
    doc_id, _ = ready(client, docs, alice)
    path = f"{BASE}/{doc_id}"
    assert client.get(path + "/file", headers=alice).status_code == 200
    for method, url in (("get", path), ("get", path + "/file"), ("delete", path)):
        response = client.request(method.upper(), url, headers=bob)
        assert response.status_code == 404, (method, url)
        assert response.json()["code"] == "NOT_FOUND"
        assert "t144.pdf" not in response.text
    assert client.get(BASE, headers=bob).json()["items"] == []
    # 남의 삭제 시도 뒤에도 소유자는 그대로 내려받는다.
    assert client.get(path + "/file", headers=alice).content == SAMPLE


def test_anonymous_and_bad_token_rejected(client, docs):
    alice = login(client, "t144-anon@example.com")
    doc_id, _ = ready(client, docs, alice)
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}):
        assert client.get(f"{BASE}/{doc_id}/file", headers=headers).status_code == 401
        assert upload(client, headers).status_code == 401


def test_deleted_document_cannot_be_downloaded_and_purge_removes_object(client, docs):
    alice = login(client, "t144-del@example.com")
    doc_id, owner = ready(client, docs, alice)
    row = docs.repo.session.get(UserDocument, doc_id)
    storage_key = row.storage_key
    assert client.delete(f"{BASE}/{doc_id}", headers=alice).status_code == 202
    response = client.get(f"{BASE}/{doc_id}/file", headers=alice)
    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_NOT_READY"

    class Purger:
        def purge(self, document_id):
            pass
    docs.purge(owner, doc_id, Purger())
    assert storage_key not in docs.storage.objects
    for url in (f"{BASE}/{doc_id}", f"{BASE}/{doc_id}/file"):
        assert client.get(url, headers=alice).status_code == 404


def test_tampered_object_is_not_served(client, docs):
    alice = login(client, "t144-tamper@example.com")
    doc_id, _ = ready(client, docs, alice)
    row = docs.repo.session.get(UserDocument, doc_id)
    docs.storage.objects[row.storage_key] = SAMPLE.replace(b"T144", b"EVIL")
    response = client.get(f"{BASE}/{doc_id}/file", headers=alice)
    assert response.status_code == 503 and b"EVIL" not in response.content


def test_no_public_url_surface(app):
    """공개 버킷·공개 URL 없음: 문서 경로는 모두 인증 필요, 응답 모델에 URL·storage_key 필드 없음."""
    schema = app.openapi()
    doc_paths = {p: ops for p, ops in schema["paths"].items() if p.startswith(BASE)}
    assert doc_paths, "documents router not mounted"
    for path, ops in doc_paths.items():
        assert "public" not in path and "share" not in path and "signed" not in path
        for op in ops.values():
            assert "401" in op["responses"], (path, op.get("operationId"))
    props = schema["components"]["schemas"]["Document"]["properties"]
    assert not {"url", "download_url", "storage_key", "checksum_sha256", "visibility"} & set(props)


def test_download_headers_prevent_caching_and_sniffing(client, docs):
    alice = login(client, "t144-headers@example.com")
    doc_id, _ = ready(client, docs, alice)
    response = client.get(f"{BASE}/{doc_id}/file", headers=alice)
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")


# --------------------------------------------------------------------------- 경로·설정
@pytest.mark.parametrize("bad", ["../etc/passwd", "..", "/abs/path", "a" * 31, "A" * 64, "0" * 65,
                                 "0" * 63 + "/", "0" * 32 + "\x00", "..%2f" + "0" * 32, "0" * 32 + "\\x"])
def test_storage_key_rejects_traversal_and_foreign_paths(bad):
    with pytest.raises(AppError) as err:
        DirectoryDocumentStorage._key(bad)
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_storage_root_must_be_absolute_and_private(tmp_path):
    with pytest.raises(ValueError):
        DirectoryDocumentStorage("relative/dir")
    if POSIX:
        loose = tmp_path / "loose"
        loose.mkdir(mode=0o755)
        os.chmod(loose, 0o755)
        with pytest.raises(ValueError):
            DirectoryDocumentStorage(str(loose))


def test_missing_storage_root_fails_closed(monkeypatch):
    monkeypatch.delenv("DOCUMENT_STORAGE_ROOT", raising=False)
    storage = get_document_storage()
    assert isinstance(storage, UnavailableDocumentStorage)
    for call in (lambda: storage.put("0" * 64, b"x"), lambda: storage.read("0" * 64)):
        with pytest.raises(AppError) as err:
            call()
        assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_env_contract_has_storage_root_and_no_document_key_material():
    """T111 계약: 저장 경로는 비밀이 아닌 설정. 문서 암호화 키 변수는 아직 없음(PROPOSED)."""
    names = {var.name: var for var in CONTRACT}
    assert names["DOCUMENT_STORAGE_ROOT"].secret is False
    assert not [n for n in names if n.startswith("DOCUMENT_") and ("KEY" in n or "KEK" in n)]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as fh:
        example = fh.read()
    assert "DOCUMENT_KEK" not in example


# --------------------------------------------------------------------------- 저장 시 암호화 사실 확인
@pytest.mark.skipif(not POSIX, reason="DirectoryDocumentStorage needs POSIX O_DIRECTORY/O_NOFOLLOW")
def test_finding_f1_directory_storage_is_plaintext_at_rest(tmp_path):
    """FINDING F-1: 현재 운영 경로의 저장 객체는 평문이다. 암호화가 연결되면 이 시험을 뒤집는다."""
    storage = DirectoryDocumentStorage(str(tmp_path / "files"))
    k = key()
    storage.put(k, SAMPLE)
    on_disk = (tmp_path / "files" / k).read_bytes()
    assert on_disk == SAMPLE
    assert (tmp_path / "files" / k).stat().st_mode & 0o777 == 0o600


def test_service_wiring_uses_plain_directory_storage():
    """라우터는 EncryptedDocumentStorage를 쓰지 않는다(미연결 사실 고정)."""
    import inspect
    from app.routers import documents as router_module
    source = inspect.getsource(router_module)
    assert "EncryptedDocumentStorage" not in source and "DirectoryDocumentStorage(root)" in source


# --------------------------------------------------------------------------- 봉투 암호화 계약
def encrypted(ring=None, inner=None):
    ring = ring or KeyRing()
    if ring.state("kek-2026-01") is None:
        ring.add_active("kek-2026-01", synthetic_kek())
    return EncryptedDocumentStorage(inner or MemoryStorage(), ring, SimulationCipher(), allow_simulation=True)


def test_simulation_cipher_rejected_without_explicit_flag():
    assert "AES-256-GCM" in APPROVED_ALGORITHMS
    with pytest.raises(ValueError):
        EncryptedDocumentStorage(MemoryStorage(), KeyRing(), SimulationCipher())


def test_ciphertext_at_rest_and_roundtrip():
    store = encrypted()
    k = key()
    store.put(k, SAMPLE)
    raw = store.inner.objects[k]
    assert is_envelope(raw) and SAMPLE not in raw and b"T144 synthetic" not in raw
    header, _ = decode_envelope(raw)
    assert header.kek_id == "kek-2026-01" and header.algorithm == SimulationCipher.algorithm
    assert store.read(k) == SAMPLE


def test_each_object_gets_fresh_dek_and_object_id():
    store = encrypted()
    a, b = key(), key()
    store.put(a, SAMPLE)
    store.put(b, SAMPLE)
    ha, body_a = decode_envelope(store.inner.objects[a])
    hb, body_b = decode_envelope(store.inner.objects[b])
    assert ha.object_id != hb.object_id and ha.wrapped_dek != hb.wrapped_dek and body_a != body_b


@pytest.mark.parametrize("where", ["body", "dek", "header_kek", "header_alg", "truncate"])
def test_tamper_fails_closed(where):
    store = encrypted()
    k = key()
    store.put(k, SAMPLE)
    raw = bytearray(store.inner.objects[k])
    if where == "body":
        raw[-40] ^= 1
    elif where == "dek":
        header, body = decode_envelope(bytes(raw))
        flipped = bytes([header.wrapped_dek[0] ^ 1]) + header.wrapped_dek[1:]
        raw = bytearray(encode_envelope(replace(header, wrapped_dek=flipped), body))
    elif where == "header_kek":
        raw = bytearray(bytes(raw).replace(b"kek-2026-01", b"kek-2026-02"))
    elif where == "header_alg":
        raw = bytearray(bytes(raw).replace(SimulationCipher.algorithm.encode(), b"AES-256-GCM"))
    else:
        raw = raw[:20]
    store.inner.objects[k] = bytes(raw)
    with pytest.raises(AppError) as err:
        store.read(k)
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_swapped_objects_are_caught_by_service_checksum(app):
    """객체 바꿔치기: 둘 다 정상 복호되지만 DB의 크기·SHA-256과 달라 503."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS career")
        conn.commit()
    UserDocument.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    store = encrypted()
    service = DocumentService(SqlDocumentRepository(session), store, ListCursor(b"d" * 32))
    owner = uuid4()
    one = service.upload(owner, "resume", "a.pdf", PDF, SAMPLE)
    two = service.upload(owner, "resume", "b.pdf", PDF, SAMPLE.replace(b"T144", b"OTHR"))
    for d in (one, two):
        service.verify(owner, d.document_id)
    assert service.download(owner, one.document_id)[1] == SAMPLE
    r1 = session.get(UserDocument, one.document_id)
    r2 = session.get(UserDocument, two.document_id)
    objs = store.inner.objects
    objs[r1.storage_key], objs[r2.storage_key] = objs[r2.storage_key], objs[r1.storage_key]
    with pytest.raises(AppError) as err:
        service.download(owner, one.document_id)
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    session.close()
    engine.dispose()


def test_legacy_plaintext_rejected_unless_migration_mode():
    inner = MemoryStorage()
    legacy = key()
    inner.put(legacy, SAMPLE)
    strict = encrypted(inner=inner)
    with pytest.raises(AppError):
        strict.read(legacy)
    lenient = EncryptedDocumentStorage(inner, strict.keyring, SimulationCipher(), allow_simulation=True,
                                       allow_legacy_plaintext=True)
    assert lenient.read(legacy) == SAMPLE
    new = key()
    lenient.migrate_plaintext(legacy, new)
    assert is_envelope(inner.objects[new]) and strict.read(new) == SAMPLE
    with pytest.raises(AppError):
        lenient.migrate_plaintext(new, key())


def test_key_rotation_simulation_end_to_end():
    """KEK v1 → v2 회전: 새 쓰기는 v2, 옛 객체는 decrypt_only로 읽힘, rewrap 후 v1 폐기, 폐기 키는 복구 불가."""
    ring = KeyRing()
    ring.add_active("kek-2026-01", synthetic_kek())
    store = encrypted(ring)
    old_keys = [key() for _ in range(3)]
    contents = {k: SAMPLE + k.encode() for k in old_keys}
    for k in old_keys:
        store.put(k, contents[k])

    ring.add_active("kek-2026-02", synthetic_kek())
    assert ring.state("kek-2026-01") is KeyState.DECRYPT_ONLY and ring.active_id == "kek-2026-02"
    fresh = key()
    store.put(fresh, SAMPLE)
    assert store.kek_of(fresh) == "kek-2026-02"
    assert all(store.read(k) == contents[k] for k in old_keys)

    # 참조가 남아 있으면 폐기 거부, active는 폐기 거부
    refs = lambda kek: sum(store.kek_of(k) == kek for k in list(store.inner.objects))
    with pytest.raises(ValueError):
        ring.retire("kek-2026-01", remaining_references=refs("kek-2026-01"))
    with pytest.raises(ValueError):
        ring.retire("kek-2026-02", remaining_references=0)

    # 하나는 rewrap하지 않고 남겨 둔 채 나머지 rewrap (copy-on-rewrap: 새 키 → 옛 키 삭제)
    straggler, mapping = old_keys[0], {}
    for k in old_keys[1:]:
        _, body_before = decode_envelope(store.inner.objects[k])
        new = key()
        store.rewrap_to(k, new)
        _, body_after = decode_envelope(store.inner.objects[new])
        assert body_after == body_before, "rewrap must not re-encrypt the body"
        assert store.kek_of(new) == "kek-2026-02" and store.read(new) == contents[k]
        store.delete(k)
        mapping[k] = new
    assert refs("kek-2026-01") == 1

    # 강제 폐기 시뮬레이션: 남은 객체는 fail-closed (crypto-shredding 확인)
    forced = KeyRing()
    forced.add_active("kek-2026-01", b"\x00" * 32)
    forced.add_active("kek-2026-02", b"\x01" * 32)
    forced.retire("kek-2026-01", remaining_references=0)
    with pytest.raises(KeyUnavailable):
        forced.material_for_unwrap("kek-2026-01")

    store.rewrap_to(straggler, mapping.setdefault(straggler, key()))
    store.delete(straggler)
    ring.retire("kek-2026-01", remaining_references=refs("kek-2026-01"))
    assert ring.state("kek-2026-01") is KeyState.RETIRED
    assert all(store.read(new) == contents[old] for old, new in mapping.items())
    with pytest.raises(ValueError):
        ring.add_active("kek-2026-01", synthetic_kek())  # id 재사용 금지


def test_retired_kek_makes_unrewrapped_objects_unreadable():
    ring = KeyRing()
    store = encrypted(ring)
    k = key()
    store.put(k, SAMPLE)
    ring.add_active("kek-2026-02", synthetic_kek())
    ring.retire("kek-2026-01", remaining_references=0)  # 운영자가 집계를 잘못 넣은 경우
    with pytest.raises(AppError) as err:
        store.read(k)
    assert err.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_no_active_kek_fails_closed_and_key_material_not_in_repr():
    ring = KeyRing()
    store = EncryptedDocumentStorage(MemoryStorage(), ring, SimulationCipher(), allow_simulation=True)
    with pytest.raises(AppError):
        store.put(key(), SAMPLE)
    material = synthetic_kek()
    ring.add_active("kek-x", material)
    assert material.hex() not in repr(ring) and repr(material) not in repr(ring)
    with pytest.raises(ValueError):
        ring.add_active("bad id/../", synthetic_kek())
    with pytest.raises(ValueError):
        ring.add_active("short", b"too-short")


def test_encrypted_storage_still_enforces_key_rules():
    store = encrypted()
    with pytest.raises(AppError):
        store.put("../escape", SAMPLE)


# --------------------------------------------------------------------------- 만료형 다운로드 토큰
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)


def signer(ttl=300):
    return DownloadTokenSigner(derive_key("t144-synthetic-secret-" + "x" * 32, PURPOSE), ttl_seconds=ttl)


def test_download_token_roundtrip_and_expiry():
    s, owner, doc = signer(), uuid4(), uuid4()
    token = s.issue(owner, doc, now=NOW)
    s.verify(token, owner, doc, now=NOW + timedelta(seconds=299))
    with pytest.raises(AppError) as err:
        s.verify(token, owner, doc, now=NOW + timedelta(seconds=300))
    assert err.value.code == ErrorCode.TOKEN_EXPIRED


@pytest.mark.parametrize("case", ["other_owner", "other_doc", "tampered", "other_key", "garbage", "padded"])
def test_download_token_rejections_look_like_not_found(case):
    s, owner, doc = signer(), uuid4(), uuid4()
    token = s.issue(owner, doc, now=NOW)
    target_owner, target_doc = owner, doc
    if case == "other_owner":
        target_owner = uuid4()
    elif case == "other_doc":
        target_doc = uuid4()
    elif case == "tampered":
        body, sig = token.split(".")
        token = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1] + "." + sig
    elif case == "other_key":
        token = DownloadTokenSigner(derive_key("another-synthetic-secret-" + "y" * 32, PURPOSE)).issue(
            owner, doc, now=NOW)
    elif case == "garbage":
        token = "not.a-token"
    else:
        token += "="
    with pytest.raises(AppError) as err:
        s.verify(token, target_owner, target_doc, now=NOW)
    assert err.value.code == ErrorCode.NOT_FOUND


def test_download_token_ttl_bounds_and_key_isolation():
    with pytest.raises(ValueError):
        signer(ttl=MAX_TTL_SECONDS + 1)
    with pytest.raises(ValueError):
        signer(ttl=0)
    with pytest.raises(ValueError):
        DownloadTokenSigner(b"short")
    secret = "t144-synthetic-secret-" + "x" * 32
    assert derive_key(secret, PURPOSE) != derive_key(secret, "t17-job-roles-cursor-v1")
    assert "t144" not in repr(signer())
