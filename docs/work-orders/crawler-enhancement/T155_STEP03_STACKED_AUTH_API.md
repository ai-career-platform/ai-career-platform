# T155 STEP03 stacked implementation — T15-authenticated metadata HTTP routes

**Branch:** `feat/t155-admin-authenticated-read-api`, based on unmerged `task/t15-auth` (PR #48). This is not deployable or mergeable into main until T15 is reviewed, merged and rebased. Nothing was installed on staging. T155 private PostgreSQL read-store is already on main via PR #119/#120, but is not present on the old T15 base until the stacked branch is rebased.

## API draft in stacked branch only

- `GET /api/v1/admin/crawler/keywords`
- `GET /api/v1/admin/crawler/jobs`
- `GET /api/v1/admin/crawler/schedules`
- `GET /api/v1/admin/crawler/runs`
- `GET /api/v1/admin/crawler/runs/{run_id}/events`
- `GET /api/v1/admin/crawler/stats/keywords`

**Security:** every route uses T15 `require_roles("admin")` dependency, which validates signed Bearer token, session active and account status, and loads roles freshly from auth DB. TestClient ensures anonymous 401, normal user 403 without calling crawler DB, admin 200 with fake read-store, immediate role revocation 403, query validation 422, and metadata-only responses. No special case for localhost, header actor override, hardcoded secrets, or bypass.

**Crawler DB:** `get_crawler_admin_store` creates dedicated crawler DB connection only after auth, scopes it to `SET TRANSACTION READ ONLY`, returns 503 without DB details if the environment/database is not configured. It performs no writes, no Raw HTML access, no HTTP crawling, and no Timer/Worker operation. Auth DB is separate.

## Merge/deployment HOLD

1. T15 PR #48 independent review/approval, latest main sync, Backend pytest CI and auth runtime DB checks PASS.
2. Rebase stacked branch on merged T15+T155 main; resolve imports and file conflicts. Confirm integrated backend image includes `crawler` and runtime read permissions.
3. Complete T155 admin 401/403/200, 422/503, session/role revocation and dedicated PostgreSQL staging read-only E2E.
4. Normal PR and CI merge gates; only then deploy; retain T154 Timer disabled and Live HOLD.

No permission seed or migration is added in this step; current T15 `admin` role is required. T155 write/schedule commands remain out of scope.


## 2026-11-09 deployment-path audit

The currently active staging crawler container uses `poc/staging/backend/Dockerfile.integrated` and runs `poc/staging/backend/main.py` with the standalone `backend/training_jobs_api.py`. It **does not run** `backend/app/main.py`, where T15 and T155 are registered. Passing stacked-branch TestClient tests is therefore **not** evidence that the live staging backend exposes the admin endpoints.

To complete STEP03 in an appropriate isolated deployment, integrate the main Backend application and T15 application DB schema, include the `crawler` package and dependencies in its runtime image, configure *separate* restricted crawler DB read access, prove role and session revocation and explicit 401/403/200/422/503 paths. Do not replace the existing staging PoC image, wire new external routes to its public port, or modify T154 night state as part of this stacked branch. Build and verify a separate integration target first.

The T15 base branch advanced to `108436ff1c4106484daf650f91dfcddbc22e771b` after #122 was opened. This stacked PR's head must be synchronized with that T15 version and **current main** only after T15 merges. The follow-up store `crawler/admin/read_models.py` exists on current main, not necessarily in the old T15 stacked base. No early deployment or green staging claim.
