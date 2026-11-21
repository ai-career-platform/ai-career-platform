/** T143: 로그인한 채 비밀번호 재확인(T142 reauth)이 틀려도 세션을 끝내지 않습니다. 실제 API 모드(Mock 아님). */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSession } from './session';

vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: false } }));

const problem = (code: string) => new Response(JSON.stringify({ code, status: 401, message: 'x' }),
  { status: 401, headers: { 'Content-Type': 'application/json' } });

afterEach(() => { vi.unstubAllGlobals(); });

describe('createSession and 401 codes', () => {
  it('keeps the session when an authenticated re-auth gets 401 INVALID_CREDENTIALS', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => problem('INVALID_CREDENTIALS')));
    const onExpired = vi.fn<() => void>();
    const session = createSession(onExpired);
    session.setToken('synthetic-access');
    await expect(session.api.personalData.reauth('wrong')).rejects.toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' });
    expect(onExpired).not.toHaveBeenCalled();
  });

  it('still ends the session on other 401 codes', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => problem('TOKEN_EXPIRED')));
    const onExpired = vi.fn<() => void>();
    const session = createSession(onExpired);
    session.setToken('synthetic-access');
    await expect(session.api.personalData.list()).rejects.toMatchObject({ status: 401 });
    expect(onExpired).toHaveBeenCalledTimes(1);
  });
});
