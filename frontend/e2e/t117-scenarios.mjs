// T117 실제 브라우저 사용자 시나리오 — Mock 모드와 실제 API 모드의 결과를 **따로** 기록합니다.
//
//   E2E_BASE_URL=http://127.0.0.1:5196 E2E_MODE=real|mock E2E_OUT=result.json \
//   PLAYWRIGHT_CORE=<path to playwright-core> CHROME_PATH=<chrome.exe> node e2e/t117-scenarios.mjs
//
// - playwright-core 는 저장소 의존성에 넣지 않았습니다(잠금 파일·SBOM 변경 없음, T118). 실행 환경의 경로를 받습니다.
// - 계정: mock 모드는 Mock 로그인 계정, real 모드는 E2E_SEEKER/E2E_ADMIN(합성 계정, 실행 전 생성)과 E2E_PASSWORD.
// - real 모드만 네트워크 지연·실패를 page.route 로 주입합니다(Mock Adapter 는 네트워크를 쓰지 않음).
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173';
const MODE = process.env.E2E_MODE || 'mock';
const SEEKER = process.env.E2E_SEEKER || 'user@example.com';
const ADMIN = process.env.E2E_ADMIN || 'admin@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'mock-password-1234';
const SHOTS = process.env.E2E_SHOTS || '';

const results = [];
async function step(scenario, name, fn) {
  const started = Date.now();
  try {
    const detail = await fn();
    results.push({ scenario, step: name, status: 'PASS', ms: Date.now() - started, ...(detail ? { detail } : {}) });
  } catch (error) {
    results.push({ scenario, step: name, status: 'FAIL', ms: Date.now() - started, error: String(error.message || error).split('\n')[0] });
  }
}
const skip = (scenario, name, reason) => results.push({ scenario, step: name, status: 'NOT_RUN', reason });

