// #328 Google SSO 실제 브라우저 시나리오 (로컬: 가짜 IdP + 실제 Backend·PostgreSQL + /career 빌드 + nginx 흉내 프록시).
//
//   E2E_BASE_URL=http://localhost:9100 E2E_IDP_URL=http://localhost:9101 E2E_BACKEND_URL=http://127.0.0.1:9102 \
//   E2E_COOKIE_SECRET=<로컬 합성 키> E2E_OUT=result.json PLAYWRIGHT_CORE=<path> CHROME_PATH=<chrome> node e2e/google-sso.mjs
//
// - 준비: scripts/e2e/google_sso/README.md. 실제 Google·Staging 에 접속하지 않습니다(가짜 IdP).
// - 기록: 시나리오별 PASS/FAIL, 이동 경로(쿼리 제외 — code·state 를 남기지 않음), 네트워크 상태, 콘솔 오류.
import { createHmac } from 'node:crypto';
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const BASE = process.env.E2E_BASE_URL || 'http://localhost:9100';
const IDP = process.env.E2E_IDP_URL || 'http://localhost:9101';
const BACKEND = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:9102';
const COOKIE_SECRET = process.env.E2E_COOKIE_SECRET || '';
const APP = `${BASE}/career`;

const NEW_USER = { sub: 'e2e-sub-new-user', email: 'allowed.one@e2e.example.com', name: 'E2E 신규' };
const CONFLICT = { sub: 'e2e-sub-conflict', email: 'local.user@e2e.example.com', name: 'E2E 충돌' };
const STRANGER = { sub: 'e2e-sub-stranger', email: 'stranger@e2e.example.com', name: 'E2E 미허용' };
const LOCAL = { email: 'local.user@e2e.example.com', password: 'e2e-local-password-1', name: 'E2E 로컬' };

const results = [];
const pathOnly = (url) => { try { const u = new URL(url); return `${u.origin === BASE ? '' : u.origin}${u.pathname}`; } catch { return url; } };

async function identity(user) {
  const q = new URLSearchParams(user);
  const res = await fetch(`${IDP}/_identity?${q}`);
  if (!res.ok) throw new Error('idp identity failed');
}

// 이벤트는 페이지마다 한 번만 구독하고, 지금 실행 중인 시나리오의 기록(current)에만 쌓습니다.
let current = null;
const watched = new WeakSet();
function watch(page) {
  if (watched.has(page)) return;
  watched.add(page);
  page.on('framenavigated', (f) => { if (current && f === page.mainFrame()) current.navigation.push(pathOnly(f.url())); });
  page.on('response', (r) => {
    const url = r.url();
    if (current && (url.startsWith(BASE) || url.startsWith(IDP))) current.network.push(`${r.request().method()} ${pathOnly(url)} ${r.status()}`);
  });
  page.on('console', (m) => { if (current && m.type() === 'error') current.console.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => current?.console.push(`pageerror: ${String(e).slice(0, 200)}`));
}

async function scenario(id, title, fn) {
  const log = { id, title, status: 'FAIL', checks: [], navigation: [], network: [], console: [] };
  const check = (name, ok, detail = '') => { log.checks.push({ name, ok: Boolean(ok), detail }); if (!ok) throw new Error(`${name} ${detail}`); };
  current = log;
  try {
    await fn({ log, check });
    log.status = 'PASS';
  } catch (error) {
    log.error = String(error).slice(0, 300);
  }
  results.push(log);
  console.log(`${log.status} ${id} ${title}${log.error ? ` — ${log.error}` : ''}`);
}

// 쿠키 Path 가 /career/... 이므로 URL 로 거르지 않고 컨텍스트의 전체 쿠키를 봅니다(호스트는 하나뿐).
const cookieNames = async (ctx) => (await ctx.cookies()).map((c) => c.name).sort();
const cookieValue = async (ctx, name) => (await ctx.cookies()).find((c) => c.name === name)?.value;

function hs256(payload) {
  const enc = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const head = enc({ alg: 'HS256', typ: 'JWT' });
  const body = enc(payload);
  const sig = createHmac('sha256', COOKIE_SECRET).update(`${head}.${body}`).digest('base64url');
  return `${head}.${body}.${sig}`;
}

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true });
const ctx = await browser.newContext();
const page = await ctx.newPage();
let callbackUrl = null;
page.on('request', (r) => { if (r.url().includes('/api/v1/auth/google/callback') && !callbackUrl) callbackUrl = r.url(); });

