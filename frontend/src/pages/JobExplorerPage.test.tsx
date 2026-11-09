import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { JobExplorerPage } from './JobExplorerPage';
import { demoJobRoles, filterJobRoles, pageJobRoles, type JobRole } from './jobExplorerData';

describe('T23 synthetic job role explorer', () => {
  it('displays explicit mock notice, search, role and skill detail', async () => {
    render(<JobExplorerPage />);
    expect(screen.getByText('UI 미리보기 · 가상 데이터')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '백엔드' } });
    const card = await screen.findByRole('button', { name: '백엔드 개발자 상세 보기' });
    fireEvent.click(card);
    expect(card).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { level: 3, name: '백엔드 개발자' })).toBeInTheDocument();
    expect(screen.getByText(/실제 보유 기술·Skill Gap 분석은 연동되지 않았습니다/)).toBeInTheDocument();
  });

  it('filters by skill and category and restores results after empty search', async () => {
    render(<JobExplorerPage />);
    await screen.findByText('8개 직무');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Python' } });
    expect(screen.getByText('4개 직무')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '데이터' }));
    expect(screen.getByText('2개 직무')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '없는 기술' } });
    expect(screen.getByText('검색 결과가 없습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검색 조건 초기화' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(screen.getByText('8개 직무')).toBeInTheDocument();
  });

  it('supports next/previous and resets page when search changes', async () => {
    render(<JobExplorerPage />);
    await screen.findByText('8개 직무');
    expect(screen.getByText('1 / 2 페이지')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getByText('2 / 2 페이지')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '다음' })).toBeDisabled();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'UX' } });
    expect(screen.getByText('1 / 1 페이지')).toBeInTheDocument();
  });

  it('does not display a stale selection after another search', async () => {
    render(<JobExplorerPage />);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '백엔드' } });
    fireEvent.click(await screen.findByRole('button', { name: '백엔드 개발자 상세 보기' }));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'UX' } });
    expect(screen.getByText('직무를 선택해 주세요')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: '백엔드 개발자' })).not.toBeInTheDocument();
  });

  it('renders an error state and retries without contacting backend', async () => {
    const loader = vi.fn<() => Promise<readonly JobRole[]>>()
      .mockRejectedValueOnce(new Error('synthetic'))
      .mockResolvedValueOnce(demoJobRoles);
    render(<JobExplorerPage loadRoles={loader} />);
    expect(screen.getByText('예시 직무를 불러오는 중입니다')).toBeInTheDocument();
    expect(await screen.findByText('직무 목록을 불러오지 못했습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('8개 직무');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('keeps mock data immutable and validates pagination', () => {
    const snapshot = demoJobRoles.map((job) => job.id);
    expect(filterJobRoles(demoJobRoles, 'SQL', '전체', 'category').length).toBe(4);
    expect(demoJobRoles.map((job) => job.id)).toEqual(snapshot);
    expect(pageJobRoles(demoJobRoles, 100).current).toBe(2);
    expect(pageJobRoles([], 1).items).toEqual([]);
    expect(() => pageJobRoles(demoJobRoles, 0)).toThrow('Invalid page');
  });
});
