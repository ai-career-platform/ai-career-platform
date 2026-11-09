import { ApiError } from '../api/errors';
import type {
  JobPostingSummary,
  RecommendationFeedback,
  RecommendationFeedbackChoice,
  RecommendationFeedbackValue,
  RecommendationItem,
  RecommendationRun,
} from '../api/recommendations';

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
  /**
   * POST /recommendation-feedback 응답: 저장(201) / 서버 오류(500) / 세션 만료(401)
   * / 내 추천에 없는 공고(404 NOT_FOUND) / 입력값 오류(422 VALIDATION_FAILED) (T48)
   */
  feedback: 'saved' | 'error' | 'unauthorized' | 'notFound' | 'invalid';
  /** GET /recommendation-runs/{id} 응답: 정상 / 서버 오류(500). 피드백 저장 후 재조회 실패 검증용 (T48) */
  runById: 'ok' | 'error';
}

const defaultScenario: RecommendationMockScenario = {
  latest: 'personalized',
  create: 'completed',
  feedback: 'saved',
  runById: 'ok',
};
let scenario: RecommendationMockScenario = { ...defaultScenario };
/** 사용자별로 POST 로 만든 최근 추천 (Mock 메모리. 새로고침하면 사라집니다) */
let createdRuns = new Map<string, RecommendationRun>();
let runSequence = 0;
/** 사용자별·공고별 최신 피드백 기록 (D07 "공고별 최신 행이 현재 값"). Mock 메모리입니다. */
let feedbackStore = new Map<string, Map<string, RecommendationFeedback>>();
let feedbackSequence = 0;
/** 테스트에서 호출 순서·본문을 확인할 수 있도록 받은 추천 관련 요청을 순서대로 남깁니다 (가상 데이터만 담깁니다). */
export const recommendationMockLog: { method: string; path: string; body: unknown }[] = [];

export function setRecommendationMockScenario(next: Partial<RecommendationMockScenario>) {
  scenario = { ...scenario, ...next };
}

export function resetRecommendationMock() {
  scenario = { ...defaultScenario };
  createdRuns = new Map();
  runSequence = 0;
  feedbackStore = new Map();
  feedbackSequence = 0;
  recommendationMockLog.length = 0;
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

const notFound = (): never => {
  throw new ApiError(404, '', undefined, 'NOT_FOUND');
};
const validationFailed = (): never => {
  throw new ApiError(422, '', undefined, 'VALIDATION_FAILED');
};

/** 저장된 최신 피드백을 추천 항목에 반영합니다. cleared 는 null 로 돌려줍니다 (RecommendationItem.feedback 계약). */
function currentFeedback(email: string, item: RecommendationItem): RecommendationFeedbackValue | null {
  const saved = feedbackStore.get(email)?.get(item.job_posting.job_posting_id);
  if (!saved) return item.feedback;
  return saved.feedback === 'cleared' ? null : saved.feedback;
}

const withFeedback = (email: string, source: RecommendationRun): RecommendationRun => ({
  ...source,
  items: source.items.map((item) => ({ ...item, feedback: currentFeedback(email, item) })),
});

/** 이 사용자가 볼 수 있는 추천 실행 (Mock 에서는 가상 seed 실행 2개 + POST 로 만든 실행) */
const visibleRuns = (email: string) =>
  [createdRuns.get(email), seededRun(), seededFallbackRun()].filter((candidate): candidate is RecommendationRun => !!candidate);

function latestFor(email: string): RecommendationRun {
  const created = createdRuns.get(email);
  if (created) return withFeedback(email, created);
  if (scenario.latest === 'error') throw new ApiError(500, '');
  if (scenario.latest === 'unauthorized') throw new ApiError(401, '', undefined, 'UNAUTHENTICATED');
  if (scenario.latest === 'none') return notFound();
  return withFeedback(email, scenario.latest === 'fallback' ? seededFallbackRun() : seededRun());
}

function createFor(email: string, body: unknown): RecommendationRun {
  const { limit = 20 } = (body ?? {}) as { limit?: unknown };
  if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > 50) {
    return validationFailed();
  }
  if (scenario.create === 'error') throw new ApiError(500, '');
  runSequence += 1;
  const id = `00000000-0000-4000-8000-000000000b${String(runSequence).padStart(2, '0')}`;
  const generatedAt = new Date(Date.UTC(2026, 10, 9, 1, runSequence)).toISOString();
  // FR-ANL-004: 최신 피드백이 not_interested 인 공고는 다음 추천에서 제외합니다.
  const personalized = personalizedItems
    .filter((item) => currentFeedback(email, item) !== 'not_interested')
    .slice(0, limit)
    .map((item, index) => ({ ...item, rank: index + 1 }));
  const created =
    scenario.create === 'failed'
      ? run(id, 'failed', [], generatedAt)
      : scenario.create === 'fallback'
        ? run(id, 'fallback', fallbackItems.slice(0, limit), generatedAt)
        : run(id, 'completed', personalized, generatedAt);
  createdRuns.set(email, created);
  return withFeedback(email, created);
}

