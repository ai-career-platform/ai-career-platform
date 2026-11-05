# AI Career Platform staging PoC

This isolated proof of concept demonstrates a static frontend, a FastAPI backend,
and PostgreSQL. It does not implement AI, ML, OAuth, or crawling.

## Architecture

```text
Browser -> ngrok HTTPS -> 127.0.0.1:18080 -> Nginx frontend
                                                  |
                                                  +-> /api/ -> FastAPI -> PostgreSQL
```

Only the frontend publishes a host port. Nginx strips `/api/` when forwarding
to the backend, so `/api/health`, `/api/version`, and `/api/health/db` map to
`/health`, `/version`, and `/health/db`. Backend and database have no published
ports. Compose uses its own `ai-career-staging-poc` project network and volume.

## Files

```text
poc/staging/
  compose.yaml
  .env.example
  README.md
  frontend/  Dockerfile, nginx.conf, index.html
  backend/   Dockerfile, requirements.txt, main.py
  tests/     test_health.py
```

## Environment

In a later deployment step, copy `.env.example` to `.env` **in this directory**,
and replace `CHANGE_ME` with a strong, unique password without sharing it.
Do not use the example placeholder as a real password or commit `.env`.
Compose requires every variable below to be nonempty:

| Variable | Purpose |
| --- | --- |
| `POSTGRES_DB` | PoC database name |
| `POSTGRES_USER` | PoC database user |
| `POSTGRES_PASSWORD` | PoC database password |
| `APP_ENV` | Environment shown by `/version` |
| `APP_VERSION` | Version shown by `/version` |

Compose sets `POSTGRES_HOST=db` and `POSTGRES_PORT=5432` for the backend.
PostgreSQL initializes its user, password, and database only when the named
volume is empty; changing these variables later does not update existing data.
Use a unique password for this PoC, not credentials from another service.

## Local execution

These are instructions for a later approved execution, not commands run in
this step. Docker Engine and Compose are required. From `poc/staging`, after
preparing `.env` as above and confirming port 18080 is free:

```sh
docker compose --env-file .env up --build -d
```

Visit `http://127.0.0.1:18080/` on the same host. To run the mocked backend
tests in an isolated Python environment:

```sh
python -m pip install -r backend/requirements.txt pytest==8.3.5 httpx==0.28.1
python -m pytest -q tests
```

## Ubuntu staging execution

In a later authorized deployment, transfer only these PoC files, prepare a
private `poc/staging/.env` on the staging host, and check that
`127.0.0.1:18080` is available. From that directory, use the same Compose
command as above. Do not copy the repository root `.env` to the server.

## Health checks

After startup, on the host running Compose:

```sh
curl -fsS http://127.0.0.1:18080/api/health
curl -fsS http://127.0.0.1:18080/api/version
curl -fsS http://127.0.0.1:18080/api/health/db
```

The DB check executes `SELECT 1`; it returns 503 when DB access fails.
Compose also checks each service's health. The backend container health check
tests the API process, while the separate DB endpoint checks database access.

## ngrok plan

In a later approved step, point the existing ngrok HTTPS tunnel to
`http://127.0.0.1:18080`. Verify external access to the page and API without
publishing backend or database ports. No ngrok configuration is changed here.

## Data preservation verification plan

In a later approved test, create a non-sensitive test record in the PoC DB,
recreate only the PoC services, then verify the record remains. The named volume
is mounted at `/var/lib/postgresql`, the PostgreSQL 18 image's volume root.
Back up the volume before any destructive operation. Do not use `down -v`,
volume pruning, or delete the volume as part of this test.

## Existing service protection

Check port availability before deployment. Do not modify or reference other
projects' containers, networks, volumes, databases, or credentials. The fixed
Compose project name scopes PoC resources; do not override it or configure
external resources. A same-name existing Compose project must be investigated
before deployment, not adopted or removed.

## Stop and recovery

From `poc/staging` and with its environment file:

```sh
docker compose --env-file .env stop
docker compose --env-file .env start
```

These affect only this Compose project and preserve the volume. If containers
need to be removed, `docker compose --env-file .env down` retains named volumes
by default; restart with the `up` command above. Never add `-v` or prune volumes.
For DB recovery, restore a previously verified PoC backup into this project's
database using a separately approved procedure; do not touch another project's
data. Investigate health-check failures before restarting or restoring anything.
