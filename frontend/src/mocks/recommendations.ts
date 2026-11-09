import { ApiError } from '../api/errors';
import type { JobPostingSummary, RecommendationItem, RecommendationRun } from '../api/recommendations';

/**
 * 맞춤 추천 Mock (UI-017). T45 추천 실행 API 머지 전까지만 사용합니다.
 * 회사·공고는 모두 가상 데이터이며 실제 개인정보·운영 데이터를 넣지 않습니다.
 * Mock 성공은 실제 서비스 PASS가 아닙니다.
 */

export const MOCK_RULE_MODEL = { model_code: 'match_rule', version: '1', kind: 'rule' } as const;
export const MOCK_FALLBACK_MODEL = { model_code: 'latest_postings', version: '1', kind: 'rule' } as const;

const posting = (
  n: number,
  title: string,
  company: string,
  role: readonly [code: string, name: string] | null,
  location: string,
): JobPostingSummary => ({
  job_posting_id: `00000000-0000-4000-8000-0000000001${String(n).padStart(2, '0')}`,
  title,
  status: 'published',
  company: { company_id: `00000000-0000-4000-8000-0000000002${String(n).padStart(2, '0')}`, name: company },
  job_role: role
    ? { job_role_id: `00000000-0000-4000-8000-0000000003${String(n).padStart(2, '0')}`, code: role[0], name: role[1] }
    : null,
  employment_type: 'full_time',
  location_text: location,
  published_at: '2026-11-01T00:00:00Z',
  expires_at: null,
});

const BACKEND = ['backend', '백엔드 개발'] as const;
const postings: [JobPostingSummary, JobPostingSummary, JobPostingSummary, JobPostingSummary] = [
  posting(1, '백엔드 개발자 (신입)', '예시 테크', BACKEND, '서울'),
  posting(2, 'Python 서버 개발자', '노바랩', BACKEND, '판교'),
  posting(3, '데이터 엔지니어 (주니어)', '데이터포레스트', ['data_engineer', '데이터 엔지니어'], '서울'),
  posting(4, '프론트엔드 개발자', '넥스트웨이브', null, '서울'),
];

const personalizedItems: RecommendationItem[] = [
  { rank: 1, score: 82, reason: '목표 직무(백엔드 개발)와 일치하고 Python·SQL 요구 기술을 보유하고 있습니다.', feedback: null, job_posting: postings[0] },
  { rank: 2, score: 67.5, reason: 'Python 요구를 충족합니다. Docker 경험은 부족 역량으로 확인됩니다.', feedback: 'liked', job_posting: postings[1] },
  { rank: 3, score: 41, reason: 'SQL 요구를 충족하지만 목표 직무와 다른 직무입니다.', feedback: 'not_interested', job_posting: postings[2] },
];

const fallbackItems: RecommendationItem[] = postings.map((job_posting, index) => ({
  rank: index + 1,
  score: null,
  reason: '맞춤 추천을 준비하지 못해 최근 게시된 공고를 보여 드립니다.',
  feedback: null,
  job_posting,
}));

/** 화면 상태 검증용 Mock 시나리오. 테스트에서 setRecommendationMockScenario 로 바꿉니다. */
export interface RecommendationMockScenario {
  /** GET latest 응답: 기존 추천 있음 / 없음(404) / 기준 추천(fallback) / 서버 오류(500) / 세션 만료(401) */
  latest: 'personalized' | 'none' | 'fallback' | 'error' | 'unauthorized';
  /** POST 응답: 맞춤 추천 / 기준 추천 / 계산 실패 / 서버 오류(500) */
  create: 'completed' | 'fallback' | 'failed' | 'error';
}

const defaultScenario: RecommendationMockScenario = { latest: 'personalized', create: 'completed' };
let scenario: RecommendationMockScenario = { ...defaultScenario };
/** 사용자별로 POST 로 만든 최근 추천 (Mock 메모리. 새로고침하면 사라집니다) */
let createdRuns = new Map<string, RecommendationRun>();
let runSequence = 0;

export function setRecommendationMockScenario(next: Partial<RecommendationMockScenario>) {
  scenario = { ...scenario, ...next };
}

export function resetRecommendationMock() {
  scenario = { ...defaultScenario };
  createdRuns = new Map();
  runSequence = 0;
}

const run = (id: string, status: RecommendationRun['status'], items: RecommendationItem[], generatedAt: string): RecommendationRun => ({
  recommendation_run_id: id,
  status,
  model_version: status === 'fallback' ? { ...MOCK_FALLBACK_MODEL } : { ...MOCK_RULE_MODEL },
  generated_at: generatedAt,
  items,
});

const seededRun = () => run('00000000-0000-4000-8000-000000000a01', 'completed', personalizedItems, '2026-11-06T03:10:00Z');
const seededFallbackRun = () => run('00000000-0000-4000-8000-000000000a02', 'fallback', fallbackItems, '2026-11-06T03:10:00Z');

function latestFor(email: string): RecommendationRun {
  const created = createdRuns.get(email);
  if (created) return created;
  if (scenario.latest === 'error') throw new ApiError(500, '');
  if (scenario.latest === 'unauthorized') throw new ApiError(401, '', undefined, 'UNAUTHENTICATED');
  if (scenario.latest === 'none') throw new ApiError(404, '', undefined, 'NOT_FOUND');
  return scenario.latest === 'fallback' ? seededFallbackRun() : seededRun();
}

function createFor(email: string, body: unknown): RecommendationRun {
  const { limit = 20 } = (body ?? {}) as { limit?: unknown };
  if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new ApiError(422, '', undefined, 'VALIDATION_FAILED');
  }
  if (scenario.create === 'error') throw new ApiError(500, '');
  runSequence += 1;
  const id = `00000000-0000-4000-8000-000000000b${String(runSequence).padStart(2, '0')}`;
  const generatedAt = new Date(Date.UTC(2026, 10, 9, 1, runSequence)).toISOString();
  const created =
    scenario.create === 'failed'
      ? run(id, 'failed', [], generatedAt)
      : scenario.create === 'fallback'
        ? run(id, 'fallback', fallbackItems.slice(0, limit), generatedAt)
        : run(id, 'completed', personalizedItems.slice(0, limit).map((item) => ({ ...item, feedback: item.feedback === 'not_interested' ? null : item.feedback })), generatedAt);
  createdRuns.set(email, created);
  return created;
}

/** handlers.ts 의 resolveMock 에서 로그인 사용자 email 과 함께 호출합니다. 해당 경로가 아니면 null. */
export function resolveRecommendationMock(path: string, method: string, body: unknown, email: string): unknown {
  if (method === 'GET' && path === '/v1/recommendation-runs/latest') return latestFor(email);
  if (method === 'POST' && path === '/v1/recommendation-runs') return createFor(email, body);
  if (method === 'GET' && path.startsWith('/v1/recommendation-runs/')) {
    const id = decodeURIComponent(path.slice('/v1/recommendation-runs/'.length));
    const candidates = [createdRuns.get(email), seededRun(), seededFallbackRun()];
    const found = candidates.find((candidate) => candidate?.recommendation_run_id === id);
    if (!found) throw new ApiError(404, '', undefined, 'NOT_FOUND');
    return found;
  }
  return null;
}
