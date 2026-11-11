"""T145 백그라운드 작업 공통 계약 시험.

- 같은 시나리오를 MemoryJobStore와 PostgresJobStore(일회용 DB, `T145_ADMIN_URL` 있을 때만)에 돌린다.
- 합성 작업만 사용한다. 실제 Worker·Timer·외부 요청·알림 발송 없음.
"""
import logging
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.background_jobs import (
    ALLOWED, KINDS, TERMINAL, ContractOnly, InvalidJobTransition, JobRunner, JobStatus, LeaseLost,
    MemoryJobStore, PermanentJobError, RetryableJobError, backoff_delay, current_correlation_id, new_job,
    replay_dead_letter, request_cancel, safe_correlation_id,
)

ADMIN_URL = os.environ.get("T145_ADMIN_URL")
DDL = Path(__file__).resolve().parents[2] / "database" / "proposed" / "T145_background_jobs.sql"
T0 = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
FETCH = "crawler.fixture_fetch"
NOTIFY = "notification.deliver"


class Clock:
    def __init__(self, at=T0):
        self.at = at

    def __call__(self):
        return self.at

    def advance(self, delta):
        self.at += delta


# --------------------------------------------------------------------------- 저장소 fixture
@pytest.fixture(scope="module")
def pg_database():
    if not ADMIN_URL:
        yield None
        return
    import psycopg
    name = f"t145_jobs_{secrets.token_hex(4)}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA career")
        conn.execute(DDL.read_text(encoding="utf-8"))
    yield url
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture(params=["memory", "postgres"])
def store(request, pg_database):
    if request.param == "memory":
        return MemoryJobStore()
    if pg_database is None:
        pytest.skip("T145_ADMIN_URL not set (disposable PostgreSQL only)")
    import psycopg
    from app.repositories.background_jobs_pg import PostgresJobStore
    with psycopg.connect(pg_database, autocommit=True) as conn:
        conn.execute("TRUNCATE career.background_job_history, career.background_jobs")
    return PostgresJobStore(lambda: psycopg.connect(pg_database))


def enqueue(store, key="k1", kind=FETCH, clock=None, cid=None):
    job, created = store.enqueue(new_job(kind, key, "raw-artifact-1", now=(clock or Clock())(), correlation_id=cid))
    return job, created


def runner(store, handlers, clock, worker="worker-a1"):
    return JobRunner(store, handlers, worker_id=worker, clock=clock)


def statuses(job):
    return [h.to_status.value for h in job.history]


# --------------------------------------------------------------------------- 상태 계약
def test_transition_table_terminals_and_illegal_moves():
    for status in TERMINAL - {JobStatus.DEAD_LETTER}:
        assert ALLOWED[status] == frozenset()
    assert ALLOWED[JobStatus.DEAD_LETTER] == {JobStatus.QUEUED}
    job = new_job(FETCH, "x1", "raw-1", now=T0)
    with pytest.raises(InvalidJobTransition):
        job.moved(JobStatus.SUCCEEDED, at=T0, reason="skip")
    with pytest.raises(InvalidJobTransition):
        job.moved(JobStatus.DEAD_LETTER, at=T0, reason="skip")
    running = job.moved(JobStatus.RUNNING, at=T0, reason="claimed", attempts=1)
    with pytest.raises(InvalidJobTransition):
        running.moved(JobStatus.RUNNING, at=T0, reason="again")  # lease 회수 외 running→running 금지
    done = running.moved(JobStatus.SUCCEEDED, at=T0, reason="ok")
    with pytest.raises(InvalidJobTransition):
        done.moved(JobStatus.QUEUED, at=T0, reason="reopen")


def test_contract_only_and_input_validation():
    for kind in ("llm.document_analysis", "llm.recommendation_explain"):
        assert KINDS[kind].executable is False and "T110" in KINDS[kind].source
        with pytest.raises(ContractOnly):
            new_job(kind, "a1", "doc-1", now=T0)
    with pytest.raises(ValueError):
        new_job("unknown.kind", "a1", "ref", now=T0)
    for bad in ("", "has space", "x" * 129, "키"):
        with pytest.raises(ValueError):
            new_job(FETCH, bad, "ref", now=T0)
    with pytest.raises(ValueError):
        new_job(FETCH, "ok-key", "user email@example.com body text", now=T0)
    with pytest.raises(ValueError):
        new_job(FETCH, "ok-key", "ref", now=datetime(2026, 11, 11))  # naive