await scenario('C01', '신규 Google 사용자: /career/ → 게이트 → Google → 약관 동의 → 자동 가입·로그인', async ({ log, check }) => {
  watch(page);
  await identity(NEW_USER);
  await page.goto(`${APP}/`);
  await page.waitForURL(/\/career\/auth\/google\/signup$/, { timeout: 15000 });
  check('gate redirected to Google start', log.navigation.some((p) => p.endsWith('/api/v1/auth/google/start') || p.includes('/authorize')) || log.network.some((n) => n.includes('/api/v1/auth/google/start 302')));
  check('fake Google authorize visited', log.network.some((n) => n.includes('/authorize 302')));
  check('callback 302 to signup page', log.network.some((n) => n.includes('/career/api/v1/auth/google/callback 302')));
  await page.getByText(NEW_USER.email).waitFor();
  check('pending email shown from server', true);
  const submit = page.getByRole('button', { name: '동의하고 가입' });
  await submit.click();
  check('required consents enforced on the client', await page.getByRole('alert').textContent().then((t) => t.includes('필수 약관')));
  await page.getByLabel(/이용약관 동의 \(필수\)/).check();
  await page.getByLabel(/개인정보 처리 동의 \(필수\)/).check();
  await submit.click();
  await page.waitForURL(/\/career\/?$/, { timeout: 15000 }); // navigate('/') 는 basename 기준 '/career'
  check('signup POST 201', log.network.some((n) => n === 'POST /career/api/v1/auth/google/signup 201'));
  await page.goto(`${APP}/account`);
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('account shows Google email', await page.getByText(NEW_USER.email).count() > 0);
  check('cookies: gate + refresh, no pending', JSON.stringify(await cookieNames(ctx)) === JSON.stringify(['career_gate', 'refresh_token']), JSON.stringify(await cookieNames(ctx)));
});

await scenario('C05', '세션 유지: 새로고침·페이지 이동·탭 전환·refresh 회전', async ({ check }) => {
  watch(page);
  const before = await cookieValue(ctx, 'refresh_token');
  await page.reload();
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('reload keeps the session', true);
  check('refresh token rotated on reload', (await cookieValue(ctx, 'refresh_token')) !== before);
  await page.getByRole('link', { name: '나의 기술 관리' }).click();
  await page.waitForURL(`${APP}/me/skills`);
  check('protected page after in-app navigation', !page.url().includes('/login'));
  const other = await ctx.newPage();
  await other.goto(`${APP}/job-roles`);
  await page.bringToFront();
  await page.goto(`${APP}/account`);
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('session survives tab switch', true);
  await other.close();
});

await scenario('C06a', '일반 로그아웃: 앱 세션만 종료, 게이트 유지, 로그인 화면 표시(Google 로 튕기지 않음)', async ({ check }) => {
  watch(page);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.waitForURL(/\/career\/login/, { timeout: 10000 });
  await page.waitForTimeout(1500);
  check('stays on login page', page.url().startsWith(`${APP}/login`));
  check('gate cookie kept, refresh cookie gone', JSON.stringify(await cookieNames(ctx)) === JSON.stringify(['career_gate']), JSON.stringify(await cookieNames(ctx)));
  check('Google button visible', await page.getByRole('link', { name: 'Google로 계속하기' }).count() === 1);
});

