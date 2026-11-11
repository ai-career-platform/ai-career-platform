"""T99 채용공고 고급 검색 규칙 (T98 계약 PROPOSED — docs/search/T98_ADVANCED_SEARCH_CONTRACT.md §3~§5).

`JOB_SEARCH_ADVANCED=true` 일 때만 쓰입니다(기본 꺼짐 → 기존 T18 목록 API 그대로).
지역은 원천에 구조화된 값이 없어 `location_text` 첫 단어로 판정하는 파생값입니다(§4). 표는 시험이 문서와 대조합니다.
"""
from __future__ import annotations

from datetime import timedelta

from app.core.errors import AppError, ErrorCode

REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "seoul": ("서울",), "busan": ("부산",), "daegu": ("대구",), "incheon": ("인천",), "gwangju": ("광주",),
    "daejeon": ("대전",), "ulsan": ("울산",), "sejong": ("세종",), "gyeonggi": ("경기",), "gangwon": ("강원",),
    "chungbuk": ("충북", "충청북도"), "chungnam": ("충남", "충청남도"), "jeonbuk": ("전북", "전라북도"),
    "jeonnam": ("전남", "전라남도"), "gyeongbuk": ("경북", "경상북도"), "gyeongnam": ("경남", "경상남도"),
    "jeju": ("제주",),
}
POSTED_WITHIN: dict[str, timedelta] = {"1d": timedelta(days=1), "3d": timedelta(days=3), "7d": timedelta(days=7),
                                       "30d": timedelta(days=30)}
EMPLOYMENT_TYPES = ("full_time", "contract", "intern", "part_time")
MAX_VALUES = {"company_id": 10, "job_role_id": 10, "employment_type": 4, "region": 5}
Q_MAX = 100


def invalid(field: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"job search: invalid {field}")


def normalize_q(q: str | None) -> str | None:
    """앞뒤 공백 제거·연속 공백 1칸. 결과가 비거나 100자를 넘으면 422."""
    if q is None:
        return None
    value = " ".join(q.split())
    if not 1 <= len(value) <= Q_MAX:
        raise invalid("q")
    return value


def unique(field: str, values: list | None) -> tuple:
    """개수 상한은 중복 제거 **전** 기준(계약 §3). 결과는 정렬된 tuple — 순서·중복이 cursor 에 영향 없음."""
    values = values or []
    if len(values) > MAX_VALUES[field]:
        raise invalid(field)
    return tuple(sorted(set(values), key=str))
