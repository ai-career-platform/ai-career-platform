# Staging crawler: manual fixtures and bounded nightly live collection

Status: proposed operation transition. This document grants no collection rights, renews no
approval and activates nothing. Independent PR review, required CI and PM operation approval
are required before applying the steps below. Historical night-test reports describe older code.

## Target and preservation

The PM selected the existing Staging crawler database: Docker service `db:5432`, database
`ai_career_crawler_training`, schema `crawler_training`, runtime role `crawler_staging`.
`Host_GCP` is a different server/application database and is **not** this transition's target.
Do not change either connection URL, migrate old data, widen privileges or run migrations.
The existing connection identity guards remain in force. Verify the current TLS status and
record any unmet transport requirement before operation approval; do not claim encrypted
transport from a healthy DB connection alone.

## Proposed policy and existing hard bounds

| Item | Policy |
|---|---|
| Daily fixture | Preserve `jobkorea-daily`, `03:00`, `mode=fixture`; set only `enabled=false` |
| Manual fixture | Explicit `python -m crawler.jobs.dispatcher manual-fixture`; works with daily disabled |
| Dispatcher | Existing 5-minute timer, unchanged; an IDLE poll sends no Slack message |
| Live window | Every night, 21:00 inclusive to next-day 08:00 exclusive, Asia/Seoul |
| Keywords | Existing AX, 데이터 분석, 빅데이터, AI 엔지니어, 머신러닝, 딥러닝; active registered keywords only |
| New keyword pacing | `CRAWLER_NIGHT_INTERVAL_MINUTES=60` default; configurable 60..660, never faster than existing hourly policy |
| Completed keywords | At most one successful job per keyword/night; no repeated completed jobs or unbounded cycles |
| Job requests | At most 7: robots + search + 5 detail pages; existing per-URL T61 scope checks |
| Night requests | `CRAWLER_NIGHT_MAX_REQUESTS=126` ceiling, configurable 1..126 (6 keywords × 3 attempts × 7) |
| Retry | Existing classified transient errors only, at most 3 attempts, 60/120-second backoff; never retry access blocks |
| HTTP | At least 2 seconds/request, or the larger robots crawl-delay; 15-second timeout; 2,000,000-byte response limit |
| Concurrency | One dispatcher/session advisory lock shared by manual fixtures, daily dispatch and night steps |
| Stale process | Existing recovery; a crashed attempt still consumes its full 7-request reservation |

The night cap counts **reserved** requests: every committed attempt consumes seven slots even
if it used fewer or died before recording its result. This intentionally underuses capacity
instead of refunding unknown requests after a crash. Normal `http_requests` counts request
starts via the pre-request hook. A stale orphan records a conservative upper bound of seven
with `HEARTBEAT_TIMEOUT`; do not present that orphan count as exact observed requests.

Late timer startup does not replay missed keyword jobs in a five-minute burst. A new keyword
waits the configured interval from the latest actual job start. A classified retry keeps the
existing bounded backoff and also consumes a new reservation. Remaining keywords can stay
unprocessed when the budget or night window closes. Fresh next-night results allow planning
again, but a still-expired approval continues to block HTTP.

Every HTTP start, including robots and requests after crawl-delay, checks the job deadline,
08:00 boundary and approval expiry again. A request already in flight may finish after 08:00
within the existing HTTP timeout; this is **not** an OS-level hard-stop guarantee. No new
request may start once the check sees 08:00. Time-injected tests are not overnight production
evidence. The T154 one-shot timer remains unrelated and must not be activated by this procedure.

## Explicit finite approval

Keep the existing private T61 `SourceApproval` file and its expiry checks. The operator must
obtain a reviewed, finite replacement with the actual approver and evidence reference; never
copy an expired approval, create a fictitious approval record or remove its expiry.

