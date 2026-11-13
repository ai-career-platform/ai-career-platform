// Local rendered-DOM regression with synthetic API responses; never probes Staging.
// Start VITE_API_MOCK=false npm run dev -- --port 5215, then:
// PLAYWRIGHT_CORE=<playwright path> AXE_CORE=<axe.min.js path> node e2e/e2e005-cards-a11y.mjs
// E2E_ENGINES=chromium,firefox,webkit (default chromium), E2E_OUT=<JSON>, E2E_SHOTS=<directory>.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const engines = require(process.env.PLAYWRIGHT_CORE || 'playwright');
const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5215';
assert.equal(new URL(base).hostname, '127.0.0.1', 'This synthetic regression is local-only');
const axe = readFileSync(process.env.AXE_CORE, 'utf8');
const out = [];
const roleId = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const postingId = ['33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444'];
const company = { company_id: '55555555-5555-4555-8555-555555555555', name: '합성 기업' };
const roles = roleId.map((id, i) => ({ job_role_id: id, code: i ? 'BE' : 'DBA', name: i ? '백엔드 개발자' : '데이터베이스 관리자', description: `합성 직무 설명 ${i}`, required_skills: [] }));
const postings = postingId.map((id, i) => ({ job_posting_id: id, title: `합성 공고 ${i + 1}`, company, job_role: roles[i], status: 'published', location_text: '서울', employment_type: 'full_time', published_at: '2026-10-01T00:00:00Z', expires_at: i ? null : '2026-12-31T00:00:00Z', description: `합성 공고 설명 ${i}`, source_url: null, is_bookmarked: null, required_skills: [] }));

async function tabTo(page, target) {
  for (let i = 0; i < 60; i += 1) {
    await page.keyboard.press('Tab');
    if (await target.evaluate(el => document.activeElement === el)) return;
  }
  assert.fail('Card is unreachable with Tab');
}
async function scan(page, phase, row) {
  const result = await page.evaluate(async () => {
    const report = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } });
    return { violations: report.violations.map(v => ({ id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target) })), labelPassNodes: report.passes.find(v => v.id === 'label-content-name-mismatch')?.nodes.length || 0 };
  });
  row.scans.push({ phase, ...result });
  assert.deepEqual(result.violations, [], `${phase}: axe violations`);
  assert.ok(result.labelPassNodes >= 2, 'Label rule must actually pass on both rendered cards');
}

