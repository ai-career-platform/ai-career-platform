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

    await http.request('/v1/auth/refresh', { method: 'POST', token: null }); // 본문 없는 refresh
    await http.request('/v1/auth/login', { method: 'POST', body: {}, token: null });
    await http.request('/v1/me/skills', { method: 'PUT', body: { items: [] } });
    await http.request('/v1/me', { method: 'PATCH', body: {} });
    await http.request('/v1/me/bookmarks/x', { method: 'DELETE' });
    await http.request('/v1/job-roles');

    const headers = fetchImpl.mock.calls.map(([, init]) => init?.headers as Record<string, string>);
    expect(headers.slice(0, 5).map((h) => h['X-CSRF-TOKEN'])).toEqual(['1', '1', '1', '1', '1']);
    expect(headers[5]).not.toHaveProperty('X-CSRF-TOKEN');
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

describe('createHttpClient — success bodies that are not JSON (E2E-006 D-1)', () => {
  const client = (response: Response, onUnauthorized = vi.fn<(error: ApiError) => void>()) =>
    ({ http: createHttpClient({ baseUrl: '/api', fetch: vi.fn<typeof fetch>().mockResolvedValue(response), onUnauthorized }), onUnauthorized });
  const html = '<!doctype html><html><body><div id="root"></div></body></html>';

  it('keeps parsing a normal JSON 200', async () => {
    const { http } = client(jsonResponse(200, { items: [], next_cursor: null }));
    await expect(http.request('/v1/job-roles')).resolves.toEqual({ items: [], next_cursor: null });
  });

  it('rejects an HTML 200 (SPA fallback / proxy page) as INVALID_RESPONSE instead of returning undefined', async () => {
    const { http, onUnauthorized } = client(new Response(html, { status: 200, headers: { 'Content-Type': 'text/html' } }));
    const error: unknown = await http.request('/v1/job-roles').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 200, path: '/v1/job-roles', code: 'INVALID_RESPONSE', userMessage: undefined, requestId: undefined });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('rejects a JSON content-type whose body does not parse, keeping the X-Request-ID', async () => {
    const { http } = client(new Response('{"items": [', { status: 200, headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-0123456789abcdef' } }));
    await expect(http.request('/v1/job-roles')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', requestId: 'req-0123456789abcdef' });
  });

  it('rejects HTML even when served without a content-type', async () => {
    const { http } = client(new Response(html, { status: 200, headers: { 'Content-Type': '' } }));
    await expect(http.request('/v1/job-roles')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });

  it('still accepts valid JSON served with a non-JSON content-type (existing fixtures and proxies)', async () => {
    const { http } = client(new Response('{"ok":true}', { status: 200 })); // text/plain;charset=UTF-8
    await expect(http.request('/v1/x')).resolves.toEqual({ ok: true });
  });

  it('keeps the empty-body contract: 204, 205 and an empty 200/201 resolve to undefined', async () => {
    for (const response of [new Response(null, { status: 204 }), new Response(null, { status: 205 }),
      new Response('', { status: 200 }), new Response('  ', { status: 201, headers: { 'Content-Type': 'application/json' } })]) {
      await expect(client(response).http.request('/v1/x', { method: 'DELETE' })).resolves.toBeUndefined();
    }
  });

  it('leaves 4xx/5xx JSON errors unchanged, with their request id', async () => {
    await expect(client(jsonResponse(404, { code: 'NOT_FOUND', status: 404, message: '요청한 정보를 찾을 수 없습니다.' }, { 'X-Request-ID': 'req-aaaaaaaaaaaaaaaa' })).http.request('/v1/job-roles/x'))
      .rejects.toMatchObject({ status: 404, code: 'NOT_FOUND', requestId: 'req-aaaaaaaaaaaaaaaa' });
    await expect(client(jsonResponse(500, { code: 'INTERNAL_ERROR', status: 500, message: '서버 오류' }, { 'X-Request-ID': 'req-bbbbbbbbbbbbbbbb' })).http.request('/v1/job-roles'))
      .rejects.toMatchObject({ status: 500, code: 'INTERNAL_ERROR', requestId: 'req-bbbbbbbbbbbbbbbb' });
  });

  it('maps a body that cannot be read to a network error and passes aborts through', async () => {
    const used = jsonResponse(200, {});
    await used.text(); // 이미 소비된 본문
    await expect(client(used).http.request('/v1/x')).rejects.toMatchObject({ name: 'ApiError', status: 0 });

    const aborting = new Response('{}', { status: 200 });
    vi.spyOn(aborting, 'text').mockRejectedValue(new DOMException('aborted', 'AbortError'));
    await expect(client(aborting).http.request('/v1/x')).rejects.toMatchObject({ name: 'AbortError' });
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
