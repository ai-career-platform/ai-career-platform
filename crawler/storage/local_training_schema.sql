-- T62 STEP 04 - apply ONLY to a dedicated LOCAL database:
-- database: ai_career_crawler_training, role: a non-superuser training account
-- This SQL must never be applied to staging/production or the career schema.
-- The local DB and limited-privilege role must be created by the local owner.
CREATE SCHEMA IF NOT EXISTS crawler_training;

CREATE TABLE IF NOT EXISTS crawler_training.postings (
    source_code text NOT NULL,
    external_posting_id text NOT NULL,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_code, external_posting_id)
);