The reviewed operation record must specify: purpose `night_keyword_collection`, exact search
URLs/keywords and bounded discovered details, validity start/review expiry, retention/deletion
policy, request budgets above, hourly pacing and retry exception, single concurrency, target DB,
21:00–08:00 KST, stop-on-block, audit/notification scope, approver, provider permission evidence,
and stop/change procedure. `approved_by`, `evidence_ref`, `valid_from_utc`, `review_due_utc`,
`allowed_urls`, `max_discovered_details`, `max_requests` and the remaining existing T61 fields
remain mandatory according to the existing evaluator. This PR contains no APPROVED record.

`CRAWLER_NIGHT_ENABLED=1` and `CRAWLER_LIVE_SCHEDULE_APPROVED=1` are necessary activation flags,
not substitutes for the approval. The current expired policy must remain blocking until a
valid reviewed replacement is provisioned privately. Environment limits may only lower the
hard bounds; record the exact configured values in the reviewed operation evidence.

## Apply only after review, CI and operation approval

1. Confirm deployed main SHA, healthy services, no active daily/night worker and unchanged
   DB identity. Snapshot the schedule, counters/fingerprints, private configuration, timer and
   current container/volume IDs. Create a uniquely named full crawler backup and verify restore
   in a separate instance. Do not reuse an old restore result as proof of a new dump.
2. With the operator's existing DB connection, transactionally disable only the matching row:

   ```sql
   BEGIN;
   UPDATE crawler_training.schedules SET enabled=false, updated_at=now()
   WHERE schedule_id='jobkorea-daily' AND mode='fixture'
   RETURNING schedule_id, enabled, mode, local_time, next_run_at;
   -- Require exactly one returned row and compare the preserved fields before COMMIT.
   COMMIT;
   ```

3. Preserve the current DB credentials/target. Provision only the reviewed finite approval
   and the two bounded pacing/budget settings via the existing private release configuration.
   Record hashes/expiry, never credentials or policy secrets. Use the existing release/Auto-CD
   path; never deploy an unmerged branch or edit Auto-CD. If a restart affects another task,
   stop for operation coordination rather than restarting shared services.
4. Keep the dispatcher timer active. Validate the explicit manual-fixture subprocess with
   approved synthetic data, scheduled fixture dispatch IDLE, and unchanged schedule slot.
5. Inside the actual night window only, validate one approved minimal live keyword and its
   committed job/posting/discovery/checkpoint rows. No manual clock bypass or automatic second
   live run after failure. Outside the window record `PENDING_WINDOW`.
6. Compare original data/service/volume fingerprints; verify no unexpected jobs. Observe 08:00
   and next 21:00 separately. Until actually observed, `OVERNIGHT_REAL_RUN=NOT_VERIFIED`.

## Monitoring, stop and rollback

Use the existing `dispatcher schedules`, `runs`, and `events --run-id <id>` read commands.
Night jobs remain in `crawler_training.night_job_results` and `keyword_jobs` (not synthetic
T64 `runs`). Posting identity is `(source_code, external_posting_id)`; discoveries link the
keyword to that same identity. A night job can discover multiple postings and is not a claim
that one T64 run row exists per night job. Posting writes retain their existing per-posting
transaction/UPSERT semantics; previously committed valid rows are not deleted after a later
page fails. Inspect failed/partial counts and FK integrity accordingly.

Record `NIGHT_HALTED`, `REQUEST_BUDGET`, `WAIT_INTERVAL`, approval expiry and window-close JSON
results. Slack sends one job result and one morning summary, including actual counters and
reserved request budget; it does not notify on every IDLE poll. Slack failure never changes
DB success. Do not send a real notification during mock/isolated tests.

Stop new live work by disabling `CRAWLER_NIGHT_ENABLED` through the approved private release
configuration; do not modify Auto-CD. If approval is revoked/expired, leave it fail-closed.
Restore only the backed-up crawler settings and the exact previous schedule fields if rollback
is approved. Do not restore the whole DB, delete committed postings, reset sequences, or touch
Redmine, Church, nginx, ngrok, Google SSO or PR #331. Keep the fixture schedule disabled unless
PM separately approves restoring its automatic behavior.
