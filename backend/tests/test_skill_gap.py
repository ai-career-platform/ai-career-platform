import pytest
from app.services.skill_gap import Requirement, calculate_skill_gap, to_snapshot_example, RULE_VERSION


def test_golden_gap_missing_and_deterministic_order():
    requirements = [Requirement('sql', 3), Requirement('python', 3), Requirement('html', 1, False)]
    result = calculate_skill_gap(requirements, {'python': 1, 'sql': None})
    assert [(x.code, x.gap, x.missing_kind, x.mandatory) for x in result.items] == [
        ('sql', 3, 'not_reported', True), ('python', 2, None, True), ('html', 1, 'not_registered', False)]
    assert result.rule_version == RULE_VERSION
    assert result == calculate_skill_gap(list(reversed(requirements)), {'sql': None, 'python': 1})


def test_floor_zero_tie_order_and_empty():
    result = calculate_skill_gap([Requirement('z', 1), Requirement('a', 1)], {'z': 5, 'a': 1})
    assert [(x.code, x.gap) for x in result.items] == [('a', 0), ('z', 0)]
    assert calculate_skill_gap([], {}).items == ()


@pytest.mark.parametrize('level', [-1, 0, 6, True, 1.5, '3'])
def test_reject_invalid_levels(level):
    with pytest.raises(ValueError):
        calculate_skill_gap([Requirement('python', 3)], {'python': level})


def test_reject_duplicate_codes_and_invalid_requirement():
    with pytest.raises(ValueError):
        calculate_skill_gap([Requirement('a', 1), Requirement('a', 2)], {})
    with pytest.raises(ValueError):
        calculate_skill_gap([Requirement('a', 6)], {})
    with pytest.raises(ValueError):
        calculate_skill_gap([Requirement(' a', 1)], {})


def test_snapshot_converts_missing_to_zero_without_mutating_input():
    observed = {'python': None, 'sql': 2}
    result = calculate_skill_gap([Requirement('python', 3), Requirement('sql', 3)], observed)
    snapshots = {item.code: to_snapshot_example(item) for item in result.items}
    assert snapshots['python'] == {'skill_code': 'python', 'required_level': 3, 'observed_level': 0, 'gap': 3}
    assert snapshots['sql']['observed_level'] == 2
    assert observed['python'] is None
    assert next(item for item in result.items if item.code == 'python').missing_kind == 'not_reported'
