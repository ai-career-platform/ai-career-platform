#!/usr/bin/env bash
set -euo pipefail

# T138: disposable test database only; NEVER execute against staging.
# Builds the real schema (0001 + T10 seed) in a throwaway postgres:18.1 container, loads the
# T137 taxonomy mock and the T138 pipeline mock, then proves: preflight blocks (loop, chain,
# missing target), dry run changes nothing, apply remaps current-state rows with the
# "keep the higher value" rule, original rows are kept in remap_log, re-running is a no-op,
# raw terms are mapped or queued, and only t138_operator can run it.
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-t138-cleanup-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=t138test \
  -e POSTGRES_PASSWORD=t138test-disposable-only \
  -e POSTGRES_DB=t138test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U t138test -d t138test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t138test -d t138test "$@"; }
for f in security/DRAFT_00_create_roles_schema.sql migrations/0001_initial_schema.sql seeds/0001_initial_seed.sql \
         tests/taxonomy/T137_code_taxonomy_mock.sql tests/taxonomy/T138_code_cleanup_pipeline_mock.sql; do
  docker cp "database/$f" "$container:/tmp/$(basename "$f")"
done
roles_sql=/tmp/DRAFT_00_create_roles_schema.sql
schema_sql=/tmp/0001_initial_schema.sql
seed_sql=/tmp/0001_initial_seed.sql
t137_sql=/tmp/T137_code_taxonomy_mock.sql
t138_sql=/tmp/T138_code_cleanup_pipeline_mock.sql

# ---- shared test body (also used by local runners that redefine psql_test and the *_sql paths)
psql_test -q -f "$roles_sql" >/dev/null
psql_test -q -c 'SET ROLE career_migrator' -f "$schema_sql" >/dev/null
psql_test -q -f "$seed_sql" >/dev/null
psql_test -q -f "$t137_sql" >/dev/null
psql_test -q -f "$t138_sql" >/dev/null
echo "PASS real schema 0001 + T10 seed + T137 mock + T138 mock loaded"

q()  { psql_test -qAtc "$1" | tr -d '\r'; }
op() { psql_test -qAtc "SET ROLE t138_operator; $1" | tr -d '\r'; }
cur(){ psql_test -qAtc "SET ROLE t137_curator; SELECT $1;" >/dev/null; }
expect_eq() {
  local label="$1" got="$2" want="$3"
  [[ "$got" == "$want" ]] || { echo "FAIL $label: got '$got' want '$want'"; exit 1; }
  echo "PASS $label"
}
expect_rejected() {
  local label="$1" sql="$2"
  if psql_test -c "$sql" >/dev/null 2>&1; then
    echo "FAIL expected rejected: $label"
    exit 1
  fi
  echo "PASS expected rejected: $label"
}
# fingerprint of every current-state table the pipeline may touch
snapshot() {
  q "SELECT md5(string_agg(x, '|' ORDER BY x)) FROM (
       SELECT 'us'  || t::text AS x FROM career.user_skills t UNION ALL
       SELECT 'jps' || t::text FROM career.job_posting_skills t UNION ALL
       SELECT 'jrs' || t::text FROM career.job_role_skills t UNION ALL
       SELECT 'ups' || t::text FROM career.user_project_skills t UNION ALL
       SELECT 'utr' || t::text FROM career.user_target_roles t UNION ALL
       SELECT 'jp'  || t::text FROM career.job_postings t UNION ALL
       SELECT 'sk'  || t::text FROM career.skills t UNION ALL
       SELECT 'jr'  || t::text FROM career.job_roles t) s"
}
uid() { echo "(SELECT user_id FROM career.users WHERE email = 'seed-user-$1@example.com')"; }
sid() { echo "(SELECT skill_id FROM career.skills WHERE code = '$1')"; }
rid() { echo "(SELECT job_role_id FROM career.job_roles WHERE code = '$1')"; }
pid() { echo "(SELECT job_posting_id FROM career.job_postings ORDER BY job_posting_id OFFSET $1 LIMIT 1)"; }
prof(){ q "SELECT coalesce(proficiency::text,'-') FROM career.user_skills WHERE user_id = $(uid "$1") AND skill_id = $(sid "$2")"; }

