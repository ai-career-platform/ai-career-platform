import { createContext, useContext } from 'react';

export interface AuthUser {
  email: string;
  displayName: string;
  roles: string[];
}

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'authenticated'; token: string; user: AuthUser };

/** 로그인 상태와 동작. API 호출은 useApi() 로 합니다(로그인 중이면 토큰이 자동으로 붙음). */
export interface AuthContextValue {
  state: AuthState;
  login: (email: string, password: string, autoLogin?: boolean) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
