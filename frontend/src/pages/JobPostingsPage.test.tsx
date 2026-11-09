import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { JobPostingsPage } from './JobPostingsPage';
import {
  DEMO_REFERENCE_DATE, demoPostings, filterDemoPostings, isClosed, pageDemoPostings,
  type DemoPosting,
} from './jobPostingData';

function LocationView() {
  const location = useLocation();
  return <output data-testid="current-query">{location.search}</output>;
}
function renderPage(loadPostings?: () => Promise<readonly DemoPosting[]>, initial = '/job-postings') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <JobPostingsPage loadPostings={loadPostings} />
      <LocationView />
    </MemoryRouter>,
  );
}
const defaults = {
  query: '', companyId: '', role: '', status: 'open' as const,
  order: 'recent' as const, asOf: DEMO_REFERENCE_DATE,
};

describe('T24 synthetic company and job posting explorer', () => {
  it('renders clear mock disclaimer and six open postings with detail', async () => {
    renderPage();
    expect(screen.getByText('UI 시안 · 합성 채용 데이터')).toBeInTheDocument();
    expect(await screen.findByText('검색 결과 6건')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '클라우드 운영 엔지니어 상세 보기' }));
    expect(screen.getByRole('heading', { name: '클라우드 운영 엔지니어', level: 3 }))
      .toBeInTheDocument();
    expect(screen.getByText('출처: 합성 데이터 (synthetic_seed)')).toBeInTheDocument();
    expect(screen.getByText(/실제 원문·지원 링크가 없습니다/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /지원|원문/ })).not.toBeInTheDocument();
  });

  it('supports closed and all status; never exposes draft even in all', async () => {
    renderPage();
    await screen.findByText('검색 결과 6건');
    fireEvent.click(screen.getByRole('button', { name: '마감' }));
    expect(screen.getByText('검색 결과 2건')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '전체' }));
    expect(screen.getByText('검색 결과 8건')).toBeInTheDocument();
    expect(screen.queryByText('미게시 가상 채용')).not.toBeInTheDocument();
  });

  it('filters by company, role and keyword and clears old detail', async () => {
    renderPage();
    await screen.findByText('검색 결과 6건');
    fireEvent.click(screen.getByRole('button', { name: '클라우드 운영 엔지니어 상세 보기' }));
    fireEvent.change(screen.getByRole('searchbox', { name: '채용공고·기업·기술 검색' }),
      { target: { value: 'Python' } });
    expect(screen.getByText('검색 결과 4건')).toBeInTheDocument();
    expect(screen.getByText('공고를 선택해 주세요')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: '기업' }),
      { target: { value: 'demo-forest' } });
    expect(screen.getByText('검색 결과 2건')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: '직무' }),
      { target: { value: '데이터 분석가' } });
    expect(screen.getByText('검색 결과 1건')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'),
      { target: { value: '완전히 없는 공고' } });
    expect(screen.getByText('조건에 맞는 공고가 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색 조건 초기화' }));
    expect(screen.getByText('검색 결과 6건')).toBeInTheDocument();
  });

  it('can use company cards to filter and reset the company selection', async () => {
    renderPage();
    await screen.findByText('검색 결과 6건');
    const company = screen.getByRole('button', { name: /노바랩.*가상 기업/ });
    fireEvent.click(company);
    expect(company).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('검색 결과 2건')).toBeInTheDocument();
    expect(screen.getByText('기업 필터: 노바랩')).toBeInTheDocument();
    fireEvent.click(company);
    expect(company).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByText('검색 결과 6건')).toBeInTheDocument();
  });

  it('keeps URL search conditions and paginates deterministically', async () => {
    renderPage(undefined, '/job-postings?status=all&order=deadline');
    await screen.findByText('검색 결과 8건');
    expect(screen.getByRole('combobox', { name: '정렬' })).toHaveValue('deadline');
    expect(screen.getByText('1 / 2 페이지')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getByText('2 / 2 페이지')).toBeInTheDocument();
    expect(screen.getByTestId('current-query')).toHaveTextContent('page=2');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Python' } });
    expect(screen.getByText('1 / 1 페이지')).toBeInTheDocument();
    expect(screen.getByTestId('current-query')).not.toHaveTextContent('page=2');
    expect(screen.getByTestId('current-query')).toHaveTextContent('q=Python');
    fireEvent.click(screen.getByRole('button', { name: '조건 초기화' }));
    expect(screen.getByTestId('current-query')).toHaveTextContent('');
    expect(screen.getByText('검색 결과 6건')).toBeInTheDocument();
  });

  it('handles loading, failure and retry without any external API', async () => {
    const loader = vi.fn<() => Promise<readonly DemoPosting[]>>()
      .mockRejectedValueOnce(new Error('synthetic loader error'))
      .mockResolvedValueOnce(demoPostings);
    renderPage(loader);
    expect(screen.getByText('예시 공고를 불러오는 중입니다')).toBeInTheDocument();
    expect(await screen.findByText('채용공고를 불러오지 못했습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('검색 결과 6건');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('treats expiry as closed in the explicit mock date, sorts missing deadlines last', () => {
    const expired = demoPostings.find((posting) => posting.id === 'demo-post-04');
    const undated = demoPostings.find((posting) => posting.id === 'demo-post-03');
    expect(expired).toBeDefined();
    expect(undated).toBeDefined();
    expect(isClosed(expired!, DEMO_REFERENCE_DATE)).toBe(true);
    expect(isClosed(undated!, DEMO_REFERENCE_DATE)).toBe(false);
    expect(isClosed(expired!, '2026-11-01')).toBe(false);
    const all = filterDemoPostings(demoPostings, { ...defaults, status: 'all', order: 'deadline' });
    expect(all).toHaveLength(8);
    expect(all[all.length - 1]?.id).toBe('demo-post-03');
    expect(all.find((posting) => posting.status === 'draft')).toBeUndefined();
    expect(filterDemoPostings(demoPostings, defaults)).toHaveLength(6);
    expect(pageDemoPostings(all, 99).current).toBe(2);
    expect(pageDemoPostings([], 1).items).toEqual([]);
    expect(() => pageDemoPostings(all, 0)).toThrow('Invalid page');
  });
});
