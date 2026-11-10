/**
 * T68 개발용 채용시장 추세 Mock (합성 값, 실제 시장·Staging 데이터 아님). Mock 성공은 실제 서비스 PASS가 아닙니다.
 * T67 동작을 흉내 냅니다: 기간 검사 422, 없는 직무·기술 404, skill_demand_share 는 skill_id 필수,
 * 관측 없는 구간은 응답에서 빠짐(0으로 채우지 않음), 관측이 없으면 source=null.
 */
import { ApiError } from '../api/errors';
import type { MarketMetricCode, MarketPeriod, MarketPoint, MarketTrend } from '../api/marketTrends';
import { MAX_BUCKETS, bucketCount, bucketsBetween, parseDate } from '../pages/marketTrendFormat';
import { mockSkillCatalog } from './skills';

const ROLES: Record<string, { code: string; name: string }> = {
  '11111111-1111-4111-8111-111111111111': { code: 'backend', name: '백엔드 개발자' },
  '22222222-2222-4222-8222-222222222222': { code: 'frontend', name: '프론트엔드 개발자' },
  // 데이터 엔지니어는 관측값이 없는 직무로 둡니다(빈 상태 확인용).
  '33333333-3333-4333-8333-333333333333': { code: 'data', name: '데이터 엔지니어' },
};
const SOURCE = { code: 'synthetic_mock', name: '합성 Mock 출처' };

const fail = (status: number, code: string): never => { throw new ApiError(status, '', undefined, code); };

/** 구간 순번으로 만든 결정적 합성 값. 7개 구간 중 하나는 관측을 빼서 빈 구간을 보여 줍니다. */
function series(buckets: string[], metric: MarketMetricCode, seed: number): MarketPoint[] {
  return buckets.flatMap((date, i) => {
    if ((i + seed) % 7 === 3) return [];
    const wave = Math.round(20 + seed * 3 + 8 * Math.sin((i + seed) / 2));
    const value = metric === 'posting_count' ? wave : Math.round((0.2 + 0.05 * Math.sin((i + seed) / 3)) * 10_000) / 10_000;
    return [{ date, value }];
  });
}

export function resolveMarketTrendsMock(path: string): MarketTrend | null {
  const url = new URL(path, 'http://mock.invalid');
  if (url.pathname !== '/v1/market-trends') return null;
  const q = url.searchParams;
  const metric = q.get('metric_code') as MarketMetricCode | null;
  const period = (q.get('period') ?? 'week') as MarketPeriod;
  const from = q.get('from') ?? '';
  const to = q.get('to') ?? '';
  const roleId = q.get('job_role_id');
  const skillId = q.get('skill_id');
  if (metric !== 'posting_count' && metric !== 'skill_demand_share') return fail(422, 'VALIDATION_FAILED');
  if (!['day', 'week', 'month'].includes(period) || !parseDate(from) || !parseDate(to) || from > to
    || bucketCount(from, to, period) > MAX_BUCKETS[period]) return fail(422, 'VALIDATION_FAILED');
  if ((metric === 'skill_demand_share') !== (skillId !== null)) return fail(422, 'VALIDATION_FAILED');
  const role = roleId ? ROLES[roleId] ?? fail(404, 'NOT_FOUND') : null;
  const skillIndex = skillId ? mockSkillCatalog.findIndex((s) => s.skill_id === skillId) : -1;
  const skill = skillId ? mockSkillCatalog[skillIndex] ?? fail(404, 'NOT_FOUND') : null;
  if (q.get('source') && q.get('source') !== SOURCE.code) return fail(404, 'NOT_FOUND');

  // T67 처럼 구간 시작일(observed_on)이 조회 기간 안인 구간만 돌려줍니다.
  const buckets = bucketsBetween(from, to, period).filter((date) => date >= from);
  const observations = role?.code === 'data' ? [] : series(buckets, metric, (roleId ? 2 : 0) + Math.max(skillIndex, 0));
  return {
    metric_code: metric,
    unit: metric === 'posting_count' ? 'count' : 'ratio',
    period, from, to,
    source: observations.length ? SOURCE : null,
    job_role: role && roleId ? { job_role_id: roleId, ...role } : null,
    skill: skill ? { skill_id: skill.skill_id, code: skill.code, name: skill.name } : null,
    observations,
    forecasts: [],
    forecast_model: null,
  };
}
