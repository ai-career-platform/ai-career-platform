#!/usr/bin/env bash
set -euo pipefail

# T71: disposable test database only; NEVER execute against staging.
# Loads database/tests/behavior/T71_behavior_events_mock.sql into a throwaway postgres:18.1
# container and proves the behavior-event contract: consent matrix, withdrawal erases data,
# property allow-list, privilege boundaries, pseudonymous subject key, k-anonymous insights,
# account erasure and retention purge.
if [[ "${D1_TEST_ONLY:-}" != "YES" ]]; then
  echo "ERROR: D1_TEST_ONLY=YES is required" >&2
  exit 2
fi

container="career-t71-behavior-test-${GITHUB_RUN_ID:-manual}-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_USER=t71test \
  -e POSTGRES_PASSWORD=t71test-disposable-only \
  -e POSTGRES_DB=t71test \
  postgres:18.1 >/dev/null

ready=0
for _ in $(seq 1 50); do
  if docker exec "$container" pg_isready -U t71test -d t71test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" == "1" ]] || { echo "FAIL postgres never ready"; exit 1; }

psql_test() { docker exec -i "$container" psql -X -v ON_ERROR_STOP=1 -U t71test -d t71test "$@"; }
docker cp database/tests/behavior/T71_behavior_events_mock.sql "$container:/tmp/behavior_mock.sql"
mock_sql=/tmp/behavior_mock.sql

# ---- shared test body (also used by local runners that redefine psql_test/mock_sql)
psql_test -f "$mock_sql" >/dev/null
echo "PASS mock schema loaded"

q()       { psql_test -qAtc "$1"; }
ingest()  { psql_test -qAtc "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($1);"; }
consent() { psql_test -qAtc "SET ROLE t71_consent; SELECT behavior_mock.record_consent($1);"; }
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
uid() { printf '00000000-0000-4000-8000-%012d' "$1"; }
U1="'$(uid 1)'"; U2="'$(uid 2)'"; U3="'$(uid 3)'"; U4="'$(uid 4)'"
count_subject() { q "SELECT count(*) FROM behavior_mock.behavior_events WHERE subject_key = behavior_mock.subject_key($1)"; }

# 1. consent matrix
consent "$U1, 'behavior_analytics', true, 'signup'" >/dev/null                                   # analytics only
consent "$U2, 'behavior_analytics', true, 'signup'" >/dev/null; consent "$U2, 'personalization', true, 'signup'" >/dev/null   # both
consent "$U4, 'behavior_analytics', true, 'signup'" >/dev/null                                   # will withdraw
# U3: no consent at all

expect_eq "analytics consent  + page.view            -> stored"  "$(ingest "$U1, 'page.view', now(), '{\"page_id\":\"jobs_list\"}'")" "stored"
expect_eq "analytics consent  + recommendation.click -> blocked" "$(ingest "$U1, 'recommendation.click', now(), '{\"rank\":1}'")" "blocked_no_consent"
expect_eq "no consent         + page.view            -> blocked" "$(ingest "$U3, 'page.view', now(), '{}'")" "blocked_no_consent"
expect_eq "no consent         + posting.bookmark     -> blocked" "$(ingest "$U3, 'posting.bookmark', now(), '{}'")" "blocked_no_consent"
expect_eq "both consents      + page.view            -> stored"  "$(ingest "$U2, 'page.view', now(), '{\"page_id\":\"home\"}'")" "stored"
expect_eq "both consents      + recommendation.click -> stored"  "$(ingest "$U2, 'recommendation.click', now(), '{\"recommendation_id\":\"$(uid 99)\",\"rank\":2}'")" "stored"
expect_eq "blocked events were not stored" "$(count_subject "$U3")" "0"

# 2. property allow-list and input contract
expect_rejected "property not in allow-list"   "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'page.view', now(), '{\"email\":\"x\"}');"
expect_rejected "free text value (search query)" "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'search.submit', now(), '{\"search_type\":\"backend developer seoul\"}');"
expect_rejected "nested object value"          "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'page.view', now(), '{\"page_id\":{\"a\":1}}');"
expect_rejected "unknown event_code"           "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'mouse.move', now(), '{}');"
expect_rejected "occurred_at in the future"    "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'page.view', now() + interval '1 day', '{}');"
expect_rejected "occurred_at older than 7 days" "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event($U1, 'page.view', now() - interval '8 days', '{}');"
expect_rejected "anonymous (NULL user)"        "SET ROLE t71_ingest; SELECT behavior_mock.record_behavior_event(NULL, 'page.view', now(), '{}');"

