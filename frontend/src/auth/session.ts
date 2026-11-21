import { createApi, type Api } from '../api';
import { appFetch } from '../api/client';
import { createHttpClient } from '../api/http';
import { env } from '../config/env';

export interface Session {
  /** 이 세션의 토큰을 붙여 호출하는 API 묶음. 세션 동안 같은 객체입니다. */
  api: Api;
  setToken: (token: string | null) => void;
}

/**
 * 로그인 세션 하나. access token 은 이 클로저 안(메모리)에만 두고 localStorage·URL·console 에는 남기지 않습니다.
 * 토큰을 가진 상태에서 401 을 받으면 토큰을 버리고 onExpired 를 부릅니다.
 * 로그인 실패처럼 토큰 없이 받은 401 은 세션과 무관하므로 무시합니다.
 * 로그인한 채 비밀번호를 다시 확인하다 틀린 경우(T142 재인증, 401 INVALID_CREDENTIALS)도 세션 만료가 아니므로 무시합니다.
 */
export function createSession(onExpired: () => void): Session {
  let token: string | null = null;
  const api = createApi(createHttpClient({
    baseUrl: env.apiBaseUrl,
    fetch: appFetch,
    getToken: () => token,
    onUnauthorized: (error) => {
      if (token === null || error.code === 'INVALID_CREDENTIALS') return;
      token = null;
      onExpired();
    },
  }));
  return { api, setToken: (next) => { token = next; } };
}
