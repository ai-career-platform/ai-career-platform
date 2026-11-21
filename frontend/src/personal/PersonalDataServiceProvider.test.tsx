/** T143 데이터 경로: Mock 모드가 아니면 실제 API(T142)를 씁니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { usePersonalDataService } from './personalDataContext';
import { PersonalDataServiceProvider } from './PersonalDataServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, personalDataUi: true } }));

const auth: AuthContextValue = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Probe() {
  const service = usePersonalDataService();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => { void service.list().then((items) => setCount(items.length)); }, [service]);
  return <p>items:{count ?? '-'}</p>;
}

describe('PersonalDataServiceProvider (real API)', () => {
  it('lists through the authenticated HttpClient, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => ({ items: [] }));
    render(
      <WithApi request={request}><AuthContext.Provider value={auth}><MemoryRouter>
        <PersonalDataServiceProvider><Probe /></PersonalDataServiceProvider>
      </MemoryRouter></AuthContext.Provider></WithApi>,
    );
    expect(await screen.findByText('items:0')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/me/data-requests', expect.anything()));
  });
});
