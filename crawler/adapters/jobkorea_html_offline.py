"""T62 STEP 07: offline JobPosting JSON-LD reader for supplied HTML strings.

NO HTTP, browser automation, filesystem, DB or live JobKorea access.
Only explicit JobPosting JSON-LD is trusted. Missing fields stay missing;
HTML presentation text, employer address and SEO snippets are not guessed.
The user-supplied 2026-11-07 detail-page JSON-LD is covered by a minimal
regression fixture. This is not evidence of live HTTP collection or all pages.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin

from crawler.normalizer import InvalidPosting, normalize


class HtmlPostingError(ValueError):
    """HTML metadata missing, contradictory or malformed (no raw HTML in error)."""


class _PostingLinkCollector(HTMLParser):
    def __init__(self, limit):
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'a' or len(self.urls) >= self.limit:
            return
        href = dict(attrs).get('href')
        if not href:
            return
        try:
            parts = urlsplit(urljoin('https://www.jobkorea.co.kr/', href))
            # Tracking query/fragment are not part of posting identity.
            candidate = parts._replace(query='', fragment='').geturl()
            identifier = _source_id(candidate)
        except (ValueError, HtmlPostingError):
            return
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + identifier
        if url not in self.urls:
            self.urls.append(url)


def parse_jobkorea_list_html(html: str, *, limit: int = 10) -> list[str]:
    """Extract only explicit detail links, in document order; no HTTP requests."""
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('limit must be between 1 and 10')
    if not isinstance(html, str) or not html.strip() or len(html) > 2_000_000:
        raise HtmlPostingError('Invalid offline list HTML input')
    reader = _PostingLinkCollector(limit)
    reader.feed(html)
    return reader.urls


class _JsonLdCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._collecting = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attributes = dict(attrs)
            script_type = attributes.get("type", "").split(";")[0].strip().lower()
            self._collecting = script_type == "application/ld+json"
            self._parts = []

    def handle_data(self, data):
        if self._collecting:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._collecting:
            self.blocks.append("".join(self._parts))
            self._collecting = False
            self._parts = []


def _nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _nodes(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            yield from _nodes(graph)


def _jobposting(obj):
    kind = obj.get("@type")
    return kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind


def _text(value):
    if not isinstance(value, str):
        return None
    return " ".join(value.split()).strip() or None


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        raise HtmlPostingError("Invalid date in JobPosting metadata") from None


def _employment(value):
    mapping = {
        "FULL_TIME": "full_time",
        "PART_TIME": "part_time",
        "CONTRACTOR": "contract",
        "CONTRACT": "contract",
        "INTERN": "intern",
        "INTERN_SHIP": "intern",
    }
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, str) or value.upper() not in mapping:
        return None  # Never invent an unsupported employment classification.
    return mapping[value.upper()]


def _location(value):
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]
    if not isinstance(value, dict):
        return None
    address = value.get("address")
    if isinstance(address, str):
        return _text(address)
    if not isinstance(address, dict):
        return None
    pieces = [_text(address.get(key)) for key in (
        "addressRegion", "addressLocality", "streetAddress",
    )]
    return " ".join(part for part in pieces if part) or None


def _source_id(url):
    if not isinstance(url, str):
        raise HtmlPostingError("Valid source URL required")
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in
                {"www.jobkorea.co.kr", "jobkorea.co.kr"} or
                parts.username or parts.password or parts.port or
                parts.query or parts.fragment):
            raise HtmlPostingError("Unsupported JobKorea URL")
    except ValueError:
        raise HtmlPostingError("Unsupported JobKorea URL") from None
    match = re.fullmatch(r"/Recruit/GI_Read/([0-9]+)", parts.path, flags=re.IGNORECASE)
    if not match:
        raise HtmlPostingError("Unsupported JobKorea posting URL path")
    return match.group(1)


@dataclass(frozen=True)
class HtmlExtraction:
    raw_record: dict
    evidence_fields: tuple[str, ...]
    unknown_fields: tuple[str, ...]

    def normalized(self):
        return normalize(self.raw_record)


def parse_jobkorea_html(*, html: str, source_url: str) -> HtmlExtraction:
    """Parse only supplied HTML. Strictly rejects unsupported/ambiguous pages."""
    external_id = _source_id(source_url)
    if not isinstance(html, str) or not html.strip() or len(html) > 2_000_000:
        raise HtmlPostingError("Invalid offline HTML input")
    reader = _JsonLdCollector()
    reader.feed(html)
    jobs = []
    for block in reader.blocks:
        try:
            document = json.loads(block)
        except (ValueError, TypeError):
            raise HtmlPostingError("Malformed JSON-LD metadata") from None
        jobs.extend(item for item in _nodes(document) if _jobposting(item))
    if len(jobs) != 1:
        raise HtmlPostingError("Expected exactly one JobPosting JSON-LD object")
    item = jobs[0]
    title = _text(item.get("title"))
    employer = item.get("hiringOrganization")
    company = _text(employer.get("name")) if isinstance(employer, dict) else None
    if not title or not company:
        raise HtmlPostingError("Required title or company absent in JSON-LD")
    for key in ("url", "identifier"):
        value = item.get(key)
        if key == "url" and value is not None and value != source_url:
            raise HtmlPostingError("JobPosting URL mismatch")
        if key == "identifier" and value is not None:
            identifier = value.get("value") if isinstance(value, dict) else value
            if str(identifier) != external_id:
                raise HtmlPostingError("JobPosting identifier mismatch")

    raw = {
        "external_posting_id": external_id,
        "source_url": source_url,
        "title": title,
        "company_name": company,
        "location_text": _location(item.get("jobLocation")),
        "employment_type": _employment(item.get("employmentType")),
        "published_on": _date(item.get("datePosted")),
        "expires_on": _date(item.get("validThrough")),
        "status": "published",
    }
    # Validate DTO now; do not let malformed data silently enter a worker.
    try:
        normalize(raw)
    except InvalidPosting:
        raise HtmlPostingError("Extracted JobPosting does not meet normalized contract") from None
    observed = tuple(key for key in (
        "title", "company_name", "location_text", "employment_type",
        "published_on", "expires_on",
    ) if raw[key] is not None)
    missing = tuple(key for key in (
        "location_text", "employment_type", "published_on", "expires_on",
    ) if raw[key] is None)
    return HtmlExtraction(raw, observed, missing)
