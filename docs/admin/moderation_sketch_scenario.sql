-- T80 opt-in check of the PROPOSED DDL sketch (MODERATION_IMPLEMENTATION_CONTRACT.md §2.2).
-- Run only by docs/admin/test_moderation_state_model.py on a disposable *_test database, after 0001 + the sketch.
-- Synthetic rows only. Not a migration, not a seed.

INSERT INTO career.users (user_id, email, email_canonical, display_name) VALUES
  ('00000000-0000-4000-8000-0000000000a1', 'owner@example.invalid', 'owner@example.invalid', 'Synthetic owner'),
  ('00000000-0000-4000-8000-0000000000a2', 'admin@example.invalid', 'admin@example.invalid', 'Synthetic admin');
INSERT INTO career.data_sources (source_id, code, name)
  VALUES ('00000000-0000-4000-8000-0000000000b1', 'synthetic_seed', 'Synthetic');
INSERT INTO career.companies (company_id, name, source_id)
  VALUES ('00000000-0000-4000-8000-0000000000c1', 'Synthetic Co', '00000000-0000-4000-8000-0000000000b1');
INSERT INTO career.job_postings (job_posting_id, company_id, source_id, title)
  VALUES ('00000000-0000-4000-8000-0000000000d1', '00000000-0000-4000-8000-0000000000c1',
          '00000000-0000-4000-8000-0000000000b1', 'Synthetic posting');
INSERT INTO career.user_documents (document_id, owner_user_id, kind, original_filename, mime_type, size_bytes,
                                   storage_key, checksum_sha256, visibility)
  VALUES ('00000000-0000-4000-8000-0000000000e1', '00000000-0000-4000-8000-0000000000a1', 'career_guide', 'guide.pdf',
          'application/pdf', 10, repeat('a', 32), repeat('b', 64), 'shared');
INSERT INTO career.model_versions (model_version_id, model_code, version, kind)
  VALUES ('00000000-0000-4000-8000-0000000000f1', 'synthetic', '1', 'rule');
INSERT INTO career.document_analyses (analysis_id, document_id, model_version_id, analysis_type)
  VALUES ('00000000-0000-4000-8000-0000000000a9', '00000000-0000-4000-8000-0000000000e1',
          '00000000-0000-4000-8000-0000000000f1', 'summary');
INSERT INTO career.retrieval_runs (retrieval_run_id, user_id, query_hash)
  VALUES ('00000000-0000-4000-8000-0000000000c9', '00000000-0000-4000-8000-0000000000a1', repeat('c', 64));

-- 101 open + 102 decided on the posting, 103 IN_REVIEW on the shared document, 104 APPEALED on the analysis,
-- 105 REJECTED on the retrieval run
INSERT INTO career.moderation_cases (case_id, target_type, target_id, job_posting_id, review_trigger, status, priority, due_at) VALUES
  ('00000000-0000-4000-8000-000000000101', 'job_posting', '00000000-0000-4000-8000-0000000000d1',
   '00000000-0000-4000-8000-0000000000d1', 'REPORT', 'PENDING', 2, now()),
  ('00000000-0000-4000-8000-000000000102', 'job_posting', '00000000-0000-4000-8000-0000000000d1',
   '00000000-0000-4000-8000-0000000000d1', 'PRE_PUBLISH', 'APPROVED', 3, now());
INSERT INTO career.moderation_cases (case_id, target_type, target_id, document_id, review_trigger, status, priority, due_at,
                                     assignee_id, content_owner_id) VALUES
  ('00000000-0000-4000-8000-000000000103', 'shared_document', '00000000-0000-4000-8000-0000000000e1',
   '00000000-0000-4000-8000-0000000000e1', 'PRE_PUBLISH', 'IN_REVIEW', 3, now(),
   '00000000-0000-4000-8000-0000000000a2', '00000000-0000-4000-8000-0000000000a1');
INSERT INTO career.moderation_cases (case_id, target_type, target_id, analysis_id, review_trigger, status, priority, due_at,
                                     appeal_count, reason_code) VALUES
  ('00000000-0000-4000-8000-000000000104', 'document_analysis', '00000000-0000-4000-8000-0000000000a9',
   '00000000-0000-4000-8000-0000000000a9', 'REPORT', 'APPEALED', 2, now(), 1, 'INACCURATE');
INSERT INTO career.moderation_cases (case_id, target_type, target_id, retrieval_run_id, review_trigger, status, priority, due_at,
                                     reason_code) VALUES
  ('00000000-0000-4000-8000-000000000105', 'retrieval_run', '00000000-0000-4000-8000-0000000000c9',
   '00000000-0000-4000-8000-0000000000c9', 'REPORT', 'REJECTED', 2, now(), 'HARMFUL');

