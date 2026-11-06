import { env } from '../config/env';
import { resolveMock } from '../mocks/handlers';
import { ApiError } from './errors';

export { ApiError };

export interface ApiClientOptions {
  baseUrl?: string;
  mockEnabled?: boolean;
  fetchImpl?: typeof fetch;
}

/**
 * 모든 Backend 호출은 이 함수를 통해 같은 Origin의 /api 아래로 보냅니다.
 * path는 Backend 기준 경로(예: '/health', '/v1/jobs')입니다.
 */
export async function apiGet<T>(path: string, options: ApiClientOptions = {}): Promise<T> {
  const mockEnabled = options.mockEnabled ?? env.mockEnabled;
  if (mockEnabled) {
    return resolveMock<T>(path);
  }

  const baseUrl = options.baseUrl ?? env.apiBaseUrl;
  const fetchImpl = options.fetchImpl ?? fetch;
  const url = `${baseUrl.replace(/\/$/, '')}${path}`;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
  } catch (error) {
    throw new ApiError(0, path, error instanceof Error ? error.message : 'Network error');
  }

  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}
