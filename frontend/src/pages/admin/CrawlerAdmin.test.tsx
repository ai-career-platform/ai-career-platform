/**
 * T156 크롤러 관리자 콘솔: 경로·메뉴·권한(실제 RequireAuth + Mock 로그인), 화면 동작(Mock Adapter),
 * 실제 API Adapter 계약(가짜 fetch: 경로·헤더·오류 매핑). 네트워크 요청 없음.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { CrawlerAdminServiceProvider } from '../../admin/CrawlerAdminServiceProvider';
import { crawlerAdminErrorMessage, type CrawlerAdminService } from '../../api/crawlerAdmin';
import { createHttpCrawlerAdminService } from '../../api/crawlerAdminHttp';
import { createHttpClient } from '../../api/http';
import { MOCK_PASSWORD } from '../../mocks/handlers';
import { createMockCrawlerAdminService, type CrawlerAdminMockOptions } from '../../mocks/crawlerAdmin';
import { buildRoutes } from '../../routes';
import { CrawlerAdminPage } from './CrawlerAdminPage';

vi.mock('../../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true, adminModerationUi: false, adminAuditUi: false, crawlerAdminUi: false } }));

// ------------------------------------------------------------------ routes
function open(path: string, crawlerAdminUi: boolean) {
  const router = createMemoryRouter(buildRoutes({ adminModerationUi: false, crawlerAdminUi }), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

async function login(email: string) {
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

describe('crawler admin routes', () => {
  it('flag off (default): admin has no menu and /admin/crawler is not found', async () => {
    const router = open('/login', false);
    await login('admin@example.com');
    await screen.findByRole('heading', { name: '내 계정' });
    await router.navigate('/admin/crawler');
    expect(await screen.findByRole('heading', { name: '페이지를 찾을 수 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '크롤러 관리' })).not.toBeInTheDocument();
  });

  it('the default exported routes keep the feature off', async () => {
    const { routes } = await import('../../routes');
    expect(JSON.stringify(routes, (key, value) => (key === 'element' ? undefined : value))).not.toContain('admin/crawler');
  });

  it('flag on: anonymous goes to login, job seeker gets 403 without menu', async () => {
    open('/admin/crawler', true);
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument();
    await login('user@example.com');
    expect(await screen.findByRole('heading', { name: '접근 권한이 없습니다' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '크롤러 관리' })).not.toBeInTheDocument();
  });

  it('flag on: admin sees the menu and the console with mock keywords', async () => {
    open('/admin/crawler', true);
    await login('admin@example.com');
    expect(await screen.findByRole('heading', { name: '크롤러 관리' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '크롤러 관리' })).toHaveAttribute('href', '/admin/crawler');
    expect(await screen.findByRole('table', { name: /검색어 목록/ }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /LIVE/ })).not.toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ page with mock service
function renderPage(options: CrawlerAdminMockOptions = {}, service?: CrawlerAdminService) {
  const mock = createMockCrawlerAdminService({ now: () => new Date('2026-11-11T03:00:00Z'), ...options });
  render(<CrawlerAdminServiceProvider service={service ?? mock}><CrawlerAdminPage /></CrawlerAdminServiceProvider>);
  return mock;
}
const table = (name: RegExp) => screen.findByRole('table', { name });
const row = async (tableName: RegExp, text: string) => {
  const t = await table(tableName);
  const cell = await within(t).findByText(text);
  return cell.closest('tr')!;
};

describe('crawler admin console (mock)', () => {
  it('lists keywords with stats and creates a keyword; duplicates and blanks are refused', async () => {
    const svc = renderPage();
    expect(await row(/검색어 목록/, '데이터 분석')).toBeInTheDocument();
    const spy = vi.spyOn(svc, 'createKeyword');
    fireEvent.change(screen.getByRole('textbox', { name: '검색어' }), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('검색어를 입력해 주세요.');
    expect(spy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole('textbox', { name: '검색어' }), { target: { value: '  ＭＬ   엔지니어 ' } });
    fireEvent.change(screen.getByLabelText(/^우선순위/), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    expect(await screen.findByText('검색어 "ML 엔지니어"를 추가했습니다.')).toBeInTheDocument();
    expect(await row(/검색어 목록/, 'ML 엔지니어')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: '검색어' }), { target: { value: 'python' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('같은 검색어가 이미 있습니다');
  });

  it('edits (Esc cancels), disables, deletes with confirmation and shows the audit trail', async () => {
    const svc = renderPage();
    const llm = await row(/검색어 목록/, 'LLM');
    fireEvent.click(within(llm).getByRole('button', { name: 'LLM 수정' }));
    const editor = screen.getByRole('form', { name: '검색어 수정: LLM' });
    expect(within(editor).getByLabelText('새 검색어')).toHaveFocus();
    fireEvent.keyDown(editor, { key: 'Escape' });
    expect(screen.queryByRole('form', { name: '검색어 수정: LLM' })).not.toBeInTheDocument();

    fireEvent.click(within(await row(/검색어 목록/, 'LLM')).getByRole('button', { name: 'LLM 수정' }));
    fireEvent.change(screen.getByLabelText('새 검색어'), { target: { value: 'LLM 서비스' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByText('"LLM 서비스"로 수정했습니다.')).toBeInTheDocument();

    fireEvent.click(within(await row(/검색어 목록/, 'LLM 서비스')).getByRole('button', { name: 'LLM 서비스 비활성화' }));
    expect(await screen.findByText('"LLM 서비스"를 비활성화했습니다.')).toBeInTheDocument();
    fireEvent.click(within(await row(/검색어 목록/, 'LLM 서비스')).getByRole('button', { name: 'LLM 서비스 Fixture 실행' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('비활성 검색어는 실행할 수 없습니다.');

    fireEvent.click(within(await row(/검색어 목록/, 'LLM 서비스')).getByRole('button', { name: 'LLM 서비스 변경 이력' }));
    const audit = await table(/검색어 변경 이력/);
    expect(within(audit).getByText('활성 변경')).toBeInTheDocument();
    expect(within(audit).getByText('수정')).toBeInTheDocument();

    fireEvent.click(within(await row(/검색어 목록/, 'LLM 서비스')).getByRole('button', { name: 'LLM 서비스 삭제' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '삭제' }));
    expect(await screen.findByText('"LLM 서비스"를 삭제했습니다.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('LLM 서비스')).not.toBeInTheDocument());
    expect(svc.snapshot().audit.map((a) => a.action)).toEqual(['SOFT_DELETE', 'SET_ENABLED', 'EDIT']);
  });

  it('runs a fixture job once; a second run is refused while one is active', async () => {
    const svc = renderPage();
    const ai = await row(/검색어 목록/, 'AI');
    fireEvent.click(within(ai).getByRole('button', { name: 'AI Fixture 실행' }));
    expect(await screen.findByText('"AI" Fixture 작업을 대기열에 만들었습니다(PENDING).')).toBeInTheDocument();
    fireEvent.click(within(await row(/검색어 목록/, 'AI')).getByRole('button', { name: 'AI Fixture 실행' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('대기·진행 중인 작업이 이미 있습니다');
    const ledger = svc.snapshot().commands;
    expect(ledger.map((c) => [c.outcome, c.reason])).toEqual([['REFUSED', 'ACTIVE_JOB_EXISTS'], ['ACCEPTED', 'FIXTURE_JOB_PENDING']]);
  });

  it('tabs follow the WAI-ARIA keyboard pattern; jobs can be stopped and retried', async () => {
    renderPage();
    const keywordsTab = screen.getByRole('tab', { name: '검색어' });
    expect(keywordsTab).toHaveAttribute('aria-selected', 'true');
    keywordsTab.focus();
    fireEvent.keyDown(keywordsTab, { key: 'ArrowRight' });
    const jobsTab = screen.getByRole('tab', { name: '작업' });
    expect(jobsTab).toHaveFocus();
    expect(jobsTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'crawler-tab-jobs');
    fireEvent.keyDown(jobsTab, { key: 'End' });
    expect(screen.getByRole('tab', { name: '명령 기록' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('tab', { name: '명령 기록' }), { key: 'Home' });
    fireEvent.keyDown(screen.getByRole('tab', { name: '검색어' }), { key: 'ArrowLeft' });
    expect(screen.getByRole('tab', { name: '명령 기록' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(screen.getByRole('tab', { name: '작업' }));

    const pending = await row(/작업 목록/, '대기');
    fireEvent.click(within(pending).getByRole('button', { name: /대기 작업 중단/ }));
    expect(await screen.findByText('대기 작업을 취소했습니다.')).toBeInTheDocument();
    const failed = await row(/작업 목록/, '실패');
    fireEvent.click(within(failed).getByRole('button', { name: /작업 재시도/ }));
    expect(await screen.findByText('재시도 작업을 대기열에 만들었습니다(PENDING).')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('상태'), { target: { value: 'COMPLETED' } });
    const t = await table(/작업 목록/);
    await waitFor(() => expect(within(t).queryByText('실패')).not.toBeInTheDocument());
    expect(within(t).getAllByText('완료').length).toBeGreaterThan(0);
  });

  it('shows run history with failures and the safe event log', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '실행 이력' }));
    expect(await screen.findByText('최근 2건 중 실패·일부 성공 1건')).toBeInTheDocument();
    const failedRun = await row(/실행 이력/, '실패');
    expect(within(failedRun).getByText('3 / 0 / 1 / 2')).toBeInTheDocument();
    fireEvent.click(within(failedRun).getByRole('button', { name: /실행 로그 보기/ }));
    expect(await screen.findByText('재시도 한도 도달')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/<html|https?:\/\//i);
  });

  it('changes the schedule time but cannot enable it; read-only when the server write API is off', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: '스케줄 설정' }));
    expect(await screen.findByText('21:00~08:00 KST (변경 불가)')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '스케줄 활성' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('실행 시각 (KST)'), { target: { value: '04:30' } });
    fireEvent.click(screen.getByRole('button', { name: '시각 저장' }));
    expect(await screen.findByText('실행 시각을 04:30 KST로 바꿨습니다. 스케줄은 계속 꺼져 있습니다.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '명령 기록' }));
    expect(await row(/명령 기록/, 'schedule:jobkorea-daily')).toHaveTextContent('수락');
  });

  it('write API off: settings are read-only and keyword writes explain the 404', async () => {
    renderPage({ writeApi: false });
    fireEvent.click(screen.getByRole('tab', { name: '스케줄 설정' }));
    expect(await screen.findByText(/읽기 전용으로 표시합니다/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '시각 저장' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '검색어' }));
    await table(/검색어 목록/);
    fireEvent.change(screen.getByRole('textbox', { name: '검색어' }), { target: { value: '새 검색어' } });
    fireEvent.click(screen.getByRole('button', { name: '추가' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('쓰기 API(CRAWLER_ADMIN_WRITE_API)가 꺼져 있습니다');
  });

  it.each([
    [403, '관리자 권한이 없습니다', false],
    [503, '크롤러 데이터베이스에 연결할 수 없습니다', true],
  ])('load error %s shows a clear state panel', async (status, text, retry) => {
    renderPage({ failWith: status });
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(Boolean(screen.queryByRole('button', { name: '다시 시도' }))).toBe(retry);
  });

  it('empty keyword list shows the empty state', async () => {
    const svc = createMockCrawlerAdminService();
    renderPage({}, { ...svc, listKeywordStats: async () => [] });
    expect(await screen.findByText('등록된 검색어가 없습니다')).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------ HTTP adapter contract
describe('crawler admin HTTP adapter', () => {
  function client(responder: (url: string, init: RequestInit) => Response) {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const http = createHttpClient({
      baseUrl: '/api', getToken: () => 'token-x',
      fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ url: String(input), init: init! });
        return responder(String(input), init!);
      }) as typeof fetch,
    });
    return { svc: createHttpCrawlerAdminService(http), calls };
  }
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

  it('reads use the T155 paths; commands send Idempotency-Key, CSRF and bearer headers', async () => {
    const { svc, calls } = client(() => json({ command_id: 'c', outcome: 'ACCEPTED', reason: 'FIXTURE_JOB_PENDING', replayed: false }, 201));
    await svc.listJobs({ status: 'FAILED', keyword_id: 3 });
    expect(calls[0]!.url).toBe('/api/v1/admin/crawler/jobs?limit=100&status=FAILED&keyword_id=3');
    await svc.runKeyword(3, 'ui:key-1');
    const run = calls[1]!;
    expect(run.url).toBe('/api/v1/admin/crawler/commands/run');
    const headers = run.init.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe('ui:key-1');
    expect(headers['X-CSRF-TOKEN']).toBe('1');
    expect(headers.Authorization).toBe('Bearer token-x');
    expect(JSON.parse(run.init.body as string)).toEqual({ keyword_id: 3, mode: 'fixture' });
    await svc.updateScheduleTime('jobkorea-daily', '04:30', 'ui:key-2');
    expect(calls[2]!.init.method).toBe('PATCH');
    expect(calls[2]!.url).toBe('/api/v1/admin/crawler/schedules/jobkorea-daily');
  });

  it('settings fall back to the read-only schedules when the write API is off (404)', async () => {
    const { svc, calls } = client((url) => (url.includes('/settings')
      ? json({ code: 'NOT_FOUND', status: 404, message: 'x' }, 404)
      : json([{ schedule_id: 'jobkorea-daily', enabled: false, mode: 'fixture', local_time: '03:00:00' }])));
    const settings = await svc.getSettings();
    expect(settings.writeApi).toBe(false);
    expect(settings.schedules[0]!.local_time).toBe('03:00:00');
    expect(calls.map((c) => c.url)).toEqual(['/api/v1/admin/crawler/settings', '/api/v1/admin/crawler/schedules']);
  });

  it('a 409 refusal maps the reason header to a message', async () => {
    const { svc } = client(() => json({ code: 'CONFLICT', status: 409, message: 'x' }, 409,
      { 'X-Crawler-Command-Reason': 'LIVE_NOT_APPROVED:NOT_APPROVED' }));
    const error = await svc.runKeyword(1, 'ui:k').catch((e: unknown) => e);
    expect(crawlerAdminErrorMessage(error).message).toBe('실제 사이트 수집은 승인 전이라 실행할 수 없습니다(LIVE HOLD).');
  });
});
