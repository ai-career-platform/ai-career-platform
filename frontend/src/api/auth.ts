/** 인증 API (T15). 로그인·refresh 는 이전 토큰을 보내지 않습니다(token: null). */
import type { HttpClient } from './http';
import type { BodyOf, ResponseOf } from './schema';

export type TokenResponse = ResponseOf<'login'>;

export const authApi = (http: HttpClient) => ({
  /** 이메일 가입 + 필수 약관 동의. 성공하면 바로 로그인 상태(201 + access token, refresh 쿠키) */
  signup: (body: BodyOf<'signup'>) =>
    http.request<TokenResponse>('/v1/auth/signup', { method: 'POST', body, token: null }),
  login: (body: BodyOf<'login'>) =>
    http.request<TokenResponse>('/v1/auth/login', { method: 'POST', body, token: null }),
  /** refresh 쿠키(HttpOnly)로 새 access token 을 받습니다. 호출할 때마다 토큰이 회전합니다. */
  refresh: () => http.request<TokenResponse>('/v1/auth/refresh', { method: 'POST', token: null }),
  logout: (token?: string | null) =>
    http.request<undefined>('/v1/auth/logout', { method: 'POST', token }),
});
