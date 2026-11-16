# feat(crawler): Windows local crawler and safe GCP sync cutover

> PR body for `feat/crawler-windows-local-pc` → `main`.
> PR #371 is merged (`a134e40`). This branch already contains it: `129d1e1` merges main and resolves the 2 `gcp_sync.py` hunks exactly as on the tested `integration/pr371-windows-crawler` (`558e48e`, identical tree). The diff against main holds only this branch's changes.
> Do not merge without an independent approving review and green CI.

## 1. Purpose

Move crawler collection to a dedicated Windows PC, and prepare the first safe GCP transfer of its real postings.

- **One source of truth:** only one machine writes to GCP at a time.
- **Origin enforced:** no unproven or test rows reach production.

## 2. Windows PC (results)

- **Stack:** Windows 11, Python 3.12, local PostgreSQL 18.7 on loopback, least-privilege `crawler_local`.
- **Schema:** migrations 0002–0013.
- **Scheduler:** supervised PostgreSQL host plus a fixture-only scheduler with automatic OFF on expiry.
- **Scripts:** status and reboot checks, and fault scenarios (`scripts/windows/*`).
- **Not done:** an elevated install and the logoff/reboot tests need admin rights. See `CRAWLER_WINDOWS_UNATTENDED_READINESS.md`.

## 3. First real LIVE run (evidence)

- **Run:** `8e54090d-34ce-412a-88f1-9a693d0a47ed`, approval B (PM risk acceptance), keyword AX, search page 1.
- **Requests:** 7 HTTP requests, 20 links.
- **Result:** **5 inserted**, 0 failed.
- **Turned off afterwards:** the approval file was deleted right after the run.
- **Note:** JobKorea permission is not obtained; the API application is pending.

## 4. GCP sync protections (`crawler/jobs/gcp_sync.py`)

- **Local source (`GCP_SYNC_SOURCE=local`):** only postings of named, finished LIVE harvest runs with real HTTP are synced.
  - Selection is through the `harvest_items` ledger, with `updated_at ≤ run end`.
  - Fixture and test rows can't be selected.
- **Verify mode:** compares source and target read-only.
- **Defaults kept:** drafts by default, one target transaction per run, run-scoped rollback, an admin login is refused, and TLS is `verify-full`.

## 5. Staging provenance (per row, replaces any blanket block)

- **Rule (`STAGING_PROVENANCE_SQL`):** a Staging row syncs only when it was discovered, first or last seen, inside a finished night job with HTTP > 0 that ran inside its own night (21:00–08:00 KST), **and its stored payload was last written no later than that job ended**. A later overwrite, e.g. a test or CLI import reusing the id, is not proven.
  - Night jobs only exist after `live_gate()` returns ALLOWED.
  - Every other row is skipped as `PROVENANCE_UNVERIFIED`. That covers the 2026-11-08 CLI imports, clock-injected tests and failed jobs.
- **Approved rows keep syncing.**
- **Same rule in the check script:** the read-only Staging check script (section 8b) uses the same rule. A PostgreSQL test runs both on the same rows and requires identical results.

## 6. Dual-sync prevention

- **Writer recorded:** each run records its writer (`local` / `staging`) in `error_summary`. Runs of the old deployed code count as `staging`.
- **Second writer refused:** a run refuses while another writer is active — runs of any status count, since a PARTIAL run is stored as failed. There is no time window. A writer counts as retired only once this writer completes a confirmed cutover run after that writer's last run.
  - The refusal is `FAILED`, or `SKIPPED` for the scheduled run.
  - Codes, in order: `OTHER_SYNC_SOURCE_ACTIVE` (no `GCP_SYNC_CUTOVER_CONFIRMED=1`), `OTHER_SYNC_RUNNING`, `OTHER_SYNC_RECENT` (the other writer synced within 26 h, so its daily cron has not provably stopped), `CUTOVER_EVIDENCE_REQUIRED`.
  - The evidence reference is recorded in `error_summary.cutover`.
- **Crash and alert handling:** the running row carries its writer from insertion, and stale-run cleanup keeps it, so a crash never blocks its own writer. A refused scheduled run sends a Slack notice.
- **Wrapper:** cutover confirmation and evidence are per-invocation wrapper parameters, not stored settings.
- **Dry-run and verify** report `other_writers` and `already_in_target`.

## 7. Tests

