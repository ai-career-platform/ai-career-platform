"""T152 fixture-only list->detail raw capture, reusing T62 URL discovery.

No network, live worker, posting JSON-LD parsing, normalizer, or UPSERT.
HTML discovery is limited to explicit links from already supplied list bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from crawler.adapters.jobkorea_html_offline import parse_jobkorea_list_html
from crawler.jobs.raw_artifact_store import RawArtifactError, validate_page


@dataclass(frozen=True)
class FixtureBatchResult:
    keyword_id: int
    list_artifact_id: object
    detail_artifact_ids: tuple[object, ...]
    detail_urls: tuple[str, ...]


def capture_fixture_batch(*, keyword_id: int, list_url: str, list_html: bytes,
                          detail_pages: dict[str, bytes], files, metadata,
                          job_id=None, limit: int = 10) -> FixtureBatchResult:
    """Store a complete synthetic fixture batch.

    Preflight checks all requested bytes BEFORE writing any files. DB records
    are per-page metadata inserts; retry is idempotent by keyword/kind/url/hash.
    A mid-batch metadata failure may leave content-addressed files; no auto-delete.
    """
    if type(keyword_id) is not int or keyword_id <= 0:
        raise RawArtifactError("Positive keyword_id required")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise RawArtifactError("Invalid fixture batch limit")
    if not isinstance(detail_pages, dict):
        raise RawArtifactError("Detail map required")
    validate_page("list", list_url, list_html, "text/html")
    try:
        urls = tuple(parse_jobkorea_list_html(list_html.decode("utf-8", errors="strict"), limit=limit))
    except UnicodeError:
        raise RawArtifactError("List HTML must be UTF-8") from None
    if not urls:
        raise RawArtifactError("No explicit detail links in fixture list")
    if set(detail_pages) != set(urls):
        raise RawArtifactError("Detail map must match discovered links exactly")
    for url in urls:
        validate_page("detail", url, detail_pages[url], "text/html")

    list_receipt = files.save(kind="list", source_url=list_url, body=list_html)
    list_id = metadata.insert(receipt=list_receipt, keyword_id=keyword_id, job_id=job_id)
    detail_ids = []
    for url in urls:
        receipt = files.save(kind="detail", source_url=url, body=detail_pages[url])
        detail_ids.append(metadata.insert(receipt=receipt,keyword_id=keyword_id,job_id=job_id))
    return FixtureBatchResult(keyword_id, list_id, tuple(detail_ids), urls)
