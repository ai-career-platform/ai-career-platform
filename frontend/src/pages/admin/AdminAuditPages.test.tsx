/**
 * T85 운영 감사·AI 사용량 화면 테스트 (Mock Adapter, 합성 데이터). 번호는 작업지시서 STEP 09 항목입니다.
 * 모든 테스트 공통: 화면이 네트워크 요청을 보내면 실패합니다(Mock 전용 단계).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminAuditServiceProvider } from '../../admin/AdminAuditServiceProvider';
import type { AdminAuditService, AiUsageResult, AuditEventPage, AuditQuery, UsageQuery } from '../../api/adminAudit';
import { ApiError } from '../../api/errors';
import { AuthContext, type AuthContextValue } from '../../auth/useAuth';
import { createMockAdminAuditService, seedAuditEvents, type MockAdminAuditService, type MockUsageRecord } from '../../mocks/adminAudit';
import { AiUsagePage, COST_WARNING } from './AiUsagePage';
import { AuditEventsPage } from './AuditEventsPage';

const NOW = new Date('2026-11-10T03:00:00Z');
const now = () => NOW;
let fetchSpy: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => { fetchSpy = vi.fn<typeof fetch>(); vi.stubGlobal('fetch', fetchSpy); });
afterEach(() => {
  const calls = fetchSpy.mock.calls.length;
  vi.unstubAllGlobals();
  if (calls) throw new Error(`the admin audit UI sent ${calls} network request(s); it must use the mock adapter only`);
});

const auth: AuthContextValue = {
  state: { status: 'authenticated', token: 'synthetic', user: { email: 'synthetic-admin', displayName: '합성 관리자',
    roles: ['job_seeker', 'admin'], userId: 'synthetic-admin' } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
};

function setup<S extends AdminAuditService>(path: '/admin/audit-events' | '/admin/ai-usage', service: S): S {
  render(
    <AuthContext.Provider value={auth}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AdminAuditServiceProvider service={service} />}>
            <Route path="/admin/audit-events" element={<AuditEventsPage now={now} />} />
            <Route path="/admin/ai-usage" element={<AiUsagePage now={now} />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
  return service;
}
const mock = (options: Parameters<typeof createMockAdminAuditService>[0] = {}): MockAdminAuditService =>
  createMockAdminAuditService({ now, ...options });
const rows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1);
const cells = (row: HTMLElement) => within(row).getAllByRole('cell').map((c) => c.textContent);
const auditCalls = (s: MockAdminAuditService) => s.calls.filter((c) => c.method === 'listEvents').map((c) => c.query as AuditQuery);
const usageCalls = (s: MockAdminAuditService) => s.calls.filter((c) => c.method === 'getUsage').map((c) => c.query as UsageQuery);
const field = (label: RegExp) => screen.getByLabelText(label);
const set = (label: RegExp, value: string) => fireEvent.change(field(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe('audit events', () => {
  it('1. admin sees the latest events first with KST time, code, target, request id', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table', { name: /감사 기록 목록/ });
    expect(rows()).toHaveLength(20);
    const first = cells(rows()[0]!);
    expect(first[0]).toBe('2026. 11. 10. 10:00:00 KST');                 // 01:00Z → 10:00 KST
    expect(first[4]).toMatch(/^req-mock-000[1-4]$/);
    expect(auditCalls(service)[0]).toEqual({ from: '2026-11-03T12:00:00+09:00', to: '2026-11-10T12:01:00+09:00', limit: 20,
      action_code: undefined, cursor: undefined });
  });

  it('4. loading state', async () => {
    setup('/admin/audit-events', mock({ latencyMs: 50 }));
    expect(screen.getByRole('status')).toHaveTextContent('불러오는 중');
    await screen.findByRole('table');
  });

  it('5. empty result', async () => {
    setup('/admin/audit-events', mock({ events: [] }));
    expect(await screen.findByText('조건에 맞는 감사 기록이 없습니다')).toBeInTheDocument();
  });

  it('6. period filter is sent as KST offsets and narrows the rows', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    set(/^시작 일시/, '2026-11-10T00:00'); set(/^종료 일시/, '2026-11-10T12:00');
    click('조회');
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(auditCalls(service).at(-1)).toMatchObject({ from: '2026-11-10T00:00:00+09:00', to: '2026-11-10T12:00:00+09:00' });
  });

  it('6b. from >= to is rejected on screen without a request', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    set(/^시작 일시/, '2026-11-10T12:00'); set(/^종료 일시/, '2026-11-10T12:00');
    click('조회');
    expect(screen.getByRole('alert')).toHaveTextContent('시작 일시는 종료 일시보다 빨라야 합니다');
    expect(auditCalls(service)).toHaveLength(1);
  });

  it('7. event type filter', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    set(/^작업 코드/, 'admin.role.grant');
    click('조회');
    await waitFor(() => expect(rows().every((r) => cells(r)[1] === 'admin.role.grant')).toBe(true));
    expect(auditCalls(service).at(-1)!.action_code).toBe('admin.role.grant');
    set(/^작업 코드/, 'Admin Role');
    click('조회');
    expect(screen.getByRole('alert')).toHaveTextContent('영역.대상.동작');
    expect(auditCalls(service)).toHaveLength(2);
  });

  it('8·9. next page uses the cursor, previous page returns to page 1', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    const firstPage = rows().map((r) => cells(r)[4]);
    click('다음');
    await waitFor(() => expect(rows()).toHaveLength(10));
    expect(screen.getByText('2페이지')).toBeInTheDocument();
    expect(auditCalls(service).at(-1)!.cursor).toEqual(expect.any(String));
    expect(rows().map((r) => cells(r)[4]).some((id) => firstPage.includes(id))).toBe(false);
    expect(screen.getByRole('button', { name: '다음' })).toBeDisabled();
    click('이전');
    await waitFor(() => expect(rows()).toHaveLength(20));
    expect(rows().map((r) => cells(r)[4])).toEqual(firstPage);
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled();
  });

  it('10. changing the filter drops the cursor and goes back to page 1', async () => {
    const service = setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    click('다음');
    await screen.findByText('2페이지');
    set(/^작업 코드/, 'agent.tool.call');
    click('조회');
    await screen.findByText('1페이지');
    expect(auditCalls(service).at(-1)).toMatchObject({ action_code: 'agent.tool.call', cursor: undefined });
    click('새로 조회');
    await waitFor(() => expect(auditCalls(service).at(-1)!.cursor).toBeUndefined());
  });

  it('11. a late response for old filters is ignored', async () => {
    const first = deferred<AuditEventPage>();
    const late = { items: [{ ...seedAuditEvents(NOW)[0]!, request_id: 'req-stale' }], next_cursor: null };
    const fresh = { items: [{ ...seedAuditEvents(NOW)[1]!, request_id: 'req-fresh' }], next_cursor: null };
    let n = 0;
    const service: AdminAuditService = {
      listEvents: () => (n++ === 0 ? first.promise : Promise.resolve(fresh)),
      getUsage: () => Promise.reject(new Error('unused')),
    };
    setup('/admin/audit-events', service);
    set(/^작업 코드/, 'agent.tool.call');
    click('조회');
    expect(await screen.findByText('req-fresh')).toBeInTheDocument();
    first.resolve(late);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('req-stale')).not.toBeInTheDocument();
  });

  it('12. 400 INVALID_CURSOR offers a restart from page 1', async () => {
    const service = mock();
    setup('/admin/audit-events', service);
    await screen.findByRole('table');
    service.failNext(new ApiError(400, '/v1/admin/audit-events', undefined, 'INVALID_CURSOR'));
    click('다음');
    expect(await screen.findByText(/목록 위치 정보가 만료/)).toBeInTheDocument();
    click('처음부터 다시 조회');
    await waitFor(() => expect(rows()).toHaveLength(20));
    expect(screen.getByText('1페이지')).toBeInTheDocument();
    expect(auditCalls(service).at(-1)!.cursor).toBeUndefined();
  });

  it.each([
    [401, 'TOKEN_EXPIRED', /로그인이 만료/],
    [403, 'FORBIDDEN', /권한이 없습니다.*회수/],
    [422, 'VALIDATION_FAILED', /조회 조건을 확인/],
  ])('13·14. %i %s shows a fixed message without retry', async (status, code, text) => {
    const service = mock();
    service.failNext(new ApiError(status, '/v1/admin/audit-events', undefined, code, 'raw server text'));
    setup('/admin/audit-events', service);
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByText('raw server text')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument();
  });

  it('15. 503 can be retried', async () => {
    const service = mock();
    service.failNext(new ApiError(503, '/v1/admin/audit-events', undefined, 'DEPENDENCY_UNAVAILABLE'));
    setup('/admin/audit-events', service);
    expect(await screen.findByText(/잠시 사용할 수 없습니다/)).toBeInTheDocument();
    click('다시 시도');
    await waitFor(() => expect(rows()).toHaveLength(20));
  });

  it('30a. no user id search input; actor and user targets are shortened; notices are shown', async () => {
    setup('/admin/audit-events', mock());
    await screen.findByRole('table');
    expect(screen.queryByLabelText(/사용자 ID/)).not.toBeInTheDocument();
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-0000000000(07|08)/);
    expect(text).toContain('사용자 00000000…0007');
    expect(text).not.toMatch(/@|token|password/i);
    expect(screen.getByRole('note')).toHaveTextContent('조회 시점 고정 아님');
    expect(screen.getByRole('note')).toHaveTextContent('가상 데이터(Mock)');
  });
});

describe('AI usage', () => {
  const at = (iso: string, extra: Partial<MockUsageRecord> = {}): MockUsageRecord => ({
    occurred_at: iso, feature_code: 'agent', provider_model: 'mock-model-a', input_tokens: 10, output_tokens: 5,
    estimated_cost_usd: '0.010000', user: 'active', ...extra,
  });

  it('16·17·18·26. request count, input/output tokens and the mock label', async () => {
    setup('/admin/ai-usage', mock());
    await screen.findByRole('table');
    const summary = screen.getByLabelText('기간 합계');
    expect(within(summary).getByText('요청 수').nextSibling).toHaveTextContent('5');
    expect(within(summary).getByText('입력 토큰').nextSibling).toHaveTextContent('9,100');
    expect(within(summary).getByText('출력 토큰').nextSibling).toHaveTextContent('2,250');
    expect(screen.getByText('표시 중: 가상 데이터(Mock)')).toBeInTheDocument();
  });

  it('19·20·21. model, feature and daily grouping use the server buckets', async () => {
    const service = setup('/admin/ai-usage', mock());
    await screen.findByRole('table');
    expect(rows().map((r) => cells(r)[0])).toEqual(['2026-11-07 (KST)', '2026-11-08 (KST)', '2026-11-09 (KST)']);
    set(/^집계 단위/, 'provider_model'); click('조회');
    await waitFor(() => expect(rows().map((r) => cells(r)[0])).toEqual(['mock-model-a', 'mock-model-b', 'mock-model-c']));
    set(/^집계 단위/, 'feature_code'); click('조회');
    await waitFor(() => expect(rows().map((r) => cells(r)[0])).toEqual(['Agent (agent)', '문서 분석 (document_analysis)', 'RAG 답변 (rag_answer)']));
    expect(usageCalls(service).map((q) => q.group_by)).toEqual(['day', 'provider_model', 'feature_code']);
  });

  it('22. KST day boundary (UTC 14:59 vs 15:00)', async () => {
    setup('/admin/ai-usage', mock({ usage: [at('2026-11-08T14:59:59.999Z'), at('2026-11-08T15:00:00.000Z')] }));
    await screen.findByRole('table');
    expect(rows().map((r) => cells(r)[0])).toEqual(['2026-11-08 (KST)', '2026-11-09 (KST)']);
  });

  it('23·24·29. USD, unverified warning and exact server values (no recalculation)', async () => {
    const result: AiUsageResult = { costStatus: 'unverified', source: 'api', buckets: [
      { key: '2026-11-08', request_count: 3, input_tokens: 1_234_567, output_tokens: 7, estimated_cost_usd: 0.300001 },
      { key: '2026-11-09', request_count: 1, input_tokens: 1, output_tokens: 1, estimated_cost_usd: 0 },
    ] };
    setup('/admin/ai-usage', { listEvents: () => Promise.reject(new Error('unused')), getUsage: () => Promise.resolve(result) });
    await screen.findByRole('table');
    expect(cells(rows()[0]!)).toEqual(['2026-11-08 (KST)', '3', '1,234,567', '7', '$0.300001미검증']);
    expect(cells(rows()[1]!)[4]).toBe('$0.00미검증 무료로 확인된 값 아님');
    expect(screen.getByRole('alert')).toHaveTextContent(COST_WARNING);
    expect(screen.getByLabelText('기간 합계')).toHaveTextContent('서버 미제공');
    expect(screen.queryByText('$0.300001', { exact: false, selector: 'dd' })).not.toBeInTheDocument();
    expect(screen.queryByText('표시 중: 가상 데이터(Mock)')).not.toBeInTheDocument();
  });

  it('24b. missing cost status header is still shown as unverified', async () => {
    setup('/admin/ai-usage', { listEvents: () => Promise.reject(new Error('unused')),
      getUsage: () => Promise.resolve({ costStatus: 'unknown', source: 'api', buckets: [] }) });
    expect(await screen.findByRole('alert')).toHaveTextContent('검증되지 않은 것으로 표시');
    expect(document.body.textContent).not.toMatch(/검증 완료|확정 금액|청구 금액:/);
  });

  it('25. no usage records is distinct from unverified cost', async () => {
    setup('/admin/ai-usage', mock({ usage: [] }));
    expect(await screen.findByText('집계된 사용 기록 없음')).toBeInTheDocument();
    expect(screen.getByText(/비용이 0원이라는 뜻은 아닙니다/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(COST_WARNING);
  });

  it('27. invalid period is rejected without a request', async () => {
    const service = setup('/admin/ai-usage', mock());
    await screen.findByRole('table');
    set(/^시작일/, '2026-11-09'); set(/^종료일/, '2026-11-01');
    click('조회');
    expect(screen.getAllByRole('alert').some((a) => a.textContent?.includes('시작일은 종료일보다 늦을 수 없습니다'))).toBe(true);
    expect(usageCalls(service)).toHaveLength(1);
  });

  it('28. API error and retry', async () => {
    const service = mock();
    service.failNext(new ApiError(503, '/v1/admin/ai-usage', undefined, 'DEPENDENCY_UNAVAILABLE'));
    setup('/admin/ai-usage', service);
    expect(await screen.findByText(/잠시 사용할 수 없습니다/)).toBeInTheDocument();
    click('다시 시도');
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it('withdrawn-user rows are included and no identity is shown (30b)', async () => {
    setup('/admin/ai-usage', mock({ usage: [at('2026-11-08T01:00:00Z', { user: 'withdrawn' }), at('2026-11-08T02:00:00Z')] }));
    await screen.findByRole('table');
    expect(cells(rows()[0]!)[1]).toBe('2');
    expect(document.body.textContent).not.toMatch(/withdrawn|active|@|[0-9a-f]{8}-[0-9a-f]{4}/);
  });

  it('a late usage response for an old query is ignored', async () => {
    const first = deferred<AiUsageResult>();
    let n = 0;
    setup('/admin/ai-usage', { listEvents: () => Promise.reject(new Error('unused')), getUsage: () => (n++ === 0 ? first.promise
      : Promise.resolve({ costStatus: 'unverified', source: 'api', buckets: [{ key: 'fresh-model', request_count: 1, input_tokens: 1, output_tokens: 1, estimated_cost_usd: 0.1 }] })) });
    set(/^집계 단위/, 'provider_model'); click('조회');
    expect(await screen.findByText('fresh-model')).toBeInTheDocument();
    first.resolve({ costStatus: 'unverified', source: 'api', buckets: [{ key: '2026-11-01', request_count: 9, input_tokens: 9, output_tokens: 9, estimated_cost_usd: 9 }] });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText('2026-11-01 (KST)')).not.toBeInTheDocument();
  });
});

describe('real API source (service.source === "api")', () => {
  const real: AdminAuditService = {
    source: 'api',
    listEvents: () => Promise.resolve({ items: [], next_cursor: null }),
    getUsage: () => Promise.resolve({ costStatus: 'unverified', source: 'api', buckets: [] }),
  };

  it.each(['/admin/audit-events', '/admin/ai-usage'] as const)('%s does not claim to be mock data', async (path) => {
    setup(path, real);
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('읽기 전용');
    expect(screen.getByRole('note')).not.toHaveTextContent('가상 데이터(Mock)');
    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument());
    expect(screen.queryByText('표시 중: 가상 데이터(Mock)')).not.toBeInTheDocument();
  });
});
