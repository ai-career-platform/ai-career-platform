/** T32 synthetic-only state. No DB, real accounts or persistence. */
import { ApiError } from '../api/errors';
import type { ConsentPolicy, PrivacyConsent, DeletionRequest } from '../api/privacy';
import type { MockRequest } from './handlers';

const policies: ConsentPolicy[] = ['terms', 'privacy', 'llm_processing', 'behavior_tracking'].map(code => ({
  policy_code: code, version: '2026-11', is_required: code === 'terms' || code === 'privacy',
  content_url: `https://example.invalid/privacy/${code}`, effective_at: '2026-11-01T00:00:00Z',
}));
interface UserState { consents: PrivacyConsent[]; deletions: DeletionRequest[] }
const states = new Map<string, UserState>();
export function resetPrivacyMocks() { states.clear(); }
function userState(key: string): UserState {
  let state = states.get(key);
  if (!state) {
    state = { consents: policies.map(p => ({ consent_id: crypto.randomUUID(), is_required: p.is_required,
      policy_code: p.policy_code, policy_version: p.version, granted: p.policy_code !== 'behavior_tracking',
      recorded_at: '2026-11-01T00:00:00Z' })), deletions: [] };
    states.set(key, state);
  }
  return state;
}
export function resolvePrivacyMock(path: string, request: MockRequest, userKey: string | null): unknown {
  if (path === '/v1/consent-policies' && request.method === 'GET') return policies;
  if (!userKey) throw new ApiError(401, path, undefined, 'UNAUTHENTICATED');
  const state = userState(userKey);
  if (path === '/v1/me/consents') {
    if (request.method === 'GET') return state.consents;
    if (request.method === 'POST') {
      const input = request.body as Partial<PrivacyConsent> | null;
      const p = policies.find(policy => policy.policy_code === input?.policy_code);
      if (!p || p.is_required || input?.policy_version !== p.version || typeof input?.granted !== 'boolean') {
        throw new ApiError(422, path, undefined, 'VALIDATION_FAILED');
      }
      const latest = state.consents.find(c => c.policy_code === p.policy_code);
      if (latest?.policy_version === p.version && latest.granted === input.granted) return latest;
      const result: PrivacyConsent = { consent_id: crypto.randomUUID(), is_required: false,
        policy_code: p.policy_code, policy_version: p.version, granted: input.granted, recorded_at: new Date().toISOString() };
      state.consents.unshift(result);
      return result;
    }
  }
  if (path === '/v1/me/deletion-request') {
    const pending = state.deletions.find(d => d.status === 'requested');
    if (request.method === 'GET') {
      if (!pending) throw new ApiError(404, path, undefined, 'NOT_FOUND');
      return pending;
    }
    if (request.method === 'POST') {
      if ((request.body as {confirmation?: string})?.confirmation !== 'DELETE') throw new ApiError(422, path);
      if (pending) throw new ApiError(409, path, undefined, 'DELETION_ALREADY_REQUESTED');
      const result: DeletionRequest = { request_id: crypto.randomUUID(), status: 'requested',
        requested_at: new Date().toISOString(), scheduled_purge_at: null, completed_at: null };
      state.deletions.push(result);
      return result;
    }
    if (request.method === 'DELETE') {
      if (!pending) throw new ApiError(404, path, undefined, 'NOT_FOUND');
      pending.status = 'cancelled';
      return undefined;
    }
  }
  throw new ApiError(404, path);
}
