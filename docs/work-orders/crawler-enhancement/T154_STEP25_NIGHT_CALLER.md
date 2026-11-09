# T154 STEP25 finite night caller

Scope: existing Fixture one-shot + T151 Keyword/Job + immutable Payload + synthetic list/detail Raw capture. No live HTTP, schema migration, T64/Auto-CD change, or automatic installation. Target night is **2026-11-08 21:00 to 2026-11-09 08:00 KST only**.

## Runtime

`python -m crawler.jobs.fixture_night_caller once --night-date 2026-11-08 --input /app/crawler/fixtures/night_synthetic_input.json --raw-root /tmp/t154-night-20261108/raw --log-file /tmp/t154-night-20261108/caller.jsonl`

The caller uses only its dedicated synthetic-night-<date> keyword. It prefers a valid PENDING job with no Attempt or remaining RETRYABLE budget. An unresolved IN_PROGRESS/STOPPED job stops fresh supply for that night. Otherwise the committed synthetic template supplies at most10 items (default2), with deterministic per-night/per-slot numeric IDs and a collision check. Keyword/Job UUIDs are allocated in the target DB, never copied from isolated tests. Completed jobs are never selected again.

A caller session lock spans supply and one-shot. Existing slot PK and atomic Slot+Attempt claim cap each night at22 slots and each job at3 attempts. Already-used slot, no input, disabled keyword, outside the exact night or less than3 minutes before08 are IDLE, not successful new collection. Raw corruption/DB inconsistency is UNRESOLVED/manual review. No automatic retry loop.

Both full caller (including preparation) and Worker are supervised. The outer guard uses at most140 seconds, reserves bounded TERM/KILL and DB cleanup time, and kills residual POSIX process-group descendants. Token-scoped own-role caller/Worker PostgreSQL sessions are terminated/checked separately. The existing inner Worker guard remains unchanged by default. Errors are structured codes, never DSN/exception text/HTML.

The host gives each invocation a hex identity. On interruption/completion, its finalizer requests cancellation by that identity and waits at most10s for the atomic done marker before copying final Raw/JSONLs. The marker is written after child reap/DB cleanup/JSONL close. Any caller/archive error creates a persistent HALT file; subsequent invocations log IDLE and do not create data. HALT is never automatically cleared.

## Install/activate gate — not performed by this PR

1. Normal review/CI/merge, then existing Auto-CD main/image SHA match. Preserve retained first-batch data and existing original7/app51 fingerprints. Do not redeploy branch code.
2. Reuse the verified backup restoration point; confirm0010/runtime permissions. Validate new caller on staging using new synthetic IDs and short deadlines, preserving first-batch successful rows.
3. Install the merged wrapper as `/home/kant/ai-career-staging-poc/bin/t154-night-once-20261108.sh` (0750) and the two merged units into standard system unit directory; do not overwrite pre-existing same-name files. Verify with systemd-analyze, then daemon-reload. Do not modify T64 or Auto-CD units.
4. Units are disabled by default. Only after every gate passes and time remains, **start the dedicated timer once, do not enable it**. This prevents reboot persistence. Calendar contains22 absolute half-hour times; Persistent=false avoids catch-up, RemainAfterElapse=false unloads the elapsed timer after final service completion. Restart=no. This finite file must not be reused for another night.
5. Confirm actual OS trigger/one Supervisor, JSONL/DB result and archival. If absent or uncertain, stop and leave automation HOLD. Never replay past slots. After08 verify inactive/disabled and no caller/Worker/DB locks.

## Retention and monitoring

Wrapper snapshots are private, unique directories under `outputs/t154-night-20261108/`; no existing snapshot or backup is overwritten. Raw content, caller.jsonl, worker.jsonl, guard.jsonl and done markers are copied out of the replaceable container after finalization. If a later image replacement loses pending Raw, the caller fails closed rather than silently recreating it. Preserve archives for manual reconciliation.

Count caller invocations, IDLE/rejected calls, slot reservations, attempts, committed postings, inserted/updated/unchanged separately. Inspect Job/Attempt mismatch, db_cleanup/whole_caller_cleanup, cleanup_before_deadline and errors. Unknown/IN_PROGRESS is manual review, never implicit success. Synthetic titles/keyword/raw mode identify these records; `jobkorea_imported` alone does not establish live collection. Actual HTTP stays0.

The previously retained first staging batch is a separate successful manual one-shot, not evidence that this new timer ran. Its DB rows and independent archive must not be cleaned as validation data.

## Validation

Isolated runtime PostgreSQL tests cover supplied success, same-slot duplicate IDLE, empty input IDLE, completed job exclusion, retry same UUID, third-attempt STOPPED barrier, corrupt Raw unresolved,08 no DB access, whole-caller preparation kill/rollback and nested one-shot success. Linux tests additionally cover wrapper archive failure/HALT, process-group descendant reap, and killing the actual host docker-exec client while the disposable container guard cancels/cleans and final logs are archived. All staging activation gates remain separate.
