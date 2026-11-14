/** T97 데이터 경로: Mock 모드가 아니면 실제 API(T97)를 씁니다. */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { AuthContext, type AuthContextValue } from '../auth/useAuth';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { useNotificationService } from './notificationContext';
import { NotificationServiceProvider } from './NotificationServiceProvider';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false, notificationsUi: true } }));

const auth: AuthContextValue = {
  state: { status: 'authenticated', token: 't', user: { userId: 'u-1', email: 'u@example.invalid', displayName: 'U', roles: ['job_seeker'] } },
  login: vi.fn<AuthContextValue['login']>(), logout: vi.fn<AuthContextValue['logout']>(), signup: vi.fn<AuthContextValue['signup']>(),
  googleSignup: vi.fn<AuthContextValue['googleSignup']>(), fullLogout: vi.fn<AuthContextValue['fullLogout']>(),
} as AuthContextValue;

function Probe() {
  const service = useNotificationService();
  const [unread, setUnread] = useState<number | null>(null);
  useEffect(() => { void service.listInbox().then((p) => setUnread(p.unread_count)); }, [service]);
  return <p>unread:{unread ?? '-'}</p>;
}

describe('NotificationServiceProvider (real API)', () => {
  it('lists through the authenticated HttpClient, not the mock', async () => {
    const request = vi.fn<RequestFn>(async () => ({ items: [], unread_count: 3 }));
    render(
      <WithApi request={request}><AuthContext.Provider value={auth}><MemoryRouter>
        <NotificationServiceProvider><Probe /></NotificationServiceProvider>
      </MemoryRouter></AuthContext.Provider></WithApi>,
    );
    expect(await screen.findByText('unread:3')).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledWith('/v1/me/notifications', expect.anything()));
  });
});
