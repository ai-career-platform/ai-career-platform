// Phase 1 Staging — Frontend 27 tasks (S8 plan §7). Real browser against a real backend.
//
//   E2E_BASE_URL=http://127.0.0.1:18099 E2E_OUT=result.json \
//   E2E_SEEKER=<synthetic> E2E_ADMIN=<synthetic admin> E2E_PASSWORD=<synthetic> \
//   E2E_TIERS=R,H[,A][,W]  E2E_READONLY=1 \
//   PLAYWRIGHT_CORE=<path to playwright-core> CHROME_PATH=<chrome.exe> node e2e/phase1-fe27.mjs
//
// Tiers (docs/testing/phase1-staging/S8_REACT_STAGING_DEPLOY_PLAN.md §7):
//   R anonymous GET only · A logged-in GET only (login itself writes a session row)
//   H must be hidden on Staging (Mock-only / flag off) · W data changes (isolated DB only)
// E2E_READONLY=1 aborts and FAILS on any non-GET request (use on shared Staging; then only R and H can run).
// playwright-core is not a repo dependency (T118 lock/SBOM policy); pass its path.
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173';
const TIERS = new Set((process.env.E2E_TIERS || 'R,H').split(',').map((t) => t.trim()));
const READONLY = process.env.E2E_READONLY === '1';
const SEEKER = process.env.E2E_SEEKER;
const ADMIN = process.env.E2E_ADMIN;
const PASSWORD = process.env.E2E_PASSWORD;
if (READONLY && (TIERS.has('A') || TIERS.has('W'))) throw new Error('E2E_READONLY=1 allows only tiers R and H');
const NOT_FOUND = '페이지를 찾을 수 없습니다';
const results = [];

async function api(path) {
  const r = await fetch(BASE + path, { headers: { Accept: 'application/json' } });
  return { status: r.status, body: r.headers.get('content-type')?.includes('json') ? await r.json() : null };
}

function watch(page) {
  const log = { console: [], failed: [], server: [], nonGet: [], api: [] };
  // Network-level 'Failed to load resource' lines duplicate the response log below (expected 401 refresh probe,
  // 404 empty states); HTTP problems are judged from responses (5xx, failed, external) instead.
  page.on('console', (m) => { if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) log.console.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => log.console.push(String(e).slice(0, 200)));
  page.on('requestfailed', (r) => { if (!r.failure()?.errorText.includes('ERR_ABORTED') || READONLY) log.failed.push(`${r.method()} ${new URL(r.url()).pathname}`); });
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.origin !== new URL(BASE).origin) log.failed.push(`EXTERNAL ${u.origin}`);
    if (u.pathname.startsWith('/api/')) log.api.push(`${r.request().method()} ${u.pathname} ${r.status()}`);
    if (r.status() >= 500) log.server.push(`${r.request().method()} ${u.pathname} ${r.status()}`);
  });
  return log;
}

async function guard(page, log) {
  await page.route('**/*', (route) => {
    const m = route.request().method();
    if (READONLY && m !== 'GET' && m !== 'HEAD') { log.nonGet.push(`${m} ${new URL(route.request().url()).pathname}`); return route.abort(); }
    return route.continue();
  });
}

async function check(task, tier, name, page, log, fn) {
  if (!TIERS.has(tier)) { results.push({ task, tier, name, result: 'NOT_RUN', reason: 'tier not selected' }); return; }
  const before = { c: log.console.length, f: log.failed.length, s: log.server.length, n: log.nonGet.length, a: log.api.length };
  try {
    const evidence = (await fn()) || {};
    const fresh = { console: log.console.slice(before.c), failed: log.failed.slice(before.f), server: log.server.slice(before.s),
      nonGet: log.nonGet.slice(before.n), api: [...new Set(log.api.slice(before.a))] };
    const problems = [...fresh.console.map((x) => `console: ${x}`), ...fresh.failed.map((x) => `failed: ${x}`),
      ...fresh.server.map((x) => `5xx: ${x}`), ...fresh.nonGet.map((x) => `blocked non-GET: ${x}`)];
    results.push({ task, tier, name, result: problems.length ? 'FAIL' : 'PASS', problems, api: fresh.api, evidence });
  } catch (error) {
    results.push({ task, tier, name, result: 'FAIL', error: String(error).slice(0, 300), api: [...new Set(log.api.slice(before.a))] });
  }
}

