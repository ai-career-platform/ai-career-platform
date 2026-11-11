"""T142 내 데이터 반출 요청·상태·1회용 다운로드 (T141 정책 PROPOSED — docs/privacy/t141_data_subject_requests.json).

- 반출(export) 요청만 새로 만든다. 삭제 요청은 T31(`/me/deletion-request`)을 그대로 쓰고, 목록에서 T141 상태
  이름으로 바꿔 보여 주기만 한다(중복 구현 없음).
- 재인증: 비밀번호를 다시 확인하면 10분짜리 재인증 토큰을 세션에 묶어 발급한다. 저장은 SHA-256 해시만.
- 다운로드: 완료된 요청에 대해 10분짜리 1회용 다운로드 토큰을 발급한다(해시만 저장). 한 번 내려받으면 요청은
  `expired`로 끝나고 묶음을 지운다. 완료 후 24시간이 지나도 `expired`.
- 묶음에는 T141 `never_export_columns`(비밀번호·토큰 해시, IP 해시, 저장 키 등)를 어떤 깊이에서도 넣지 않는다.
- 다른 사람 요청은 존재를 숨기고 404. 같은 유형의 열린 요청이 있으면 409 CONFLICT.
- 저장소는 메모리 구현만(migration 승인 전, 제안 DDL: database/proposed/T142_personal_data_requests.sql).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from collections.abc import Callable
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


class MemoryRequestRepository:
    """요청·재인증·다운로드 토큰 저장. 모든 변경은 한 잠금 안에서(동시 요청 → 하나만 성공)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.requests: dict[uuid.UUID, ExportRequest] = {}
        self.artifacts: dict[uuid.UUID, bytes] = {}
        self.reauth: dict[str, tuple[uuid.UUID, uuid.UUID, datetime]] = {}      # hash → (user, session, expires)
        self.downloads: dict[str, tuple[uuid.UUID, datetime]] = {}               # hash → (request, expires)
        self.audit: list[dict[str, Any]] = []


