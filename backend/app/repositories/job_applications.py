"""T102 개인 지원 기록 DB 접근. 표: database/migrations/0004_job_applications.sql (T101).

모든 쿼리는 user_id 로 범위를 묶습니다(본인 기록만). 값은 바인딩 변수로만 전달합니다.
각 쓰기 메서드는 스스로 커밋합니다.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.job_applications import ApplicationRow, NewApplication

_SELECT = """
SELECT a.application_id, a.user_id, a.job_posting_id, a.posting_title, a.company_name,
       p.status AS posting_status, p.expires_at AS posting_expires_at, a.stage, a.applied_on, a.next_step_on, a.memo,
       a.version, a.created_at, a.updated_at, a.stage_changed_at
FROM career.job_applications a
LEFT JOIN career.job_postings p ON p.job_posting_id = a.job_posting_id
"""


def _row(r) -> ApplicationRow:
    return ApplicationRow(**r._mapping)


class SqlJobApplicationRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def list(self, user_id: UUID, stages: tuple[str, ...], after: tuple[datetime, UUID] | None,
             limit: int) -> list[ApplicationRow]:
        where, params = ["a.user_id = :u"], {"u": user_id, "limit": limit}
        if stages:
            where.append("a.stage IN :stages")
            params["stages"] = list(stages)
        if after is not None:
            where.append("(a.updated_at, a.application_id) < (:after_at, :after_id)")
            params.update(after_at=after[0], after_id=after[1])
        stmt = text(_SELECT + " WHERE " + " AND ".join(where)
                    + " ORDER BY a.updated_at DESC, a.application_id DESC LIMIT :limit")
        if stages:
            stmt = stmt.bindparams(bindparam("stages", expanding=True))
        return [_row(r) for r in self.db.execute(stmt, params)]

    def get(self, user_id: UUID, application_id: UUID) -> ApplicationRow | None:
        r = self.db.execute(text(_SELECT + " WHERE a.user_id = :u AND a.application_id = :id"),
                            {"u": user_id, "id": application_id}).first()
        return None if r is None else _row(r)

    def create(self, new: NewApplication, max_per_user: int) -> ApplicationRow | str:
        db = self.db
        try:
            posting = db.execute(text(
                "SELECT p.title, c.name FROM career.job_postings p JOIN career.companies c ON c.company_id = p.company_id "
                "WHERE p.job_posting_id = :p AND p.status IN ('published', 'closed')"), {"p": new.job_posting_id}).first()
            if posting is None:
                db.rollback()
                return "posting_not_found"
            # 같은 사용자의 동시 추가를 직렬화해 상한(500)을 지킴
            db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:u AS text), 102))"), {"u": new.user_id})
            if db.execute(text("SELECT 1 FROM career.job_applications WHERE user_id = :u AND job_posting_id = :p"),
                          {"u": new.user_id, "p": new.job_posting_id}).first():
                db.rollback()
                return "duplicate"
            count = db.execute(text("SELECT count(*) FROM career.job_applications WHERE user_id = :u"),
                               {"u": new.user_id}).scalar_one()
            if count >= max_per_user:
                db.rollback()
                return "limit"
            new_id = db.execute(text(
                "INSERT INTO career.job_applications (user_id, job_posting_id, posting_title, company_name, stage, "
                "applied_on, next_step_on, memo, created_at, updated_at, stage_changed_at) "
                "VALUES (:u, :p, :title, :company, :stage, :applied_on, :next_step_on, :memo, :now, :now, :now) "
                "RETURNING application_id"),
                {"u": new.user_id, "p": new.job_posting_id, "title": posting[0], "company": posting[1],
                 "stage": new.stage, "applied_on": new.applied_on, "next_step_on": new.next_step_on, "memo": new.memo,
                 "now": new.now}).scalar_one()
            db.commit()
        except IntegrityError:            # 동시 요청이 UNIQUE 로 막힘
            db.rollback()
            return "duplicate"
        return self.get(new.user_id, new_id)

    def update(self, user_id: UUID, application_id: UUID, version: int, values: dict) -> ApplicationRow | None:
        updated = self.db.execute(text(
            "UPDATE career.job_applications SET stage = :stage, applied_on = :applied_on, next_step_on = :next_step_on, "
            "memo = :memo, updated_at = :updated_at, stage_changed_at = :stage_changed_at, version = version + 1 "
            "WHERE user_id = :u AND application_id = :id AND version = :v RETURNING application_id"),
            {**values, "u": user_id, "id": application_id, "v": version}).first()
        self.db.commit()
        return None if updated is None else self.get(user_id, application_id)

    def delete(self, user_id: UUID, application_id: UUID) -> bool:
        deleted = self.db.execute(text(
            "DELETE FROM career.job_applications WHERE user_id = :u AND application_id = :id RETURNING application_id"),
            {"u": user_id, "id": application_id}).first()
        self.db.commit()
        return deleted is not None