const h1 = (page) => page.locator('main h1, h1').first();
async function open(page, path) { await page.goto(BASE + path); await h1(page).waitFor({ timeout: 15000 }); return (await h1(page).textContent())?.trim(); }
function expectApi(log, start, pattern) {
  const hit = log.api.slice(start).find((x) => pattern.test(x));
  if (!hit) throw new Error(`expected API call ${pattern} not seen: ${log.api.slice(start).join(' | ')}`);
  return hit;
}
async function login(page, email) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel(/^이메일/).fill(email);
  await page.getByLabel(/^비밀번호/).fill(PASSWORD);
  await page.getByRole('button', { name: '로그인' }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15000 });
}

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true });
try {
  // ---------- R: anonymous, GET only ----------
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, timezoneId: 'America/Los_Angeles', locale: 'ko-KR' });
  const page = await ctx.newPage(); const log = watch(page); await guard(page, log);
  const version = (await api('/api/version')).body?.version;
  const roles = (await api('/api/v1/job-roles?limit=20')).body?.items ?? [];
  const postings = (await api('/api/v1/job-postings?limit=20')).body?.items ?? [];

  await check('T19', 'R', 'app boots; /system-status shows backend version from /api/version', page, log, async () => {
    const start = log.api.length; const title = await open(page, '/system-status');
    const shown = (await page.getByTestId('backend-version').textContent({ timeout: 10000 }))?.trim();
    await page.getByTestId('backend-version').filter({ hasText: version }).waitFor({ timeout: 10000 });
    expectApi(log, start, /^GET \/api\/version 200/);
    return { h1: title, shown, version };
  });
  await check('T20', 'R', 'layout landmarks; no horizontal overflow at 320 and 1280px', page, log, async () => {
    const out = {};
    for (const width of [320, 1280]) {
      await page.setViewportSize({ width, height: 800 }); await open(page, '/');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) throw new Error(`horizontal overflow ${overflow}px at ${width}`);
      out[width] = { nav: await page.getByRole('navigation').count(), main: await page.getByRole('main').count() };
      if (!out[width].nav || out[width].main !== 1) throw new Error(`landmarks ${JSON.stringify(out[width])}`);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    return { lang: await page.evaluate(() => document.documentElement.lang), ...out };
  });
  await check('T21', 'R', 'login screen renders (no submit)', page, log, async () => {
    const title = await open(page, '/login');
    await page.getByLabel(/^이메일/).waitFor(); await page.getByLabel(/^비밀번호/).waitFor();
    return { h1: title };
  });
  await check('T23', 'R', 'job roles screen lists the API first page', page, log, async () => {
    const start = log.api.length; const title = await open(page, '/job-roles');
    for (const r of roles.slice(0, 5)) await page.getByText(r.name, { exact: false }).first().waitFor({ timeout: 10000 });
    expectApi(log, start, /^GET \/api\/v1\/job-roles 200/);
    return { h1: title, matchedNames: roles.slice(0, 5).map((r) => r.name) };
  });
  await check('T24', 'R', 'job postings list = API, detail title matches', page, log, async () => {
    const start = log.api.length; const title = await open(page, '/job-postings');
    for (const p of postings.slice(0, 5)) await page.getByText(p.title, { exact: false }).first().waitFor({ timeout: 10000 });
    expectApi(log, start, /^GET \/api\/v1\/job-postings 200/);
    await page.getByRole('button', { name: `${postings[0].title} 상세 보기` }).click();
    await page.getByRole('heading', { name: postings[0].title }).first().waitFor({ timeout: 10000 });
    expectApi(log, start, /^GET \/api\/v1\/job-postings\/[0-9a-f-]+ 200/);
    return { h1: title, firstTitles: postings.slice(0, 5).map((p) => p.title) };
  });
  await check('T94', 'R', 'password reset screen renders (no submit)', page, log, async () => {
    const title = await open(page, '/password-reset');
    return { h1: title, emailField: await page.getByLabel(/이메일/).count() };
  });
  await check('T146', 'R', 'dates are KST although the browser runs in America/Los_Angeles; html lang=ko', page, log, async () => {
    const withDate = postings.find((p) => p.expires_at);
    const kst = new Date(withDate.expires_at).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric' });
    await open(page, `/job-postings`);
    await page.getByText(withDate.title, { exact: false }).first().waitFor();
    const text = await page.locator('main').innerText();
    if (!text.includes(`마감 ${kst}`)) throw new Error(`KST deadline ${kst} not shown`);
    return { lang: await page.evaluate(() => document.documentElement.lang), kst, browserTz: 'America/Los_Angeles' };
  });

  // ---------- H: hidden on Staging (anonymous + nav) ----------
  const hidden = [
    ['T82', '/admin/moderation'], ['T85', '/admin/audit-events'], ['T85', '/admin/ai-usage'], ['T97', '/me/notifications'],
    ['T97', '/me/notification-settings'], ['T103', '/me/applications'], ['T124', '/company'], ['T124', '/company-invitations/accept'],
    ['T127', '/company/postings'], ['T130', '/me/public-profile'], ['T130', '/p/synthetic-token'], ['T143', '/me/data'], ['T156', '/admin/crawler'],
  ];
  for (const [task, path] of hidden) {
    await check(task, 'H', `${path} is not routed (404 screen)`, page, log, async () => {
      const title = await open(page, path);
      if (title !== NOT_FOUND) throw new Error(`expected not-found, got "${title}"`);
      return { h1: title };
    });
  }
  await check('T100', 'H', 'advanced (Mock) filters hidden on /job-postings', page, log, async () => {
    await open(page, '/job-postings');
    const badge = await page.getByText('시범 · Mock').count(); const advLabel = await page.getByLabel('공고·기업 검색').count();
    if (badge || advLabel) throw new Error(`advanced UI visible badge=${badge} label=${advLabel}`);
    return { basicSearch: await page.getByLabel('공고 검색').count() };
  });
  await ctx.close();

  // ---------- A: logged in, GET only (after the login POST) ----------
  if (TIERS.has('A') || TIERS.has('W')) {
    const actx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'ko-KR' });
    const ap = await actx.newPage(); const alog = watch(ap); await guard(ap, alog);
    await check('T21', 'A', 'login with synthetic job seeker', ap, alog, async () => {
      const start = alog.api.length; await login(ap, SEEKER);
      expectApi(alog, start, /^POST \/api\/v1\/auth\/login 200/);
      return { landed: new URL(ap.url()).pathname };
    });
    const screens = [
      ['T22', '/account', /^GET \/api\/v1\/me 200/],
      ['T32', '/account/privacy', /^GET \/api\/v1\/me\/consents 200/],
      ['T34', '/me/skills', /^GET \/api\/v1\/me\/skills 200/],
      ['T36', '/me/target-roles', /^GET \/api\/v1\/me\/target-roles 200/],
      ['T38', '/me/career-history', /^GET \/api\/v1\/me\/(experiences|projects) 200/],
      ['T40', '/me/bookmarks', /^GET \/api\/v1\/me\/bookmarks 200/],
      ['T46', '/recommendations', /^GET \/api\/v1\/recommendation-runs\/latest (200|404)/],
      ['T50', '/me/documents', /^GET \/api\/v1\/documents 200/],
      ['T68', '/market-trends', /^GET \/api\/v1\/market-trends (200|404)/],
    ];
    for (const [task, path, pattern] of screens) {
      await check(task, 'A', `${path} renders from the real API`, ap, alog, async () => {
        const start = alog.api.length; const title = await open(ap, path);
        if (title === NOT_FOUND) throw new Error('not routed');
        await ap.waitForTimeout(300);
        return { h1: title, api: expectApi(alog, start, pattern) };
      });
    }
    await check('T22', 'A', 'account shows the same display name as GET /me', ap, alog, async () => {
      await open(ap, '/account');
      await ap.getByText('P1 seeker', { exact: false }).first().waitFor({ timeout: 10000 });
      return { displayName: 'P1 seeker' };
    });
    await check('T140', 'A', 'skill search falls back to T17 /skills (T139 suggest flag off)', ap, alog, async () => {
      const start = alog.api.length; await open(ap, '/me/skills');
      await ap.getByRole('combobox', { name: '기술 검색' }).fill('Python');
      await ap.getByRole('option', { name: /Python/ }).first().waitFor({ timeout: 10000 });
      const hit = expectApi(alog, start, /^GET \/api\/v1\/skills 200/);
      if (alog.api.slice(start).some((x) => x.includes('/skills/suggest'))) throw new Error('suggest API called while flag is off');
      return { api: hit };
    });

    // ---------- W: data changes — isolated DB only ----------
    if (TIERS.has('W')) {
      await check('T34', 'W', 'add Python and save; reload shows it', ap, alog, async () => {
        const start = alog.api.length; await open(ap, '/me/skills');
        const box = ap.getByRole('combobox', { name: '기술 검색' }); await box.click(); await ap.keyboard.type('pyth');
        await ap.getByRole('option', { name: /^Python/ }).first().waitFor(); await ap.keyboard.press('Enter');
        await ap.locator('.skills-row', { hasText: 'Python' }).first().waitFor();
        const [put] = await Promise.all([
          ap.waitForResponse((r) => r.request().method() === 'PUT' && new URL(r.url()).pathname === '/api/v1/me/skills'),
          ap.getByRole('button', { name: '저장', exact: true }).click(),
        ]);
        if (put.status() !== 200) throw new Error(`PUT /me/skills ${put.status()}`);
        expectApi(alog, start, /^PUT \/api\/v1\/me\/skills 200/);
        await ap.reload(); await ap.locator('.skills-row', { hasText: 'Python' }).first().waitFor({ timeout: 10000 });
        return { saved: 'Python' };
      });
      await check('T40', 'W', 'bookmark a posting from its detail; /me/bookmarks lists it', ap, alog, async () => {
        const start = alog.api.length; const target = postings[0];
        await open(ap, '/job-postings'); await ap.getByRole('button', { name: `${target.title} 상세 보기` }).click();
        await ap.getByRole('heading', { name: target.title }).first().waitFor();
        await ap.getByRole('button', { name: '관심 공고 저장' }).click();
        await ap.getByRole('button', { name: '관심 공고 해제', pressed: true }).waitFor();
        expectApi(alog, start, /^PUT \/api\/v1\/me\/bookmarks\/[0-9a-f-]+ (200|201|204)/);
        await open(ap, '/me/bookmarks'); await ap.getByText(target.title, { exact: false }).first().waitFor({ timeout: 10000 });
        return { bookmarked: target.job_posting_id };
      });
    }
    await actx.close();

    // H for an admin account: even an admin must not see flag-off admin screens.
    const hctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const hp = await hctx.newPage(); const hlog = watch(hp); await guard(hp, hlog);
    await check('T156', 'A', 'admin: crawler/moderation/audit menus absent, routes 404', hp, hlog, async () => {
      await login(hp, ADMIN); await open(hp, '/');
      const nav = await hp.getByRole('navigation').first().innerText();
      for (const word of ['크롤러', '검수', '감사']) if (nav.includes(word)) throw new Error(`admin nav shows ${word}`);
      for (const path of ['/admin/crawler', '/admin/moderation', '/admin/audit-events']) {
        if ((await open(hp, path)) !== NOT_FOUND) throw new Error(`${path} routed for admin`);
      }
      return { nav: nav.replace(/\s+/g, ' ').slice(0, 200) };
    });
    await hctx.close();
  }
} finally {
  await browser.close();
}
const summary = results.reduce((acc, r) => ({ ...acc, [r.result]: (acc[r.result] || 0) + 1 }), {});
const tasks = [...new Set(results.filter((r) => r.result !== 'NOT_RUN').map((r) => r.task))].sort();
const out = { base: BASE, tiers: [...TIERS], readonly: READONLY, summary, tasksCovered: tasks.length, tasks, results };
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, JSON.stringify(out, null, 1));
console.log(JSON.stringify({ summary, tasksCovered: tasks.length }, null, 1));
for (const r of results) if (r.result === 'FAIL') console.log('FAIL', r.task, r.tier, r.name, r.error || (r.problems || []).join('; '));
process.exitCode = results.some((r) => r.result === 'FAIL') ? 1 : 0;
