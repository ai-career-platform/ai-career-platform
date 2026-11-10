/// <reference types="node" />
// T68 opt-in real Backend E2E: market_observations (DB) -> T67 GET /api/v1/market-trends -> T68 graph and table.
// Runs only when T68_REAL_API_ORIGIN points to a loopback Backend and T68_DB_SNAPSHOT is a JSON file made by a
// read-only SELECT of the same database (see frontend/docs/T68_MARKET_TRENDS_DASHBOARD.md). It signs up synthetic
// users, so never point it at Staging or any shared database.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { env as processEnv } from 'node:process';
import { beforeAll, describe, expect, it } from 'vitest';
import { createHttpClient, type HttpClient } from '../api/http';
import { marketTrendsApi, type MarketTrend, type MarketTrendQuery } from '../api/marketTrends';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { MarketTrendsPage } from './MarketTrendsPage';
import { formatMetricValue, periodLabel } from './marketTrendFormat';

const origin = processEnv.T68_REAL_API_ORIGIN;
const snapshotPath = processEnv.T68_DB_SNAPSHOT;
const STAMP = Date.now().toString(36);
const CONSENTS = [
  { policy_code: 'terms', policy_version: '2026-11', granted: true },
  { policy_code: 'privacy', policy_version: '2026-11', granted: true },
];

type DbRow = {
  period: string; metric_code: string; date: string; value: number; job_role_id: string | null; role_code: string | null;
  role_name: string | null; skill_id: string | null; skill_code: string | null; skill_name: string | null;
  source_code: string; source_name: string;
};
type Snapshot = { observations: DbRow[]; empty_role: { job_role_id: string; name: string } };

async function signUp(name: string): Promise<HttpClient> {
  const anonymous = createHttpClient({ baseUrl: `${origin}/api` });
  const { access_token: token } = await anonymous.request<{ access_token: string }>('/v1/auth/signup', {
    method: 'POST', token: null,
    body: { email: `t68-${name}-${STAMP}@example.invalid`, password: 'synthetic-e2e-password-1', display_name: `T68 ${name}`, consents: CONSENTS },
  });
  return createHttpClient({ baseUrl: `${origin}/api`, getToken: () => token });
}

type Case = { name: string; period: 'week' | 'month'; metric: 'posting_count' | 'skill_demand_share'; from: string; to: string;
  role: string | null; skill: string | null };
// 최소 3개 조건 조합 (작업지시서 STEP 06)
const CASES: Case[] = [
  { name: '전체 직무 주간 공고 수', period: 'week', metric: 'posting_count', from: '2026-10-05', to: '2026-11-08', role: null, skill: null },
  { name: '백엔드 직무 주간 공고 수', period: 'week', metric: 'posting_count', from: '2026-10-05', to: '2026-11-08', role: 'BACKEND_ENGINEER', skill: null },
  { name: '전체 시장 PYTHON 주간 기술 요구 비율', period: 'week', metric: 'skill_demand_share', from: '2026-10-05', to: '2026-11-08', role: null, skill: 'PYTHON' },
  { name: '전체 직무 월간 공고 수', period: 'month', metric: 'posting_count', from: '2026-10-01', to: '2026-10-31', role: null, skill: null },
  { name: '백엔드 직무 월간 JAVA 기술 요구 비율', period: 'month', metric: 'skill_demand_share', from: '2026-10-01', to: '2026-10-31', role: 'BACKEND_ENGINEER', skill: 'JAVA' },
];

