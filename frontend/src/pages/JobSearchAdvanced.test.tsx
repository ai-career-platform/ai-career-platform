/**
 * T100 채용공고 고급 검색 — URL 상태, Mock Adapter(T98 수용 사례와 대조), 화면(필터·URL·결과 일치, 뒤로가기, 0건, 키보드).
 * 화면 시험 대부분은 Mock Adapter 를 주입합니다. Mock 모드가 아닐 때 실제 HttpClient 로 보내는 요청(쿼리·정렬·커서)도 따로 확인합니다.
 * 실제 서버(T99)는 같은 T98 JSON 으로 별도 검증됩니다.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildQuery } from '../api/http';
import { env } from '../config/env';
import type { AdvancedJobQuery } from '../api/jobSearch';
import { createMockJobSearchService, REGION_ALIASES, type MockPosting } from '../mocks/jobSearch';
import { WithApi } from '../test/WithApi';
import { JobPostingsPage } from './JobPostingsPage';
import { normalizeSearch, parseSearch, serializeSearch, toApiQuery } from './jobSearchUrl';

type Case = { id: string; why?: string; params: Record<string, unknown>; expect?: string[]; status?: number; page_size?: number };
const ROOT = resolve(cwd(), '..');
const T98 = JSON.parse(readFileSync(resolve(ROOT, 'docs/search/t98_acceptance_cases.json'), 'utf8')) as {
  now: string; companies: Record<string, { name: string }>; job_roles: Record<string, string>;
  postings: Record<string, { title: string; company: string; role: string | null; employment_type: string | null;
    location_text: string | null; published_at: string | null; expires_at: string | null; status: MockPosting['status'] }>;
  cases: Case[]; invalid: Case[]; pagination: Case[];
};
const CONTRACT = readFileSync(resolve(ROOT, 'docs/search/T98_ADVANCED_SEARCH_CONTRACT.md'), 'utf8');

/** T99 PG 시험과 같은 합성 ID 규칙: p01 → …0000 00000001, c1 → …c000 00000001, r1 → …a000 00000001 */
const uid = (key: string) => {
  const prefix = { p: '0000', c: 'c000', r: 'a000' }[key[0] as 'p' | 'c' | 'r'];
  return `00000000-0000-4000-8000-${prefix}${String(Number(key.slice(1))).padStart(8, '0')}`;
};
const POSTINGS: MockPosting[] = Object.entries(T98.postings).map(([key, p]) => ({
  job_posting_id: uid(key), title: p.title, status: p.status,
  company: { company_id: uid(p.company), name: T98.companies[p.company]!.name },
  job_role: p.role ? { job_role_id: uid(p.role), code: T98.job_roles[p.role]!, name: T98.job_roles[p.role]! } : null,
  employment_type: p.employment_type, location_text: p.location_text, published_at: p.published_at, expires_at: p.expires_at,
}));
const keyOf = Object.fromEntries(Object.keys(T98.postings).map((k) => [uid(k), k]));
const keys = (items: Array<{ job_posting_id: string }>) => items.map((i) => keyOf[i.job_posting_id] ?? '?');
const NOW = () => new Date(T98.now);

function apiQuery(params: Record<string, unknown>): AdvancedJobQuery {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (k.startsWith('_')) continue;
    if (k === 'q' && typeof v === 'object' && v) { const r = v as { repeat: string; times: number }; out.q = r.repeat.repeat(r.times); continue; }
    out[k] = Array.isArray(v) && (k === 'company_id' || k === 'job_role_id') ? v.map((x) => uid(String(x))) : v;
  }
  return out as AdvancedJobQuery;
}