# ---- fixtures: a duplicate skill code GOLANG and a duplicate job role SERVER_ENGINEER arrive in career
psql_test -q >/dev/null <<SQL
INSERT INTO career.skills (code, name) VALUES ('GOLANG', 'Golang'), ('SPRING_MVC', 'Spring MVC');
INSERT INTO career.job_roles (code, name) VALUES ('SERVER_ENGINEER', '서버 엔지니어');
-- user 01: GO 2 + GOLANG 4 (duplicate) | user 02: GOLANG 3 only | user 03: GO 5 + GOLANG 1 (duplicate)
INSERT INTO career.user_skills (user_id, skill_id, proficiency) VALUES
  ($(uid 01), $(sid GO), 2), ($(uid 01), $(sid GOLANG), 4),
  ($(uid 02), $(sid GOLANG), 3),
  ($(uid 03), $(sid GO), 5), ($(uid 03), $(sid GOLANG), 1)
ON CONFLICT (user_id, skill_id) DO UPDATE SET proficiency = EXCLUDED.proficiency;
-- posting 0: GO optional lv2 + GOLANG required lv4 (duplicate) | posting 1: GOLANG only
INSERT INTO career.job_posting_skills (job_posting_id, skill_id, is_required, required_level) VALUES
  ($(pid 0), $(sid GO), false, 2), ($(pid 0), $(sid GOLANG), true, 4), ($(pid 1), $(sid GOLANG), false, 3)
ON CONFLICT (job_posting_id, skill_id) DO UPDATE SET is_required = EXCLUDED.is_required, required_level = EXCLUDED.required_level;
INSERT INTO career.job_role_skills (job_role_id, skill_id, required_level) VALUES
  ($(rid DEVOPS_ENGINEER), $(sid GO), 2), ($(rid DEVOPS_ENGINEER), $(sid GOLANG), 4)
ON CONFLICT (job_role_id, skill_id) DO UPDATE SET required_level = EXCLUDED.required_level;
INSERT INTO career.user_projects (project_id, user_id, title) VALUES
  ('00000000-0000-4000-8000-000000000138', $(uid 01), 'T138 fixture project');
INSERT INTO career.user_project_skills (project_id, skill_id) VALUES
  ('00000000-0000-4000-8000-000000000138', $(sid GO)), ('00000000-0000-4000-8000-000000000138', $(sid GOLANG));
-- user 04: SERVER_ENGINEER 1st + BACKEND_ENGINEER 2nd (duplicate) | user 05: SERVER_ENGINEER 2nd only
DELETE FROM career.user_target_roles WHERE user_id IN ($(uid 04), $(uid 05));
INSERT INTO career.user_target_roles (user_id, job_role_id, priority) VALUES
  ($(uid 04), $(rid SERVER_ENGINEER), 1), ($(uid 04), $(rid BACKEND_ENGINEER), 2),
  ($(uid 05), $(rid SERVER_ENGINEER), 2);
UPDATE career.job_postings SET job_role_id = $(rid SERVER_ENGINEER) WHERE job_posting_id = $(pid 2);
SQL
cur "taxonomy_mock.add_code('skill', 'GOLANG', 'Go 언어(중복)', 'Golang', '1.1.0', '공고 수집 중 별도 코드로 들어온 사례')"
cur "taxonomy_mock.add_code('skill', 'JIRA', '지라', 'Jira', '1.1.0', '기준선 코드 등록')"
cur "taxonomy_mock.add_code('job_role', 'SERVER_ENGINEER', '서버 엔지니어', 'Server Engineer', '1.1.0', '직무 중복 코드 등록')"
echo "PASS fixtures: duplicate codes GOLANG / SERVER_ENGINEER with overlapping rows"

# 1. preflight before any merge: nothing blocks, unknown career codes are only warnings
expect_eq "preflight has no blocking problem" "$(op "SELECT count(*) FROM taxonomy_pipeline_mock.preflight('skill') WHERE severity = 'block'")" "0"
expect_eq "career codes missing from taxonomy are warnings" \
  "$(op "SELECT count(*) > 0 FROM taxonomy_pipeline_mock.preflight('skill') WHERE check_name = 'career_code_not_in_taxonomy' AND severity = 'warn'")" "t"

