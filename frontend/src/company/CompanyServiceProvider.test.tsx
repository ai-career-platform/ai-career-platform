/** T124 데이터 경로: Mock 모드가 아니면 실제 API(T123)를 쓰고, Mock 메일함은 없습니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { useCompanyService, useMockCompanyBackend } from './companyContext';
import { CompanyServiceProvider } from './CompanyServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, companyConsoleUi: true } }));

const authed = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Probe() {
  const service = useCompanyService();
  const mock = useMockCompanyBackend();
  const [names, setNames] = useState<string | null>(null);
  useEffect(() => { void service.myOrganizations().then((rows) => setNames(rows.map((r) => r.organization.name).join(','))); }, [service]);
  return <p>orgs:{names ?? '-'} mock:{mock ? 'yes' : 'no'}</p>;
}

describe('CompanyServiceProvider (real API)', () => {
  it('goes through the authenticated HttpClient, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => [{ organization: { organization_id: 'o-1', name: '합성 기업' }, role: 'owner' }]);
    render(
      <WithApi request={request}><AuthContext.Provider value={authed}><MemoryRouter>
        <CompanyServiceProvider><Probe /></CompanyServiceProvider>
      </MemoryRouter></AuthContext.Provider></WithApi>,
    );
    expect(await screen.findByText('orgs:합성 기업 mock:no')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/me/organizations', expect.anything()));
  });
});
