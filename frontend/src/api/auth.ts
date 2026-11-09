/** 인증 API (T15). 로그인·refresh 는 이전 토큰을 보내지 않습니다(token: null). */
import type { HttpClient } from './http';
import type { BodyOf, ResponseOf } from './schema';

export type TokenResponse = ResponseOf<'login'>;

export const authApi = (http: HttpClient) => ({
  login: (body: BodyOf<'login'>) =>
    http.request<TokenResponse>('/v1/auth/login', { method: 'POST', body, token: null }),
  /** refresh 쿠키(HttpOnly)로 새 access token 을 받습니다. 호출할 때마다 토큰이 회전합니다. */
  refresh: () => http.request<TokenResponse>('/v1/auth/refresh', { method: 'POST', token: null }),
  logout: (token?: string | null) =>
    http.request<undefined>('/v1/auth/logout', { method: 'POST', token }),
});
