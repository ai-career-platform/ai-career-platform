"""`match_rule` v1 Golden Fixture (FR-ANL-001 수용 기준 1: 같은 입력이면 항상 같은 점수)."""

import random
import uuid
from decimal import Decimal

import pytest

from app.services import match_rule as rule
from app.services.match_rule import Requirement, evaluate

S = [uuid.UUID(int=i) for i in range(1, 10)]


def test_golden_required_only():
    # 충족도 1, 2/3, 0 (모두 필수, 가중치 2) → 100 × (2 + 4/3 + 0) / 6 = 55.555… → 55.56
    out = evaluate([Requirement(S[0], 4), Requirement(S[1], 3), Requirement(S[2], 2)], {S[0]: 4, S[1]: 2}, set())
    assert (out.status, out.score, out.matched_skill_count, out.missing_skill_count) == (
        "completed", Decimal("55.56"), 1, 2,
    )
    assert out.matched_skill_ids == (S[0],) and set(out.missing_skill_ids) == {S[1], S[2]}
    assert out.limitations == [rule.LIMIT_BASE]


def test_golden_preferred_and_project_only_skill():
    # 위 + 우대 기술(요구 2, 가중치 1)을 프로젝트에서만 사용 → 수준 1 → 충족도 1/2
    # 100 × (10/3 + 1/2) / 7 = 54.7619… → 54.76
    reqs = [Requirement(S[0], 4), Requirement(S[1], 3), Requirement(S[2], 2), Requirement(S[3], 2, is_required=False)]
    out = evaluate(reqs, {S[0]: 4, S[1]: 2}, {S[3]})
    assert out.score == Decimal("54.76")
    assert (out.matched_skill_count, out.missing_skill_count) == (1, 3)
    assert out.limitations == [rule.LIMIT_BASE, rule.LIMIT_PROJECT_ONLY]


def test_rounding_is_half_up_not_bankers():
    # 필수 3개 충족(75) + 우대(요구 4, 수준 1 → 1/4 × 12.5 = 3.125) + 우대 미보유 → 78.125 → 78.13
    reqs = [Requirement(S[i], 2) for i in range(3)] + [
        Requirement(S[3], 4, is_required=False),
        Requirement(S[4], 2, is_required=False),
    ]
    out = evaluate(reqs, {S[0]: 2, S[1]: 3, S[2]: 5, S[3]: 1}, set())
    assert out.score == Decimal("78.13")


def test_full_and_zero_scores():
    reqs = [Requirement(S[0], 3), Requirement(S[1], 1)]
    assert evaluate(reqs, {S[0]: 5, S[1]: 1}, set()).score == Decimal("100.00")
    assert evaluate(reqs, {S[5]: 5}, set()).score == Decimal("0.00")


def test_unrated_proficiency_counts_as_zero_and_is_explained():
    out = evaluate([Requirement(S[0], 2)], {S[0]: None}, set())
    assert out.score == Decimal("0.00") and out.missing_skill_count == 1
    assert rule.LIMIT_UNRATED in out.limitations


def test_project_use_never_lowers_a_rated_skill():
    out = evaluate([Requirement(S[0], 3)], {S[0]: 3}, {S[0]})
    assert out.score == Decimal("100.00") and rule.LIMIT_PROJECT_ONLY not in out.limitations


def test_no_requirements_is_failed_without_score():
    out = evaluate([], {S[0]: 3}, set(), posting_closed=True)
    assert (out.status, out.score, out.matched_skill_count, out.missing_skill_count) == ("failed", None, None, None)
    assert out.limitations == [rule.LIMIT_BASE, rule.LIMIT_NO_REQUIREMENTS, rule.LIMIT_CLOSED]


def test_closed_posting_is_explained():
    assert evaluate([Requirement(S[0], 1)], {S[0]: 1}, set(), posting_closed=True).limitations[-1] == rule.LIMIT_CLOSED


@pytest.mark.parametrize("seed", range(5))
def test_input_order_does_not_change_result(seed):
    reqs = [Requirement(S[i], 1 + i % 5, is_required=i % 2 == 0) for i in range(9)]
    skills = {S[i]: (i % 6) or None for i in range(9)}
    expected = evaluate(reqs, skills, {S[1], S[7]})
    shuffled = reqs[:]
    random.Random(seed).shuffle(shuffled)
    assert evaluate(shuffled, dict(reversed(list(skills.items()))), {S[7], S[1]}) == expected
