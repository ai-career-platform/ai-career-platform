#!/usr/bin/env bash
# READ-ONLY Staging safety check v2 (AI_CAREER_CRAWLER_STAGING_SAFETY_CHECK).
#
# Usage on the Staging host, as the deploy user (kant), from any directory:
#   bash staging_readonly_check.sh > staging-check-$(date +%Y%m%d-%H%M%S).txt 2>&1
# or from a machine that can reach it:
#   ssh <staging> 'bash -s' < staging_readonly_check.sh > out.txt
#
# Guarantees (review before running):
#  * No writes anywhere: no docker restart/up/down/cp-in, no crontab -e/-r, no systemctl start/stop/enable,
#    no file creation outside stdout. SQL runs only inside BEGIN READ ONLY ... ROLLBACK.
#  * Secrets: environment variables are reported as SET/UNSET only; secret files are tested for existence
#    and mode only; the single value printed from gcp-sync.env is GCP_SYNC_PUBLISH (0/1, not a secret).
#  * Everything printed passes through redact(): KEY=value pairs for password/token/secret/key/webhook
#    names, credentials inside URLs (scheme://user:pass@), Slack webhook paths and PEM blocks are masked.
#  * Job postings contain public company/job data only (no personal data is selected).
set -u
B=/home/kant/ai-career-staging-poc
P=ai-career-staging-poc
dc() { docker compose --project-name "$P" "$@"; }
sec() { printf '\n===== %s =====\n' "$1"; }
redact() {
  sed -E \
    -e 's#([A-Za-z0-9_]*(PASS|PASSWORD|TOKEN|SECRET|KEY|WEBHOOK|RUL)[A-Za-z0-9_]*)=[^[:space:]"]+#\1=<redacted>#Ig' \
    -e 's#(://)[^/@[:space:]]+@#\1<redacted>@#g' \
    -e 's#hooks\.slack\.com/services/[A-Za-z0-9/_-]+#hooks.slack.com/services/<redacted>#g' \
    -e '/-----BEGIN [A-Z ]+-----/,/-----END [A-Z ]+-----/c\<pem redacted>'
}
psql_ro() {  # $1 = database; SQL on stdin; always READ ONLY
  dc exec -T db sh -c "psql -X -v ON_ERROR_STOP=1 -P pager=off -U \"\${POSTGRES_USER:-postgres}\" -d $1"
}

main() {
sec "0. host / time"; hostname; date -u +%FT%TZ; date; id -un; uptime

sec "1. containers and images"
cd "$B" 2>/dev/null || echo "NO_BASE_DIR $B"
dc ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Image}}' 2>&1
dc images 2>&1 | head -10

sec "2. deployed code version"
curl -s --max-time 5 http://127.0.0.1:8000/api/version 2>/dev/null; echo
git -C "$B" log -1 --format='%H %cd' 2>/dev/null || echo "NO_GIT_CHECKOUT"
dc exec -T backend sh -c 'cat /app/VERSION /app/.version 2>/dev/null; ls -la /app/crawler/jobs/gcp_sync.py 2>&1; sha256sum /app/crawler/jobs/gcp_sync.py 2>&1' 2>&1
echo "fail_closed_guard_present=$(dc exec -T backend sh -c 'grep -c SOURCE_PROVENANCE_REQUIRED /app/crawler/jobs/gcp_sync.py 2>/dev/null || echo 0' 2>/dev/null | tr -d '\r')"
echo "local_source_mode_present=$(dc exec -T backend sh -c 'grep -c GCP_SYNC_SOURCE /app/crawler/jobs/gcp_sync.py 2>/dev/null || echo 0' 2>/dev/null | tr -d '\r')"

sec "3. timers (dispatcher / night)"
systemctl list-timers 'ai-career-*' --all --no-pager 2>&1 | head -20
for t in ai-career-crawler-dispatch.timer ai-career-t154-night-20261108.timer ai-career-staging-deploy.timer; do
  printf '%s enabled=%s active=%s\n' "$t" "$(systemctl is-enabled "$t" 2>&1)" "$(systemctl is-active "$t" 2>&1)"
done

