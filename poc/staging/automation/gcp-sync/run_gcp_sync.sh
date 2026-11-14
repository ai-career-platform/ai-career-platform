#!/usr/bin/env bash
# #337 GCP posting sync wrapper for the Staging host.
# cron (host clock is UTC): 5 23 * * *  = 08:05 KST, after the 21:00-08:00 night crawl window.
# Runs the merged module inside the existing backend container; starts no crawl.
# Secrets stay in gcp-sync.env (mode 600) and are passed by NAME only (-e KEY), never on argv.
set -euo pipefail
BASE=/home/kant/ai-career-staging-poc
CONF="$BASE/gcp-sync"
MODE="${1:-scheduled}"
fail() { printf '{"status":"FAILED","error_code":"%s","wrapper":true}\n' "$1"; exit 2; }
case "$MODE" in dry-run|run|scheduled) ;; *) fail BAD_MODE ;; esac
[ -f "$CONF/gcp-sync.env" ] || fail ENV_FILE_MISSING
[ "$(stat -c %a "$CONF/gcp-sync.env")" = 600 ] || fail ENV_FILE_MODE
[ -f "$CONF/server-ca.pem" ] || fail CA_FILE_MISSING
set -a
# shellcheck disable=SC1091
. "$CONF/gcp-sync.env"
set +a
GCP_SYNC_TARGET_SSLROOTCERT_PEM="$(cat "$CONF/server-ca.pem")"
export GCP_SYNC_TARGET_SSLROOTCERT_PEM
cd "$BASE"
printf '{"wrapper_start":"%s","mode":"%s"}\n' "$(date -u +%FT%TZ)" "$MODE"
exec /usr/bin/flock --nonblock --conflict-exit-code 75 "$CONF/.lock" \
  /usr/bin/docker compose --project-name ai-career-staging-poc exec -T \
  -e GCP_SYNC_TARGET_HOST -e GCP_SYNC_TARGET_HOSTADDR -e GCP_SYNC_TARGET_PORT -e GCP_SYNC_TARGET_DB \
  -e GCP_SYNC_TARGET_USER -e GCP_SYNC_TARGET_PASSWORD -e GCP_SYNC_TARGET_SSLROOTCERT_PEM \
  -e GCP_SYNC_SOURCE_CODE -e GCP_SYNC_PUBLISH \
  backend python -m crawler.jobs.gcp_sync "$MODE" </dev/null
