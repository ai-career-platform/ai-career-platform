import { env } from '../config/env';
import { resolveMock } from '../mocks/handlers';
import { ApiError } from './errors';
import type { FieldError } from './errors';

export { ApiError };

export interface ApiClientOptions {
  baseUrl?: string;
  mockEnabled?: boolean;
  fetchImpl?: typeof fetch;
}

export interface ApiRequestOptions extends ApiClientOptions {
  method?: 'GET' | 'POST' | 'PATCH';
  body?: unknown;
  /** access token. 메모리에만 두고 Authorization 헤더로만 보냅니다. */
  token?: string | null;
}

/**
 * 모든 Backend 호출은 이 함수를 통해 같은 Origin의 /api 아래로 보냅니다.
 * path는 Backend 기준 경로(예: '/health', '/v1/jobs')입니다.
 * refresh 쿠키(HttpOnly)가 /v1/auth 로 가도록 credentials 를 same-origin 으로 둡니다.
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token } = options;
  const mockEnabled = options.mockEnabled ?? env.mockEnabled;
  if (mockEnabled) {
    return resolveMock<T>(path, { method, body, token });
  }

  const baseUrl = options.baseUrl ?? env.apiBaseUrl;
  const fetchImpl = options.fetchImpl ?? fetch;
  const url = `${baseUrl.replace(/\/$/, '')}${path}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch (error) {
    throw new ApiError(0, path, error instanceof Error ? error.message : 'Network error');
  }

  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as { code?: string; errors?: FieldError[] } | null;
    throw new ApiError(response.status, path, undefined, problem?.code, problem?.errors);
  }
  // 204 No Content 등 본문이 없는 성공 응답
  return (await response.json().catch(() => undefined)) as T;
}

export const apiGet = <T>(path: string, options: ApiClientOptions = {}) =>
  apiRequest<T>(path, options);
