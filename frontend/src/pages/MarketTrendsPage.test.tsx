import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import type { MarketPoint, MarketTrend } from '../api/marketTrends';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { routes } from '../routes';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { MarketTrendsPage } from './MarketTrendsPage';
import { MARKET_DISCLAIMER } from './marketTrendFormat';

// 화면 테스트는 T67 응답 모양(PR #174 MarketTrend)의 가상 응답으로 처리한다. 실제 Backend·Staging 검증은 아니다.
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

const ROLE = { job_role_id: '00000000-0000-4000-8000-0000000000b1', code: 'BACKEND_ENGINEER', name: '백엔드 개발자' };
const PYTHON = { skill_id: '00000000-0000-4000-8000-0000000000c1', code: 'PYTHON', name: 'Python' };
const OBS: MarketPoint[] = [
  { date: '2026-08-24', value: 12 }, { date: '2026-08-31', value: 0 }, { date: '2026-09-14', value: 1580 },
];

const trendOf = (over: Partial<MarketTrend> = {}): MarketTrend => ({
  metric_code: 'posting_count', unit: 'count', period: 'week', from: '2026-08-19', to: '2026-11-10',
  source: { code: 'synthetic_src', name: '합성 출처' }, job_role: null, skill: null, observations: OBS,
  // 화면은 예측값을 쓰지 않는다: 이 값이 보이면 실패
  forecasts: [{ date: '2026-11-16', value: 98765, lower_bound: 1, upper_bound: 2 }],
  forecast_model: { model_code: 'baseline', version: 'v0', kind: 'rule' },
  ...over,
});

type TrendImpl = (path: string) => Promise<unknown>;
const transport = (trend: TrendImpl) => vi.fn<RequestFn>(async (path) => {
  if (path.startsWith('/v1/job-roles')) return { items: [ROLE], next_cursor: null };
  if (path.startsWith('/v1/skills')) return { items: [PYTHON] };
  if (path.startsWith('/v1/market-trends')) return trend(path);
  throw new ApiError(404, path);
});

const trendCalls = (request: ReturnType<typeof transport>) =>
  request.mock.calls.map(([path]) => path).filter((path) => path.startsWith('/v1/market-trends'));
const lastQuery = (request: ReturnType<typeof transport>) =>
  new URLSearchParams(trendCalls(request).at(-1)!.split('?')[1]);

function renderPage(trend: TrendImpl = async () => trendOf()) {
  const request = transport(trend);
  const view = render(<WithApi request={request}><MarketTrendsPage /></WithApi>);
  return { request, ...view };
}

const tableRows = async () => {
  const table = await screen.findByRole('table');
  return within(table).getAllByRole('row').slice(1).map((row) =>
    within(row).getAllByRole('cell').map((cell) => cell.textContent));
};

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-11-10T03:00:00Z')); // 2026-11-10 12:00 KST
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
});

describe('MarketTrendsPage (UI-024) — rendering and chart/table parity', () => {
  it('requests the default query and shows source, period basis and the disclaimer', async () => {
    const { request } = renderPage();
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(Object.fromEntries(lastQuery(request))).toEqual({
      metric_code: 'posting_count', from: '2026-08-19', to: '2026-11-10', period: 'week',
    });
    expect(screen.getByRole('note')).toHaveTextContent(MARKET_DISCLAIMER);
    const basis = screen.getByLabelText('데이터 기준');
    expect(basis).toHaveTextContent('합성 출처 (synthetic_src)');
    expect(basis).toHaveTextContent('2026-08-19 ~ 2026-11-10 · 주 단위 (KST)');
    expect(basis).toHaveTextContent('전체 시장');
    expect(basis).toHaveTextContent('기준 시점 (마지막 관측 구간)2026-09-14 주');
    expect(screen.getByLabelText('지표 정의')).toHaveTextContent('새로 게시된 공고 수');
  });

  it('graph and table use the same observations: same dates, same values, no zero-filled gaps, no forecasts', async () => {
    const { container } = renderPage();
    expect(await tableRows()).toEqual([
      ['2026-08-24 주', '12건'],
      ['2026-08-31 주', '0건'],
      ['2026-09-14 주', '1,580건'],
    ]);
    const markers = [...container.querySelectorAll('circle[data-date]')]
      .map((c) => ({ date: c.getAttribute('data-date'), value: Number(c.getAttribute('data-value')) }));
    expect(markers).toEqual(OBS); // API 원본 값 그대로
    // 08-24·08-31 은 이어지고, 09-07 은 관측이 없어 선이 끊긴다(0으로 채우지 않음). 09-14 는 홀로 찍힌 점.
    expect(container.querySelectorAll('.market-chart-series path')).toHaveLength(1);
    expect(container.querySelectorAll('circle[data-date="2026-09-07"]')).toHaveLength(0);
    expect(screen.queryByText(/98,?765/)).not.toBeInTheDocument();

    // 키보드로 읽은 그래프 값 = 표의 값
    const chart = screen.getByRole('group', { name: /그래프/ });
    chart.focus();
    const readout = screen.getByTestId('market-chart-readout');
    const fromChart: string[] = [];
    for (let i = 0; i < OBS.length; i += 1) {
      fireEvent.keyDown(chart, { key: 'ArrowRight' });
      fromChart.push(readout.textContent ?? '');
    }
    const rows = await tableRows();
    expect(fromChart).toEqual(rows.map(([label, value]) => `${label}: ${value}`));
    fireEvent.keyDown(chart, { key: 'Home' });
    expect(readout).toHaveTextContent('2026-08-24 주: 12건');
    fireEvent.keyDown(chart, { key: 'End' });
    expect(readout).toHaveTextContent('2026-09-14 주: 1,580건');
    fireEvent.keyDown(chart, { key: 'Escape' });
    expect(readout).toHaveTextContent('');
  });
});

