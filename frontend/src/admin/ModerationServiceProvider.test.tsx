/** T82 데이터 경로: Mock 모드가 아니면 실제 API(T81 /v1/admin/moderation-cases)를 씁니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { useModerationService } from './moderationContext';
import { ModerationServiceProvider } from './ModerationServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, adminModerationUi: true } }));

const auth = {
  state: { status: 'authenticated', token: 't', user: { userId: 'admin-1', email: 'a@example.invalid', displayName: 'A', roles: ['admin'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Queue() {
  const service = useModerationService();
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => { void service.list({ limit: 100 }).then((page) => setCount(page.items.length)); }, [service]);
  return <p>count:{count ?? '-'}</p>;
}

describe('ModerationServiceProvider (real API)', () => {
  it('the queue goes through the authenticated HttpClient, not the mock seed', async () => {
    const request = vi.fn<RequestFn>(async () => ({ items: [], next_cursor: null }));
    render(
      <WithApi request={request}><AuthContext.Provider value={auth}><MemoryRouter>
        <ModerationServiceProvider><Queue /></ModerationServiceProvider>
      </MemoryRouter></AuthContext.Provider></WithApi>,
    );
    expect(await screen.findByText('count:0')).toBeInTheDocument();         // mock seed 는 9건
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/admin/moderation-cases?limit=100', expect.anything()));
  });
});
