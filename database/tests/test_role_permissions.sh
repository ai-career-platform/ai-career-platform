#!/usr/bin/env bash
set -euo pipefail
[[ "${D1_TEST_ONLY:-}" == "YES" ]] || { echo "D1_TEST_ONLY=YES required"; exit 2; }
c="career-role-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$c" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$c" -e POSTGRES_USER=d1admin -e POSTGRES_PASSWORD=disposable-test-only -e POSTGRES_DB=d1roles postgres:18.1 >/dev/null
ready=0
for i in $(seq 1 50); do
 if docker exec "$c" pg_isready -U d1admin -d d1roles >/dev/null 2>&1; then ready=1; break; fi
 sleep 2
done
[[ "$ready" == 1 ]] || exit 1

docker cp database/security/DRAFT_00_create_roles_schema.sql "$c:/tmp/roles.sql"
docker cp database/migrations/DRAFT_0001_initial_schema.sql "$c:/tmp/schema.sql"
sql() { docker exec "$c" psql -X -v ON_ERROR_STOP=1 -U d1admin -d d1roles "$@"; }

sql -f /tmp/roles.sql >/dev/null
sql -c 'SET ROLE career_migrator' -f /tmp/schema.sql >/dev/null

role_count="$(sql -Atc "SELECT COUNT(*) FROM pg_roles WHERE rolname IN ('career_reader','career_app','career_migrator','career_admin') AND rolcanlogin=false AND rolsuper=false")"
[[ "$role_count" == 4 ]] || { echo "FAIL roles=$role_count"; exit 1; }
echo "PASS roles=4 no-login and no-superuser"

# can use SET ROLE as superuser to simulate grant enforcement;
# default ACLs attached to career_migrator are applied because DDL was
# executed as career_migrator, not d1admin.
reader_can_read="$(sql -Atc "SELECT has_table_privilege('career_reader','career.users','SELECT')")"
reader_can_write="$(sql -Atc "SELECT has_table_privilege('career_reader','career.users','INSERT')")"
app_can_write="$(sql -Atc "SELECT has_table_privilege('career_app','career.users','INSERT')")"
app_can_create="$(sql -Atc "SELECT has_schema_privilege('career_app','career','CREATE')")"
[[ "$reader_can_read" == t && "$reader_can_write" == f && "$app_can_write" == t && "$app_can_create" == f ]] || {
 echo "FAIL ACL reader_read=$reader_can_read reader_write=$reader_can_write app_write=$app_can_write app_create=$app_can_create"; exit 1;
}
echo "PASS reader SELECT-only; app CRUD without schema CREATE"

expect_denied() {
 local role="$1" operation="$2" statement="$3" output
 if output="$(sql -v VERBOSITY=verbose -c "SET ROLE $role; $statement" 2>&1)" ||
    [[ "$output" != *'ERROR:  42501:'* ]]; then
  printf 'FAIL %s %s expected SQLSTATE 42501\n%s\n' "$role" "$operation" "$output"
  exit 1
 fi
 echo "PASS $role $operation denied (42501)"
}

sql -c "SET ROLE career_reader; SELECT count(*) FROM career.users;" >/dev/null
echo "PASS career_reader SELECT"
expect_denied career_reader INSERT "INSERT INTO career.users(email,display_name) VALUES ('blocked@example.org','No');"
expect_denied career_reader UPDATE "UPDATE career.users SET display_name = 'No' WHERE false;"
expect_denied career_reader DELETE "DELETE FROM career.users WHERE false;"
expect_denied career_reader CREATE "CREATE TABLE career.reader_probe (id integer);"

sql -c "BEGIN; SET ROLE career_app;
 SELECT count(*) FROM career.users;
 INSERT INTO career.users(email,display_name) VALUES ('app-probe@example.org','Probe');
 UPDATE career.users SET display_name = 'Updated' WHERE email = 'app-probe@example.org';
 DELETE FROM career.users WHERE email = 'app-probe@example.org';
 ROLLBACK;" >/dev/null
echo "PASS career_app CRUD"
expect_denied career_app CREATE "CREATE TABLE career.app_probe (id integer);"
expect_denied career_app ALTER "ALTER TABLE career.users ADD COLUMN app_probe integer;"

sql -c "BEGIN; SET ROLE career_migrator;
 CREATE TABLE career.migrator_probe (id integer);
 ALTER TABLE career.users ADD COLUMN migrator_probe integer;
 ROLLBACK;" >/dev/null
echo "PASS career_migrator CREATE and ALTER"

# Need reapply read-only bootstrap idempotently; do not recreate schema.
sql -f /tmp/roles.sql >/dev/null
echo "PASS safe bootstrap rerun"
echo "D2_ROLE_TEST=PASS"