describe('filters', () => {
  it('role, period and dates change the request', async () => {
    const { request } = renderPage(async (path) => {
      const q = new URLSearchParams(path.split('?')[1]);
      return trendOf({ period: q.get('period') as MarketTrend['period'], from: q.get('from')!, to: q.get('to')!,
        job_role: q.get('job_role_id') ? ROLE : null });
    });
    await screen.findByRole('table');
    await screen.findByRole('option', { name: ROLE.name });
    fireEvent.change(screen.getByLabelText('직무'), { target: { value: ROLE.job_role_id } });
    await waitFor(() => expect(lastQuery(request).get('job_role_id')).toBe(ROLE.job_role_id));
    expect(await screen.findByLabelText('데이터 기준')).toHaveTextContent('백엔드 개발자');

    fireEvent.click(screen.getByRole('button', { name: '월 단위' }));
    expect(screen.getByRole('button', { name: '월 단위' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(lastQuery(request).get('period')).toBe('month'));

    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '2026-01-01' } });
    await waitFor(() => expect(lastQuery(request).get('from')).toBe('2026-01-01'));
    expect(lastQuery(request).get('to')).toBe('2026-11-10');
    expect(lastQuery(request).get('skill_id')).toBeNull();
  });

  it('skill_demand_share waits for a skill, then sends skill_id and shows percentages', async () => {
    const { request } = renderPage(async (path) => (path.includes('skill_demand_share')
      ? trendOf({ metric_code: 'skill_demand_share', unit: 'ratio', skill: PYTHON,
        observations: [{ date: '2026-10-05', value: 0.7143 }, { date: '2026-10-12', value: 0.2857 }] })
      : trendOf()));
    await screen.findByRole('table');
    const before = trendCalls(request).length;

    fireEvent.click(screen.getByRole('button', { name: '기술 요구 비율' }));
    expect(await screen.findByText('기술을 선택해 주세요')).toBeInTheDocument();
    expect(trendCalls(request)).toHaveLength(before); // 기술 없이 요청하지 않음
    expect(screen.getByLabelText('지표 정의')).toHaveTextContent('0~1 비율');

    fireEvent.change(screen.getByLabelText('기술 검색'), { target: { value: 'Py' } });
    await screen.findByRole('option', { name: 'Python' });
    fireEvent.change(screen.getByLabelText('기술 (필수)'), { target: { value: PYTHON.skill_id } });
    await waitFor(() => expect(lastQuery(request).get('skill_id')).toBe(PYTHON.skill_id));
    expect(lastQuery(request).get('metric_code')).toBe('skill_demand_share');
    expect((await tableRows()).map((row) => row[1])).toEqual(['71.43%', '28.57%']);
    expect(screen.getByLabelText('데이터 기준')).toHaveTextContent('비율 (화면은 %)');
  });

  it('invalid dates show an inline error and send no request', async () => {
    const { request } = renderPage();
    await screen.findByRole('table');
    const before = trendCalls(request).length;
    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '2026-12-01' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('시작일은 종료일보다 늦을 수 없습니다');
    expect(screen.getByLabelText('시작일')).toHaveAttribute('aria-invalid', 'true');

    // 계속 잘못된 조건만 거친다: 일 단위로 바꾼 뒤 시작일을 366일 넘게 당긴다.
    fireEvent.click(screen.getByRole('button', { name: '일 단위' }));
    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: '2025-01-01' } });
    expect(screen.getByRole('alert')).toHaveTextContent('최대 366일');
    fireEvent.change(screen.getByLabelText('종료일'), { target: { value: '' } });
    expect(screen.getByRole('alert')).toHaveTextContent('모두 입력');
    expect(trendCalls(request)).toHaveLength(before);
  });
});

