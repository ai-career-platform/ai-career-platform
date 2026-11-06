#!/usr/bin/env bash
set -euo pipefail

# T10: disposable test database only; NEVER execute against staging.
# Applies DRAFT_0001 schema, then the seed twice, and proves:
#   - second run changes nothing (row content fingerprint identical, updated_at untouched)
#   - verify_seed.sql checks all PASS (counts, duplicates 0, orphans 0, lookups)
#   - negative cases: seed without schema fails atomically; invalid fixture rejected by constraints
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-t10-seed-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=t10test \
  -e POSTGRES_PASSWORD=t10test-disposable-only \
  -e POSTGRES_DB=t10test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U t10test -d t10test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t10test -d t10test "$@"; }

docker cp database/migrations/DRAFT_0001_initial_schema.sql "$container:/tmp/schema.sql"
docker cp database/seeds/0001_initial_seed.sql "$container:/tmp/seed.sql"
docker cp database/seeds/verify_seed.sql "$container:/tmp/verify.sql"

# Negative 1: seed before the schema exists must fail and leave nothing behind.
psql_test -c "CREATE SCHEMA career AUTHORIZATION t10test;"
if psql_test -f /tmp/seed.sql >/dev/null 2>&1; then
  echo "FAIL seed unexpectedly succeeded without tables"
  exit 1
fi
leftover="$(psql_test -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='career'")"
[[ "$leftover" == "0" ]] || { echo "FAIL partial objects left: $leftover"; exit 1; }
echo "PASS expected rejected: seed without schema (atomic rollback)"

psql_test -f /tmp/schema.sql >/dev/null

fingerprint() {
  psql_test -Atc "
    SELECT md5(string_agg(t || ':' || h, ',' ORDER BY t)) FROM (
      SELECT 'job_roles' t, md5(string_agg(x::text, '|' ORDER BY x::text)) h FROM career.job_roles x
      UNION ALL SELECT 'skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.skills x
      UNION ALL SELECT 'companies', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.companies x
      UNION ALL SELECT 'users', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.users x
      UNION ALL SELECT 'user_profiles', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.user_profiles x
      UNION ALL SELECT 'job_role_skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.job_role_skills x
      UNION ALL SELECT 'job_postings', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.job_postings x
      UNION ALL SELECT 'job_posting_skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.job_posting_skills x
      UNION ALL SELECT 'user_skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.user_skills x
      UNION ALL SELECT 'user_job_bookmarks', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.user_job_bookmarks x
    ) s"
}
counts() {
  psql_test -Atc "
    SELECT (SELECT count(*) FROM career.job_roles) || ',' || (SELECT count(*) FROM career.skills) || ',' ||
           (SELECT count(*) FROM career.companies) || ',' || (SELECT count(*) FROM career.users) || ',' ||
           (SELECT count(*) FROM career.user_profiles) || ',' || (SELECT count(*) FROM career.job_role_skills) || ',' ||
           (SELECT count(*) FROM career.job_postings) || ',' || (SELECT count(*) FROM career.job_posting_skills) || ',' ||
           (SELECT count(*) FROM career.user_skills) || ',' || (SELECT count(*) FROM career.user_job_bookmarks)"
}

psql_test -f /tmp/seed.sql >/dev/null
first_fp="$(fingerprint)"
first_counts="$(counts)"
echo "PASS seed run 1 counts(roles,skills,companies,users,profiles,role_skills,postings,posting_skills,user_skills,bookmarks)=$first_counts"

psql_test -f /tmp/seed.sql >/dev/null
second_fp="$(fingerprint)"
second_counts="$(counts)"
[[ "$first_counts" == "$second_counts" ]] || { echo "FAIL counts changed on rerun: $first_counts -> $second_counts"; exit 1; }
[[ "$first_fp" == "$second_fp" ]] || { echo "FAIL row content changed on rerun"; exit 1; }
echo "PASS seed run 2 idempotent (counts and row fingerprint identical)"

verify_out="$(psql_test -At -F ' | ' -f /tmp/verify.sql)"
echo "$verify_out"
if grep -q ' | f$' <<<"$verify_out"; then
  echo "FAIL verify_seed.sql has failing checks"
  exit 1
fi
grep -q '^SEED_VERIFY | t$' <<<"$verify_out" || { echo "FAIL verdict row missing"; exit 1; }
echo "PASS verify_seed.sql all checks"

expect_rejected() {
  local label="$1"
  local query="$2"
  if psql_test -c "$query" >/dev/null 2>&1; then
    echo "FAIL expected rejected: $label"
    exit 1
  fi
  echo "PASS expected rejected: $label"
}
expect_rejected "duplicate seed email" \
  "INSERT INTO career.users(email,display_name) VALUES('seed-user-01@example.com','Dup');"
expect_rejected "duplicate skill code" \
  "INSERT INTO career.skills(code,name) VALUES('PYTHON','Python again');"
expect_rejected "importance out of range" \
  "UPDATE career.job_role_skills SET importance = 9 WHERE importance = 5;"
expect_rejected "posting expires before published" \
  "UPDATE career.job_postings SET expires_at = published_at - interval '1 day' WHERE status = 'published';"
expect_rejected "delete skill referenced by seed" \
  "DELETE FROM career.skills WHERE code = 'PYTHON';"

[[ "$(fingerprint)" == "$first_fp" ]] || { echo "FAIL rejected statements altered data"; exit 1; }
echo "PASS data unchanged after rejected statements"
echo "T10_SEED_TEST=PASS"
