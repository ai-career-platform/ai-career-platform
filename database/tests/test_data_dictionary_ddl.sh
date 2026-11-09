#!/usr/bin/env bash
set -euo pipefail

# T05: validate DATA_DICTIONARY.md against a DISPOSABLE PostgreSQL only.
# Never point this at Staging. Two modes:
#   1) default: docker postgres:18.1 throwaway container (same pattern as D1-9)
#   2) T05_PSQL="psql -h /tmp -p 55432 -U t": an already-running local throwaway server
if [[ "${T05_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: T05_TEST_ONLY=YES is required" >&2
  exit 2
fi

ddl_file="$(mktemp)"
trap 'rm -f "$ddl_file"' EXIT
python3 database/model/check_data_dictionary.py --ddl > "$ddl_file"

if [[ -n "${T05_PSQL:-}" ]]; then
  db="t05_check_$$"
  $T05_PSQL -d postgres -X -q -c "CREATE DATABASE $db"
  trap '$T05_PSQL -d postgres -X -q -c "DROP DATABASE IF EXISTS $db"; rm -f "$ddl_file"' EXIT
  run_psql() { $T05_PSQL -d "$db" -X -q -v ON_ERROR_STOP=1 "$@"; }
  run_file() { run_psql -f "$1"; }
else
  container="career-t05-test-${GITHUB_RUN_ID:-manual}-$$"
  trap 'docker rm -f "$container" >/dev/null 2>&1 || true; rm -f "$ddl_file"' EXIT
  docker run -d --name "$container" -e POSTGRES_USER=t05test \
    -e POSTGRES_PASSWORD=t05test-disposable-only -e POSTGRES_DB=t05test postgres:18.1 >/dev/null
  for _ in $(seq 1 50); do
    docker exec "$container" pg_isready -U t05test -d t05test >/dev/null 2>&1 && break
    sleep 2
  done
  run_psql() { docker exec -i "$container" psql -X -q -v ON_ERROR_STOP=1 -U t05test -d t05test "$@"; }
  run_file() { docker cp "$1" "$container:/tmp/in.sql"; run_psql -f /tmp/in.sql; }
fi

run_psql -c "CREATE SCHEMA career;"
run_file "$ddl_file"
tables="$(run_psql -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='career'")"
fks="$(run_psql -Atc "SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='career' AND constraint_type='FOREIGN KEY'")"
echo "PASS ddl tables=$tables fks=$fks"
run_file database/tests/t05_contract_cases.sql 2>&1 >/dev/null | grep -E "PASS|FAIL|ERROR"
echo "T05_DDL_TEST=PASS"
