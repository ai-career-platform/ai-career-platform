"""T62 STEP 08: explicit-evidence offline extraction accuracy evaluation.

No HTTP, no database, no filesystem. Synthetic accuracy cannot become a
real-site PASS. Missing ground truth is never counted as a correct prediction.
Reports contain counts and field names only, not raw job text or PII.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from crawler.adapters.jobkorea_html_offline import HtmlExtraction, HtmlPostingError, parse_jobkorea_html

FIELDS = (
    "external_posting_id", "title", "company_name", "location_text",
    "employment_type", "published_on", "expires_on",
)
# status="published" is only a placeholder in STEP07, not a validated posting state.
NOT_SUPPORTED = ("experience", "education", "salary", "application_status")


class FieldVerdict(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class AccuracyStatus(str, Enum):
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"
    REAL_NOT_VERIFIED = "REAL_NOT_VERIFIED"
    REAL_PARTIAL = "REAL_PARTIAL"


@dataclass(frozen=True)
class GoldCase:
    """Human-checked or synthetic truth; provenance is mandatory.

    Real cases require source authorization and inspected HTML to be supplied
    separately to evaluate_html(); this is NOT a legal permission checker.
    """
    source_url: str
    expected: Mapping[str, str | None]
    provenance: str = "synthetic"
    evidence_ref: str | None = None

    def __post_init__(self):
        if self.provenance not in ("synthetic", "real_authorized"):
            raise ValueError("Unrecognized provenance")
        if self.provenance == "real_authorized" and (
            not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip()
        ):
            raise ValueError("Real case requires a traceable evidence reference")
        if not isinstance(self.expected, Mapping) or not self.expected:
            raise ValueError("Ground truth must declare at least one field")
        for key, value in self.expected.items():
            if key not in FIELDS + NOT_SUPPORTED:
                raise ValueError("Unknown reference field")
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Reference value must be non-empty or None")
        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise ValueError("Source URL is required")


@dataclass(frozen=True)
class FieldResult:
    field: str
    verdict: FieldVerdict


@dataclass(frozen=True)
class AccuracyReport:
    provenance: str
    status: AccuracyStatus
    fields: tuple[FieldResult, ...]
    compared: int
    matches: int
    mismatches: int
    missing: int
    unverified: int
    unsupported: int
    exact_match_rate: float | None
    coverage_rate: float | None

    def snapshot(self) -> dict:
        """Safe JSON output; no source HTML or gold/prediction values."""
        return {
            "provenance": self.provenance,
            "status": self.status.value,
            "counts": {
                "compared": self.compared, "matches": self.matches,
                "mismatches": self.mismatches, "missing": self.missing,
                "not_verified": self.unverified, "not_supported": self.unsupported,
            },
            "exact_match_rate": self.exact_match_rate,
            "coverage_rate": self.coverage_rate,
            "fields": {item.field: item.verdict.value for item in self.fields},
            "real_site_accuracy_verified": False,
        }


def evaluate_extraction(case: GoldCase, extracted: HtmlExtraction | None) -> AccuracyReport:
    """Compare STEP07 extraction to only fields with explicit reference truth.

    A None reference value is 'unknown', not a verified absence. Exact-match
    denominator includes all verified supported fields including missing ones.
    Coverage measures nonmissing predictions over supported verified fields.
    Unsupported fields never disappear from reporting.
    """
    if not isinstance(case, GoldCase):
        raise TypeError("A GoldCase is required")
    if extracted is not None and not isinstance(extracted, HtmlExtraction):
        raise TypeError("Expected an HtmlExtraction or None")
    predicted = extracted.raw_record if extracted is not None else {}
    if extracted is not None and predicted.get("source_url") != case.source_url:
        raise ValueError("Prediction/source URL mismatch")
    fields = []
    for field in FIELDS + NOT_SUPPORTED:
        if field in NOT_SUPPORTED:
            verdict = FieldVerdict.NOT_SUPPORTED
        elif field not in case.expected or case.expected[field] is None:
            verdict = FieldVerdict.NOT_VERIFIED
        elif predicted.get(field) is None or predicted.get(field) == "":
            verdict = FieldVerdict.MISSING
        elif str(predicted[field]).strip() == case.expected[field].strip():
            verdict = FieldVerdict.MATCH
        else:
            verdict = FieldVerdict.MISMATCH
        fields.append(FieldResult(field, verdict))
    def count(v):
        return sum(item.verdict == v for item in fields)
    matches = count(FieldVerdict.MATCH)
    mismatches = count(FieldVerdict.MISMATCH)
    missing = count(FieldVerdict.MISSING)
    compared = matches + mismatches + missing
    status = (
        AccuracyStatus.SYNTHETIC_ONLY if case.provenance == "synthetic"
        else AccuracyStatus.REAL_PARTIAL if extracted is not None and compared else AccuracyStatus.REAL_NOT_VERIFIED
    )
    return AccuracyReport(
        provenance=case.provenance, status=status, fields=tuple(fields),
        compared=compared, matches=matches, mismatches=mismatches,
        missing=missing, unverified=count(FieldVerdict.NOT_VERIFIED),
        unsupported=count(FieldVerdict.NOT_SUPPORTED),
        exact_match_rate=(matches / compared if compared else None),
        coverage_rate=((matches + mismatches) / compared if compared else None),
    )


def evaluate_html(*, case: GoldCase, html: str | None) -> AccuracyReport:
    """Caller supplies authorized HTML bytes as text; never fetches a URL.

    None means there is no usable HTML evidence yet. Malformed HTML is reported
    as missing predictions for verified fields, never an invented 100% score.
    """
    if html is None:
        extracted = None
    else:
        try:
            extracted = parse_jobkorea_html(html=html, source_url=case.source_url)
        except HtmlPostingError:
            extracted = None
    return evaluate_extraction(case, extracted)


def aggregate(reports: tuple[AccuracyReport, ...]) -> dict:
    """Micro-average only comparable fields; synthetic/real cannot be mixed."""
    if not isinstance(reports, tuple) or any(not isinstance(x, AccuracyReport) for x in reports):
        raise ValueError("Expected tuple of accuracy reports")
    kinds = {x.provenance for x in reports}
    if len(kinds) > 1:
        raise ValueError("Synthetic and real references cannot be mixed")
    matches = sum(x.matches for x in reports)
    compared = sum(x.compared for x in reports)
    nonmissing = sum(x.matches + x.mismatches for x in reports)
    return {
        "provenance": next(iter(kinds)) if kinds else None,
        "cases": len(reports),
        "verified_fields": compared,
        "matches": matches,
        "mismatches": sum(x.mismatches for x in reports),
        "missing": sum(x.missing for x in reports),
        "exact_match_rate": matches / compared if compared else None,
        "coverage_rate": nonmissing / compared if compared else None,
        "real_site_accuracy_verified": False,
    }