def test_backoff_exponential_capped_and_deterministic():
    spec = KINDS[NOTIFY]
    job_a, job_b = uuid4(), uuid4()
    delays = [backoff_delay(job_a, n, spec) for n in range(1, 11)]
    for n, d in enumerate(delays, start=1):
        base = min(spec.backoff_cap, spec.backoff_base * 2 ** (n - 1))
        assert base <= d <= min(spec.backoff_cap, base * (1 + spec.jitter_ratio))
    assert delays[-1] == spec.backoff_cap
    assert delays == [backoff_delay(job_a, n, spec) for n in range(1, 11)]
    assert [backoff_delay(job_b, n, spec) for n in range(1, 4)] != delays[:3]
    with pytest.raises(ValueError):
        backoff_delay(job_a, 0, spec)


# --------------------------------------------------------------------------- 실행 시나리오 (메모리·PG)
def test_success_path_records_history_and_correlation(store, caplog):
    clock = Clock()
    job, created = enqueue(store, cid="req-0123456789abcdef", clock=clock)
    assert created
    seen = {}

    def handler(ctx):
        seen["cid"] = current_correlation_id()
        seen["attempts"] = ctx.job.attempts

    with caplog.at_level(logging.INFO, logger="app.background_jobs"):
        summary = runner(store, {FETCH: handler}, clock).run_once()
    assert summary.claimed == 1 and summary.succeeded == 1
    assert seen == {"cid": "req-0123456789abcdef", "attempts": 1}
    assert current_correlation_id() is None
    final = store.get(job.job_id)
    assert final.status is JobStatus.SUCCEEDED and final.lease_owner is None and final.lease_until is None
    assert statuses(final) == ["queued", "running", "succeeded"]
    assert {h.correlation_id for h in final.history} == {"req-0123456789abcdef"}
    assert final.history[1].worker_id == "worker-a1"
    assert "req-0123456789abcdef" in caplog.text and "raw-artifact-1" not in caplog.text


def test_duplicate_message_runs_handler_once(store):
    clock = Clock()
    first, created1 = enqueue(store, "dup-1", clock=clock)
    second, created2 = enqueue(store, "dup-1", clock=clock)
    assert created1 and not created2 and second.job_id == first.job_id
    _, other_kind = enqueue(store, "dup-1", kind=NOTIFY, clock=clock)
    assert other_kind  # 같은 키라도 유형이 다르면 별개
    calls = []
    r = runner(store, {FETCH: lambda ctx: calls.append(ctx.job.job_id), NOTIFY: lambda ctx: None}, clock)
    r.run_once()
    enqueue(store, "dup-1", clock=clock)  # 완료 뒤 재전송
    r.run_once()
    assert calls == [first.job_id]


def test_retry_backoff_then_dead_letter(store):
    clock = Clock()
    job, _ = enqueue(store, "retry-1", clock=clock)
    calls = []

    def flaky(ctx):
        calls.append(ctx.job.attempts)
        raise RetryableJobError("TIMEOUT")

    r = runner(store, {FETCH: flaky}, clock)
    spec = KINDS[FETCH]
    for attempt in range(1, spec.max_attempts):
        assert r.run_once().retry_scheduled == 1
        current = store.get(job.job_id)
        assert current.status is JobStatus.FAILED and current.last_error == "TIMEOUT"
        expected_due = clock() + backoff_delay(job.job_id, attempt, spec)
        assert current.next_attempt_at == expected_due
        clock.advance(expected_due - clock() - timedelta(seconds=1))
        assert r.run_once().claimed == 0          # 아직 대기 중
        clock.advance(timedelta(seconds=1))
    assert r.run_once().dead_lettered == 1
    final = store.get(job.job_id)
    assert final.status is JobStatus.DEAD_LETTER and final.attempts == spec.max_attempts
    assert calls == list(range(1, spec.max_attempts + 1))
    assert final.history[-1].reason == "attempts_exhausted"
    clock.advance(timedelta(days=1))
    assert r.run_once().claimed == 0              # dead_letter 는 자동 재시도하지 않음


