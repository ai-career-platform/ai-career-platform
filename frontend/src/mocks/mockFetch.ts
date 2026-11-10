import { ApiError } from '../api/errors';
import { resolveMock } from './handlers';

const json = (status: number, body: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
  });

const abortError = () => new DOMException('The operation was aborted.', 'AbortError');

/**
 * 가상 데이터(handlers.ts)를 fetch 모양으로 감쌉니다.
 * 실제 fetch 자리에 끼우므로 mock 모드에서도 http.ts 의 헤더 구성·오류 해석 코드가 그대로 실행됩니다.
 * Mock 성공은 실제 서비스 PASS가 아닙니다.
 */
export function createMockFetch(baseUrl: string): typeof fetch {
  const prefix = baseUrl.replace(/\/$/, '');

  return async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = url.startsWith(prefix) ? url.slice(prefix.length) : url;
    const headers = new Headers(init.headers);
    const token = headers.get('Authorization')?.replace(/^Bearer /, '') ?? null;
    const body = typeof init.body === 'string' ? (JSON.parse(init.body) as unknown)
      : init.body instanceof FormData ? init.body : undefined;
    const signal = init.signal ?? undefined;
    if (signal?.aborted) throw abortError();

    const result = resolveMock<unknown>(path, { method: init.method ?? 'GET', body, token }).then(
      async (data) => data instanceof Blob
        ? new Response(await data.arrayBuffer(), { status: 200, headers: { 'Content-Type': data.type } })
        : json(200, data),
      (error: unknown) => {
        if (!(error instanceof ApiError)) throw error;
        return json(error.status, error.code ? { code: error.code, status: error.status, message: error.userMessage } : undefined);
      },
    );
    if (!signal) return result;
    return new Promise<Response>((resolve, reject) => {
      const onAbort = () => reject(abortError());
      signal.addEventListener('abort', onAbort, { once: true });
      result.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
    });
  };
}