describe('states', () => {
  it('empty data: explains that no observation is not zero and shows no table', async () => {
    renderPage(async () => trendOf({ observations: [], source: null }));
    expect(await screen.findByText('선택한 조건의 관측 데이터가 없습니다')).toBeInTheDocument();
    expect(screen.getByText(/0건과 다릅니다/)).toBeInTheDocument();
    expect(screen.getByLabelText('데이터 기준')).toHaveTextContent('출처관측값 없음');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /그래프/ })).not.toBeInTheDocument();
  });

  it('server error: alert with retry, then data', async () => {
    let fail = true;
    renderPage(async () => {
      if (fail) throw new ApiError(503, '/v1/market-trends', 'db down', 'DEPENDENCY_UNAVAILABLE');
      return trendOf();
    });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('잠시 후 다시 시도');
    expect(alert).not.toHaveTextContent('db down');
    fail = false;
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it('401: asks to sign in again and offers no retry', async () => {
    renderPage(async () => { throw new ApiError(401, '/v1/market-trends', undefined, 'UNAUTHENTICATED'); });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('로그인이 필요합니다');
    expect(within(alert).queryByRole('button')).not.toBeInTheDocument();
  });

  it.each([
    [404, 'NOT_FOUND', '찾을 수 없습니다'],
    [422, 'VALIDATION_FAILED', '조회 조건을 확인해 주세요'],
    [0, undefined, '네트워크 연결'],
  ])('%i shows its own message', async (status, code, text) => {
    renderPage(async () => { throw new ApiError(status, '/v1/market-trends', undefined, code); });
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });

  it('race: a late response for an old filter never replaces the newer one', async () => {
    let releaseWeek: (value: MarketTrend) => void = () => undefined;
    renderPage((path) => (path.includes('period=week')
      ? new Promise((resolve) => { releaseWeek = resolve; })
      : Promise.resolve(trendOf({ period: 'month', observations: [{ date: '2026-09-01', value: 77 }] }))));
    await waitFor(() => expect(screen.getByText('채용시장 추세를 불러오는 중입니다')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '월 단위' }));
    expect(await tableRows()).toEqual([['2026년 9월', '77건']]);
    await act(async () => { releaseWeek(trendOf()); });
    expect(await tableRows()).toEqual([['2026년 9월', '77건']]);
  });
});

describe('accessibility and mobile', () => {
  it('labelled controls, focusable chart with a summary, captioned table', async () => {
    renderPage();
    await screen.findByRole('table');
    for (const name of ['시작일', '종료일', '직무']) expect(screen.getByLabelText(name)).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '관측 지표' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '집계 단위' })).toBeInTheDocument();
    const chart = screen.getByRole('group', { name: /좌우 화살표/ });
    expect(chart).toHaveAttribute('tabindex', '0');
    expect(within(chart).getByRole('img')).toHaveAccessibleName(
      '전체 시장 신규 게시 공고 수 (주 단위): 3개 구간 관측, 최솟값 0건, 최댓값 1,580건');
    expect(screen.getByRole('table')).toHaveAccessibleName('전체 시장 신규 게시 공고 수 (주 단위) 관측값');
    expect(screen.getByRole('region', { name: /표 영역/ })).toHaveAttribute('tabindex', '0');
  });

  it('redraws the chart at phone width without overflowing labels', async () => {
    class FakeResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe() { this.callback([{ contentRect: { width: 343 } } as ResizeObserverEntry], this as unknown as ResizeObserver); }
      disconnect() { /* noop */ }
      unobserve() { /* noop */ }
    }
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
    const { container } = renderPage();
    await screen.findByRole('table');
    const svg = container.querySelector('.market-chart svg')!;
    expect(svg).toHaveAttribute('width', '343');
    const xLabels = [...svg.querySelectorAll('.market-chart-grid > text')];
    expect(xLabels.length).toBeLessThanOrEqual(3);
    for (const circle of svg.querySelectorAll('circle')) {
      expect(Number(circle.getAttribute('cx'))).toBeLessThanOrEqual(343);
    }
  });
});

describe('route /market-trends (mock mode, through login)', () => {
  it('requires login, is in the main menu and renders the synthetic mock series', async () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/market-trends'] });
    render(<RouterProvider router={router} />);
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    expect(await screen.findByRole('heading', { name: '채용시장 추세' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '채용시장 추세' })).toHaveAttribute('href', '/market-trends');
    expect(await screen.findByRole('table', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByLabelText('데이터 기준')).toHaveTextContent('합성 Mock 출처');
  });
});
