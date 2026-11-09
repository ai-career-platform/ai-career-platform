/// <reference types="node" />
// T48 opt-in real Backend E2E: T45 recommendation runs -> T47 feedback API -> T48 components.
// Runs only when T48_REAL_API_ORIGIN points to a loopback Backend backed by a DISPOSABLE PostgreSQL.
// It creates synthetic users, so never point it at Staging or any shared database.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { env as processEnv } from 'node:process';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/errors';
import { createHttpClient, type HttpClient } from '../api/http';
import { recommendationsApi, type RecommendationRun } from '../api/recommendations';
import type { RequestFn } from '../test/api';
import { WithApi } from '../test/WithApi';
import { RecommendationFeedbackActions } from './RecommendationFeedbackActions';

const origin = processEnv.T48_REAL_API_ORIGIN;
const STAMP = Date.now().toString(36);
const PASSWORD = 'synthetic-e2e-password-1';
const CONSENTS = [
  { policy_code: 'terms', policy_version: '2026-11', granted: true },
  { policy_code: 'privacy', policy_version: '2026-11', granted: true },
];
// Synthetic postings inserted by the E2E setup (PYTHON only, expires_at NULL).
const P1 = '00000000-0000-4000-8000-000000004801';

async function signUp(name: string): Promise<HttpClient> {
  const anonymous = createHttpClient({ baseUrl: `${origin}/api` });
  const { access_token: token } = await anonymous.request<{ access_token: string }>('/v1/auth/signup', {
    method: 'POST', token: null,
    body: { email: `t48-${name}-${STAMP}@example.invalid`, password: PASSWORD, display_name: `T48 ${name}`, consents: CONSENTS },
  });
  const http = createHttpClient({ baseUrl: `${origin}/api`, getToken: () => token });
  const skills = await http.request<{ items: { skill_id: string; code: string }[] }>('/v1/skills', { query: { q: 'Python' } });
  const python = skills.items.find((s) => s.code === 'PYTHON');
  if (!python) throw new Error('PYTHON skill missing from seed');
  await http.request('/v1/me/skills', { method: 'PUT', body: { items: [{ skill_id: python.skill_id, proficiency: 3 }] } });
  return http;
}

const ids = (run: RecommendationRun) => run.items.map((i) => i.job_posting.job_posting_id);
const itemOf = (run: RecommendationRun, id: string) => {
  const found = run.items.find((i) => i.job_posting.job_posting_id === id);
  if (!found) throw new Error(`posting ${id} not in run`);
  return found;
};

