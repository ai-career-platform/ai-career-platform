// Full-system E2E — 실제 React 빌드 + 실제 FastAPI + 실제 PostgreSQL, Playwright Chromium.
// tests/e2e_full/run_full_e2e.py 가 DB·API·웹을 띄운 뒤 이 스크립트를 부릅니다(단독 실행용이 아님).
//
// 입력 env: E2E_BASE_URL, E2E_ACCOUNTS(JSON), E2E_PASSWORD, E2E_STATE(harness 상태 JSON), E2E_OUT, E2E_ARTIFACTS,
//           E2E_PYTHON·E2E_BACKEND_DIR·E2E_HELPERS(worker·fixture 1회 실행), PLAYWRIGHT_CORE(선택), CHROME_PATH(선택).
// 합성 계정·합성 데이터만 씁니다. 실패한 단계는 스크린샷, 컨텍스트마다 trace·console 오류·네트워크(method/URL/status)를 남깁니다.
// 단계 결과: PASS(실제 증거) / FAIL / NOT_RUN(화면이 없음 등, 사유 기록) / BLOCKED(미병합 정책 의존).
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync, appendFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const BASE = process.env.E2E_BASE_URL;
const ACC = JSON.parse(process.env.E2E_ACCOUNTS);
const PASSWORD = process.env.E2E_PASSWORD;
const STATE = JSON.parse(readFileSync(process.env.E2E_STATE, 'utf8'));
const ART = process.env.E2E_ARTIFACTS;
mkdirSync(ART, { recursive: true });
const NET = path.join(ART, 'network.jsonl');
const CONSOLE = path.join(ART, 'console-errors.jsonl');
writeFileSync(NET, ''); writeFileSync(CONSOLE, '');

const results = [];
const out = {};   // 다른 단계·harness 가 쓰는 값(링크 URL, id)
let current = { ctx: null, page: null };

async function step(area, scenario, name, fn) {
  const started = Date.now();
  try {
    const evidence = await fn();
    results.push({ area, scenario, step: name, status: 'PASS', ms: Date.now() - started, source: 'browser', ...(evidence !== undefined ? { evidence } : {}) });
    console.log(`[PASS] ${area} / ${scenario} / ${name}`);
    return true;
  } catch (error) {
    const msg = String(error?.message || error).split('\n').slice(0, 3).join(' | ');
    const shot = `${area}-${scenario}-${name}`.replace(/[^A-Za-z0-9가-힣_-]+/g, '_').slice(0, 90) + '.png';
    let screenshot = null;
    if (current.page) {
      try { await current.page.screenshot({ path: path.join(ART, shot), fullPage: true }); screenshot = shot; } catch { /* ignore */ }
    }
    results.push({ area, scenario, step: name, status: 'FAIL', ms: Date.now() - started, source: 'browser', error: msg, screenshot, url: current.page?.url() });
    console.log(`[FAIL] ${area} / ${scenario} / ${name}: ${msg}`);
    return false;
  }
}
const mark = (area, scenario, name, status, reason) => {
  results.push({ area, scenario, step: name, status, source: 'browser', reason });
  console.log(`[${status}] ${area} / ${scenario} / ${name}: ${reason}`);
};

function py(args) {
  return execFileSync(process.env.E2E_PYTHON, args, { cwd: process.env.E2E_BACKEND_DIR, env: process.env, encoding: 'utf8', timeout: 300000 });
}
const worker = (module) => py(['-m', module]).trim();

