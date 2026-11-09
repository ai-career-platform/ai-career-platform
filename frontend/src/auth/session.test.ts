import { describe, expect, it, vi } from 'vitest';
import { createSession } from './session';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

describe('createSession', () => {
  it('attaches the session token to API calls', async () => {
    const session = createSession(vi.fn<() => void>());
    session.setToken('mock-access-user@example.com');
    await expect(session.api.me.profile.get()).resolves.toMatchObject({ email: 'user@example.com' });
  });

  it('drops the token and reports expiry once when an authenticated call gets 401', async () => {
    const onExpired = vi.fn<() => void>();
    const session = createSession(onExpired);
    session.setToken('mock-access-expired@example.com');

    await expect(session.api.me.profile.get()).rejects.toMatchObject({ status: 401 });
    expect(onExpired).toHaveBeenCalledTimes(1);

    // 토큰을 버렸으므로 다음 401 은 세션 만료로 보지 않습니다.
    await expect(session.api.me.profile.get()).rejects.toMatchObject({ status: 401 });
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it('ignores 401 from calls made without a token (e.g. wrong password)', async () => {
    const onExpired = vi.fn<() => void>();
    const session = createSession(onExpired);
    await expect(session.api.auth.login({ email: 'user@example.com', password: 'wrong' }))
      .rejects.toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' });
    expect(onExpired).not.toHaveBeenCalled();
  });
});
