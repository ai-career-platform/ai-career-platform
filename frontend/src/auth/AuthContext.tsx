import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, apiRequest } from '../api/client';
import type { ApiRequestOptions } from '../api/client';
import { AuthContext } from './useAuth';
import type { AuthState } from './useAuth';

interface TokenResponse {
  access_token: string;
}
interface Me {
  email: string;
  display_name: string;
}
interface Permissions {
  roles: string[];
}

async function loadUser(token: string): Promise<AuthState> {
  const [me, permissions] = await Promise.all([
    apiRequest<Me>('/v1/me', { token }),
    apiRequest<Permissions>('/v1/me/permissions', { token }),
  ]);
  return {
    status: 'authenticated',
    token,
    user: { email: me.email, displayName: me.display_name, roles: permissions.roles },
  };
}

/**
 * 로그인 세션 상태. access token 은 React 메모리에만 두고
 * localStorage·URL·console 에는 남기지 않습니다 (새로고침 시 refresh 쿠키로 복구).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });
  const started = useRef(false);

  useEffect(() => {
    // refresh 는 호출할 때마다 토큰이 회전하므로 StrictMode 에서도 한 번만 호출합니다.
    if (started.current) return;
    started.current = true;
    apiRequest<TokenResponse>('/v1/auth/refresh', { method: 'POST' })
      .then((t) => loadUser(t.access_token))
      .then(setState)
      .catch(() => setState({ status: 'anonymous' }));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const t = await apiRequest<TokenResponse>('/v1/auth/login', { method: 'POST', body: { email, password } });
    setState(await loadUser(t.access_token));
  }, []);

  const token = state.status === 'authenticated' ? state.token : null;

  const logout = useCallback(async () => {
    try {
      await apiRequest<void>('/v1/auth/logout', { method: 'POST', token });
    } finally {
      // 서버 호출이 실패해도 화면에서는 로그아웃 처리합니다.
      setState({ status: 'anonymous' });
    }
  }, [token]);

  const request = useCallback(
    async <T,>(path: string, options: ApiRequestOptions = {}) => {
      try {
        return await apiRequest<T>(path, { ...options, token });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) setState({ status: 'anonymous' });
        throw error;
      }
    },
    [token],
  );

  const value = useMemo(() => ({ state, login, logout, request }), [state, login, logout, request]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
