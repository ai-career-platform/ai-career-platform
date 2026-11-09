import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WithApi } from '../test/WithApi';
import { JobPostingsPage } from './JobPostingsPage';

// 화면이 보낸 요청을 "경로 + 쿼리스트링" 한 줄로 받습니다.
const get = vi.fn<(path: string) => Promise<unknown>>();

const C1 = '11111111-1111-4111-8111-111111111111';
const C2 = '22222222-2222-4222-8222-222222222222';
const R1 = '33333333-3333-4333-8333-333333333333';
const company = (id: string, name: string) => ({ company_id: id, name });
const posting = (id: string, title: string, over: Record<string, unknown> = {}) => ({
  job_posting_id: id, title, status: 'published', company: company(C1, '알파'), job_role: { job_role_id: R1, code: 'BE', name: '백엔드' },
  employment_type: 'full_time', location_text: '서울', published_at: '2026-10-01T00:00:00Z', expires_at: '2026-12-31T00:00:00Z', ...over,
});
const detailOf = (id: string, over: Record<string, unknown> = {}) => ({
  ...posting(id, '상세 공고'), description: '설명입니다', source_url: null, is_bookmarked: null,
  required_skills: [
    { skill: { skill_id: 's1', code: 'PY', name: 'Python' }, required_level: 4, is_required: true },
    { skill: { skill_id: 's2', code: 'GIT', name: 'Git' }, required_level: null, is_required: false },
  ], ...over,
});
const companyDetail = (over: Record<string, unknown> = {}) => ({
  company_id: C1, name: '알파', website_url: 'https://alpha.example.com', description: '알파 소개', open_posting_count: 3, source: 'synthetic_seed', ...over,
});

type Handlers = Partial<Record<'companies' | 'roles' | 'list' | 'detail' | 'company', (path: string) => unknown>>;
/** 요청 경로로 가짜 응답을 고릅니다(여러 요청이 동시에 나가므로 순서에 의존하지 않음). */
function serve(handlers: Handlers) {
  const defaults: Required<Handlers> = {
    companies: () => ({ items: [company(C1, '알파'), company(C2, '베타')], next_cursor: null }),
    roles: () => ({ items: [{ job_role_id: R1, code: 'BE', name: '백엔드' }], next_cursor: null }),
    list: () => ({ items: [posting('p1', '첫 공고')], next_cursor: null }),
    detail: (path) => detailOf(path.split('/').pop() ?? ''),
    company: () => companyDetail(),
  };
  get.mockImplementation(((path: string) => {
    const kind = path.startsWith('/v1/job-postings?') ? 'list'
      : path.startsWith('/v1/job-postings/') ? 'detail'
        : path.startsWith('/v1/companies?') ? 'companies'
          : path.startsWith('/v1/companies/') ? 'company'
            : path.startsWith('/v1/job-roles?') ? 'roles' : null;
    if (!kind) return Promise.reject(new Error(`unexpected ${path}`));
    try { return Promise.resolve((handlers[kind] ?? defaults[kind])(path)); } catch (error) { return Promise.reject(error); }
  }) as typeof get);
}
const listCalls = () => get.mock.calls.map(([path]) => path).filter((path) => path.startsWith('/v1/job-postings?'));
function Where() { const location = useLocation(); return <output data-testid="where">{location.search}</output>; }
function renderPage(url = '/job-postings') {
  return render(<WithApi request={(path) => get(path)}><MemoryRouter initialEntries={[url]}><JobPostingsPage /><Where /></MemoryRouter></WithApi>);
}

beforeEach(() => { get.mockReset(); });

