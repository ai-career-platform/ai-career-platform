/** T103 데이터 경로: Mock 모드가 아니면 실제 API(T102)를 씁니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { useApplicationService } from './applicationContext';
import { ApplicationServiceProvider } from './ApplicationServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, applicationsUi: true } }));

const auth: AuthContextValue = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Probe() {
  const service = useApplicationService();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => { void service.list().then((p) => setCount(p.items.length)); }, [service]);
  return <p>items:{count ?? '-'}</p>;
}

describe('ApplicationServiceProvider (real API)', () => {
  it('lists through the authenticated HttpClient, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => ({ items: [], next_cursor: null }));
    render(
      <WithApi request={request}><AuthContext.Provider value={auth}><MemoryRouter>
        <ApplicationServiceProvider><Probe /></ApplicationServiceProvider>
      </MemoryRouter></AuthContext.Provider></WithApi>,
    );
    expect(await screen.findByText('items:0')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/me/job-applications?limit=100', expect.anything()));
  });
});
