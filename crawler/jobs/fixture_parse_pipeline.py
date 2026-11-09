"""T153 stage-1: parse already stored synthetic detail HTML, without HTTP.

T152 owns raw storage; this stage only verifies bytes then invokes the existing
T62 JSON-LD parser + normalizer. No posting writes, DB DDL or scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_html, HtmlPostingError
from crawler.jobs.raw_artifact_store import RawArtifactError

PARSER_VERSION = "jobkorea-jsonld-v1"


@dataclass(frozen=True)
class ParsedArtifact:
    artifact_id: object
    parser_version: str
    status: str
    posting: object | None
    error_code: str | None


def parse_stored_detail(*, artifact_id, source_url: str, storage_key: str,
                        sha256: str, files) -> ParsedArtifact:
    """Read integrity-verified T152 bytes and normalize one detail.

    Invalid raw pages become a typed failed result. A missing/corrupt storage
    reference remains an error so the caller can repair the storage first.
    """
    data = files.read_verified(storage_key, sha256)
    try:
        html = data.decode("utf-8", errors="strict")
    except UnicodeError:
        return ParsedArtifact(artifact_id, PARSER_VERSION, "INVALID", None,
                              "INVALID_ENCODING")
    try:
        extracted = parse_jobkorea_html(html=html, source_url=source_url)
    except (HtmlPostingError, ValueError):
        return ParsedArtifact(artifact_id, PARSER_VERSION, "INVALID", None,
                              "INVALID_METADATA")
    posting = replace(extracted.normalized(), source_code="jobkorea_imported")
    return ParsedArtifact(artifact_id, PARSER_VERSION, "VALID", posting, None)


def process_stored_details(*, artifacts, files, posting_store):
    """Explicit optional offline fixture postprocessing. Never fetches HTML.

    Caller passes metadata rows with artifact_id, kind, source_url,
    storage_key, sha256. Only VALID detail postings are upserted.
    """
    report = dict(valid=0,invalid=0,inserted=0,updated=0,unchanged=0,results=[])
    for row in artifacts:
        if row["kind"] != "detail":
            continue
        result = parse_stored_detail(artifact_id=row["artifact_id"],
                                     source_url=row["source_url"],
                                     storage_key=row["storage_key"],
                                     sha256=row["sha256"], files=files)
        report["results"].append(result)
        if result.status != "VALID":
            report["invalid"] += 1
            continue
        report["valid"] += 1
        outcome = posting_store.upsert(result.posting)
        if outcome not in ("inserted","updated","unchanged"):
            raise ValueError("Unknown posting store result")
        report[outcome] += 1
    return report
