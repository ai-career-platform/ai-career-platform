// E2E-006 D-1/D-2 local regression: real browser, local Vite dev server, synthetic API. Never probes Staging.
// Start VITE_API_MOCK=false npm run dev -- --port 5219, then:
// PLAYWRIGHT_CORE=<playwright path> node e2e/e2e006-error-handling.mjs
// E2E_ENGINES=chromium[,firefox,webkit] (default chromium), E2E_OUT=<JSON>, E2E_SHOTS=<directory>.
// All failures are injected inside the test browser context only.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const engines = require(process.env.PLAYWRIGHT_CORE || 'playwright');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5219';
assert.equal(new URL(base).hostname, '127.0.0.1', 'This synthetic regression is local-only');
const out = [];
const RID_500 = 'req-e2e006500aaaaaaa';
const RID_404 = 'req-e2e006404bbbbbbb';
const roleId = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const postingId = ['33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444'];
const company = { company_id: '55555555-5555-4555-8555-555555555555', name: '합성 기업' };
const roles = roleId.map((id, i) => ({ job_role_id: id, code: i ? 'BE' : 'DBA', name: i ? '백엔드 개발자' : '데이터베이스 관리자', description: `합성 직무 설명 ${i}`, required_skills: [] }));
const postings = postingId.map((id, i) => ({ job_posting_id: id, title: `합성 공고 ${i + 1}`, company, job_role: roles[i], status: 'published', location_text: '서울', employment_type: 'full_time', published_at: '2026-10-01T00:00:00Z', expires_at: null, description: `합성 공고 설명 ${i}`, source_url: null, is_bookmarked: null, required_skills: [] }));
const KINDS = {
  roles: { path: '/job-roles', list: '직무 검색 결과', api: '/api/v1/job-roles', title: roles[0].name, error: '직무 목록을 불러오지 못했습니다' },
  postings: { path: '/job-postings', list: '채용공고 검색 결과', api: '/api/v1/job-postings', title: postings[0].title, error: '채용공고를 불러오지 못했습니다' },
};
const HTML_SHELL = '<!doctype html><html lang="ko"><head><title>AI Career Platform</title></head><body><div id="root"></div></body></html>';
const STACK = /Unexpected Application Error|TypeError|reading 'items'|\.js:\d+:\d+|at [A-Za-z$_]+ \(/;

function synthetic(url) {
  const p = url.pathname;
  if (p === '/api/v1/job-roles') return { items: roles, next_cursor: null };
  if (p === '/api/v1/job-postings') return { items: postings, next_cursor: null };
  if (p === '/api/v1/companies') return { items: [company], next_cursor: null };
  if (p.startsWith('/api/v1/job-roles/')) return roles.find((r) => p.endsWith(r.job_role_id));
  if (p.startsWith('/api/v1/job-postings/')) return postings.find((x) => p.endsWith(x.job_posting_id));
  if (p.startsWith('/api/v1/companies/')) return { ...company, description: '합성 기업 설명', website_url: null, open_posting_count: 1, source: 'synthetic_seed' };
  throw new Error(`Unexpected synthetic API route: ${p}`);
}

async function scenario(browser, engine, kind, name, inject, check) {
  const k = KINDS[kind];
  const row = { engine, version: browser.version(), kind, scenario: name, externalRequests: [], pageErrors: [], injected: 0 };
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'ko-KR' });
  const page = await context.newPage();
  page.on('pageerror', (e) => row.pageErrors.push(e.message));
  const state = { inject };
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(base).origin) { row.externalRequests.push(url.origin); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname === '/api/v1/auth/refresh') return route.fulfill({ status: 401, json: { code: 'UNAUTHENTICATED', status: 401, message: '로그인이 필요합니다.' } });
    const injected = state.inject?.(url);
    if (injected) {
      row.injected += 1;
      if (injected === 'abort') return route.abort('internetdisconnected');
      return route.fulfill(injected);
    }
    return route.fulfill({ json: synthetic(url), headers: { 'X-Request-ID': 'req-e2e006okcccccccc' } });
  });
  try {
    await page.goto(`${base}${k.path}`);
    await check(page, k, state, row);
    assert.deepEqual(row.externalRequests, []);
    if (process.env.E2E_SHOTS) {
      mkdirSync(process.env.E2E_SHOTS, { recursive: true });
      await page.screenshot({ path: join(process.env.E2E_SHOTS, `${engine}-${kind}-${name}.png`), fullPage: true });
    }
    row.status = 'PASS';
  } catch (error) {
    row.status = 'FAIL'; row.error = error.message.split('\n')[0];
  } finally {
    out.push(row);
    await context.close();
  }
}

const cards = (page, k) => page.locator(`ul[aria-label="${k.list}"] > li`);
const alertWith = (page, text) => page.getByRole('alert').filter({ hasText: text });
async function noStackAndLayout(page, row) {
  const body = await page.evaluate(() => document.body.innerText);
  row.stackVisible = STACK.test(body);
  assert.equal(row.stackVisible, false, 'stack trace / router default error visible');
  assert.equal(await page.getByRole('navigation', { name: '주 메뉴' }).count(), 1, 'app layout must remain');
}
async function retryRestores(page, k, state, row) {
  state.inject = null;
  await alertWith(page, k.error).getByRole('button', { name: '다시 시도' }).click();
  await cards(page, k).first().waitFor({ timeout: 10000 });
  row.restoredCards = await cards(page, k).count();
  assert.equal(await page.getByText('문의용 요청 번호').count(), 0, 'request id line must disappear after recovery');
}
const isList = (k) => (url) => url.pathname === k.api;

