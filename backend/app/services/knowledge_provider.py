"""T56 검색·답변 생성 경계와 인용 검증기 (mock 범위).

- 문서 청크 본문은 T53(청킹·색인) 소관이다. `document_chunks`에는 본문이 없고(해시·색인 위치만),
  기본 `UnavailableChunkText`는 본문을 주지 않는다 → 실제 서버에서는 근거 없음(no_evidence).
- 검색기(T54 소관)는 `LexicalMockRetriever`: 질문과 청크의 단어 겹침 비율로 점수(0~1)를 매긴다.
- 답변 생성기(LLM 소관)는 `ExtractiveMockGenerator`: LLM 없이 근거 문장을 그대로 발췌한다.
  LLM 제공자·데이터 처리 계약 승인 전이라 **외부 호출 없음**. 모델 표시는 kind=rule.
- `verify_citations`: 생성기가 낸 인용이 이번 검색에서 **권한 확인된 청크인지** 다시 확인하고,
  근거가 하나도 남지 않으면 답변하지 않는다(FR-AI-003 수용 기준 1·2).
- 문서 본문은 **데이터**다. 지시문처럼 보이는 문장은 근거에서 빼고, 생성기는 어떤 경우에도 그 지시를
  따르지 않는다(수용 기준 3).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

MODEL_CODE = "knowledge_answer_mock"
MODEL_VERSION = "t56-mock-1"
MODEL_KIND = "rule"
MODEL_DESCRIPTION = "T56 extractive mock answer: quotes retrieved evidence only, no LLM or external call"

TOP_K = 5
MIN_SCORE = 0.2
MAX_CHUNKS_SCANNED = 500
MAX_CONTEXT_CHARS = 4000
MAX_ANSWER_SENTENCES = 2
MAX_ANSWER_CHARS = 600

_TOKEN = re.compile(r"[0-9A-Za-z+#.]+|[가-힣]+")  # 영문·숫자와 한글을 따로 끊는다 ("Python과" → "python", "과")
# 한글 낱말 끝의 흔한 조사·어미. 형태소 분석기가 아니라 mock 검색용 단순 규칙이다.
_JOSA = ("에게는", "에게서", "에서는", "으로는", "이라는", "에게", "에서", "으로", "부터", "까지", "처럼",
         "은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "로", "만")
_SENTENCE = re.compile(r"(?<=[.!?。])\s+|\n+")
_STOPWORDS = {"은", "는", "이", "가", "을", "를", "에", "의", "와", "과", "도", "무엇", "어떤", "가장",
              "있나요", "인가요", "무엇인가요", "알려줘", "알려주세요", "the", "a", "an", "is", "are", "what", "how"}
# 문서 속 지시문(프롬프트 인젝션) 후보. 완전한 탐지기가 아니라 근거에서 빼는 1차 방어선이다.
_INJECTION = re.compile(
    r"(ignore (all |the )?(previous|prior|above) (instructions|prompts?)|disregard .*instructions|"
    r"system\s*prompt|^\s*(system|assistant|user)\s*:|you are now|act as|jailbreak|"
    r"이전\s*(의\s*)?(지시|명령|지침)|위의?\s*(지시|명령)|지시(를|사항을)?\s*무시|시스템\s*프롬프트|"
    r"너는\s*이제|다른\s*사용자의?\s*(문서|정보)|비밀번호|토큰을?\s*(알려|출력))",
    re.IGNORECASE,
)


class ProviderError(Exception):
    """검색·생성 실패. 문서 본문이나 제공자 원문 응답을 담지 않는다."""


@dataclass(frozen=True)
class AccessibleChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: AccessibleChunk
    text: str
    score: float


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    cited_chunk_ids: tuple[UUID, ...]


class ChunkTextSource(Protocol):
    def read(self, chunk: AccessibleChunk) -> str | None: ...


class Retriever(Protocol):
    def search(self, question: str, chunks: Sequence[AccessibleChunk], source: ChunkTextSource,
               top_k: int) -> list[RetrievedChunk]: ...


class AnswerGenerator(Protocol):
    def generate(self, question: str, evidence: Sequence[RetrievedChunk]) -> GeneratedAnswer: ...


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(text.split()))


def _stem(word: str) -> str:
    if re.fullmatch(r"[가-힣]+", word):
        for josa in _JOSA:
            if word.endswith(josa) and len(word) - len(josa) >= 2:
                return word[: -len(josa)]
    return word


def tokens(text: str) -> set[str]:
    out = set()
    for m in _TOKEN.finditer(normalize(text)):
        word = m.group(0).lower().strip(".")
        if word in _STOPWORDS:
            continue
        word = _stem(word)
        if len(word) >= 2 and word not in _STOPWORDS:
            out.add(word)
    return out


def strip_instructions(text: str) -> tuple[str, bool]:
    """지시문처럼 보이는 문장을 뺀 본문과, 뺀 것이 있었는지."""
    kept, flagged = [], False
    for sentence in (s.strip() for s in _SENTENCE.split(text)):
        if not sentence:
            continue
        if _INJECTION.search(sentence):
            flagged = True
            continue
        kept.append(sentence)
    return " ".join(kept), flagged


class UnavailableChunkText:
    """T53 색인 연동 전 기본값: 본문을 제공하지 않는다."""

    def read(self, chunk: AccessibleChunk) -> str | None:
        return None


class LexicalMockRetriever:
    """권한 확인된 청크만 받아 단어 겹침으로 점수를 매긴다(결정적). 외부 호출 없음."""

    def search(self, question: str, chunks: Sequence[AccessibleChunk], source: ChunkTextSource,
               top_k: int = TOP_K) -> list[RetrievedChunk]:
        q = tokens(question)
        if not q:
            return []
        found = []
        for chunk in chunks[:MAX_CHUNKS_SCANNED]:
            raw = source.read(chunk)
            if not raw:
                continue
            text, _ = strip_instructions(raw)
            overlap = len(q & tokens(text))
            if overlap:
                found.append(RetrievedChunk(chunk, text, round(overlap / len(q), 5)))
        found.sort(key=lambda r: (-r.score, str(r.chunk.document_id), r.chunk.chunk_index))
        return found[:top_k]


class ExtractiveMockGenerator:
    """LLM 대신 근거 청크에서 질문 단어가 가장 많이 겹치는 문장을 발췌한다. 근거 밖 내용을 만들지 않는다."""

    def generate(self, question: str, evidence: Sequence[RetrievedChunk]) -> GeneratedAnswer:
        q = tokens(question)
        scored = []
        for order, item in enumerate(evidence):
            for sentence in (s.strip() for s in _SENTENCE.split(item.text)):
                hit = len(q & tokens(sentence))
                if sentence and hit:
                    scored.append((-hit, order, sentence, item.chunk.chunk_id))
        scored.sort()
        picked = scored[:MAX_ANSWER_SENTENCES]
        if not picked:
            return GeneratedAnswer("", ())
        answer = " ".join(s for _, _, s, _ in picked)[:MAX_ANSWER_CHARS]
        cited = tuple(dict.fromkeys(cid for *_, cid in picked))
        return GeneratedAnswer(answer, cited)


def fit_context(evidence: Sequence[RetrievedChunk], max_chars: int = MAX_CONTEXT_CHARS) -> list[RetrievedChunk]:
    """생성기에 넘길 근거를 글자 수 상한(비용·토큰 한도) 안으로 자른다. 순서 유지."""
    kept, used = [], 0
    for item in evidence:
        if used + len(item.text) > max_chars and kept:
            break
        kept.append(item)
        used += len(item.text)
    return kept


def verify_citations(generated: GeneratedAnswer, evidence: Sequence[RetrievedChunk],
                     allowed_chunk_ids: set[UUID]) -> list[RetrievedChunk]:
    """생성기가 인용한 청크 중 (1) 이번 검색 결과에 있고 (2) 권한 확인된 것만 남긴다. 순서는 검색 순위."""
    if not generated.answer.strip():
        return []
    cited = set(generated.cited_chunk_ids)
    return [e for e in evidence if e.chunk.chunk_id in cited and e.chunk.chunk_id in allowed_chunk_ids]
