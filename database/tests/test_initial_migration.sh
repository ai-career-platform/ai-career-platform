#!/usr/bin/env bash
set -euo pipefail

# D1-9: disposable test database only; NEVER execute against staging.
# Requires docker, and runs against postgres:18.1 in a temporary isolated container.
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-d1-9-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=d1test \
  -e POSTGRES_PASSWORD=d1test-disposable-only \
  -e POSTGRES_DB=d1test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U d1test -d d1test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U d1test -d d1test "$@"; }

psql_test -c "CREATE SCHEMA career AUTHORIZATION d1test;"
docker cp database/migrations/DRAFT_0001_initial_schema.sql "$container:/tmp/initial_schema.sql"
docker exec "$container" psql -X -v ON_ERROR_STOP=1 -U d1test -d d1test -f /tmp/initial_schema.sql >/dev/null

tables="$(psql_test -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='career' AND table_type='BASE TABLE'")"
[[ "$tables" == "10" ]] || { echo "FAIL tables=$tables"; exit 1; }
echo "PASS tables=10"

indexes="$(psql_test -Atc "SELECT count(*) FROM pg_indexes WHERE schemaname='career' AND indexname LIKE 'ix_%'")"
[[ "$indexes" == "6" ]] || { echo "FAIL custom_indexes=$indexes"; exit 1; }
echo "PASS custom_indexes=6"

fks="$(psql_test -Atc "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_schema='career' AND constraint_type='FOREIGN KEY'")"
[[ "$fks" == "11" ]] || { echo "FAIL foreign_keys=$fks"; exit 1; }
echo "PASS foreign_keys=11"

user_id="$(psql_test -Atc "INSERT INTO career.users(email,display_name) VALUES('test@example.org','Test') RETURNING user_id")"
skill_id="$(psql_test -Atc "INSERT INTO career.skills(code,name) VALUES('PYTHON','Python') RETURNING skill_id")"
psql_test -c "INSERT INTO career.user_skills(user_id,skill_id,proficiency) VALUES('$user_id','$skill_id',3)" >/dev/null
echo "PASS valid rows and FK"

expect_rejected() {
  local label="$1"
  local query="$2"
  if psql_test -c "$query" >/dev/null 2>&1; then
    echo "FAIL expected rejected: $label"
    exit 1
  fi
  echo "PASS expected rejected: $label"
}
expect_rejected "duplicate unique email" "INSERT INTO career.users(email,display_name) VALUES('test@example.org','Duplicated');"
expect_rejected "invalid user status" "INSERT INTO career.users(email,display_name,status) VALUES('new@example.org','Test','invalid');"
expect_rejected "invalid proficiency" "INSERT INTO career.user_skills(user_id,skill_id,proficiency) VALUES('$user_id','$skill_id',8);"
expect_rejected "missing FK user" "INSERT INTO career.user_profiles(user_id) VALUES('00000000-0000-0000-0000-000000000001');"

if docker exec "$container" psql -X -v ON_ERROR_STOP=1 -U d1test -d d1test -f /tmp/initial_schema.sql >/dev/null 2>&1; then
  echo "FAIL duplicate migration unexpectedly succeeded"
  exit 1
fi
echo "PASS non-idempotent migration rerun rejected"

final_tables="$(psql_test -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='career' AND table_type='BASE TABLE'")"
[[ "$final_tables" == "10" ]] || { echo "FAIL rerun altered tables count"; exit 1; }
echo "PASS migration transactional integrity tables=10"
echo "D1_SQL_TEST=PASS"
