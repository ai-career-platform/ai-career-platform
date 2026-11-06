#!/usr/bin/env bash
set -euo pipefail

# T83: disposable test database only; NEVER execute against staging.
# Loads database/tests/audit/T83_audit_events_mock.sql into a throwaway postgres:18.1
# container and proves the audit contract: normal write, append-only, privilege
# boundaries, forbidden content, retention purge and tamper detection.
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-t83-audit-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=t83test \
  -e POSTGRES_PASSWORD=t83test-disposable-only \
  -e POSTGRES_DB=t83test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U t83test -d t83test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t83test -d t83test "$@"; }
docker cp database/tests/audit/T83_audit_events_mock.sql "$container:/tmp/audit_mock.sql"
mock_sql=/tmp/audit_mock.sql

# ---- shared test body (also used by local runners that redefine psql_test/mock_sql)
psql_test -f "$mock_sql" >/dev/null
echo "PASS mock schema loaded"

as_writer() { psql_test -qAtc "SET ROLE t83_audit_writer; $1"; }
as_reader() { psql_test -qAtc "SET ROLE t83_audit_reader; $1"; }
expect_rejected() {
  local label="$1"
  local sql="$2"
  if psql_test -c "$sql" >/dev/null 2>&1; then
    echo "FAIL expected rejected: $label"
    exit 1
  fi
  echo "PASS expected rejected: $label"
}

base_cols="occurred_at, actor_type, actor_user_id, action_code, resource_type, resource_id, result, reason_code, request_id, changed_fields, metadata, retention_class"
uid="11111111-1111-4111-8111-111111111111"
uid2="33333333-3333-4333-8333-333333333333"
psql_test -c "INSERT INTO audit_mock.users VALUES ('$uid'), ('$uid2')" >/dev/null
rid="22222222-2222-4222-8222-222222222222"

# 1. normal writes by the application role
as_writer "INSERT INTO audit_mock.audit_events ($base_cols) VALUES
  (now(), 'user', '$uid', 'user.profile.update', 'user_profile', '$uid', 'success', NULL, 'req-t83-0001', ARRAY['headline','bio'], '{\"source\":\"web\"}', 'standard'),
  (now(), 'admin', '$uid', 'admin.posting.close', 'job_posting', '$rid', 'denied', 'NOT_AUTHORIZED', 'req-t83-0002', NULL, NULL, 'security'),
  (now(), 'ai_agent', NULL, 'agent.tool.call', 'agent_run', '$rid', 'failed', 'TOOL_TIMEOUT', 'req-t83-0003', NULL, '{\"tool_code\":\"job_search\",\"latency_ms\":3000}', 'ai_agent');" >/dev/null
rows="$(psql_test -Atc "SELECT count(*) FROM audit_mock.audit_events")"
[[ "$rows" == "3" ]] || { echo "FAIL normal insert rows=$rows"; exit 1; }
echo "PASS normal insert by writer (3 rows: success/denied/failed)"

forced="$(psql_test -Atc "SELECT bool_and(row_hash = audit_mock.compute_row_hash(e) AND retain_until > recorded_at) FROM audit_mock.audit_events e")"
[[ "$forced" == "t" ]] || { echo "FAIL row_hash/retain_until not set by trigger"; exit 1; }
echo "PASS DB-owned fields set (row_hash, retain_until)"

spoof="$(as_writer "INSERT INTO audit_mock.audit_events ($base_cols, recorded_at, retain_until, row_hash) VALUES
  (now(), 'system', NULL, 'system.seed.apply', 'seed', NULL, 'success', NULL, 'req-t83-0004', NULL, NULL, 'standard',
   '2000-01-01', '2000-01-02', repeat('0', 64));" && psql_test -Atc "SELECT recorded_at > '2020-01-01' AND retain_until > now() AND row_hash <> repeat('0',64) FROM audit_mock.audit_events WHERE request_id = 'req-t83-0004'")"
[[ "$spoof" == *t ]] || { echo "FAIL client could spoof recorded_at/retain_until/row_hash"; exit 1; }
echo "PASS client-supplied recorded_at/retain_until/row_hash ignored"