for (const engine of (process.env.E2E_ENGINES || 'chromium').split(',')) {
  const browser = await engines[engine].launch({ headless: true });
  try {
    for (const kind of Object.keys(KINDS)) {
      const k = KINDS[kind];
      await scenario(browser, engine, kind, 'normal', null, async (page, kk, state, row) => {
        await cards(page, kk).first().waitFor({ timeout: 10000 });
        row.cards = await cards(page, kk).count();
        assert.equal(await page.getByRole('alert').count(), 0);
        assert.deepEqual(row.pageErrors, []);
      });
      await scenario(browser, engine, kind, 'html-200', (url) => isList(k)(url) && { status: 200, contentType: 'text/html', body: HTML_SHELL },
        async (page, kk, state, row) => {
          await alertWith(page, kk.error).waitFor({ timeout: 10000 });
          await noStackAndLayout(page, row);
          row.requestIdShown = await page.getByText('문의용 요청 번호').count();
          assert.equal(row.requestIdShown, 0, 'HTML fallback has no X-Request-ID, so nothing is shown');
          await retryRestores(page, kk, state, row);
        });
      await scenario(browser, engine, kind, 'network-failure', (url) => isList(k)(url) && 'abort', async (page, kk, state, row) => {
        await alertWith(page, kk.error).waitFor({ timeout: 10000 });
        await noStackAndLayout(page, row);
        assert.equal(await page.getByText('문의용 요청 번호').count(), 0, 'no response, no request id');
        await retryRestores(page, kk, state, row);
      });
      await scenario(browser, engine, kind, 'http-500-request-id', (url) => isList(k)(url) && {
        status: 500, contentType: 'application/json', headers: { 'X-Request-ID': RID_500 },
        body: JSON.stringify({ code: 'INTERNAL_ERROR', status: 500, message: '일시적인 오류가 발생했습니다.' }),
      }, async (page, kk, state, row) => {
        const panel = alertWith(page, kk.error);
        await panel.waitFor({ timeout: 10000 });
        row.requestIdText = (await panel.locator('.state-panel-request-id').textContent())?.trim();
        assert.equal(row.requestIdText, `문의용 요청 번호: ${RID_500}`);
        assert.equal(await panel.locator('code', { hasText: RID_500 }).count(), 1);
        await noStackAndLayout(page, row);
        await retryRestores(page, kk, state, row);
      });
      await scenario(browser, engine, kind, 'detail-404-request-id', (url) => url.pathname.startsWith(`${k.api}/`) && {
        status: 404, contentType: 'application/json', headers: { 'X-Request-ID': RID_404 },
        body: JSON.stringify({ code: 'NOT_FOUND', status: 404, message: '요청한 정보를 찾을 수 없습니다.' }),
      }, async (page, kk, state, row) => {
        await page.getByText(kk.title, { exact: true }).first().click();
        const panel = alertWith(page, '상세 정보를 불러오지 못했습니다');
        await panel.waitFor({ timeout: 10000 });
        assert.equal(await panel.locator('code', { hasText: RID_404 }).count(), 1);
        state.inject = null;
        await panel.getByRole('button', { name: '다시 시도' }).click();
        await page.getByText(kind === 'roles' ? '합성 직무 설명 0' : '합성 공고 설명 0', { exact: true }).waitFor({ timeout: 10000 });
        row.detailRecovered = true;
      });
      // Valid JSON of the wrong shape makes the page throw while rendering: the route boundary must catch it.
      await scenario(browser, engine, kind, 'render-crash-boundary', (url) => isList(k)(url) && { status: 200, contentType: 'application/json', body: '{}' },
        async (page, kk, state, row) => {
          await page.getByText('화면을 표시하지 못했습니다', { exact: true }).waitFor({ timeout: 10000 });
          await noStackAndLayout(page, row);
          row.homeLink = await page.getByRole('link', { name: '홈으로 이동' }).count();
          assert.equal(row.homeLink, 1);
          state.inject = null;
          await page.getByRole('button', { name: '다시 시도' }).click();   // reloads the page
          await cards(page, kk).first().waitFor({ timeout: 10000 });
          row.restoredCards = await cards(page, kk).count();
        });
    }
  } finally {
    await browser.close();
  }
}
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, JSON.stringify(out, null, 2));
console.log(JSON.stringify({ passed: out.filter((r) => r.status === 'PASS').length, failed: out.filter((r) => r.status === 'FAIL').length, scenarios: out.map((r) => ({ engine: r.engine, kind: r.kind, scenario: r.scenario, status: r.status, error: r.error })) }, null, 2));
if (out.some((r) => r.status !== 'PASS')) process.exitCode = 1;
