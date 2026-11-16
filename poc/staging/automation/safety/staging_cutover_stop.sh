#!/usr/bin/env bash
# Staging -> Windows cutover: stop ONLY the Staging crawler and GCP-sync schedules, reversibly.
# PM approval scope (AI_CAREER_CRAWLER_STAGING_TO_WINDOWS_CUTOVER): stop crawler + GCP sync automatic runs.
# NOT in scope and never done here: PostgreSQL data, server shutdown, other services (the release-deploy
# timer, docker, backend), credentials, firewall, GCP.
#
# Run on the Staging host as the deploy user (kant). Interactive sudo is used only for `systemctl disable/enable`
# of the matched crawler timers.
#
#   bash staging_cutover_stop.sh plan                                  # read only: what would change
#   bash staging_cutover_stop.sh apply --approval-ref <ref> [--wait-min 30]
#   bash staging_cutover_stop.sh verify                                # read only: state + 26 h earliest time
#   bash staging_cutover_stop.sh rollback <backup-dir> --yes           # restore crontab + timers exactly
#
# apply: (1) backup to ~/aicp-cutover-backup-<UTC> (mode 700) and verify it, else abort with no change;
#        (2) wait for a running sync/crawl to finish (never kills it), else abort with no change;
#        (3) comment out only the matching crontab lines; (4) disable --now only the matching timers;
#        (5) print verification. Output passes through redact(); no secret values are printed.
set -euo pipefail
B=${AICP_STAGING_BASE:-/home/kant/ai-career-staging-poc}
LOG="$B/gcp-sync/logs/gcp-sync.log"
CRON_RE='run_gcp_sync\.sh|crawler\.jobs|night_crawl|dispatcher|import_jobkorea|harvest'
TIMER_RE='crawler|night|t15[0-9]|harvest|gcp'
TIMER_EXCLUDE_RE='deploy'
PROC_RE='crawler\.jobs\.(gcp_sync|night|dispatcher|harvest|import_jobkorea)|run_gcp_sync\.sh|import_jobkorea_html'
QUIET_HOURS=26

redact() {
  sed -E \
    -e 's#([A-Za-z0-9_]*(PASS|PASSWORD|TOKEN|SECRET|KEY|WEBHOOK|RUL)[A-Za-z0-9_]*)=[^[:space:]"]+#\1=<redacted>#Ig' \
    -e 's#(://)[^/@[:space:]]+@#\1<redacted>@#g' \
    -e 's#hooks\.slack\.com/services/[A-Za-z0-9/_-]+#hooks.slack.com/services/<redacted>#g'
}
say() { printf '%s\n' "$*" | redact; }
die() { say "ABORT: $*  (no schedule was changed)"; exit 2; }

crontab_now() { crontab -l 2>/dev/null || true; }
cron_targets() { crontab_now | grep -nE "$CRON_RE" | grep -vE '^[0-9]+:[[:space:]]*#' || true; }

timer_names() {  # system + user unit files and loaded timers matching the crawler pattern, deploy excluded
  { systemctl list-unit-files --type=timer --no-legend 2>/dev/null | awk '{print $1}'
    systemctl list-timers --all --no-legend 2>/dev/null | grep -oE '[A-Za-z0-9@_.-]+\.timer' ; } \
    | grep -E '^ai-career-|^t61' | grep -E "$TIMER_RE" | grep -vE "$TIMER_EXCLUDE_RE" | sort -u || true
}
timer_state() { printf '%s %s %s\n' "$1" "$(systemctl is-enabled "$1" 2>/dev/null || true)" \
                "$(systemctl is-active "$1" 2>/dev/null || true)"; }
user_timers() { systemctl --user list-timers --all --no-legend 2>/dev/null | grep -oE '[A-Za-z0-9@_.-]+\.timer' \
                | grep -E "$TIMER_RE" | grep -vE "$TIMER_EXCLUDE_RE" | sort -u || true; }
running() { pgrep -af "$PROC_RE" 2>/dev/null | grep -v -- "$0" || true; }

