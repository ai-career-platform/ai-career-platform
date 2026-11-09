import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '../api/client';
import { JobPostingsPage } from './JobPostingsPage';
vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
const get = vi.mocked(apiGet);
const posting = { job_posting_id: '1', title: '개발자', status: 'published', company: { name: '회사' } };
beforeEach(() => {
  get.mockReset();
  get.mockImplementation(async path => {
    if (path.startsWith('/v1/companies?')) return { items: [{ company_id: 'c1', name: '회사' }], next_cursor: null };
    if (path.startsWith('/v1/job-roles?')) return { items: [{ job_role_id: 'r1', name: '개발자' }], next_cursor: null };
    if (path === '/v1/job-postings/1') return { ...posting, job_role: null, location_text: null, description: null, source_url: 'javascript:alert(1)', required_skills: [] };
    return { items: [posting], next_cursor: path.includes('cursor=') ? null : 'next' };
  });
});
describe('job postings API', () => {
  it('shows list and detail without rendering unsafe source links', async () => {
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /개발자 · 회사/ }));
    expect(await screen.findByText('상세 설명이 없습니다.')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '원본 공고 보기' })).not.toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('/v1/job-postings/1');
  });
  it('sends company and role IDs and resets pagination when filters change', async () => {
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-postings?limit=20&sort=-published_at&include_closed=false&cursor=next'));
    await screen.findByRole('option', { name: '회사' });
    fireEvent.change(screen.getByLabelText('기업 필터'), { target: { value: 'c1' } });
    fireEvent.change(screen.getByLabelText('직무 필터'), { target: { value: 'r1' } });
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-postings?limit=20&sort=-published_at&include_closed=false&company_id=c1&job_role_id=r1'));
  });
  it('shows a retry when postings fail', async () => {
    const original = get.getMockImplementation()!;
    let failed = false;
    get.mockImplementation(path => {
      if (path.startsWith('/v1/job-postings?') && !failed) { failed = true; return Promise.reject(new Error('offline')); }
      return original(path);
    });
    render(<JobPostingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByRole('button', { name: /개발자 · 회사/ })).toBeInTheDocument();
  });
});