describe.skipIf(!origin)('T48 real Backend E2E (T45 -> T47 -> T48, disposable PostgreSQL only)', () => {
  beforeAll(() => {
    const url = new URL(origin!);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.protocol !== 'http:'
      || url.pathname !== '/' || url.username || url.password) {
      throw new Error('T48 E2E requires a loopback http Backend origin');
    }
  });

  it('explains, saves, corrects and clears feedback against real T45/T47 and drives the next run', async () => {
    const alice = await signUp('alice');
    const api = recommendationsApi(alice);
    expect(await api.findLatest()).toBeNull(); // T45 GET latest: 404 -> null

    const run1 = await api.create({ limit: 50 });
    expect(run1.status).toBe('completed');
    expect(ids(run1)).toContain(P1);
    expect(itemOf(run1, P1).feedback).toBeNull();

    // T48 components on real data: explanation dialog, then liked through the real API.
    const onRunChange = vi.fn<(next: RecommendationRun) => void>();
    const request: RequestFn = (path, init) => alice.request(path, init);
    render(<WithApi request={request}>
      <RecommendationFeedbackActions item={itemOf(run1, P1)} run={run1} onRunChange={onRunChange} />
    </WithApi>);
    const title = itemOf(run1, P1).job_posting.title;
    fireEvent.click(screen.getByRole('button', { name: `${title} 추천 설명 보기` }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(itemOf(run1, P1).reason)).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/skill_overlap_baseline|skill-overlap-draft-v2/);
    expect(dialog).toHaveTextContent('합격 가능성(확률)이 아닙니다');
    expect(dialog).toHaveTextContent('부족 역량 정보 없음');
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '관심 있음' }));
    await waitFor(() => expect(onRunChange).toHaveBeenCalledTimes(1));
    expect(itemOf(onRunChange.mock.calls[0]![0], P1).feedback).toBe('liked'); // re-fetched from T45 GET
    expect(screen.getByText('관심 있음으로 저장했어요.')).toBeInTheDocument();
    expect(itemOf(await api.get(run1.recommendation_run_id), P1).feedback).toBe('liked');
    expect(itemOf(await api.latest(), P1).feedback).toBe('liked');

    // Idempotent same value: same feedback row.
    const again = await api.sendFeedback({ recommendation_run_id: run1.recommendation_run_id, job_posting_id: P1, feedback: 'liked' });
    const third = await api.sendFeedback({ recommendation_run_id: run1.recommendation_run_id, job_posting_id: P1, feedback: 'liked' });
    expect(third.feedback_id).toBe(again.feedback_id);

    // Correction -> excluded from the next T45 run.
    await api.sendFeedback({ recommendation_run_id: run1.recommendation_run_id, job_posting_id: P1, feedback: 'not_interested' });
    expect(itemOf(await api.get(run1.recommendation_run_id), P1).feedback).toBe('not_interested');
    const run2 = await api.create({ limit: 50 });
    expect(ids(run2)).not.toContain(P1);

    // Cleared -> no longer in the exclusion set; P1 (score 100, lowest id) is a candidate again.
    await api.sendFeedback({ recommendation_run_id: run1.recommendation_run_id, job_posting_id: P1, feedback: 'cleared' });
    expect(itemOf(await api.get(run1.recommendation_run_id), P1).feedback).toBeNull();
    const run3 = await api.create({ limit: 50 });
    expect(ids(run3)).toContain(P1);
    expect(itemOf(run3, P1).feedback).toBeNull();
  });

  it('enforces ownership (404), validation (422) and authentication (401) on the real API', async () => {
    const alice = await signUp('owner');
    const bob = await signUp('other');
    const run = await recommendationsApi(alice).create({ limit: 50 });
    const bobApi = recommendationsApi(bob);
    await expect(bobApi.get(run.recommendation_run_id)).rejects.toMatchObject({ status: 404 });
    await expect(bobApi.sendFeedback({ recommendation_run_id: run.recommendation_run_id, job_posting_id: P1, feedback: 'liked' }))
      .rejects.toMatchObject({ status: 404 });
    const aliceApi = recommendationsApi(alice);
    await expect(aliceApi.sendFeedback({ job_posting_id: P1, feedback: 'love' as never }))
      .rejects.toMatchObject({ status: 422, code: 'VALIDATION_FAILED' });
    await expect(alice.request('/v1/recommendation-feedback', { method: 'POST',
      body: { job_posting_id: P1, feedback: 'liked', user_id: '00000000-0000-4000-8000-000000000001' } }))
      .rejects.toMatchObject({ status: 422 });
    const anonymous = recommendationsApi(createHttpClient({ baseUrl: `${origin}/api` }));
    await expect(anonymous.sendFeedback({ job_posting_id: P1, feedback: 'liked' })).rejects.toMatchObject({ status: 401 });
  });

  it('recovers in the UI after a network failure: alert with retry, then saves on the real API', async () => {
    const alice = await signUp('recover');
    const run = await recommendationsApi(alice).create({ limit: 50 });
    let offline = true;
    const request: RequestFn = (path, init) => offline && init?.method === 'POST'
      ? Promise.reject(new ApiError(0, path, 'Network error')) : alice.request(path, init);
    const onRunChange = vi.fn<(next: RecommendationRun) => void>();
    render(<WithApi request={request}>
      <RecommendationFeedbackActions item={itemOf(run, P1)} run={run} onRunChange={onRunChange} />
    </WithApi>);
    fireEvent.click(screen.getByRole('button', { name: '관심 없음' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('피드백을 저장하지 못했습니다');
    expect(onRunChange).not.toHaveBeenCalled();
    offline = false;
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(onRunChange).toHaveBeenCalledTimes(1));
    expect(itemOf(onRunChange.mock.calls[0]![0], P1).feedback).toBe('not_interested');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