@pytest.mark.parametrize("error", [PermanentJobError("VALIDATION_FAILED"), RetryableJobError("HTTP_403"),
                                   RetryableJobError("CAPTCHA"), RetryableJobError("ROBOTS_DISALLOWED")])
def test_blocking_and_permanent_errors_stop_immediately(store, error):
    clock = Clock()
    job, _ = enqueue(store, f"perm-{secrets.token_hex(3)}", clock=clock)

    def handler(ctx):
        raise error

    assert runner(store, {FETCH: handler}, clock).run_once().dead_lettered == 1
    final = store.get(job.job_id)
    assert final.status is JobStatus.DEAD_LETTER and final.attempts == 1
    assert final.history[-1].reason == "permanent_error"


def test_unknown_exception_is_retryable_without_leaking_message(store):
    clock = Clock()
    job, _ = enqueue(store, "boom-1", clock=clock)

    def handler(ctx):
        raise RuntimeError("secret token=abc user@example.com")

    runner(store, {FETCH: handler}, clock).run_once()
    final = store.get(job.job_id)
    assert final.status is JobStatus.FAILED and final.last_error == "RuntimeError"


def test_cancel_queued_running_and_terminal(store):
    clock = Clock()
    queued, _ = enqueue(store, "cancel-q", clock=clock)
    cancelled = request_cancel(store, queued.job_id, now=clock(), actor="admin-1")
    assert cancelled.status is JobStatus.CANCELLED
    assert runner(store, {FETCH: lambda ctx: None}, clock).run_once().claimed == 0

    running, _ = enqueue(store, "cancel-r", clock=clock)

    def cooperative(ctx):
        request_cancel(store, ctx.job.job_id, now=clock(), actor="admin-1")
        assert ctx.cancel_requested()
        raise RetryableJobError("ABORTED")

    assert runner(store, {FETCH: cooperative}, clock).run_once().cancelled == 1
    final = store.get(running.job_id)
    assert final.status is JobStatus.CANCELLED and final.history[-1].reason == "cancelled_during_run"

    late, _ = enqueue(store, "cancel-late", clock=clock)

    def finishes_anyway(ctx):
        request_cancel(store, ctx.job.job_id, now=clock(), actor="admin-1")

    runner(store, {FETCH: finishes_anyway}, clock).run_once()
    done = store.get(late.job_id)
    assert done.status is JobStatus.SUCCEEDED and done.history[-1].reason == "succeeded_after_cancel_request"
    assert request_cancel(store, late.job_id, now=clock(), actor="admin-1").status is JobStatus.SUCCEEDED


def test_lease_expiry_reclaim_and_fencing(store):
    clock = Clock()
    job, _ = enqueue(store, "lease-1", clock=clock)
    spec = KINDS[FETCH]
    claimed_a = store.claim(now=clock(), worker_id="worker-a1", limit=1, kinds=KINDS)  # A 가 가져가고 멈춤
    assert claimed_a[0].lease_token == 1
    clock.advance(spec.lease - timedelta(seconds=1))
    assert store.claim(now=clock(), worker_id="worker-b1", limit=1, kinds=KINDS) == []
    clock.advance(timedelta(seconds=1))
    claimed_b = store.claim(now=clock(), worker_id="worker-b1", limit=1, kinds=KINDS)
    assert claimed_b[0].attempts == 2 and claimed_b[0].lease_token == 2 and claimed_b[0].lease_owner == "worker-b1"
    assert claimed_b[0].history[-1].reason == "lease_expired_reclaimed"
    # A 의 늦은 완료 보고는 fencing 으로 거부
    late = claimed_a[0].moved(JobStatus.SUCCEEDED, at=clock(), reason="late", lease_owner=None, lease_until=None)
    with pytest.raises(LeaseLost):
        store.save(late, expected_token=claimed_a[0].lease_token)
    assert store.get(job.job_id).lease_owner == "worker-b1"


def test_runner_reports_lease_lost_instead_of_overwriting(store):
    clock = Clock()
    job, _ = enqueue(store, "lease-2", clock=clock)

    def slow(ctx):
        clock.advance(KINDS[FETCH].lease + timedelta(seconds=1))
        store.claim(now=clock(), worker_id="worker-b1", limit=1, kinds=KINDS)  # B 가 회수

    summary = runner(store, {FETCH: slow}, clock).run_once()
    assert summary.lease_lost == 1 and summary.succeeded == 0
    current = store.get(job.job_id)
    assert current.status is JobStatus.RUNNING and current.lease_owner == "worker-b1"


