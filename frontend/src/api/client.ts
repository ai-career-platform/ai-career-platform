import { env } from '../config/env';
import { resolveMock } from '../mocks/handlers';
import { ApiError } from './errors';

export { ApiError };

export interface ApiClientOptions {
  baseUrl?: string;
  mockEnabled?: boolean;
  fetchImpl?: typeof fetch;
}

export interface ApiRequestOptions extends ApiClientOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** access token. 메모리에만 두고 Authorization 헤더로만 보냅니다. */
  token?: string | null;
  /** 요청 취소(업로드 취소 등). 취소되면 ApiError(status 0, code 'ABORTED') */
  signal?: AbortSignal;
  /** 'blob'이면 성공 응답 본문을 Blob 으로 돌려줍니다(파일 다운로드). 기본 'json' */
  responseType?: 'json' | 'blob';
}

/** 사용자가 취소한 요청인지 확인합니다. 취소된 요청의 결과는 성공으로 다루지 않습니다. */
export const isAbortError = (error: unknown) => error instanceof ApiError && error.code === 'ABORTED';

/**
 * 모든 Backend 호출은 이 함수를 통해 같은 Origin의 /api 아래로 보냅니다.
 * path는 Backend 기준 경로(예: '/health', '/v1/jobs')입니다.
 * refresh 쿠키(HttpOnly)가 /v1/auth 로 가도록 credentials 를 same-origin 으로 둡니다.
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token, signal, responseType = 'json' } = options;
  const mockEnabled = options.mockEnabled ?? env.mockEnabled;
  if (mockEnabled) {
    return resolveMock<T>(path, { method, body, token, signal });
  }

  const baseUrl = options.baseUrl ?? env.apiBaseUrl;
  const fetchImpl = options.fetchImpl ?? fetch;
  const url = `${baseUrl.replace(/\/$/, '')}${path}`;
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const headers: Record<string, string> = { Accept: responseType === 'blob' ? '*/*' : 'application/json' };
  // FormData 는 브라우저가 multipart boundary 를 포함한 Content-Type 을 정하도록 직접 지정하지 않습니다.
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetchImpl(url, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'same-origin',
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw new ApiError(0, path, 'Request aborted', 'ABORTED');
    throw new ApiError(0, path, error instanceof Error ? error.message : 'Network error');
  }

  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as { code?: string; message?: string } | null;
    throw new ApiError(response.status, path, undefined, problem?.code, problem?.message);
  }
  if (responseType === 'blob') {
    try {
      return (await response.blob()) as T;
    } catch {
      if (signal?.aborted) throw new ApiError(0, path, 'Request aborted', 'ABORTED');
      throw new ApiError(0, path, 'Network error');
    }
  }
  // 204 No Content 등 본문이 없는 성공 응답
  return (await response.json().catch(() => undefined)) as T;
}

export const apiGet = <T>(path: string, options: ApiClientOptions = {}) =>
  apiRequest<T>(path, options);
