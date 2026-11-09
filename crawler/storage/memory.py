"""Temporary in-memory upsert store for normalized job postings.

No PostgreSQL, disk persistence, external requests, or network access.
The store is intentionally scoped to the life of a Python process.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from crawler.normalizer import NormalizedPosting


WriteResult = Literal["inserted", "updated", "unchanged"]


class PostingStore(Protocol):
    """Contract to be implemented by a future approved persistence adapter."""

    def upsert(self, posting: NormalizedPosting) -> WriteResult: ...


@dataclass
class MemoryPostingStore:
    """Simple deterministic in-memory store, keyed by source and external ID."""

    def __init__(self) -> None:
        self._postings: dict[tuple[str, str], NormalizedPosting] = {}

    def upsert(self, posting: NormalizedPosting) -> WriteResult:
        key = (posting.source_code, posting.external_posting_id)
        existing = self._postings.get(key)
        if existing is None:
            self._postings[key] = posting
            return "inserted"
        if existing == posting:
            return "unchanged"
        self._postings[key] = posting
        return "updated"

    def get(self, source_code: str, external_posting_id: str) -> NormalizedPosting | None:
        return self._postings.get((source_code, external_posting_id))

    def __len__(self) -> int:
        return len(self._postings)
