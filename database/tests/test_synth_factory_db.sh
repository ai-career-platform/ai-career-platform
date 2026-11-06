#!/usr/bin/env bash
set -euo pipefail

# T147: disposable test database only; NEVER execute against staging.
# Generates synthetic data with database/fixtures/synth_factory.py, applies it twice to the
# T05 validation DDL in a throwaway postgres:18.1 container and proves:
#   - every generated row lands (counts match), FK/UNIQUE/CHECK all satisfied by PostgreSQL
#   - second apply changes nothing (row fingerprint identical)
#   - the SQL refuses to run in a database whose name looks shared (staging/prod)
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

work="$(mktemp -d)"
container="career-t147-factory-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

python3 database/model/check_data_dictionary.py --ddl > "$work/schema.sql"
python3 database/fixtures/synth_factory.py --target-env ci --seed 147 --users 300 --companies 40 \
  --postings 500 --out-sql "$work/synth.sql" --out-features "$work/features.jsonl" > "$work/factory.out"

docker run -d --name "$container" \
  -e POSTGRES_USER=t147test \
  -e POSTGRES_PASSWORD=t147test-disposable-only \
  -e POSTGRES_DB=ci_t147 \
  postgres:18.1 >/dev/null
for _ in $(seq 1 50); do
  docker exec "$container" pg_isready -U t147test -d ci_t147 >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$container" psql -X -q -U t147test -d ci_t147 -c "CREATE DATABASE career_staging" >/dev/null
for f in schema.sql synth.sql; do docker cp "$work/$f" "$container:/tmp/$f"; done

psql_test()    { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t147test -d ci_t147 "$@"; }
psql_staging() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t147test -d career_staging "$@"; }
schema_sql=/tmp/schema.sql
synth_sql=/tmp/synth.sql
factory_out="$work/factory.out"

# ---- shared test body (also used by local runners that redefine the functions/paths above)
cat "$factory_out"
psql_test -q -c "CREATE SCHEMA career;"
psql_test -q -f "$schema_sql" >/dev/null
echo "PASS T05 validation DDL applied"

fingerprint() {
  psql_test -qAtc "
    SELECT md5(string_agg(t || ':' || h, ',' ORDER BY t)) FROM (
      SELECT 'users' t, md5(string_agg(x::text, '|' ORDER BY x::text)) h FROM career.users x
      UNION ALL SELECT 'companies', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.companies x
      UNION ALL SELECT 'job_postings', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.job_postings x
      UNION ALL SELECT 'job_posting_skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.job_posting_skills x
      UNION ALL SELECT 'user_skills', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.user_skills x
      UNION ALL SELECT 'user_job_bookmarks', md5(string_agg(x::text, '|' ORDER BY x::text)) FROM career.user_job_bookmarks x
    ) s"
}
db_counts() {
  psql_test -qAtc "SELECT json_build_object(
      'companies', (SELECT count(*) FROM career.companies), 'job_posting_skills', (SELECT count(*) FROM career.job_posting_skills),
      'job_postings', (SELECT count(*) FROM career.job_postings), 'job_role_skills', (SELECT count(*) FROM career.job_role_skills),
      'job_roles', (SELECT count(*) FROM career.job_roles), 'skills', (SELECT count(*) FROM career.skills),
      'user_job_bookmarks', (SELECT count(*) FROM career.user_job_bookmarks), 'user_profiles', (SELECT count(*) FROM career.user_profiles),
      'user_skills', (SELECT count(*) FROM career.user_skills), 'users', (SELECT count(*) FROM career.users))::text"
}

psql_test -q -f "$synth_sql" >/dev/null
first_fp="$(fingerprint)"
expected="$(sed -n 's/.*counts=\(.*\)$/\1/p' "$factory_out")"
got="$(db_counts)"
python3 -c "import json,sys; a=json.loads(sys.argv[1]); b=json.loads(sys.argv[2]); sys.exit(0 if a==b else 1)" "$expected" "$got" \
  || { echo "FAIL counts differ: expected $expected got $got"; exit 1; }
echo "PASS apply 1: every generated row stored (FK/UNIQUE/CHECK satisfied) $got"

psql_test -q -f "$synth_sql" >/dev/null
[[ "$(fingerprint)" == "$first_fp" && "$(db_counts)" == "$got" ]] || { echo "FAIL second apply changed data"; exit 1; }
echo "PASS apply 2: idempotent (counts and row fingerprint identical)"

bad="$(psql_test -qAtc "SELECT count(*) FROM career.users WHERE email NOT LIKE '%@example.test' OR email_canonical <> lower(email)")"
[[ "$bad" == "0" ]] || { echo "FAIL non-synthetic emails: $bad"; exit 1; }
echo "PASS only example.test canonical emails"

src="$(psql_test -qAtc "SELECT count(*) FROM career.job_postings jp JOIN career.data_sources d USING (source_id) WHERE d.code <> 'synthetic_seed'")"
[[ "$src" == "0" ]] || { echo "FAIL postings from non-synthetic source: $src"; exit 1; }
echo "PASS all postings reference the synthetic_seed source"

if psql_staging -q -f "$synth_sql" >/dev/null 2>&1; then
  echo "FAIL factory SQL ran in a database named career_staging"
  exit 1
fi
echo "PASS expected rejected: factory SQL refuses database named career_staging"

echo "T147_FACTORY_DB_TEST=PASS"
