/** T127 데이터 경로: Mock 모드가 아니면 실제 API(T126, migration 0009)를 씁니다. 기업 쪽에는 게시 경로가 없습니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { usePostingService } from './postingContext';
import { PostingServiceProvider } from './PostingServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, companyConsoleUi: true, companyPostingsUi: true } }));

const authed = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(),
  signup: vi.fn<AuthContextValue['signup']>(), googleSignup: vi.fn<AuthContextValue['googleSignup']>(),
  fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Probe() {
  const service = usePostingService();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => { void service.list('org-1').then((rows) => setCount(rows.length)); }, [service]);
  return <p>count:{count ?? '-'}</p>;
}

function Submit() {
  const service = usePostingService();
  const [status, setStatus] = useState('-');
  useEffect(() => { void service.submit('org-1', 'p-1', 3).then((p) => setStatus(p.status)); }, [service]);
  return <p>status:{status}</p>;
}

const mount = (request: RequestFn, child: ReactNode) => render(
  <WithApi request={request}><AuthContext.Provider value={authed}><MemoryRouter>
    <PostingServiceProvider>{child}</PostingServiceProvider>
  </MemoryRouter></AuthContext.Provider></WithApi>,
);

describe('PostingServiceProvider (real API)', () => {
  it('lists the organization postings through the HTTP client, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => [{ posting_id: 'p-1' }, { posting_id: 'p-2' }]);
    mount(request, <Probe />);
    expect(await screen.findByText('count:2')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/v1/organizations/org-1/postings', expect.anything());
  });

  it('submit for review sends only the version; no company-side publish endpoint is called', async () => {
    const request = vi.fn<RequestFn>(async () => ({ posting_id: 'p-1', status: 'pending_review' }));
    mount(request, <Submit />);
    expect(await screen.findByText('status:pending_review')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/organizations/org-1/postings/p-1/submit',
      expect.objectContaining({ method: 'POST', body: { version: 3 } })));
    expect(request.mock.calls.every(([path]) => !path.includes('/admin/'))).toBe(true);
  });
});
