"""T139 기술 자동완성·동의어 검색 (PROPOSED, `SKILL_AUTOCOMPLETE_API=true` 일 때만 노출).

T137 정책(docs/data/CODE_TAXONOMY_POLICY.md §3)을 그대로 따른다.
- 정규화: 앞뒤 공백 제거 → NFKC → 소문자 → 공백·`.`·`-`·`_`·`/`·괄호 제거. `+`, `#` 은 남긴다 (C++ ≠ C#).
  T137 mock 의 SQL `normalize_term()` 과 같은 결과여야 한다(시험으로 고정).
- 일치 순서: 코드 철자(code) → exact 별칭(alias) → ambiguous 별칭(ambiguous, 후보 전부, 자동 선택 안 함)
  → 이름·코드·별칭 앞부분(prefix) → 부분 포함(partial).
- 같은 표준 코드는 한 번만 (가장 좋은 일치만 남김). merged 코드는 `replaced_by` 를 따라 살아 있는 코드로 바꾸고,
  deprecated(대체 없음) 코드는 결과에서 뺀다. 순환·5단계 초과 체인은 뺀다(T138 preflight 가 막아야 할 데이터).
- 페이지: 결과 전체를 같은 규칙으로 정렬한 뒤 offset 으로 자른다. cursor 는 HMAC 서명이며 검색어와
  분류 데이터 지문에 묶인다. 데이터가 바뀌면 400 INVALID_CURSOR (중간 항목이 조용히 빠지지 않도록).

출처(TaxonomySource)
- `SqlSkillSource`: 실제 `career.skills` (code, name, is_active). **별칭 표는 아직 없다**(T137 표는 제안 단계,
  T138 #154 미병합). 그래서 실제 DB 에서는 code/prefix/partial 만 가능하다.
- `MemoryTaxonomySource`: 시험·Mock 용 합성 분류(별칭·병합·폐기 포함).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from app.core.errors import AppError, ErrorCode

CURSOR_KEY_PURPOSE = "t139-skill-suggest-cursor-v1"
CURSOR_VERSION = 1
MAX_CHAIN = 5
MAX_QUERY_LEN = 60
MAX_SOURCE_ROWS = 5000
_SIG_LEN = 32
_STRIP = re.compile(r"[\s._/()\[\]\-]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

MatchType = Literal["code", "alias", "ambiguous", "prefix", "partial"]
_RANK: dict[str, int] = {"code": 0, "alias": 1, "ambiguous": 2, "prefix": 3, "partial": 4}


def normalize_term(value: str) -> str:
    """T137 `normalize_term()` 의 Python 판. regexp `[[:space:]._/()\\[\\]-]+` 제거와 같다."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", value.strip()).lower())


@dataclass(frozen=True)
class Alias:
    display: str
    kind: Literal["exact", "ambiguous"] = "exact"

    @property
    def norm(self) -> str:
        return normalize_term(self.display)


@dataclass(frozen=True)
class TaxonomyEntry:
    code: str
    name: str
    status: Literal["active", "deprecated", "merged"] = "active"
    replaced_by: str | None = None
    aliases: tuple[Alias, ...] = ()
    skill_id: UUID | None = None
    name_en: str | None = None


class TaxonomySource(Protocol):
    name: str

    def entries(self) -> list[TaxonomyEntry]: ...


@dataclass
class MemoryTaxonomySource:
    items: list[TaxonomyEntry] = field(default_factory=list)
    name: str = "memory"

    def entries(self) -> list[TaxonomyEntry]:
        return list(self.items)


@dataclass(frozen=True)
class Suggestion:
    code: str
    name: str
    match_type: MatchType
    matched: str
    skill_id: UUID | None


@dataclass(frozen=True)
class SuggestPage:
    items: list[Suggestion]
    next_cursor: str | None
    alias_source: Literal["taxonomy", "none"]


def _resolve(code: str, by_code: dict[str, TaxonomyEntry]) -> TaxonomyEntry | None:
    """merged → 살아 있는 코드. deprecated·없음·순환·긴 체인은 None."""
    seen: set[str] = set()
    current = by_code.get(code)
    while current is not None and current.status == "merged":
        if current.code in seen or len(seen) >= MAX_CHAIN or not current.replaced_by:
            return None
        seen.add(current.code)
        current = by_code.get(current.replaced_by)
    if current is None or current.status != "active":
        return None
    return current