describe('job postings (T18 API)', () => {
  it('shows postings with status, company, role, location, type and deadline', async () => {
    serve({ list: () => ({ items: [posting('p1', '첫 공고'), posting('p2', '닫힌 공고', { status: 'closed', expires_at: null, location_text: null, employment_type: null })], next_cursor: null }) });
    renderPage();
    expect(await screen.findByRole('button', { name: '첫 공고 상세 보기' })).toHaveTextContent('모집 중');
    expect(screen.getByRole('button', { name: '첫 공고 상세 보기' })).toHaveTextContent('서울 · 정규직 · 마감 2026년 12월 31일');
    const closed = screen.getByRole('button', { name: '닫힌 공고 상세 보기' });
    expect(closed).toHaveTextContent('마감');
    expect(closed).toHaveTextContent('지역 미등록 · 고용형태 미등록 · 마감일 미정');
    expect(listCalls()[0]).toBe('/v1/job-postings?limit=20&sort=-published_at&include_closed=false');
  });

  it('sends filters to the API, keeps them in the URL and restarts paging', async () => {
    serve({ list: (path) => path.includes('cursor=') ? { items: [posting('p3', '둘째 쪽')], next_cursor: null } : { items: [posting('p1', '첫 공고')], next_cursor: 'nx' } });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    expect(await screen.findByText('둘째 쪽')).toBeInTheDocument();
    expect(listCalls().at(-1)).toContain('cursor=nx');
    expect(screen.getByText('2 페이지')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('기업'), { target: { value: C2 } });
    await waitFor(() => expect(listCalls().at(-1)).toContain(`company_id=${C2}`));
    expect(listCalls().at(-1)).not.toContain('cursor=');
    expect(screen.getByTestId('where')).toHaveTextContent(`company=${C2}`);
    fireEvent.change(screen.getByLabelText('직무'), { target: { value: R1 } });
    await waitFor(() => expect(listCalls().at(-1)).toContain(`job_role_id=${R1}`));
    fireEvent.change(screen.getByLabelText('정렬'), { target: { value: 'expires' } });
    await waitFor(() => expect(listCalls().at(-1)).toContain('sort=expires_at'));
    fireEvent.click(screen.getByRole('button', { name: '마감 포함' }));
    await waitFor(() => expect(listCalls().at(-1)).toContain('include_closed=true'));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: ' 데이터 ' } });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));
    await waitFor(() => expect(listCalls().at(-1)).toContain('q=%EB%8D%B0%EC%9D%B4%ED%84%B0'));
    expect(screen.getByTestId('where').textContent).toContain('closed=1');
  });

  it('restores filters from the URL and ignores malformed ids', async () => {
    serve({});
    renderPage(`/job-postings?q=%EC%84%9C%EB%B2%84&company=${C2}&role=not-a-uuid&closed=1&order=expires`);
    await screen.findByText('첫 공고');
    const call = listCalls()[0] ?? '';
    expect(call).toContain(`company_id=${C2}`);
    expect(call).toContain('include_closed=true');
    expect(call).toContain('sort=expires_at');
    expect(call).not.toContain('job_role_id');
    expect(screen.getByRole('searchbox')).toHaveValue('서버');
    expect(screen.getByRole('button', { name: '조건 초기화' })).toBeEnabled();
  });

  it('chooses a company from the company cards and clears with reset', async () => {
    serve({});
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /베타/ }));
    await waitFor(() => expect(listCalls().at(-1)).toContain(`company_id=${C2}`));
    fireEvent.click(screen.getByRole('button', { name: '조건 초기화' }));
    await waitFor(() => expect(listCalls().at(-1)).not.toContain('company_id'));
    expect(screen.getByTestId('where')).toHaveTextContent('');
  });

  it('shows required/preferred skills, level, company intro and a safe external link', async () => {
    serve({ detail: (path) => detailOf(path.split('/').pop() ?? '', { source_url: 'https://jobs.example.com/x' }) });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '첫 공고 상세 보기' }));
    const skills = await screen.findByRole('list', { name: '요구 기술' });
    expect(within(skills).getByText('Python · 필수 · 요구 수준 4/5')).toBeInTheDocument();
    expect(within(skills).getByText('Git · 우대 · 요구 수준 미등록')).toBeInTheDocument();
    expect(await screen.findByText('알파 소개')).toBeInTheDocument();
    expect(screen.getByText('진행 중 공고 3건', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/합성 테스트 데이터/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /jobs\.example\.com에서 원문 보기/ });
    expect(link).toHaveAttribute('href', 'https://jobs.example.com/x');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('refuses unsafe source links and says when no link is provided', async () => {
    serve({ detail: (path) => detailOf(path.split('/').pop() ?? '', { source_url: 'javascript:alert(1)' }) });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '첫 공고 상세 보기' }));
    expect(await screen.findByText('이 공고는 원문 링크가 제공되지 않았습니다.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /원문/ })).not.toBeInTheDocument();
  });

  it('does not invent dates or status when the API has none', async () => {
    serve({ detail: (path) => detailOf(path.split('/').pop() ?? '', { published_at: null, expires_at: null, job_role: null, description: null, required_skills: [] }) });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '첫 공고 상세 보기' }));
    expect(await screen.findByText('등록된 요구 기술이 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('등록된 상세 설명이 없습니다.')).toBeInTheDocument();
    const facts = document.querySelector('.t24-detail-facts');
    expect(facts).toHaveTextContent('게시일미등록');
    expect(facts).toHaveTextContent('마감일미정');
  });

  it('shows empty/error states with retry for list, companies and detail', async () => {
    let fail = true;
    serve({
      list: () => { if (fail) throw new Error('down'); return { items: [], next_cursor: null }; },
      companies: () => { if (fail) throw new Error('down'); return { items: [], next_cursor: null }; },
    });
    renderPage('/job-postings?q=none');
    const retries = await screen.findAllByRole('button', { name: '다시 시도' });
    expect(retries).toHaveLength(2);
    fail = false;
    retries.forEach((button) => fireEvent.click(button));
    expect(await screen.findByText('조건에 맞는 공고가 없습니다')).toBeInTheDocument();
    expect(screen.getByText('등록된 기업이 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색 조건 초기화' }));
    await waitFor(() => expect(listCalls().at(-1)).not.toContain('q=none'));
  });

  it('keeps the posting detail when only the company intro fails', async () => {
    let failCompany = true;
    serve({ company: () => { if (failCompany) throw new Error('down'); return companyDetail(); } });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '첫 공고 상세 보기' }));
    expect(await screen.findByText('설명입니다')).toBeInTheDocument();
    const retry = await screen.findByRole('button', { name: '다시 시도' });
    failCompany = false;
    fireEvent.click(retry);
    expect(await screen.findByText('알파 소개')).toBeInTheDocument();
  });

  it('ignores a slow detail response for a posting that is no longer selected', async () => {
    let resolveSlow: (value: unknown) => void = () => undefined;
    serve({ list: () => ({ items: [posting('p1', '가'), posting('p2', '나')], next_cursor: null }) });
    const base = get.getMockImplementation();
    get.mockImplementation(((path: string) => {
      if (path.endsWith('/p1')) return new Promise<unknown>((resolve) => { resolveSlow = resolve; });
      return base?.(path);
    }) as typeof get);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '가 상세 보기' }));
    fireEvent.click(screen.getByRole('button', { name: '나 상세 보기' }));
    expect(await screen.findByText('설명입니다')).toBeInTheDocument();
    resolveSlow(detailOf('p1', { description: 'LATE-ONLY' }));
    await Promise.resolve();
    expect(screen.queryByText('LATE-ONLY')).not.toBeInTheDocument();
  });
});

describe('paging after filter changes', () => {
  it('starts from page 1 again when the filters return to an earlier combination', async () => {
    serve({ list: (path) => path.includes('cursor=') ? { items: [posting('p3', '둘째 쪽')], next_cursor: null } : { items: [posting('p1', '첫 공고')], next_cursor: 'nx' } });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    expect(await screen.findByText('둘째 쪽')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('기업'), { target: { value: C2 } });
    await waitFor(() => expect(listCalls().at(-1)).toContain(`company_id=${C2}`));
    fireEvent.click(screen.getByRole('button', { name: '조건 초기화' }));
    expect(await screen.findByText('첫 공고')).toBeInTheDocument();
    expect(listCalls().at(-1)).toBe('/v1/job-postings?limit=20&sort=-published_at&include_closed=false');
    expect(screen.getByText('1 페이지')).toBeInTheDocument();
  });
});
