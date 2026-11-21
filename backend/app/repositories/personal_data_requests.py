"""T142 내 데이터 반출 DB 접근. 표: database/migrations/0006_personal_data_requests.sql (T141/T142).

- `SqlRequestRepository`: 서비스의 `RequestRepository` 프로토콜 구현. 값은 바인딩 변수로만 전달합니다.
  `transaction()` 이 커밋·롤백을 맡고, 다른 메서드는 커밋하지 않습니다.
- 반출 묶음(JSON)은 `career.data_export_artifacts`(bytea)에 둡니다. 최대 50 MiB·완료 후 최대 24시간이고,
  첫 다운로드 성공 때 토큰 소모와 같은 트랜잭션에서 지웁니다.
- `SqlPersonalDataSource`: 본인(user_id) 행만 읽어 T141 `data_categories` 대로 묶습니다.
- 감사는 `career.audit_events`(T83)에 action_code·resource 만 남깁니다(메타데이터 열 없음, 개인정보 원문 없음).
  거부 결과는 action_code 끝에 `.denied` 를 붙입니다.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.repositories.auth import SqlAuthRepository
from app.repositories.privacy import SqlPrivacyRepository
from app.services.personal_data_requests import DeletionStatus, ExportRequest

_COLUMNS = ("request_id, user_id, status, created_at, updated_at, attempts, reason_code, completed_at, expires_at, "
            "size_bytes, request_type, artifact_sha256")
_SELECT = f"SELECT {_COLUMNS} FROM career.data_subject_requests"


def _row(r) -> ExportRequest:
    m = dict(r._mapping)
    if m.get("artifact_sha256") is not None:
        m["artifact_sha256"] = m["artifact_sha256"].strip()
    return ExportRequest(**m)


class SqlRequestRepository:
    def __init__(self, session: Session) -> None:
        self.db = session
        self._depth = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._depth:
            yield
            return
        self._depth = 1
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self._depth = 0

    def lock_user(self, user_id: UUID) -> None:
        # 같은 사용자의 동시 접수를 직렬화(열린 요청 1건·30일 3건). 최종 방어선은 ux_data_subject_requests_open.
        self.db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:u AS text), 142))"), {"u": user_id})

    def get(self, request_id: UUID, *, for_update: bool = False) -> ExportRequest | None:
        r = self.db.execute(text(_SELECT + " WHERE request_id = :id AND request_type = 'export'"
                                 + (" FOR UPDATE" if for_update else "")), {"id": request_id}).first()
        return None if r is None else _row(r)

    def list_for_user(self, user_id: UUID) -> list[ExportRequest]:
        return [_row(r) for r in self.db.execute(text(
            _SELECT + " WHERE user_id = :u AND request_type = 'export' ORDER BY created_at DESC LIMIT 200"),
            {"u": user_id})]

    def insert(self, req: ExportRequest) -> bool:
        try:
            with self.db.begin_nested():
                self.db.execute(text(
                    "INSERT INTO career.data_subject_requests (request_id, user_id, request_type, channel, status, "
                    "attempts, created_at, updated_at) VALUES (:id, :u, :t, 'self_service', :s, :a, :c, :c)"),
                    {"id": req.request_id, "u": req.user_id, "t": req.request_type, "s": req.status,
                     "a": req.attempts, "c": req.created_at})
        except IntegrityError:                      # 동시 접수가 부분 UNIQUE 로 막힘
            return False
        return True

    def update(self, req: ExportRequest, expected_status: str) -> bool:
        r = self.db.execute(text(
            "UPDATE career.data_subject_requests SET status = :s, updated_at = :up, attempts = :a, reason_code = :rc, "
            "completed_at = :ca, expires_at = :ea, size_bytes = :sz, artifact_sha256 = :sha "
            "WHERE request_id = :id AND status = :expected RETURNING request_id"),
            {"s": req.status, "up": req.updated_at, "a": req.attempts, "rc": req.reason_code, "ca": req.completed_at,
             "ea": req.expires_at, "sz": req.size_bytes, "sha": req.artifact_sha256, "id": req.request_id,
             "expected": expected_status}).first()
        return r is not None

    def claim_next(self) -> ExportRequest | None:
        r = self.db.execute(text(
            _SELECT + " WHERE status = 'received' AND request_type = 'export' AND user_id IS NOT NULL "
            "ORDER BY created_at, request_id LIMIT 1 FOR UPDATE SKIP LOCKED")).first()
        return None if r is None else _row(r)

    def list_status(self, status: str, *, due_before: datetime | None = None) -> list[ExportRequest]:
        where, params = ["status = :s", "request_type = 'export'"], {"s": status}
        if due_before is not None:
            where.append("expires_at <= :due")
            params["due"] = due_before
        return [_row(r) for r in self.db.execute(text(
            _SELECT + " WHERE " + " AND ".join(where) + " ORDER BY created_at LIMIT 500 FOR UPDATE SKIP LOCKED"),
            params)]

    # ------------------------------------------------------------------ 묶음
    def put_artifact(self, req: ExportRequest, data: bytes) -> None:
        self.db.execute(text(
            "INSERT INTO career.data_export_artifacts (request_id, user_id, content, size_bytes, content_sha256, "
            "created_at, expires_at) VALUES (:id, :u, :content, :size, :sha, :c, :e)"),
            {"id": req.request_id, "u": req.user_id, "content": data, "size": len(data), "sha": req.artifact_sha256,
             "c": req.completed_at, "e": req.expires_at})

    def has_artifact(self, request_id: UUID) -> bool:
        return self.db.execute(text("SELECT 1 FROM career.data_export_artifacts WHERE request_id = :id"),
                               {"id": request_id}).first() is not None

    def take_artifact(self, request_id: UUID) -> bytes | None:
        r = self.db.execute(text("DELETE FROM career.data_export_artifacts WHERE request_id = :id RETURNING content"),
                            {"id": request_id}).first()
        return None if r is None else bytes(r[0])

    def drop_artifact(self, request_id: UUID) -> None:
        self.db.execute(text("DELETE FROM career.data_export_artifacts WHERE request_id = :id"), {"id": request_id})

    # ------------------------------------------------------------------ 토큰(해시만)
    def add_reauth(self, token_hash: str, user_id: UUID, session_id: UUID, created_at: datetime,
                   expires_at: datetime) -> None:
        self.db.execute(text(
            "INSERT INTO career.data_reauth_grants (token_hash, user_id, session_id, created_at, expires_at) "
            "VALUES (:h, :u, :sid, :c, :e)"), {"h": token_hash, "u": user_id, "sid": session_id, "c": created_at,
                                                "e": expires_at})

    def get_reauth(self, token_hash: str) -> tuple[UUID, UUID, datetime] | None:
        r = self.db.execute(text("SELECT user_id, session_id, expires_at FROM career.data_reauth_grants "
                                 "WHERE token_hash = :h"), {"h": token_hash}).first()
        return None if r is None else (r[0], r[1], r[2])

    def replace_download(self, request_id: UUID, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        self.db.execute(text("DELETE FROM career.data_export_downloads WHERE request_id = :id AND used_at IS NULL"),
                        {"id": request_id})
        self.db.execute(text(
            "INSERT INTO career.data_export_downloads (token_hash, request_id, created_at, expires_at) "
            "VALUES (:h, :id, :c, :e)"), {"h": token_hash, "id": request_id, "c": created_at, "e": expires_at})

    def consume_download(self, token_hash: str, now: datetime) -> tuple[UUID, datetime] | None:
        r = self.db.execute(text(
            "UPDATE career.data_export_downloads SET used_at = GREATEST(:now, created_at) "
            "WHERE token_hash = :h AND used_at IS NULL RETURNING request_id, expires_at"),
            {"h": token_hash, "now": now}).first()
        return None if r is None else (r[0], r[1])

    def drop_downloads(self, request_id: UUID) -> None:
        self.db.execute(text("DELETE FROM career.data_export_downloads WHERE request_id = :id"), {"id": request_id})

    def purge_expired_tokens(self, now: datetime) -> None:
        self.db.execute(text("DELETE FROM career.data_reauth_grants WHERE expires_at <= :now"), {"now": now})
        self.db.execute(text("DELETE FROM career.data_export_downloads WHERE expires_at <= :now OR used_at IS NOT NULL"),
                        {"now": now})

    # ------------------------------------------------------------------ 감사(T83)
    def add_audit(self, event: dict[str, Any]) -> None:
        meta = event.get("metadata", {})
        action = event["action_code"] + (".denied" if meta.get("result") == "denied" else "")
        resource_id = meta.get("request_id")
        self.db.execute(text(
            "INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, occurred_at) "
            "VALUES (:actor, :action, :rtype, :rid, :at)"),
            {"actor": event.get("actor_user_id"), "action": action,
             "rtype": "data_subject_request" if resource_id else "user",
             "rid": resource_id or event.get("actor_user_id"), "at": event["recorded_at"]})


# ---------------------------------------------------------------------- 원본(본인 데이터)
# (분류, 이름, SQL, 제외 열). 모든 쿼리는 :u(요청한 사용자) 로만 범위를 묶는다.
_LIMIT = " LIMIT 100000"
_SOURCES: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    ("account", "user", "SELECT * FROM career.users WHERE user_id = :u", frozenset({"email_canonical"})),
    ("account", "profile", "SELECT * FROM career.user_profiles WHERE user_id = :u", frozenset()),
    ("career", "experiences", "SELECT * FROM career.user_experiences WHERE user_id = :u ORDER BY start_date",
     frozenset()),
    ("career", "projects", "SELECT * FROM career.user_projects WHERE user_id = :u ORDER BY start_date", frozenset()),
    ("career", "project_skills", "SELECT ps.project_id, ps.skill_id, s.name AS skill_name, ps.created_at "
     "FROM career.user_project_skills ps JOIN career.user_projects p ON p.project_id = ps.project_id "
     "JOIN career.skills s ON s.skill_id = ps.skill_id WHERE p.user_id = :u", frozenset()),
    ("career", "skills", "SELECT us.skill_id, s.name AS skill_name, us.proficiency, us.created_at, us.updated_at "
     "FROM career.user_skills us JOIN career.skills s ON s.skill_id = us.skill_id WHERE us.user_id = :u", frozenset()),
    ("career", "target_roles", "SELECT tr.job_role_id, r.name AS job_role_name, tr.priority, tr.created_at, "
     "tr.updated_at FROM career.user_target_roles tr JOIN career.job_roles r ON r.job_role_id = tr.job_role_id "
     "WHERE tr.user_id = :u", frozenset()),
    ("documents", "documents", "SELECT * FROM career.user_documents WHERE owner_user_id = :u", frozenset()),
    ("documents", "document_analyses", "SELECT a.analysis_id, a.document_id, a.analysis_type, a.status, a.result, "
     "a.error_code, a.requested_at, a.completed_at FROM career.document_analyses a "
     "JOIN career.user_documents d ON d.document_id = a.document_id WHERE d.owner_user_id = :u", frozenset()),
    ("documents", "document_chunks", "SELECT c.chunk_id, c.document_id, c.chunk_index, c.created_at "
     "FROM career.document_chunks c JOIN career.user_documents d ON d.document_id = c.document_id "
     "WHERE d.owner_user_id = :u", frozenset()),
    ("consents", "consents", "SELECT * FROM career.user_consents WHERE user_id = :u ORDER BY recorded_at",
     frozenset()),
    ("activity", "bookmarks", "SELECT * FROM career.user_job_bookmarks WHERE user_id = :u", frozenset()),
    ("activity", "behavior_events", "SELECT * FROM career.behavior_events WHERE user_id = :u ORDER BY event_at",
     frozenset()),
    ("activity", "recommendation_feedback", "SELECT * FROM career.recommendation_feedback WHERE user_id = :u",
     frozenset()),
    ("activity", "job_applications", "SELECT * FROM career.job_applications WHERE user_id = :u", frozenset()),
    ("activity", "notification_preferences", "SELECT * FROM career.notification_preferences WHERE user_id = :u",
     frozenset()),
    ("activity", "notifications", "SELECT delivery_id, notification_type, channel, status, created_at, sent_at, "
     "read_at FROM career.notification_deliveries WHERE user_id = :u", frozenset()),
    ("derived", "skill_gap_assessments", "SELECT * FROM career.skill_gap_assessments WHERE user_id = :u",
     frozenset({"model_version_id"})),
    ("derived", "skill_gap_items", "SELECT i.* FROM career.skill_gap_items i JOIN career.skill_gap_assessments a "
     "ON a.assessment_id = i.assessment_id WHERE a.user_id = :u", frozenset()),
    ("derived", "recommendation_runs", "SELECT * FROM career.recommendation_runs WHERE user_id = :u",
     frozenset({"model_version_id"})),
    ("derived", "recommendation_items", "SELECT i.* FROM career.recommendation_items i "
     "JOIN career.recommendation_runs r ON r.recommendation_run_id = i.recommendation_run_id WHERE r.user_id = :u",
     frozenset()),
    ("derived", "match_evaluations", "SELECT * FROM career.match_evaluations WHERE user_id = :u",
     frozenset({"model_version_id"})),
    ("derived", "segment_assignments", "SELECT * FROM career.user_segment_assignments WHERE user_id = :u",
     frozenset()),
    ("ai_runs", "agent_runs", "SELECT agent_run_id, workflow_code, status, started_at, ended_at "
     "FROM career.agent_runs WHERE user_id = :u", frozenset()),
    ("ai_runs", "retrieval_runs", "SELECT retrieval_run_id, status, started_at, ended_at "
     "FROM career.retrieval_runs WHERE user_id = :u", frozenset()),
    ("audit", "audit_events", "SELECT action_code, resource_type, occurred_at FROM career.audit_events "
     "WHERE actor_user_id = :u ORDER BY occurred_at", frozenset()),
    ("deletion_requests", "deletion_requests", "SELECT * FROM career.account_deletion_requests WHERE user_id = :u",
     frozenset()),
)


class SqlPersonalDataSource:
    """본인 데이터만 읽는다. 사용자가 없으면 None. 결과는 서비스가 NEVER_EXPORT 를 한 번 더 걸러 묶는다."""

    def __init__(self, session: Session) -> None:
        self.db = session

    def load(self, user_id: UUID) -> dict[str, Any] | None:
        if user_id is None or self.db.execute(text("SELECT 1 FROM career.users WHERE user_id = :u"),
                                              {"u": user_id}).first() is None:
            return None
        out: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for category, name, query, excluded in _SOURCES:
            rows = [{k: v for k, v in r._mapping.items() if k not in excluded}
                    for r in self.db.execute(text(query + _LIMIT), {"u": user_id})]
            out.setdefault(category, {})[name] = rows
        return out


class SqlPasswordVerifier:
    """T15 local identity 비밀번호 확인. 활성 사용자만. identity 가 없어도 같은 시간(더미 해시)으로 거부한다."""

    def __init__(self, session: Session) -> None:
        self.auth = SqlAuthRepository(session)

    def __call__(self, user_id: UUID, password: str) -> bool:
        ident = self.auth.find_local_identity_by_user(user_id)
        usable = ident is not None and ident.status == "active"
        return verify_password(ident.password_hash if usable else None, password) and usable


class SqlDeletionSource:
    """T31 탈퇴 접수(진행 중) 조회."""

    def __init__(self, session: Session) -> None:
        self.privacy = SqlPrivacyRepository(session)

    def __call__(self, user_id: UUID) -> DeletionStatus | None:
        d = self.privacy.get_deletion(user_id)
        return None if d is None else DeletionStatus(d.request_id, d.status, d.requested_at, d.completed_at)