describe('URL state (T98 §6)', () => {
  it('round-trips, ignores order and duplicates, and omits defaults', () => {
    const a = parseSearch(new URLSearchParams('region=gyeonggi&region=seoul&employment_type=contract&employment_type=contract&q=%20백엔드%20%20개발%20'));
    const b = parseSearch(new URLSearchParams('q=백엔드 개발&employment_type=contract&region=seoul&region=gyeonggi'));
    expect(a).toEqual(b);
    expect(serializeSearch(a).toString()).toBe(serializeSearch(b).toString());
    expect(serializeSearch(normalizeSearch(a)).toString())
      .toBe('q=%EB%B0%B1%EC%97%94%EB%93%9C+%EA%B0%9C%EB%B0%9C&employment_type=contract&region=seoul&region=gyeonggi');
    expect(serializeSearch(parseSearch(new URLSearchParams('sort=-published_at&include_closed=false'))).toString()).toBe('');
  });

  it('drops unknown keys and invalid values, caps lists, and never carries private data or a cursor', () => {
    const s = parseSearch(new URLSearchParams(
      'email=a@b.c&user_id=1&cursor=abc&employment_type=freelance&region=tokyo&posted_within=2d&company_id=not-a-uuid'
      + '&region=seoul&region=busan&region=daegu&region=incheon&region=gwangju&region=daejeon&sort=salary'));
    const url = serializeSearch(s).toString();
    expect(url).toBe('region=seoul&region=busan&region=daegu&region=incheon&region=gwangju');
    expect(url).not.toMatch(/email|user|cursor|freelance|tokyo|2d|salary/);
  });

  it('reads old T24 links (company, role, closed, order)', () => {
    const s = parseSearch(new URLSearchParams(`company=${uid('c1')}&role=${uid('r1')}&closed=1&order=expires`));
    expect(s).toMatchObject({ company_id: [uid('c1')], job_role_id: [uid('r1')], include_closed: true, sort: 'expires_at' });
  });

  it('API query repeats array keys (buildQuery)', () => {
    const q = toApiQuery(parseSearch(new URLSearchParams('region=seoul&region=jeju&employment_type=intern')), 20, null);
    expect(buildQuery(q)).toBe('?employment_type=intern&region=seoul&region=jeju&include_closed=false&sort=-published_at&limit=20');
  });
});

describe('mock adapter matches the T98 acceptance cases', () => {
  const service = () => createMockJobSearchService({ postings: POSTINGS, now: NOW });

  it.each(T98.cases.map((c) => [c.id, c] as const))('%s', async (_id, c) => {
    const page = await service().list({ ...apiQuery(c.params), limit: 100 });
    expect(keys(page.items)).toEqual(c.expect);
  });

  it.each(T98.invalid.map((c) => [c.id, c] as const))('%s is rejected with 422', async (_id, c) => {
    await expect(service().list(apiQuery(c.params))).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
  });

  it('pages without duplicates and binds the cursor to the filters', async () => {
    const svc = service();
    for (const c of T98.pagination) {
      const full = keys((await svc.list({ ...apiQuery(c.params), limit: 100 })).items);
      const seen: string[] = [];
      let cursor: string | null = null;
      do {
        const page = await svc.list({ ...apiQuery(c.params), limit: c.page_size, cursor });
        seen.push(...keys(page.items));
        cursor = page.next_cursor;
      } while (cursor);
      expect(seen).toEqual(full);
    }
    const first = await svc.list({ employment_type: ['full_time', 'contract'], limit: 1 });
    await expect(svc.list({ employment_type: ['contract', 'full_time'], limit: 1, cursor: first.next_cursor }))
      .resolves.toBeTruthy();
    await expect(svc.list({ employment_type: ['contract'], limit: 1, cursor: first.next_cursor }))
      .rejects.toMatchObject({ status: 400, code: 'INVALID_CURSOR' });
  });

  it('region aliases equal the T98 §4 table', () => {
    const section = CONTRACT.split('## 4.')[1]!.split('\n## ')[0]!;
    const table = Object.fromEntries([...section.matchAll(/^\| `([a-z]+)` \| [^|]+ \| ([^|]+) \|/gm)]
      .map((m) => [m[1], m[2]!.split(',').map((a) => a.trim())]));
    expect(REGION_ALIASES).toEqual(table);
  });
});

