// T146 실제 브라우저 점검 — 좁은 화면(320px)·넓은 화면(1280px), 긴 문자열, 키보드 이동, 브라우저 시간대.
//
//   E2E_BASE_URL=http://127.0.0.1:5202 E2E_OUT=result.json E2E_SHOTS=<dir> \
//   PLAYWRIGHT_CORE=<path to playwright-core> CHROME_PATH=<chrome.exe> node e2e/t146-i18n-a11y.mjs
//
// - Mock 모드(`npm run dev:mock`) 전용입니다. 실제 API 결과가 아닙니다.
// - 브라우저 시간대를 한국이 아닌 곳(America/Los_Angeles)으로 바꿔도 화면 날짜가 한국 날짜인지 봅니다.
// - playwright-core 는 저장소 의존성에 넣지 않습니다(T118 잠금 파일·SBOM 변경 없음).
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173';
const SHOTS = process.env.E2E_SHOTS || '';
const PASSWORD = process.env.E2E_PASSWORD || 'mock-password-1234';
const LONG = '가나다라마바사아자차카타파하'.repeat(10) + 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.repeat(4);

const results = [];
async function step(scenario, name, fn) {
  try {
    const detail = await fn();
    results.push({ scenario, step: name, status: 'PASS', ...(detail ? { detail } : {}) });
  } catch (error) {
    results.push({ scenario, step: name, status: 'FAIL', error: String(error.message || error).split('\n')[0] });
  }
}
async function nav(page, path) {
  await page.evaluate((to) => { window.history.pushState({}, '', to); window.dispatchEvent(new PopStateEvent('popstate')); }, path);
  await page.waitForURL((url) => url.pathname === path);
  await page.locator('main h1').first().waitFor();
}
async function noOverflow(page) {
  const sizes = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  if (sizes.scroll > sizes.inner) throw new Error(`horizontal overflow ${sizes.scroll} > ${sizes.inner}`);
  return sizes;
}
/** 화면의 모든 <time datetime="…T…"> 글자가 그 시각의 한국 날짜를 담는지. */
async function timesAreKst(page) {
  return page.evaluate(() => {
    const fmt = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' });
    const rows = [...document.querySelectorAll('time[datetime*="T"]')].map((el) => ({
      iso: el.getAttribute('datetime'), text: el.textContent.trim(), expected: fmt.format(new Date(el.getAttribute('datetime'))),
    }));
    const bad = rows.filter((r) => !r.text.startsWith(r.expected));
    if (bad.length) throw new Error(`non-KST date: ${JSON.stringify(bad[0])}`);
    if (!rows.length) throw new Error('no <time> element to check (0 checks is not a PASS)');
    return { checked: rows.length, browserZone: Intl.DateTimeFormat().resolvedOptions().timeZone };
  });
}

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH });
for (const [label, width] of [['w320', 320], ['w1280', 1280]]) {
  const context = await browser.newContext({ viewport: { width, height: 800 }, timezoneId: 'America/Los_Angeles', locale: 'en-US' });
  const page = await context.newPage();

  await step(label, 'html lang is ko', async () => {
    await page.goto(`${BASE}/`);
    const lang = await page.evaluate(() => document.documentElement.lang);
    if (lang !== 'ko') throw new Error(`lang=${lang}`);
  });
  await step(label, 'first Tab focuses a visible skip link; Enter moves focus to main', async () => {
    await page.goto(`${BASE}/job-postings`);
    await page.locator('main h1').first().waitFor();
    await page.keyboard.press('Tab');
    const first = await page.evaluate(() => {
      const el = document.activeElement; const r = el.getBoundingClientRect();
      return { cls: el.className, text: el.textContent.trim(), visible: r.width > 0 && r.top >= 0 && r.top < window.innerHeight };
    });
    if (!first.cls.includes('skip-link') || !first.visible) throw new Error(JSON.stringify(first));
    await page.keyboard.press('Enter');
    const focused = await page.evaluate(() => document.activeElement?.id);
    if (focused !== 'main-content') throw new Error(`focus after Enter on ${focused}`);
    return first;
  });
  for (const path of ['/', '/job-postings', '/login']) {
    await step(label, `no horizontal overflow ${path}`, async () => { await page.goto(`${BASE}${path}`); await page.locator('main h1').first().waitFor(); return noOverflow(page); });
  }
  await step(label, 'login with keyboard only', async () => {
    await page.goto(`${BASE}/login`);
    await page.getByLabel(/^이메일/).focus();
    await page.keyboard.type('user@example.com');
    await page.keyboard.press('Tab');
    await page.keyboard.type(PASSWORD);
    await page.keyboard.press('Enter');
    await page.getByRole('heading', { name: '내 계정' }).waitFor();
  });
  for (const path of ['/account', '/account/privacy', '/me/skills', '/me/notifications', '/me/applications']) {
    await step(label, `no horizontal overflow ${path}`, async () => { await nav(page, path); return noOverflow(page); });
  }
  await step(label, 'privacy dates are KST while the browser is in Los Angeles', async () => {
    await nav(page, '/account/privacy');
    const toggle = page.getByRole('button', { name: /^(동의|철회)$/ }).first();
    await toggle.click();
    await page.getByRole('dialog').getByRole('button').filter({ hasText: /동의|철회|확인/ }).last().click();
    await page.locator('time[datetime]').first().waitFor();
    return timesAreKst(page);
  });
  await step(label, 'recommendation run time is KST', async () => {
    await nav(page, '/recommendations');
    await page.locator('time[datetime]').first().waitFor();
    return timesAreKst(page);
  });
  await step(label, 'long unbroken document name wraps (no overflow) and date is KST', async () => {
    await nav(page, '/me/documents');
    await page.locator('input[type=file]').setInputFiles({ name: `${LONG}.pdf`, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic') });
    await page.getByRole('button', { name: /업로드/ }).first().click();
    await page.locator('article h3', { hasText: LONG.slice(0, 20) }).first().waitFor();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/t146-${label}-documents.png`, fullPage: true });
    return { ...(await noOverflow(page)), ...(await timesAreKst(page)) };
  });
  await step(label, 'zoom 200% equivalent (half width) keeps privacy page usable', async () => {
    await page.setViewportSize({ width: Math.max(320, Math.round(width / 2)), height: 800 });
    await nav(page, '/account/privacy');
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/t146-${label}-privacy-half.png`, fullPage: true });
    return noOverflow(page);
  });
  await context.close();
}
await browser.close();
const summary = { pass: results.filter((r) => r.status === 'PASS').length, fail: results.filter((r) => r.status === 'FAIL').length };
const out = { tool: 't146-i18n-a11y', mode: 'mock', base: BASE, browser: 'chrome (playwright-core)', browserTimezone: 'America/Los_Angeles', summary, results };
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, `${JSON.stringify(out, null, 2)}\n`);
console.log(JSON.stringify(summary));
for (const r of results.filter((x) => x.status === 'FAIL')) console.log('FAIL', r.scenario, r.step, r.error);
process.exitCode = summary.fail ? 1 : 0;
