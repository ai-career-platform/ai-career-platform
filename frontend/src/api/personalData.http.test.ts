/** T143 실제 API 어댑터(T142) 전송 계약: 경로·메서드·재인증 헤더·다운로드 토큰은 본문으로만·Blob 응답. 합성 값만 씁니다. */
import { describe, expect, it, vi } from 'vitest';
import { createHttpClient } from './http';
import { createHttpPersonalDataService, REAUTH_HEADER } from './personalData';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function setup(respond: (url: string, init: RequestInit) => Response) {
  const fetchSpy = vi.fn<typeof fetch>(async (input, init) => respond(String(input), init ?? {}));
  const http = createHttpClient({ baseUrl: '/api', fetch: fetchSpy, getToken: () => 'synthetic-access' });
  return { service: createHttpPersonalDataService(http), fetchSpy };
}
const headersOf = (init: RequestInit) => init.headers as Record<string, string>;

const ROW = { request_id: 'r-1', request_type: 'export', status: 'received', created_at: '2026-11-11T03:00:00+00:00',
  updated_at: '2026-11-11T03:00:00+00:00', source: 'T142' };

describe('createHttpPersonalDataService', () => {
  it('lists items and re-authenticates with the password in the body only', async () => {
    const { service, fetchSpy } = setup((url) => (url.endsWith('/reauth')
      ? json({ reauth_token: 'synthetic-reauth', expires_at: '2026-11-11T03:10:00+00:00' }) : json({ items: [ROW] })));
    await expect(service.list()).resolves.toEqual([ROW]);
    expect(fetchSpy.mock.calls[0]![0]).toBe('/api/v1/me/data-requests');
    expect(headersOf(fetchSpy.mock.calls[0]![1]!).Authorization).toBe('Bearer synthetic-access');
    await expect(service.reauth('synthetic-pw')).resolves.toMatchObject({ reauth_token: 'synthetic-reauth' });
    const [url, init] = fetchSpy.mock.calls[1]!;
    expect(url).toBe('/api/v1/me/data-requests/reauth');
    expect(init!.method).toBe('POST');
    expect(JSON.parse(String(init!.body))).toEqual({ password: 'synthetic-pw' });
  });

  it('sends the re-auth token as a header (never in the URL) for create and download-link', async () => {
    const { service, fetchSpy } = setup((url) => (url.endsWith('/download-link')
      ? json({ token: 't'.repeat(43), expires_at: '2026-11-11T03:10:00+00:00', uses: 1, notice: 'x' }, 201) : json(ROW, 202)));
    await service.createExport('synthetic-reauth');
    await service.downloadLink('r 1', 'synthetic-reauth');
    const [createUrl, createInit] = fetchSpy.mock.calls[0]!;
    const [linkUrl, linkInit] = fetchSpy.mock.calls[1]!;
    expect(createUrl).toBe('/api/v1/me/data-requests/exports');
    expect(linkUrl).toBe('/api/v1/me/data-requests/exports/r%201/download-link');
    for (const [url, init] of [[createUrl, createInit], [linkUrl, linkInit]] as const) {
      expect(init!.method).toBe('POST');
      expect(headersOf(init!)[REAUTH_HEADER]).toBe('synthetic-reauth');
      expect(headersOf(init!)['X-CSRF-TOKEN']).toBe('1');
      expect(String(url)).not.toContain('synthetic-reauth');
    }
  });

  it('cancels and downloads with the one-time token in the POST body, returning a Blob', async () => {
    const token = 'd'.repeat(43);
    const { service, fetchSpy } = setup((url) => (url.endsWith('/download')
      ? new Response('{"format":"ai-career-export/v1"}', { status: 200, headers: { 'Content-Type': 'application/json' } })
      : json({ ...ROW, status: 'cancelled' })));
    await expect(service.cancelExport('r-1')).resolves.toMatchObject({ status: 'cancelled' });
    expect(fetchSpy.mock.calls[0]![0]).toBe('/api/v1/me/data-requests/exports/r-1/cancel');
    const blob = await service.download(token);
    expect(await blob.text()).toContain('ai-career-export/v1');
    const [url, init] = fetchSpy.mock.calls[1]!;
    expect(url).toBe('/api/v1/me/data-requests/download');
    expect(String(url)).not.toContain(token);
    expect(JSON.parse(String(init!.body))).toEqual({ token });
  });

  it('maps a 403 re-auth-required answer to ApiError for the page to reopen the password dialog', async () => {
    const { service } = setup(() => json({ code: 'FORBIDDEN', status: 403, message: 'x' }, 403));
    await expect(service.createExport('old')).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' });
  });
});
