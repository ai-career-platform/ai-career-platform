"""Normalize synthetic JobKorea-shaped listing records for training.

No network access or database writes occur here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from urllib.parse import urlsplit


class InvalidPosting(ValueError):
    """A source record does not meet the training DTO contract."""


@dataclass(frozen=True)
class NormalizedPosting:
    source_code: str
    external_posting_id: str
    source_url: str
    title: str
    company_name: str
    location_text: str | None
    employment_type: str | None
    published_on: str | None
    expires_on: str | None
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


def _required_string(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidPosting(f"Missing or invalid field: {key}")
    return value.strip()


def _optional_string(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise InvalidPosting(f"Invalid field: {key}")
    return value.strip() or None


def _date(raw: dict, key: str) -> str | None:
    value = _optional_string(raw, key)
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise InvalidPosting(f"Invalid ISO date: {key}") from exc


def normalize(raw: dict) -> NormalizedPosting:
    if not isinstance(raw, dict):
        raise InvalidPosting("Expected a JSON object")
    external_id = _required_string(raw, "external_posting_id")
    url = _required_string(raw, "source_url")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"www.jobkorea.co.kr", "jobkorea.co.kr"} or parts.username or parts.password or parts.port:
        raise InvalidPosting("Invalid JobKorea source URL")
    published = _date(raw, "published_on")
    expires = _date(raw, "expires_on")
    if published and expires and expires < published:
        raise InvalidPosting("Expiry precedes publish date")
    status = _required_string(raw, "status").lower()
    if status not in {"published", "closed", "draft"}:
        raise InvalidPosting("Unsupported posting status")
    employment = _optional_string(raw, "employment_type")
    if employment not in {None, "full_time", "contract", "intern", "part_time"}:
        raise InvalidPosting("Unsupported employment type")
    return NormalizedPosting(
        source_code="jobkorea",
        external_posting_id=external_id,
        source_url=url,
        title=_required_string(raw, "title"),
        company_name=_required_string(raw, "company_name"),
        location_text=_optional_string(raw, "location_text"),
        employment_type=employment,
        published_on=published,
        expires_on=expires,
        status=status,
    )
