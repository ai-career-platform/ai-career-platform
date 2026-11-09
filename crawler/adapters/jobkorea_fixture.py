"""Offline JobKorea-shaped source adapter for synthetic training data only."""
from __future__ import annotations

import json
from pathlib import Path


class FixtureInputError(ValueError):
    """Fixture is missing, malformed or has the wrong shape."""


class JobKoreaFixtureAdapter:
    source_code = "jobkorea"

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = Path(fixture_path)

    def fetch(self) -> list[dict]:
        try:
            raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FixtureInputError("Cannot read a valid JSON fixture") from exc
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise FixtureInputError("Fixture must be a list of posting objects")
        return raw
