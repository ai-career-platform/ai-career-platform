import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { AuthContext } from '../auth/useAuth';
import type { AuthContextValue } from '../auth/useAuth';
import type { ApiRequestOptions } from '../api/client';
import { BookmarksPage, CareerHistoryPage, TargetRolesPage } from './MyCareerWorkspace';

const role = { job_role_id: '11111111-1111-4111-8111-111111111111', code: 'backend', name: '백엔드 개발자' };
function renderPage(page: React.ReactNode, request: AuthContextValue['request']) {
  const value: AuthContextValue = { state: { status: 'authenticated', token: 'token', user: { email: 'user@example.com', displayName: '사용자', roles: ['job_seeker'] } }, login: vi.fn<AuthContextValue['login']>(), updateUser: vi.fn<AuthContextValue['updateUser']>(), logout: vi.fn<AuthContextValue['logout']>(), request };
  return render(<AuthContext.Provider value={value}>{page}</AuthContext.Provider>);
}

it('loads and saves target roles through the real API contract', async () => {
  const requestMock = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>(async (path, options) => {
    if (path.startsWith('/v1/job-roles')) return { items: [role], next_cursor: null };
    if (options?.method === 'PUT') return [{ job_role: role, priority: 1 }];
    return [{ job_role: role, priority: 1 }];
  });
  const request = requestMock as unknown as AuthContextValue['request'];
  renderPage(<TargetRolesPage />, request);
  expect(await screen.findByText('1순위 · 백엔드 개발자')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '저장' }));
  expect(await screen.findByText('목표 직무를 저장했습니다.')).toBeInTheDocument();
  expect(requestMock).toHaveBeenCalledWith('/v1/me/target-roles', expect.objectContaining({ method: 'PUT' }));
});

it('creates an experience and renders the server response', async () => {
  const requestMock = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>(async (path, options) => {
    if (path === '/v1/me/projects') return [];
    if (options?.method === 'POST') return { experience_id: 'e1', ...(options.body as object), description: null };
    return [];
  });
  const request = requestMock as unknown as AuthContextValue['request'];
  renderPage(<CareerHistoryPage />, request);
  await screen.findByText('등록한 경력이나 프로젝트가 없습니다.');
  fireEvent.change(screen.getByLabelText('회사·기관'), { target: { value: '오픈AI' } });
  fireEvent.change(screen.getByLabelText('직무'), { target: { value: '개발자' } });
  fireEvent.click(screen.getByRole('button', { name: '추가' }));
  expect(await screen.findByText(/오픈AI · 개발자/)).toBeInTheDocument();
});

it('loads and removes a closed bookmark', async () => {
  const item = { job_posting_id: 'j1', title: 'Backend Engineer', status: 'closed', company: { name: '테스트 회사' } };
  const requestMock = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>(async (_path, options) => options?.method === 'DELETE' ? undefined : { items: [item], next_cursor: null });
  const request = requestMock as unknown as AuthContextValue['request'];
  renderPage(<BookmarksPage />, request);
  expect(await screen.findByText('마감된 공고')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '저장 해제' }));
  await waitFor(() => expect(screen.queryByText('Backend Engineer')).not.toBeInTheDocument());
  expect(requestMock).toHaveBeenCalledWith('/v1/me/bookmarks/j1', { method: 'DELETE' });
});