/** 화면이 없는 운영 절차(조직 승인 등)는 같은 Origin 의 실제 API 로 한다 — 결과에 'api' 로 표시 */
async function api(email, method, url, body) {
  const auth = await fetch(`${BASE}/api/v1/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': '1' }, body: JSON.stringify({ email, password: PASSWORD }) });
  if (auth.status !== 200) throw new Error(`api login ${email} -> ${auth.status}`);
  const { access_token } = await auth.json();
  const r = await fetch(`${BASE}${url}`, { method, headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json', 'X-CSRF-TOKEN': '1' }, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let json = null; try { json = JSON.parse(text); } catch { /* not json */ }
  return { status: r.status, json, text };
}

async function newContext(label) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  await ctx.tracing.start({ screenshots: true, snapshots: true, title: label });
  const page = await ctx.newPage();
  page.on('response', (res) => {
    const u = new URL(res.url());
    if (u.pathname.startsWith('/api/')) appendFileSync(NET, JSON.stringify({ ctx: label, method: res.request().method(), url: u.pathname + u.search, status: res.status() }) + '\n');
  });
  page.on('console', (m) => { if (m.type() === 'error') appendFileSync(CONSOLE, JSON.stringify({ ctx: label, text: m.text().slice(0, 500), url: page.url() }) + '\n'); });
  page.on('pageerror', (e) => appendFileSync(CONSOLE, JSON.stringify({ ctx: label, pageerror: String(e).slice(0, 500), url: page.url() }) + '\n'));
  current = { ctx, page };
  return { ctx, page, label };
}
async function closeContext(c) {
  await c.ctx.tracing.stop({ path: path.join(ART, `trace-${c.label}.zip`) });
  await c.ctx.close();
}

const h1 = (page) => page.locator('main h1, #main-content h1').first();
async function expectH1(page, text) {
  await h1(page).waitFor({ timeout: 15000 });
  await page.waitForFunction((t) => [...document.querySelectorAll('main h1, #main-content h1')].some((e) => e.textContent.includes(t)), text, { timeout: 15000 });
}
async function login(page, email) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel(/^이메일/).fill(email);
  await page.getByLabel(/^비밀번호/).fill(PASSWORD);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expectH1(page, '내 계정');
}
const status = (page, re) => page.getByRole('status').filter({ hasText: re }).first().waitFor({ timeout: 15000 });

function pdf() {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>'];
  let s = '%PDF-1.7\n'; const offsets = [0];
  objects.forEach((o, i) => { offsets.push(s.length); s += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const start = s.length;
  s += 'xref\n0 4\n0000000000 65535 f \n' + offsets.slice(1).map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
  s += `trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF`;
  return Buffer.from(s, 'latin1');
}

const launchOptions = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
const browser = await chromium.launch(launchOptions);
const browserInfo = { name: 'chromium', version: browser.version(), executable: process.env.CHROME_PATH || 'playwright-managed' };

// =========================================================================================== A. 구직자
const posting = STATE.browser_posting;
{
  const c = await newContext('seeker');
  const { page } = c;
  await step('USER', 'A-login', 'local test account logs in (email/password) and lands on /account', async () => {
    await login(page, ACC.seeker.email);
    await page.getByText(`${ACC.seeker.name} (${ACC.seeker.email})`).waitFor();
    return { url: new URL(page.url()).pathname };
  });
  await step('USER', 'A-login', 'session survives a full reload (refresh cookie)', async () => {
    await page.reload();
    await expectH1(page, '내 계정');
  });
  await step('USER', 'A-profile', 'profile view shows name/email/role', async () => {
    const text = await page.locator('main').innerText();
    if (!text.includes('역할')) throw new Error('role line missing');
    return { line: text.split('\n').find((l) => l.includes(ACC.seeker.email)) };
  });
  mark('USER', 'A-profile', 'profile edit in UI', 'NOT_RUN', 'no profile edit screen exists in the frontend (PATCH /me is API-only) — defect FSE-002; API edit verified in harness');

  await step('USER', 'A-experience', 'add experience and project, delete project (UI)', async () => {
    await page.goto(`${BASE}/me/career-history`);
    await expectH1(page, '경력·프로젝트');
    await page.getByLabel('유형').selectOption({ label: '경력' });
    await page.getByLabel('회사·기관').fill('E2E UI 회사');
    await page.getByLabel('직무').fill('E2E UI 개발자');
    await page.getByRole('button', { name: '추가', exact: true }).click();
    await page.locator('li', { hasText: '경력 · E2E UI 회사 · E2E UI 개발자' }).waitFor();
    await page.getByLabel('유형').selectOption({ label: '프로젝트' });
    await page.getByLabel('프로젝트명').fill('E2E 삭제할 프로젝트');
    await page.getByLabel('프로젝트 요약').fill('요약');
    await page.getByRole('button', { name: '추가', exact: true }).click();
    const row = page.locator('li', { hasText: '프로젝트 · E2E 삭제할 프로젝트' });
    await row.waitFor();
    await row.getByRole('button', { name: '삭제' }).click();
    await row.waitFor({ state: 'detached' });
    await page.reload();
    await page.locator('li', { hasText: '경력 · E2E UI 회사 · E2E UI 개발자' }).waitFor();
    if (await page.locator('li', { hasText: 'E2E 삭제할 프로젝트' }).count()) throw new Error('deleted project came back after reload');
    return { experience: 'persisted after reload', project: 'deleted' };
  });
  mark('USER', 'A-experience', 'edit experience in UI', 'NOT_RUN', 'career history screen has no edit control (PATCH API exists) — defect FSE-003; API patch verified in harness');

  await step('USER', 'A-skills', 'search skill, add, save, persists after reload, remove', async () => {
    const name = STATE.skill_names[0];
    await page.goto(`${BASE}/me/skills`);
    await expectH1(page, '나의 기술');
    await page.getByLabel('기술 검색').fill(name.slice(0, Math.max(2, Math.min(name.length, 4))));
    await page.getByRole('listbox', { name: '기술 검색 결과' }).getByRole('option', { name }).first().click();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await status(page, /저장했습니다/);
    await page.reload();
    await page.getByRole('button', { name: `${name} 삭제` }).waitFor();
    await page.getByRole('button', { name: `${name} 삭제` }).click();
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await status(page, /저장했습니다/);
    await page.reload();
    await page.getByText('등록한 기술이 없습니다').waitFor();
    return { skill: name };
  });

  await step('PUBLIC_POSTINGS', 'A-search', 'search postings, open detail panel', async () => {
    await page.goto(`${BASE}/job-postings`);
    await expectH1(page, '새로운 기회를 찾아보세요');
    await page.getByRole('search', { name: '채용공고 검색 조건' }).locator('input[name="q"]').fill(posting.title);
    await page.getByRole('button', { name: '검색', exact: true }).click();
    const btn = page.getByRole('list', { name: '채용공고 검색 결과' }).getByRole('button', { name: `${posting.title} 상세 보기` }).first();
    await btn.click();
    await page.locator('h3', { hasText: posting.title }).first().waitFor();
    return { title: posting.title, q: new URL(page.url()).searchParams.get('q') };
  });
  await step('USER', 'A-application', 'add application from posting detail', async () => {
    await page.getByRole('button', { name: '지원 기록에 추가' }).click();
    await status(page, /지원 기록에 추가했습니다/);
    await page.getByRole('button', { name: '지원 기록에 있음' }).waitFor();
  });
  await step('USER', 'A-application', 'board shows the card; change stage to 지원 완료', async () => {
    await page.getByRole('link', { name: '지원 현황 보기' }).first().click();
    await expectH1(page, '지원 현황');
    const card = page.locator('li', { has: page.locator('strong', { hasText: posting.title }) }).first();
    await card.waitFor();
    await card.getByLabel('단계').selectOption({ label: '지원 완료' });
    await status(page, /단계를 ‘지원 완료’/);
    await page.reload();
    await page.getByRole('heading', { name: /지원 완료 1건/ }).waitFor();
    const mockNote = await page.getByText('가상 데이터(Mock)입니다. 서버 연동은 아직 없습니다.').count();
    return { stage: 'applied', persisted: true, misleading_mock_note_visible: mockNote > 0 };
  });
  await step('NOTIFICATION', 'A-inbox', 'own stage change → inbox empty (no self notification)', async () => {
    await page.goto(`${BASE}/me/notifications`);
    await expectH1(page, '알림함');
    await page.getByText('받은 알림이 없습니다').waitFor();
    return { inbox: 'empty' };
  });

  // 문서: 업로드 → worker → 다운로드 가능 → 삭제 → worker → 완료
  const docName = 'e2e-ui-resume.pdf';
  await step('DOCUMENT', 'A-documents', 'upload PDF (UI) → scanning', async () => {
    await page.goto(`${BASE}/me/documents`);
    await expectH1(page, '내 문서 관리');
    await page.getByLabel('파일 선택 (PDF 또는 DOCX)').setInputFiles({ name: docName, mimeType: 'application/pdf', buffer: pdf() });
    await page.getByRole('button', { name: '업로드', exact: true }).click();
    await status(page, /업로드를 접수했습니다/);
    await page.getByRole('article', { name: docName }).waitFor();
  });
  await step('DOCUMENT', 'A-documents', 'worker run → list shows 다운로드 가능 → download bytes', async () => {
    const w = worker('app.document_worker');
    await page.getByRole('button', { name: '상태 새로고침' }).click().catch(() => {});
    await page.getByRole('article', { name: docName }).getByText('다운로드 가능').waitFor({ timeout: 20000 });
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: `${docName} 다운로드` }).click()]);
    const saved = path.join(ART, 'downloaded-' + docName);
    await dl.saveAs(saved);
    const same = readFileSync(saved).equals(pdf());
    if (!same) throw new Error('downloaded bytes differ');
    return { worker: w.slice(-120), download: 'bytes equal' };
  });
  await step('DOCUMENT', 'A-documents', 'delete (confirm dialog) → worker → removed', async () => {
    await page.getByRole('button', { name: `${docName} 삭제` }).click();
    const dlg = page.getByRole('dialog', { name: '문서 삭제 확인' });
    await dlg.getByRole('button', { name: '삭제', exact: true }).click();
    await status(page, /삭제를 요청했습니다/);
    worker('app.document_worker');
    await page.getByText('문서 삭제가 완료되었습니다.').waitFor({ timeout: 20000 });
    await page.reload();
    await page.getByText('등록한 문서가 없습니다').waitFor();
  });

  await step('USER', 'A-data-export', 'request export with password re-auth (UI)', async () => {
    await page.goto(`${BASE}/me/data`);
    await expectH1(page, '내 데이터 내려받기');
    await page.getByRole('button', { name: '내 데이터 내보내기 요청' }).click();
    const dlg = page.getByRole('dialog', { name: '비밀번호 다시 확인' });
    await dlg.getByLabel('비밀번호').fill(PASSWORD);
    await dlg.getByRole('button', { name: '확인', exact: true }).click();
    await status(page, /내보내기를 요청했습니다/);
  });
  await step('USER', 'A-data-export', 'worker run in-process → 완료 → one-time download contains own data only', async () => {
    const w = worker('app.personal_data_worker');
    await page.getByRole('button', { name: '상태 새로 고침' }).click();
    await page.getByText('완료 · 내려받기 가능').first().waitFor({ timeout: 20000 });
    const btn = page.getByRole('button', { name: /요청 파일 내려받기/ }).first();
    const [dl] = await Promise.all([page.waitForEvent('download'), (async () => {
      await btn.click();
      const dlg = page.getByRole('dialog', { name: '비밀번호 다시 확인' });
      if (await dlg.isVisible({ timeout: 1500 }).catch(() => false)) {
        await dlg.getByLabel('비밀번호').fill(PASSWORD);
        await dlg.getByRole('button', { name: '확인', exact: true }).click();
      }
    })()]);
    const saved = path.join(ART, 'my-data-export.seeker.json');
    await dl.saveAs(saved);
    const text = readFileSync(saved, 'utf8');
    if (!text.includes(ACC.seeker.email)) throw new Error('export lacks own email');
    if (text.includes(ACC.seeker_b.email) || text.includes(ACC.company.email)) throw new Error('export contains another user');
    return { worker: w.slice(-120), bytes: text.length };
  });

  await step('PORTFOLIO', 'A-portfolio', 'select fields + experience, save, confirm consent, create link', async () => {
    await page.goto(`${BASE}/me/public-profile`);
    await expectH1(page, '공개 포트폴리오');
    await page.getByLabel('이름(또는 별칭)').check();
    await page.getByLabel('회사·기관').check();
    await page.getByLabel('직무·직함').check();
    await page.getByLabel('경력: E2E UI 회사 · E2E UI 개발자').check();
    await page.getByRole('button', { name: '선택 저장' }).click();
    await status(page, /선택을 저장했습니다/);
    await page.getByRole('button', { name: '이대로 공개 확정' }).click();
    const dlg = page.getByRole('dialog', { name: '이 내용을 공개할까요?' });
    await dlg.getByLabel('위 내용을 이해했습니다').check();
    await dlg.getByRole('button', { name: '공개 확정' }).click();
    await status(page, /공개를 확정했습니다/);
    await page.getByLabel('사용 기간').selectOption({ label: '7일' });
    await page.getByRole('button', { name: '공유 링크 만들기' }).click();
    await status(page, /공유 링크를 만들었습니다/);
    out.portfolioUrl = await page.getByLabel('공유 주소').inputValue();
    if (!/\/p\/[A-Za-z0-9_-]{20,}$/.test(out.portfolioUrl)) throw new Error(`unexpected share URL ${out.portfolioUrl}`);
    return { share_url_shape: out.portfolioUrl.replace(/\/p\/.*/, '/p/<token>') };
  });
  await step('MODERATION', 'C-roles', 'seeker cannot open /admin/moderation (403 screen)', async () => {
    await page.goto(`${BASE}/admin/moderation`);
    await expectH1(page, '접근 권한이 없습니다');
  });
  await closeContext(c);
}

// =========================================================================================== D. 익명(포트폴리오·공고)
async function anonPortfolio(expectVisible, label) {
  const c = await newContext(`anon-${label}`);
  const { page } = c;
  const ok = await step('PORTFOLIO', 'D-portfolio', `anonymous opens share link — ${label}`, async () => {
    if (!out.portfolioUrl) throw new Error('no portfolio URL from previous step');
    await page.goto(out.portfolioUrl);
    await expectH1(page, '공개 포트폴리오');
    if (expectVisible) {
      await page.getByRole('article').getByText('E2E UI 회사').waitFor();
      const body = await page.locator('main').innerText();
      if (body.includes(ACC.seeker.email)) throw new Error('email leaked on public page');
      return { visible: true, email_hidden: true };
    }
    await page.getByText('볼 수 없는 링크입니다').waitFor();
    return { blocked: true };
  });
  await closeContext(c);
  return ok;
}
await anonPortfolio(true, 'consented + active link');
{
  const c = await newContext('seeker-revoke');
  const { page } = c;
  await step('PORTFOLIO', 'A-portfolio', 'revoke link (UI)', async () => {
    await login(page, ACC.seeker.email);
    await page.goto(`${BASE}/me/public-profile`);
    await page.getByRole('button', { name: /에 만든 링크 회수$/ }).first().click();
    await page.getByRole('dialog', { name: '이 링크를 회수할까요?' }).getByRole('button', { name: '회수', exact: true }).click();
    await status(page, /링크를 회수했습니다/);
  });
  await closeContext(c);
}
await anonPortfolio(false, 'revoked link blocked');
{
  const c = await newContext('seeker-withdraw');
  const { page } = c;
  await step('PORTFOLIO', 'A-portfolio', 'new link then withdraw consent (UI) — all links closed', async () => {
    await login(page, ACC.seeker.email);
    await page.goto(`${BASE}/me/public-profile`);
    await page.getByRole('button', { name: '공유 링크 만들기' }).click();
    await status(page, /공유 링크를 만들었습니다/);
    out.portfolioUrl = await page.getByLabel('공유 주소').inputValue();
    await page.getByRole('button', { name: '공개 중단(동의 철회)' }).click();
    await page.getByRole('dialog', { name: '공개를 모두 중단할까요?' }).getByRole('button', { name: '공개 중단', exact: true }).click();
    await status(page, /공개를 중단했습니다/);
  });
  await closeContext(c);
}
await anonPortfolio(false, 'non-consented (withdrawn) blocked');

// =========================================================================================== B. 기업
let orgId = null;
const uiTitles = { approve: 'E2EUI-APPROVE 승인될 공고', reject: 'E2EUI-REJECT 반려될 공고' };
const postingIds = {};
{
  const c = await newContext('company');
  const { page } = c;
  await step('COMPANY', 'B-org', 'create organization (UI) → owner, 운영 확인 대기', async () => {
    await login(page, ACC.company.email);
    await page.goto(`${BASE}/company`);
    await expectH1(page, '기업 콘솔');
    await page.getByLabel('회사 이름').fill('E2E UI 조직');
    await page.getByRole('button', { name: '등록 신청' }).click();
    await page.getByRole('navigation', { name: '내 조직' }).getByRole('button', { name: 'E2E UI 조직' }).waitFor();
    await page.getByText(/기업 관리자 · 운영 확인 대기/).first().waitFor();
    await page.waitForURL(/org=/);
    orgId = new URL(page.url()).searchParams.get('org');
    return { org: orgId };
  });
  await step('COMPANY', 'B-org', 'member list shows me as 기업 관리자', async () => {
    const table = page.getByRole('table', { name: /조직 멤버 1명/ });
    await table.waitFor();
    const row = table.getByRole('row', { name: new RegExp(`${ACC.company.name} \\(나\\)`) });
    await row.waitFor();
    const text = await row.innerText();
    if (!text.includes('기업 관리자')) throw new Error(`row: ${text}`);
    return { row: text.replace(/\s+/g, ' ').slice(0, 120) };
  });
  await step('COMPANY', 'B-org', 'admin verifies organization (no admin UI → real API) → 활성', async () => {
    const org = await api(ACC.company.email, 'GET', `/api/v1/organizations/${orgId}`);
    const v = await api(ACC.admin.email, 'POST', `/api/v1/admin/organizations/${orgId}/verification`, { decision: 'approve', version: org.json.version });
    if (v.status !== 200 || v.json.status !== 'active') throw new Error(`verify -> ${v.status} ${v.text.slice(0, 200)}`);
    await page.reload();
    await page.getByText(/기업 관리자 · 활성/).first().waitFor();
    return { via: 'api', status: v.json.status };
  });
  for (const [key, title] of Object.entries(uiTitles)) {
    await step('COMPANY', 'B-postings', `create draft, edit all required fields, save (${key})`, async () => {
      await page.goto(`${BASE}/company/postings?org=${orgId}`);
      await expectH1(page, '공고 관리');
      await page.getByLabel('새 공고 제목').fill(title);
      await page.getByRole('button', { name: '초안 만들기' }).click();
      await status(page, /초안을 만들었습니다/);
      await page.waitForURL(/posting=/);
      postingIds[key] = new URL(page.url()).searchParams.get('posting');
      const form = page.getByRole('form', { name: '공고 편집' });
      await form.getByLabel(/^직무 설명/).fill('E2E UI 합성 직무 설명');
      await form.getByLabel(/^고용형태/).selectOption({ label: '정규직' });
      await form.getByLabel(/^근무지/).fill('서울');
      await form.getByLabel(/^지원 링크/).fill('https://example.invalid/apply');
      const due = new Date(Date.now() + 20 * 86400000).toISOString().slice(0, 10);
      await form.getByLabel(/^마감일/).fill(due);
      await form.getByRole('button', { name: '저장', exact: true }).click();
      await status(page, /저장했습니다/);
      return { posting: postingIds[key] };
    });
    await step('COMPANY', 'B-postings', `submit for review → 검수 대기 (${key})`, async () => {
      await page.getByRole('button', { name: '검수 요청', exact: true }).click();
      await status(page, /검수를 요청했습니다/);
      await page.locator('h2', { hasText: title }).getByText('검수 대기').waitFor();
    });
  }
  await step('PUBLIC_POSTINGS', 'D-anon', 'pending company postings not visible on the public list (same browser, logged in)', async () => {
    for (const title of Object.values(uiTitles)) {
      await page.goto(`${BASE}/job-postings?q=${encodeURIComponent(title.split(' ')[0])}`);
      await page.getByText('조건에 맞는 공고가 없습니다').waitFor();
    }
  });
  await closeContext(c);
}

// 검수 건: 현재 스택은 검수 요청 때 자동 생성하지 않음 → 관측 후 fixture 로 생성(PR #359 대기)
const caseIds = {};
for (const [key] of Object.entries(uiTitles)) {
  if (!postingIds[key]) continue;
  const before = await api(ACC.admin.email, 'GET', `/api/v1/admin/moderation-cases?target_type=company_posting&limit=100`);
  const auto = (before.json?.items || []).filter((i) => i.target_id === postingIds[key]).length;
  if (auto === 1) {
    caseIds[key] = before.json.items.find((i) => i.target_id === postingIds[key]).case_id;
    mark('MODERATION', 'policy', `UI submit auto-created exactly 1 case (${key})`, 'PASS', 'observed 1');
  } else {
    // PR #359(a93d8ae) 병합 후에는 검수 요청이 검수 건을 만들어야 한다 → 없으면 FAIL. 관리자 화면 흐름은 계속 보려고 fixture 로 보충
    mark('MODERATION', 'policy', `UI submit auto-created exactly 1 case (${key})`, 'FAIL', `observed ${auto} cases; admin flow continues with a fixture case (e2e_helpers.py submit-case)`);
    caseIds[key] = JSON.parse(py([process.env.E2E_HELPERS, 'submit-case', postingIds[key], ACC.company.user_id])).case_id;
  }
}

// =========================================================================================== C. 관리자
{
  const c = await newContext('admin');
  const { page } = c;
  await step('MODERATION', 'C-queue', 'admin logs in and sees the moderation queue with both cases', async () => {
    await login(page, ACC.admin.email);
    await page.goto(`${BASE}/admin/moderation`);
    await expectH1(page, '콘텐츠 검수');
    for (const t of Object.values(uiTitles)) await page.getByRole('link', { name: new RegExp(t.split(' ')[0]) }).first().waitFor();
    return { cases: caseIds };
  });
  async function decide(key, decision) {
    await page.goto(`${BASE}/admin/moderation`);
    await page.getByRole('link', { name: new RegExp(uiTitles[key].split(' ')[0]) }).first().click();
    await expectH1(page, '검수 건');
    await page.getByRole('button', { name: '담당 시작' }).click();
    await status(page, /담당을 시작했습니다/);
    if (decision === 'approve') {
      await page.getByRole('button', { name: '승인', exact: true }).click();
      await page.getByRole('dialog', { name: '이 검수 건을 승인할까요?' }).getByRole('button', { name: '승인', exact: true }).click();
      await status(page, /승인했습니다/);
    } else {
      await page.getByRole('button', { name: '반려', exact: true }).click();
      const dlg = page.getByRole('dialog', { name: '이 검수 건을 반려할까요?' });
      await dlg.getByLabel('반려 사유 (필수)').selectOption({ label: '부정확·허위 정보' });
      await dlg.getByLabel(/^설명/).fill('E2E 반려 사유 메모');
      await dlg.getByRole('button', { name: '반려', exact: true }).click();
      await status(page, /반려했습니다/);
    }
    const history = await page.locator('ol li').allInnerTexts();
    return { history: history.map((h) => h.replace(/\s+/g, ' ').slice(0, 80)) };
  }
  await step('MODERATION', 'C-decide', 'open detail → assign → approve (company posting)', () => decide('approve', 'approve'));
  await step('MODERATION', 'C-decide', 'open detail → assign → reject with reason (company posting)', () => decide('reject', 'reject'));
  await step('MODERATION', 'C-audit', 'audit events record the admin case views (real API; audit UI is mock-only)', async () => {
    const from = new Date(Date.now() - 3600000).toISOString();
    const to = new Date(Date.now() + 60000).toISOString();
    const r = await api(ACC.admin.email, 'GET', `/api/v1/admin/audit-events?limit=100&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
    if (r.status !== 200) throw new Error(`audit-events -> ${r.status} ${r.text.slice(0, 200)}`);
    const items = r.json.items || [];
    const review = items.filter((i) => (i.action_code || i.action || '').includes('admin.content.review'));
    if (!review.length) throw new Error(`no admin.content.review events among ${items.length}`);
    return { via: 'api', events: items.length, content_review_events: review.length };
  });
  mark('MODERATION', 'C-audit', 'audit events screen in UI', 'NOT_RUN', 'admin audit UI is enabled only in mock mode (env.ts adminAuditUi requires VITE_API_MOCK=true) — defect FSE-005');
  await step('MODERATION', 'C-roles', 'second admin view: decided cases filtered as 승인/반려', async () => {
    await page.goto(`${BASE}/admin/moderation`);
    await page.getByRole('group', { name: '상태' }).getByRole('button', { name: '승인', exact: true }).click();
    await page.getByRole('link', { name: /E2EUI-APPROVE/ }).first().waitFor();
    await page.getByRole('group', { name: '상태' }).getByRole('button', { name: '반려', exact: true }).click();
    await page.getByRole('link', { name: /E2EUI-REJECT/ }).first().waitFor();
  });
  await closeContext(c);
}

