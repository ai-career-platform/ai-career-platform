# Crawler → GCP Cloud SQL daily posting sync (#337)

`crawler/jobs/gcp_sync.py` copies refined crawler postings from the Staging crawler DB
(`ai_career_crawler_training.crawler_training.postings`) into the GCP service DB
(`ai_career_poc`, schema `career`). It is one-way and additive: INSERT new, UPDATE changed
fields only, never DELETE. It starts no crawl and changes no crawler setting.

| Item | Value |
|---|---|
| Runs where | Staging host, inside the existing `backend` container (`docker compose exec`) |
| Source | existing `connect_configured_database()` (`crawler_staging@db:5432`, validator unchanged), READ ONLY |
| Target | TLS `verify-full`: `host` = Cloud SQL certificate SAN name, `hostaddr` = instance IP, instance CA |
| Target role | `career_sync` — grants in `target_grants.sql` (no DELETE, no DDL, no other tables) |
| Identity | `career.job_posting_external_refs (source_id, external_id)`; `data_sources.code = jobkorea_live` |
| Selected rows | `source_code = jobkorea_live` only (`GCP_SYNC_SOURCE_CODE`). Synthetic `jobkorea`, `jobkorea_imported` are skipped |
| Visibility | `GCP_SYNC_PUBLISH=0` (default) stores postings as `draft`, which the API never shows. `1` copies the source status |
| Run history | existing `career.ingestion_runs` (counters JSON in `error_summary`) |
| Schedule | cron `5 23 * * *` (host UTC) = **08:05 KST** |

## Guards (scheduled mode)

1. Skip inside the night window 21:00–08:00 KST (`NIGHT_WINDOW_OPEN`).
2. Skip while any crawler `runs`, `keyword_jobs` or `night_job_results` row is `RUNNING` (`CRAWLER_BUSY`).
3. Skip if a sync already succeeded since 08:00 KST today (`ALREADY_SYNCED_TODAY`).
4. One sync at a time: host `flock` plus a target session advisory lock (`SYNC_IN_PROGRESS`).

One run is one target transaction; any error rolls everything back and marks the run `failed`.
Connection/network errors are retried at most 3 times (60 s, 120 s). TLS errors are not retried.
A run killed mid-way is closed as `failed` (`STALE_RUN`) by the next run. Conflicts with postings of
another source (same URL, or a ref pointing to a foreign posting) are never overwritten; they are
counted as `failed` and the run is `PARTIAL`. Slack (existing webhook) gets one message per scheduled run.

## Files on the Staging host (`/home/kant/ai-career-staging-poc/gcp-sync/`, dir 700)

| File | Mode | Content |
|---|---|---|
| `run_gcp_sync.sh` | 700 | copy of this directory's wrapper from merged `main` |
| `gcp-sync.env` | 600 | `GCP_SYNC_TARGET_HOST`, `GCP_SYNC_TARGET_HOSTADDR`, `GCP_SYNC_TARGET_USER=career_sync`, `GCP_SYNC_TARGET_PASSWORD`, `GCP_SYNC_PUBLISH=0` |
| `server-ca.pem` | 644 | Cloud SQL instance CA (public certificate) |
| `logs/gcp-sync.log` | 600 | cron output (JSON lines, no secrets) |

## Commands

```bash
G=/home/kant/ai-career-staging-poc/gcp-sync
$G/run_gcp_sync.sh dry-run      # plan only
$G/run_gcp_sync.sh run          # manual run (worker guard only)
# enable (after merge + Auto-CD deploy + PM approval):
( crontab -l; echo "5 23 * * * $G/run_gcp_sync.sh scheduled >> $G/logs/gcp-sync.log 2>&1" ) | crontab -
# disable:
crontab -l | grep -v run_gcp_sync.sh | crontab -
```

Publishing to the public API is a separate PM decision: set `GCP_SYNC_PUBLISH=1` in `gcp-sync.env`
and run once; existing drafts are updated to their source status.

## Rollback (run as the `career` owner role on the target)

Before anyone has used the postings (no bookmarks/matches), remove everything this sync created:

```sql
BEGIN;
SELECT source_id AS s FROM career.data_sources WHERE code = 'jobkorea_live' \gset
DELETE FROM career.job_postings WHERE source_id = :'s';         -- cascades its external refs
DELETE FROM career.companies WHERE source_id = :'s';
DELETE FROM career.ingestion_runs WHERE source_id = :'s';
DELETE FROM career.data_sources WHERE source_id = :'s';
COMMIT;
-- as postgres: DROP ROLE career_sync;  (after REVOKE ALL / DROP OWNED BY career_sync)
```

`job_postings` deletes **cascade** to user bookmarks, match evaluations and recommendations. Once
postings are published and used, hide them instead: stop cron, set `GCP_SYNC_PUBLISH=0`, run once.
