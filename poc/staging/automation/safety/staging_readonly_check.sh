#!/usr/bin/env bash
# Usage on the Staging host (as the deploy user, from any directory):
#   bash staging_readonly_check.sh > staging-check-$(date +%Y%m%d-%H%M%S).txt 2>&1
# Or from a machine that can reach it: ssh <staging> 'bash -s' < staging_readonly_check.sh > out.txt
# READ-ONLY Staging safety check (AI_CAREER_CRAWLER_STAGING_SAFETY_GATE). Changes nothing:
# no writes, no restarts, no config edits; secret files are only tested for existence; env vars SET/UNSET only.
set -u
B=/home/kant/ai-career-staging-poc
P=ai-career-staging-poc
sec() { printf '\n===== %s =====\n' "$1"; }
sec "host"; hostname; date -u +%FT%TZ; id -un; uptime
sec "1. containers"; cd "$B" 2>/dev/null && docker compose --project-name $P ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}' 2>&1
sec "2. timers"; systemctl list-timers 'ai-career-*' --all --no-pager 2>&1 | head -20
systemctl is-enabled ai-career-crawler-dispatch.timer ai-career-t154-night-20261108.timer 2>&1
sec "3. gcp-sync cron"; echo "crontab_lines_with_run_gcp_sync=$(crontab -l 2>/dev/null | grep -c run_gcp_sync.sh)"
crontab -l 2>/dev/null | grep run_gcp_sync.sh | sed -E 's/(PASSWORD|TOKEN)=[^ ]*/\1=<redacted>/g'
sec "3b. gcp-sync files (existence only)"; ls -la "$B/gcp-sync" 2>&1 | awk '{print $1, $5, $6, $7, $8, $9}'
ls -la "$B/gcp-sync/logs" 2>&1 | awk '{print $1, $5, $6, $7, $8, $9}'
sec "10. gcp-sync log (status lines only)"
if [ -f "$B/gcp-sync/logs/gcp-sync.log" ]; then
  wc -l < "$B/gcp-sync/logs/gcp-sync.log"
  grep -o '"\(wrapper_start\|mode\|status\|error_code\|run_id\|inserted\|updated\|fetched\|publish\|source_code\)": *"\?[^,"}]*' "$B/gcp-sync/logs/gcp-sync.log" | tail -n 40
else echo "NO_GCP_SYNC_LOG"; fi
sec "backend live/gcp env (SET/UNSET only)"
docker compose --project-name $P exec -T backend sh -c 'for v in CRAWLER_DB_MODE CRAWLER_NIGHT_ENABLED CRAWLER_LIVE_SCHEDULE_APPROVED CRAWLER_NIGHT_POLICY_FILE GCP_SYNC_PUBLISH GCP_SYNC_TARGET_HOST SLACK_WEBHOOK_URL; do if [ -n "$(printenv $v)" ]; then echo "$v=SET"; else echo "$v=UNSET"; fi; done' 2>&1
sec "deployed version"; curl -s --max-time 5 http://127.0.0.1:8000/api/version 2>/dev/null || docker compose --project-name $P exec -T backend sh -c 'cat /app/VERSION 2>/dev/null || echo NO_VERSION_FILE'
sec "4-9. database (READ ONLY)"
docker compose --project-name $P exec -T db sh -c 'psql -X -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d ai_career_crawler_training' <<'SQL' 2>&1
\pset pager off
BEGIN READ ONLY;
SELECT version();
SELECT source_code, count(*), min(updated_at), max(updated_at) FROM crawler_training.postings GROUP BY 1 ORDER BY 1;
SELECT external_posting_id, payload->>'source_url' AS url, payload->>'title' AS title, payload->>'company_name' AS company,
       payload->>'published_on' AS published, payload->>'expires_on' AS expires, updated_at
  FROM crawler_training.postings WHERE source_code = 'jobkorea_live' ORDER BY updated_at;
SELECT run_id, mode, trigger, status, started_at, ended_at, fetched_count, inserted_count FROM crawler_training.runs ORDER BY started_at;
SELECT (SELECT count(*) FROM crawler_training.night_job_results) AS night_jobs,
       (SELECT count(*) FROM crawler_training.keyword_jobs) AS keyword_jobs;
SELECT external_posting_id, array_agg(source_code) FROM crawler_training.postings GROUP BY 1 HAVING count(*) > 1;
SELECT k.keyword, d.external_posting_id, d.first_seen_at FROM crawler_training.keyword_posting_discoveries d
  JOIN crawler_training.search_keywords k USING (keyword_id) WHERE d.source_code = 'jobkorea_live';
SELECT to_regclass('crawler_training.raw_artifacts') IS NOT NULL AS has_raw;
SELECT schedule_id, mode, enabled, local_time FROM crawler_training.schedules;
ROLLBACK;
SQL
sec "raw artifacts for the 5 rows (names only)"
docker compose --project-name $P exec -T db sh -c 'psql -X -At -U "${POSTGRES_USER:-postgres}" -d ai_career_crawler_training -c "BEGIN READ ONLY; SELECT count(*) FROM crawler_training.raw_artifacts; ROLLBACK;"' 2>&1
sec "shell history mentions of the live import (commands only, no secrets)"
grep -h -n 'import_jobkorea_html\|--list-url\|GI_Read' ~/.bash_history 2>/dev/null | sed -E 's/(PASSWORD|TOKEN|KEY)=[^ ]*/\1=<redacted>/g' | tail -n 20
sec "docker logs of backend around 2026-11-08 (live import JSON lines)"
docker compose --project-name $P logs --no-color --since 2026-11-08T00:00:00Z --until 2026-11-08T01:30:00Z backend 2>&1 | grep -i 'live_http\|imported_html\|GI_Read\|inserted' | tail -n 20
sec "outputs dir listing"; ls -la "$B/outputs" 2>&1 | head -30
sec "done"
