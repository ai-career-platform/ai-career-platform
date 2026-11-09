import { env } from '../config/env';
import { createMockFetch } from '../mocks/mockFetch';
import { ApiError } from './errors';
import { createHttpClient, type HttpClient, type HttpMethod } from './http';

export { ApiError };

/** env 설정(VITE_API_MOCK)에 따라 mock fetch 또는 전역 fetch. 호출 시점에 판단합니다. */
export const appFetch: typeof fetch = (input, init) =>
  (env.mockEnabled ? createMockFetch(env.apiBaseUrl) : globalThis.fetch)(input, init);

/** 로그인 토큰 없이 쓰는 앱 기본 클라이언트 (공개 API). */
export const publicHttp: HttpClient = createHttpClient({ baseUrl: env.apiBaseUrl, fetch: appFetch });

// ---------------------------------------------------------------------------
// 아래는 기존 호출을 위한 호환 래퍼입니다. 새 코드는 http.ts 의 HttpClient 를 쓰세요.
// ---------------------------------------------------------------------------

export interface ApiClientOptions {
  baseUrl?: string;
  mockEnabled?: boolean;
  fetchImpl?: typeof fetch;
}

export interface ApiRequestOptions extends ApiClientOptions {
  method?: HttpMethod;
  body?: unknown;
  /** access token. 메모리에만 두고 Authorization 헤더로만 보냅니다. */
  token?: string | null;
}

/** 호환 래퍼 — 남은 호출을 옮긴 뒤 제거합니다. 새 코드는 createHttpClient / publicHttp. */
export function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method, body, token = null } = options;
  const baseUrl = options.baseUrl ?? env.apiBaseUrl;
  const mockEnabled = options.mockEnabled ?? env.mockEnabled;
  const fetchImpl = mockEnabled ? createMockFetch(baseUrl) : options.fetchImpl;
  return createHttpClient({ baseUrl, fetch: fetchImpl }).request<T>(path, { method, body, token });
}

/** 호환 래퍼 — 새 코드는 publicHttp.request. */
export const apiGet = <T>(path: string, options: ApiClientOptions = {}) =>
  apiRequest<T>(path, options);
