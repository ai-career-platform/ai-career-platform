# Agent instructions (all agents)

## Crawler / T61 external collection

Before any crawler LIVE work, approval file or collection-permission question, read
[`docs/data/T61_PM_APPROVAL_POLICY.md`](docs/data/T61_PM_APPROVAL_POLICY.md). It is the single source of truth for:

- **PM internal approval (granted 2026-11-17, do not ask again):**
  - crawler development and tests;
  - JobKorea as the target;
  - at most 1,000 items, with an initial goal of 100 new;
  - local PostgreSQL storage for permitted data only;
  - at least 2 s between requests, one at a time;
  - stop immediately on 403/429/CAPTCHA.

  GCP transfer and enabling the nightly scheduler each need a separate approval.
- **The provider-permission requirement:**
  - Every LIVE JobKorea request needs BOTH the PM approval file AND a provider permission file (evidence from JobKorea itself).
  - The code enforces this in `crawler/policy/provider_permission.py`, via `import_jobkorea_html._permit`, `night_crawl.live_gate` and `harvest.preflight`.
  - Current status: **NOT_CONFIRMED**, so LIVE is blocked.

Rules:

- Do not create, guess or fill approval or provider-permission files.
- Do not set `CRAWLER_LIVE_SCHEDULE_APPROVED` to get around the gate.
- Approval and permission files live outside Git, under `C:\dev\crawler-data\secrets\t61\`.
- If LIVE is blocked, report only the unmet condition: `BLOCKED_PERMISSION: PROVIDER_PERMISSION_MISSING`. Continue with work that needs no LIVE request.
- Record only verified states, and only in the policy document's status table (§3).

## General

- Never print or commit secrets: `.env`, `C:\dev\crawler-data\secrets\`, webhooks, DB passwords.
- No direct commits to `main`. Use a branch and a PR; branch protection requires an independent approving review.
