"""Adapter contract; this module does not implement network fetching."""
from __future__ import annotations

from typing import Protocol


class SourceAdapter(Protocol):
    source_code: str

    def fetch(self) -> list[dict]:
        """Return raw posting dictionaries; source-specific implementation."""
        ...
