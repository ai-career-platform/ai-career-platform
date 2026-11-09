"""Adapter boundary tests and integration with the merged T26 calculator."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.errors import AppError, ErrorCode
from app.repositories.skill_gaps import GapInputSnapshot, RequiredGapSkill
from app.schemas.catalog import JobRoleRef, Skill
from app.schemas.skill_gaps import GapModelVersion
from app.services.skill_gap_evaluator import T26SkillGapEvaluator


@pytest.fixture
def snapshot():
    return GapInputSnapshot(
        role=JobRoleRef(job_role_id=UUID(int=1), code="ROLE", name="Synthetic role"),
        is_target_role=True,
        requirements=(RequiredGapSkill(
            skill=Skill(skill_id=UUID(int=2), code="SKILL", name="Synthetic skill"),
            required_level=4,
        ),),
        observed_levels={UUID(int=2): 2},
    )


def evaluator_for(raw, captures=None):
    def calculate(requirements, observed):
        if captures is not None:
            captures.update(requirements=requirements, observed=observed)
        return raw
    return T26SkillGapEvaluator(
        calculate=calculate, requirement_factory=SimpleNamespace,
        rule_version="fixture-rule-v1",
        model_version=GapModelVersion(model_code="fixture_gap", version="1", kind="rule"),
    )


def fixture_result(**changes):
    item = dict(code="SKILL", required_level=4, observed_level=2, gap=2)
    item.update(changes)
    return SimpleNamespace(rule_version="fixture-rule-v1", items=(SimpleNamespace(**item),))


def test_adapter_bridges_uuid_code_and_rule_registry_version(snapshot):
    captures = {}
    result = evaluator_for(fixture_result(), captures).evaluate(snapshot)
    assert captures["requirements"][0].code == "SKILL"
    assert captures["observed"] == {"SKILL": 2}
    assert result.items[0].skill.skill_id == UUID(int=2)
    assert result.model_version.model_code == "fixture_gap"


@pytest.mark.parametrize("registered", [True, False])
def test_null_and_absent_remain_distinct_in_input_but_numeric_in_dto(snapshot, registered):
    snapshot = replace(snapshot, observed_levels={UUID(int=2): None} if registered else {UUID(int=99): 3})
    captures = {}
    result = evaluator_for(fixture_result(observed_level=None, gap=4), captures).evaluate(snapshot)
    assert captures["observed"] == ({"SKILL": None} if registered else {})
    assert result.items[0].observed_level == 0
    assert result.items[0].gap == 4


@pytest.mark.parametrize("changes", [
    {"code": "UNKNOWN"}, {"required_level": 5}, {"observed_level": 3},
    {"gap": 5}, {"gap": True},
])
def test_malformed_rule_result_is_dependency_error(snapshot, changes):
    with pytest.raises(AppError) as exc:
        evaluator_for(fixture_result(**changes)).evaluate(snapshot)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize("case", ["wrong_version", "duplicate", "missing"])
def test_rule_version_and_required_coverage(snapshot, case):
    raw = fixture_result()
    if case == "wrong_version":
        raw.rule_version = "unapproved-other-version"
    elif case == "duplicate":
        raw.items = raw.items * 2
    else:
        raw.items = ()
    with pytest.raises(AppError):
        evaluator_for(raw).evaluate(snapshot)


def test_duplicate_requirement_codes_rejected(snapshot):
    requirement = snapshot.requirements[0]
    other = RequiredGapSkill(skill=requirement.skill.model_copy(update={"skill_id": UUID(int=3)}), required_level=4)
    with pytest.raises(AppError):
        evaluator_for(fixture_result()).evaluate(replace(snapshot, requirements=(requirement, other)))


@pytest.mark.parametrize("observed,expected", [(1, 3), (2, 2), (4, 0), (5, 0), (None, 4)])
def test_actual_t26_calculation_maps_to_response_without_mutating_input(snapshot, observed, expected):
    source = replace(snapshot, observed_levels={UUID(int=2): observed})
    model = GapModelVersion(model_code="synthetic_model", version="test", kind="rule")
    evaluator = T26SkillGapEvaluator.from_t26(model)
    result = evaluator.evaluate(source)
    assert result.items[0].gap == expected
    assert result.items[0].observed_level == (0 if observed is None else observed)
    assert result.model_version == model
    assert source.observed_levels == {UUID(int=2): observed}
    assert evaluator.evaluate(source) == result


def test_actual_t26_absent_skill_and_unrelated_skill(snapshot):
    source = replace(snapshot, observed_levels={UUID(int=99): 5})
    result = T26SkillGapEvaluator.from_t26(
        GapModelVersion(model_code="synthetic_model", version="test", kind="rule"),
    ).evaluate(source)
    assert result.items[0].gap == 4
    assert result.items[0].observed_level == 0
    assert source.observed_levels == {UUID(int=99): 5}