describe.skipIf(!origin || !snapshotPath)('T68 real Backend E2E (DB -> T67 API -> T68 UI, disposable PostgreSQL only)', () => {
  let snapshot: Snapshot;
  let http: HttpClient;

  beforeAll(async () => {
    const url = new URL(origin!);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.protocol !== 'http:' || url.pathname !== '/') {
      throw new Error('T68 E2E requires a loopback http Backend origin');
    }
    snapshot = JSON.parse(readFileSync(snapshotPath!, 'utf8')) as Snapshot;
    http = await signUp('viewer');
  });

  const dbRows = (c: Case) => snapshot.observations.filter((r) => r.period === c.period && r.metric_code === c.metric
    && r.role_code === c.role && r.skill_code === c.skill && r.date >= c.from && r.date <= c.to);
  const queryOf = (c: Case): MarketTrendQuery => {
    const rows = snapshot.observations.filter((r) => r.role_code === c.role && r.skill_code === c.skill);
    return { metric_code: c.metric, period: c.period, from: c.from, to: c.to,
      job_role_id: c.role ? rows[0]!.job_role_id : null, skill_id: c.skill ? rows[0]!.skill_id : null };
  };

  it.each(CASES)('$name: API values equal DB rows (date, value, unit, source, order)', async (c) => {
    const rows = dbRows(c);
    expect(rows.length).toBeGreaterThan(0);
    const trend = await marketTrendsApi(http).get(queryOf(c));
    expect(trend.observations.map(({ date, value }) => ({ date, value }))).toEqual(rows.map(({ date, value }) => ({ date, value })));
    expect(trend.unit).toBe(c.metric === 'posting_count' ? 'count' : 'ratio');
    expect(trend.period).toBe(c.period);
    expect(trend.source).toEqual({ code: rows[0]!.source_code, name: rows[0]!.source_name });
    expect(trend.job_role?.code ?? null).toBe(c.role);
    expect(trend.skill?.code ?? null).toBe(c.skill);
  });

  it.each(CASES)('$name: graph markers and table rows show exactly the DB values', async (c) => {
    const rows = dbRows(c);
    const request: RequestFn = (path, init) => http.request(path, init);
    const { container } = render(<WithApi request={request}><MarketTrendsPage /></WithApi>);
    if (c.metric === 'skill_demand_share') fireEvent.click(screen.getByRole('button', { name: '기술 요구 비율' }));
    fireEvent.click(screen.getByRole('button', { name: c.period === 'week' ? '주 단위' : '월 단위' }));
    fireEvent.change(screen.getByLabelText('시작일'), { target: { value: c.from } });
    fireEvent.change(screen.getByLabelText('종료일'), { target: { value: c.to } });
    if (c.role) {
      const roleName = rows[0]!.role_name!;
      await screen.findByRole('option', { name: roleName });
      fireEvent.change(screen.getByLabelText('직무'), { target: { value: rows[0]!.job_role_id } });
    }
    if (c.skill) {
      fireEvent.change(screen.getByLabelText('기술 검색'), { target: { value: rows[0]!.skill_name } });
      await screen.findByRole('option', { name: rows[0]!.skill_name! }, { timeout: 3000 });
      fireEvent.change(screen.getByLabelText('기술 (필수)'), { target: { value: rows[0]!.skill_id } });
    }
    const unit = c.metric === 'posting_count' ? 'count' : 'ratio';
    await waitFor(() => {
      const table = screen.getByRole('table');
      const cells = within(table).getAllByRole('row').slice(1).map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent));
      expect(cells).toEqual(rows.map((r) => [periodLabel(r.date, c.period), formatMetricValue(r.value, unit)]));
    }, { timeout: 5000 });
    const markers = [...container.querySelectorAll('circle[data-date]')]
      .map((m) => ({ date: m.getAttribute('data-date'), value: Number(m.getAttribute('data-value')) }));
    expect(markers).toEqual(rows.map(({ date, value }) => ({ date, value })));
    expect(screen.getByLabelText('데이터 기준')).toHaveTextContent(`${rows[0]!.source_name} (${rows[0]!.source_code})`);
  });

  it('empty series is 200 with no observations and the UI shows the empty state', async () => {
    const trend: MarketTrend = await marketTrendsApi(http).get({ metric_code: 'posting_count', period: 'week',
      from: '2026-10-05', to: '2026-11-08', job_role_id: snapshot.empty_role.job_role_id });
    expect(trend.observations).toEqual([]);
    expect(trend.source).toBeNull();
    const request: RequestFn = (path, init) => http.request(path, init);
    render(<WithApi request={request}><MarketTrendsPage /></WithApi>);
    await screen.findByRole('option', { name: snapshot.empty_role.name });
    fireEvent.change(screen.getByLabelText('직무'), { target: { value: snapshot.empty_role.job_role_id } });
    expect(await screen.findByText('선택한 조건의 관측 데이터가 없습니다', {}, { timeout: 5000 })).toBeInTheDocument();
  });

  it('enforces 404 / 422 / 401 on the real API', async () => {
    const api = marketTrendsApi(http);
    const base: MarketTrendQuery = { metric_code: 'posting_count', period: 'week', from: '2026-10-05', to: '2026-11-08' };
    const missing = '00000000-0000-4000-8000-00000000dead';
    await expect(api.get({ ...base, job_role_id: missing })).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
    await expect(api.get({ ...base, metric_code: 'skill_demand_share', skill_id: missing })).rejects.toMatchObject({ status: 404 });
    await expect(api.get({ ...base, source: 'no_such_source' })).rejects.toMatchObject({ status: 404 });
    await expect(api.get({ ...base, from: '2026-11-08', to: '2026-10-05' })).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(api.get({ ...base, period: 'day', from: '2025-01-01', to: '2026-11-08' })).rejects.toMatchObject({ status: 422 });
    await expect(api.get({ ...base, metric_code: 'skill_demand_share' })).rejects.toMatchObject({ status: 422 });
    await expect(api.get({ ...base, from: 'not-a-date' })).rejects.toMatchObject({ status: 422 });
    await expect(marketTrendsApi(createHttpClient({ baseUrl: `${origin}/api` })).get(base)).rejects.toMatchObject({ status: 401 });
  });
});