sec "4. GCP sync cron"
printf 'cron_daemon_active=%s\n' "$(systemctl is-active cron 2>&1)"
echo "user_crontab_lines_with_run_gcp_sync=$(crontab -l 2>/dev/null | grep -c run_gcp_sync.sh)"
echo "user_crontab_commented_lines=$(crontab -l 2>/dev/null | grep run_gcp_sync.sh | grep -c '^[[:space:]]*#')"
crontab -l 2>/dev/null | grep run_gcp_sync.sh
echo "system_cron_files_with_gcp_sync=$(grep -rl 'gcp_sync\|run_gcp_sync' /etc/cron* 2>/dev/null | wc -l)"
grep -rl 'gcp_sync\|run_gcp_sync' /etc/cron* 2>/dev/null
echo "systemd_units_with_gcp_sync=$(systemctl list-unit-files --no-pager 2>/dev/null | grep -ci gcp)"
echo "--- cron executions (syslog/journal, last 14 days)"
journalctl -u cron --since '14 days ago' --no-pager 2>/dev/null | grep -i 'run_gcp_sync' | tail -n 20
grep -h 'run_gcp_sync' /var/log/syslog /var/log/syslog.1 2>/dev/null | tail -n 20

sec "5. gcp-sync directory (existence/mode only)"
ls -la "$B/gcp-sync" 2>&1 | awk '{print $1, $3, $5, $6, $7, $8, $9}'
ls -la "$B/gcp-sync/logs" 2>&1 | awk '{print $1, $3, $5, $6, $7, $8, $9}'
if [ -f "$B/gcp-sync/gcp-sync.env" ]; then
  echo "gcp_sync_env_mode=$(stat -c %a "$B/gcp-sync/gcp-sync.env")"
  echo "GCP_SYNC_PUBLISH_value=$(grep -E '^GCP_SYNC_PUBLISH=' "$B/gcp-sync/gcp-sync.env" | head -1 | cut -d= -f2 | tr -cd '01')"
  echo "keys_present=$(grep -oE '^[A-Z_]+=' "$B/gcp-sync/gcp-sync.env" | tr -d '=' | tr '\n' ' ')"
  echo "target_user_is_career_sync=$(grep -cE '^GCP_SYNC_TARGET_USER=career_sync$' "$B/gcp-sync/gcp-sync.env")"
else echo "NO_GCP_SYNC_ENV_FILE"; fi
echo "lock_file=$(ls -la "$B/gcp-sync/.lock" 2>&1 | awk '{print $6, $7, $8}')"

sec "6. GCP sync history (log: status fields only)"
L="$B/gcp-sync/logs/gcp-sync.log"
if [ -f "$L" ]; then
  echo "log_lines=$(wc -l < "$L")"
  echo "wrapper_starts=$(grep -c wrapper_start "$L")"
  grep -oE '"(wrapper_start|mode|status|error_code|reason|run_id|fetched|inserted|updated|duplicate|skipped|failed|publish|source_code|attempts|started_at|ended_at)": *("[^"]*"|[0-9a-z]+)' "$L" | tail -n 80
else echo "NO_GCP_SYNC_LOG"; fi
echo "--- running sync / crawler processes"
pgrep -af 'gcp_sync|run_gcp_sync|import_jobkorea_html|harvest' 2>/dev/null || echo "none"
dc exec -T backend sh -c 'ps -eo pid,etime,args 2>/dev/null | grep -E "gcp_sync|import_jobkorea|harvest" | grep -v grep || echo none' 2>&1

sec "7. backend live/gcp env (SET/UNSET only)"
dc exec -T backend sh -c 'for v in CRAWLER_DB_MODE CRAWLER_NIGHT_ENABLED CRAWLER_LIVE_SCHEDULE_APPROVED CRAWLER_NIGHT_POLICY_FILE GCP_SYNC_PUBLISH GCP_SYNC_TARGET_HOST GCP_SYNC_ALLOW_UNVERIFIED_STAGING SLACK_WEBHOOK_URL SLACK_WEBHOOK_RUL; do if [ -n "$(printenv $v)" ]; then echo "$v=SET"; else echo "$v=UNSET"; fi; done' 2>&1

sec "8. crawler DB (READ ONLY)"
psql_ro ai_career_crawler_training <<'SQL' 2>&1
BEGIN READ ONLY;
SHOW track_commit_timestamp;
SELECT source_code, count(*), min(updated_at), max(updated_at) FROM crawler_training.postings GROUP BY 1 ORDER BY 1;
-- the jobkorea_live rows: id, url, public job fields, last write, row creation transaction
SELECT external_posting_id, payload->>'source_url' AS url, payload->>'title' AS title, payload->>'company_name' AS company,
       payload->>'location_text' AS location, payload->>'published_on' AS published, payload->>'expires_on' AS expires,
       updated_at, xmin::text AS insert_xid
  FROM crawler_training.postings WHERE source_code = 'jobkorea_live' ORDER BY updated_at, external_posting_id;
