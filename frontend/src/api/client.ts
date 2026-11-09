import { env } from '../config/env';
import { createMockFetch } from '../mocks/mockFetch';
import { ApiError } from './errors';
import { createHttpClient, type HttpClient } from './http';

export { ApiError };

/** env 설정(VITE_API_MOCK)에 따라 mock fetch 또는 전역 fetch. 호출 시점에 판단합니다. */
export const appFetch: typeof fetch = (input, init) =>
  (env.mockEnabled ? createMockFetch(env.apiBaseUrl) : globalThis.fetch)(input, init);

/** 로그인 토큰 없이 쓰는 앱 기본 클라이언트 (공개 API). 로그인 클라이언트는 AuthProvider 가 만듭니다. */
export const publicHttp: HttpClient = createHttpClient({ baseUrl: env.apiBaseUrl, fetch: appFetch });