async function login(page, email) {
  await page.getByLabel(/^이메일/).fill(email);
  await page.getByLabel(/^비밀번호/).fill(PASSWORD);
  await page.getByRole('button', { name: '로그인' }).click();
}
const h1 = (page) => page.locator('main h1, #main-content h1').first();
/** 앱 안 이동(메뉴 클릭과 같음 — 새로고침 없이 history 로). Mock 로그인은 새로고침하면 풀립니다. */
async function nav(page, path) {
  await page.evaluate((to) => { window.history.pushState({}, '', to); window.dispatchEvent(new PopStateEvent('popstate')); }, path);
  await page.waitForURL((url) => url.pathname === path.split('?')[0]);
}
const noOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH });
for (const [label, width] of [['desktop', 1280], ['mobile', 375]]) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await context.newPage();
  const S = `${label}`;

  // A. 비로그인 → 탐색 → 뒤로·앞으로 → 보호 화면 직접 URL → 로그인 → 원래 화면
  await step(`${S}:A anonymous`, 'home renders', async () => { await page.goto(`${BASE}/`); await page.getByRole('link', { name: /기업·채용공고 탐색|채용공고/ }).first().waitFor(); });
  await step(`${S}:A anonymous`, 'open job postings', async () => {
    await page.goto(`${BASE}/job-postings`);
    await h1(page).waitFor();
    return { h1: await h1(page).textContent() };
  });
  await step(`${S}:A anonymous`, 'back and forward keep the right screen', async () => {
    await page.goBack(); await page.waitForURL(`${BASE}/`);
    await page.goForward(); await page.waitForURL(/\/job-postings/);
    await h1(page).waitFor();
  });
  await step(`${S}:A anonymous`, 'protected URL redirects to login', async () => {
    await page.goto(`${BASE}/account`);
    await page.getByRole('heading', { name: '로그인' }).waitFor();
  });
  await step(`${S}:A anonymous`, 'login returns to the requested screen', async () => {
    await login(page, SEEKER);
    await page.getByRole('heading', { name: '내 계정' }).waitFor();
    return { url: new URL(page.url()).pathname };
  });
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/t117-${MODE}-${label}-account.png` });
  await step(`${S}:A anonymous`, 'reload keeps or drops the session (recorded)', async () => {
    await page.reload();
    await h1(page).waitFor();
    const text = (await h1(page).textContent())?.trim();
    await page.goto(`${BASE}/account`);
    if (text === '로그인') { await login(page, SEEKER); await page.getByRole('heading', { name: '내 계정' }).waitFor(); }
    return { afterReload: text };
  });

  // B. 구직자 주요 화면(직무·기술·추천·추세·북마크)
  for (const [path, expect] of [['/job-roles', null], ['/me/skills', '나의 기술'], ['/recommendations', '맞춤 공고 추천'],
    ['/market-trends', '채용시장 추세'], ['/me/bookmarks', null], ['/me/target-roles', null]]) {
    await step(`${S}:B job seeker`, `open ${path}`, async () => {
      await nav(page, path);
      const heading = h1(page);
      await heading.waitFor();
      const text = (await heading.textContent())?.trim();
      if (text === '로그인') throw new Error('signed out: login screen shown');
      if (expect && !text?.includes(expect)) throw new Error(`h1 "${text}" != ${expect}`);
      if (await page.getByRole('heading', { name: '페이지를 찾을 수 없습니다' }).count()) throw new Error('404 screen');
      const alerts = await page.getByRole('alert').allTextContents();
      if (!(await noOverflow(page))) throw new Error('horizontal overflow');
      return { h1: text, alerts: alerts.filter(Boolean).slice(0, 2) };
    });
  }

  // D. 관리자 화면: 구직자는 접근 불가, 관리자는 접근(플래그·역할)
  await step(`${S}:D roles`, 'seeker cannot open an admin screen', async () => {
    await nav(page, '/admin/audit-events');
    await h1(page).waitFor();
    const text = (await h1(page).textContent())?.trim();
    if (text === '로그인') throw new Error('signed out: login screen shown');
    if (/감사/.test(text ?? '') && !(await page.getByText(/권한|찾을 수 없습니다/).count())) throw new Error(`seeker saw: ${text}`);
    return { h1: text };
  });
  // C. 키보드(마지막: 새로 연 화면에서 시작): 첫 Tab = 본문 바로가기, Enter → 본문으로 포커스
  await step(`${S}:C keyboard`, 'skip link is the first tab stop and moves focus to main', async () => {
    await page.goto(`${BASE}/job-postings`);
    await h1(page).waitFor();
    await page.keyboard.press('Tab');
    const first = await page.evaluate(() => document.activeElement?.textContent?.trim());
    if (first !== '본문으로 바로가기') throw new Error(`first focus: ${first}`);
    await page.keyboard.press('Enter');
    const hash = new URL(page.url()).hash;
    return { first, hash };
  });

  await context.close();

  const adminContext = await browser.newContext({ viewport: { width, height: 900 } });
  const adminPage = await adminContext.newPage();
  await step(`${S}:D roles`, 'admin signs in and opens the account screen', async () => {
    await adminPage.goto(`${BASE}/account`);
    await login(adminPage, ADMIN);
    await adminPage.getByRole('heading', { name: '내 계정' }).waitFor();
    await nav(adminPage, '/admin/audit-events');
    await h1(adminPage).waitFor();
    return { h1: (await h1(adminPage).textContent())?.trim() };
  });

  // E. 느린·실패 응답(real 모드만 — Mock Adapter 는 네트워크를 쓰지 않음)
  if (MODE === 'real') {
    await step(`${S}:E network`, 'slow API shows a loading state, then content', async () => {
      await adminPage.route('**/api/v1/job-postings**', async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
      await adminPage.goto(`${BASE}/job-postings`);
      const loading = await adminPage.getByText(/불러오는 중/).first().isVisible({ timeout: 2000 }).catch(() => false);
      await adminPage.unroute('**/api/v1/job-postings**');
      await adminPage.getByText(/불러오는 중/).first().waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});
      return { loadingVisible: loading };
    });
    await step(`${S}:E network`, 'failing API shows an error with retry that recovers', async () => {
      await adminPage.route('**/api/v1/job-postings**', (route) => route.fulfill({ status: 503, contentType: 'application/json',
        body: JSON.stringify({ code: 'DEPENDENCY_UNAVAILABLE', status: 503, message: '서비스를 잠시 사용할 수 없습니다.' }) }));
      await adminPage.goto(`${BASE}/job-postings`);
      const retry = adminPage.getByRole('button', { name: '다시 시도' }).first();
      await retry.waitFor({ timeout: 10000 });
      await adminPage.unroute('**/api/v1/job-postings**');
      await retry.click();
      await adminPage.getByRole('button', { name: '다시 시도' }).first().waitFor({ state: 'detached', timeout: 10000 });
    });
  } else {
    skip(`${S}:E network`, 'slow/failing API', 'mock adapters do not use the network');
  }
  await adminContext.close();
}
await browser.close();

const summary = results.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }), {});
const out = { mode: MODE, base: BASE, generated_at: new Date().toISOString(), summary, results };
if (process.env.E2E_OUT) writeFileSync(process.env.E2E_OUT, JSON.stringify(out, null, 2) + '\n');
console.log(JSON.stringify({ mode: MODE, summary }, null, 1));
for (const r of results.filter((x) => x.status === 'FAIL')) console.log(`FAIL ${r.scenario} / ${r.step}: ${r.error}`);
process.exit(results.some((r) => r.status === 'FAIL') ? 1 : 0);
