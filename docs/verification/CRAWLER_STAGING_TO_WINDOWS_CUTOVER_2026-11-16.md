# Ubuntu Staging crawler stop and Windows cutover (2026-11-16)

Task: AI_CAREER_CRAWLER_STAGING_TO_WINDOWS_CUTOVER (parent #365).

**PM approval scope:** stopping the automatic crawl and GCP-sync runs on Ubuntu Staging only.

**Not approved, and not done:**
- Ubuntu DB changes, server shutdown or other services;
- Cloud SQL writes;
- Windows LIVE or scheduled sync;
- credential changes;
- network or firewall changes.

**Status words:** PASS, FAIL, PARTIAL, BLOCKED, NOT_RUN, PENDING. No secret values appear in this document.

## 1. Where the work ran

- **Ubuntu Staging:** reached from the existing management PC (Windows, host `GRMOON`) through the established SSH path. One connection attempt, which succeeded at 2026-11-16 22:50 KST.
- **The new Windows crawler PC** (`CRAWLER_NEW_PC_SETUP_2026-11-16.md`) cannot reach Staging on TCP 22, and that was not retried. The management PC is **not** the new crawler PC: it has no `C:\dev\crawler-data`, no `*_LOCAL` keys and no pgpass. So the new PC's local DB was **not** inspected in this task (§6).

## 2. Ubuntu state before the change (read-only, 2026-11-16 22:50 KST)

| Item | Observed |
|---|---|
| Deployed SHA (Auto-CD `success.json`, backend `APP_VERSION`) | `0edc1752ec3123a5e4df45f7584f84edbe0a3f19` (#372), deployed 13:18Z, health PASS |
| `kant` crontab | 3 lines: `@reboot … ngrok` (Redmine), `0 11 * * * … dbresting … backup.sh`, **`5 23 * * * …/gcp-sync/run_gcp_sync.sh scheduled >> …/gcp-sync.log 2>&1`** (08:05 KST) |
| `/etc/cron.d`, `/etc/crontab`, `cron.daily/hourly` | no ai-career, crawler or sync entries |
| System timers | `ai-career-crawler-dispatch.timer` enabled/active (every 5 min); `ai-career-staging-deploy.timer` enabled (Auto-CD, every minute); `ai-career-t154-night-20261108.timer` disabled, not scheduled |
| Dispatcher effective ExecStart | root drop-in `90-live-auto-off.conf` forces `-e CRAWLER_NIGHT_ENABLED=0 -e CRAWLER_LIVE_SCHEDULE_APPROVED=0` |
| LIVE flags | `.env` 0/0, running backend 0/0; recent dispatcher polls `night: DISABLED`, `external_requests: 0`; fixture schedule `jobkorea-daily` `enabled=false` |
| User systemd timers | only Ubuntu housekeeping (insights, launchpadlib); none for the crawler |
| Processes | no `gcp_sync`, `run_gcp_sync` or crawler process on the host or in the backend container; `gcp-sync/.lock` free |
| Night jobs | 2026-11-15: 1 (AX), 2026-11-12: 6; 0 `RUNNING`; runs `RUNNING` 0 |
| Last syncs (log) | `ce757d96` (11-14 23:05Z), **`045e68d4-e41d-41fa-8846-e720a7a883a7`** (started 2026-11-15T23:05:01.751457Z, ended 23:05:01.819938Z, SUCCEEDED, inserted 1) |

## 3. Backup before the change

Location (Ubuntu, `0700`/`0600`): `/home/kant/ai-career-staging-poc/backups/cutover-windows-20261116T135144Z/` (22 files).

Contents:
- `crontab.before`;
- `systemctl cat` and `show` output for the dispatcher service and timer, the deploy timer and the t154 timer. The root drop-in itself is unreadable; its effective ExecStart is captured through `show`;
- `timers.before`;
- `run_gcp_sync.sh` (copy);
- `gcp-sync.env.nonsecret` (the password is redacted);
- `gcp-sync.sha256` (env, CA, script);
- `last-sync-runs.jsonl`;
- `ps.before`, `compose-ps.before`;
- `deployed-sha`;
- `crawler-flags.before`;
- `ROLLBACK.txt`.

The script aborts unless the backup is complete. No PostgreSQL data was read into it or changed. **Status: PASS.**

## 4. Change made (Ubuntu)

Only the GCP-sync cron line was disabled, and only after these guards passed:
- no sync process;
- `flock -n gcp-sync/.lock` succeeded;
- exactly one matching line.

```diff
< 5 23 * * * /home/kant/ai-career-staging-poc/gcp-sync/run_gcp_sync.sh scheduled >> /home/kant/ai-career-staging-poc/gcp-sync/logs/gcp-sync.log 2>&1
---
> # CUTOVER-DISABLED 20261116T135144Z (PM: AI_CAREER_CRAWLER_STAGING_TO_WINDOWS_CUTOVER; restore by removing this prefix)
> #5 23 * * * /home/kant/ai-career-staging-poc/gcp-sync/run_gcp_sync.sh scheduled >> /home/kant/ai-career-staging-poc/gcp-sync/logs/gcp-sync.log 2>&1
```

| Check | Result |
|---|---|
| Active `run_gcp_sync` lines after the change | 0 |
| Other crontab lines (ngrok, dbresting backup) | byte-identical (diff check) |
| cron picked up the change | `2026-11-16T13:52:01Z cron: (kant) RELOAD (crontabs/kant)` |
| LIVE crawl schedule | not changed. It was already OFF on three independent layers (`.env` flags, backend env, root kill switch); the dispatcher timer is root-owned and only polls IDLE with 0 external requests. Disabling it needs root and was not part of this approval |
| Ubuntu PostgreSQL, containers, other services | unchanged (no restart, no DB write) |

## 5. 26-hour condition (code: `gcp_sync.CUTOVER_QUIET`)

- **The rule** (`other_writers`, `cutover_refusal`): a second writer may run only when it is confirmed and has an evidence reference, *and* every other writer's newest run in Cloud SQL `career.ingestion_runs` started more than 26 hours ago. Runs of any status count.
- **Cloud SQL now (read-only):** the only writer is Staging. Its newest run is `045e68d4…`, started `2026-11-15T23:05:01.751457Z`. No `local` writer run exists, and no cutover has been recorded.
- **Earliest point the condition can hold:** `2026-11-17T01:05:01.751Z` (**2026-11-17 10:05:01 KST**), but only if no Staging run starts before then.
- **Stopping the cron does not satisfy it by itself.** Current status: **NOT_MET (PENDING).**
- **Skipped 08:05 KST slot — PASS (checked 2026-11-17 08:07:58 KST, read-only):**
  - the kant crontab still has only the commented line (`#5 23 * * * …run_gcp_sync.sh`);
  - Staging `gcp-sync.log`: `wrapper_starts_after_stop=0`; the last `wrapper_start` is still `2026-11-15T23:05:01Z`;
  - `journalctl -u cron` for 23:00–23:10 UTC: 0 `run_gcp_sync` entries;
  - Cloud SQL `career.ingestion_runs`: `runs_after_045e68d4=0`.
- **Verification still needed:** the time is past 10:05:01 KST *and* there is still no Staging run in Cloud SQL. Re-check both right before the first Windows run; do not rely on this document alone.
- **Evidence reference proposed for `GCP_SYNC_CUTOVER_EVIDENCE`:** `UBUNTU-CRON-DISABLED-20261116T135144Z` (this document plus the backup directory above).

## 6. Windows PC (the new crawler PC)

Not inspected in this task: it has no Staging access, and this management PC is not that PC. All items below come from the repository documents, not from a check in this task.

| Item | Documented | Status here |
|---|---|---|
| main | `0edc175` (#371 + #372 merged) | verified on GitHub |
| Local PostgreSQL 18.7, 127.0.0.1:5432, `ai_career_crawler_training` | `CRAWLER_NEW_PC_SETUP_2026-11-16.md` | NOT_RUN (needs the new PC) |
| LIVE run `8e54090d-34ce-412a-88f1-9a693d0a47ed` | 7 HTTP, INSERT 5: 50224839, 50246410, 50309869, 50350626, 50359556 (`CRAWLER_STAGING_SAFETY_GATE.md`) | NOT_RUN locally |
| Single-writer guard | code `gcp_sync.other_writers`/`cutover_refusal`; tests on main | code present (main) |
| Windows schedules for LIVE or sync | must stay OFF | NOT_RUN (check on the new PC) |

Commands to run on the new PC (read-only):

```powershell
. .\scripts\windows\crawler-local-env.ps1
.\scripts\windows\crawler-status.ps1
.venv\Scripts\python.exe scripts\windows\verify_local_db.py --snapshot
Get-ScheduledTask | Where-Object TaskName -match 'crawler|gcp' | Select TaskName, State
```

## 7. GCP connection readiness

| Item | State |
|---|---|
| `career_sync` account | **EXISTS** in Cloud SQL. Not a superuser, no CREATEROLE, can log in. Grants match `poc/staging/automation/gcp-sync/target_grants.sql`: INSERT/SELECT on `companies`, `job_postings`, `job_posting_external_refs`, `ingestion_runs`; column-level UPDATE on `job_postings` (company_id, title, employment_type, location_text, source_url, status, published_at, expires_at, updated_at); no DELETE; no access to `users` |
| Cloud SQL CA | Public `Cloud SQL Server CA` (Google), valid until 2036-05-08. The file on Ubuntu `gcp-sync/server-ca.pem` has sha256 `56929694b62f95bff9769148d2f5e7bd220758b539a9e40d4d3659d321f38059`, and a byte-identical copy is prepared on the management PC. Only the public certificate; no key, no password |
| TLS host name | configured on Ubuntu as `GCP_SYNC_TARGET_HOST` / `HOSTADDR` (verify-full needs the host name in the server certificate's SAN plus a pinned host address). The value is not reproduced here; take it from the Ubuntu backup's `gcp-sync.env.nonsecret` |
| `career_sync` password for the new PC | not copied (out of scope). It needs a PM-approved secure hand-over, or rotation |
| Network | the new PC's egress address must be allowed by Cloud SQL. Network policy changes are out of scope: **BLOCKED (approval)** |
| GCP write approval C | **NOT_GRANTED**, so only dry-run preparation is possible |

## 8. Pre-checks for run `8e54090d` against the real target (read-only)

| Posting | In Cloud SQL `jobkorea_live` now | Expected on a real run |
|---|---|---|
| 50224839 | no | INSERT |
| 50246410 | yes (draft, synced 11-14) | DUPLICATE or UPDATE if fields differ |
| 50309869 | yes (draft, synced 11-14) | DUPLICATE or UPDATE |
| 50350626 | yes (draft, synced 11-16 08:05) | DUPLICATE or UPDATE |
| 50359556 | no | INSERT |

- **The local mock rehearsal's INSERT 4 / DUPLICATE 1 does not apply to production.** That mock reproduced only 50350626 in its target.
- **Expected on the real target:** at most 2 inserts, and 3 existing refs that are either unchanged or updated. A `dry-run` on the new PC against the real target, after approval C and network access, is the authoritative figure.
- **Other conditions:**
  - Fixtures are excluded by the `harvest_items` filter on main, and drafts are kept (`GCP_SYNC_PUBLISH=0`).
  - Single writer: Staging is now stopped; the 08:05 KST slot was skipped; the 26-hour condition is PENDING until 10:05:01 KST (§5).
  - Cutover evidence is proposed in §5.

## 9. Rollback (prepared, not executed)

1. Get the PM's rollback approval.
2. On the new PC, turn off any Windows sync or LIVE task. Confirm in Cloud SQL `ingestion_runs` whether a `local` writer has run.
   - **If one has**, the Staging code (also `0edc175`) will see `local` as another writer and refuse with `OTHER_SYNC_SOURCE_ACTIVE`. A Staging resume then needs its own cutover confirmation, evidence, and 26 hours of quiet from the local writer.
3. Restore the single cron line on Ubuntu, keeping every other line:

   ```sh
   crontab -l > /home/kant/ai-career-staging-poc/backups/crontab.pre-rollback.$(date -u +%Y%m%dT%H%M%SZ)
   crontab -l | grep -v '^# CUTOVER-DISABLED 20261116T135144Z' \
     | sed 's|^#5 23 \* \* \* /home/kant/ai-career-staging-poc/gcp-sync/run_gcp_sync.sh|5 23 * * * /home/kant/ai-career-staging-poc/gcp-sync/run_gcp_sync.sh|' | crontab -
   crontab -l | grep -c '^5 23 .*run_gcp_sync.sh'   # expect 1
   ```

   Alternatively use the full `crontab.before` from the backup, if no other line has changed since.
4. systemd: nothing was changed, so nothing needs restoring. The dispatcher, the kill switch and the deploy timer are as they were.
5. Check the next 08:05 KST run in `gcp-sync.log` and in `career.ingestion_runs`.

**Status: READY (not executed).**

## 10. Result

```
STAGING_CONNECTION=OK (management PC GRMOON, existing SSH path; 1 attempt)
STAGING_LIVE_SCHEDULE_BEFORE=OFF (flags 0/0 in .env and backend; root kill switch; dispatcher timer polls IDLE, 0 requests)
STAGING_LIVE_SCHEDULE_AFTER=OFF (unchanged; dispatcher timer still enabled, root-owned)
STAGING_GCP_SYNC_BEFORE=ACTIVE (kant crontab, 5 23 * * * UTC = 08:05 KST)
STAGING_GCP_SYNC_AFTER=DISABLED (line commented; cron RELOAD 13:52:01Z; 0 active lines)
STAGING_SYNC_PROCESS_RUNNING=NO
STAGING_LAST_SYNC_TIME=2026-11-15T23:05:01.819938Z ended (started 23:05:01.751457Z), run 045e68d4
STAGING_SYNC_STOP_EVIDENCE=backups/cutover-windows-20261116T135144Z + crontab diff + cron RELOAD; skipped 2026-11-17 08:05 KST slot verified 08:07:58 KST (0 wrapper starts, 0 cron entries, 0 new ingestion_runs)
STAGING_POSTGRESQL_PRESERVED=YES (no writes)
STAGING_OTHER_SERVICES_UNCHANGED=YES
WINDOWS_LOCAL_DB=NOT_RUN (new PC not reachable from this task)
WINDOWS_LIVE_POSTINGS=5 (documented, run 8e54090d; not re-checked)
WINDOWS_GCP_SYNC_READY=PARTIAL (code on main; credentials, network and approval C pending)
CAREER_SYNC_ACCOUNT=EXISTS (minimal grants verified)
GCP_CA=READY (public CA, sha256 56929694…)
GCP_HOSTNAME=CONFIGURED_ON_UBUNTU (value withheld; transfer with the CA)
GCP_NETWORK=BLOCKED (approval needed for the new PC's egress)
GCP_WRITE_APPROVAL=NOT_GRANTED
CUTOVER_26H_CONDITION=NOT_MET (earliest 2026-11-17 10:05:01 KST, if no Staging run happens)
CUTOVER_EVIDENCE_REF=UBUNTU-CRON-DISABLED-20261116T135144Z (proposed)
ROLLBACK_READY=YES
```
