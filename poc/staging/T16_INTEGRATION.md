# T16 staging integration

Diagnosis: published PoC image did not contain backend/app; Nginx stripped /api/ from service URLs. T16 itself is merged in PR40 b99f42e.

Integrated image reuses the formal app/lifespan, T14 Session, T15 JWT and T16 routes. PoC health/version/health-db and crawler endpoints remain; standalone PoC remains supported. API v1 is proxied with its complete prefix; legacy PoC URLs keep their existing mapping. Swagger exposes the actual external URLs with server `/`, including `/api/v1/me` and `/api/jobs/collected`, and loads `/api/openapi.json`.

Before deploying this image through the existing Auto-CD, configure the private JWT_SECRET and forward it through the existing release overlay. DATABASE_URL must refer to an approved least-privilege service DB account; do not reuse the PoC POSTGRES_* administrator credentials. Missing JWT outside test/local-dev fails startup; missing DATABASE_URL fails protected authenticated requests with503, while unauthenticated requests return401.

The server's release overlay is a local managed file: merging a repository overlay change does not automatically install that file on Ubuntu. Apply only the reviewed environment keys to the private host configuration before its image is deployed. Do not change the Auto-CD timer/deployer logic or manually deploy unmerged images. Keep all crawler timers disabled.

Read-only diagnosis found 51 career tables, 20 users, 18 profiles, zero auth identities/sessions/consent policies, and no dedicated DATABASE_URL/JWT_SECRET. Authenticated GET/PATCH stays HOLD until an approved synthetic test account and least-privilege DB connection exist. Do not create schema/roles/seed or issue artificial tokens to claim staging authentication PASS.

Validation: backend regressions plus synthetic app route tests; CI builds backend/frontend Docker images and tests HTTP through real Nginx, including401, forwarded signed-token503 (no DB configured), Swagger, legacy health, and sanitized crawler503. Disposable smoke containers have no DB or persistent volumes. No shared DB writes are needed for these checks.

Post-deployment: verify SHA/digests against publish manifest and Auto-CD success state; read /api/health, /api/version, /api/openapi.json, /api/docs and /api/v1/me. Record401 only as routing/auth guard evidence. Authenticated200/PATCH200 requires the approved test account; restore its changed field afterward, preserving other users. Compare before/after career/crawler fingerprints and PostgreSQL volume.