last_sync() {  # whitelisted fields of the last logged sync result, plus the earliest Windows cutover time
  [ -f "$LOG" ] || { echo "last_sync=NO_GCP_SYNC_LOG"; return; }
  python3 - "$LOG" "$QUIET_HOURS" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
keep = ('wrapper_start', 'mode', 'status', 'error_code', 'run_id', 'inserted', 'updated', 'duplicate', 'skipped',
        'failed', 'publish', 'started_at', 'ended_at')
start, result = None, None
for line in open(sys.argv[1], encoding='utf-8', errors='replace'):
    line = line.strip()
    if not line.startswith('{'):
        continue
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if 'wrapper_start' in rec:
        start = rec['wrapper_start']
    elif 'status' in rec:
        result = dict({k: rec[k] for k in keep if k in rec}, wrapper_start=start)
print('last_sync_record=' + json.dumps(result, ensure_ascii=False, default=str))
when = result and (result.get('ended_at') or result.get('started_at') or result.get('wrapper_start'))
if when:
    t = datetime.fromisoformat(str(when).replace('Z', '+00:00'))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    earliest = t + timedelta(hours=int(sys.argv[2]))
    now = datetime.now(timezone.utc)
    print(f'last_sync_time_utc={t.isoformat()}')
    print(f'windows_cutover_earliest_utc={earliest.isoformat()}')
    print(f'quiet_26h_met_now={"yes" if now >= earliest else "no"} (log-based; the Windows sync re-checks GCP ingestion_runs)')
else:
    print('last_sync_time_utc=UNKNOWN')
PY
}

status() {
  echo "host=$(hostname) user=$(id -un) now_utc=$(date -u +%FT%TZ)"
  echo "--- crontab lines matching crawler/GCP sync (active only)"; cron_targets | redact; [ -n "$(cron_targets)" ] || echo none
  local off; off=$(crontab_now | grep -n 'AICP-CUTOVER-DISABLED' || true)
  echo "--- crontab lines already disabled by cutover"; if [ -n "$off" ]; then printf '%s\n' "$off" | redact; else echo none; fi
  echo "--- crawler timers (system): name enabled active"; for t in $(timer_names); do timer_state "$t"; done
  [ -n "$(timer_names)" ] || echo none
  echo "--- crawler timers (user)"; user_timers || true; [ -n "$(user_timers)" ] || echo none
  echo "--- untouched (excluded) ai-career timers"
  systemctl list-unit-files --type=timer --no-legend 2>/dev/null | awk '{print $1, $2}' | grep '^ai-career-' \
    | grep -E "$TIMER_EXCLUDE_RE" || echo none
  echo "--- running crawler/sync processes"; running | redact; [ -n "$(running)" ] || echo none
  last_sync
}

seal() {  # checksum every backup file except the checksum list itself
  ( cd "$1" && find . -maxdepth 1 -type f ! -name 'SHA256SUMS*' -print | sort | xargs sha256sum > SHA256SUMS.tmp \
    && mv SHA256SUMS.tmp SHA256SUMS )
}

backup() {
  local dir="$1" ref="$2"
  umask 077; mkdir -p "$dir"; chmod 700 "$dir"
  crontab_now > "$dir/crontab.before"
  for t in $(timer_names); do timer_state "$t"; done > "$dir/timers.before"
  for t in $(timer_names); do systemctl cat "$t" "${t%.timer}.service" 2>/dev/null || true; done > "$dir/units.cat"
  systemctl list-timers --all --no-legend > "$dir/list-timers.before" 2>&1 || true
  systemctl --user list-timers --all --no-legend > "$dir/user-timers.before" 2>&1 || true
  (cd "$B" 2>/dev/null && git rev-parse HEAD 2>/dev/null || echo "NO_GIT") > "$dir/deploy-commit"
  (cd "$B" 2>/dev/null && docker compose --project-name ai-career-staging-poc ps --format '{{.Service}} {{.State}} {{.Image}}' 2>&1 || true) > "$dir/containers.before"
  { [ -f "$B/gcp-sync/gcp-sync.env" ] && sed -nE 's/^([A-Z_]+)=.*/\1/p' "$B/gcp-sync/gcp-sync.env"; } > "$dir/gcp-sync-env.keys" || true
  last_sync > "$dir/last-sync.before" 2>&1 || true
  running | redact > "$dir/processes.before" || true
  printf 'approval_ref=%s\ncreated_utc=%s\nuser=%s\n' "$ref" "$(date -u +%FT%TZ)" "$(id -un)" | redact > "$dir/README"
  # verification: the crontab copy must equal the live crontab, and every file must exist
  cmp -s "$dir/crontab.before" <(crontab_now) || die "crontab backup does not match the live crontab"
  for f in crontab.before timers.before units.cat deploy-commit last-sync.before README; do
    [ -e "$dir/$f" ] || die "backup file missing: $f"
  done
  seal "$dir"
  say "backup_dir=$dir"
}

