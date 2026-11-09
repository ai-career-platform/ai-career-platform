"""T43 adapter for the inspected T26 draft interface.

Inject calculate_skill_gap and Requirement from T26 after approval/merge.
No T26 calculation is copied here and this module does not approve a model.
The caller must resolve an approved registry version matching rule_version.
"""

from collections.abc import Callable
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.repositories.skill_gaps import GapInputSnapshot, RuleEvaluation
from app.schemas.skill_gaps import GapModelVersion, SkillGapItem


class T26SkillGapEvaluator:
    def __init__(
        self, *, calculate: Callable[..., Any], requirement_factory: Callable[..., Any],
        rule_version: str, model_version: GapModelVersion,
    ):
        self.calculate = calculate
        self.requirement_factory = requirement_factory
        self.rule_version = rule_version
        self.model_version = model_version

    def evaluate(self, snapshot: GapInputSnapshot) -> RuleEvaluation:
        # T26 uses stable skill codes; T43 API/DB uses UUIDs. Keep these maps
        # explicit, preserving registered null vs absent values for T26.
        requirements = {item.skill.code: item for item in snapshot.requirements}
        if len(requirements) != len(snapshot.requirements):
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        # Non-required owned skills also need their code metadata for T26.
        # They cannot affect gaps of required skills, so pass only the required
        # subset, while keeping null values and omitted entries distinct.
        observed = {
            item.skill.code: snapshot.observed_levels[item.skill.skill_id]
            for item in snapshot.requirements
            if item.skill.skill_id in snapshot.observed_levels
        }
        try:
            raw = self.calculate([
                self.requirement_factory(code=code, required_level=item.required_level)
                for code, item in requirements.items()
            ], observed)
            if raw.rule_version != self.rule_version:
                raise ValueError("Unexpected rule version")
            codes = [item.code for item in raw.items]
            if len(codes) != len(set(codes)) or set(codes) != set(requirements):
                raise ValueError("Rule output does not cover the required skills")
            items = []
            for item in raw.items:
                requirement = requirements[item.code]
                expected_observed = observed.get(item.code)
                # Retain T26 null meaning in its input, serialize numeric 0
                # according to T06's response contract.
                if item.observed_level != expected_observed:
                    raise ValueError("Rule output does not match its input")
                if item.required_level != requirement.required_level:
                    raise ValueError("Rule output changed the required level")
                items.append(SkillGapItem(
                    skill=requirement.skill, required_level=item.required_level,
                    observed_level=0 if item.observed_level is None else item.observed_level,
                    gap=item.gap,
                ))
        except (ValueError, TypeError, AttributeError, KeyError):
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from None
        return RuleEvaluation(model_version=self.model_version, items=tuple(items))
