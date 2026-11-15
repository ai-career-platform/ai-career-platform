# Crawler recovery verification — 2026-11-16

Parent: #365 (with #366, #367, #368, #369, #370) · Code: PR #371 · Night of 2026-11-15 KST.

The status words used here are PASS, FAIL, PARTIAL, BLOCKED, NOT_RUN and PENDING. *Isolated* means a
throwaway PostgreSQL 18 database or a network-less container. *Staging* means the real Staging host
and crawler database. *Cloud SQL* means the GCP service database (read-only queries only).

## Answers for the PM

1. **Is the crawler code itself sound?** Yes, within what was tested.
   - PR #371 passes every isolated PostgreSQL 18 suite, including 4 new scenario tests.
   - The one live job tonight collected and stored correctly: 7 requests, 5 details, 1 new posting.
   - Review fixed one hardening issue (§4). One known limitation remains, P1: an explicit "closed" state is not parsed (§6, scenario 11).
2. **What has to be approved to resume LIVE through the normal scheduler?** Three items, all
   operations; none is a code change.
   - A root change: a time-bounded `95-t61-night.conf` override with a transient removal timer (§9).
     It is verified in an isolated user-systemd copy.
   - A new finite T61 approval for that night.
   - The `.env` flags set for that night only.
3. **What is verified end to end, and what is left?**
   - **Live → Staging:** verified for 1 keyword (job `16a8fc29`, 1 new posting).
   - **Staging → Cloud SQL:** verified (08:05 run `045e68d4`, inserted 1, posting 50350626 draft, 29/29 fields match).
   - **08:01 revert:** verified (no-op, self-removed).
   - **Not verified:** a full 6-keyword night through the systemd timer (BLOCKED by the kill switch); #371 behaviour in production (not deployed).

## 1. Baseline (checked 2026-11-15 22:16 KST)

