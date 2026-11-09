import type { ApiRequestOptions } from './client';
import { ApiError } from './errors';

/*
 * 맞춤 공고 추천 API (UI-017, FR-ANL-003). docs/api/openapi.yaml 의
 * RecommendationRun / RecommendationItem / JobPostingSummary / ModelVersionRef 를 그대로 옮긴 타입입니다.
 * 실제 Backend 구현(T45)이 머지되기 전까지는 Mock(VITE_API_MOCK=true)으로만 검증합니다.
 */

/** 로그인 토큰을 붙여 호출하는 함수. 화면에서는 useAuth().request 를 넘깁니다. */
export type AuthedRequest = <T>(path: string, options?: ApiRequestOptions) => Promise<T>;

export type RecommendationRunStatus = 'completed' | 'fallback' | 'failed';
/** 이 공고에 대한 내 최신 피드백. cleared 는 서버에서 null 로 돌려줍니다. */
export type RecommendationFeedbackValue = 'liked' | 'not_interested';
export type ModelKind = 'rule' | 'ml' | 'llm';
export type EmploymentType = 'full_time' | 'contract' | 'intern' | 'part_time';

/** 결과 계산 기준. 화면에 "계산 기준" 으로 표시합니다. */
export interface ModelVersionRef {
  model_code: string;
  version: string;
  kind: ModelKind;
}

export interface CompanyRef {
  company_id: string;
  name: string;
}

export interface JobRoleRef {
  job_role_id: string;
  code: string;
  name: string;
}

export interface JobPostingSummary {
  job_posting_id: string;
  title: string;
  status: 'published' | 'closed';
  company: CompanyRef;
  job_role: JobRoleRef | null;
  employment_type: EmploymentType | null;
  location_text: string | null;
  published_at: string | null;
  expires_at: string | null;
}

export interface RecommendationItem {
  rank: number;
  /** 0~100 적합 점수. 확률이 아니며 null 이면 점수를 계산하지 않은 항목입니다. */
  score: number | null;
  reason: string;
  feedback: RecommendationFeedbackValue | null;
  job_posting: JobPostingSummary;
}

export interface RecommendationRun {
  recommendation_run_id: string;
  status: RecommendationRunStatus;
  model_version: ModelVersionRef;
  generated_at: string;
  items: RecommendationItem[];
}

export interface RecommendationRunRequest {
  /** 1~50, 기본 20 */
  limit?: number;
}

export const RECOMMENDATION_LIMIT_DEFAULT = 20;
export const RECOMMENDATION_LIMIT_MAX = 50;

const RUNS_PATH = '/v1/recommendation-runs';

/** GET /api/v1/recommendation-runs/latest — 다시 계산하지 않고 가장 최근 추천을 조회합니다. */
export const getLatestRecommendationRun = (request: AuthedRequest) =>
  request<RecommendationRun>(`${RUNS_PATH}/latest`);

/**
 * 최근 추천이 없으면(404) null 을 돌려줍니다. 화면은 null 일 때 "추천 받기" 버튼을 보여줍니다.
 * 401·5xx·네트워크 오류는 그대로 던집니다.
 */
export async function findLatestRecommendationRun(request: AuthedRequest): Promise<RecommendationRun | null> {
  try {
    return await getLatestRecommendationRun(request);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** POST /api/v1/recommendation-runs — 새 추천을 계산합니다(201). 계산 실패 시 status=fallback 으로 최신 공고를 돌려줍니다. */
export const createRecommendationRun = (
  request: AuthedRequest,
  body: RecommendationRunRequest = { limit: RECOMMENDATION_LIMIT_DEFAULT },
) => request<RecommendationRun>(RUNS_PATH, { method: 'POST', body });

/** GET /api/v1/recommendation-runs/{recommendation_run_id} */
export const getRecommendationRun = (request: AuthedRequest, recommendationRunId: string) =>
  request<RecommendationRun>(`${RUNS_PATH}/${encodeURIComponent(recommendationRunId)}`);

/**
 * 공고 상세 화면 경로(UI-012). 공고 상세 화면은 T24 범위이며,
 * API 경로 GET /api/v1/job-postings/{job_posting_id} 와 같은 이름으로 맞춥니다.
 */
export const jobPostingDetailPath = (jobPostingId: string) => `/job-postings/${encodeURIComponent(jobPostingId)}`;

/** POST 로 보낼 수 있는 피드백 값. cleared 는 이전 피드백 취소(정정)이며 조회 응답에서는 null 로 바뀝니다. */
export type RecommendationFeedbackChoice = RecommendationFeedbackValue | 'cleared';

/** OpenAPI RecommendationFeedbackInput (additionalProperties: false) */
export interface RecommendationFeedbackInput {
  recommendation_run_id?: string;
  job_posting_id: string;
  feedback: RecommendationFeedbackChoice;
}

/** OpenAPI RecommendationFeedback (201) */
export interface RecommendationFeedback {
  feedback_id: string;
  job_posting_id: string;
  feedback: RecommendationFeedbackChoice;
  created_at: string;
}

/**
 * POST /api/v1/recommendation-feedback — 추천 공고 피드백을 이력으로 추가합니다(201, T47).
 * 피드백은 내 다음 추천을 개선하는 데에만 쓰입니다.
 */
export const createRecommendationFeedback = (request: AuthedRequest, body: RecommendationFeedbackInput) =>
  request<RecommendationFeedback>('/v1/recommendation-feedback', { method: 'POST', body });

/** 저장한 피드백을 추천 결과에 반영합니다(재조회에 실패했을 때의 보정). cleared 는 null 로 바꿉니다. */
export function applyFeedbackToRun(
  run: RecommendationRun,
  saved: Pick<RecommendationFeedback, 'job_posting_id' | 'feedback'>,
): RecommendationRun {
  const feedback = saved.feedback === 'cleared' ? null : saved.feedback;
  return {
    ...run,
    items: run.items.map((item) =>
      item.job_posting.job_posting_id === saved.job_posting_id ? { ...item, feedback } : item,
    ),
  };
}
