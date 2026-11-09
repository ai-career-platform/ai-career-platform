import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '../api/client';
import { JobPostingsPage } from './JobPostingsPage';
vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
const get = vi.mocked(apiGet);
beforeEach(() => get.mockReset());
describe('job postings API', () => {
  it('shows API list and detail without rendering unsafe source links', async () => {
    get.mockResolvedValueOnce({ items: [{ job_posting_id: '1', title: '개발자', status: 'published', company: { name: '회사' } }], next_cursor: null });
    get.mockResolvedValueOnce({ title: '개발자', company: { name: '회사' }, job_role: null, location_text: null, description: null, source_url: 'javascript:alert(1)', required_skills: [] });
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /개발자 · 회사/ }));
    expect(await screen.findByText('상세 설명이 없습니다.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '원본 공고 보기' })).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('/v1/job-postings/1');
  });
  it('uses server cursor and supported filters', async () => {
    get.mockResolvedValueOnce({ items: [], next_cursor: 'next' }).mockResolvedValue({ items: [], next_cursor: null });
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-postings?limit=20&sort=-published_at&include_closed=false&cursor=next'));
    fireEvent.click(screen.getByRole('checkbox', { name: '마감 공고 포함' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-postings?limit=20&sort=-published_at&include_closed=true'));
  });
  it('shows a retry on failure', async () => {
    get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [], next_cursor: null });
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('검색 결과가 없습니다.')).toBeInTheDocument();
  });
});
