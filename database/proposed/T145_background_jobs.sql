-- PROPOSED (T145) — NOT a migration. database/migrate.py does not read this folder.
-- Common background job table + append-only state history. Applied only to disposable test databases.
-- Generalises T96 career.notification_deliveries (outbox, lease, attempts) and T64 run claims.

CREATE TABLE IF NOT EXISTS career.background_jobs (
    job_id uuid PRIMARY KEY,
    kind varchar(64) NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    payload_ref varchar(128) NOT NULL,              -- reference only; never raw content, secrets or personal data
    status varchar(20) NOT NULL,
    attempts smallint NOT NULL DEFAULT 0,
    max_attempts smallint NOT NULL,
    next_attempt_at timestamptz NOT NULL,
    correlation_id varchar(64) NOT NULL,
    created_at timestamptz NOT NULL,
    lease_owner varchar(64),
    lease_until timestamptz,
    lease_token bigint NOT NULL DEFAULT 0,          -- fencing token, +1 on every claim
    cancel_requested boolean NOT NULL DEFAULT false,
    last_error varchar(64),
    CONSTRAINT background_jobs_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'dead_letter')),
    CONSTRAINT background_jobs_attempts CHECK (attempts BETWEEN 0 AND max_attempts AND max_attempts BETWEEN 1 AND 10),
    CONSTRAINT background_jobs_lease CHECK ((status = 'running') = (lease_until IS NOT NULL AND lease_owner IS NOT NULL)),
    CONSTRAINT background_jobs_idempotency UNIQUE (kind, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_background_jobs_due
    ON career.background_jobs (next_attempt_at) WHERE status IN ('queued', 'failed');
CREATE INDEX IF NOT EXISTS ix_background_jobs_lease
    ON career.background_jobs (lease_until) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS ix_background_jobs_dead_letter
    ON career.background_jobs (kind, created_at) WHERE status = 'dead_letter';

CREATE TABLE IF NOT EXISTS career.background_job_history (
    job_id uuid NOT NULL REFERENCES career.background_jobs (job_id) ON DELETE CASCADE,
    seq integer NOT NULL,
    at timestamptz NOT NULL,
    from_status varchar(20),
    to_status varchar(20) NOT NULL,
    reason varchar(80) NOT NULL,
    worker_id varchar(64),
    correlation_id varchar(64) NOT NULL,
    attempt smallint NOT NULL,
    PRIMARY KEY (job_id, seq)
);

-- history is append-only
CREATE OR REPLACE FUNCTION career.background_job_history_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'background_job_history is append-only' USING ERRCODE = '42501';
END $$;

DROP TRIGGER IF EXISTS trg_background_job_history_immutable ON career.background_job_history;
CREATE TRIGGER trg_background_job_history_immutable BEFORE UPDATE OR DELETE ON career.background_job_history
    FOR EACH ROW EXECUTE FUNCTION career.background_job_history_immutable();
