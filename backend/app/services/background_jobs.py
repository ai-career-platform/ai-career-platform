"""T145 백그라운드 작업 공통 계약 (PROPOSED, 실행기·Timer 미연결).

수집(T64)·알림(T96)·LLM(T110) 비동기 작업이 같은 규칙을 따르게 하는 작은 라이브러리다.
- 기존 T64 `crawler/jobs/run_state.py`(불변 상태 전이), `run_claims.py`(중복 실행 방지),
  `offline_recovery.py`(재시도 판단)와 T96 `notifications.py`(outbox·lease·backoff·dedupe)의 규칙을 일반화했다.
  기존 모듈은 바꾸지 않는다.
- T112 `request_id`와 같은 형식의 correlation id를 작업에 실어 로그·이력에 남긴다.
- **T110(LLM 비동기)은 NOT_STARTED**라서 `llm.*` 유형은 계약만 있고 enqueue를 거부한다.
- 어떤 Worker·Timer도 켜지 않는다. 저장 표는 `database/proposed/T145_background_jobs.sql`(정식 migration 아님).

상태
    queued ─claim→ running ─ok→ succeeded
      │               ├─retryable error, attempts < max→ failed ─(due)claim→ running
      │               ├─permanent error 또는 attempts ≥ max→ dead_letter ─(운영자 replay)→ queued
      │               └─cancel 요청 반영→ cancelled
      └─cancel→ cancelled                      failed ─cancel→ cancelled
lease가 만료된 running은 다른 Worker가 회수한다. 회수 시 이미 시도 횟수를 다 썼으면 dead_letter.
매 claim마다 fencing token(lease_token)이 바뀌므로, lease를 잃은 옛 Worker의 완료 보고는 거부된다.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol
from uuid import UUID, uuid4

logger = logging.getLogger("app.background_jobs")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")          # T112 request_id 와 같은 형식
_SAFE_KEY = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_correlation: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_correlation_id", default=None)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"            # 재시도 대기
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.CANCELLED, JobStatus.DEAD_LETTER})
ALLOWED: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    # running→running 은 lease 만료 회수 전용(_claim_one). fencing token이 함께 바뀐다.
    JobStatus.RUNNING: frozenset({JobStatus.RUNNING, JobStatus.SUCCEEDED, JobStatus.FAILED,
                                  JobStatus.DEAD_LETTER, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.DEAD_LETTER}),
    JobStatus.DEAD_LETTER: frozenset({JobStatus.QUEUED}),      # 운영자 replay만
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


class InvalidJobTransition(ValueError):
    pass


class ContractOnly(RuntimeError):
    """계약만 있고 실행이 승인되지 않은 작업 유형."""


class LeaseLost(RuntimeError):
    """lease가 만료되어 다른 Worker가 가져갔거나 fencing token이 다름."""


class RetryableJobError(Exception):
    def __init__(self, code: str = "RETRYABLE"):
        super().__init__(code)
        self.code = code


class PermanentJobError(Exception):
    def __init__(self, code: str = "PERMANENT"):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- 유형별 정책

@dataclass(frozen=True)
class JobKindSpec:
    kind: str
    max_attempts: int
    backoff_base: timedelta
    backoff_cap: timedelta
    jitter_ratio: float           # 0 ≤ r < 1. 지연에 [0, r) 비율을 더한다
    lease: timedelta
    executable: bool               # False 면 enqueue 거부(계약만)
    source: str                    # 근거 일감

    def __post_init__(self):
        if not (1 <= self.max_attempts <= 10):
            raise ValueError("max_attempts must be 1..10")
        if self.backoff_base <= timedelta(0) or self.backoff_cap < self.backoff_base:
            raise ValueError("invalid backoff")
        if not (0 <= self.jitter_ratio < 1):
            raise ValueError("jitter_ratio must be in [0, 1)")
        if self.lease <= timedelta(0):
            raise ValueError("lease must be positive")


_S, _M, _H = timedelta(seconds=1), timedelta(minutes=1), timedelta(hours=1)
KINDS: Mapping[str, JobKindSpec] = {s.kind: s for s in (
    # T64 offline_recovery: 일시 오류 최대 3회. 403/429/CAPTCHA/robots 는 영구 오류로 즉시 중단.
    JobKindSpec("crawler.fixture_fetch", 3, 30 * _S, 10 * _M, 0.2, 10 * _M, True, "T64/T154"),
    # T96 BACKOFF(1m,5m,30m,2h,6h)·LEASE 5m, 유형별 max_attempts 2..5 → 공통 상한 5
    JobKindSpec("notification.deliver", 5, 1 * _M, 6 * _H, 0.1, 5 * _M, True, "T96"),
    JobKindSpec("crawler.parse_raw", 3, 30 * _S, 10 * _M, 0.2, 10 * _M, True, "T153"),
    # T110 NOT_STARTED: 계약만
    JobKindSpec("llm.document_analysis", 3, 1 * _M, 1 * _H, 0.2, 15 * _M, False, "T110 (NOT_STARTED)"),
    JobKindSpec("llm.recommendation_explain", 3, 1 * _M, 1 * _H, 0.2, 15 * _M, False, "T110 (NOT_STARTED)"),
)}

# 재시도해도 소용없는 오류: 즉시 dead_letter (T61/T154 차단 신호 포함)
PERMANENT_CODES = frozenset({"HTTP_403", "HTTP_429_BLOCKED", "CAPTCHA", "ROBOTS_DISALLOWED",
                             "VALIDATION_FAILED", "CONSENT_WITHDRAWN", "PERMANENT"})


def backoff_delay(job_id: UUID, attempt: int, spec: JobKindSpec) -> timedelta:
    """attempt(1부터) 실패 뒤 대기 시간. 지수 증가 + 상한 + job_id·attempt로 정해지는 결정적 지터.

    같은 job·attempt면 항상 같은 값이라 재현·시험이 가능하고, 서로 다른 job은 흩어진다.
    """
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    base = min(spec.backoff_cap, spec.backoff_base * (2 ** (attempt - 1)))
    digest = hashlib.sha256(f"{job_id}:{attempt}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2 ** 64          # [0, 1)
    return min(spec.backoff_cap, base + base * spec.jitter_ratio * fraction)


# ---------------------------------------------------------------- correlation id

def new_correlation_id() -> str:
    return f"job-{secrets.token_hex(8)}"


def safe_correlation_id(value: str | None) -> str:
    """요청에서 받은 request_id가 안전한 형식이면 그대로 이어 쓰고, 아니면 새로 만든다(T112 규칙)."""
    return value if isinstance(value, str) and _SAFE_ID.match(value) else new_correlation_id()


def current_correlation_id() -> str | None:
    return _correlation.get()


# ---------------------------------------------------------------- 작업·이력

@dataclass(frozen=True)
class HistoryEntry:
    at: datetime
    from_status: JobStatus | None
    to_status: JobStatus
    reason: str
    worker_id: str | None
    correlation_id: str
    attempt: int


@dataclass(frozen=True)
class Job:
    job_id: UUID
    kind: str
    idempotency_key: str
    payload_ref: str                # 원문·비밀이 아닌 참조(예: raw artifact id). 개인정보·토큰 저장 금지
    status: JobStatus
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    correlation_id: str
    created_at: datetime
    lease_owner: str | None = None
    lease_until: datetime | None = None
    lease_token: int = 0
    cancel_requested: bool = False
    last_error: str | None = None
    history: tuple[HistoryEntry, ...] = field(default_factory=tuple)

    def moved(self, to: JobStatus, *, at: datetime, reason: str, worker_id: str | None = None,
              **changes) -> Job:
        if to not in ALLOWED[self.status] or (
                to is self.status and not reason.startswith("lease_expired")):
            raise InvalidJobTransition(f"{self.status.value} -> {to.value}")
        entry = HistoryEntry(at, self.status, to, reason, worker_id, self.correlation_id,
                             changes.get("attempts", self.attempts))
        return replace(self, status=to, history=self.history + (entry,), **changes)


def _utc(at: datetime) -> datetime:
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return at.astimezone(UTC)


def new_job(kind: str, idempotency_key: str, payload_ref: str, *, now: datetime,
            correlation_id: str | None = None, kinds: Mapping[str, JobKindSpec] = KINDS) -> Job:
    spec = kinds.get(kind)
    if spec is None:
        raise ValueError("unknown job kind")
    if not spec.executable:
        raise ContractOnly(kind)
    if not _SAFE_KEY.match(idempotency_key or ""):
        raise ValueError("invalid idempotency key")
    if not _SAFE_KEY.match(payload_ref or ""):
        raise ValueError("payload_ref must be a short reference, not content")
    now = _utc(now)
    cid = safe_correlation_id(correlation_id or current_correlation_id())
    entry = HistoryEntry(now, None, JobStatus.QUEUED, "enqueued", None, cid, 0)
    return Job(uuid4(), kind, idempotency_key, payload_ref, JobStatus.QUEUED, 0, spec.max_attempts,
               now, cid, now, history=(entry,))


# ---------------------------------------------------------------- 저장소 계약

class JobStore(Protocol):
    def enqueue(self, job: Job) -> tuple[Job, bool]:
        """(kind, idempotency_key)가 같으면 기존 작업을 돌려주고 False."""
        ...
    def claim(self, *, now: datetime, worker_id: str, limit: int,
              kinds: Mapping[str, JobKindSpec]) -> list[Job]: ...
    def get(self, job_id: UUID) -> Job | None: ...
    def save(self, job: Job, *, expected_token: int | None) -> None:
        """fencing: expected_token이 현재 lease_token과 다르면 LeaseLost."""
        ...


def _claim_one(job: Job, *, now: datetime, worker_id: str, spec: JobKindSpec) -> Job | None:
    """claim 대상 판정 + 전이. None이면 건너뜀(또는 저장소가 dead_letter로 저장)."""
    if job.status is JobStatus.RUNNING:   # lease 만료 회수
        if job.lease_until is None or job.lease_until > now:
            return None
        if job.attempts >= job.max_attempts:
            return job.moved(JobStatus.DEAD_LETTER, at=now, reason="lease_expired_attempts_exhausted",
                             worker_id=worker_id, lease_owner=None, lease_until=None,
                             last_error="LEASE_EXPIRED")
        return job.moved(JobStatus.RUNNING, at=now, reason="lease_expired_reclaimed", worker_id=worker_id,
                               attempts=job.attempts + 1, lease_owner=worker_id, lease_until=now + spec.lease,
                               lease_token=job.lease_token + 1, last_error="LEASE_EXPIRED")
    if job.status not in (JobStatus.QUEUED, JobStatus.FAILED) or job.next_attempt_at > now:
        return None
    if job.cancel_requested:
        return job.moved(JobStatus.CANCELLED, at=now, reason="cancelled_before_run", worker_id=worker_id)
    return job.moved(JobStatus.RUNNING, at=now, reason="claimed", worker_id=worker_id,
                     attempts=job.attempts + 1, lease_owner=worker_id, lease_until=now + spec.lease,
                     lease_token=job.lease_token + 1)


class MemoryJobStore:
    """단일 프로세스 시험용. claim은 잠금 하나로 원자적이다."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._jobs: dict[UUID, Job] = {}
        self._keys: dict[tuple[str, str], UUID] = {}

    def enqueue(self, job: Job) -> tuple[Job, bool]:
        with self._lock:
            existing = self._keys.get((job.kind, job.idempotency_key))
            if existing is not None:
                return self._jobs[existing], False
            self._jobs[job.job_id] = job
            self._keys[(job.kind, job.idempotency_key)] = job.job_id
            return job, True

    def claim(self, *, now, worker_id, limit, kinds=KINDS):
        now = _utc(now)
        out: list[Job] = []
        with self._lock:
            for job in sorted(self._jobs.values(), key=lambda j: (j.next_attempt_at, str(j.job_id))):
                if len(out) >= limit:
                    break
                spec = kinds.get(job.kind)
                if spec is None or not spec.executable:
                    continue
                moved = _claim_one(job, now=now, worker_id=worker_id, spec=spec)
                if moved is None:
                    continue
                self._jobs[job.job_id] = moved
                if moved.status is JobStatus.RUNNING:
                    out.append(moved)
        return out

    def get(self, job_id):
        return self._jobs.get(job_id)

    def save(self, job, *, expected_token):
        with self._lock:
            current = self._jobs.get(job.job_id)
            if current is None:
                raise KeyError(job.job_id)
            if expected_token is not None and current.lease_token != expected_token:
                raise LeaseLost(str(job.job_id))
            self._jobs[job.job_id] = job

    def all(self) -> list[Job]:
        return list(self._jobs.values())