class PersonalDataRequestService:
    def __init__(self, repo: MemoryRequestRepository, source: PersonalDataSource, verify_password: PasswordVerifier,
                 deletion: DeletionSource, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 max_export_bytes: int = MAX_EXPORT_BYTES) -> None:
        self.repo, self.source, self.verify_password, self.deletion = repo, source, verify_password, deletion
        self.clock = clock
        self.max_export_bytes = max_export_bytes

    # ------------------------------------------------------------------ 감사
    def _audit(self, action: str, actor: str, user_id: uuid.UUID | None, **meta: Any) -> None:
        assert set(meta) <= AUDIT_KEYS, set(meta) - AUDIT_KEYS     # T83 §4: 허용 키만
        self.repo.audit.append({"action_code": action, "actor_type": actor, "actor_user_id": user_id,
                                "recorded_at": self.clock(),
                                "metadata": {k: str(v) for k, v in meta.items() if v is not None}})

    def _move(self, req: ExportRequest, to: str, actor: str, **changes: Any) -> ExportRequest:
        action = TRANSITIONS.get((req.status, to))
        if action is None:
            raise AppError(ErrorCode.CONFLICT, log_detail=f"transition {req.status}->{to} not allowed")
        new = replace(req, status=to, updated_at=self.clock(), **changes)
        self.repo.requests[req.request_id] = new
        self._audit(action, actor, req.user_id if actor == "user" else None, request_id=req.request_id,
                    request_type="export", **{"from": req.status, "to": to}, reason_code=changes.get("reason_code"))
        return new

    # ------------------------------------------------------------------ 재인증
    def reauthenticate(self, user_id: uuid.UUID, session_id: uuid.UUID, password: str) -> tuple[str, datetime]:
        if not self.verify_password(user_id, password):
            self._audit("privacy.dsr.reauth", "user", user_id, result="denied", reason_code="invalid_credentials")
            raise AppError(ErrorCode.INVALID_CREDENTIALS, log_detail="reauth password mismatch")
        token, expires = secrets.token_urlsafe(32), self.clock() + REAUTH_TTL
        with self.repo.lock:
            self.repo.reauth[_hash(token)] = (user_id, session_id, expires)
        self._audit("privacy.dsr.reauth", "user", user_id, result="success")
        return token, expires

    def require_reauth(self, user_id: uuid.UUID, session_id: uuid.UUID, token: str | None) -> None:
        grant = self.repo.reauth.get(_hash(token)) if token else None
        if grant is None or grant[0] != user_id or grant[1] != session_id or grant[2] <= self.clock():
            error = AppError(ErrorCode.FORBIDDEN, log_detail="recent reauthentication required")
            error.headers["X-Reauth-Required"] = "true"
            raise error

    # ------------------------------------------------------------------ 본인
    def _owned(self, user_id: uuid.UUID, request_id: uuid.UUID) -> ExportRequest:
        req = self.repo.requests.get(request_id)
        if req is None or req.user_id != user_id:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="export request missing or owned by another user")
        return req

    def create_export(self, user_id: uuid.UUID) -> ExportRequest:
        now = self.clock()
        with self.repo.lock:
            mine = [r for r in self.repo.requests.values() if r.user_id == user_id]
            if any(r.status in OPEN_STATES or r.status == "completed" for r in mine):
                raise AppError(ErrorCode.CONFLICT, log_detail="open export request exists")
            if sum(r.created_at > now - timedelta(days=30) for r in mine) >= REQUESTS_PER_30_DAYS:
                raise AppError(ErrorCode.RATE_LIMITED, log_detail="export requests per 30 days exceeded",
                               retry_after=86400)
            req = ExportRequest(uuid.uuid4(), user_id, "received", now, now)
            self.repo.requests[req.request_id] = req
        self._audit("privacy.export.request", "user", user_id, request_id=req.request_id, request_type="export",
                    to="received")
        return req

    def get_export(self, user_id: uuid.UUID, request_id: uuid.UUID) -> ExportRequest:
        return self._owned(user_id, request_id)

    def cancel_export(self, user_id: uuid.UUID, request_id: uuid.UUID) -> ExportRequest:
        with self.repo.lock:
            req = self._owned(user_id, request_id)
            return self._move(req, "cancelled", "user")

    def list_requests(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        items = [self.public_view(r) for r in self.repo.requests.values() if r.user_id == user_id]
        deletion = self.deletion(user_id)
        if deletion is not None:
            items.append({"request_id": str(deletion.request_id), "request_type": "erasure",
                          "status": DELETION_STATE[deletion.status], "created_at": deletion.requested_at.isoformat(),
                          "updated_at": (deletion.completed_at or deletion.requested_at).isoformat(),
                          "source": "T31"})
        return sorted(items, key=lambda i: i["created_at"], reverse=True)

    def issue_download(self, user_id: uuid.UUID, request_id: uuid.UUID) -> tuple[str, datetime]:
        with self.repo.lock:
            req = self._expire_if_due(self._owned(user_id, request_id))
            if req.status != "completed" or req.request_id not in self.repo.artifacts:
                raise AppError(ErrorCode.CONFLICT, log_detail=f"export not downloadable in {req.status}")
            token = secrets.token_urlsafe(32)
            expires = min(self.clock() + DOWNLOAD_LINK_TTL, req.expires_at)
            # 새 링크를 만들면 이전 링크는 무효(동시에 하나만).
            self.repo.downloads = {h: v for h, v in self.repo.downloads.items() if v[0] != request_id}
            self.repo.downloads[_hash(token)] = (request_id, expires)
            return token, expires

    def consume_download(self, user_id: uuid.UUID, token: str) -> bytes:
        """1회용: 성공하면 토큰·묶음을 지우고 요청을 expired로 끝낸다. 실패 사유는 모두 같은 404."""
        with self.repo.lock:
            entry = self.repo.downloads.pop(_hash(token), None)
            req = self.repo.requests.get(entry[0]) if entry else None
            if entry is None or req is None or req.user_id != user_id or entry[1] <= self.clock():
                self._audit("privacy.dsr.download", "user", user_id, result="denied")
                raise AppError(ErrorCode.NOT_FOUND, log_detail="download token invalid, used, expired or foreign")
            req = self._expire_if_due(req)
            data = self.repo.artifacts.pop(req.request_id, None)
            if req.status != "completed" or data is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="artifact gone")
            self._audit("privacy.dsr.download", "user", user_id, request_id=req.request_id, result="success")
            self._move(req, "expired", "system")
            return data

    # ------------------------------------------------------------------ 시스템(Worker)
    def process_next(self) -> ExportRequest | None:
        """received 하나를 잡아 묶음을 만든다. 잠금 안에서 상태를 바꿔 두 Worker가 같은 요청을 잡지 않는다."""
        with self.repo.lock:
            waiting = sorted((r for r in self.repo.requests.values() if r.status == "received"),
                             key=lambda r: r.created_at)
            if not waiting:
                return None
            req = self._move(waiting[0], "in_progress", "system", attempts=waiting[0].attempts + 1)
        try:
            data = self.source.load(req.user_id)
            if data is None:
                raise LookupError("user data missing")
            bundle = json.dumps({"format": "ai-career-export/v1", "generated_at": self.clock().isoformat(),
                                 "data": strip_never_export(data)}, ensure_ascii=False, default=str).encode()
        except Exception:  # noqa: BLE001 — 원인은 사유 코드로만 남긴다(개인정보 로그 금지)
            with self.repo.lock:
                return self._move(req, "failed", "system", reason_code="dependency_unavailable")
        with self.repo.lock:
            if len(bundle) > self.max_export_bytes:
                return self._move(req, "failed", "system", reason_code="export_too_large", size_bytes=len(bundle))
            now = self.clock()
            self.repo.artifacts[req.request_id] = bundle
            return self._move(req, "completed", "system", completed_at=now, expires_at=now + ARTIFACT_TTL,
                              size_bytes=len(bundle), reason_code=None)

    def retry_failed(self) -> int:
        """재시도 한도 안의 failed → received. export_too_large는 같은 결과라 다시 하지 않는다."""
        moved = 0
        with self.repo.lock:
            for req in list(self.repo.requests.values()):
                if (req.status == "failed" and req.attempts < MAX_ATTEMPTS
                        and req.reason_code != "export_too_large"):
                    self._move(req, "received", "system")
                    moved += 1
        return moved

    def _expire_if_due(self, req: ExportRequest) -> ExportRequest:
        if req.status == "completed" and req.expires_at is not None and req.expires_at <= self.clock():
            self.repo.artifacts.pop(req.request_id, None)
            self.repo.downloads = {h: v for h, v in self.repo.downloads.items() if v[0] != req.request_id}
            return self._move(req, "expired", "system")
        return req

    def expire_due(self) -> int:
        with self.repo.lock:
            before = sum(r.status == "expired" for r in self.repo.requests.values())
            for req in list(self.repo.requests.values()):
                self._expire_if_due(req)
            return sum(r.status == "expired" for r in self.repo.requests.values()) - before

    # ------------------------------------------------------------------ 표시
    @staticmethod
    def public_view(req: ExportRequest) -> dict[str, Any]:
        return {"request_id": str(req.request_id), "request_type": req.request_type, "status": req.status,
                "created_at": req.created_at.isoformat(), "updated_at": req.updated_at.isoformat(),
                "completed_at": req.completed_at.isoformat() if req.completed_at else None,
                "expires_at": req.expires_at.isoformat() if req.expires_at else None,
                "size_bytes": req.size_bytes, "reason_code": req.reason_code, "attempts": req.attempts,
                "source": "T142"}
