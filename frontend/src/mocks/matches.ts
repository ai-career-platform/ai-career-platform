/**
 * T42 개발용 가상 데이터 — 적합도 API(T41 POST/GET /v1/matches).
 * 점수는 계산하지 않고 고정 fixture(계약 예시와 같은 값)를 돌려줍니다. Mock 성공은 실제 서비스 PASS가 아닙니다.
 */
import { ApiError } from '../api/errors';
import type { Match } from '../api/matches';
import type { MockRequest } from './handlers';
import { mockSkillCount } from './skills';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const results = new Map<string, { owner: string; match: Match }>();
let sequence = 0;
export function resetMatchMocks() { results.clear(); sequence = 0; }

const fail = (status: number, code: string): never => { throw new ApiError(status, '', undefined, code); };

/** 계약(openapi.yaml createMatch 201 example)과 같은 고정 결과. */
export function fixtureMatch(matchId: string, target: Match['target']): Match {
  return {
    match_id: matchId, target, status: 'completed', score: 62.5, score_is_probability: false,
    matched_skill_count: 5, missing_skill_count: 3,
    model_version: { model_code: 'match_rule', version: '1', kind: 'rule' },
    limitations: ['자기평가 숙련도 기준이며 채용 결과를 예측하지 않습니다.'],
    evaluated_at: '2026-11-06T03:00:00Z',
  };
}

export function resolveMatchesMock(path: string, request: MockRequest, userKey: string): unknown {
  if (path === '/v1/matches' && request.method === 'POST') {
    const body = (request.body ?? {}) as Record<string, unknown>;
    const keys = Object.keys(body);
    const id = body.job_posting_id ?? body.job_role_id;
    if (keys.length !== 1 || !['job_posting_id', 'job_role_id'].includes(keys[0]!) || typeof id !== 'string' || !UUID.test(id)) {
      return fail(422, 'VALIDATION_FAILED');
    }
    if (mockSkillCount(userKey) === 0) return fail(400, 'NO_USER_SKILLS');
    sequence += 1;
    const matchId = `90000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`;
    const match = fixtureMatch(matchId, {
      job_posting_id: 'job_posting_id' in body ? id : null, job_role_id: 'job_role_id' in body ? id : null,
    });
    results.set(matchId, { owner: userKey, match });
    return match;
  }
  const found = /^\/v1\/matches\/([^/?]+)$/.exec(path);
  if (found && request.method === 'GET') {
    const saved = results.get(decodeURIComponent(found[1]!));
    return saved && saved.owner === userKey ? saved.match : fail(404, 'NOT_FOUND');
  }
  return null;
}