DO $$
BEGIN
  BEGIN  -- missing target row
    INSERT INTO career.moderation_cases (target_type, target_id, job_posting_id, review_trigger, priority, due_at)
    VALUES ('job_posting', '00000000-0000-4000-8000-00000000dead', '00000000-0000-4000-8000-00000000dead', 'EXPIRY', 2, now());
    RAISE EXCEPTION 'expected FK failure';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;
  BEGIN  -- live column of another type
    INSERT INTO career.moderation_cases (target_type, target_id, document_id, review_trigger, priority, due_at)
    VALUES ('job_posting', '00000000-0000-4000-8000-0000000000e1', '00000000-0000-4000-8000-0000000000e1', 'EXPIRY', 2, now());
    RAISE EXCEPTION 'expected type/column check failure';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN  -- snapshot only, no live reference
    INSERT INTO career.moderation_cases (target_type, target_id, review_trigger, priority, due_at)
    VALUES ('job_posting', '00000000-0000-4000-8000-0000000000d1', 'EXPIRY', 2, now());
    RAISE EXCEPTION 'expected live reference failure';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN  -- duplicate open case for the same target and trigger
    INSERT INTO career.moderation_cases (target_type, target_id, job_posting_id, review_trigger, priority, due_at)
    VALUES ('job_posting', '00000000-0000-4000-8000-0000000000d1', '00000000-0000-4000-8000-0000000000d1', 'REPORT', 2, now());
    RAISE EXCEPTION 'expected unique failure';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  BEGIN  -- the snapshot cannot be re-pointed
    UPDATE career.moderation_cases SET target_id = gen_random_uuid() WHERE case_id = '00000000-0000-4000-8000-000000000101';
    RAISE EXCEPTION 'expected immutable snapshot failure';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN  -- APPEALED requires appeal_count = 1 (counted at submission)
    UPDATE career.moderation_cases SET appeal_count = 0 WHERE case_id = '00000000-0000-4000-8000-000000000104';
    RAISE EXCEPTION 'expected appeal_count check failure';
  EXCEPTION WHEN check_violation THEN NULL; END;
END $$;

-- service path: lock target, close the open case with an actor, then delete the target
BEGIN;
SELECT 1 FROM career.job_postings WHERE job_posting_id = '00000000-0000-4000-8000-0000000000d1' FOR UPDATE;
SELECT 1 FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000101' FOR UPDATE;
UPDATE career.moderation_cases SET status = 'CLOSED', close_reason = 'TARGET_DELETED', version = version + 1
 WHERE case_id = '00000000-0000-4000-8000-000000000101';
INSERT INTO career.moderation_case_events (case_id, from_status, to_status, event, actor_user_id, reason_code)
VALUES ('00000000-0000-4000-8000-000000000101', 'PENDING', 'CLOSED', 'CLOSE', '00000000-0000-4000-8000-0000000000a2', 'TARGET_DELETED');
DELETE FROM career.job_postings WHERE job_posting_id = '00000000-0000-4000-8000-0000000000d1';
COMMIT;

-- cascade path: account deletion removes the shared document, its analysis (two levels) and the retrieval run
DELETE FROM career.users WHERE user_id = '00000000-0000-4000-8000-0000000000a1';

DO $$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000101';
  ASSERT r.status = 'CLOSED' AND r.job_posting_id IS NULL AND r.target_id = '00000000-0000-4000-8000-0000000000d1', 'service path';
  ASSERT (SELECT count(*) FROM career.moderation_case_events WHERE case_id = r.case_id) = 1, 'no duplicate event';
  SELECT * INTO r FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000102';
  ASSERT r.status = 'APPROVED' AND r.job_posting_id IS NULL AND r.target_id = '00000000-0000-4000-8000-0000000000d1',
         'decided APPROVED case kept';
  SELECT * INTO r FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000103';
  ASSERT r.status = 'CLOSED' AND r.close_reason = 'TARGET_DELETED' AND r.assignee_id IS NULL AND r.version = 2
     AND r.document_id IS NULL AND r.content_owner_id IS NULL AND r.target_id = '00000000-0000-4000-8000-0000000000e1',
         'cascade closed IN_REVIEW';
  SELECT * INTO r FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000104';
  ASSERT r.status = 'CLOSED' AND r.analysis_id IS NULL AND r.appeal_count = 1, 'cascade closed APPEALED';
  SELECT * INTO r FROM career.moderation_cases WHERE case_id = '00000000-0000-4000-8000-000000000105';
  ASSERT r.status = 'REJECTED' AND r.retrieval_run_id IS NULL AND r.target_id = '00000000-0000-4000-8000-0000000000c9',
         'decided REJECTED case kept';
  ASSERT (SELECT count(*) FROM career.moderation_case_events
          WHERE event = 'CLOSE' AND reason_code = 'TARGET_DELETED' AND actor_user_id IS NULL) = 2,
         'system events for the two cascaded open cases';
  ASSERT (SELECT count(*) FROM career.moderation_cases) = 5, 'history preserved';
END $$;
SELECT 'T80_SKETCH_PG=PASS';
