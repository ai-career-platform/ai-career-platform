"""T51 document analysis: request (POST), read (GET), apply, and one-shot worker logic.

State machine (career.document_analyses.status):
    queued --claim--> running --> succeeded | failed
    queued  older than QUEUE_TTL            --> failed(TIMEOUT)   (bounded retry window)
    running older than RUNNING_TTL (crash)  --> failed(TIMEOUT)
    running --storage unavailable--> queued (retried only until QUEUE_TTL expires)
No automatic retry after failed; the user may request a new analysis.

The worker re-checks document ready/ownership and llm_processing consent both
before reading the document and again before saving the result. If either has
changed, no result is stored. GET never runs or updates an analysis.
"""
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

from pydantic import ValidationError

from app.core.errors import AppError, ErrorCode
from app.repositories.document_analyses import AnalysisRecord, AnalysisRepository, ClaimedJob
from app.repositories.my_skills import UserSkillRecord
from app.schemas.document_analyses import Analysis, AnalysisApplyItem, AnalysisResult, ModelVersionRef
from app.schemas.my_skills import MAX_SKILLS
from app.services.analysis_provider import AnalysisInput, AnalysisProvider, ProviderError, ProviderOutput
from app.services.document_storage import DocumentStorage

log = logging.getLogger(__name__)

MAX_ACTIVE_PER_USER = 5          # queued+running per user; beyond -> 429
RETRY_AFTER_SECONDS = 3
QUEUE_TTL = timedelta(minutes=30)
RUNNING_TTL = timedelta(minutes=60)
JOB_TIMEOUT_SECONDS = 30.0       # per provider call
MAX_JOBS_PER_RUN = 20            # hard cap per worker invocation (cost limit)
RUN_BUDGET_SECONDS = 300.0       # stop claiming new jobs after this


def _now() -> datetime:
    return datetime.now(UTC)


def to_dto(record: AnalysisRecord) -> Analysis:
    return Analysis(
        analysis_id=record.analysis_id, document_id=record.document_id, analysis_type=record.analysis_type,
        status=record.status, result=None if record.result is None else AnalysisResult.model_validate(record.result),
        error_code=record.error_code,
        model_version=ModelVersionRef(model_code=record.model_code, version=record.version, kind=record.kind),
        requested_at=record.requested_at, completed_at=record.completed_at)


class DocumentAnalysisService:
    def __init__(self, repo: AnalysisRepository, clock=_now):
        self.repo, self.clock = repo, clock

    def request(self, owner: UUID, document_id: UUID, analysis_type: str) -> Analysis:
        now = self.clock()
        with self.repo.transaction():
            doc = self.repo.lock_document(owner, document_id)
            if doc is None:
                raise AppError(ErrorCode.NOT_FOUND)
            if doc.status != "ready":
                raise AppError(ErrorCode.DOCUMENT_NOT_READY)
            if not self.repo.llm_consent_granted(owner, now):
                raise AppError(ErrorCode.CONSENT_REQUIRED)
            existing = self.repo.active_for_document(document_id, analysis_type)
            if existing is not None:  # duplicate request -> same pending analysis (document row is locked)
                return to_dto(existing)
            if self.repo.count_active_for_owner(owner) >= MAX_ACTIVE_PER_USER:
                raise AppError(ErrorCode.RATE_LIMITED, retry_after=30)
            version_id = self.repo.ensure_model_version()
            return to_dto(self.repo.insert(owner, document_id, analysis_type, version_id, now))

    def get(self, owner: UUID, analysis_id: UUID) -> Analysis:
        with self.repo.transaction():
            record = self.repo.get_owned(owner, analysis_id)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND)
            return to_dto(record)

    def apply(self, owner: UUID, analysis_id: UUID, items: list[AnalysisApplyItem]) -> list[UserSkillRecord]:
        wanted: dict[UUID, int] = {}
        for item in items:
            if item.skill_id in wanted:
                raise AppError(ErrorCode.DUPLICATE_SKILL)
            wanted[item.skill_id] = item.proficiency
        with self.repo.transaction():
            record = self.repo.get_owned(owner, analysis_id, lock=True)
            if record is None:
                raise AppError(ErrorCode.NOT_FOUND)
            if record.status != "succeeded":
                raise AppError(ErrorCode.CONFLICT)
            offered = {UUID(str(s["skill"]["skill_id"])) for s in (record.result or {}).get("skills") or []}
            if not set(wanted) <= offered:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="skill not offered by analysis")
            if set(wanted) - self.repo.usable_skill_ids(owner, set(wanted)):
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="retired or unknown skill")
            self.repo.upsert_user_skills(owner, wanted, self.clock())
            result = self.repo.list_user_skills(owner)
            if len(result) > MAX_SKILLS:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="skill limit exceeded")
            return result


@dataclass
class WorkerSummary:
    expired: int = 0
    succeeded: int = 0
    failed: int = 0
    requeued: int = 0
    discarded: int = 0


