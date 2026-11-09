import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { apiRequest } from './client';
import type { ApiRequestOptions } from './client';
import {
  createRecommendationRun,
  findLatestRecommendationRun,
  getRecommendationRun,
  jobPostingDetailPath,
} from './recommendations';
import type { AuthedRequest } from './recommendations';

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** useAuth().request 와 같이 토큰을 붙여 실제 fetch 경로로 보내는 테스트용 requester */
const requesterFor = (fetchImpl: typeof fetch): AuthedRequest =>
  <T,>(path: string, options: ApiRequestOptions = {}) =>
    apiRequest<T>(path, { ...options, token: 'test-token', baseUrl: '/api', mockEnabled: false, fetchImpl });

const run = {
  recommendation_run_id: '00000000-0000-4000-8000-000000000a01',
  status: 'completed',
  model_version: { model_code: 'match_rule', version: '1', kind: 'rule' },
  generated_at: '2026-11-06T03:10:00Z',
  items: [],
};

describe('recommendations API client (OpenAPI contract)', () => {
  it('GET /api/v1/recommendation-runs/latest with the bearer token', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, run));
    await expect(findLatestRecommendationRun(requesterFor(fetchImpl))).resolves.toEqual(run);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/recommendation-runs/latest');
    expect(init).toMatchObject({ method: 'GET', headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) });
  });

  it('maps 404 (no recommendation yet) to null and rethrows other errors', async () => {
    const notFound = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(404, { code: 'NOT_FOUND' }));
    await expect(findLatestRecommendationRun(requesterFor(notFound))).resolves.toBeNull();

    const serverError = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(findLatestRecommendationRun(requesterFor(serverError))).rejects.toMatchObject({ status: 500 });

    const unauthorized = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(401, { code: 'UNAUTHENTICATED' }));
    await expect(findLatestRecommendationRun(requesterFor(unauthorized))).rejects.toMatchObject({ status: 401 });
  });

  it('POST /api/v1/recommendation-runs with {limit}', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(201, run));
    await createRecommendationRun(requesterFor(fetchImpl), { limit: 10 });

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/recommendation-runs');
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify({ limit: 10 }) });
  });

  it('defaults limit to 20 and encodes ids in paths', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(201, run));
    await createRecommendationRun(requesterFor(fetchImpl));
    expect(fetchImpl.mock.calls[0]?.[1]).toMatchObject({ body: JSON.stringify({ limit: 20 }) });

    await getRecommendationRun(requesterFor(fetchImpl), 'a/b');
    expect(fetchImpl.mock.calls[1]?.[0]).toBe('/api/v1/recommendation-runs/a%2Fb');
    expect(jobPostingDetailPath('x y')).toBe('/job-postings/x%20y');
  });
});

describe('recommendations mock', () => {
  it('requires a login token and validates limit (422)', async () => {
    await expect(apiRequest('/v1/recommendation-runs/latest', { mockEnabled: true })).rejects.toMatchObject({ status: 401 });

    const login = await apiRequest<{ access_token: string }>('/v1/auth/login', {
      mockEnabled: true,
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const token = login.access_token;
    await expect(
      apiRequest('/v1/recommendation-runs', { mockEnabled: true, method: 'POST', body: { limit: 0 }, token }),
    ).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(
      apiRequest('/v1/recommendation-runs', { mockEnabled: true, method: 'POST', body: { limit: 51 }, token }),
    ).rejects.toMatchObject({ status: 422 });
  });
});
