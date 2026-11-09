import { createContext, useContext } from 'react';
import type { ApiRequestOptions } from '../api/client';

export interface AuthUser {
  email: string;
  displayName: string;
  roles: string[];
}

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; token: string; user: AuthUser };

export interface AuthContextValue {
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** 로그인 토큰을 붙여 호출하고, 401이면 세션을 비워 로그인 화면으로 돌려보냅니다. */
  request: <T>(path: string, options?: ApiRequestOptions) => Promise<T>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