# 2. curator merges GOLANG into GO and deprecates JIRA (taxonomy only; career untouched so far)
cur "taxonomy_mock.merge_code('skill', 'GOLANG', 'GO', '2.0.0', '같은 기술이라 병합')"
cur "taxonomy_mock.deprecate_code('skill', 'JIRA', '2.0.0', '도구 목록 정리로 폐기')"
cur "taxonomy_mock.merge_code('job_role', 'SERVER_ENGINEER', 'BACKEND_ENGINEER', '2.0.0', '같은 직무라 병합')"
jira_refs_before="$(q "SELECT (SELECT count(*) FROM career.job_role_skills WHERE skill_id = $(sid JIRA)) + (SELECT count(*) FROM career.job_posting_skills WHERE skill_id = $(sid JIRA)) + (SELECT count(*) FROM career.user_skills WHERE skill_id = $(sid JIRA))")"

# 3. dry run: exact counts, but no data and no log rows are kept
before="$(snapshot)"
dry="$(op "SELECT status || ' ' || (summary->>'status_synced') || ' ' || (summary->'tables'->'career.user_skills')::text FROM taxonomy_pipeline_mock.run_cleanup('skill', 'dry_run')")"
expect_eq "dry run reports the planned changes" "$dry" 'ok 2 {"remapped": 1, "conflict_merged": 2}'
expect_eq "dry run leaves career data unchanged" "$(snapshot)" "$before"
expect_eq "dry run keeps no remap_log rows" "$(q "SELECT count(*) FROM taxonomy_pipeline_mock.remap_log")" "0"
dry_summary="$(q "SELECT summary - 'warnings' FROM taxonomy_pipeline_mock.pipeline_runs WHERE mode = 'dry_run' ORDER BY run_id DESC LIMIT 1")"

# 4. apply: same counts as the dry run
op "SELECT taxonomy_pipeline_mock.run_cleanup('skill', 'apply')" >/dev/null
apply_summary="$(q "SELECT summary - 'warnings' FROM taxonomy_pipeline_mock.pipeline_runs WHERE mode = 'apply' ORDER BY run_id DESC LIMIT 1")"
expect_eq "apply matches the dry run" "$apply_summary" "$dry_summary"

# 5. duplicate rule: keep the higher value
expect_eq "user 01 GO 2 + GOLANG 4 -> GO 4" "$(prof 01 GO)" "4"
expect_eq "user 02 GOLANG 3 -> GO 3 (moved)" "$(prof 02 GO)" "3"
expect_eq "user 03 GO 5 + GOLANG 1 -> GO 5" "$(prof 03 GO)" "5"
expect_eq "posting duplicate -> required, level 4" \
  "$(q "SELECT is_required || ',' || required_level FROM career.job_posting_skills WHERE job_posting_id = $(pid 0) AND skill_id = $(sid GO)")" "true,4"
expect_eq "posting GOLANG only -> moved to GO" \
  "$(q "SELECT is_required || ',' || required_level FROM career.job_posting_skills WHERE job_posting_id = $(pid 1) AND skill_id = $(sid GO)")" "false,3"
expect_eq "job role skill duplicate -> level 4" \
  "$(q "SELECT required_level FROM career.job_role_skills WHERE job_role_id = $(rid DEVOPS_ENGINEER) AND skill_id = $(sid GO)")" "4"
expect_eq "project skill duplicate -> one GO row" \
  "$(q "SELECT string_agg(s.code, ',') FROM career.user_project_skills p JOIN career.skills s USING (skill_id) WHERE project_id = '00000000-0000-4000-8000-000000000138'")" "GO"

# 6. FK / reference check: nothing points at the merged code any more, the code row itself stays
expect_eq "no current-state row references GOLANG" \
  "$(q "SELECT (SELECT count(*) FROM career.user_skills WHERE skill_id = $(sid GOLANG)) + (SELECT count(*) FROM career.job_posting_skills WHERE skill_id = $(sid GOLANG)) + (SELECT count(*) FROM career.job_role_skills WHERE skill_id = $(sid GOLANG)) + (SELECT count(*) FROM career.user_project_skills WHERE skill_id = $(sid GOLANG))")" "0"
