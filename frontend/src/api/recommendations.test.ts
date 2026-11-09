import { describe, expect, it, vi } from 'vitest';
import { MOCK_PASSWORD } from '../mocks/handlers';
import {
  MOCK_FALLBACK_REASON,
  MOCK_RULE_MODEL,
  resetRecommendationMock,
  setRecommendationMockScenario,
} from '../mocks/recommendations';
import { mockHttp } from '../test/api';
import { createHttpClient } from './http';
import { applyFeedbackToRun, jobPostingDetailPath, recommendationsApi } from './recommendations';
import type { RecommendationRun } from './recommendations';

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** 로그인 클라이언트와 같이 토큰을 붙여 실제 fetch 경로로 보내는 테스트용 API */
const apiFor = (fetchImpl: typeof fetch) =>
  recommendationsApi(createHttpClient({ baseUrl: '/api', fetch: fetchImpl, getToken: () => 'test-token' }));

const run = {
  recommendation_run_id: '00000000-0000-4000-8000-000000000a01',
  status: 'completed',
  // T45 실제 규칙 기준선 버전 (backend/app/repositories/recommendation_runs.py)
  model_version: { model_code: 'skill_overlap_baseline', version: 'skill-overlap-draft-v2', kind: 'rule' },
  generated_at: '2026-11-06T03:10:00Z',
  items: [],
};

describe('recommendations API client (OpenAPI contract)', () => {
  it('GET /api/v1/recommendation-runs/latest with the bearer token', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(200, run));
    await expect(apiFor(fetchImpl).findLatest()).resolves.toEqual(run);

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/recommendation-runs/latest');
    expect(init).toMatchObject({ method: 'GET', headers: expect.objectContaining({ Authorization: 'Bearer test-token' }) });
  });

  it('maps 404 (no recommendation yet) to null and rethrows other errors', async () => {
    const notFound = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(404, { code: 'NOT_FOUND' }));
    await expect(apiFor(notFound).findLatest()).resolves.toBeNull();

    const serverError = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(500, {}));
    await expect(apiFor(serverError).findLatest()).rejects.toMatchObject({ status: 500 });

    const unauthorized = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(401, { code: 'UNAUTHENTICATED' }));
    await expect(apiFor(unauthorized).findLatest()).rejects.toMatchObject({ status: 401 });
  });

  it('POST /api/v1/recommendation-runs with {limit}', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(201, run));
    await apiFor(fetchImpl).create({ limit: 10 });

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/recommendation-runs');
    expect(init).toMatchObject({ method: 'POST', body: JSON.stringify({ limit: 10 }) });
  });

  it('defaults limit to 20 and encodes ids in paths', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(201, run));
    await apiFor(fetchImpl).create();
    expect(fetchImpl.mock.calls[0]?.[1]).toMatchObject({ body: JSON.stringify({ limit: 20 }) });

    await apiFor(fetchImpl).get('a/b');
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
    await expect(apiFor(fetchImpl).sendFeedback(body)).resolves.toEqual(saved);

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
      model_version: { ...MOCK_RULE_MODEL },
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
    await expect(mockHttp().request('/v1/recommendation-runs/latest')).rejects.toMatchObject({ status: 401 });

    const login = await mockHttp().request<{ access_token: string }>('/v1/auth/login', {
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const user = mockHttp(login.access_token);
    await expect(
      user.request('/v1/recommendation-runs', { method: 'POST', body: { limit: 0 } }),
    ).rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(
      user.request('/v1/recommendation-runs', { method: 'POST', body: { limit: 51 } }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('validates feedback input (422) and hides postings outside my runs (404)', async () => {
    resetRecommendationMock();
    const login = await mockHttp().request<{ access_token: string }>('/v1/auth/login', {
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const user = mockHttp(login.access_token);
    const post = (body: unknown) =>
      user.request('/v1/recommendation-feedback', { method: 'POST', body });
    const posting = '00000000-0000-4000-8000-000000000101';

    await expect(
      mockHttp().request('/v1/recommendation-feedback', { method: 'POST', body: { job_posting_id: posting, feedback: 'liked' } }),
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

  it('excludes not_interested postings from the next run in both completed and fallback runs (T45 + T47)', async () => {
    resetRecommendationMock();
    const login = await mockHttp().request<{ access_token: string }>('/v1/auth/login', {
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const user = mockHttp(login.access_token);
    const create = () => user.request<RecommendationRun>('/v1/recommendation-runs', { method: 'POST', body: {} });
    const posting = '00000000-0000-4000-8000-000000000101';

    setRecommendationMockScenario({ create: 'fallback' });
    const before = await create();
    expect(before.items.map((entry) => entry.job_posting.job_posting_id)).toContain(posting);
    await user.request('/v1/recommendation-feedback', {
      method: 'POST',
      body: { recommendation_run_id: before.recommendation_run_id, job_posting_id: posting, feedback: 'not_interested' },
    });

    const fallback = await create();
    expect(fallback.items.map((entry) => entry.job_posting.job_posting_id)).not.toContain(posting);
    expect(fallback.items.map((entry) => entry.rank)).toEqual(fallback.items.map((_, index) => index + 1));

    setRecommendationMockScenario({ create: 'completed' });
    const completed = await create();
    expect(completed.items.map((entry) => entry.job_posting.job_posting_id)).not.toContain(posting);
    resetRecommendationMock();
  });

  it('follows the T45 response shape: same rule model for completed and fallback, fallback reason, empty fallback, 503', async () => {
    resetRecommendationMock();
    const login = await mockHttp().request<{ access_token: string }>('/v1/auth/login', {
      method: 'POST',
      body: { email: 'user@example.com', password: MOCK_PASSWORD },
    });
    const user = mockHttp(login.access_token);
    const create = () =>
      recommendationsApi(user).create({ limit: 20 });

    const completed = await create();
    expect(completed.status).toBe('completed');
    expect(completed.model_version).toEqual(MOCK_RULE_MODEL);
    expect(completed.items.every((item) => item.feedback !== 'not_interested')).toBe(true);

    setRecommendationMockScenario({ create: 'fallback' });
    const fallback = await create();
    expect(fallback.model_version).toEqual(MOCK_RULE_MODEL);
    expect(fallback.items.every((item) => item.score === null && item.reason === MOCK_FALLBACK_REASON)).toBe(true);

    setRecommendationMockScenario({ create: 'fallback_empty' });
    await expect(create()).resolves.toMatchObject({ status: 'fallback', items: [] });

    setRecommendationMockScenario({ create: 'unavailable' });
    await expect(create()).rejects.toMatchObject({ status: 503, code: 'DEPENDENCY_UNAVAILABLE' });
    resetRecommendationMock();
  });
});
