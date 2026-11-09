-- T153: manual-only parser lineage migration; do not run at startup.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Isolated crawler training database required';
 END IF;
 IF to_regclass('crawler_training.raw_artifacts') IS NULL
    OR to_regclass('crawler_training.postings') IS NULL THEN
  RAISE EXCEPTION 'Apply previous crawler migrations first';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.raw_parse_results (
 parse_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 artifact_id uuid NOT NULL REFERENCES crawler_training.raw_artifacts(artifact_id),
 parser_version text NOT NULL CHECK (length(parser_version) BETWEEN 1 AND 100),
 validation_status text NOT NULL CHECK (validation_status IN ('VALID','INVALID')),
 error_code text,
 source_code text,
 external_posting_id text,
 write_result text CHECK (write_result IN ('inserted','updated','unchanged')),
 parsed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(artifact_id,parser_version),
 FOREIGN KEY (source_code,external_posting_id)
  REFERENCES crawler_training.postings(source_code,external_posting_id),
 CHECK (
  (validation_status='INVALID' AND error_code IS NOT NULL
   AND source_code IS NULL AND external_posting_id IS NULL AND write_result IS NULL)
  OR
  (validation_status='VALID' AND error_code IS NULL
   AND source_code IS NOT NULL AND external_posting_id IS NOT NULL AND write_result IS NOT NULL)
 )
);
CREATE INDEX IF NOT EXISTS t153_raw_parse_posting_idx
 ON crawler_training.raw_parse_results(source_code,external_posting_id);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.raw_parse_results TO crawler_staging;
  GRANT USAGE,SELECT ON SEQUENCE crawler_training.raw_parse_results_parse_id_seq TO crawler_staging;
 END IF;
END $$;
COMMIT;