// =========================================================================================== B. 결과 확인 + D. 공개
{
  const c = await newContext('company-result');
  const { page } = c;
  await step('COMPANY', 'B-review', 'company sees 게시 중 (approved) and 반려 + reason (rejected)', async () => {
    await login(page, ACC.company.email);
    await page.goto(`${BASE}/company/postings?org=${orgId}&posting=${postingIds.approve}`);
    await page.locator('h2', { hasText: uiTitles.approve }).getByText('게시 중').waitFor();
    await page.goto(`${BASE}/company/postings?org=${orgId}&posting=${postingIds.reject}`);
    await page.locator('h2', { hasText: uiTitles.reject }).getByText('반려').waitFor();
    const reason = await page.getByText(/반려 사유:/).first().innerText();
    return { approve: '게시 중', reject: '반려', reason };
  });
  await closeContext(c);
}
{
  const c = await newContext('anon');
  const { page } = c;
  await step('PUBLIC_POSTINGS', 'D-anon', 'anonymous public list renders', async () => {
    await page.goto(`${BASE}/job-postings`);
    await expectH1(page, '새로운 기회를 찾아보세요');
    await page.getByRole('list', { name: '채용공고 검색 결과' }).getByRole('button').first().waitFor();
  });
  await step('PUBLIC_POSTINGS', 'D-anon', 'approved company posting is public; rejected one is not', async () => {
    await page.goto(`${BASE}/job-postings?q=E2EUI-APPROVE`);
    await page.getByRole('button', { name: `${uiTitles.approve} 상세 보기` }).waitFor();
    await page.goto(`${BASE}/job-postings?q=E2EUI-REJECT`);
    await page.getByText('조건에 맞는 공고가 없습니다').waitFor();
  });
  await step('PUBLIC_POSTINGS', 'D-anon', 'JobKorea-like crawled draft and API company draft/rejected not visible', async () => {
    for (const q of ['E2EJOBKOREADRAFT', 'E2EAPI-DRAFT', 'E2EAPI-REJECTED']) {
      await page.goto(`${BASE}/job-postings?q=${q}`);
      await page.getByText('조건에 맞는 공고가 없습니다').waitFor();
    }
  });
  await step('PUBLIC_POSTINGS', 'D-anon', 'anonymous cannot open protected screens (redirect to login)', async () => {
    await page.goto(`${BASE}/me/applications`);
    await expectH1(page, '로그인');
  });
  await closeContext(c);
}

await browser.close();
writeFileSync(path.join(path.dirname(process.env.E2E_OUT), 'browser-state.json'), JSON.stringify({ ...out, orgId, postingIds, caseIds }, null, 2));
const summary = results.reduce((a, r) => ({ ...a, [r.status]: (a[r.status] ?? 0) + 1 }), {});
writeFileSync(process.env.E2E_OUT, JSON.stringify({ browser: browserInfo, summary, results }, null, 2));
console.log(JSON.stringify({ browser: browserInfo, summary }));
