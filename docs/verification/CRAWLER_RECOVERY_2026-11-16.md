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
   - Live collection into Staging: verified for 1 keyword (job `16a8fc29`).
   - Staging → Cloud SQL for posting 50350626: see §11–13 (filled in from the 08:05 run).
   - Not verified: a full 6-keyword night through the systemd timer (BLOCKED by the kill switch).

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
| 7 | Explicit closed or removed postings are not detected; only a changed `validThrough` is | Code (limitation) | P1, open (§15) |
| 8 | A Staging DB credential was exposed in local session logs | Security/operations | Rotation procedure ready; BLOCKED on approval (§14) |

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
| Night integration (real PG) | `crawler.tests.local_night_integration` | 13 | PASS |
| Night E2E (real PG, full night simulation) | `crawler.tests.staging_night_e2e` | 7 | PASS |
| GCP sync (real career schema and grants) | `crawler.tests.local_gcp_sync_pg` | 11 | PASS |
| HTML → PG → API | `crawler.tests.local_html_pg_integration` | 2 | PASS |

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
| 11 | Closing → update | `test_changed_expiry_on_a_known_posting_is_an_update` (new), GCP `test_11` (new) | PARTIAL: a changed expiry date is handled; an explicit closed or removed posting is not detected (P1) |
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

Production state: `SYSTEMD_PRODUCTION_RECOVERY=NOT_RUN` (needs PM approval, §10).

## 10. Approvals needed before LIVE through the normal scheduler

1. **Root change for one night (PM plus root operator):** install the `95-t61-night.conf` drop-in and a transient removal timer (procedure in §16).
2. **A new finite T61 approval** for that night. Same limits: 6 keywords, page 1, ≤5 details per job, ≤7 requests per job, ≤126 per night.
3. **`.env` flags 1 for that night**, with the existing idempotent revert.
4. **Separately:** independent review of #371 before merge and deploy (optional for the LIVE night; without it the night runs `1797f4c` behaviour).
5. **Separately:** rotation of the `crawler_staging` password (§14).

## 11. 08:01 KST revert cron

PENDING: filled in from the read-only check after 08:12 KST.

## 12. 08:05 KST GCP sync

PENDING: filled in from the read-only check after 08:12 KST. Expected (not a result): 1 insert, for 50350626.

## 13. Evidence of a real new insert

| Stage | Evidence | Status |
|---|---|---|
| LIVE → Staging | job `16a8fc29-b12c-4ab7-8a9e-ae9029474dd9`: AX, `SUCCEEDED`, 7 HTTP requests, 5 details, inserted 1, unchanged 4, failed 0 (2026-11-15 12:54:34–12:54:49Z). Posting `jobkorea_live/50350626` first seen and written tonight; `jobkorea_live` 28 → 29 | PASS |
| How it ran | A manual run of the dispatcher's ExecStart from SSH, inside the approved window and limits. A manual exec does not get the drop-in's `-e` flags; the systemd timer path stayed `DISABLED` | Disclosed |
| Staging → Cloud SQL | §12 | PENDING |

## 14. Exposed password

| Item | State |
|---|---|
| Account | `crawler_staging`: not a superuser; CONNECT to `postgres`, `ai_career_poc`, `ai_career_crawler_training`; read/write on `crawler_training` tables. The DB port is not published (docker network only) |
| Dependents | Backend dispatcher (every 5 min) and the 08:05 GCP sync (reads the source through the backend env) |
| Exposure | Two local Claude Code session transcripts; local output files were redacted. Not in the repo, git history, `outputs/`, issue/PR text, or the Staging journal |
| Rotation | BLOCKED: needs PM approval (backend recreate, about 30 s; crawler and sync dependency) |
| Procedure (prepared, not run) | (1) Outside the night window and away from 08:05; back up `.env` (600). (2) Holding `.crawler-dispatch.lock`: generate the password on the host into a 600 file (never printed); `ALTER ROLE crawler_staging PASSWORD` reading that file through a psql variable; update `.env` atomically; recreate only the backend with the Auto-CD compose command. (3) Verify a read-only `SELECT 1` via `connect_configured_database`, the next dispatcher poll IDLE, and a GCP sync dry-run. (4) Rollback: `ALTER ROLE` back to the value in the backed-up `.env`, then recreate the backend. (5) The PM decides what happens to the stale `.env.bak-*` copies and the two transcripts; nothing is deleted without that decision |

## 15. Remaining P0/P1 items

| Priority | Item | State |
|---|---|---|
| P0 | LIVE through the normal scheduler | BLOCKED: root kill switch; approval needed (§10) |
| P0 | Independent review of PR #371 | PENDING: CI green, 0 reviews; not merged or deployed |
| P1 | Rotate the `crawler_staging` password | BLOCKED on approval |
| P1 | Explicit closed or removed posting detection (parser always emits `published`; a 404 or "마감" page is not mapped) | Open |
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
   systemd-run --unit ai-career-t61-expire --on-calendar='<YYYY-MM-DD> 23:01:00 UTC' \
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