# ---------------------------------------------------------------- 실행

@dataclass
class JobContext:
    job: Job
    store: JobStore

    def cancel_requested(self) -> bool:
        current = self.store.get(self.job.job_id)
        return bool(current and current.cancel_requested)


Handler = Callable[[JobContext], None]


@dataclass
class RunSummary:
    claimed: int = 0
    succeeded: int = 0
    retry_scheduled: int = 0
    dead_lettered: int = 0
    cancelled: int = 0
    lease_lost: int = 0


class JobRunner:
    """claim → handler → 결과 반영. 시계·저장소·handler를 주입한다(실행기·Timer 아님)."""

    def __init__(self, store: JobStore, handlers: Mapping[str, Handler], *, worker_id: str,
                 clock: Callable[[], datetime], kinds: Mapping[str, JobKindSpec] = KINDS) -> None:
        if not _SAFE_ID.match(worker_id):
            raise ValueError("invalid worker_id")
        self.store, self.handlers, self.worker_id, self.clock, self.kinds = store, handlers, worker_id, clock, kinds

    def run_once(self, limit: int = 10) -> RunSummary:
        summary = RunSummary()
        executable = {k: s for k, s in self.kinds.items() if s.executable and k in self.handlers}
        for job in self.store.claim(now=self.clock(), worker_id=self.worker_id, limit=limit, kinds=executable):
            summary.claimed += 1
            self._run(job, summary)
        return summary

    def _run(self, job: Job, summary: RunSummary) -> None:
        token = _correlation.set(job.correlation_id)
        try:
            outcome, code = "ok", None
            try:
                self.handlers[job.kind](JobContext(job, self.store))
            except PermanentJobError as exc:
                outcome, code = "permanent", exc.code
            except RetryableJobError as exc:
                outcome, code = ("permanent" if exc.code in PERMANENT_CODES else "retry"), exc.code
            except Exception as exc:  # noqa: BLE001 - 알 수 없는 오류는 재시도 대상
                outcome, code = "retry", type(exc).__name__
            self._finish(job, outcome, code, summary)
        finally:
            _correlation.reset(token)

    def _finish(self, job: Job, outcome: str, code: str | None, summary: RunSummary) -> None:
        now = _utc(self.clock())
        current = self.store.get(job.job_id)
        if current is None or current.lease_token != job.lease_token or current.status is not JobStatus.RUNNING:
            summary.lease_lost += 1
            logger.warning("job_lease_lost job_id=%s kind=%s correlation_id=%s", job.job_id, job.kind,
                           job.correlation_id)
            return
        spec = self.kinds[job.kind]
        clear = dict(lease_owner=None, lease_until=None)
        if outcome == "ok":
            reason = "succeeded_after_cancel_request" if current.cancel_requested else "succeeded"
            new = current.moved(JobStatus.SUCCEEDED, at=now, reason=reason, worker_id=self.worker_id,
                                last_error=None, **clear)
            summary.succeeded += 1
        elif current.cancel_requested:
            new = current.moved(JobStatus.CANCELLED, at=now, reason="cancelled_during_run",
                                worker_id=self.worker_id, last_error=code, **clear)
            summary.cancelled += 1
        elif outcome == "permanent" or current.attempts >= current.max_attempts:
            reason = "permanent_error" if outcome == "permanent" else "attempts_exhausted"
            new = current.moved(JobStatus.DEAD_LETTER, at=now, reason=reason, worker_id=self.worker_id,
                                last_error=code, **clear)
            summary.dead_lettered += 1
        else:
            delay = backoff_delay(current.job_id, current.attempts, spec)
            new = current.moved(JobStatus.FAILED, at=now, reason="retry_scheduled", worker_id=self.worker_id,
                                last_error=code, next_attempt_at=now + delay, **clear)
            summary.retry_scheduled += 1
        try:
            self.store.save(new, expected_token=job.lease_token)
        except LeaseLost:
            summary.lease_lost += 1
            return
        logger.info("job_finished job_id=%s kind=%s status=%s attempt=%s correlation_id=%s",
                    new.job_id, new.kind, new.status.value, new.attempts, new.correlation_id)