expect_eq "merged and deprecated codes kept, is_active=false" \
  "$(q "SELECT string_agg(code || ':' || is_active, ',' ORDER BY code) FROM career.skills WHERE code IN ('GO', 'GOLANG', 'JIRA')")" "GO:true,GOLANG:false,JIRA:false"
expect_eq "deprecated code without replacement: references untouched" \
  "$(q "SELECT (SELECT count(*) FROM career.job_role_skills WHERE skill_id = $(sid JIRA)) + (SELECT count(*) FROM career.job_posting_skills WHERE skill_id = $(sid JIRA)) + (SELECT count(*) FROM career.user_skills WHERE skill_id = $(sid JIRA))")" "$jira_refs_before"

# 7. original rows preserved in remap_log (append-only)
expect_eq "conflict log keeps both original rows (user 01: dropped 4, kept 2)" \
  "$(q "SELECT (original_row->>'proficiency') || '/' || (kept_row->>'proficiency') FROM taxonomy_pipeline_mock.remap_log WHERE table_name = 'career.user_skills' AND action = 'conflict_merged' AND original_row->>'user_id' = $(uid 01)::text")" "4/2"
expect_eq "every change has one log row" \
  "$(q "SELECT count(*) FROM taxonomy_pipeline_mock.remap_log WHERE run_id = (SELECT max(run_id) FROM taxonomy_pipeline_mock.pipeline_runs WHERE mode = 'apply')")" \
  "$(q "SELECT (summary->>'status_synced')::int + (SELECT sum((v->>'remapped')::int + (v->>'conflict_merged')::int) FROM jsonb_each(summary->'tables') e(k, v)) FROM taxonomy_pipeline_mock.pipeline_runs WHERE mode = 'apply' ORDER BY run_id DESC LIMIT 1")"
expect_eq "status sync logs the original career row" \
  "$(q "SELECT original_row->>'is_active' FROM taxonomy_pipeline_mock.remap_log WHERE action = 'status_synced' AND from_code = 'GOLANG'")" "true"

# 8. idempotency: a second apply changes nothing
after_first="$(snapshot)"
second="$(op "SELECT (summary->>'status_synced') || ' ' || (SELECT coalesce(sum((v->>'remapped')::int + (v->>'conflict_merged')::int), 0) FROM jsonb_each(summary->'tables') e(k, v)) FROM taxonomy_pipeline_mock.run_cleanup('skill', 'apply')")"
expect_eq "second apply reports 0 changes" "$second" "0 0"
expect_eq "second apply leaves data identical" "$(snapshot)" "$after_first"

# 9. job roles: user_target_roles keeps the higher priority (1 = first choice), postings move
op "SELECT taxonomy_pipeline_mock.run_cleanup('job_role', 'apply')" >/dev/null
expect_eq "user 04 SERVER 1st + BACKEND 2nd -> BACKEND 1st, one row" \
  "$(q "SELECT string_agg(r.code || ':' || t.priority, ',') FROM career.user_target_roles t JOIN career.job_roles r USING (job_role_id) WHERE t.user_id = $(uid 04)")" "BACKEND_ENGINEER:1"
expect_eq "user 05 SERVER 2nd -> BACKEND 2nd" \
  "$(q "SELECT string_agg(r.code || ':' || t.priority, ',') FROM career.user_target_roles t JOIN career.job_roles r USING (job_role_id) WHERE t.user_id = $(uid 05)")" "BACKEND_ENGINEER:2"
expect_eq "posting role moved to BACKEND_ENGINEER" \
  "$(q "SELECT r.code FROM career.job_postings p JOIN career.job_roles r USING (job_role_id) WHERE p.job_posting_id = $(pid 2)")" "BACKEND_ENGINEER"
expect_eq "job_role second apply is a no-op" \
  "$(op "SELECT (summary->>'status_synced') || ' ' || (SELECT coalesce(sum((v->>'remapped')::int + (v->>'conflict_merged')::int), 0) FROM jsonb_each(summary->'tables') e(k, v)) FROM taxonomy_pipeline_mock.run_cleanup('job_role', 'apply')")" "0 0"

