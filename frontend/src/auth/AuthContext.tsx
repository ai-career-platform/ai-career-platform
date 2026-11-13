import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Api } from '../api';
import type { BodyOf } from '../api/schema';
import { ApiContext } from '../api/ApiContext';
import { publicHttp } from '../api/client';
import { env } from '../config/env';
import { GOOGLE_DONE_PATH, googleApi, googleSignedOutHref, navigation } from './google';
import type { GoogleSignupBody } from './google';
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
/** 라우터 basename 을 뺀 현재 경로가 Google 인증 완료 경로인지. AuthProvider 첫 렌더 시점에 한 번만 봅니다. */
function arrivedFromGoogle(): boolean {
  const base = import.meta.env.BASE_URL.replace(/\/+$/, '');
  const path = window.location.pathname;
  return path === `${base}${GOOGLE_DONE_PATH}` || path === `${base}${GOOGLE_DONE_PATH}/`;
}

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
    // #328: Google 인증을 마치고 돌아온 직후에는 세션 유지 표시가 없다(다른 사이트를 거쳐 옴). 첫 refresh 보다 먼저
    // 표시해 두지 않으면 아래 shouldKeepSession() 이 false 가 되어 방금 만든 세션을 끊는다.
    // Google 로그인은 '자동 로그인'으로 취급한다(localStorage). sessionStorage 만 쓰면 주소로 연 새 탭이 세션을
    // 끊어(기존 자동 로그인 꺼짐 규칙) 다른 탭까지 로그아웃된다(로컬 E2E C05 에서 확인). 공용 PC 는 '완전 로그아웃'.
    if (arrivedFromGoogle()) rememberSession(true);
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

  const signup = useCallback(async (body: BodyOf<'signup'>) => {
    const t = await api.auth.signup(body);
    const next = await signIn(t.access_token);
    rememberSession(false);
    apply(next);
  }, [api, apply, signIn]);

  /** #328 Google 최초 가입(약관 동의). 가입 즉시 로그인 상태가 됩니다(Google 로그인 = 자동 로그인, 위 설명). */
  const googleSignup = useCallback(async (body: GoogleSignupBody) => {
    const t = await googleApi(publicHttp).signup(body);
    const next = await signIn(t.access_token);
    rememberSession(true);
    apply(next);
  }, [apply, signIn]);

  /**
   * 완전 로그아웃: 앱 세션 + Google 게이트 쿠키 종료 후 게이트 밖 정적 페이지로 이동합니다.
   * SPA 안에 머물면 게이트가 곧바로 Google 로 보내 다시 로그인되는 루프가 생기므로 페이지를 떠납니다.
   * Google 계정 자체는 로그아웃하지 않습니다.
   */
  const fullLogout = useCallback(async () => {
    try {
      await googleApi(publicHttp).signout();
    } finally {
      forgetSession();
      apply({ status: 'anonymous' });
      navigation.assign(googleSignedOutHref(env.apiBaseUrl));
    }
  }, [apply]);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      // 서버 호출이 실패해도 화면에서는 로그아웃 처리합니다.
      forgetSession();
      apply({ status: 'anonymous' });
    }
  }, [api, apply]);

  const value = useMemo(
    () => ({ state, login, logout, signup, googleSignup, fullLogout }),
    [state, login, logout, signup, googleSignup, fullLogout],
  );
  return (
    <AuthContext.Provider value={value}>
      <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
    </AuthContext.Provider>
  );
}