apply() {
  local ref="" wait_min=30
  while [ $# -gt 0 ]; do case "$1" in
    --approval-ref) ref="${2:-}"; shift 2 ;; --wait-min) wait_min="${2:-30}"; shift 2 ;; *) die "unknown option $1" ;; esac; done
  [ -n "$ref" ] || die "--approval-ref <PM approval reference> is required"
  [ "$(id -un)" = "${AICP_STAGING_USER:-kant}" ] || die "run as the deploy user ${AICP_STAGING_USER:-kant}"
  [ -d "$B" ] || die "no base dir $B"
  local dir; dir="$HOME/aicp-cutover-backup-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "== 1. backup"; backup "$dir" "$ref"
  echo "== 2. wait for running crawl/sync (max ${wait_min} min, never killed)"
  local i=0; while [ -n "$(running)" ]; do
    if [ $i -ge $((wait_min * 2)) ]; then die "a crawl/sync is still running after ${wait_min} min; retry later"; fi
    if [ $i -eq 0 ]; then running | redact; fi
    sleep 30; i=$((i + 1)); done
  echo "none running"
  echo "== 3. crontab: comment out matching lines only"
  local stamp; stamp="# AICP-CUTOVER-DISABLED $(date -u +%FT%TZ) "
  local before after changed expect
  before="$dir/crontab.before"; after="$dir/crontab.after"
  # pattern via ENVIRON: awk -v would turn '\.' into '.'
  CRON_RE="$CRON_RE" STAMP="$stamp" awk '($0 ~ ENVIRON["CRON_RE"]) && ($0 !~ /^[[:space:]]*#/) {print ENVIRON["STAMP"] $0; next} {print}' \
    "$before" > "$after"
  expect=$(grep -E "$CRON_RE" "$before" | grep -cvE '^[[:space:]]*#' || true)
  changed=$(diff "$before" "$after" | grep -c '^>' || true)
  [ "$changed" = "$expect" ] || die "crontab edit would change $changed lines, expected $expect"
  [ "$(wc -l < "$before")" = "$(wc -l < "$after")" ] || die "crontab line count would change"
  if [ "$expect" -gt 0 ]; then crontab "$after"; say "commented $expect crontab line(s)"; else echo "no active crontab line matched (already off)"; fi
  cmp -s "$after" <(crontab_now) || [ "$expect" -eq 0 ] || die "installed crontab differs from the reviewed edit"
  echo "== 4. timers: disable --now matching crawler timers only (deploy timer untouched)"
  local t
  local en ac
  while read -r t en ac <&3; do
    [ -n "$t" ] || continue
    if [ "$en" = enabled ] || [ "$ac" = active ]; then sudo systemctl disable --now "$t"; echo "disabled $t"
    else echo "already off: $t ($en/$ac)"; fi
  done 3< "$dir/timers.before"
  user_timers > "$dir/user-timers.disabled"
  for t in $(cat "$dir/user-timers.disabled"); do systemctl --user disable --now "$t"; echo "disabled user timer $t"; done
  for t in $(timer_names); do timer_state "$t"; done > "$dir/timers.after"
  echo "== 5. verification"; status | tee "$dir/verify.after"
  seal "$dir"
  echo "ROLLBACK: bash $0 rollback $dir --yes"
}

rollback() {
  local dir="${1:-}"; [ -d "$dir" ] && [ "${2:-}" = --yes ] || die "usage: rollback <backup-dir> --yes"
  ( cd "$dir" && sha256sum -c --quiet SHA256SUMS ) || die "backup checksum mismatch"
  crontab "$dir/crontab.before"; echo "crontab restored"
  local t en ac
  while read -r t en ac <&3; do
    [ -n "$t" ] || continue
    if [ "$en" = enabled ]; then sudo systemctl enable "$t"; echo "enabled $t"; fi
    if [ "$ac" = active ]; then sudo systemctl start "$t"; echo "started $t"; fi
  done 3< "$dir/timers.before"
  if [ -f "$dir/user-timers.disabled" ]; then
    for t in $(cat "$dir/user-timers.disabled"); do systemctl --user enable --now "$t"; echo "enabled user timer $t"; done
  fi
  status
}

case "${1:-plan}" in
  plan)     echo "PLAN (read only). Would comment these crontab lines and disable these timers:"; status ;;
  verify)   status ;;
  apply)    shift; apply "$@" ;;
  rollback) shift; rollback "$@" ;;
  *)        die "mode must be plan|verify|apply|rollback" ;;
esac
