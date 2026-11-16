"""T56 persistence — existing 0001 tables only (user_documents, document_chunks, retrieval_runs,
retrieval_citations, model_versions). No DDL, Migration or Seed.

권한은 SQL에서 먼저 거른다: 내 문서 또는 공용(shared) 문서이면서 status='ready'인 문서의 청크만 조회한다.
질문 원문은 저장하지 않고 sha256 해시만 저장한다(FR-AI-003 수용 기준 4).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import DateTime, Integer, Numeric, String, Uuid, column, or_, select, table, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.recommendation_runs import model_versions
from app.services.knowledge_provider import (
    MAX_CHUNKS_SCANNED,
    MODEL_CODE,
    MODEL_DESCRIPTION,
    MODEL_KIND,
    MODEL_VERSION,
    AccessibleChunk,
)

SCHEMA = "career"
documents = table("user_documents", column("document_id", Uuid), column("owner_user_id", Uuid),
                  column("original_filename", String), column("visibility", String), column("status", String),
                  column("created_at", DateTime(timezone=True)), schema=SCHEMA)
chunks = table("document_chunks", column("chunk_id", Uuid), column("document_id", Uuid),
               column("chunk_index", Integer), schema=SCHEMA)
runs = table("retrieval_runs", column("retrieval_run_id", Uuid), column("user_id", Uuid),
             column("model_version_id", Uuid), column("query_hash", String), column("status", String),
             column("started_at", DateTime(timezone=True)), column("ended_at", DateTime(timezone=True)),
             schema=SCHEMA)
citations = table("retrieval_citations", column("retrieval_run_id", Uuid), column("chunk_id", Uuid),
                  column("rank", Integer), column("score", Numeric), schema=SCHEMA)


class KnowledgeRepository(Protocol):
    def accessible_chunks(self, user_id: UUID, document_ids: Sequence[UUID] | None) -> list[AccessibleChunk]: ...
    def accessible_document_ids(self, user_id: UUID, document_ids: Sequence[UUID]) -> set[UUID]: ...
    def start_run(self, user_id: UUID, query_hash: str) -> UUID: ...
    def finish_run(self, run_id: UUID, status: str, cited: Sequence[tuple[UUID, int, float | None]],
                   with_model: bool) -> None: ...


class SqlKnowledgeRepository:
    def __init__(self, session: Session):
        self.session = session

    def _fail(self, exc: Exception) -> AppError:
        self.session.rollback()
        return AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__)

    @staticmethod
    def _allowed(user_id: UUID):
        return (or_(documents.c.owner_user_id == user_id, documents.c.visibility == "shared"),
                documents.c.status == "ready")

    def accessible_document_ids(self, user_id: UUID, document_ids: Sequence[UUID]) -> set[UUID]:
        try:
            rows = self.session.execute(select(documents.c.document_id).where(
                documents.c.document_id.in_(list(document_ids)), *self._allowed(user_id)))
            return {r.document_id for r in rows}
        except SQLAlchemyError as exc:
            raise self._fail(exc) from None

    def accessible_chunks(self, user_id: UUID, document_ids: Sequence[UUID] | None) -> list[AccessibleChunk]:
        query = (select(chunks.c.chunk_id, chunks.c.document_id, chunks.c.chunk_index,
                        documents.c.original_filename)
                 .join(documents, documents.c.document_id == chunks.c.document_id)
                 .where(*self._allowed(user_id))
                 .order_by(documents.c.created_at.desc(), documents.c.document_id, chunks.c.chunk_index)
                 .limit(MAX_CHUNKS_SCANNED))
        if document_ids is not None:
            query = query.where(chunks.c.document_id.in_(list(document_ids)))
        try:
            return [AccessibleChunk(r.chunk_id, r.document_id, r.original_filename, r.chunk_index)
                    for r in self.session.execute(query)]
        except SQLAlchemyError as exc:
            raise self._fail(exc) from None

    def _model_version_id(self) -> UUID:
        existing = self.session.scalar(select(model_versions.c.model_version_id).where(
            model_versions.c.model_code == MODEL_CODE, model_versions.c.version == MODEL_VERSION).limit(1))
        if existing:
            return existing
        return self.session.execute(pg_insert(model_versions).values(
            model_code=MODEL_CODE, version=MODEL_VERSION, kind=MODEL_KIND, description=MODEL_DESCRIPTION,
        ).returning(model_versions.c.model_version_id)).scalar_one()

    def start_run(self, user_id: UUID, query_hash: str) -> UUID:
        """실행 기록을 running으로 먼저 남기고 커밋한다(실패해도 시도 흔적이 남도록)."""
        try:
            run_id = self.session.execute(pg_insert(runs).values(
                user_id=user_id, query_hash=query_hash, status="running", started_at=datetime.now(UTC),
            ).returning(runs.c.retrieval_run_id)).scalar_one()
            self.session.commit()
            return run_id
        except SQLAlchemyError as exc:
            raise self._fail(exc) from None

    def finish_run(self, run_id: UUID, status: str, cited: Sequence[tuple[UUID, int, float | None]],
                   with_model: bool) -> None:
        try:
            model_id = self._model_version_id() if with_model else None
            self.session.execute(update(runs).where(runs.c.retrieval_run_id == run_id).values(
                status=status, model_version_id=model_id, ended_at=datetime.now(UTC)))
            if cited:
                self.session.execute(pg_insert(citations).values([
                    {"retrieval_run_id": run_id, "chunk_id": cid, "rank": rank, "score": score}
                    for cid, rank, score in cited]))
            self.session.commit()
        except SQLAlchemyError as exc:
            raise self._fail(exc) from None