# 10. preflight blocks before any change (each case runs in a transaction that is rolled back)
blocked_case() {
  local label="$1" setup="$2" want_check="$3"
  local out
  out="$(psql_test -qAt <<SQL | tr -d '\r' | tail -n 1
BEGIN;
$setup
CREATE TEMP TABLE before_snap AS SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) AS h FROM career.user_skills t;
SELECT r.status || ' ' || (r.summary->'blocked_by'->0->>'check') || ' ' ||
       ((SELECT h FROM before_snap) = (SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM career.user_skills t))
FROM taxonomy_pipeline_mock.run_cleanup('skill', 'apply') r;
ROLLBACK;
SQL
)"
  expect_eq "$label" "$out" "blocked $want_check true"
}
blocked_case "replacement loop blocks the run (owner bypassed triggers)" "
ALTER TABLE taxonomy_mock.taxonomy_codes DISABLE TRIGGER USER;
INSERT INTO taxonomy_mock.taxonomy_codes (entity_type, code, name_ko, name_en, status, replaced_by, introduced_in, deprecated_in)
VALUES ('skill', 'LOOP_A', 'a', 'Loop A', 'active', NULL, '1.0.0', NULL), ('skill', 'LOOP_B', 'b', 'Loop B', 'active', NULL, '1.0.0', NULL);
UPDATE taxonomy_mock.taxonomy_codes SET status = 'merged', deprecated_in = '2.0.0', replaced_by = CASE code WHEN 'LOOP_A' THEN 'LOOP_B' ELSE 'LOOP_A' END
WHERE code IN ('LOOP_A', 'LOOP_B');" "taxonomy_violation"
expect_eq "loop is also reported as chain_loop_or_too_deep" "$(psql_test -qAt <<'SQL' | tr -d '\r' | tail -n 1
BEGIN;
ALTER TABLE taxonomy_mock.taxonomy_codes DISABLE TRIGGER USER;
INSERT INTO taxonomy_mock.taxonomy_codes (entity_type, code, name_ko, name_en, introduced_in) VALUES ('skill', 'LOOP_A', 'a', 'Loop A', '1.0.0'), ('skill', 'LOOP_B', 'b', 'Loop B', '1.0.0');
UPDATE taxonomy_mock.taxonomy_codes SET status = 'merged', deprecated_in = '2.0.0', replaced_by = CASE code WHEN 'LOOP_A' THEN 'LOOP_B' ELSE 'LOOP_A' END WHERE code IN ('LOOP_A', 'LOOP_B');
SELECT string_agg(code, ',' ORDER BY code) FROM taxonomy_pipeline_mock.preflight('skill') WHERE check_name = 'chain_loop_or_too_deep';
ROLLBACK;
SQL
)" "LOOP_A,LOOP_B"
blocked_case "merge target missing in career blocks the run" "
SET ROLE t137_curator;
SELECT taxonomy_mock.add_code('skill', 'SPRING_MVC', '스프링 MVC', 'Spring MVC', '1.1.0', '중복 후보 코드 등록');
SELECT taxonomy_mock.merge_code('skill', 'SPRING_MVC', 'SPRING_FRAMEWORK', '2.0.0', '프레임워크로 병합');
RESET ROLE;" "target_missing_in_career"
blocked_case "merge target inactive in career blocks the run" "
UPDATE career.skills SET is_active = false WHERE code = 'GO';" "target_inactive_in_career"
blocked_case "unflattened chain (A -> B -> C) blocks until the curator re-points A" "
INSERT INTO career.skills (code, name) VALUES ('GO_LEGACY', 'Go legacy'), ('GO_LANG', 'Go lang');
SET ROLE t137_curator;
SELECT taxonomy_mock.add_code('skill', 'GO_LEGACY', 'Go 구버전', 'Go legacy', '1.1.0', '체인 테스트 코드');
SELECT taxonomy_mock.add_code('skill', 'GO_LANG', 'Go 랭', 'Go lang', '1.1.0', '체인 테스트 코드');
SELECT taxonomy_mock.merge_code('skill', 'GO_LEGACY', 'GO_LANG', '2.0.0', '체인 첫 단계');
SELECT taxonomy_mock.merge_code('skill', 'GO_LANG', 'GO', '2.0.0', '체인 두 번째 단계');
RESET ROLE;" "taxonomy_violation"