# 2. append-only and privilege boundaries
expect_rejected "writer UPDATE" "SET ROLE t83_audit_writer; UPDATE audit_mock.audit_events SET result = 'success';"
expect_rejected "writer DELETE" "SET ROLE t83_audit_writer; DELETE FROM audit_mock.audit_events;"
expect_rejected "writer DELETE with purge flag set" "SET ROLE t83_audit_writer; SET audit_mock.purge_in_progress = 'on'; DELETE FROM audit_mock.audit_events;"
expect_rejected "writer SELECT" "SET ROLE t83_audit_writer; SELECT count(*) FROM audit_mock.audit_events;"
expect_rejected "writer purge_expired()" "SET ROLE t83_audit_writer; SELECT audit_mock.purge_expired();"
expect_rejected "reader INSERT" "SET ROLE t83_audit_reader; INSERT INTO audit_mock.audit_events ($base_cols) VALUES (now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0100', NULL, NULL, 'standard');"
expect_rejected "owner UPDATE (trigger)" "UPDATE audit_mock.audit_events SET result = 'success' WHERE result = 'denied';"
expect_rejected "owner DELETE unexpired (trigger)" "DELETE FROM audit_mock.audit_events;"
expect_rejected "owner TRUNCATE (trigger)" "TRUNCATE audit_mock.audit_events;"
read_rows="$(as_reader "SELECT count(*) FROM audit_mock.audit_events")"
[[ "$read_rows" == "4" ]] || { echo "FAIL reader SELECT rows=$read_rows"; exit 1; }
echo "PASS reader SELECT allowed (4 rows)"

# 3. forbidden content and format rules
ins() { echo "SET ROLE t83_audit_writer; INSERT INTO audit_mock.audit_events ($base_cols) VALUES ($1);"; }
expect_rejected "metadata key password" "$(ins "now(), 'system', NULL, 'auth.login.attempt', 'user', NULL, 'failed', 'BAD_CREDENTIAL', 'req-t83-0201', NULL, '{\"password\":\"x\"}', 'security'")"
expect_rejected "nested metadata key access_token" "$(ins "now(), 'system', NULL, 'auth.token.issue', 'user', NULL, 'success', NULL, 'req-t83-0202', NULL, '{\"detail\":{\"items\":[{\"access_token\":\"x\"}]}}', 'security'")"
expect_rejected "metadata key prompt (raw LLM text)" "$(ins "now(), 'ai_agent', NULL, 'agent.run.start', 'agent_run', NULL, 'success', NULL, 'req-t83-0203', NULL, '{\"prompt\":\"...\"}', 'ai_agent'")"
expect_rejected "email address in metadata value" "$(ins "now(), 'system', NULL, 'user.account.create', 'user', NULL, 'success', NULL, 'req-t83-0204', NULL, '{\"note\":\"seed-user-01@example.com\"}', 'standard'")"
expect_rejected "metadata over 4KB" "$(ins "now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0205', NULL, jsonb_build_object('blob', repeat('a', 5000)), 'standard'")"
expect_rejected "changed_fields with values" "$(ins "now(), 'user', '$uid', 'user.profile.update', 'user_profile', '$uid', 'success', NULL, 'req-t83-0206', ARRAY['headline=Hello'], NULL, 'standard'")"
expect_rejected "invalid action_code format" "$(ins "now(), 'system', NULL, 'DeleteUser', 'user', NULL, 'success', NULL, 'req-t83-0207', NULL, NULL, 'standard'")"
expect_rejected "non-success without reason_code" "$(ins "now(), 'system', NULL, 'system.job.run', 'job', NULL, 'failed', NULL, 'req-t83-0208', NULL, NULL, 'standard'")"
expect_rejected "user actor without actor_user_id" "$(ins "now(), 'user', NULL, 'user.profile.update', 'user_profile', NULL, 'success', NULL, 'req-t83-0209', NULL, NULL, 'standard'")"
expect_rejected "user actor without request_id" "$(ins "now(), 'user', '$uid', 'user.profile.update', 'user_profile', '$uid', 'success', NULL, NULL, NULL, NULL, 'standard'")"
expect_rejected "malformed request_id" "$(ins "now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'bad id!', NULL, NULL, 'standard'")"
expect_rejected "actor_user_id not in users (FK)" "$(ins "now(), 'user', '44444444-4444-4444-8444-444444444444', 'user.profile.update', 'user_profile', NULL, 'success', NULL, 'req-t83-0212', NULL, NULL, 'standard'")"
expect_rejected "occurred_at far in future" "$(ins "now() + interval '1 day', 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0210', NULL, NULL, 'standard'")"
expect_rejected "unknown retention_class" "$(ins "now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0211', NULL, NULL, 'forever'")"

