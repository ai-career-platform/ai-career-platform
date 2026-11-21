"""T142 내 데이터 반출 요청·상태·1회용 다운로드 (T141 정책 PROPOSED — docs/privacy/t141_data_subject_requests.json).

- 반출(export) 요청만 새로 만든다. 삭제 요청은 T31(`/me/deletion-request`)을 그대로 쓰고, 목록에서 T141 상태
  이름으로 바꿔 보여 주기만 한다(중복 구현 없음).
- 재인증: 비밀번호를 다시 확인하면 10분짜리 재인증 토큰을 세션에 묶어 발급한다. 저장은 SHA-256 해시만.
- 다운로드: 완료된 요청에 대해 10분짜리 1회용 다운로드 토큰을 발급한다(해시만 저장). 한 번 내려받으면 요청은
  `expired`로 끝나고 묶음을 지운다. 완료 후 24시간이 지나도 `expired`.
- 묶음에는 T141 `never_export_columns`(비밀번호·토큰 해시, IP 해시, 저장 키 등)를 어떤 깊이에서도 넣지 않는다.
- 다른 사람 요청은 존재를 숨기고 404. 같은 유형의 열린 요청이 있으면 409 CONFLICT.
- 저장소는 `RequestRepository` 프로토콜. 운영은 `app.repositories.personal_data_requests.SqlRequestRepository`
  (migration 0006), 단위 시험은 아래 `MemoryRequestRepository`.
- 상태 변경은 모두 `repo.transaction()` 안에서 한다. 남겨야 하는 결과(토큰 소모·거부 감사·만료)는 트랜잭션을
  확정한 다음에 오류를 올린다(SQL 저장소는 예외가 나면 롤백하므로).
- 로그·감사에는 개인정보 원문을 남기지 않는다(감사 메타데이터는 AUDIT_KEYS 만).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.core.errors import AppError, ErrorCode

# T141 정책 값(시험에서 JSON과 일치 확인)
REAUTH_TTL = timedelta(minutes=10)
DOWNLOAD_LINK_TTL = timedelta(minutes=10)
ARTIFACT_TTL = timedelta(hours=24)
MAX_ATTEMPTS = 3
MAX_EXPORT_BYTES = 50 * 1024 * 1024
REQUESTS_PER_30_DAYS = 3
NEVER_EXPORT = frozenset({"password_hash", "refresh_token_hash", "token_hash", "client_ip_hash", "storage_key",
                          "row_hash"})
OPEN_STATES = frozenset({"pending_verification", "received", "in_progress", "failed"})
TERMINAL_STATES = frozenset({"rejected", "cancelled", "expired", "closed"})
# T141 transitions 중 반출 요청이 쓰는 것(from, to) → 감사 액션
TRANSITIONS = {
    ("received", "in_progress"): "privacy.dsr.start",
    ("received", "cancelled"): "privacy.dsr.cancel",
    ("in_progress", "completed"): "privacy.dsr.complete",
    ("in_progress", "failed"): "privacy.dsr.fail",
    ("failed", "received"): "privacy.dsr.retry",
    ("completed", "expired"): "privacy.dsr.expire",
}
# T31 탈퇴 요청 상태 → T141 상태 이름
DELETION_STATE = {"requested": "received", "cancelled": "cancelled", "completed": "closed"}
AUDIT_KEYS = frozenset({"request_id", "request_type", "from", "to", "reason_code", "result"})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def strip_never_export(value: Any) -> Any:
    """사전·목록 어느 깊이에서든 반출 금지 키를 뺀다."""
    if isinstance(value, dict):
        return {k: strip_never_export(v) for k, v in value.items() if k not in NEVER_EXPORT}
    if isinstance(value, list):
        return [strip_never_export(v) for v in value]
    return value


@dataclass(frozen=True)
class ExportRequest:
    request_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime
    attempts: int = 0
    reason_code: str | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    size_bytes: int | None = None
    request_type: str = "export"
    artifact_sha256: str | None = None


@dataclass(frozen=True)
class DeletionStatus:
    request_id: uuid.UUID
    status: str
    requested_at: datetime
    completed_at: datetime | None


class PersonalDataSource(Protocol):
    def load(self, user_id: uuid.UUID) -> dict[str, Any] | None: ...


class PasswordVerifier(Protocol):
    def __call__(self, user_id: uuid.UUID, password: str) -> bool: ...


class DeletionSource(Protocol):
    """T31 탈퇴 요청 조회(PrivacyService.get_deletion 과 같은 의미). 없으면 None."""

    def __call__(self, user_id: uuid.UUID) -> DeletionStatus | None: ...


class RequestRepository(Protocol):
    """요청·재인증·다운로드 토큰·묶음·감사 저장. 토큰은 해시만 받는다."""

    def transaction(self) -> AbstractContextManager[None]: ...
    def lock_user(self, user_id: uuid.UUID) -> None: ...
    def get(self, request_id: uuid.UUID, *, for_update: bool = False) -> ExportRequest | None: ...
    def list_for_user(self, user_id: uuid.UUID) -> list[ExportRequest]: ...
    def insert(self, req: ExportRequest) -> bool: ...
    def update(self, req: ExportRequest, expected_status: str) -> bool: ...
    def claim_next(self) -> ExportRequest | None: ...
    def list_status(self, status: str, *, due_before: datetime | None = None) -> list[ExportRequest]: ...
    def put_artifact(self, req: ExportRequest, data: bytes) -> None: ...
    def has_artifact(self, request_id: uuid.UUID) -> bool: ...
    def take_artifact(self, request_id: uuid.UUID) -> bytes | None: ...
    def drop_artifact(self, request_id: uuid.UUID) -> None: ...
    def add_reauth(self, token_hash: str, user_id: uuid.UUID, session_id: uuid.UUID, created_at: datetime,
                   expires_at: datetime) -> None: ...
    def get_reauth(self, token_hash: str) -> tuple[uuid.UUID, uuid.UUID, datetime] | None: ...
    def replace_download(self, request_id: uuid.UUID, token_hash: str, created_at: datetime,
                         expires_at: datetime) -> None: ...
    def consume_download(self, token_hash: str, now: datetime) -> tuple[uuid.UUID, datetime] | None: ...
    def drop_downloads(self, request_id: uuid.UUID) -> None: ...
    def purge_expired_tokens(self, now: datetime) -> None: ...
    def add_audit(self, event: dict[str, Any]) -> None: ...


class MemoryRequestRepository:
    """메모리 구현(단위 시험). 모든 변경은 한 잠금 안에서(동시 요청 → 하나만 성공). 롤백은 하지 않는다."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.requests: dict[uuid.UUID, ExportRequest] = {}
        self.artifacts: dict[uuid.UUID, bytes] = {}
        self.reauth: dict[str, tuple[uuid.UUID, uuid.UUID, datetime]] = {}      # hash → (user, session, expires)
        self.downloads: dict[str, tuple[uuid.UUID, datetime]] = {}               # hash → (request, expires)
        self.audit: list[dict[str, Any]] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.lock:
            yield

    def lock_user(self, user_id):
        pass                                       # transaction() 의 잠금이 이미 전체를 직렬화한다

    def get(self, request_id, *, for_update=False):
        return self.requests.get(request_id)

    def list_for_user(self, user_id):
        return [r for r in self.requests.values() if r.user_id == user_id]

    def insert(self, req):
        if any(r.user_id == req.user_id and r.request_type == req.request_type
               and (r.status in OPEN_STATES or r.status == "completed") for r in self.requests.values()):
            return False
        self.requests[req.request_id] = req
        return True

    def update(self, req, expected_status):
        current = self.requests.get(req.request_id)
        if current is None or current.status != expected_status:
            return False
        self.requests[req.request_id] = req
        return True

    def claim_next(self):
        waiting = sorted((r for r in self.requests.values() if r.status == "received"), key=lambda r: r.created_at)
        return waiting[0] if waiting else None

    def list_status(self, status, *, due_before=None):
        return [r for r in self.requests.values() if r.status == status
                and (due_before is None or (r.expires_at is not None and r.expires_at <= due_before))]

    def put_artifact(self, req, data):
        self.artifacts[req.request_id] = data

    def has_artifact(self, request_id):
        return request_id in self.artifacts

    def take_artifact(self, request_id):
        return self.artifacts.pop(request_id, None)

    def drop_artifact(self, request_id):
        self.artifacts.pop(request_id, None)

    def add_reauth(self, token_hash, user_id, session_id, created_at, expires_at):
        self.reauth[token_hash] = (user_id, session_id, expires_at)

    def get_reauth(self, token_hash):
        return self.reauth.get(token_hash)

    def replace_download(self, request_id, token_hash, created_at, expires_at):
        self.drop_downloads(request_id)
        self.downloads[token_hash] = (request_id, expires_at)

    def consume_download(self, token_hash, now):
        return self.downloads.pop(token_hash, None)

    def drop_downloads(self, request_id):
        for h in [h for h, v in self.downloads.items() if v[0] == request_id]:
            del self.downloads[h]

    def purge_expired_tokens(self, now):
        for h in [h for h, v in self.reauth.items() if v[2] <= now]:
            del self.reauth[h]
        for h in [h for h, v in self.downloads.items() if v[1] <= now]:
            del self.downloads[h]

    def add_audit(self, event):
        self.audit.append(event)


