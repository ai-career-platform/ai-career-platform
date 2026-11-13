# Free Google first-factor gate for `/career/` (#265 design)

Parent: #263 · This design: #265 · Apply: #266 (not done here) · E2E: #267

**Status: DESIGN ONLY.** Nothing in this folder is deployed. Every file is a draft (`*.example` or `*.draft`) and holds no secrets.

## 1. Goal and constraints

- 11–30 named Google accounts pass a first gate before reaching AI Career Platform under `/career/`, including its API.
- The platform's own signup and login stay unchanged as the second gate. Google sign-in neither creates nor logs in a platform account.
- **Additional monthly cost: 0.** No ngrok upgrade, ngrok Traffic Policy OAuth, or paid Google service.
- Redmine (`/`), `/church/`, the ngrok agent, and its PostgreSQL TCP tunnel are not changed.

## 2. Current environment (read-only check, 2026-11-13)

| Item | Observed |
|---|---|
| ngrok | 3.39.13 (snap). `ngrok http 80` was started by hand on 2026-10-26. No traffic policy. The config holds only `authtoken` (no API key, so the CLI can't read plan or usage). |
| Shared nginx | 1.28.3 with `--with-http_auth_request_module` and `--with-http_realip_module`. `dbresting-shared.conf` routes `/church/` to :8081, `/career/` to the snippet `ai-career-route.conf` (`proxy_pass http://127.0.0.1:18080/`, prefix stripped), and `/` to Redmine :3000. |
| Existing auth gate | None. There's no oauth2-proxy, Authelia, Vouch or Pomerium, and no `auth_request`, `auth_basic`, `X-Auth-Request-*` or `proxy_cookie_*` in the nginx config. |
| App auth | Uses its own `Authorization: Bearer` header plus the HttpOnly cookie `refresh_token` (Path `/api/v1/auth`). The app reads no `X-Forwarded-User/Email` header. |
| Redmine cookie | `_redmine_session` (Path `/`). The gate uses `_oauth2_proxy_career` (Path `/career/`), so the names don't clash. |
| Frontend container ports | `127.0.0.1:18080` and **`<LAN IP>:18080`** (base `compose.yaml`). The LAN address is private, so it can't be reached from the internet. However, **a LAN client can bypass the gate**. See §8. |
| PR #271 | Merged as 82ca9e4: the bundle is built for `/career/`. Auto-CD recreated the frontend container at 2026-11-13 00:34Z. |

## 3. Architecture

```text
browser ─https→ ngrok (unchanged) ─→ shared nginx :80
   /                → Redmine            (no auth, unchanged)
   /church/         → :8081              (no auth, unchanged)
   /career/oauth2/  → oauth2-proxy 127.0.0.1:4180   (sign_in / start / callback / sign_out)
   /career/api/     → auth_request → 202 ? frontend:18080/api/ : 401 JSON
   /career/         → auth_request → 202 ? frontend:18080/     : 302 → Google sign-in
                         then the app's own login (2nd gate) as today
```

**No ngrok restart is needed.** Only the `/career` snippet changes, followed by an `nginx -t` and a graceful reload.

## 4. Files in this folder

| File | Target in #266 |
|---|---|
| `oauth2-proxy.cfg.example` | `/etc/oauth2-proxy/career/oauth2-proxy.cfg` (root:oauth2-proxy 0640) |
| `ai-career-route.conf.draft` | `/etc/nginx/snippets/ai-career-route.conf`, replacing the current file after a backup |
| `oauth2-proxy-career.service.example` | `/etc/systemd/system/oauth2-proxy-career.service` |
| `allowed_emails.txt.example` | Format only. The real file is `/etc/oauth2-proxy/career/allowed_emails.txt`, kept on the server and never in git. |

Key decisions are checked against the oauth2-proxy **v7.15.6** docs and source (latest release, 2026-11-05):

- **Allowlist:** only `authenticated_emails_file` is set, and `email_domains` is left unset.
  - In `validator.go`, a valid email must match a domain or the file.
  - An empty file allows nobody, and a missing file aborts startup (`logger.Fatalf`). Both fail closed.
  - Never use `email_domains = "*"`.
- **Trusted proxy:** `trusted_proxy_ips = ["127.0.0.1/32"]`. **`trusted_ips` must never be set.** The docs call it "an authentication bypass, not a list of trusted reverse proxies", and nginx runs on 127.0.0.1.
- **Auth endpoint:** `/career/oauth2/auth` returns "202 Accepted ... or a 401 Unauthorized". The nginx block for it is `internal`, so it can't be called from outside.
- **App credentials untouched:** `pass_authorization_header`, `set_authorization_header` and `set_xauthrequest` are false, so the app's Bearer token (second gate) is never overwritten. `skip_jwt_bearer_tokens` is false, so the app token is never accepted as a Google session.
- **Scope and email checks:**
  - The scope is `openid email profile` only. In Testing mode, tokens limited to these scopes don't expire after 7 days (Google docs).
  - `insecure_oidc_allow_unverified_email` is false.
- **State check:** oauth2-proxy's built-in CSRF state cookie and nonce are used.

## 5. Nginx location order and bypass review

- `= /career/oauth2/auth` (exact, internal) is matched first. Next comes the longest prefix: `/career/oauth2/`, then `/career/api/`, then `/career/`. Anything else goes to the existing blocks.
- **No redirect loop:** `/career/oauth2/*` has no `auth_request`. A signed-out browser is sent to `/career/oauth2/sign_in?rd=<path>`, which with `skip_provider_button` goes straight to Google and then to `/career/oauth2/callback`.
- **The API never redirects:** an unauthenticated call gets `401 {"code":"EDGE_AUTH_REQUIRED"}`.
- **Encoded paths:** nginx decodes the URI before matching, so `/career/%61pi/` still lands in a protected block. Everything under `/career/` except `/career/oauth2/` is protected.
- **Root paths:** `/api/*` and `/login` at the root go to Redmine, not the app (PR #271), so they are no bypass.
- **Forged headers:** `X-Forwarded-User/Email` and `X-Auth-Request-User/Email` are blanked before the app. oauth2-proxy accepts `X-Forwarded-*` only from 127.0.0.1.
- **Bypass via direct access:** see §8.
- **Syntax check:** `nginx -t` passed on 2026-11-13 using the draft in a throwaway `/tmp` config with Staging's nginx 1.28.3. The live config was not touched.

## 6. Google setup (owner's browser, existing project)

**Project:** reuse the owner's existing default gcloud project (ID kept out of git; billing flag on). An OAuth client needs no API to be enabled.

**Not done by CLI:** standard *Google Auth Platform → Clients → Web application* clients can't be listed or created with `gcloud`, and `gcloud iam oauth-clients` is Workforce Identity, a different resource. So existing clients are NOT_VERIFIED and nothing was created.

Steps for the owner, in Google Cloud Console with that existing project:

1. **Google Auth Platform → Branding:** set the app name (for example "AI Career Staging") and the support email. Add `sulfite-footbath-next.ngrok-free.dev` as an **authorized domain**.
   - `ngrok-free.dev` is on the Public Suffix List, so this subdomain is its own registrable domain.
   - Google says all redirect-URI domains "must be pre-registered here". Whether the Console accepts this domain without ownership verification is **NOT_VERIFIED**.
2. **Audience:** External, publishing status **Testing**, and add the 11–30 Google accounts as **test users** (limit 100). This is a second, Google-side allowlist.
3. **Data access:** `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` only.
4. **Clients → Create client → Web application:**
   - Authorized redirect URI, exactly: `https://sulfite-footbath-next.ngrok-free.dev/career/oauth2/callback`. The scheme, case and trailing slash must all match.
   - No JavaScript origin is needed.
5. Keep the client ID and secret only in the server's 0600 files during #266. **Never put them in GitHub, an issue or a chat.**

## 7. Allowlist handling (private)

- **Who:** the PM hands the list over through a private channel, not GitHub.
- **Where it lives:** `/etc/oauth2-proxy/career/allowed_emails.txt`, owned by `root:oauth2-proxy`, mode 0640. One exact address per line, lowercase.
- **Second list:** the same addresses go into the Google Console test users.
- **Change:** back up the file, edit it, then `sudo systemctl restart oauth2-proxy-career`. This affects only `/career`.
- **Empty file:** nobody is allowed. Use it as an emergency lock.

## 8. Risks to close in #266

1. **LAN direct port:** the base `compose.yaml` publishes the frontend on `<LAN IP>:18080`, so a LAN client can skip the gate. Proposal: publish on `127.0.0.1:18080` only. This changes the server-owned base compose file, so it needs separate approval. Auto-CD health checks use 127.0.0.1 and are unaffected.
2. **ngrok usage:** the agent counted **30,356 HTTP requests** since 2026-10-26 01:28 UTC, about 49k a month at that pace and across all services. The Free plan lists 20,000 requests and 1 GB a month. The real plan and the month's usage need the **ngrok dashboard (Usage)**, so they are NOT_VERIFIED. The gate itself adds only one sign-in redirect chain per session. `auth_request` is an internal nginx call and never goes through ngrok.
3. **ngrok warning page:** how the Free plan's browser warning page interacts with the Google redirect chain is NOT_VERIFIED (#267).
4. **Deep links:** a link with several query parameters may lose those after `&` in `rd` (relative `$request_uri`).

## 9. Apply, verify, rollback (#266, with approval; Redmine and /church/ untouched)

```bash
# 0. preconditions: PR #271 live, Google client created, allowlist received, ngrok usage confirmed
curl -s http://127.0.0.1:18080/ | grep -q 'src="/career/assets/' && echo BASE_OK

# 1. install the pinned binary (verify checksum)
V=v7.15.6; cd /tmp
curl -fsSLO https://github.com/oauth2-proxy/oauth2-proxy/releases/download/$V/oauth2-proxy-$V.linux-amd64.tar.gz
curl -fsSLO https://github.com/oauth2-proxy/oauth2-proxy/releases/download/$V/oauth2-proxy-$V.linux-amd64.tar.gz-sha256sum.txt
sha256sum -c oauth2-proxy-$V.linux-amd64.tar.gz-sha256sum.txt
tar xzf oauth2-proxy-$V.linux-amd64.tar.gz
sudo install -m 0755 oauth2-proxy-$V.linux-amd64/oauth2-proxy /usr/local/bin/oauth2-proxy

# 2. user, config, secrets (secret values typed on the server, never echoed into logs)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin oauth2-proxy
sudo install -d -o root -g oauth2-proxy -m 0750 /etc/oauth2-proxy/career
sudo install -o root -g oauth2-proxy -m 0640 oauth2-proxy.cfg /etc/oauth2-proxy/career/oauth2-proxy.cfg
sudo install -o root -g oauth2-proxy -m 0640 /dev/null /etc/oauth2-proxy/career/allowed_emails.txt   # then add emails
sudo sh -c 'umask 027; python3 -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode(),end=\"\")" > /etc/oauth2-proxy/career/cookie_secret'
sudo sh -c 'umask 027; cat > /etc/oauth2-proxy/career/client_secret'   # paste the secret, Ctrl-D, no trailing newline
sudo chgrp oauth2-proxy /etc/oauth2-proxy/career/cookie_secret /etc/oauth2-proxy/career/client_secret

# 3. service (loopback only)
sudo install -m 0644 oauth2-proxy-career.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now oauth2-proxy-career
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4180/ping                  # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4180/career/oauth2/auth    # 401

# 4. nginx (backup -> replace snippet -> test -> graceful reload)
TS=$(date +%Y%m%d%H%M%S)
sudo cp -a /etc/nginx/snippets/ai-career-route.conf /etc/nginx/snippets/ai-career-route.conf.bak-$TS
sudo install -m 0644 ai-career-route.conf.draft /etc/nginx/snippets/ai-career-route.conf
sudo nginx -t && sudo systemctl reload nginx

# 5. verify (Host header through the shared nginx)
H='Host: sulfite-footbath-next.ngrok-free.dev'
for p in / /projects /church/ /career/ /career/login /career/api/v1/consent-policies /career/oauth2/auth /career/oauth2/sign_in; do
  printf '%-36s ' "$p"; curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -H "$H" "http://127.0.0.1$p"; done
# expect: / and /projects = Redmine as before; /church/ = as before; /career/* = 302 to /career/oauth2/sign_in;
#         /career/api/... = 401 EDGE_AUTH_REQUIRED; /career/oauth2/auth = 404 (internal); sign_in = 302 to accounts.google.com
```

**Rollback** (about 1 minute; Redmine and `/church/` keep running throughout):

```bash
sudo cp -a /etc/nginx/snippets/ai-career-route.conf.bak-$TS /etc/nginx/snippets/ai-career-route.conf
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl disable --now oauth2-proxy-career
# optional cleanup after sign-off: remove /etc/oauth2-proxy/career, the unit, /usr/local/bin/oauth2-proxy, the user
```

## 10. Cost view

| Part | Charge | Status |
|---|---|---|
| oauth2-proxy | Open source (MIT), runs on the existing host as a loopback service | 0 |
| nginx `auth_request` | Already compiled in | 0 |
| ngrok | Unchanged agent, no Traffic Policy and no OAuth action, so ngrok OAuth MAU billing doesn't apply. Free request and bandwidth limits against actual usage are unknown. | **NOT_VERIFIED** (dashboard) |
| Google OAuth client | Created in an existing project; no API to enable; Testing status with ≤100 test users. The docs I read don't state a price. | No paid service needed; explicit pricing NOT_VERIFIED |
