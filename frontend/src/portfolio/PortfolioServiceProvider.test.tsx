/** T130 데이터 경로: Mock 모드가 아니면 실제 API(T129)를 씁니다. 공개 화면은 로그인 없이 공개 조회만 부릅니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { usePortfolioReader, usePortfolioService } from './portfolioContext';
import { PortfolioServiceProvider } from './PortfolioServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, publicPortfolioUi: true } }));

const fns = () => ({
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
});
const authed = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  ...fns(),
} as AuthContextValue;
const anonymous = { state: { status: 'anonymous' }, ...fns() } as AuthContextValue;

function Owner() {
  const service = usePortfolioService();
  const [version, setVersion] = useState<number | null>(null);
  useEffect(() => { void service.settings().then((s) => setVersion(s.selection.version)); }, [service]);
  return <p>version:{version ?? '-'}</p>;
}

function Viewer() {
  const reader = usePortfolioReader();
  const [headline, setHeadline] = useState<string | null>(null);
  useEffect(() => { void reader.view('tok').then((p) => setHeadline(p.headline ?? '')); }, [reader]);
  return <p>headline:{headline ?? '-'}</p>;
}

function mount(auth: AuthContextValue, request: RequestFn, child: ReactNode) {
  render(
    <WithApi request={request}><AuthContext.Provider value={auth}><MemoryRouter>
      <PortfolioServiceProvider>{child}</PortfolioServiceProvider>
    </MemoryRouter></AuthContext.Provider></WithApi>,
  );
}

describe('PortfolioServiceProvider (real API)', () => {
  it('owner settings go through the authenticated HttpClient, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => ({ selection: { version: 7 }, links: [] }));
    mount(authed, request, <Owner />);
    expect(await screen.findByText('version:7')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/me/public-profile', expect.anything()));
  });

  it('an anonymous visitor reads the public endpoint without a login token', async () => {
    const request = vi.fn<RequestFn>(async () => ({ headline: '공개 소개' }));
    mount(anonymous, request, <Viewer />);
    expect(await screen.findByText('headline:공개 소개')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/v1/public/portfolios/tok', expect.objectContaining({ token: null }));
    expect(request.mock.calls.every(([path]) => !path.startsWith('/v1/me/'))).toBe(true);
  });
});