| Item | Value | Status |
|---|---|---|
| main | `1797f4ce8a541a1e06368296ed0cdbb04bac6c7b` | — |
| Staging deployed (Auto-CD `success.json`, backend `APP_VERSION`) | `1797f4c…`, health PASS | PASS |
| PR #371 head | see the PR (this document is on its branch) | — |
| Staging `.env` flags / running backend env | `CRAWLER_NIGHT_ENABLED=0`, `CRAWLER_LIVE_SCHEDULE_APPROVED=0` / `0`/`0` | PASS |
| Live gate in the backend (no HTTP) | `PM_ACTIVATION_REQUIRED` | PASS |
| Dispatcher unit | drop-in `90-live-auto-off.conf` loaded; timer active, polls every 5 min | — |
| Dispatcher polls since the stop (13:03Z) | `night: DISABLED`, 0 HTTP | PASS |
| Running jobs | night `RUNNING` 0, runs `RUNNING` 0 | PASS |
| Staging data | `jobkorea_live` 29 (28 + 50350626), `jobkorea` 2, `jobkorea_imported` 28 | PASS |
| Public API (#342) | 76 public postings; 0 of the 28 draft `jobkorea_live` postings exposed | PASS |

## 2. LIVE block state

- **LIVE is off through three independent layers:**
  - the `.env` flags are 0;
  - the running backend env is 0;
  - the root drop-in passes `-e …=0` on every timer run.
- **The approval expires at 08:00 KST.** The one-night T61 file (`jobkorea-t61-night-20261116.json`, valid until `2026-11-15T23:00:00Z`) gives `EXPIRED` from then on. This was checked offline in the backend.
- **The 08:01 KST revert cron is a no-op check.** `t61-oneshot/revert.sh` calls `apply_flags.sh 0`. That script was made idempotent after the stop: when `.env` and the container are already 0 it changes nothing and restarts nothing. The cron then removes its own line.
- **No manual runs after the stop.** One manual dispatcher run happened before the stop (§13).

## 3. Code problems and operations/policy problems

| # | Problem | Kind | State |
|---|---|---|---|
| 1 | No LIVE collection since 11-13: the one-night approval expired, then the flags were turned off | Operations/policy | Fixed for one job tonight; a scheduler-path night is BLOCKED by #2 |
| 2 | The root drop-in `90-live-auto-off.conf` (11-13 22:36Z, #336 rollout) forces the timer OFF regardless of `.env` | Operations | Root cause confirmed; recovery procedure tested (§8–9); needs PM and root approval |
| 3 | Ceiling of 30 details per night (6 keywords × page 1 × 5) | Policy/approval scope | Unchanged by design; see §17 |
| 4 | 17% of detail requests on 11-12 repeated a posting another keyword had already fetched that night | Code | Fixed in #371 (§4, §7) |
| 5 | No per-record skip evidence; the Slack text mixed the crawl and sync stages | Code | Fixed in #371 (§8) |
| 6 | Skip predicate parsed the ID by string splitting | Code (found in this review) | Fixed in #371 `6c45cbf` |
| 7 | Explicit closed or removed postings are not detected; only a changed `validThrough` is | Code (limitation) | Deadline path verified end to end (§6.1); explicit close BLOCKED on a real sample (§6.1) |
| 8 | A Staging DB credential was exposed in local session logs, and the DB is reachable from the LAN | Security/operations | Rotation procedure ready; BLOCKED on approval (§14) |
| 9 | `local_gcp_sync_pg.test_08` time bomb (from #338, on main): fails from 2026-11-16 08:00 KST because the injected "next day" clock was overtaken by real DB timestamps | Test defect | Fixed in #371 (§5); main's PG integration job fails until then |
| 10 | Staging disk at 100% (923 MB free): Auto-CD never prunes images; 36.8 GB build cache; journald uncapped beyond its default | Operations | Analysed (§18); nothing deleted |

## 4. PR #371 changes

Commit `2c7108a`, already in the PR:

- **#368 early dedupe:**
  - `fetch_pages(skip=)` and `NightStore.fetched_tonight()` drop a detail URL before its request when a finished job of the same night already fetched that posting;
  - it runs after all T61 checks and never adds URLs or requests;
  - a skipped posting is still linked to the keyword as a discovery, and counted in `duplicates`;
  - postings from earlier nights are still fetched, so change and close detection stay nightly.
- **#369 / #366 GCP sync:**
  - `skipped_by_source` and per-record `skipped_items` (≤50, with a truncation flag) are added;
  - `source_changed_since_last_sync` is recorded;
  - a `COUNT_MISMATCH` guard requires inserted + updated + duplicate + skipped + failed = fetched;
  - the Slack text names the sync stage.

Commit `6c45cbf`, from this review:

- **Hardening:** the skip predicate now uses the same `/Recruit/GI_Read/<digits>` parser (`_source_id`) that produces the stored `external_posting_id`. Unparseable or non-canonical URLs are never skipped, and get the normal import path and its error reporting.
- **New PostgreSQL 18 tests:**
  - an expired approval blocks before any request;
  - an expiry change counts as an UPDATE and reaches `expires_at`;
  - `COUNT_MISMATCH` aborts before any write.
- **Isolated systemd harness:** `poc/staging/automation/t61-override/isolated_systemd_test.sh`.

Review checklist (code read and tested):

| Check | Result |
|---|---|
| A new posting is not lost by dedupe | PASS: only IDs fetched *tonight* are skipped; the new detail in the same job is still requested (unit + PG) |
| Changes to known postings from earlier nights are still detected | PASS: earlier nights are not in `fetched_tonight`; update and expiry-change tests |
| Keyword–posting links are kept for skipped postings | PASS: the discovery row is written for the skipped ID |
| Skip count | PASS: `duplicates` = same-page repeats + early skips; `fetched` counts processed pages only |
| A failed job shown as success | PASS: `_outcome` ignores skips; an all-skipped job is SUCCEEDED, not FAILED; block, 429 and window close still FAIL |
| Repeated runs insert duplicates | PASS: `UNIQUE (source_code, external_posting_id)` + upsert; GCP refs `(source_id, external_id)`; rerun tests |
| T61 limits | PASS: unchanged (`DETAIL_LIMIT=5`, 7 per job, 126 per night); the skip hook cannot add requests |
| Search-URL duplicates vs posting-ID duplicates | PASS: the list parser drops repeated URLs on a page (per-page `duplicates`); the cross-keyword skip is by posting ID |
| Note | A run with `failed` items is stored as status `failed`, so `source_changed_since_last_sync` counts from the last fully succeeded run (it over-counts, which is the safe direction) |

Review state: no independent review yet. Not merged or deployed (§15). Tonight's live job ran the
deployed `1797f4c` code, so **none of the #371 behaviour has run in production.**

## 5. PostgreSQL 18 test results (isolated)

Environment:
- PostgreSQL 18.6 (x86_64-windows, throwaway data directory, port 55433);
- Python 3.12, PR branch `6c45cbf`;
- HTTP mocked or injected; no network request in any test.

| Suite | Command (env opt-ins omitted) | Tests | Result |
|---|---|---|---|
| Crawler unit (CI shape) | `python -m unittest discover -s crawler/tests` | 523 (5 skipped by design) | 522 PASS, 1 error = BASELINE_FAILURE (`test_t155_read_models`, Windows cp949 decode; also fails on main) |
| Night integration (real PG) | `crawler.tests.local_night_integration` | 13 | PASS (0 skipped) |
| Night E2E (real PG, full night simulation) | `crawler.tests.staging_night_e2e` | 7 | PASS |
| GCP sync (real career schema and grants) | `crawler.tests.local_gcp_sync_pg` | 12 | PASS |
| HTML → PG → API | `crawler.tests.local_html_pg_integration` | 2 | PASS |
| Focused: approval gate, scheduler lock, dedupe, lifecycle, GCP | `test_source_approval_gate test_scheduler_policy test_night_crawl test_lifecycle test_gcp_sync` | 106 | PASS |

Re-run on 2026-11-16 08:40 KST, on the final test changes of this PR (no production code changed since `6c45cbf`).

**Time-bomb fix.** `local_gcp_sync_pg.test_08_scheduled_guards` (from #338) injects `now = 2026-11-16 08:05 KST`, while earlier tests stamp `ingestion_runs.started_at` with the DB clock. It pinned only the latest run, so from 2026-11-16 08:00 KST the real-clock rows counted as "today" and the guard returned `ALREADY_SYNCED_TODAY`. This fails on main as well. The test now pins every succeeded run. The production guard is correct: there the injected and DB clocks are the same.

CI on GitHub for the PR head: see §15.

## 6. Scenario matrix (20 required)

| # | Scenario | Evidence (test) | Status |
|---|---|---|---|
| 1 | No LIVE approval → blocked | `test_gate_blocked_and_disabled_write_nothing` (PG); systemd case A | PASS |
| 2 | Valid approval → allowed | `test_full_pipeline_with_mocked_http_responses` (real gate, PG); systemd B; Staging AX job | PASS |
| 3 | Approval expired → blocked | `test_expired_approval_blocks_before_any_request_and_writes_nothing` (PG, new); systemd C/E2 | PASS |
| 4 | Request ceiling → stop | `test_failed_reservation_is_visible_and_consumes_budget_as_runtime` (`REQUEST_BUDGET`) | PASS |
| 5 | One job per keyword per night | `test_6_duplicate_execution_and_worker_abort`; `NOTHING_DUE` assertions | PASS |
| 6 | Same posting under two keywords | `test_posting_fetched_by_an_earlier_keyword_tonight_is_not_requested_again` | PASS |
| 7 | Detail request saved | same test (robots + search + new detail only); E2E 24 → 23 requests | PASS |
| 8 | New posting → INSERT | `test_keyword_jobs_insert_update_duplicate_discovery_checkpoint_and_slack` | PASS |
| 9 | Changed posting → UPDATE | same test; E2E `test_2` | PASS |
| 10 | Unchanged → unchanged/DUPLICATE | same tests; GCP `test_03` | PASS |
| 11 | Closing → update | `test_changed_expiry_on_a_known_posting_is_an_update`, GCP `test_11`, GCP `test_12_deadline_passed_is_closed_for_the_service_without_rewriting_status` (new) | PARTIAL: deadline passing is handled end to end; an explicit early close is BLOCKED on a real sample (§6.1) |
| 12 | Normalization failure reason | `test_partial_when_one_detail_is_unparseable`; E2E `test_5` | PASS |
| 13 | Per-record skip evidence | GCP `test_02`; unit `EvidenceTest` | PASS |
| 14 | COUNT_MISMATCH → safe failure | GCP `test_10_count_mismatch_aborts_before_any_write` (new) | PASS |
| 15 | Transaction rollback | GCP `test_05`; E2E `test_5` | PASS |
| 16 | Re-run idempotency | GCP `test_03`; `test_html_postgres_repeat_update_api` | PASS |
| 17 | Concurrent run lock | `test_dispatcher_lock_excludes_night_step`; GCP `test_08` (`SYNC_IN_PROGRESS`); systemd G1 | PASS |
| 18 | Night completion record | E2E `test_1` (summary once); `SUMMARY_SENT` once | PASS |
| 19 | Slack result counts | E2E `test_7`; unit Slack text tests (no real send) | PASS |
| 20 | GCP mapping | GCP `test_02`, `test_07` (draft by default, publish visibility) | PASS |
| — | Browser (Playwright) | No UI change in this work | NOT_RUN (not applicable) |

### 6.1 Closed postings: contract and what was fixed

- **Existing contract (T63 `crawler/quality/lifecycle.py`, its tests, and the backend):**
  - source `status='closed'` means the *source* explicitly closed the posting (`Lifecycle.CLOSED`, priority over dates);
  - a passed `expires_on` is the *derived* `Lifecycle.EXPIRED`;
  - the backend shows `published` + `expires_at ≤ now` as closed and leaves it out of open lists (`_is_open`, `_display_status`).
- **Deadline passed (`validThrough`): PASS.** Verified on real PostgreSQL 18 through the real GCP sync and the real backend repository (new GCP `test_12`):
  - the source status stays `published` and `expires_at` moves;
  - the posting is excluded from the open list and still returned with `include_closed=true`;
  - nothing is deleted.
  - Writing `closed` on deadline would merge EXPIRED into CLOSED and break that contract, so the parser was deliberately not changed to do it.
- **Expiry that precedes first-seen:** the sync skips it as `INVALID: Expiry precedes publish time` (existing guard, seen while writing the test).
- **Explicit early close (JobKorea marks a posting closed before its deadline, or removes it): BLOCKED.**
  - The repository has a single real JobKorea fixture, and it is an open posting. The parser documentation (`T62_STEP07_HTML_PARSER.md`) already states that `status='published'` is not a verified open/closed value.
  - Without a real closed-page sample, any marker (text such as "마감", HTTP 404/410, or a JSON-LD change) would be a guess, so none was added.
  - Unblocking needs one of these:
    - (a) the PM provides saved HTML of a JobKorea posting that is closed early, as an offline fixture;
    - (b) a PM-approved T61 fetch of one known-closed detail URL.
  - Then: parse the confirmed marker, map it to `status='closed'`, and add tests (crawler UPDATE, GCP status propagation with `publish=true`, backend `CLOSED`).

## 7. Measured effect of the dedupe

- **On real data (night of 11-12):** 30 detail requests produced 25 distinct IDs. So 5 requests (17%) repeated a posting another keyword had already fetched that night; #371 removes exactly these.
- **In isolation:** the night E2E goes from 24 to 23 requests; the PG test requests only robots + search + the new detail.
- **Tonight (AX only, deployed code without #371):** 4 of 5 details were postings first seen on 11-12. That is cross-night refresh, which #371 deliberately keeps.
- **Not live-tested:** #371 is not deployed, so its effect on a live night is NOT_RUN.

## 8. Skipped-record verification

| Check | Result |
|---|---|
| Read-only replay of real run `ce757d96` with the #371 code | PASS: `{"SOURCE_NOT_SELECTED": {"jobkorea": 2, "jobkorea_imported": 28}}`, `skipped_items: []`, accounting holds |
| Isolated PG test `test_02` | PASS: `skipped_by_source` and per-record `skipped_items` stored in `ingestion_runs.error_summary` |
| The 08:05 production run (deployed code without #371) | §12; per-source evidence will appear only after #371 is deployed |

## 9. systemd recovery test (isolated)

Setup:
- the `kant` user systemd manager (systemd 259, same version as the system manager) on the Staging host;
- a separate compose project `t61systest` with `network_mode: none`, using the same backend image digest as production (`sha256:e482b8ca…`);
- a copy of the production unit's ExecStart shape (`flock --nonblock` + `docker compose exec -T … backend python …`);
- a `90-live-auto-off.conf` produced by the same transformation the 11-13 root script applied;
- a test-only approval fixture (`approved_by: ISOLATED-SYSTEMD-TEST-ONLY`).

The probe runs the real `dispatcher.night_step` env check, the real `live_gate` and the real approval loader. Only `run_night_step` is replaced, so nothing touches a database. Production units, timer, lock, DB and network were untouched; afterwards 0 test units and 0 test containers were left.

Script: `poc/staging/automation/t61-override/isolated_systemd_test.sh`. Run 2026-11-15 22:21–22:23 KST.

| Case | Setup | Effective ExecStart env | Result | Status |
|---|---|---|---|---|
| A | No approval file, flags ON | — | `BLOCKED UNAPPROVED_SOURCE` | PASS |
| A2 | Container flags 0 | — | `DISABLED` | PASS |
| B | Valid approval, flags ON, no drop-in | — | `WOULD_RUN_LIVE_JOB (ALLOWED)` | PASS |
| C | Clock at 08:00:01 KST after `review_due` | — | `BLOCKED EXPIRED` | PASS |
| D | `90-live-auto-off.conf` | `-e …=0 -e …=0` | `DISABLED` even with container flags 1 | PASS |
| E | `90` + `95-t61-night.conf` | original (no `-e`) | `ALLOWED`: normal path restored | PASS |
| E2 | `90` + `95`, approval expired | original | `BLOCKED EXPIRED`: the override does not bypass approval | PASS |
| E3 | `90` + `95`, container flags 0 | original | `DISABLED`: the override does not force ON | PASS |
| F | transient `systemd-run --on-active` removes `95` + daemon-reload | `-e …=0` | `DISABLED`: back OFF automatically | PASS |
| G1 | Dispatch lock held, unit started | — | exit 1, probe not run (`flock --nonblock`) | PASS |
| G2 | daemon-reload with `95` present | exactly one ExecStart | `ALLOWED` | PASS |
| G3 | Manual rollback (remove `95`) | `-e …=0` | `DISABLED` | PASS |

Second run, 2026-11-16 08:32–08:35 KST: all of A–G again PASS, plus the failure and timing cases below.

| Case | Setup | Result | Status |
|---|---|---|---|
| H1 | Host time zone; calendar specs | `Etc/UTC`; `2026-11-16 23:01:00 UTC` and `2026-11-17 08:01:00 Asia/Seoul` both elapse at `Mon 2026-11-16 23:01:00 UTC` | PASS |
| H2 | Real `--on-calendar` removal with `--timer-property=AccuracySec=1s` | spec `23:34:40 UTC`, removal seen at `23:34:40`; kill switch back, `DISABLED` | PASS |
| — | Same without `AccuracySec` (first attempt, 08:31 KST) | fired 30–60 s late (systemd default `AccuracySec=1min`); one probe started on the old config and returned ALLOWED | FINDING → the procedure pins `AccuracySec=1s`; the approval expiry (08:00) still blocks such a run |
| I | Removal command fails (`/bin/false`) | `95` still present; with the approval expired → `BLOCKED EXPIRED`; with the flags off → `DISABLED` | PASS (safe) |
| J | `.env` flags set to 1, backend recreate fails (missing image, `--pull never`) | `recreate_rc=1`; the old container keeps running with flags 0 → `DISABLED` | PASS (safe) |
| — | Duplicate dispatcher | `flock --nonblock` refusal (G1) + systemd oneshot | PASS |
| — | Request ceiling after the override | unchanged code limits (scenario 4); the override only restores the env path | PASS (PG test) |

Production state: `SYSTEMD_PRODUCTION_RECOVERY=NOT_RUN` (needs PM approval, §10).

## 10. Approvals needed before LIVE through the normal scheduler

1. **Root change for one night (PM plus root operator):** install the `95-t61-night.conf` drop-in and a transient removal timer (procedure in §16).
2. **A new finite T61 approval** for that night. Same limits: 6 keywords, page 1, ≤5 details per job, ≤7 requests per job, ≤126 per night.
3. **`.env` flags 1 for that night**, with the existing idempotent revert.
4. **Separately:** independent review of #371 before merge and deploy (optional for the LIVE night; without it the night runs `1797f4c` behaviour).
5. **Separately:** rotation of the `crawler_staging` password (§14).
6. **Before any LIVE night:** free disk space (at least the journald cap and the old ai-career images, §18). With less than 1 GB free, a night of writes and logs is at risk.

## 11. 08:01 KST revert cron

The background check scheduled for 08:12 KST stopped with the previous session, so the same read-only check ran at 08:25 KST.

| Check | Observed | Status |
|---|---|---|
| Ran | `revert start 2026-11-15T23:01:01Z` → `revert done 2026-11-15T23:01:01Z` (08:01:01 KST) | PASS |
| Action | `flags already 0 in .env and container; no recreate` (backend `StartedAt` unchanged since 13:03:07Z) | PASS |
| Self-removal | `cron line removed`; crontab now holds only the 08:05 sync line (`revert_line_present=0`) | PASS |
| Flags after | `.env` 0/0; running backend 0/0; `APP_VERSION=1797f4c…` | PASS |
| Timer | drop-in `90-live-auto-off.conf` loaded; 123 polls since the stop, all `night: DISABLED`, `external_requests: 0` | PASS |
| LIVE jobs / extra HTTP | night 2026-11-15: 1 job (AX, before the stop), 0 `RUNNING`, HTTP total 7 = the AX job; 0 after the stop | PASS |

Note: cron records no exit code. The log reaching `revert done` is the only completion evidence.

## 12. 08:05 KST GCP sync (production, deployed `1797f4c` code)

| Field | Value |
|---|---|
| Run ID | `045e68d4-e41d-41fa-8846-e720a7a883a7` (scheduled; wrapper start 23:05:01Z; ended 23:05:01.82Z; 1 attempt; Slack SENT 200) |
| Status | SUCCEEDED (`career.ingestion_runs.status = succeeded`) |
| Fetched | 59 = `jobkorea_live` 29 + `jobkorea` 2 + `jobkorea_imported` 28 |
| Inserted | **1** (companies created 1) |
| Updated | 0 |
| Duplicate/unchanged | 28 |
| Skipped | 30, all `SOURCE_NOT_SELECTED` (per-source split appears only after #371 is deployed) |
| Failed | 0 |
| Buckets | 1 + 0 + 28 + 30 + 0 = 59 |

Cloud SQL, read-only (`default_transaction_read_only=on`):

- `job_posting_external_refs` for (`jobkorea_live`, `50350626`): exactly 1 row. Its posting `5be9ce82-462b-4921-afd0-ded17c1a4af0` has `status=draft`, `source_url=https://www.jobkorea.co.kr/Recruit/GI_Read/50350626`, and was created at 23:05:01.82Z by this run.
- `jobkorea_live`: 29 postings, all 29 draft, 29 distinct URLs; 29 refs with 29 distinct external IDs. No duplicate insert.
- Field-by-field source ↔ target comparison of all 29 `jobkorea_live` rows (company, title, employment type, location, URL, status, `published_at`, `expires_at`, `first_seen_at`): **29 compared, 0 mismatches.**
- Public API (#342) at 08:28 KST: 76 public postings; **0** of the 29 draft `jobkorea_live` postings are exposed, including 50350626.

**Status: PASS.** The GCP sync success is reported separately from the crawl: the crawl evidence is §13.

## 13. Evidence of a real new insert

| Stage | Evidence | Status |
|---|---|---|
| LIVE → Staging | job `16a8fc29-b12c-4ab7-8a9e-ae9029474dd9`: AX, `SUCCEEDED`, 7 HTTP requests, 5 details, inserted 1, unchanged 4, failed 0 (2026-11-15 12:54:34–12:54:49Z). Posting `jobkorea_live/50350626` first seen and written tonight; `jobkorea_live` 28 → 29 | PASS |
| How it ran | A manual run of the dispatcher's ExecStart from SSH, inside the approved window and limits. A manual exec does not get the drop-in's `-e` flags; the systemd timer path stayed `DISABLED` | Disclosed |
| Staging → Cloud SQL | run `045e68d4`: inserted 1; ref (`jobkorea_live`, `50350626`) exists once; draft; fields match | PASS |

## 14. Exposed password

| Item | State |
|---|---|
| Account | `crawler_staging`: not a superuser; SCRAM-SHA-256; CONNECT to `postgres`, `ai_career_poc`, `ai_career_crawler_training`; read/write on `crawler_training` tables |
| Reachability (corrected 2026-11-16) | Not only the docker network: `ai-career-db-lan-proxy` (socat) publishes `db:5432` on the host's LAN address, port 15432, limited to one /24, and `pg_hba` has `host all all all scram-sha-256`. Anyone on that /24 with the password can log in. This raises the rotation priority |
| Dependents | Backend dispatcher (every 5 min) and the 08:05 GCP sync (reads the source through the backend env). No other `crawler_staging` sessions in `pg_stat_activity` (2026-11-16 08:36 KST) |
| Exposure | Two local Claude Code session transcripts (`14337784…jsonl`, `153bee14…jsonl`); local output files were redacted (0 copies in the scratchpad). Not in the repo, git history, `outputs/`, issue/PR text, or the Staging journal. The Staging `.env` and its `.env.bak-*` copies hold it by design (600). The `backups/*` dumps reference the role but carry no password (`pg_dump` does not export passwords) |
| Rotation | BLOCKED: needs PM approval (backend recreate, about 30 s; crawler and sync dependency) |
| Procedure (prepared, not run) | (1) Outside the night window and away from 08:05; back up `.env` (600). (2) Holding `.crawler-dispatch.lock`: generate the password on the host into a 600 file (never printed); `ALTER ROLE crawler_staging PASSWORD` reading that file through a psql variable; update `.env` atomically; recreate only the backend with the Auto-CD compose command. (3) Verify a read-only `SELECT 1` via `connect_configured_database`, the next dispatcher poll IDLE, and a GCP sync dry-run. (4) Rollback: `ALTER ROLE` back to the value in the backed-up `.env`, then recreate the backend. (5) The PM decides what happens to the stale `.env.bak-*` copies and the two transcripts; nothing is deleted without that decision |

## 15. Remaining P0/P1 items

| Priority | Item | State |
|---|---|---|
| P0 | LIVE through the normal scheduler | BLOCKED: root kill switch; approval needed (§10) |
| P0 | Independent review of PR #371 | PENDING: CI green, 0 reviews; not merged or deployed |
| P0 | Staging disk at 100% (923 MB free); journald can still grow about 1 GB on its default cap | Analysed; cleanup needs approval (§18) |
| P1 | Rotate the `crawler_staging` password (reachable from the LAN /24) | BLOCKED on approval |
| P1 | Explicit early-close detection | BLOCKED on a real closed-page sample (§6.1) |
| P1 | main's `local_gcp_sync_pg` job fails from 2026-11-16 08:00 KST (time bomb) | Fixed only on the #371 branch |
| P1 | #370 daily inflow monitoring (zero-inflow day detection) | Design posted; not implemented |
| P1 | Search-volume measurement for #367 | Needs approval for a bounded probe |

## 16. Procedure for the next normal T61 night (not run; needs approval)

1. **Before (read-only):**
   - deployed SHA and health;
   - `systemctl show ai-career-crawler-dispatch.service -p DropInPaths -p ExecStart`;
   - no night `RUNNING` jobs;
   - crawler DB dump + `pg_restore --list`;
   - `.env` backup.
2. **Approval record:** a new private T61 file with `approved_by` (the PM), `evidence_ref` (the access basis), `valid_from_utc` = activation and `review_due_utc` = 08:00 KST. Same limits.
3. **Root override (exact content, the operator copies it):**

   ```ini
   # /etc/systemd/system/ai-career-crawler-dispatch.service.d/95-t61-night.conf  (root:root 0644)
   [Service]
   # T61 one-night override <YYYY-MM-DD>, approved by <PM>; removed by ai-career-t61-expire timer
   ExecStart=
   ExecStart=/usr/bin/flock --nonblock /home/kant/ai-career-staging-poc/.crawler-dispatch.lock /usr/bin/docker compose --project-name ai-career-staging-poc exec -T backend python -m crawler.jobs.dispatcher dispatch
   ```

   The diff against the effective unit: only the `-e CRAWLER_NIGHT_ENABLED=0 -e CRAWLER_LIVE_SCHEDULE_APPROVED=0` arguments are removed. `90-live-auto-off.conf` is **kept**; `95` sorts after `90`, so its reset wins (verified, case E).
4. **Automatic expiry (root, same step):**

   ```sh
   # Host is Etc/UTC: 08:01 KST is 23:01 UTC of the previous day. AccuracySec=1s is required:
   # the systemd default (1 min) fired the removal up to a minute late in the isolated test.
   systemd-run --unit ai-career-t61-expire --on-calendar='<YYYY-MM-DD> 23:01:00 UTC' \
     --timer-property=AccuracySec=1s \
     /bin/sh -c 'rm -f /etc/systemd/system/ai-career-crawler-dispatch.service.d/95-t61-night.conf && systemctl daemon-reload'
   systemctl daemon-reload
   systemctl show ai-career-crawler-dispatch.service -p DropInPaths -p ExecStart   # expect 90 + 95, no -e
   systemctl list-timers ai-career-t61-expire.timer
   ```

5. **Flags:** set `.env` flags to 1 and recreate only the backend under the dispatcher lock (`t61-oneshot/apply_flags.sh 1`). The idempotent revert cron at 08:01 KST sets them back to 0.
6. **Layers that stop it at 08:00 KST:**
   - the approval expiry;
   - the 08:00 window boundary in the code;
   - the root timer removing `95`, which restores the kill switch;
   - the flag revert.
7. **Evidence during and after:** dispatcher journal lines per poll; `night_job_results` (jobs, HTTP ≤126, inserted/updated/unchanged); Slack job and summary; the 08:05 sync run row; the systemd state after 08:01.
8. **Rollback at any time:**
   - root: `rm 95-t61-night.conf && systemctl daemon-reload`;
   - `apply_flags.sh 0`;
   - no data is deleted.

## 17. Plan toward 1,000 new postings per day (#367)

- **Current maximum: 30 details per night.** 6 keywords × search page 1 × 5 details, within 126 requests. Best observed: 21 new (11-12); tonight: 1 (one keyword). **1,000 per day is not feasible under the current approval.**
- **Supply is UNKNOWN.** Total search results, pages per keyword and the daily new-posting rate were never measured.

| Step | Design | External requests | Approval |
|---|---|---|---|
| 1. Measure totals | 1 search page per keyword; record the total-count text and links per page; no details | 6 + robots | PM (bounded probe) |
| 2. Pages | Page 2..N for 1–2 keywords until no new IDs appear; record links/page, the overlap between pages, and the ID stability of the `GI_Read/<id>` canonical form | ≤ 20 | PM |
| 3. Overlap between keywords | From the stored discoveries (no new requests): the 11-12 overlap was 5/30 (17%) | 0 | — |
| 4. Revisit cost | Share of known IDs on page 1 per night (tonight 4/5 were known) → decide refresh cadence (e.g. revisit details every N nights, ETag/Last-Modified if served) | 0 | — |
| 5. New-posting rate | New IDs per keyword per day over ≥3 nights at a fixed scope | within the existing budget | PM (nightly T61) |
| 6. Request model | requests ≈ robots + Σ pages + Σ new details + revisits; 1,000 new/day needs ≥1,000 detail requests + 25–50 list pages ≈ 1,050–1,100 per day (8–9× the 126 cap); ≥2 s/request ≈ 35–40 min sequential | — | — |
| 7. Licensed sources | Ask about a JobKorea partner/feed/API and other sources with explicit terms; the current basis is a verbal PM statement only | 0 | PM / legal |
| 8. Stepwise increase | 126 → 300 → 1,100 requests per night, each step gated on 0 blocks/429s and the measured new-posting rate; wider keyword/category set | stepwise | PM per step |

- **Impact:**
  - Time: about 40 minutes per night at 1,100 requests.
  - Storage is small: the posting payloads are KB-sized.
  - The main risks are access blocks and terms compliance, not compute.
  - Disk on the Staging host is at 99% (1.1 GB free), which needs attention before any scale-up.
- **No widening of collection was done in this work.**

## 18. Staging disk usage (read-only, 2026-11-16 08:35 KST)

**`/` is 98 GB with 92 GB used and 923 MB free (100%).** Inodes are at 27%.

Nothing was deleted or pruned, and no VACUUM was run.

### Top consumers

| Area | Size | Reclaimable (reported) | Notes |
|---|---|---|---|
| Docker build cache | 36.8 GB | 33.7–36.4 GB | 317 entries, all last used ≥10 days ago (180 at "2 weeks", 54 at "2 months"); from local builds on this host (other projects too); none active |
| Docker images | 30.8 GB (374 images) | 16.7 GB | **324 are `ai-career-platform` backend/frontend images (162 pairs, 11-06 → 11-14)**; only the current pair is in use. Auto-CD (`automation/deploy.py`) pulls every release and never removes the old ones |
| Docker volumes | 1.0 GB (21) | 0.7 GB | 13 anonymous volumes of about 50 MB each with 0 links (look like old PostgreSQL data from removed containers: review before removal); `ai-career-staging-poc_postgres_data` 78 MB (in use) |
| `/home/kant` | 14 GB | — | `.codex` 4.4 GB (7+ old app-server releases of 0.3 GB each); `.vscode-server` 3.3 GB (several old servers); `kant-moa` 1.5 GB (backups, exports); `webserver` 0.9 GB; `.nvm` 0.75 GB; `.cache` 0.68 GB; `.npm` 0.22 GB; `Downloads` 0.29 GB; a Chrome `.deb` 0.14 GB |
| `/var/log/journal` | 3.1 GB | — | journald defaults (no `journald.conf.d`); the cap is 10% of the filesystem, at most 4 GB, so it **can still grow about 0.9 GB, enough to fill the disk** |
| `/var/lib/snapd/snaps` | 3.1 GB | — | 12 snaps with retained revisions |
| `/usr`, `/opt` | 6.0 GB, 0.8 GB | — | system |
| AI Career data | crawler DB 9 MB, app DB 10 MB; `ai-career-staging-poc/` 5 MB (backups 1.5 MB) | — | not a contributor |

**Growth.** The main source is the ai-career Auto-CD: each release adds a backend + frontend image (shared base layers, so less than their 310 + 75 MB nominal size), with 2–76 images per day over 11-06 → 11-14. Next come the journald logs (the 5-minute dispatcher and other services) and tool self-updates (`.codex` gains about 0.3 GB per release, 4 releases in the last 7 days).

**Risk.** With less than 1 GB free, PostgreSQL WAL/checkpoints, image pulls in the next Auto-CD deploy, journald and the 08:05 sync log can fail. That puts tonight's operations at risk.

### Cleanup candidates (none executed)

| Class | Candidates | Est. space | Condition |
|---|---|---|---|
| A. Keep | all in-use images/containers; named volumes in use (`ai-career-staging-poc_postgres_data`, `dbresting_postgres_data`, `ax2-…_postgres_data`, `cat-game-…`); `ai-career-staging-poc/.env*`, `backups/`, `crawler-policy/`, `gcp-sync/`, `.deploy-state/`; `dbresting-backups`; the current journal | — | — |
| B. Delete after review | ai-career images except the current and the previous (rollback) digests: ~16 GB; Docker build cache (owners of the other projects' builds should confirm): ~34–36 GB; the 13 anonymous 0-link volumes (~0.7 GB; confirm they are not wanted DB data); old `.codex` releases (~2 GB) and old `.vscode-server` servers (~2 GB); old snap revisions (~1–2 GB); `kant-moa/backups/migration-export-*` (~0.6 GB, the owner decides) | ~55 GB | PM/host owner approval; image prune by digest list, not `-a` |
| C. Temporary, safe | `~/.cache` (0.68 GB), `~/.npm/_cacache` (0.22 GB), `/tmp` and `/var/tmp` (<0.1 MB), `google-chrome-stable_current_amd64.deb` (0.14 GB) | ~1 GB | regenerable; still deferred to approval in this task |

### Proposed plan (needs approval)

1. **Immediately (root):** cap journald with `SystemMaxUse=1G` in `/etc/systemd/journald.conf.d/size.conf`, then `systemctl restart systemd-journald` and `journalctl --vacuum-size=1G`. Frees about 2 GB and stops the growth.
2. Remove the unreferenced `ai-career-platform` images except the current and the previous release digests (the list comes from `.deploy-state/success.json` plus the last deploy event). Frees about 16 GB.
3. With the owners' agreement: `docker builder prune --filter until=168h`. Frees about 34 GB.
4. **A follow-up code PR:** Auto-CD retention, keeping the last N release digests after a healthy deploy. This prevents the regrowth.
5. Review the B items in `/home/kant` with the host owner.
