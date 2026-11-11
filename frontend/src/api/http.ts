import { ApiError } from './errors';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | readonly QueryValue[]>;

export interface HttpRequest {
  method?: HttpMethod;
  /** 쿼리스트링. null·undefined·빈 문자열 값은 빠집니다. */
  query?: Query;
  body?: unknown;
  /** 취소 신호. 취소되면 ApiError가 아니라 AbortError(DOMException)가 그대로 던져집니다. */
  signal?: AbortSignal;
  /**
   * 이 호출에만 쓸 access token. 지정하지 않으면 클라이언트의 getToken()을 씁니다.
   * null을 넘기면 토큰 없이 보냅니다 (로그인·refresh 처럼).
   */
  token?: string | null;
  /** 'blob'이면 성공 응답 본문을 Blob 으로 돌려줍니다(인증된 파일 다운로드). 기본 'json' */
  responseType?: 'json' | 'blob';
  /**
   * 성공 응답의 헤더를 받는 콜백 (T85: getAiUsage 의 X-AI-Cost-Status). 오류 응답에서는 부르지 않습니다.
   * 반환 타입(본문)을 바꾸지 않으려고 콜백으로 둡니다.
   */
  onResponseHeaders?: (headers: Headers) => void;
  /**
   * 이 요청에만 더할 헤더 (T156: 크롤러 관리자 명령의 Idempotency-Key).
   * Accept·Content-Type·Authorization·CSRF 는 덮어쓸 수 없습니다(아래에서 다시 정합니다).
   */
  headers?: Record<string, string>;
}

export interface HttpClient {
  request<T>(path: string, init?: HttpRequest): Promise<T>;
}

export interface HttpClientConfig {
  /** 같은 Origin의 API 기본 경로. 예: '/api' */
  baseUrl: string;
  /** 실제 fetch 또는 mock fetch. 지정하지 않으면 호출 시점의 전역 fetch. */
  fetch?: typeof fetch;
  /** 로그인 상태면 access token. 메모리에만 두고 Authorization 헤더로만 보냅니다. */
  getToken?: () => string | null | undefined;
  /** 401 응답을 받았을 때 (세션 비우기 등). 오류는 그대로 호출자에게도 던져집니다. */
  onUnauthorized?: (error: ApiError) => void;
}

export const REQUEST_ID_HEADER = 'X-Request-ID';
/** 상태를 바꾸는 요청(GET 외)에 항상 붙이는 CSRF 헤더. Backend auth 라우터가 검사합니다 (docs/SECURITY.md). */
export const CSRF_HEADER = 'X-CSRF-TOKEN';

/** { q: 'a b', page: 2, empty: '', region: ['x', 'y'] } → '?q=a+b&page=2&region=x&region=y' (값이 없으면 '') */
export function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {   // 배열은 키를 반복(T98 다중 값)
      if (item === null || item === undefined || item === '') continue;
      params.append(key, String(item));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : '';
}

const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

/**
 * 모든 Backend 호출이 지나가는 단일 전송 계층.
 * path는 Backend 기준 경로(예: '/health', '/v1/job-roles')이고, 같은 Origin의 baseUrl 아래로 보냅니다.
 * refresh 쿠키(HttpOnly)가 /v1/auth 로 가도록 credentials 는 same-origin 입니다.
 */
export function createHttpClient(config: HttpClientConfig): HttpClient {
  const baseUrl = config.baseUrl.replace(/\/$/, '');

  async function request<T>(path: string, init: HttpRequest = {}): Promise<T> {
    const { method = 'GET', query, body, signal, responseType = 'json' } = init;
    const token = init.token !== undefined ? init.token : config.getToken?.();
    // FormData(파일 업로드)는 브라우저가 boundary 를 포함한 multipart Content-Type 을 정하도록 직접 지정하지 않습니다.
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
    const headers: Record<string, string> = {
      ...init.headers, Accept: responseType === 'blob' ? '*/*' : 'application/json',
    };
    // CSRF 보호(OWASP custom-header): 외부 페이지의 HTML form 은 이 헤더를 보낼 수 없습니다. 비밀값이 아닙니다.
    if (method !== 'GET') headers[CSRF_HEADER] = '1';
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;

    const fetchImpl = config.fetch ?? globalThis.fetch;
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}${buildQuery(query)}`, {
        method,
        headers,
        body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
        signal,
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new ApiError(0, path, error instanceof Error ? error.message : 'Network error');
    }

    if (!response.ok) {
      const problem = (await response.json().catch(() => null)) as { code?: string; message?: string } | null;
      const error = new ApiError(
        response.status, path, undefined, problem?.code, problem?.message,
        response.headers.get(REQUEST_ID_HEADER) ?? undefined, response.headers,
      );
      if (response.status === 401) config.onUnauthorized?.(error);
      throw error;
    }
    init.onResponseHeaders?.(response.headers);
    if (responseType === 'blob') {
      try {
        return (await response.blob()) as T;
      } catch (error) {
        if (isAbort(error)) throw error;
        throw new ApiError(0, path, 'Network error');
      }
    }
    // 204 No Content 등 본문이 없는 성공 응답
    return (await response.json().catch(() => undefined)) as T;
  }

  return { request };
}
