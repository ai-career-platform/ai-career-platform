#!/bin/bash
# Manual JobKorea official XML API collector run on ai-career-vm (egress IP registered with JobKorea).
# Never scheduled by this script. Runs in a throwaway container (--rm) from the image of the running backend
# (Python + psycopg already there): nothing is installed on the VM and the web service is not touched.
#
#   run-jobkorea-collector.sh check                 # T61 preflight + IP check: no JobKorea request, no DB access
#   run-jobkorea-collector.sh dry-run [--new 100]   # API pages + Cloud SQL plan, no writes
#   run-jobkorea-collector.sh run     [--new 100]   # writes (needs storage permission in the T61 provider record)
#
# Layout (owner-only, never in Git):
#   $BASE/code/crawler/...            crawler package from the approved commit (read-only mount)
#   $BASE/secrets/collector.env       GCP_SYNC_TARGET_* (career_sync, verify-full), CRAWLER_LIVE_SCHEDULE_APPROVED
#   $BASE/secrets/approval.json       T61 PM approval (collection_method API, api_collection), provider_permission_file
#                                     = /secrets/provider.json
#   $BASE/secrets/provider.json       T61 provider permission (JobKorea)
#   $BASE/secrets/jobkorea-api.json   API endpoint URLs + registered IPs
set -euo pipefail
MODE=${1:?usage: run-jobkorea-collector.sh check|dry-run|run [options]}; shift
BASE=${JOBKOREA_COLLECTOR_BASE:-/opt/ai-career-gcp/jobkorea-collector}
CA=${JOBKOREA_COLLECTOR_CA:-/opt/ai-career-gcp/secrets/cloudsql-server-ca.pem}
TIMEOUT=${JOBKOREA_COLLECTOR_TIMEOUT:-2400}        # seconds; the collector's own deadline is 1800
LOG_DIR="$BASE/logs"
umask 077
mkdir -p "$LOG_DIR"
exec 9>"$BASE/.run.lock"
flock -n 9 || { echo '{"status":"SKIPPED","reason":"COLLECTOR_ALREADY_RUNNING"}'; exit 0; }
IMAGE=$(docker inspect --format '{{.Config.Image}}' ai-career-gcp-backend-1)
case "$MODE" in
  check)   ARGS=(-m crawler.jobs.jobkorea_api live --policy-file /secrets/approval.json --api-config /secrets/jobkorea-api.json --check "$@") ;;
  dry-run|run) ARGS=(-m crawler.jobs.jobkorea_collector "$MODE" --policy-file /secrets/approval.json --api-config /secrets/jobkorea-api.json "$@") ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
LOG="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$MODE.json"
set +e
timeout "$TIMEOUT" docker run --rm --network bridge --env-file "$BASE/secrets/collector.env" \
  -e PYTHONPATH=/collector -e PYTHONDONTWRITEBYTECODE=1 -e GCP_SYNC_TARGET_SSLROOTCERT=/run/cloudsql/server-ca.pem \
  -v "$BASE/code:/collector:ro" -v "$BASE/secrets:/secrets:ro" -v "$CA:/run/cloudsql/server-ca.pem:ro" \
  -w /collector --entrypoint python "$IMAGE" "${ARGS[@]}" | tee "$LOG"
STATUS=${PIPESTATUS[0]}
set -e
echo "exit=$STATUS log=$LOG" >&2
exit "$STATUS"
