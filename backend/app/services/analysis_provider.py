"""T51 document analysis provider boundary.

Only the deterministic MockAnalysisProvider exists. No real LLM, cloud API or
network provider is implemented or allowed in this scope (PM approval required).

Security rule: document bytes are opaque *data*. A provider must never treat
document text as instructions, tool calls or configuration. The mock does not
parse the content at all, so instructions embedded in a document cannot change
its output.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AnalysisInput:
    analysis_type: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class SkillCandidate:
    code: str
    suggested_proficiency: int
    evidence: str


@dataclass(frozen=True)
class ExperienceCandidate:
    organization: str
    title: str


@dataclass(frozen=True)
class ProviderOutput:
    summary: str | None = None
    skills: tuple[SkillCandidate, ...] | None = None
    experiences: tuple[ExperienceCandidate, ...] | None = None


class ProviderError(Exception):
    """Provider failed. Never carries document text or provider raw output."""


class AnalysisProvider(Protocol):
    def analyze(self, request: AnalysisInput) -> ProviderOutput: ...


# Synthetic fixtures only. Not derived from any real resume.
MOCK_SKILLS = (
    SkillCandidate("PYTHON", 3, "합성 fixture: 데이터 처리 스크립트 작성 경험이 언급된 것으로 가정한 예시 근거입니다."),
    SkillCandidate("SQL", 2, "합성 fixture: 조회 쿼리 작성 경험이 언급된 것으로 가정한 예시 근거입니다."),
)
MOCK_SUMMARY = ("합성 fixture 요약: 백엔드 개발 학습 경험과 데이터 처리 실습 경험을 가진 지원자로 가정한 "
                "예시 문장입니다. 실제 문서 내용을 분석한 결과가 아닙니다.")
MOCK_EXPERIENCES = (ExperienceCandidate("합성 예시 회사", "백엔드 개발 인턴"),)


class MockAnalysisProvider:
    """Deterministic fixture output keyed only by analysis_type. No I/O, no network."""

    def analyze(self, request: AnalysisInput) -> ProviderOutput:
        if request.analysis_type == "skill_extraction":
            return ProviderOutput(skills=MOCK_SKILLS)
        if request.analysis_type == "summary":
            return ProviderOutput(summary=MOCK_SUMMARY, experiences=MOCK_EXPERIENCES)
        raise ProviderError("unsupported analysis type")