class AnalysisWorker:
    """One-shot batch processor. Never started by the API process."""

    def __init__(self, repo: AnalysisRepository, storage: DocumentStorage, provider: AnalysisProvider, *,
                 clock=_now, timer=monotonic, max_jobs=MAX_JOBS_PER_RUN, job_timeout=JOB_TIMEOUT_SECONDS,
                 run_budget=RUN_BUDGET_SECONDS):
        if not 1 <= max_jobs <= 100:
            raise ValueError("max_jobs must be 1..100")
        self.repo, self.storage, self.provider = repo, storage, provider
        self.clock, self.timer = clock, timer
        self.max_jobs, self.job_timeout, self.run_budget = max_jobs, job_timeout, run_budget

    def run(self) -> WorkerSummary:
        summary = WorkerSummary()
        with self.repo.transaction():
            summary.expired = self.repo.expire_stale(self.clock(), QUEUE_TTL, RUNNING_TTL)
        started = self.timer()
        for _ in range(self.max_jobs):
            if self.timer() - started > self.run_budget:
                break
            with self.repo.transaction():
                job = self.repo.claim_next()
            if job is None:
                break
            outcome = self._process(job)
            setattr(summary, outcome, getattr(summary, outcome) + 1)
            if outcome == "requeued":  # storage outage: stop; do not re-claim the same job in this run
                break
        # Counts only: no IDs, filenames, storage keys, content or provider output.
        log.info("document analysis worker: expired=%d succeeded=%d failed=%d requeued=%d discarded=%d",
                 summary.expired, summary.succeeded, summary.failed, summary.requeued, summary.discarded)
        return summary

    def _allowed(self, job: ClaimedJob):
        doc = self.repo.lock_document(job.owner_user_id, job.document_id)
        if doc is None or doc.status != "ready":
            return None, "UNREADABLE_DOCUMENT"
        if not self.repo.llm_consent_granted(job.owner_user_id, self.clock()):
            return None, None  # consent revoked: fail without result (no contract error_code; see docs)
        return doc, "OK"

    def _fail(self, job: ClaimedJob, error_code: str | None) -> str:
        with self.repo.transaction():
            stored = self.repo.finish(job.analysis_id, "failed", None, error_code, self.clock())
        return "failed" if stored else "discarded"

    def _process(self, job: ClaimedJob) -> str:
        with self.repo.transaction():
            doc, verdict = self._allowed(job)
            if doc is not None:
                key, size, checksum, mime = doc.storage_key, doc.size_bytes, doc.checksum_sha256, doc.mime_type
        if doc is None:
            return self._fail(job, verdict)
        try:
            content = self.storage.read(key)
        except AppError:
            with self.repo.transaction():  # storage outage: retry later, bounded by QUEUE_TTL
                return "requeued" if self.repo.requeue(job.analysis_id) else "discarded"
        except Exception:
            return self._fail(job, "UNREADABLE_DOCUMENT")
        if len(content) != size or hashlib.sha256(content).hexdigest() != checksum:
            return self._fail(job, "UNREADABLE_DOCUMENT")

        output, error_code = self._call_provider(AnalysisInput(job.analysis_type, mime, content))
        del content
        result = None
        if output is not None:
            try:
                result = self._build_result(output)
            except (ValidationError, ValueError):
                error_code = "PROVIDER_ERROR"
        if result is None:
            return self._fail(job, error_code or "PROVIDER_ERROR")

        with self.repo.transaction():
            doc, verdict = self._allowed(job)  # TOCTOU re-check before persisting
            if doc is None:
                stored = self.repo.finish(job.analysis_id, "failed", None, verdict, self.clock())
                return "failed" if stored else "discarded"
            stored = self.repo.finish(job.analysis_id, "succeeded", result, None, self.clock())
        return "succeeded" if stored else "discarded"

    def _call_provider(self, request: AnalysisInput) -> tuple[ProviderOutput | None, str | None]:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.provider.analyze, request)
        try:
            return future.result(timeout=self.job_timeout), None
        except FutureTimeout:
            return None, "TIMEOUT"
        except ProviderError:
            return None, "PROVIDER_ERROR"
        except Exception:
            log.warning("document analysis provider raised an unexpected error")  # no message: may echo input
            return None, "PROVIDER_ERROR"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _build_result(self, output: ProviderOutput) -> dict:
        body: dict = {}
        if output.summary is not None:
            body["summary"] = output.summary
        if output.skills is not None:
            catalog = self.repo.resolve_active_skills(sorted({c.code for c in output.skills}))
            seen: set[str] = set()
            body["skills"] = []
            for c in output.skills:  # unknown/retired catalog codes are dropped, duplicates collapsed
                if c.code in catalog and c.code not in seen:
                    seen.add(c.code)
                    body["skills"].append({"skill": catalog[c.code].model_dump(mode="json"),
                                           "suggested_proficiency": c.suggested_proficiency,
                                           "evidence": c.evidence})
        if output.experiences is not None:
            body["experiences"] = [{"organization": e.organization, "title": e.title,
                                    "start_date": None, "end_date": None} for e in output.experiences]
        return AnalysisResult.model_validate(body).model_dump(mode="json")