class SkillSuggestService:
    def __init__(self, source: TaxonomySource, *, cursor_key: bytes):
        if not isinstance(cursor_key, bytes) or len(cursor_key) < _SIG_LEN:
            raise ValueError("cursor_key must contain at least 32 bytes")
        self.source = source
        self._key = cursor_key

    # ------------------------------------------------------------------ input
    @staticmethod
    def check_query(q: str) -> str:
        if _CONTROL.search(q) or len(q) > MAX_QUERY_LEN:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="suggest query rejected")
        norm = normalize_term(q)
        if not norm:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="suggest query empty after normalization")
        return norm

    # ------------------------------------------------------------------ matching
    def _candidates(self, norm: str) -> tuple[list[Suggestion], str, bool]:
        entries = self.source.entries()
        if len(entries) > MAX_SOURCE_ROWS:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="taxonomy source too large for in-memory suggest")
        by_code = {e.code: e for e in entries}
        has_alias = any(e.aliases for e in entries)
        best: dict[str, tuple[int, Suggestion]] = {}

        def offer(entry: TaxonomyEntry, match_type: MatchType, matched: str) -> None:
            live = _resolve(entry.code, by_code)
            if live is None:
                return
            if match_type == "code" and live.code != entry.code:
                match_type = "alias"            # 병합된 옛 코드 철자는 별칭처럼 취급(돌려주는 코드가 다름)
            rank = _RANK[match_type]
            current = best.get(live.code)
            if current is None or rank < current[0]:
                best[live.code] = (rank, Suggestion(live.code, live.name, match_type, matched, live.skill_id))

        for entry in entries:
            names = [entry.name] + ([entry.name_en] if entry.name_en else [])
            if normalize_term(entry.code) == norm:
                offer(entry, "code", entry.code)
            for alias in entry.aliases:
                if alias.norm == norm:
                    offer(entry, "alias" if alias.kind == "exact" else "ambiguous", alias.display)
            for text in [entry.code, *names, *(a.display for a in entry.aliases)]:
                n = normalize_term(text)
                if n.startswith(norm):
                    offer(entry, "prefix", text)
                elif norm in n:
                    offer(entry, "partial", text)

        ordered = sorted(best.values(), key=lambda p: (p[0], len(p[1].name), p[1].name.casefold(), p[1].code))
        fingerprint = hashlib.sha256(json.dumps(
            sorted((e.code, e.name, e.status, e.replaced_by or "", [(a.display, a.kind) for a in e.aliases])
                   for e in entries), ensure_ascii=False).encode()).hexdigest()
        return [s for _, s in ordered], fingerprint, has_alias

    # ------------------------------------------------------------------ cursor
    def _encode(self, norm: str, fingerprint: str, offset: int) -> str:
        payload = json.dumps([CURSOR_VERSION, hashlib.sha256(norm.encode()).hexdigest(), fingerprint[:32], offset],
                             separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(hmac.digest(self._key, payload, "sha256") + payload).decode().rstrip("=")

    def _decode(self, token: str, norm: str, fingerprint: str) -> int:
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
                raise ValueError("non-canonical")
            sig, payload = raw[:_SIG_LEN], raw[_SIG_LEN:]
            if not hmac.compare_digest(sig, hmac.digest(self._key, payload, "sha256")):
                raise ValueError("bad signature")
            version, q_hash, fp, offset = json.loads(payload)
            if (type(version) is not int or version != CURSOR_VERSION
                    or q_hash != hashlib.sha256(norm.encode()).hexdigest() or fp != fingerprint[:32]
                    or type(offset) is not int or offset < 1):
                raise ValueError("cursor does not match")
            return offset
        except (ValueError, TypeError, binascii.Error):
            raise AppError(ErrorCode.INVALID_CURSOR, log_detail="skill suggest cursor rejected") from None

    # ------------------------------------------------------------------ api
    def suggest(self, q: str, *, limit: int = 10, cursor: str | None = None) -> SuggestPage:
        norm = self.check_query(q)
        results, fingerprint, has_alias = self._candidates(norm)
        offset = self._decode(cursor, norm, fingerprint) if cursor else 0
        page = results[offset:offset + limit]
        nxt = offset + limit
        return SuggestPage(
            items=page,
            next_cursor=self._encode(norm, fingerprint, nxt) if nxt < len(results) else None,
            alias_source="taxonomy" if has_alias else "none",
        )
