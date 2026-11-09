import { describe, expect, it, vi } from 'vitest';
import { createMockFetch } from '../mocks/mockFetch';
import { ApiError } from './errors';
import { buildQuery, createHttpClient } from './http';

const jsonResponse = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('buildQuery', () => {
  it('drops empty values and encodes the rest', () => {
    expect(buildQuery({ q: '데이터 분석', limit: 20, closed: false, cursor: null, role: undefined, company: '' }))
      .toBe('?q=%EB%8D%B0%EC%9D%B4%ED%84%B0+%EB%B6%84%EC%84%9D&limit=20&closed=false');
    expect(buildQuery({ cursor: null })).toBe('');
    expect(buildQuery()).toBe('');
  });
});

describe('createHttpClient', () => {
  it('sends same-origin JSON requests with query, body and the client token', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, { ok: true }));
    const http = createHttpClient({ baseUrl: '/api/', fetch: fetchImpl, getToken: () => 'tok' });

    await expect(http.request('/v1/me/skills', { method: 'PUT', query: { dry: true }, body: { items: [] } }))
      .resolves.toEqual({ ok: true });

    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe('/api/v1/me/skills?dry=true');
    expect(init).toMatchObject({ method: 'PUT', body: '{"items":[]}', cache: 'no-store', credentials: 'same-origin' });
    expect(init?.headers).toMatchObject({ Authorization: 'Bearer tok', 'Content-Type': 'application/json' });
  });

  it('adds the CSRF header to every non-GET request (including token-less auth calls) but not to GET', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(200, {}));
    const http = createHttpClient({ baseUrl: '/api', fetch: fetchImpl });

    await http.request('/v1/auth/login', { method: 'POST', body: {}, token: null });
    await http.request('/v1/me/skills', { method: 'PUT', body: { items: [] } });
    await http.request('/v1/me/bookmarks/x', { method: 'DELETE' });
    await http.request('/v1/job-roles');

    const headers = fetchImpl.mock.calls.map(([, init]) => init?.headers as Record<string, string>);
    expect(headers.slice(0, 3).map((h) => h['X-CSRF-TOKEN'])).toEqual(['1', '1', '1']);
    expect(headers[3]).not.toHaveProperty('X-CSRF-TOKEN');
  });

  it('lets a call override or drop the client token', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => jsonResponse(200, {}));
    const http = createHttpClient({ baseUrl: '/api', fetch: fetchImpl, getToken: () => 'client' });

    await http.request('/a', { token: 'call' });
    await http.request('/b', { token: null });

    expect(fetchImpl.mock.calls[0]![1]?.headers).toMatchObject({ Authorization: 'Bearer call' });
    expect(fetchImpl.mock.calls[1]![1]?.headers).not.toHaveProperty('Authorization');
  });

  it('turns error responses into ApiError with code, message and request id', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(409, { code: 'LAST_ADMIN', status: 409, message: '관리자는 최소 1명' }, { 'X-Request-ID': 'req-12345678' }),
    );
    const http = createHttpClient({ baseUrl: '/api', fetch: fetchImpl });

    await expect(http.request('/v1/x')).rejects.toMatchObject({
      name: 'ApiError', status: 409, path: '/v1/x', code: 'LAST_ADMIN', userMessage: '관리자는 최소 1명', requestId: 'req-12345678',
    });
  });

  it('reports 401 to onUnauthorized and still throws', async () => {
    const onUnauthorized = vi.fn<(error: ApiError) => void>();
    const http = createHttpClient({
      baseUrl: '/api', fetch: vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(401, { code: 'UNAUTHENTICATED' })), onUnauthorized,
    });

    await expect(http.request('/v1/me')).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledWith(expect.objectContaining({ code: 'UNAUTHENTICATED' }));
  });

  it('maps network failure to status 0 but passes aborts through', async () => {
    const network = createHttpClient({ baseUrl: '/api', fetch: vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch')) });
    const error: unknown = await network.request('/health').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);

    const aborted = createHttpClient({
      baseUrl: '/api', fetch: vi.fn<typeof fetch>().mockRejectedValue(new DOMException('aborted', 'AbortError')),
    });
    await expect(aborted.request('/health')).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('returns undefined for an empty success body', async () => {
    const http = createHttpClient({ baseUrl: '/api', fetch: vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 })) });
    await expect(http.request('/v1/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });
});

describe('createMockFetch', () => {
  const http = createHttpClient({ baseUrl: '/api', fetch: createMockFetch('/api') });

  it('serves fixtures through the real client path', async () => {
    await expect(http.request('/health')).resolves.toMatchObject({ status: 'ok' });
    await expect(http.request('/v1/unknown')).rejects.toMatchObject({ status: 404 });
  });

  it('reads the bearer token and keeps catalog codes and messages', async () => {
    await expect(http.request('/v1/me')).rejects.toMatchObject({ status: 401, code: 'UNAUTHENTICATED', userMessage: '로그인이 필요합니다.' });
    await expect(http.request('/v1/me', { token: 'mock-access-user@example.com' })).resolves.toMatchObject({ email: 'user@example.com' });
  });

  it('honours abort signals', async () => {
    const controller = new AbortController();
    const pending = http.request('/health', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});
