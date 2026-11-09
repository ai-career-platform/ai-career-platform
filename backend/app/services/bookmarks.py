from datetime import UTC, datetime
from uuid import UUID
from app.core.errors import AppError, ErrorCode
from app.repositories.bookmarks import BookmarkRepository
from app.schemas.job_postings import JobPostingPage, JobPostingSummary
from app.services.job_postings import ListCursor, _summary

class BookmarkService:
    def __init__(self, repo: BookmarkRepository, cursor: ListCursor, clock=lambda: datetime.now(UTC)):
        self.repo, self.cursor, self.clock = repo, cursor, clock
    def list(self, user_id: UUID, limit: int, cursor: str | None):
        after = None
        if cursor is not None:
            item_id, raw = self.cursor.decode(cursor, "bookmarks", {})
            try: after = (datetime.fromisoformat(raw), item_id) if raw else None
            except ValueError: raise AppError(ErrorCode.INVALID_CURSOR) from None
        rows = self.repo.list(user_id, after, limit + 1, self.clock()); page = rows[:limit]
        next_cursor = self.cursor.encode("bookmarks", {}, page[-1].posting.job_posting_id,
            page[-1].created_at.isoformat()) if len(rows) > limit else None
        return JobPostingPage(items=[JobPostingSummary(**_summary(x.posting)) for x in page], next_cursor=next_cursor)
    def add(self, user_id, posting_id):
        if not self.repo.add(user_id, posting_id): raise AppError(ErrorCode.NOT_FOUND)
    def remove(self, user_id, posting_id): self.repo.remove(user_id, posting_id)
