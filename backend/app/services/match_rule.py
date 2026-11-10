"""적합도 규칙 기반 Baseline `match_rule` v1 (FR-ANL-001). DB·HTTP와 무관한 순수 함수.

같은 입력이면 언제나 같은 결과가 나온다(입력 순서와 무관). 점수는 **합격 확률이 아니다.**

규칙 (backend/docs/MATCH_RULE.md 에 예시와 함께 정리)
1. 요구 기술: 공고는 job_posting_skills(필수/우대, required_level), 직무는 job_role_skills(모두 필수).
   공고의 required_level이 없으면 공고 직무의 기본값(job_role_skills), 그것도 없으면 3.
2. 내 수준: user_skills.proficiency (NULL은 0). 프로젝트 사용 기술(user_project_skills)은 최소 1.
3. 기술별 충족도 = min(내 수준, 요구 수준) / 요구 수준 (0~1).
4. 점수 = 100 × Σ(가중치 × 충족도) / Σ가중치. 가중치는 필수 2, 우대 1. 소수 둘째 자리 반올림(half-up).
5. 충족 기술 = 내 수준 ≥ 요구 수준, 부족 기술 = 나머지.
6. 요구 기술이 하나도 없으면 계산하지 않음(status=failed).
"""

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

MODEL_CODE = "match_rule"
VERSION = "1"
KIND = "rule"

DEFAULT_REQUIRED_LEVEL = 3
PROJECT_ONLY_LEVEL = 1
WEIGHT_REQUIRED = 2
WEIGHT_PREFERRED = 1

# 화면에 그대로 표시하는 한계 설명. 순서는 아래 목록 순서로 고정.
LIMIT_BASE = "자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다."
LIMIT_UNRATED = "숙련도를 입력하지 않은 기술은 0으로 계산했습니다."
LIMIT_PROJECT_ONLY = "프로젝트에서만 사용한 기술은 숙련도 1로 계산했습니다."
LIMIT_CLOSED = "마감된 공고입니다."
LIMIT_NO_REQUIREMENTS = "요구 기술 정보가 없어 적합도를 계산할 수 없습니다."


@dataclass(frozen=True)
class Requirement:
    skill_id: uuid.UUID
    required_level: int  # 1~5
    is_required: bool = True


@dataclass(frozen=True)
class MatchOutcome:
    status: str  # completed / failed
    score: Decimal | None
    matched_skill_count: int | None
    missing_skill_count: int | None
    limitations: list[str] = field(default_factory=list)
    matched_skill_ids: tuple[uuid.UUID, ...] = ()
    missing_skill_ids: tuple[uuid.UUID, ...] = ()


def evaluate(
    requirements: list[Requirement],
    proficiencies: dict[uuid.UUID, int | None],
    project_skill_ids: set[uuid.UUID],
    *,
    posting_closed: bool = False,
) -> MatchOutcome:
    closed = [LIMIT_CLOSED] if posting_closed else []
    reqs = sorted(requirements, key=lambda r: str(r.skill_id))  # 입력 순서와 무관하게
    if not reqs:
        return MatchOutcome("failed", None, None, None, [LIMIT_BASE, LIMIT_NO_REQUIREMENTS, *closed])

    used_unrated = used_project_only = False
    total_weight = 0
    earned = Fraction(0)
    matched: list[uuid.UUID] = []
    missing: list[uuid.UUID] = []
    for req in reqs:
        proficiency = proficiencies.get(req.skill_id)
        level = proficiency or 0
        if req.skill_id in proficiencies and proficiency is None:
            used_unrated = True
        if req.skill_id in project_skill_ids and level < PROJECT_ONLY_LEVEL:
            level = PROJECT_ONLY_LEVEL
            used_project_only = True

        weight = WEIGHT_REQUIRED if req.is_required else WEIGHT_PREFERRED
        total_weight += weight
        earned += weight * Fraction(min(level, req.required_level), req.required_level)
        (matched if level >= req.required_level else missing).append(req.skill_id)

    exact = earned * 100 / total_weight  # 분수로 정확히 계산한 뒤 마지막에 한 번만 반올림
    score = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    limitations = [LIMIT_BASE]
    if used_unrated:
        limitations.append(LIMIT_UNRATED)
    if used_project_only:
        limitations.append(LIMIT_PROJECT_ONLY)
    limitations += closed
    return MatchOutcome(
        "completed", score, len(matched), len(missing), limitations, tuple(matched), tuple(missing)
    )