// ---------------------------------------------------------------- 화면
const get = vi.fn<(path: string) => Promise<unknown>>();
function serveCatalog() {
  get.mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/companies?')) {
      return { items: Object.entries(T98.companies).map(([k, c]) => ({ company_id: uid(k), name: c.name })), next_cursor: null };
    }
    if (path.startsWith('/v1/job-roles?')) {
      return { items: Object.entries(T98.job_roles).map(([k, code]) => ({ job_role_id: uid(k), code, name: code })), next_cursor: null };
    }
    if (path.startsWith('/v1/job-postings')) throw new Error(`advanced mode must not call the T18 list: ${path}`);
    throw new Error(`unexpected ${path}`);
  });
}
function Where() { return <output data-testid="where">{useLocation().search}</output>; }
function open(url: string, svc = createMockJobSearchService({ postings: POSTINGS, now: NOW })) {
  const router = createMemoryRouter([{ path: '/job-postings', element: <><JobPostingsPage advanced searchService={svc} /><Where /></> }],
    { initialEntries: [url] });
  render(<WithApi request={(path) => get(path)}><RouterProvider router={router} /></WithApi>);
  return { router, svc };
}
const results = () => within(screen.getByRole('list', { name: '채용공고 검색 결과' })).getAllByRole('button')
  .map((b) => b.getAttribute('aria-label')!.replace(' 상세 보기', ''));
const titles = (ids: string[]) => ids.map((k) => T98.postings[k]!.title);
const where = () => screen.getByTestId('where').textContent;

beforeEach(() => { get.mockReset(); serveCatalog(); });