def test_lease_reclaim_after_last_attempt_goes_to_dead_letter(store):
    clock = Clock()
    job, _ = enqueue(store, "lease-3", clock=clock)
    for _ in range(KINDS[FETCH].max_attempts):
        assert store.claim(now=clock(), worker_id="worker-a1", limit=1, kinds=KINDS)
        clock.advance(KINDS[FETCH].lease)
    assert store.claim(now=clock(), worker_id="worker-a1", limit=1, kinds=KINDS) == []
    final = store.get(job.job_id)
    assert final.status is JobStatus.DEAD_LETTER and final.last_error == "LEASE_EXPIRED"


def test_dead_letter_replay_by_operator(store):
    clock = Clock()
    job, _ = enqueue(store, "dlq-1", clock=clock)

    def fail(ctx):
        raise PermanentJobError("VALIDATION_FAILED")

    runner(store, {FETCH: fail}, clock).run_once()
    replayed = replay_dead_letter(store, job.job_id, now=clock(), actor="admin-ops")
    assert replayed.status is JobStatus.QUEUED and replayed.attempts == 0
    assert replayed.history[-1].reason == "replayed_by:admin-ops"
    assert runner(store, {FETCH: lambda ctx: None}, clock).run_once().succeeded == 1
    assert statuses(store.get(job.job_id)) == ["queued", "running", "dead_letter", "queued", "running", "succeeded"]
    with pytest.raises(InvalidJobTransition):
        replay_dead_letter(store, job.job_id, now=clock(), actor="admin-ops")


def test_competing_workers_claim_each_job_once(store):
    clock = Clock()
    jobs = [enqueue(store, f"race-{n}", clock=clock)[0].job_id for n in range(24)]
    claimed: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker(n):
        barrier.wait()
        while True:
            got = store.claim(now=clock(), worker_id=f"worker-r{n}", limit=3, kinds=KINDS)
            if not got:
                return
            with lock:
                claimed.extend(j.job_id for j in got)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(map(str, claimed)) == sorted(map(str, jobs))
    assert len(set(claimed)) == len(claimed) == 24


def test_disabled_kind_is_never_claimed(store):
    clock = Clock()
    enqueue(store, "nohandler", kind=NOTIFY, clock=clock)
    assert runner(store, {FETCH: lambda ctx: None}, clock).run_once().claimed == 0


# --------------------------------------------------------------------------- correlation id
def test_correlation_id_follows_t112_request_id_rules():
    assert safe_correlation_id("req-0123456789abcdef") == "req-0123456789abcdef"
    for bad in (None, "", "short", "has space here", "x" * 65, "<script>alert</script>"):
        generated = safe_correlation_id(bad)
        assert generated.startswith("job-") and len(generated) == 20
    job = new_job(FETCH, "cid-1", "raw-1", now=T0, correlation_id="bad id")
    assert job.correlation_id.startswith("job-")


# --------------------------------------------------------------------------- PostgreSQL 전용
def test_pg_history_is_append_only(pg_database):
    if pg_database is None:
        pytest.skip("T145_ADMIN_URL not set (disposable PostgreSQL only)")
    import psycopg
    from app.repositories.background_jobs_pg import PostgresJobStore
    store = PostgresJobStore(lambda: psycopg.connect(pg_database))
    job, _ = store.enqueue(new_job(FETCH, f"imm-{secrets.token_hex(3)}", "raw-1", now=T0))
    with psycopg.connect(pg_database, autocommit=True) as conn:
        for sql in ("UPDATE career.background_job_history SET reason='x' WHERE job_id=%s",
                    "DELETE FROM career.background_job_history WHERE job_id=%s"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql, (job.job_id,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO career.background_jobs (job_id, kind, idempotency_key, payload_ref, status, "
                         "max_attempts, next_attempt_at, correlation_id, created_at) "
                         "VALUES (gen_random_uuid(), %s, %s, 'r', 'queued', 3, now(), 'job-x', now())",
                         (FETCH, job.idempotency_key))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE career.background_jobs SET status='running' WHERE job_id=%s", (job.job_id,))
