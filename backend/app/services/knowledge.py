"""T56 근거 기반 커리어 Q&A 업무 규칙 (FR-AI-003, API_CONTRACT `POST /knowledge/answers`).

흐름: 권한 있는 청크 조회(SQL) → 검색(mock) → 문맥 상한 → 답변 생성(mock) → 인용 검증 → 기록.
- 근거가 하나도 확인되지 않으면 답변하지 않는다: status=no_evidence, answer=null (수용 기준 1).
- 다른 사용자의 비공개 문서는 조회 단계에서 빠지고, 인용 검증에서 한 번 더 막힌다 (수용 기준 2).
- 문서 속 지시문은 근거에서 빼고 따르지 않는다 (수용 기준 3).
- 질문 원문은 저장·로그하지 않고 sha256만 남긴다 (수용 기준 4).
- 생성기 시간 초과 → 504 DEPENDENCY_TIMEOUT, 그 밖의 실패 → 503 DEPENDENCY_UNAVAILABLE. 실행 기록은 failed.
"""

import hashlib
import logging
from collections.abc import Sequence
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.knowledge import KnowledgeRepository
from app.schemas.knowledge import Citation, KnowledgeAnswer
from app.services.knowledge_provider import (
    TOP_K,
    MIN_SCORE,
    AnswerGenerator,
    ChunkTextSource,
    Retriever,
    fit_context,
    normalize,
    strip_instructions,
    verify_citations,
)

logger = logging.getLogger("app.knowledge")

SCOPE_NOTE = "공용 자료와 내 문서만 검색했습니다."
MOCK_NOTE = "검증용 규칙 기반 답변입니다(LLM 미사용). 근거 문장을 그대로 발췌했습니다."
EXCLUDED_NOTE = "요청한 문서 중 일부는 검색 대상에서 제외됐습니다."
NO_EVIDENCE_NOTE = "관련 근거를 찾지 못했습니다."
INSTRUCTION_NOTE = "문서 안의 지시문은 따르지 않았습니다."
UNVERIFIED_NOTE = "확인되지 않은 인용이 있어 답변하지 않았습니다."


def query_hash(question: str) -> str:
    return hashlib.sha256(normalize(question).encode("utf-8")).hexdigest()


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository, retriever: Retriever, generator: AnswerGenerator,
                 text_source: ChunkTextSource):
        self.repository = repository
        self.retriever = retriever
        self.generator = generator
        self.text_source = text_source

    def answer(self, user_id: UUID, question: str, document_ids: Sequence[UUID] | None) -> KnowledgeAnswer:
        limitations = [SCOPE_NOTE, MOCK_NOTE]
        if document_ids is not None:
            allowed_docs = self.repository.accessible_document_ids(user_id, document_ids)
            if len(allowed_docs) != len(document_ids):
                # 어떤 문서가 빠졌는지는 알리지 않는다 (남의 문서 존재 여부 숨김)
                limitations.append(EXCLUDED_NOTE)
            document_ids = [d for d in document_ids if d in allowed_docs]

        run_id = self.repository.start_run(user_id, query_hash(question))
        try:
            chunks = self.repository.accessible_chunks(user_id, document_ids) if document_ids != [] else []
            allowed_ids = {c.chunk_id for c in chunks}
            if any(strip_instructions(self.text_source.read(c) or "")[1] for c in chunks[:TOP_K * 4]):
                limitations.append(INSTRUCTION_NOTE)
            retrieved = [r for r in self.retriever.search(question, chunks, self.text_source, TOP_K)
                         if r.score >= MIN_SCORE and r.chunk.chunk_id in allowed_ids]
            evidence = fit_context(retrieved)
            generated = self.generator.generate(question, evidence) if evidence else None
            verified = verify_citations(generated, evidence, allowed_ids) if generated else []
            if generated and len(verified) != len(set(generated.cited_chunk_ids)):
                # 검색 결과에 없거나 권한 없는 청크를 인용함 → 답변 전체를 버린다 (허위 인용 차단)
                logger.warning("knowledge answer rejected: unverified citation run=%s", run_id)
                limitations.append(UNVERIFIED_NOTE)
                verified = []
        except TimeoutError:
            self.repository.finish_run(run_id, "failed", [], with_model=False)
            raise AppError(ErrorCode.DEPENDENCY_TIMEOUT, log_detail="knowledge generation timeout") from None
        except AppError:
            self.repository.finish_run(run_id, "failed", [], with_model=False)
            raise
        except Exception as exc:  # noqa: BLE001 — 원인 클래스만 남기고 질문·문서 내용은 남기지 않는다
            logger.warning("knowledge answer failed run=%s error=%s", run_id, type(exc).__name__)
            self.repository.finish_run(run_id, "failed", [], with_model=False)
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

        if not verified or generated is None or not generated.answer.strip():
            self.repository.finish_run(run_id, "no_evidence", [], with_model=False)
            return KnowledgeAnswer(retrieval_run_id=run_id, status="no_evidence", answer=None, citations=[],
                                   limitations=limitations + [NO_EVIDENCE_NOTE])

        cited = [(e.chunk.chunk_id, rank, e.score) for rank, e in enumerate(verified, start=1)]
        self.repository.finish_run(run_id, "answered", cited, with_model=True)
        return KnowledgeAnswer(
            retrieval_run_id=run_id, status="answered", answer=generated.answer,
            citations=[Citation(rank=rank, document_id=e.chunk.document_id, document_title=e.chunk.document_title,
                                chunk_index=e.chunk.chunk_index, score=e.score)
                       for rank, e in enumerate(verified, start=1)],
            limitations=limitations,
        )