# ---------------------------------------------------------------- 운영 명령

def request_cancel(store: JobStore, job_id: UUID, *, now: datetime, actor: str) -> Job:
    """queued/failed는 즉시 cancelled, running은 표시만(handler가 확인하거나 끝날 때 반영). 종료 상태는 그대로."""
    job = store.get(job_id)
    if job is None:
        raise KeyError(job_id)
    now = _utc(now)
    if job.status in (JobStatus.QUEUED, JobStatus.FAILED):
        new = job.moved(JobStatus.CANCELLED, at=now, reason=f"cancelled_by:{actor}", cancel_requested=True)
        store.save(new, expected_token=None)
        return new
    if job.status is JobStatus.RUNNING and not job.cancel_requested:
        new = replace(job, cancel_requested=True)
        store.save(new, expected_token=job.lease_token)
        return new
    return job


def replay_dead_letter(store: JobStore, job_id: UUID, *, now: datetime, actor: str) -> Job:
    """운영자 재처리: dead_letter → queued, 시도 횟수 초기화. 이력에 행위자를 남긴다."""
    job = store.get(job_id)
    if job is None:
        raise KeyError(job_id)
    now = _utc(now)
    new = job.moved(JobStatus.QUEUED, at=now, reason=f"replayed_by:{actor}", attempts=0, next_attempt_at=now,
                    cancel_requested=False, last_error=None)
    store.save(new, expected_token=None)
    return new