# 3. privilege boundaries
expect_rejected "ingest INSERT directly"       "SET ROLE t71_ingest; INSERT INTO behavior_mock.behavior_events (event_code, subject_key, occurred_at, received_at, policy_code, policy_version, retain_until) VALUES ('page.view', repeat('a',64), now(), now(), 'behavior_analytics', 'x', now());"
expect_rejected "ingest SELECT raw events"     "SET ROLE t71_ingest; SELECT count(*) FROM behavior_mock.behavior_events;"
expect_rejected "ingest record_consent()"      "SET ROLE t71_ingest; SELECT behavior_mock.record_consent($U3, 'behavior_analytics', true);"
expect_rejected "consent role ingest events"   "SET ROLE t71_consent; SELECT behavior_mock.record_behavior_event($U1, 'page.view', now(), '{}');"
expect_rejected "analyst SELECT raw events"    "SET ROLE t71_analyst; SELECT count(*) FROM behavior_mock.behavior_events;"
expect_rejected "analyst read consents"        "SET ROLE t71_analyst; SELECT count(*) FROM behavior_mock.user_consents;"
expect_rejected "analyst erase_subject()"      "SET ROLE t71_analyst; SELECT behavior_mock.erase_subject($U1);"
expect_rejected "analyst read pseudonym secret" "SET ROLE t71_analyst; SELECT secret FROM behavior_mock.pseudonym_secret;"
expect_eq "analyst SELECT insights_daily allowed" "$(psql_test -qAtc "SET ROLE t71_analyst; SELECT count(*) >= 0 FROM behavior_mock.insights_daily;")" "t"

# 4. pseudonymous subject key
expect_eq "raw user_id never stored" "$(q "SELECT count(*) FROM behavior_mock.behavior_events WHERE subject_key LIKE '%' || replace($U1::text, '-', '') || '%' OR properties::text LIKE '%' || $U1 || '%'")" "0"
expect_eq "subject_key is keyed (not plain sha256 of user_id)" "$(q "SELECT behavior_mock.subject_key($U1) <> encode(sha256(uuid_send($U1::uuid)), 'hex')")" "t"

# 5. withdrawal blocks new events and erases existing ones
ingest "$U4, 'page.view', now(), '{}'" >/dev/null; ingest "$U4, 'role.view', now(), '{\"job_role_id\":\"BACKEND_ENGINEER\"}'" >/dev/null
expect_eq "before withdrawal U4 has 2 events" "$(count_subject "$U4")" "2"
expect_eq "withdrawal erased 2 events" "$(consent "$U4, 'behavior_analytics', false")" "2"
expect_eq "after withdrawal U4 has 0 events" "$(count_subject "$U4")" "0"
expect_eq "after withdrawal page.view -> blocked" "$(ingest "$U4, 'page.view', now(), '{}'")" "blocked_no_consent"
consent "$U4, 'behavior_analytics', true" >/dev/null
expect_eq "re-consent allows new events again" "$(ingest "$U4, 'page.view', now(), '{}'")" "stored"
expect_eq "re-consent does not restore erased events" "$(count_subject "$U4")" "1"
expect_eq "consent history kept (3 rows for U4)" "$(q "SELECT count(*) FROM behavior_mock.user_consents WHERE user_id = $U4")" "3"
expect_eq "withdrawing personalization keeps analytics events" "$(consent "$U2, 'personalization', false")/$(count_subject "$U2")" "1/1"

# 6. k-anonymous insights (k = 5)
for n in 11 12 13 14; do
  consent "'$(uid $n)', 'behavior_analytics', true, 'signup'" >/dev/null
  ingest "'$(uid $n)', 'posting.view', now(), '{\"job_posting_id\":\"$(uid 500)\"}'" >/dev/null
done
expect_eq "4 subjects on posting.view -> suppressed" "$(psql_test -qAtc "SET ROLE t71_analyst; SELECT count(*) FROM behavior_mock.insights_daily WHERE event_code = 'posting.view';")" "0"
consent "'$(uid 15)', 'behavior_analytics', true, 'signup'" >/dev/null
ingest "'$(uid 15)', 'posting.view', now(), '{\"job_posting_id\":\"$(uid 500)\"}'" >/dev/null
expect_eq "5 subjects on posting.view -> visible" "$(psql_test -qAtc "SET ROLE t71_analyst; SELECT subject_count FROM behavior_mock.insights_daily WHERE event_code = 'posting.view';")" "5"

# 7. account erasure and retention purge
expect_eq "erase_subject removed all U1 events" "$(q "SELECT behavior_mock.erase_subject($U1)")/$(count_subject "$U1")" "1/0"
expect_eq "after erasure U1 is blocked" "$(ingest "$U1, 'page.view', now(), '{}'")" "blocked_no_consent"
q "UPDATE behavior_mock.behavior_event_catalog SET retain_for = interval '0' WHERE event_code = 'role.view'" >/dev/null
consent "$U3, 'behavior_analytics', true" >/dev/null
ingest "$U3, 'role.view', now(), '{\"job_role_id\":\"DBA\"}'" >/dev/null
before="$(q "SELECT count(*) FROM behavior_mock.behavior_events")"
purged="$(q "SELECT behavior_mock.purge_expired()")"
after="$(q "SELECT count(*) FROM behavior_mock.behavior_events")"
expect_eq "purge removed only the expired event" "$purged/$((before - after))" "1/1"

echo "T71_BEHAVIOR_CONTRACT_TEST=PASS"
