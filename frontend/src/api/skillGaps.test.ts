import { describe, expect, it, vi } from 'vitest';
import type { AuthContextValue } from '../auth/useAuth';
import { createSkillGapApi } from './skillGaps';

describe('T44 Skill Gap API contract', () => {
  function setup() {
    const request = vi.fn<AuthContextValue['request']>();
    const authenticatedRequest: AuthContextValue['request'] = async <T>(path: string, options?: Parameters<AuthContextValue['request']>[1]) => await request(path, options) as T;
    return { request, api: createSkillGapApi(authenticatedRequest) };
  }

  it('uses authenticated request with only job_role_id in the create body', async () => {
    const { request, api } = setup();
    request.mockResolvedValue({ assessment_id: 'result-1' });
    await expect(api.create('role-1')).resolves.toEqual({ assessment_id: 'result-1' });
    expect(request).toHaveBeenCalledWith('/v1/skill-gaps', { method: 'POST', body: { job_role_id: 'role-1' } });
  });

  it('encodes result ID as one path segment', async () => {
    const { request, api } = setup();
    await api.get('id/with?reserved');
    expect(request).toHaveBeenCalledWith('/v1/skill-gaps/id%2Fwith%3Freserved', undefined);
  });

  it('preserves the role filter, limit and opaque cursor', async () => {
    const { request, api } = setup();
    const query = { job_role_id: 'role-1', limit: 20, cursor: 'a+b/c= &?' };
    await api.list(query);
    const path = request.mock.calls[0]![0];
    const url = new URL(path, 'https://example.test');
    expect(url.pathname).toBe('/v1/skill-gaps');
    expect(Object.fromEntries(url.searchParams)).toEqual({ ...query, limit: '20' });
  });

  it('leaves default pagination to the server and preserves empty cursor for validation', async () => {
    const { request, api } = setup();
    await api.list();
    expect(request).toHaveBeenLastCalledWith('/v1/skill-gaps', undefined);
    await api.list({ cursor: '' });
    expect(request).toHaveBeenLastCalledWith('/v1/skill-gaps?cursor=', undefined);
  });

  it.each([401, 404, 503])('propagates %s without replacing failure with fake results', async (status) => {
    const { request, api } = setup();
    const error = Object.assign(new Error('request failed'), { status });
    request.mockRejectedValue(error);
    await expect(api.create('role-1')).rejects.toBe(error);
  });
});
