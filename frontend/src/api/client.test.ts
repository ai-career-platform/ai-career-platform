import { describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet } from './client';

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('apiGet', () => {
  it('calls the same-origin /api base path and returns JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }));

    const result = await apiGet<{ status: string }>('/health', {
      baseUrl: '/api',
      useMock: false,
      fetchImpl,
    });

    expect(result).toEqual({ status: 'ok' });
    expect(fetchImpl).toHaveBeenCalledWith('/api/health', expect.objectContaining({ cache: 'no-store' }));
  });

  it('throws ApiError with HTTP status on 4xx/5xx', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(503, { detail: 'down' }));

    await expect(
      apiGet('/health/db', { baseUrl: '/api', useMock: false, fetchImpl }),
    ).rejects.toMatchObject({ name: 'ApiError', status: 503, path: '/health/db' });
  });

  it('throws ApiError with status 0 on network failure', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

    const error: unknown = await apiGet('/health', { baseUrl: '/api', useMock: false, fetchImpl }).catch(
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
  });

  it('returns fixture data in mock mode and 404 for unknown mock path', async () => {
    await expect(apiGet('/health', { useMock: true })).resolves.toMatchObject({ status: 'ok' });
    await expect(apiGet('/v1/jobs', { useMock: true })).rejects.toMatchObject({ status: 404 });
  });
});
