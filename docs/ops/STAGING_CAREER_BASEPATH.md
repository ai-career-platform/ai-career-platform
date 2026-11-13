# Staging: AI Career Platform under `/career/`, Redmine at `/`

Parent: #269 (Staging manual E2E). This change: `fix/staging-career-basepath`.

One public origin (`https://sulfite-footbath-next.ngrok-free.dev`) serves several services. Redmine owns `/`.
AI Career Platform must stay entirely under `/career/`.

## 1. Where requests go (observed read-only on 2026-11-13)

```text
ngrok agent (`ngrok http 80`)
  └─ shared host nginx :80, /etc/nginx/sites-enabled/dbresting-shared.conf
       ├─ /church/   → 127.0.0.1:8081   (another service; not touched)
       ├─ /career/   → include /etc/nginx/snippets/ai-career-route.conf
       │               proxy_pass http://127.0.0.1:18080/;   (strips the /career prefix)
       │               + sub_filter: 'href="/'→'href="/career/', 'src="/'→'src="/career/', '"/api/'→'"/career/api/'
       └─ /          → 127.0.0.1:3000   (Redmine)

127.0.0.1:18080 = frontend container (poc/staging/frontend/nginx.conf), which serves the SPA from /
                  and proxies /api/v1/ and /api/ to the backend container.
```

The shared nginx files exist only on the server. They are **not** in this repository.

## 2. Why the platform leaked onto `/`

| # | Cause | Effect |
|---|---|---|
| A | The React Router had no `basename`. Links such as `/`, `/login` and `/signup` were app-root paths. | Clicking the logo moved the browser to `/` client-side, which showed the app at Redmine's URL. Reloading `/login` loaded Redmine's own login page. |
| B | The bundle was built with Vite base `/`. Only the HTML was fixed up, by the shared `sub_filter`. | Assets loaded only because of the HTML rewrite. |
| C | The bundle calls `` `/api` ``, a template literal. The shared `sub_filter '"/api/'` never matches it. | The browser called `/api/v1/...`, which Redmine answers with 404. `GET /api/v1/consent-policies` returned 404 (Redmine) and `/career/api/v1/consent-policies` returned 200. |
| D | The refresh cookie has `Path=/api/v1/auth`. The browser calls `/career/api/v1/auth/refresh`. | The cookie is never sent, so the session is lost on reload. |

## 3. Design (prefix stripped at the edge, app built for `/career/`)

- **Build:** `VITE_BASE_PATH=/career/ VITE_API_BASE_URL=/career/api` for the Staging image build only (`poc/staging/frontend/Dockerfile.integrated`). Tests and local dev keep `/`.
- **Router:** `createBrowserRouter(routes, { basename: routerBasename(import.meta.env.BASE_URL) })`, which gives `/career`. The logo, login and signup links, the guards and the 404 page all stay under `/career`.
- **API:** `/career/api/v1/...`. The shared nginx strips `/career`, so the container sees `/api/v1/...`. The backend is unchanged.
- **Assets:** HTML references `/career/assets/...`. After the strip, the container serves `/assets/...`.
- **Container nginx:** an extra `location /career/assets/` alias serves the same files when the prefix is still present. This keeps the new image working before the shared `sub_filter` is removed. That rewrite turns `/career/assets/` into `/career/career/assets/`, which after the strip arrives as `/career/assets/`.
- **Container health:** the container still answers `/`, `/api/health` and so on. The `deploy.py` health checks are unchanged.

## 4. Proposed shared-nginx change (NOT applied; needs approval)

Replace `/etc/nginx/snippets/ai-career-route.conf` with the following. The `= /career` redirect and the strip are kept, `sub_filter` is removed, and the cookie path is mapped:

```nginx
location = /career {
    return 301 /career/;
}
location /career/ {
    proxy_pass http://127.0.0.1:18080/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $dbresting_forwarded_proto;
    proxy_read_timeout 60s;
    # Refresh cookie: backend sets Path=/api/v1/auth; the browser calls /career/api/v1/auth/*
    proxy_cookie_path /api/v1/auth /career/api/v1/auth;
}
```

`location /` (Redmine), `/church/` and the ngrok agent are untouched.

## 5. Apply order

1. Merge the PR. Auto-CD deploys the new frontend image. It works with the existing snippet thanks to the container alias.
2. Verify:
   - `/career/` loads.
   - The logo stays on `/career`.
   - `/career/login` and `/career/signup` load.
   - `/career/api/v1/consent-policies` returns 200.
   - `/` is still Redmine.
3. With approval from the Redmine/server owner:
   1. `sudo cp ai-career-route.conf ai-career-route.conf.bak-<ts>`
   2. Write §4.
   3. `sudo nginx -t`
   4. `sudo systemctl reload nginx`. This reloads the **shared** nginx, so a window must be agreed.
4. Verify again: assets load without the double `/career/career/`, and the session survives a reload (refresh cookie).

## 6. Rollback

- **Shared nginx:** restore `ai-career-route.conf.bak-<ts>`, then run `nginx -t` and `systemctl reload nginx`.
- **App:** revert the PR on `main`. Auto-CD redeploys the previous image, which uses base `/` and works with the old `sub_filter`.

If the app has been reverted, restore the old snippet too: the old bundle relies on `sub_filter` for its assets.

## 7. Not verified here

The real Staging browser flow, the shared nginx change, the cookie refresh under `/career`, and real signups are **NOT_VERIFIED**. Signing up on Staging creates real DB accounts.