await scenario('C04a', '게이트 아래 로컬 회원가입·로그인 공존', async ({ log, check }) => {
  watch(page);
  await page.goto(`${APP}/signup`);
  await page.getByLabel(/^이메일/).fill(LOCAL.email);
  await page.getByLabel(/^이름/).fill(LOCAL.name);
  await page.getByLabel(/^비밀번호/).first().fill(LOCAL.password);
  await page.getByLabel(/^비밀번호 확인/).fill(LOCAL.password);
  await page.getByLabel(/이용약관 동의/).check();
  await page.getByLabel(/개인정보 처리 동의/).check();
  await page.getByRole('button', { name: '회원가입' }).click();
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('local signup 201', log.network.some((n) => n === 'POST /career/api/v1/auth/signup 201'));
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.waitForURL(/\/career\/login/);
  await page.getByLabel(/^이메일/).fill(LOCAL.email);
  await page.getByLabel(/^비밀번호/).fill(LOCAL.password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('local login 200', log.network.some((n) => n === 'POST /career/api/v1/auth/login 200'));
  check('local account shown', await page.getByText(LOCAL.email).count() > 0);
  await page.getByRole('button', { name: '로그아웃', exact: true }).click();
  await page.waitForURL(/\/career\/login/);
});

await scenario('C04b', '같은 이메일 로컬 계정 + Google 로그인 → 자동 연결 거부·로컬 로그인 안내', async ({ check }) => {
  watch(page);
  await identity(CONFLICT);
  await page.getByRole('link', { name: 'Google로 계속하기' }).click();
  await page.waitForURL(/google_error=email_conflict/, { timeout: 15000 });
  check('conflict message shown', await page.getByText('이 이메일로 가입된 계정이 있습니다').count() > 0);
  check('no session cookie issued', !(await cookieNames(ctx)).includes('refresh_token'));
});

await scenario('C02', '재방문: 완전 로그아웃 → 정적 페이지(루프 없음) → /career/ → Google → 약관 없이 자동 로그인', async ({ log, check }) => {
  watch(page);
  await identity(NEW_USER);
  await page.goto(`${APP}/login`);
  await page.getByRole('link', { name: 'Google로 계속하기' }).click();
  await page.waitForURL(`${APP}/account`, { timeout: 15000 });
  await page.getByRole('heading', { name: '내 계정' }).waitFor();
  check('returning login via done route', log.navigation.some((p) => p === '/career/auth/google/done'));
  check('no consent screen for returning user', !log.navigation.some((p) => p.endsWith('/auth/google/signup')));
  await page.getByRole('button', { name: '완전 로그아웃' }).click();
  await page.waitForURL(/\/career\/api\/v1\/auth\/google\/signed-out$/, { timeout: 10000 });
  await page.waitForTimeout(2000);
  check('stays on static signed-out page (no auto re-login loop)', page.url().endsWith('/auth/google/signed-out'));
  check('signed-out text', await page.getByText('로그아웃되었습니다').count() > 0);
  check('all auth cookies removed', (await cookieNames(ctx)).length === 0, JSON.stringify(await cookieNames(ctx)));
  check('signout POST 204', log.network.some((n) => n === 'POST /career/api/v1/auth/google/signout 204'));
  log.navigation.length = 0;
  await page.goto(`${APP}/`);
  await page.waitForURL(/\/career\/?$/, { timeout: 15000 });
  await page.waitForLoadState('networkidle');
  await page.goto(`${APP}/account`);
  await page.getByRole('heading', { name: '내 계정' }).waitFor({ timeout: 10000 });
  check('re-entry went through Google and done (no signup)', log.navigation.includes('/career/auth/google/done') && !log.navigation.some((p) => p.endsWith('/auth/google/signup')));
});

await scenario('C10', 'callback URL 재사용(replay) 거부', async ({ log, check }) => {
  watch(page);
  check('captured a callback URL', Boolean(callbackUrl));
  const before = await fetch(`${IDP}/_stats`).then((r) => r.json());
  await page.goto(callbackUrl);
  await page.waitForLoadState('networkidle');
  const after = await fetch(`${IDP}/_stats`).then((r) => r.json());
  // 이미 로그인한 브라우저라 /login?google_error=failed 로 간 뒤 로그인 화면이 /account 로 넘겨 준다 → 응답으로 판정
  check('replayed callback rejected (302 to login error, no new session)', log.network.includes('GET /career/api/v1/auth/google/callback 302') && log.navigation.includes('/career/login'), JSON.stringify(log.navigation));
  check('no token exchange for the replay', after.token_requests === before.token_requests);
});

await scenario('C03', '미허용 Google 계정: 정적 403, 계정·세션·게이트 없음, 무한 리디렉트 없음', async ({ log, check }) => {
  const fresh = await browser.newContext();
  const p = await fresh.newPage();
  watch(p);
  await identity(STRANGER);
  await p.goto(`${APP}/`);
  await p.getByText('허용되지 않은 Google 계정입니다').waitFor({ timeout: 15000 });
  await p.waitForTimeout(1500);
  check('callback answered 403', log.network.some((n) => n === 'GET /career/api/v1/auth/google/callback 403'));
  check('navigation chain is short (no loop)', log.navigation.length <= 6, String(log.navigation.length));
  check('no gate/refresh/pending cookie', !(await cookieNames(fresh)).some((n) => ['career_gate', 'refresh_token', 'career_g_pending'].includes(n)), JSON.stringify(await cookieNames(fresh)));
  await fresh.close();
});

await scenario('C03b', 'Google 로그인 취소: 정적 안내, 루프 없음', async ({ log, check }) => {
  const fresh = await browser.newContext();
  const p = await fresh.newPage();
  watch(p);
  await identity({ sub: 'x', email: 'cancel', name: 'x' });
  await p.goto(`${APP}/`);
  await p.getByText('Google 로그인이 취소되었습니다').waitFor({ timeout: 15000 });
  await p.waitForTimeout(1500);
  check('navigation chain is short (no loop)', log.navigation.length <= 6, String(log.navigation.length));
  check('no gate cookie', !(await cookieNames(fresh)).includes('career_gate'));
  await fresh.close();
});

await scenario('C07', '직접 API 접근: 게이트 없음·위조·만료·Bearer 만 → 401, 허용 세션 → 200, Backend 직통(LAN 재현) → 401', async ({ log, check }) => {
  const api = `${APP}/api/v1`;
  const code = async (res) => `${res.status}:${res.status === 204 ? '' : (await res.json().catch(() => ({}))).code ?? ''}`;
  log.network.push(`no cookie ${await code(await fetch(`${api}/consent-policies`))}`);
  check('no gate cookie → 401 EDGE_AUTH_REQUIRED', log.network.at(-1).endsWith('401:EDGE_AUTH_REQUIRED'));
  log.network.push(`forged ${await code(await fetch(`${api}/consent-policies`, { headers: { Cookie: 'career_gate=forged.value.x' } }))}`);
  check('forged gate → 401', log.network.at(-1).endsWith('401:EDGE_AUTH_REQUIRED'));
  const now = Math.floor(Date.now() / 1000);
  const expired = hs256({ purpose: 'google_gate', iss: 'ai-career-platform/google', iat: now - 7200, exp: now - 3600, jti: 'e2e', sub: NEW_USER.sub, email: NEW_USER.email });
  log.network.push(`expired ${await code(await fetch(`${api}/consent-policies`, { headers: { Cookie: `career_gate=${expired}` } }))}`);
  check('expired gate → 401', log.network.at(-1).endsWith('401:EDGE_AUTH_REQUIRED'));
  // 허용된 세션: 브라우저 로그인 상태에서 쿠키를 가져와 refresh → access token
  const gate = await cookieValue(ctx, 'career_gate');
  const refresh = await cookieValue(ctx, 'refresh_token');
  check('browser session has gate + refresh', Boolean(gate && refresh));
  const r = await fetch(`${api}/auth/refresh`, { method: 'POST', headers: { Cookie: `career_gate=${gate}; refresh_token=${refresh}`, 'X-CSRF-TOKEN': '1' } });
  check('refresh with gate → 200', r.status === 200, String(r.status));
  const { access_token: token } = await r.json();
  log.network.push(`bearer only ${await code(await fetch(`${api}/me`, { headers: { Authorization: `Bearer ${token}` } }))}`);
  check('Bearer without gate → 401', log.network.at(-1).endsWith('401:EDGE_AUTH_REQUIRED'));
  const ok = await fetch(`${api}/me`, { headers: { Authorization: `Bearer ${token}`, Cookie: `career_gate=${gate}` } });
  log.network.push(`gate+bearer ${ok.status}`);
  check('gate + Bearer → 200', ok.status === 200);
  log.network.push(`backend direct ${await code(await fetch(`${BACKEND}/api/v1/consent-policies`))}`);
  check('backend direct (LAN analogue) without gate → 401', log.network.at(-1).endsWith('401:EDGE_AUTH_REQUIRED'));
  log.network.push(`static shell without gate ${(await fetch(`${APP}/account`, { redirect: 'manual' })).status}`);
  check('SPA shell without gate → 302 to Google start', log.network.at(-1).endsWith('302'));
});

await browser.close();
const out = { generated_at: new Date().toISOString(), base: BASE, results };
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, JSON.stringify(out, null, 2));
const failed = results.filter((r) => r.status !== 'PASS').length;
console.log(`E2E_GOOGLE_SSO total=${results.length} pass=${results.length - failed} fail=${failed}`);
process.exit(failed ? 1 : 0);
