import { describe, expect, it, vi } from 'vitest';
import { apiFrom, type RequestFn } from '../test/api';

describe('T44 Skill Gap API contract', () => {
  // 요청은 "경로+쿼리스트링" 한 줄과 나머지 옵션으로 받습니다 (test/api.ts).
  function setup() {
    const request = vi.fn<RequestFn>();
    return { request, api: apiFrom(request).skillGaps };
  }

  it('sends only job_role_id in the create body', async () => {
    const { request, api } = setup();
    request.mockResolvedValue({ assessment_id: 'result-1' });
    await expect(api.create('role-1')).resolves.toEqual({ assessment_id: 'result-1' });
    expect(request).toHaveBeenCalledWith('/v1/skill-gaps', { method: 'POST', body: { job_role_id: 'role-1' } });
  });

  it('encodes result ID as one path segment', async () => {
    const { request, api } = setup();
    await api.get('id/with?reserved');
    expect(request.mock.calls[0]![0]).toBe('/v1/skill-gaps/id%2Fwith%3Freserved');
  });

  it('preserves the role filter, limit and opaque cursor', async () => {
    const { request, api } = setup();
    const query = { job_role_id: 'role-1', limit: 20, cursor: 'a+b/c= &?' };
    await api.list(query);
    const url = new URL(request.mock.calls[0]![0], 'https://example.test');
    expect(url.pathname).toBe('/v1/skill-gaps');
    expect(Object.fromEntries(url.searchParams)).toEqual({ ...query, limit: '20' });
  });

  it('leaves default pagination to the server', async () => {
    const { request, api } = setup();
    await api.list();
    expect(request.mock.calls[0]![0]).toBe('/v1/skill-gaps');
    // 공통 규칙(http.ts buildQuery): 빈 값은 보내지 않습니다.
    await api.list({ cursor: '' });
    expect(request.mock.calls[1]![0]).toBe('/v1/skill-gaps');
  });

  it.each([401, 404, 503])('propagates %s without replacing failure with fake results', async (status) => {
    const { request, api } = setup();
    const error = Object.assign(new Error('request failed'), { status });
    request.mockRejectedValue(error);
    await expect(api.create('role-1')).rejects.toBe(error);
  });
});
