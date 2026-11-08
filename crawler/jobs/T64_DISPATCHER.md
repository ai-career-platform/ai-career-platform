# T64 DB dispatcher — disabled by default

The existing `career.data_sources`, `career.ingestion_runs` and `career.audit_events`
belong to the application DB and its UUID/FK model. T64 must not change that DB.
The isolated crawler DB therefore adds only `crawler_training.schedules`, `runs`
and `run_events`, retaining the existing postings table. Existing RunRecord state
validation, KST timezone calculation, bounded recovery policy and T61 gate are reused.

## Implementation / verification order

1. Explicit guarded migration, initially disabled fixture schedule.
2. Atomic row-locked claim plus unique active source constraint; independent worker.
3. DB events/counters, heartbeat, source lock, timeout/kill and bounded retries.
4. Pure tests and isolated PostgreSQL contention/process tests.
5. Existing Auto-CD image and systemd unit verification in CI.
6. Normal review/merge, approved isolated staging migration and disabled safe QA.
7. Live activation is a separate PM/provider authorization decision, never automatic.

## Internal commands

```text
python -m crawler.jobs.dispatcher schedules
python -m crawler.jobs.dispatcher runs
python -m crawler.jobs.dispatcher run --run-id UUID
python -m crawler.jobs.dispatcher events --run-id UUID
python -m crawler.jobs.dispatcher configure --time 03:00 --mode fixture
python -m crawler.jobs.dispatcher dispatch
```

`configure` defaults to `enabled=false`. There is no externally exposed admin
HTTP API: existing admin authentication/RBAC is not ready. The authenticated
operator's CLI is the interim inspection/configuration boundary.

## Execution and recovery

The dedicated systemd oneshot/timer files are in `poc/staging/crawler/` and are
not installed or enabled by code or deployment. They poll about every five
minutes and are separate from the existing Auto-CD timer. The existing backend
image includes both dispatcher and worker through its existing crawler COPY.

Dispatcher holds a DB session advisory lock. Claims use a row lock, a unique
source RUNNING index and a unique schedule/slot/attempt key. The worker holds
a second source session lock. An expired heartbeat cannot release a claim
while a surviving worker still holds that lock. A duplicate worker that cannot
acquire it leaves the owner's run untouched. On DB connection loss, worker
writes fail; there is no reconnect-and-continue path.

Dispatcher updates heartbeats every ten seconds, kills/reaps its worker after
120 seconds, and records safe failure codes. DB statements/locks are bounded
to 15/5 seconds. After dispatcher loss, a surviving bounded worker can finish
its own run. Once its connection is gone, the next dispatcher can expire a
five-minute stale heartbeat. An OS-frozen surviving worker lock deliberately
blocks replacement until the operator confirms/terminates that worker.

Only timeout, heartbeat expiry and temporary I/O errors retry, at 60/120-second
backoff with three attempts maximum. HTTP 403/429, robots/challenge rejection,
invalid contracts and unapproved sources never retry. Unknown crashes are
recorded for inspection rather than automatically rerunning unsafe work.
The next daily slot is stored in UTC for Asia/Seoul local time. A late poll
claims one overdue slot, then advances to the next future daily time.

Fixture mode invokes the existing synthetic worker and can write only its
clearly labeled synthetic records. It never performs HTTP. Disabled schedules
start no worker. Live mode additionally requires the separate environment flag
`CRAWLER_LIVE_SCHEDULE_APPROVED=1`, enabled DB schedule, and a valid existing T61
approval record covering every explicit detail URL, scheduled purpose, dates,
storage/use constraints and total request budget (including robots). No provider
approval record has been created for deployment. Live target count is at most five.

## Migration / staging approval / rollback

`crawler/storage/migrations/0002_scheduler.sql` is an explicit transaction,
guarded by the dedicated database name. It creates three tables, their indexes
and the event identity sequence. It inserts one disabled fixture schedule and
grants minimal runtime table/sequence privileges to an existing crawler_staging
role. It never creates roles, touches the career schema, or runs on startup.

Apply only after PM/DB approval and a verified private backup of the isolated
crawler DB. Review/merge must precede normal Auto-CD. The server release overlay
does not auto-sync: any later live approval flag requires a reviewed private
configuration update; its repository default is zero. No timer activation is
authorized by this implementation. Keep the staging schedule disabled.

Rollback: leave timer disabled, set schedule disabled if already provisioned,
and retain run/event history for review. Previous images ignore these additive
tables; dropping them is unnecessary and requires a separate destructive DDL
decision. Existing postings and application data must remain intact.

## Tests

Pure tests run in normal crawler discovery. `local_t64_integration` needs an
explicit disposable DB opt-in (`CRAWLER_T64_ISOLATED_TEST=1`); it exercises actual
subprocesses and may create the existing bundled SYNTH fixture records. Do not
point it at an active scheduler. CI also tests the non-owner staging runtime
role and verifies systemd units without installing/enabling them. Local/CI
results are not staging evidence. Staging migration and disabled fixture QA
remain HOLD until their approval, deployment and actual execution are recorded.