describe('advanced search screen (mock flag)', () => {
  it('filter → URL → API → results agree, and filters combine with AND', async () => {
    const { svc } = open('/job-postings');
    await waitFor(() => expect(results()).toEqual(titles(T98.cases[0]!.expect!)));
    fireEvent.click(screen.getByRole('checkbox', { name: '정규직' }));
    await waitFor(() => expect(where()).toBe('?employment_type=full_time'));
    fireEvent.click(screen.getByText('근무 지역'));
    fireEvent.click(screen.getByRole('checkbox', { name: '서울' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '경기' }));
    fireEvent.change(screen.getByLabelText('공고·기업 검색'), { target: { value: '개발자' } });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));
    await waitFor(() => expect(where()).toBe('?q=%EA%B0%9C%EB%B0%9C%EC%9E%90&employment_type=full_time&region=seoul&region=gyeonggi'));
    const a12 = T98.cases.find((c) => c.id === 'A12')!;
    await waitFor(() => expect(results()).toEqual(titles(a12.expect!)));
    expect(svc.calls.at(-1)).toMatchObject({ q: '개발자', employment_type: ['full_time'], region: ['seoul', 'gyeonggi'] });
    expect(screen.getByText('근무 지역 (2개 선택)')).toBeInTheDocument();
  });

  it('opening a shared URL gives the same results; browser back restores the previous filters', async () => {
    const { router } = open('/job-postings?q=%EB%B2%A0%ED%83%80');
    await waitFor(() => expect(results()).toEqual(titles(T98.cases.find((c) => c.id === 'A02')!.expect!)));
    fireEvent.click(screen.getByRole('checkbox', { name: '파트타임' }));
    await waitFor(() => expect(results()).toEqual(titles(['p05'])));
    fireEvent.change(screen.getByLabelText('게시일'), { target: { value: '7d' } });
    await waitFor(() => expect(where()).toContain('posted_within=7d'));
    await act(() => router.navigate(-1));
    await waitFor(() => expect(where()).toBe('?q=%EB%B2%A0%ED%83%80&employment_type=part_time'));
    expect(screen.getByRole('checkbox', { name: '파트타임' })).toBeChecked();
    expect(screen.getByLabelText('게시일')).toHaveValue('');
    await act(() => router.navigate(-1));
    await waitFor(() => expect(results()).toEqual(titles(['p05', 'p02', 'p09'])));
    expect(screen.getByRole('checkbox', { name: '파트타임' })).not.toBeChecked();
  });

  it('zero results show the empty state; reset clears filters but keeps the sort', async () => {
    open('/job-postings?q=%EC%A1%B4%EC%9E%AC%ED%95%98%EC%A7%80%EC%95%8A%EB%8A%94%EA%B3%B5%EA%B3%A0&employment_type=intern&sort=expires_at');
    expect(await screen.findByText('조건에 맞는 공고가 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색 조건 초기화' }));
    await waitFor(() => expect(where()).toBe('?sort=expires_at'));
    await waitFor(() => expect(results()).toEqual(titles(['p09', 'p03', 'p05', 'p01', 'p02', 'p04', 'p10'])));
    expect(screen.getByRole('button', { name: '조건 초기화' })).toBeDisabled();
  });

  it('invalid URL values are dropped before the API call (no 422 shown to the user)', async () => {
    const { svc } = open('/job-postings?region=tokyo&employment_type=freelance&posted_within=2d&email=a%40b.c');
    await waitFor(() => expect(results()).toEqual(titles(T98.cases[0]!.expect!)));
    expect(svc.calls[0]).toEqual({ include_closed: false, sort: '-published_at', limit: 20, cursor: null });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('caps regions at five (others disabled) and shows a load error with retry', async () => {
    const { svc } = open('/job-postings?region=seoul&region=busan&region=daegu&region=incheon&region=gwangju');
    await screen.findByText('근무 지역 (5개 선택)');
    expect(screen.getByRole('checkbox', { name: '제주' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: '서울' })).toBeEnabled();
    svc.failNext();
    fireEvent.click(screen.getByRole('checkbox', { name: '인턴' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('채용공고를 불러오지 못했습니다');
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(results()).toEqual(titles(['p03'])));            // 부산 인턴
  });

  it('pages through results and restarts at page 1 when a filter changes', async () => {
    open('/job-postings?include_closed=true&sort=expires_at');
    await waitFor(() => expect(results()).toHaveLength(9));
    expect(screen.getByRole('button', { name: '다음' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: '계약직' }));
    await waitFor(() => expect(results()).toEqual(titles(['p07', 'p02'])));
    expect(screen.getByText('1 페이지')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- 실제 API 경로(Mock 모드 아님)
describe('advanced search screen (real API, not mock mode)', () => {
  const posting = (n: number) => ({
    job_posting_id: uid(`p${n}`), title: `공고 ${n}`, status: 'published', company: { company_id: uid('c1'), name: '회사' },
    job_role: null, employment_type: 'full_time', location_text: '서울 강남구', published_at: T98.now, expires_at: null,
  });
  const listCalls = () => get.mock.calls.map(([p]) => p).filter((p) => p.startsWith('/v1/job-postings?'));
  function serveList(impl: (path: string) => unknown) {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith('/v1/companies?') || path.startsWith('/v1/job-roles?')) return { items: [], next_cursor: null };
      if (path.startsWith('/v1/job-postings?')) return impl(path);
      throw new Error(`unexpected ${path}`);
    });
  }
  function openReal(url: string) {
    const router = createMemoryRouter([{ path: '/job-postings', element: <><JobPostingsPage advanced /><Where /></> }],
      { initialEntries: [url] });
    render(<WithApi request={(path) => get(path)}><RouterProvider router={router} /></WithApi>);
    return router;
  }

  it('uses the HttpClient (not the mock adapter) and sends filters and sort as T99 query params', async () => {
    expect(env.mockEnabled).toBe(false);
    serveList(() => ({ items: [posting(1)], next_cursor: null }));
    openReal(`/job-postings?q=%EB%B0%B1%EC%97%94%EB%93%9C&company_id=${uid('c2')}&company_id=${uid('c1')}`
      + '&employment_type=intern&employment_type=full_time&region=jeju&region=seoul&posted_within=7d&include_closed=true&sort=expires_at');
    await waitFor(() => expect(results()).toEqual(['공고 1']));
    expect(listCalls()).toEqual([
      `/v1/job-postings?q=%EB%B0%B1%EC%97%94%EB%93%9C&company_id=${uid('c1')}&company_id=${uid('c2')}`
      + '&employment_type=full_time&employment_type=intern&region=seoul&region=jeju&posted_within=7d'
      + '&include_closed=true&sort=expires_at&limit=20',
    ]);
    expect(screen.getByText('시범')).toBeInTheDocument();                      // Mock 배지 없음
    fireEvent.click(screen.getByRole('checkbox', { name: '계약직' }));
    await waitFor(() => expect(listCalls().at(-1)).toContain('employment_type=full_time&employment_type=contract&employment_type=intern'));
  });

  it('pages with next_cursor, goes back, and restarts at page 1 when a filter changes', async () => {
    serveList((path) => (path.includes('cursor=')
      ? { items: [posting(2)], next_cursor: null }
      : { items: [posting(1)], next_cursor: 'opaque/c+2=' }));
    openReal('/job-postings?region=busan');
    await waitFor(() => expect(results()).toEqual(['공고 1']));
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    await waitFor(() => expect(results()).toEqual(['공고 2']));
    expect(listCalls().at(-1)).toBe('/v1/job-postings?region=busan&include_closed=false&sort=-published_at&limit=20&cursor=opaque%2Fc%2B2%3D');
    expect(screen.getByText('2 페이지')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '이전' }));
    await waitFor(() => expect(results()).toEqual(['공고 1']));
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    await waitFor(() => expect(results()).toEqual(['공고 2']));
    fireEvent.change(screen.getByLabelText('게시일'), { target: { value: '1d' } });
    await waitFor(() => expect(listCalls().at(-1)).toBe('/v1/job-postings?region=busan&posted_within=1d&include_closed=false&sort=-published_at&limit=20'));
    expect(screen.getByText('1 페이지')).toBeInTheDocument();
  });

  it('server flag off: an unfiltered T18 response still renders; a 422/other error shows the retryable error state', async () => {
    let fail = true;
    serveList(() => {
      if (fail) { fail = false; throw Object.assign(new Error('VALIDATION_FAILED'), { status: 422 }); }
      return { items: [posting(3)], next_cursor: null };                     // T18 은 고급 조건을 무시하고 응답
    });
    openReal('/job-postings?employment_type=intern');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('채용공고를 불러오지 못했습니다');
    fireEvent.click(within(alert).getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(results()).toEqual(['공고 3']));
    serveList(() => ({ items: [], next_cursor: null }));
    fireEvent.click(screen.getByRole('checkbox', { name: '정규직' }));
    expect(await screen.findByText('조건에 맞는 공고가 없습니다')).toBeInTheDocument();
  });
});

describe('flag off', () => {
  it('the default route renders the T24 screen without advanced filters', async () => {
    const envText = readFileSync(resolve(cwd(), 'src/config/env.ts'), 'utf8');
    // PM 결정: 고급 검색 UI 는 Mock 전용이 아니라 실제 API 도 씀. 플래그 하나로만 켜지고 기본은 꺼짐.
    expect(envText).toContain("jobSearchAdvancedUi: import.meta.env.VITE_JOB_SEARCH_ADVANCED_UI === 'true',");
    expect(envText).not.toMatch(/jobSearchAdvancedUi:[^\n]*VITE_API_MOCK/);
    expect(env.jobSearchAdvancedUi).toBe(false);
    get.mockImplementation(async (path: string) => (path.startsWith('/v1/job-postings')
      ? { items: [], next_cursor: null } : { items: [], next_cursor: null }));
    const router = createMemoryRouter([{ path: '/job-postings', element: <JobPostingsPage /> }], { initialEntries: ['/job-postings'] });
    render(<WithApi request={(path) => get(path)}><RouterProvider router={router} /></WithApi>);
    expect(await screen.findByLabelText('공고 검색')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '근무 지역' })).not.toBeInTheDocument();
    expect(screen.queryByText('상세 조건')).not.toBeInTheDocument();
    await waitFor(() => expect(get.mock.calls.some(([p]) => p.startsWith('/v1/job-postings?'))).toBe(true));
  });
});
