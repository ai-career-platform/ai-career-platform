import { createContext, useContext } from 'react';
import type { BodyOf } from '../api/schema';

export interface AuthUser {
  email: string;
  displayName: string;
  roles: string[];
  /** GET /me 의 user_id. 화면에서 "내 담당·내 콘텐츠" 표시용이며 권한 판단은 서버가 합니다. */
  userId?: string;
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
  /** 가입 후 바로 로그인 상태가 됩니다 (FR-ACC-001). */
  signup: (body: BodyOf<'signup'>) => Promise<void>;
  /** #328 Google 최초 가입(약관 동의 후). 성공하면 바로 로그인 상태가 됩니다. */
  googleSignup: (body: BodyOf<'completeGoogleSignup'>) => Promise<void>;
  /** #328 완전 로그아웃(앱 세션 + Google 게이트). Google 계정 자체는 로그아웃하지 않습니다. */
  fullLogout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