Run on `558e48e`, whose tree is identical to this PR's head `129d1e1`, on a freshly created disposable PostgreSQL 18.7 cluster (port 5436). 17 steps, 0 failures, 0 outside network requests. Log: `C:\dev\crawler-data-int3\logs\tests-20261116-214411`.

| Suite | Ran | Pass | Fail | Skip |
|---|---|---|---|---|
| Crawler unit | 554 | 549 | 0 | 5 (Linux-only) |
| Backend | 21 | 21 | 0 | 0 |
| PostgreSQL | 99 | 98 | 0 | 1 |

- **PostgreSQL by step:**
  - gcp-sync 12/12 (with #371's date fix);
  - local-source 7/7 and staging-provenance 8/8;
  - harvest 9/9, html 2/2, t64 14/14;
  - night executor/caller 15 + 1 skip, night integration 13/13, night e2e 7/7;
  - t155 read 3/3, t155 write 6/6, t152 2/2.
- **Not run:**
  - staging-mode and t64-permissions, which hard-code `db:5432`;
  - the Docker container test (Docker isn't installed).

- **Real-data dry-run:** run `8e54090d` against a disposable TLS target that already holds Staging's 50350626 gave 4 inserts and 1 duplicate. The real run was refused (`OTHER_SYNC_SOURCE_ACTIVE`) and wrote nothing.
- **TLS rehearsal:** 1,050 rows went through dry-run → run → verify → re-run → rollback. Negative cases (wrong certificate name, admin login, fixture run) were refused.
- **Conflict with #371** is in `gcp_sync.py` (2 hunks). Resolution: the provenance skip goes through #371's `Plan.skip()` before `selected_changed` counting, and both helper sets are kept.
  - **Checked mechanically:** all 42 lines #371 adds to `gcp_sync.py` are present. All 10 of #371's other files are intact.
  - **Of the Windows side's 274 added lines**, only the old `skipped.append` line is replaced by that `skip()` call.

## 8. Operational scope of this PR

- **No deploy, no production or GCP write, no cron or credential change.**
- **Changes once deployed to Staging:**
  - the Staging sync skips unproven rows;
  - it refuses to run while another writer (`local`) has synced since Staging's last confirmed cutover. There is no time window.
  - Today no other writer exists, so the 08:05 cron keeps syncing proven rows.
  - No target migration is needed. If the provenance tables are missing on Staging, every row is skipped (fail-closed).
- **New migration 0013** (harvest tables): applied manually, never at startup.

## 9. Not done / follow-ups

- **Staging read-only check:** `poc/staging/automation/safety/staging_readonly_check.sh`, SHA-256 `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd`. It needs someone with Staging access; the 29 Staging rows are **not** classified yet.
- **Approval C:** production `career_sync`, Cloud SQL CA and hostname, network path, and the GCP write approval.
- **Credential rotation:** Staging `crawler_staging`, Staging SSH, Slack webhook, Cloud SQL admin login.
- **Volume:** the 1,000-a-day target (GOAL 3) depends on JobKorea permission or API approval.

## 9b. Independent review (pre-PR)

An independent review of the integration diff was given the code only, not this PR's conclusions. It found:
- a single-writer bypass via PARTIAL runs;
- a Staging payload overwritten after its proving job could still sync;
- a crashed run that blocked its own writer;
- bypass of the cutover rule by waiting 7 days;
- a malformed-summary DoS;
- analyzer, check-script redaction and alerting gaps.

All are fixed in `efa436a` with tests. That review is not a GitHub approval; this PR still needs one.

## 10. Review checklist

- [ ] `STAGING_PROVENANCE_SQL`: can any row without a gate-approved night job pass? Are time-zone and night-window bounds correct (server time zone independent)?
- [ ] Is `plan()` skip ordering compatible with #371's `check_accounting` (every row in one bucket)?
- [ ] Can `other_writers` / `cutover_refusal` be bypassed (NULL or legacy `error_summary`, stale `running` rows, clock skew)?
- [ ] Local source: only `mode='live'`, finished, HTTP > 0 runs; `updated_at ≤ ended_at`.
- [ ] T61 gate harvest scope is opt-in; existing night approvals behave exactly as before.
- [ ] `staging_readonly_check.sh` is strictly read-only and prints no secrets.
- [ ] No secrets in code, logs or tests; `.env` is never read by the sync.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
