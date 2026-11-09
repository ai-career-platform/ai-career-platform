import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '../api/client';
import { JobExplorerPage } from './JobExplorerPage';

vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
const get = vi.mocked(apiGet);
beforeEach(() => get.mockReset());

describe('job role API', () => {
  it('loads a role and its required skills from separate endpoints', async () => {
    get.mockResolvedValueOnce({ items: [{ job_role_id: '1', code: 'dev', name: '개발자' }], next_cursor: null });
    get.mockResolvedValueOnce({ job_role_id: '1', name: '개발자', code: 'dev', description: null, required_skills: [{ skill: { skill_id: 's1', name: 'Python' }, required_level: 3 }] });
    render(<JobExplorerPage />);
    fireEvent.click(await screen.findByRole('button', { name: '개발자' }));
    expect(await screen.findByText('Python · 요구 수준 3')).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('/v1/job-roles/1');
  });
  it('uses the returned cursor and sends server-side search', async () => {
    get.mockResolvedValueOnce({ items: [], next_cursor: 'next' });
    get.mockResolvedValueOnce({ items: [], next_cursor: null });
    get.mockResolvedValueOnce({ items: [], next_cursor: null });
    render(<JobExplorerPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다음' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-roles?limit=20&cursor=next'));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '개발' } });
    fireEvent.click(screen.getByRole('button', { name: '검색' }));
    await waitFor(() => expect(get).toHaveBeenCalledWith('/v1/job-roles?limit=20&q=%EA%B0%9C%EB%B0%9C'));
  });
  it('shows an error and retries', async () => {
    get.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [], next_cursor: null });
    render(<JobExplorerPage />);
    fireEvent.click(await screen.findByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('검색 결과가 없습니다.')).toBeInTheDocument();
  });
});
