// T89 실제 브라우저(Chrome·Edge) 접근성·반응형 점검 — 수동 실행용(CI 아님, 새 의존성 없음).
//
//   1) npm run dev:mock  (또는 VITE_API_MOCK=true npx vite --port 5189)
//   2) PLAYWRIGHT_CORE=<playwright-core 설치 경로> BASE_URL=http://127.0.0.1:5189 \
//        CHROME=<chrome.exe> EDGE=<msedge.exe> node scripts/a11y-browser-check.mjs > result.json
//
// Mock 모드의 합성 계정만 씁니다. 실제 사용자·비밀정보 없음.
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE);
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5189';
const BROWSERS = [['chrome', process.env.CHROME], ['edge', process.env.EDGE]].filter(([, path]) => path);
const VIEWPORTS = [
  ['desktop-1280', { width: 1280, height: 800 }, 1],
  ['mobile-375', { width: 375, height: 800 }, 1],
  ['zoom-200%', { width: 640, height: 400 }, 2],   // 1280 화면을 200% 확대한 것과 같은 CSS 폭
];
const PUBLIC = ['/', '/login', '/job-postings', '/job-roles'];
const PRIVATE = ['/me/skills', '/recommendations', '/account/privacy'];

async function tabUntil(page, predicate, max = 40) {
  for (let i = 0; i < max; i += 1) {
    await page.keyboard.press('Tab');
    if (await page.evaluate(predicate)) return i + 1;
  }
  return null;
}

async function checkPage(page, path) {
  await page.goto(BASE + path);
  await page.locator('h1').first().waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  // 새로 연 페이지에서 바로 Tab: 문서 처음부터의 순서 (클릭하면 시작점이 바뀜)
  await page.keyboard.press('Tab');
  const skip = await page.evaluate(() => {
    const el = document.activeElement;
    const box = el?.getBoundingClientRect();
    return { isSkip: el?.classList.contains('skip-link') ?? false, visible: !!box && box.width > 0 && box.height > 0 && box.top >= 0 };
  });
  await page.keyboard.press('Enter');
  const mainFocused = await page.evaluate(() => document.activeElement?.id === 'main-content');
  await page.keyboard.press('Tab');
  const focusRing = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body) return { tag: null, visible: false };
    const s = getComputedStyle(el);
    return { tag: el.tagName, visible: (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none' };
  });
  return { path, overflow, skipLinkFirst: skip.isSkip, skipLinkVisible: skip.visible, skipMovesFocusToMain: mainFocused,
    focusAfterSkip: focusRing.tag, focusIndicatorVisible: focusRing.visible };
}

async function keyboardLogin(page) {
  await page.goto(BASE + '/login');
  await page.locator('h1').first().waitFor();
  const toEmail = await tabUntil(page, () => document.activeElement?.getAttribute('type') === 'email'
    || (document.activeElement?.labels?.[0]?.textContent ?? '').startsWith('이메일'));
  await page.keyboard.type('user@example.com');
  await page.keyboard.press('Tab');
  await page.keyboard.type('mock-password-1234');
  await page.keyboard.press('Enter');
  await page.getByRole('link', { name: '일반 사용자' }).waitFor({ timeout: 5000 });
  return { tabsToEmail: toEmail, loggedIn: true };
}

const results = [];
for (const [name, executablePath] of BROWSERS) {
  const browser = await chromium.launch({ executablePath });
  for (const [label, viewport, deviceScaleFactor] of VIEWPORTS) {
    const context = await browser.newContext({ viewport, deviceScaleFactor });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    const pages = [];
    for (const path of PUBLIC) pages.push(await checkPage(page, path));
    const login = await keyboardLogin(page);
    for (const path of PRIVATE) pages.push(await checkPage(page, path));
    results.push({ browser: name, version: browser.version(), viewport: label, login, pages, pageErrors: errors });
    await context.close();
  }
  await browser.close();
}
console.log(JSON.stringify(results, null, 2));
