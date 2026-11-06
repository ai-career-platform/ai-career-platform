"""T27 draft rule-based ranking. No persistence, network or access control."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Sequence

RULE_VERSION = 'skill-overlap-draft-v1'
LIMITATION = '기술 목록의 단순 일치 비율이며 채용 성공 확률이 아닙니다.'


@dataclass(frozen=True)
class Posting:
    id: str
    skills: tuple[str, ...]
    source_id: str
    expires_on: date
    status: str = 'published'


@dataclass(frozen=True)
class Recommendation:
    posting_id: str
    score: int
    matched_skills: tuple[str, ...]
    missing_skills: tuple[str, ...]
    source_id: str


@dataclass(frozen=True)
class RecommendationResult:
    items: tuple[Recommendation, ...]
    input_hash: str
    rule_version: str = RULE_VERSION
    limitation: str = LIMITATION


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('식별자는 앞뒤 공백 없는 문자열이어야 합니다')
    return value


def _skills(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list)):
        raise ValueError('기술은 코드 목록이어야 합니다')
    codes = tuple(_identifier(value) for value in values)
    if len(set(codes)) != len(codes):
        raise ValueError('중복된 기술 코드입니다')
    return tuple(sorted(codes))


def recommend(user_skills: Sequence[str], postings: Sequence[Posting], *,
              as_of: date, excluded_ids: Sequence[str] = ()) -> RecommendationResult:
    """Rank published, non-expired items by matched / required skill count.

    Draft choices: expiry date is inclusive; ties use exact ID ordering;
    skill-free postings are omitted. All IDs/codes are opaque and exact-match.
    Caller is responsible for authorization and a privacy-reviewed provenance scheme.
    """
    if type(as_of) is not date:
        raise ValueError('기준일은 date여야 합니다')
    skills = _skills(user_skills)
    if not skills:
        raise ValueError('보유 기술이 필요합니다')
    if isinstance(excluded_ids, (str, bytes)):
        raise ValueError('제외 공고는 ID 목록이어야 합니다')
    excluded = tuple(sorted({_identifier(x) for x in excluded_ids}))
    seen = set()
    normalized = []
    results = []
    for posting in postings:
        if not isinstance(posting, Posting):
            raise ValueError('공고 형식이 올바르지 않습니다')
        pid, source = _identifier(posting.id), _identifier(posting.source_id)
        if pid in seen:
            raise ValueError('중복 공고 ID입니다')
        seen.add(pid)
        if type(posting.expires_on) is not date or posting.status not in ('published', 'closed', 'draft'):
            raise ValueError('공고 상태 또는 만료일이 올바르지 않습니다')
        required = _skills(posting.skills)
        normalized.append({'id': pid, 'skills': required, 'source_id': source,
                           'expires_on': posting.expires_on.isoformat(), 'status': posting.status})
        if posting.status != 'published' or posting.expires_on < as_of or pid in excluded or not required:
            continue
        matched = tuple(code for code in required if code in skills)
        missing = tuple(code for code in required if code not in skills)
        score = int((Decimal(len(matched)) * 100 / Decimal(len(required))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        results.append(Recommendation(pid, score, matched, missing, source))
    results.sort(key=lambda item: (-item.score, item.posting_id))
    canonical = {'rule_version': RULE_VERSION, 'as_of': as_of.isoformat(), 'skills': skills,
                 'excluded_ids': excluded, 'postings': sorted(normalized, key=lambda item: item['id'])}
    digest = sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    return RecommendationResult(tuple(results), digest)
