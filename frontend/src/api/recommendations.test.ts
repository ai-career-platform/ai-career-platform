import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import { resetRecommendationMock } from '../mocks/recommendations';
import { apiRequest } from './client';
import type { ApiRequestOptions } from './client';
import {
  applyFeedbackToRun,
  createRecommendationFeedback,
  createRecommendationRun,
  findLatestRecommendationRun,
  getRecommendationRun,
  jobPostingDetailPath,
} from './recommendations';
import type { AuthedRequest, RecommendationRun } from './recommendations';

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

  it('POST /api/v1/recommendation-feedback with RecommendationFeedbackInput (T48)', async () => {
    const saved = {
      feedback_id: '00000000-0000-4000-8000-000000000c01',
      job_posting_id: '00000000-0000-4000-8000-000000000101',
      feedback: 'liked',
      created_at: '2026-11-09T02:01:00Z',
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(201, saved));
    const body = {
      recommendation_run_id: run.recommendation_run_id,
      job_posting_id: saved.job_posting_id,
      feedback: 'liked',
    } as const;
    await expect(createRecommendationFeedback(requesterFor(fetchImpl), body)).resolves.toEqual(saved);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/recommendation-feedback');
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify(body),
      headers: expect.objectContaining({ Authorization: 'Bearer test-token', 'Content-Type': 'application/json' }),
    });
  });

  it('applyFeedbackToRun updates only the matching posting and maps cleared to null', () => {
    const item = (id: string, feedback: 'liked' | null) => ({
      rank: 1,
      score: 50,
      reason: '테스트',
      feedback,
      job_posting: {
        job_posting_id: id,
        title: '가상 공고',
        status: 'published' as const,
        company: { company_id: 'c', name: '가상 회사' },
        job_role: null,
        employment_type: null,
        location_text: null,
        published_at: null,
        expires_at: null,
      },
    });
    const source: RecommendationRun = {
      recommendation_run_id: run.recommendation_run_id,
      status: 'completed',
      model_version: { model_code: 'match_rule', version: '1', kind: 'rule' },
      generated_at: run.generated_at,
      items: [item('p1', 'liked'), item('p2', 'liked')],
    };
    const next = applyFeedbackToRun(source, { job_posting_id: 'p1', feedback: 'cleared' });
    expect(next.items.map((entry) => entry.feedback)).toEqual([null, 'liked']);
    expect(source.items[0]?.feedback).toBe('liked');
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

  it('validates feedback input (422) and hides postings outside my runs (404)', async () => {
    resetRecommendationMock();
    const login = await apiRequest<{ access_token: string }>('/v1/auth/login', {
      mockEnabled: true,
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const post = (body: unknown) =>
      apiRequest('/v1/recommendation-feedback', { mockEnabled: true, method: 'POST', body, token: login.access_token });
    const posting = '00000000-0000-4000-8000-000000000101';

    await expect(
      apiRequest('/v1/recommendation-feedback', { mockEnabled: true, method: 'POST', body: { job_posting_id: posting, feedback: 'liked' } }),
    ).rejects.toMatchObject({ status: 401 });
    await expect(post({ job_posting_id: posting, feedback: 'LIKED' })).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(post({ feedback: 'liked' })).rejects.toMatchObject({ status: 422 });
    await expect(post({ job_posting_id: posting, feedback: 'liked', user_id: 'x' })).rejects.toMatchObject({ status: 422 });
    await expect(post({ recommendation_run_id: null, job_posting_id: posting, feedback: 'liked' })).rejects.toMatchObject({ status: 422 });
    // OpenAPI Uuid 형식이 아니면 소유권 확인(404) 전에 422 (T47 pydantic UUID 와 같게)
    await expect(post({ job_posting_id: 'x', feedback: 'liked' })).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(post({ recommendation_run_id: 'x', job_posting_id: posting, feedback: 'liked' })).rejects.toMatchObject({
      status: 422,
      code: 'VALIDATION_FAILED',
    });
    await expect(post({ job_posting_id: '00000000-0000-4000-8000-000000000999', feedback: 'liked' })).rejects.toMatchObject({ status: 404 });
    await expect(
      post({ recommendation_run_id: '00000000-0000-4000-8000-000000000fff', job_posting_id: posting, feedback: 'liked' }),
    ).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });

    const first = await post({ job_posting_id: posting, feedback: 'liked' });
    expect(first).toMatchObject({ job_posting_id: posting, feedback: 'liked' });
    // 같은 값을 다시 보내면 같은 기록을 돌려준다 (멱등)
    await expect(post({ job_posting_id: posting, feedback: 'liked' })).resolves.toEqual(first);
    resetRecommendationMock();
  });
});