-- synthetic markers: long synthetic ids, fixture titles, non-JobKorea urls
SELECT count(*) FILTER (WHERE length(external_posting_id) > 8) AS long_ids,
       count(*) FILTER (WHERE payload->>'title' ILIKE '%합성%' OR payload->>'title' ILIKE '%synthetic%' OR payload->>'title' ILIKE '%fixture%') AS synthetic_titles,
       count(*) FILTER (WHERE payload->>'source_url' !~ '^https://(www\.)?jobkorea\.co\.kr/Recruit/GI_Read/[0-9]+$') AS non_jobkorea_urls
  FROM crawler_training.postings WHERE source_code = 'jobkorea_live';
SELECT run_id, mode, trigger, status, started_at, ended_at, fetched_count, inserted_count, error_code FROM crawler_training.runs ORDER BY started_at;
SELECT (SELECT count(*) FROM crawler_training.night_job_results) AS night_jobs,
       (SELECT count(*) FROM crawler_training.keyword_jobs) AS keyword_jobs,
       (SELECT count(*) FROM crawler_training.run_events) AS run_events;
SELECT k.keyword, d.external_posting_id, d.first_seen_at, d.last_seen_at FROM crawler_training.keyword_posting_discoveries d
  JOIN crawler_training.search_keywords k USING (keyword_id) WHERE d.source_code = 'jobkorea_live' ORDER BY d.first_seen_at;
SELECT external_posting_id, array_agg(source_code ORDER BY source_code) FROM crawler_training.postings GROUP BY 1 HAVING count(*) > 1;
SELECT schedule_id, mode, enabled, local_time FROM crawler_training.schedules;
SELECT to_regclass('crawler_training.harvest_runs') IS NOT NULL AS has_harvest_ledger;
ROLLBACK;
SQL
echo "--- commit timestamps (only if track_commit_timestamp=on)"
psql_ro ai_career_crawler_training <<'SQL' 2>&1
BEGIN READ ONLY;
SELECT external_posting_id, pg_xact_commit_timestamp(xmin) FROM crawler_training.postings
 WHERE source_code = 'jobkorea_live' AND current_setting('track_commit_timestamp') = 'on';
ROLLBACK;
SQL

sec "9. fixture/test match of the jobkorea_live ids (deployed image files)"
IDS=$(psql_ro ai_career_crawler_training <<'SQL' 2>/dev/null | grep -E '^[0-9]+$'
\pset tuples_only on
\pset format unaligned
BEGIN READ ONLY;
SELECT external_posting_id FROM crawler_training.postings WHERE source_code = 'jobkorea_live';
ROLLBACK;
SQL
)
for id in $IDS; do
  n=$(dc exec -T backend sh -c "grep -rl '$id' /app/crawler/fixtures /app/crawler/tests 2>/dev/null | wc -l" 2>/dev/null | tr -d '\r')
  echo "id=$id fixture_or_test_files_mentioning=$n"
done

sec "10. evidence of the 2026-11-08 import (read only)"
echo "--- deploy journal 2026-11-08 08:30-10:30 KST"
journalctl --since '2026-11-08 08:30' --until '2026-11-08 10:30' --no-pager 2>/dev/null | grep -iE 'deploy|ai-career|import_jobkorea|live' | tail -n 30
echo "--- backend logs 2026-11-08 (UTC 23:30 prev day - 01:30)"
dc logs --no-color --since 2026-11-07T23:30:00Z --until 2026-11-08T01:30:00Z backend 2>&1 | grep -iE 'live_http|imported_html|GI_Read|inserted|STOPPED' | tail -n 30
echo "--- shell history mentions"
grep -h -n 'import_jobkorea_html\|--list-url\|GI_Read\|policy-file' ~/.bash_history 2>/dev/null | tail -n 30
echo "--- outputs directory"
ls -la "$B/outputs" 2>&1 | head -40
find "$B/outputs" -maxdepth 3 -newermt '2026-11-08 08:00' ! -newermt '2026-11-08 11:00' -printf '%TY-%Tm-%Td %TH:%TM %p\n' 2>/dev/null | head -40
echo "--- T61 approval files (existence only)"
dc exec -T backend sh -c 'ls -la /run/secrets 2>/dev/null; for v in CRAWLER_NIGHT_POLICY_FILE; do f=$(printenv $v); [ -n "$f" ] && ls -la "$f"; done; echo checked' 2>&1
find "$B" -maxdepth 3 -iname '*approval*.json' -o -maxdepth 3 -iname '*policy*.json' 2>/dev/null | head

sec "11. service DB visible from Staging? (READ ONLY; only if a local career schema exists)"
psql_ro postgres <<'SQL' 2>&1
BEGIN READ ONLY;
SELECT datname FROM pg_database WHERE datname NOT IN ('template0','template1') ORDER BY 1;
ROLLBACK;
SQL

sec "done"; date -u +%FT%TZ
}

main 2>&1 | redact
