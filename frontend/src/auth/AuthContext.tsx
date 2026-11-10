import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Api } from '../api';
import { ApiContext } from '../api/ApiContext';
import { forgetSession, rememberSession, shouldKeepSession } from './loginPreferences';
import { createSession } from './session';
import { AuthContext } from './useAuth';
import type { AuthState } from './useAuth';

async function loadUser(api: Api, token: string): Promise<AuthState> {
  const [me, permissions] = await Promise.all([api.me.profile.get(), api.me.profile.permissions()]);
  return {
    status: 'authenticated',
    token,
    user: { email: me.email, displayName: me.display_name, roles: permissions.roles, userId: me.user_id },
  };
}

/**
 * 로그인 세션 상태와, 토큰을 붙여 호출하는 API 묶음(useApi)을 내려 줍니다.
 * 새로고침하면 refresh 쿠키로 복구하고, 401 응답을 받으면 세션을 비워 로그인 화면으로 돌려보냅니다.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });
  const [session] = useState(() => createSession(() => setState({ status: 'anonymous' })));
  const { api, setToken } = session;
  const started = useRef(false);

  const apply = useCallback((next: AuthState) => {
    setToken(next.status === 'authenticated' ? next.token : null);
    setState(next);
  }, [setToken]);

  /** 받은 토큰으로 사용자 정보를 불러옵니다. 실패하면 토큰을 버립니다. */
  const signIn = useCallback(async (accessToken: string) => {
    setToken(accessToken);
    try {
      return await loadUser(api, accessToken);
    } catch (error) {
      setToken(null);
      throw error;
    }
  }, [api, setToken]);

  useEffect(() => {
    // refresh 는 호출할 때마다 토큰이 회전하므로 StrictMode 에서도 한 번만 호출합니다.
    if (started.current) return;
    started.current = true;
    api.auth.refresh()
      .then(async (t) => {
        const restored = await signIn(t.access_token);
        if (shouldKeepSession()) return restored;
        // 자동 로그인을 끄고 브라우저를 닫았다 다시 연 경우: 서버 세션도 끝내고 로그인 화면으로 보냅니다.
        await api.auth.logout(t.access_token).catch(() => undefined);
        return { status: 'anonymous' } as AuthState;
      })
      .then(apply)
      .catch(() => apply({ status: 'anonymous' }));
  }, [api, apply, signIn]);

  const login = useCallback(async (email: string, password: string, autoLogin = false) => {
    const t = await api.auth.login({ email, password });
    const next = await signIn(t.access_token);
    rememberSession(autoLogin);
    apply(next);
  }, [api, apply, signIn]);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      // 서버 호출이 실패해도 화면에서는 로그아웃 처리합니다.
      forgetSession();
      apply({ status: 'anonymous' });
    }
  }, [api, apply]);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return (
    <AuthContext.Provider value={value}>
      <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
    </AuthContext.Provider>
  );
}