class PersonalDataRequestService:
    def __init__(self, repo: RequestRepository, source: PersonalDataSource, verify_password: PasswordVerifier,
                 deletion: DeletionSource, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 max_export_bytes: int = MAX_EXPORT_BYTES) -> None:
        self.repo, self.source, self.verify_password, self.deletion = repo, source, verify_password, deletion
        self.clock = clock
        self.max_export_bytes = max_export_bytes

    # ------------------------------------------------------------------ 감사
    def _audit(self, action: str, actor: str, user_id: uuid.UUID | None, **meta: Any) -> None:
        assert set(meta) <= AUDIT_KEYS, set(meta) - AUDIT_KEYS     # T83 §4: 허용 키만
        self.repo.add_audit({"action_code": action, "actor_type": actor, "actor_user_id": user_id,
                             "recorded_at": self.clock(),
                             "metadata": {k: str(v) for k, v in meta.items() if v is not None}})

    def _move(self, req: ExportRequest, to: str, actor: str, **changes: Any) -> ExportRequest:
        action = TRANSITIONS.get((req.status, to))
        if action is None:
            raise AppError(ErrorCode.CONFLICT, log_detail=f"transition {req.status}->{to} not allowed")
        new = replace(req, status=to, updated_at=self.clock(), **changes)
        if not self.repo.update(new, req.status):
            raise AppError(ErrorCode.CONFLICT, log_detail=f"concurrent change during {req.status}->{to}")
        self._audit(action, actor, req.user_id if actor == "user" else None, request_id=req.request_id,
                    request_type="export", **{"from": req.status, "to": to}, reason_code=changes.get("reason_code"))
        return new

    # ------------------------------------------------------------------ 재인증
    def reauthenticate(self, user_id: uuid.UUID, session_id: uuid.UUID, password: str) -> tuple[str, datetime]:
        ok = self.verify_password(user_id, password)
        token, now = secrets.token_urlsafe(32), self.clock()
        expires = now + REAUTH_TTL
        with self.repo.transaction():
            if ok:
                self.repo.add_reauth(_hash(token), user_id, session_id, now, expires)
                self._audit("privacy.dsr.reauth", "user", user_id, result="success")
            else:
                self._audit("privacy.dsr.reauth", "user", user_id, result="denied", reason_code="invalid_credentials")
        if not ok:
            raise AppError(ErrorCode.INVALID_CREDENTIALS, log_detail="reauth password mismatch")
        return token, expires

    def require_reauth(self, user_id: uuid.UUID, session_id: uuid.UUID, token: str | None) -> None:
        grant = self.repo.get_reauth(_hash(token)) if token else None
        if grant is None or grant[0] != user_id or grant[1] != session_id or grant[2] <= self.clock():
            error = AppError(ErrorCode.FORBIDDEN, log_detail="recent reauthentication required")
            error.headers["X-Reauth-Required"] = "true"
            raise error

    # ------------------------------------------------------------------ 본인
    def _owned(self, user_id: uuid.UUID, request_id: uuid.UUID, *, for_update: bool = False) -> ExportRequest:
        req = self.repo.get(request_id, for_update=for_update)
        if req is None or req.user_id != user_id:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="export request missing or owned by another user")
        return req

    def create_export(self, user_id: uuid.UUID) -> ExportRequest:
        now = self.clock()
        with self.repo.transaction():
            self.repo.lock_user(user_id)
            mine = self.repo.list_for_user(user_id)
            if any(r.status in OPEN_STATES or r.status == "completed" for r in mine):
                raise AppError(ErrorCode.CONFLICT, log_detail="open export request exists")
            if sum(r.created_at > now - timedelta(days=30) for r in mine) >= REQUESTS_PER_30_DAYS:
                raise AppError(ErrorCode.RATE_LIMITED, log_detail="export requests per 30 days exceeded",
                               retry_after=86400)
            req = ExportRequest(uuid.uuid4(), user_id, "received", now, now)
            if not self.repo.insert(req):
                raise AppError(ErrorCode.CONFLICT, log_detail="open export request exists (unique)")
            self._audit("privacy.export.request", "user", user_id, request_id=req.request_id, request_type="export",
                        to="received")
        return req

    def get_export(self, user_id: uuid.UUID, request_id: uuid.UUID) -> ExportRequest:
        return self._owned(user_id, request_id)

    def cancel_export(self, user_id: uuid.UUID, request_id: uuid.UUID) -> ExportRequest:
        with self.repo.transaction():
            req = self._owned(user_id, request_id, for_update=True)
            return self._move(req, "cancelled", "user")

    def list_requests(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        items = [self.public_view(r) for r in self.repo.list_for_user(user_id)]
        deletion = self.deletion(user_id)
        if deletion is not None:
            items.append({"request_id": str(deletion.request_id), "request_type": "erasure",
                          "status": DELETION_STATE[deletion.status], "created_at": deletion.requested_at.isoformat(),
                          "updated_at": (deletion.completed_at or deletion.requested_at).isoformat(),
                          "source": "T31"})
        return sorted(items, key=lambda i: i["created_at"], reverse=True)

    def issue_download(self, user_id: uuid.UUID, request_id: uuid.UUID) -> tuple[str, datetime]:
        blocked: str | None = None
        with self.repo.transaction():
            req = self._expire_if_due(self._owned(user_id, request_id, for_update=True))
            if req.status != "completed" or not self.repo.has_artifact(req.request_id):
                blocked = req.status                 # 만료 처리는 확정한 뒤 409
            else:
                token, now = secrets.token_urlsafe(32), self.clock()
                expires = min(now + DOWNLOAD_LINK_TTL, req.expires_at)
                # 새 링크를 만들면 이전 링크는 무효(동시에 하나만).
                self.repo.replace_download(request_id, _hash(token), now, expires)
        if blocked is not None:
            raise AppError(ErrorCode.CONFLICT, log_detail=f"export not downloadable in {blocked}")
        return token, expires

    def consume_download(self, user_id: uuid.UUID, token: str) -> bytes:
        """1회용: 성공하면 토큰·묶음을 지우고 요청을 expired로 끝낸다. 실패 사유는 모두 같은 404.

        타인이 쓴 토큰도 소모된다(유출 시 피해 최소화). 소모·거부 감사는 확정한 뒤 404를 올린다.
        """
        data: bytes | None = None
        with self.repo.transaction():
            now = self.clock()
            entry = self.repo.consume_download(_hash(token), now)
            req = self.repo.get(entry[0], for_update=True) if entry else None
            if entry is None or req is None or req.user_id != user_id or entry[1] <= now:
                self._audit("privacy.dsr.download", "user", user_id, result="denied")
            else:
                req = self._expire_if_due(req)
                data = self.repo.take_artifact(req.request_id) if req.status == "completed" else None
                if data is not None:
                    self._audit("privacy.dsr.download", "user", user_id, request_id=req.request_id, result="success")
                    self.repo.drop_downloads(req.request_id)
                    self._move(req, "expired", "system")
        if data is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="download token invalid, used, expired, foreign or gone")
        return data

    # ------------------------------------------------------------------ 시스템(Worker)
    def process_next(self) -> ExportRequest | None:
        """received 하나를 잡아 묶음을 만든다. 잡기는 잠금(SQL: FOR UPDATE SKIP LOCKED) 안에서 상태를 바꿔
        두 Worker가 같은 요청을 잡지 않는다. 원본 읽기는 트랜잭션 밖에서 한다."""
        with self.repo.transaction():
            head = self.repo.claim_next()
            if head is None:
                return None
            req = self._move(head, "in_progress", "system", attempts=head.attempts + 1)
        try:
            data = self.source.load(req.user_id)
            if data is None:
                raise LookupError("user data missing")
            bundle = json.dumps({"format": "ai-career-export/v1", "generated_at": self.clock().isoformat(),
                                 "data": strip_never_export(data)}, ensure_ascii=False, default=str).encode()
        except Exception:  # noqa: BLE001 — 원인은 사유 코드로만 남긴다(개인정보 로그 금지)
            with self.repo.transaction():
                return self._move(req, "failed", "system", reason_code="dependency_unavailable")
        with self.repo.transaction():
            current = self.repo.get(req.request_id, for_update=True)
            if current is None or current.status != "in_progress":
                return current
            if current.user_id is None:            # 처리 중 탈퇴(SET NULL): 묶음을 만들지 않는다
                return self._move(current, "failed", "system", reason_code="internal_error")
            if len(bundle) > self.max_export_bytes:
                return self._move(current, "failed", "system", reason_code="export_too_large",
                                  size_bytes=len(bundle))
            now = self.clock()
            done = self._move(current, "completed", "system", completed_at=now, expires_at=now + ARTIFACT_TTL,
                              size_bytes=len(bundle), reason_code=None,
                              artifact_sha256=hashlib.sha256(bundle).hexdigest())
            self.repo.put_artifact(done, bundle)
            return done

    def retry_failed(self) -> int:
        """재시도 한도 안의 failed → received. export_too_large는 같은 결과라 다시 하지 않는다."""
        moved = 0
        with self.repo.transaction():
            for req in self.repo.list_status("failed"):
                if req.attempts < MAX_ATTEMPTS and req.reason_code != "export_too_large" and req.user_id is not None:
                    self._move(req, "received", "system")
                    moved += 1
        return moved

    def _expire_if_due(self, req: ExportRequest) -> ExportRequest:
        if req.status == "completed" and req.expires_at is not None and req.expires_at <= self.clock():
            self.repo.drop_artifact(req.request_id)
            self.repo.drop_downloads(req.request_id)
            return self._move(req, "expired", "system")
        return req

    def expire_due(self) -> int:
        """완료 후 24시간이 지난 요청을 expired로 끝내고 묶음을 지운다. 지난 재인증·다운로드 토큰도 정리한다."""
        with self.repo.transaction():
            now = self.clock()
            expired = sum(self._expire_if_due(r).status == "expired"
                          for r in self.repo.list_status("completed", due_before=now))
            self.repo.purge_expired_tokens(now)
        return expired

    def run_once(self, limit: int = 20) -> dict[str, int]:
        """Worker 1회분: 재시도 → 처리(최대 limit) → 만료. 개수만 돌려준다(식별자·내용 없음)."""
        retried = self.retry_failed()
        processed = 0
        while processed < limit and self.process_next() is not None:
            processed += 1
        return {"retried": retried, "processed": processed, "expired": self.expire_due()}

    # ------------------------------------------------------------------ 표시
    @staticmethod
    def public_view(req: ExportRequest) -> dict[str, Any]:
        return {"request_id": str(req.request_id), "request_type": req.request_type, "status": req.status,
                "created_at": req.created_at.isoformat(), "updated_at": req.updated_at.isoformat(),
                "completed_at": req.completed_at.isoformat() if req.completed_at else None,
                "expires_at": req.expires_at.isoformat() if req.expires_at else None,
                "size_bytes": req.size_bytes, "reason_code": req.reason_code, "attempts": req.attempts,
                "source": "T142"}