for (const engine of (process.env.E2E_ENGINES || 'chromium').split(',')) {
  const browser = await engines[engine].launch({ headless: true });
  try {
    for (const width of [320, 1366]) {
      for (const kind of ['roles', 'postings']) {
        const context = await browser.newContext({ viewport: { width, height: 844 }, locale: 'ko-KR' });
        const page = await context.newPage();
        const row = { engine, version: browser.version(), width, kind, scans: [], externalRequests: [], pageErrors: [] };
        page.on('pageerror', error => row.pageErrors.push(error.message));
        await page.route('**/*', async route => {
          const url = new URL(route.request().url());
          if (url.origin !== new URL(base).origin) {
            row.externalRequests.push(url.origin);
            return route.abort();
          }
          if (!url.pathname.startsWith('/api/')) return route.continue();
          let data;
          if (url.pathname === '/api/v1/auth/refresh') return route.fulfill({ status: 401, json: { code: 'UNAUTHENTICATED', status: 401 } });
          if (url.pathname === '/api/v1/job-roles') data = { items: roles, next_cursor: null };
          else if (url.pathname === '/api/v1/job-postings') data = { items: postings, next_cursor: null };
          else if (url.pathname === '/api/v1/companies') data = { items: [company], next_cursor: null };
          else if (url.pathname.startsWith('/api/v1/job-roles/')) data = roles.find(r => url.pathname.endsWith(r.job_role_id));
          else if (url.pathname.startsWith('/api/v1/job-postings/')) data = postings.find(p => url.pathname.endsWith(p.job_posting_id));
          else if (url.pathname.startsWith('/api/v1/companies/')) data = { ...company, description: '합성 기업 설명', website_url: null, open_posting_count: 1, source: 'synthetic_seed' };
          else throw new Error(`Unexpected synthetic API route: ${url.pathname}`);
          assert.ok(data, `Missing fixture for ${url.pathname}`);
          return route.fulfill({ json: data });
        });
        try {
          await page.goto(`${base}/job-${kind}`);
          const list = page.getByRole('list', { name: kind === 'roles' ? '직무 검색 결과' : '채용공고 검색 결과' });
          const cards = list.getByRole('button');
          await cards.nth(1).waitFor();
          await page.evaluate(axe);
          await scan(page, 'list', row);
          const names = kind === 'roles'
            ? ['DBA 데이터베이스 관리자', 'BE 백엔드 개발자']
            : ['합성 공고 1 합성 기업 · 데이터베이스 관리자', '합성 공고 2 합성 기업 · 백엔드 개발자'];
          for (let i = 0; i < 2; i += 1) {
            assert.equal(await list.getByRole('button', { name: names[i], exact: true }).count(), 1);
          }
          row.accessibility = await cards.evaluateAll(buttons => buttons.map(button => ({
            labelText: button.getAttribute('aria-labelledby').split(' ').map(id => document.getElementById(id)?.textContent).join(' '),
            descriptionText: button.getAttribute('aria-describedby').split(' ').map(id => document.getElementById(id)?.textContent).join(' '),
          })));
          await tabTo(page, cards.nth(0));
          row.focusVisible = await cards.nth(0).evaluate(el => {
            const style = getComputedStyle(el.closest('li'));
            return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
          });
          assert.ok(row.focusVisible);
          await page.keyboard.press('Enter');
          await page.getByText(kind === 'roles' ? '합성 직무 설명 0' : '합성 공고 설명 0', { exact: true }).waitFor();
          assert.equal(await cards.nth(0).getAttribute('aria-pressed'), 'true');
          await page.keyboard.press('Tab');
          assert.ok(await cards.nth(1).evaluate(el => document.activeElement === el));
          await page.keyboard.press('Space');
          await page.getByText(kind === 'roles' ? '합성 직무 설명 1' : '합성 공고 설명 1', { exact: true }).waitFor();
          assert.equal(await cards.nth(1).getAttribute('aria-pressed'), 'true');
          await page.keyboard.press('Shift+Tab');
          assert.ok(await cards.nth(0).evaluate(el => document.activeElement === el));
          // Click auxiliary text, outside the button DOM but inside its stretched hit area.
          const description = list.locator(kind === 'roles' ? '.role-explorer-description' : '.t24-posting-meta').first();
          await description.scrollIntoViewIfNeeded();
          const box = await description.boundingBox();
          await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
          await page.getByText(kind === 'roles' ? '합성 직무 설명 0' : '합성 공고 설명 0', { exact: true }).waitFor();
          assert.equal(await cards.nth(0).getAttribute('aria-pressed'), 'true');
          await scan(page, 'selected detail', row);
          row.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
          assert.equal(row.overflow, false);
          assert.deepEqual(row.externalRequests, []);
          assert.deepEqual(row.pageErrors, []);
          if (process.env.E2E_SHOTS) {
            mkdirSync(process.env.E2E_SHOTS, { recursive: true });
            await page.screenshot({ path: join(process.env.E2E_SHOTS, `${engine}-${width}-${kind}.png`), fullPage: true });
          }
          row.status = 'PASS';
        } catch (error) {
          row.status = 'FAIL';
          row.error = error.message;
        } finally {
          out.push(row);
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
  }
}
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, JSON.stringify(out, null, 2));
console.log(JSON.stringify({ passed: out.filter(r => r.status === 'PASS').length, failed: out.filter(r => r.status === 'FAIL').length, scenarios: out }, null, 2));
if (out.some(r => r.status !== 'PASS')) process.exitCode = 1;
