#!/usr/bin/env bash
# T11: constraint, index and privilege tests for database/migrations/0001_initial_schema.sql.
# Disposable postgres:18.1 container only. Never point this at a shared or Staging DB.
set -euo pipefail
[[ "${D1_TEST_ONLY:-}" == "YES" ]] || { echo "D1_TEST_ONLY=YES required"; exit 2; }
c="career-t11-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$c" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$c" -e POSTGRES_USER=d1admin -e POSTGRES_PASSWORD=disposable-test-only -e POSTGRES_DB=t11 postgres:18.1 >/dev/null
ready=0
for i in $(seq 1 50); do
 if docker exec "$c" pg_isready -U d1admin -d t11 >/dev/null 2>&1; then ready=1; break; fi
 sleep 2
done
[[ "$ready" == 1 ]] || exit 1

docker cp database/security/DRAFT_00_create_roles_schema.sql "$c:/tmp/roles.sql"
docker cp database/migrations/0001_initial_schema.sql "$c:/tmp/schema.sql"
docker cp database/tests/test_full_schema.sql "$c:/tmp/t11.sql"
sql() { docker exec "$c" psql -X -v ON_ERROR_STOP=1 -U d1admin -d t11 "$@"; }

sql -q -f /tmp/roles.sql
# DDL runs as career_migrator so the default privileges for app/reader apply.
sql -q -c 'SET ROLE career_migrator' -f /tmp/schema.sql
echo "PASS 0001_initial_schema.sql applied as career_migrator"

log="$(sql -o /dev/null -f /tmp/t11.sql 2>&1)" || { echo "$log"; echo "T11_FULL_SCHEMA_TEST=FAIL"; exit 1; }
log="$(sed -n 's/^.*NOTICE:  //p' <<<"$log")"
echo "$log"

# A failing statement inside an explicit transaction must leave nothing behind after COMMIT.
docker exec -i "$c" psql -X -U d1admin -d t11 >/dev/null 2>&1 <<'SQL' || true
BEGIN;
INSERT INTO career.skills (code, name) VALUES ('t11_tx_commit', 'kept?');
INSERT INTO career.skills (code, name) VALUES (NULL, 'bad');
COMMIT;
SQL
n="$(sql -Atc "SELECT count(*) FROM career.skills WHERE code = 't11_tx_commit'")"
[[ "$n" == 0 ]] || { echo "FAIL aborted transaction left $n row(s)"; exit 1; }
echo "PASS aborted transaction is rolled back as a whole on COMMIT"

echo "T11_SUMMARY pass=$(($(grep -c '^PASS' <<<"$log") + 2)) warn=$(grep -c '^WARN' <<<"$log" || true)"
echo "T11_FULL_SCHEMA_TEST=PASS"