/** OpenAPI `Uuid` (format: uuid). T47 Backend 는 pydantic UUID 로 검증해 형식이 틀리면 422 입니다. */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isUuid = (value: unknown): value is string => typeof value === 'string' && UUID_PATTERN.test(value);

const FEEDBACK_KEYS = new Set(['recommendation_run_id', 'job_posting_id', 'feedback']);
const FEEDBACK_VALUES: readonly RecommendationFeedbackChoice[] = ['liked', 'not_interested', 'cleared'];

/** POST /v1/recommendation-feedback (RecommendationFeedbackInput → 201 RecommendationFeedback). T47 계약을 따릅니다. */
function createFeedbackFor(email: string, body: unknown): RecommendationFeedback {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return validationFailed();
  const input = body as Record<string, unknown>;
  if (Object.keys(input).some((key) => !FEEDBACK_KEYS.has(key))) return validationFailed();
  const { recommendation_run_id: runId, job_posting_id: postingId, feedback } = input;
  // 형식 검증(422)은 소유권·존재 확인(404)보다 먼저 합니다.
  if (!isUuid(postingId)) return validationFailed();
  if (!FEEDBACK_VALUES.includes(feedback as RecommendationFeedbackChoice)) return validationFailed();
  if ('recommendation_run_id' in input && !isUuid(runId)) return validationFailed();

  if (scenario.feedback === 'unauthorized') throw new ApiError(401, '', undefined, 'UNAUTHENTICATED');
  if (scenario.feedback === 'error') throw new ApiError(500, '');
  if (scenario.feedback === 'invalid') return validationFailed();
  if (scenario.feedback === 'notFound') return notFound();

  // 내 추천 실행에 있던 공고에만 남깁니다. 다른 사람 실행·없는 공고는 모두 404 (API_CONTRACT §1.3).
  const runs = visibleRuns(email);
  const scope = typeof runId === 'string' ? runs.filter((candidate) => candidate.recommendation_run_id === runId) : runs;
  if (scope.length === 0) return notFound();
  if (!scope.some((candidate) => candidate.items.some((item) => item.job_posting.job_posting_id === postingId))) {
    return notFound();
  }

  const perUser = feedbackStore.get(email) ?? new Map<string, RecommendationFeedback>();
  feedbackStore.set(email, perUser);
  const latest = perUser.get(postingId);
  // 같은 값을 다시 보내면 새 기록을 만들지 않고 최신 기록을 돌려줍니다 (멱등, T47).
  if (latest && latest.feedback === feedback) return latest;

  feedbackSequence += 1;
  const saved: RecommendationFeedback = {
    feedback_id: `00000000-0000-4000-8000-000000000c${String(feedbackSequence).padStart(2, '0')}`,
    job_posting_id: postingId,
    feedback: feedback as RecommendationFeedbackChoice,
    created_at: new Date(Date.UTC(2026, 10, 9, 2, feedbackSequence)).toISOString(),
  };
  perUser.set(postingId, saved);
  return saved;
}

/** handlers.ts 의 resolveMock 에서 로그인 사용자 email 과 함께 호출합니다. 해당 경로가 아니면 null. */
export function resolveRecommendationMock(path: string, method: string, body: unknown, email: string): unknown {
  recommendationMockLog.push({ method, path, body: structuredClone(body) });
  if (method === 'POST' && path === '/v1/recommendation-feedback') return createFeedbackFor(email, body);
  if (method === 'GET' && path === '/v1/recommendation-runs/latest') return latestFor(email);
  if (method === 'POST' && path === '/v1/recommendation-runs') return createFor(email, body);
  if (method === 'GET' && path.startsWith('/v1/recommendation-runs/')) {
    if (scenario.runById === 'error') throw new ApiError(500, '');
    const id = decodeURIComponent(path.slice('/v1/recommendation-runs/'.length));
    const found = visibleRuns(email).find((candidate) => candidate.recommendation_run_id === id);
    return found ? withFeedback(email, found) : notFound();
  }
  return null;
}