# 11. raw terms: exact hits map to a live code, ambiguous / unknown go to the review queue once
staged="$(op "SELECT string_agg(term || '=' || coalesce(canonical_code, '-') || ':' || match_type || ':' || queued, ' ' ORDER BY term COLLATE \"C\") FROM taxonomy_pipeline_mock.stage_terms('skill', 'posting:test', ARRAY['파이썬', 'Spring', 'COBOL', 'k8s', 'Golang', '  '])")"
expect_eq "stage_terms maps, follows merges and queues" "$staged" \
  "COBOL=-:not_found:true Golang=GO:code:false Spring=-:ambiguous:true k8s=KUBERNETES:alias:false 파이썬=PYTHON:alias:false"
expect_eq "ambiguous term keeps all candidates" \
  "$(q "SELECT array_to_string(candidates, ',') FROM taxonomy_pipeline_mock.term_review_queue WHERE term_norm = 'spring'")" "SPRING_BOOT,SPRING_FRAMEWORK"
op "SELECT count(*) FROM taxonomy_pipeline_mock.stage_terms('skill', 'posting:test', ARRAY['Spring', 'COBOL'])" >/dev/null
expect_eq "re-staging does not duplicate queue rows" \
  "$(q "SELECT count(*) || ' ' || sum(seen_count) FROM taxonomy_pipeline_mock.term_review_queue")" "2 4"

# 12. rejections: bad input and privilege boundaries
expect_rejected "unknown mode"                     "SET ROLE t138_operator; SELECT taxonomy_pipeline_mock.run_cleanup('skill', 'force');"
expect_rejected "unknown entity type"              "SET ROLE t138_operator; SELECT taxonomy_pipeline_mock.run_cleanup('company', 'apply');"
expect_rejected "empty source for stage_terms"     "SET ROLE t138_operator; SELECT * FROM taxonomy_pipeline_mock.stage_terms('skill', ' ', ARRAY['python']);"
expect_rejected "app role cannot run cleanup"      "SET ROLE career_app; SELECT taxonomy_pipeline_mock.run_cleanup('skill', 'apply');"
expect_rejected "reader role cannot run cleanup"   "SET ROLE career_reader; SELECT taxonomy_pipeline_mock.run_cleanup('skill', 'dry_run');"
expect_rejected "T137 reader cannot run cleanup"   "SET ROLE t137_reader; SELECT taxonomy_pipeline_mock.run_cleanup('skill', 'dry_run');"
expect_rejected "app role cannot read remap_log"   "SET ROLE career_app; SELECT count(*) FROM taxonomy_pipeline_mock.remap_log;"
expect_rejected "operator cannot call internal remap step" "SET ROLE t138_operator; SELECT taxonomy_pipeline_mock.sync_status(1, 'skill');"
expect_rejected "operator cannot edit remap_log"   "SET ROLE t138_operator; UPDATE taxonomy_pipeline_mock.remap_log SET to_code = 'X';"
expect_rejected "remap_log UPDATE (owner)"         "UPDATE taxonomy_pipeline_mock.remap_log SET to_code = 'X';"
expect_rejected "remap_log DELETE (owner)"         "DELETE FROM taxonomy_pipeline_mock.remap_log;"
expect_rejected "operator cannot change career rows directly" "SET ROLE t138_operator; UPDATE career.user_skills SET proficiency = 1;"

# 13. the taxonomy is still consistent after the run
expect_eq "T137 validate_taxonomy() reports no violations" "$(q "SELECT count(*) FROM taxonomy_mock.validate_taxonomy()")" "0"
expect_eq "no skill or job role row was deleted (100+2 skills, 30+1 roles)" \
  "$(q "SELECT count(*) FROM career.skills") $(q "SELECT count(*) FROM career.job_roles")" "102 31"

echo "T138_CODE_CLEANUP_TEST=PASS"