# 4. retention purge removes only expired rows
psql_test -c "INSERT INTO audit_mock.audit_retention_policies VALUES ('test_ephemeral', interval '0', 'T83 test only')" >/dev/null
as_writer "INSERT INTO audit_mock.audit_events ($base_cols) VALUES
  (now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0301', NULL, NULL, 'test_ephemeral'),
  (now(), 'system', NULL, 'system.job.run', 'job', NULL, 'success', NULL, 'req-t83-0302', NULL, NULL, 'test_ephemeral');" >/dev/null
purged="$(psql_test -Atc "SELECT audit_mock.purge_expired()")"
left="$(psql_test -Atc "SELECT count(*) FROM audit_mock.audit_events")"
[[ "$purged" == "2" && "$left" == "4" ]] || { echo "FAIL purge purged=$purged left=$left"; exit 1; }
echo "PASS retention purge removed 2 expired rows, kept 4 unexpired"
expect_rejected "plain DELETE after purge (flag reset)" "DELETE FROM audit_mock.audit_events;"

# 4b. account deletion anonymizes actor (T05 FK ON DELETE SET NULL), nothing else may change
as_writer "INSERT INTO audit_mock.audit_events ($base_cols) VALUES
  (now(), 'user', '$uid2', 'user.skill.update', 'user_skill', NULL, 'success', NULL, 'req-t83-0401', ARRAY['proficiency'], NULL, 'standard');" >/dev/null
expect_rejected "re-assign actor to another user (owner)" "UPDATE audit_mock.audit_events SET actor_user_id = '$uid' WHERE request_id = 'req-t83-0401';"
expect_rejected "anonymize + change result together (owner)" "UPDATE audit_mock.audit_events SET actor_user_id = NULL, result = 'failed', reason_code = 'X_TEST' WHERE request_id = 'req-t83-0401';"
psql_test -c "DELETE FROM audit_mock.users WHERE user_id = '$uid2'" >/dev/null
anon="$(psql_test -qAtc "SELECT actor_user_id IS NULL AND result = 'success' FROM audit_mock.audit_events WHERE request_id = 'req-t83-0401'")"
[[ "$anon" == "t" ]] || { echo "FAIL account deletion did not anonymize: $anon"; exit 1; }
echo "PASS account deletion anonymized actor_user_id (row kept, other fields unchanged)"
still_ok="$(psql_test -qAtc "SELECT count(*) FROM audit_mock.find_tampered_rows()")"
[[ "$still_ok" == "0" ]] || { echo "FAIL anonymized row flagged as tampered"; exit 1; }
echo "PASS anonymized row keeps a valid row_hash"

# 5. tamper detection: owner bypasses triggers and edits a row silently
before="$(psql_test -Atc "SELECT count(*) FROM audit_mock.find_tampered_rows()")"
[[ "$before" == "0" ]] || { echo "FAIL tampered rows before=$before"; exit 1; }
psql_test -c "BEGIN; ALTER TABLE audit_mock.audit_events DISABLE TRIGGER trg_audit_events_block_change;
              UPDATE audit_mock.audit_events SET result = 'success', reason_code = NULL WHERE request_id = 'req-t83-0002';
              ALTER TABLE audit_mock.audit_events ENABLE TRIGGER trg_audit_events_block_change; COMMIT;" >/dev/null
tampered="$(as_reader "SELECT request_id FROM audit_mock.audit_events WHERE audit_event_id IN (SELECT audit_event_id FROM audit_mock.find_tampered_rows())")"
[[ "$tampered" == "req-t83-0002" ]] || { echo "FAIL tamper not detected: '$tampered'"; exit 1; }
echo "PASS tamper detected by row_hash (req-t83-0002)"

echo "T83_AUDIT_CONTRACT_TEST=PASS"
