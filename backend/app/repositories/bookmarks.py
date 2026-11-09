from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid, case, column, delete, literal, select, table, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.repositories.job_postings import PostingRow

S = "career"
bookmarks = table("user_job_bookmarks", column("user_id", Uuid), column("job_posting_id", Uuid),
    column("created_at", DateTime(timezone=True)), schema=S)
postings = table("job_postings", column("job_posting_id", Uuid), column("company_id", Uuid),
    column("job_role_id", Uuid), column("title", String), column("status", String), column("employment_type", String),
    column("location_text", String), column("published_at", DateTime(timezone=True)),
    column("expires_at", DateTime(timezone=True)), schema=S)
companies = table("companies", column("company_id", Uuid), column("name", String), schema=S)
roles = table("job_roles", column("job_role_id", Uuid), column("code", String), column("name", String), schema=S)

@dataclass(frozen=True)
class BookmarkRow:
    posting: PostingRow
    created_at: datetime

class BookmarkRepository(Protocol):
    def list(self, user_id: UUID, after: tuple[datetime, UUID] | None, limit: int, now: datetime) -> list[BookmarkRow]: ...
    def add(self, user_id: UUID, posting_id: UUID) -> bool: ...
    def remove(self, user_id: UUID, posting_id: UUID) -> None: ...

class SqlBookmarkRepository:
    def __init__(self, db: Session): self.db = db
    def list(self, user_id, after, limit, now):
        p, c, r, b = postings.c, companies.c, roles.c, bookmarks.c
        status = case((p.status == "published", case((p.expires_at <= now, literal("closed")), else_=literal("published"))), else_=p.status)
        stmt = select(p.job_posting_id, p.title, status.label("display_status"), c.company_id,
            c.name.label("company_name"), r.job_role_id, r.code.label("job_role_code"), r.name.label("job_role_name"),
            p.employment_type, p.location_text, p.published_at, p.expires_at, b.created_at).select_from(bookmarks)
        stmt = stmt.join(postings, p.job_posting_id == b.job_posting_id).join(companies, c.company_id == p.company_id)
        stmt = stmt.outerjoin(roles, r.job_role_id == p.job_role_id).where(b.user_id == user_id)
        if after: stmt = stmt.where(tuple_(b.created_at, b.job_posting_id) < tuple_(after[0], after[1]))
        rows = self.db.execute(stmt.order_by(b.created_at.desc(), b.job_posting_id.desc()).limit(limit)).all()
        return [BookmarkRow(PostingRow(job_posting_id=x.job_posting_id, title=x.title, status=x.display_status,
            company_id=x.company_id, company_name=x.company_name, job_role_id=x.job_role_id,
            job_role_code=x.job_role_code, job_role_name=x.job_role_name, employment_type=x.employment_type,
            location_text=x.location_text, published_at=x.published_at, expires_at=x.expires_at), x.created_at) for x in rows]
    def add(self, user_id, posting_id):
        exists = self.db.scalar(select(postings.c.job_posting_id).where(postings.c.job_posting_id == posting_id,
            postings.c.status.in_(("published", "closed"))))
        if exists is None: return False
        self.db.execute(insert(bookmarks).values(user_id=user_id, job_posting_id=posting_id).on_conflict_do_nothing())
        self.db.commit(); return True
    def remove(self, user_id, posting_id):
        self.db.execute(delete(bookmarks).where(bookmarks.c.user_id == user_id, bookmarks.c.job_posting_id == posting_id))
        self.db.commit()
