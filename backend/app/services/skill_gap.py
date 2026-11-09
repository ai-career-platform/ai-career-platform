"""T26 draft: pure, deterministic Skill Gap calculation (no DB or API)."""
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

RULE_VERSION = "skill-gap-draft-v1"
LIMITATION = "자기평가를 기준으로 한 규칙 비교이며 채용 성공 확률이 아닙니다."


@dataclass(frozen=True)
class Requirement:
    code: str
    required_level: int
    mandatory: bool = True


@dataclass(frozen=True)
class GapItem:
    code: str
    required_level: int
    observed_level: Optional[int]
    gap: int
    mandatory: bool
    missing_kind: Optional[str]


@dataclass(frozen=True)
class GapResult:
    items: tuple[GapItem, ...]
    rule_version: str = RULE_VERSION
    limitation: str = LIMITATION


def _code(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("기술 코드는 앞뒤 공백 없는 빈 문자열이 아니어야 합니다")
    return value


def _level(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 5:
        raise ValueError("숙련도는 1~5 사이 정수여야 합니다")
    return value


def calculate_skill_gap(requirements: Sequence[Requirement],
                        observed: Mapping[str, Optional[int]]) -> GapResult:
    """Compare 1..5 levels; missing entries and null use zero for calculation.

    Draft FR-ANL-002; absent vs unreported remains distinguishable in results.
    Input identifiers are exact codes; normalization belongs to a future contract.
    """
    if not isinstance(observed, Mapping):
        raise ValueError("보유 기술은 코드와 수준의 매핑이어야 합니다")
    for code, level in observed.items():
        _code(code)
        if level is not None:
            _level(level)
    seen = set()
    items = []
    for req in requirements:
        if not isinstance(req, Requirement):
            raise ValueError("요구 기술 형식이 올바르지 않습니다")
        code = _code(req.code)
        if code in seen:
            raise ValueError("중복된 요구 기술 코드입니다")
        seen.add(code)
        required = _level(req.required_level)
        if type(req.mandatory) is not bool:
            raise ValueError("필수 여부는 참 또는 거짓이어야 합니다")
        level = observed.get(code)
        missing = 'not_registered' if code not in observed else ('not_reported' if level is None else None)
        items.append(GapItem(code, required, level, max(required - (level or 0), 0), req.mandatory, missing))
    items.sort(key=lambda item: (-item.gap, item.code))
    return GapResult(tuple(items))


def to_snapshot_example(item: GapItem) -> dict:
    """Map one draft result to a synthetic T05-shaped calculation snapshot.

    No persistence or DB identifier mapping; the source value remains untouched.
    """
    if not isinstance(item, GapItem):
        raise ValueError("GapItem이 필요합니다")
    return {
        'skill_code': item.code,
        'required_level': item.required_level,
        'observed_level': 0 if item.observed_level is None else item.observed_level,
        'gap': item.gap,
    }
