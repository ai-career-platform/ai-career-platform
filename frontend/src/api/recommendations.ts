import { ApiError } from './errors';
import type { HttpClient } from './http';
import type { ResponseOf, Schemas } from './schema';

/*
 * 맞춤 공고 추천 API (UI-017, FR-ANL-003). 타입은 docs/api/openapi.yaml 에서 생성한 타입
 * (RecommendationRun / RecommendationItem / JobPostingSummary / ModelVersionRef)입니다.
 * T45 Backend(backend/app/schemas/recommendation_runs.py, app/routers/recommendation_runs.py)와
 * 필드 이름·필수 여부·경로가 같습니다. T45 규칙 기준선은 completed·fallback 모두
 * model_version = skill_overlap_baseline / skill-overlap-draft-v2 (kind=rule) 을 돌려줍니다.
 * 화면은 useApi().recommendations 로 씁니다. 로그인 토큰과 401 처리는 AuthProvider 의 클라이언트가 맡습니다.
 */

export type RecommendationRun = ResponseOf<'getRecommendationRun'>;
export type RecommendationItem = Schemas['RecommendationItem'];
export type ModelVersionRef = Schemas['ModelVersionRef'];
export type JobPostingSummary = Schemas['JobPostingSummary'];
/**
 * 계약(openapi.yaml)의 status 전체. T45 Backend는 현재 completed·fallback 만 만들고 failed 는 만들지 않지만,
 * 계약에 있으므로 화면은 failed 도 처리합니다.
 */
export type RecommendationRunStatus = RecommendationRun['status'];
/** 이 공고에 대한 내 최신 피드백. cleared 는 서버에서 null 로 돌려줍니다. */
export type RecommendationFeedbackValue = NonNullable<RecommendationItem['feedback']>;
export type ModelKind = ModelVersionRef['kind'];
export type EmploymentType = NonNullable<JobPostingSummary['employment_type']>;
/** limit 1~50, 기본 20 */
export type RecommendationRunRequest = Partial<Schemas['RecommendationRunRequest']>;
/** OpenAPI RecommendationFeedbackInput (additionalProperties: false) */
export type RecommendationFeedbackInput = Schemas['RecommendationFeedbackInput'];
/** OpenAPI RecommendationFeedback (201) */
export type RecommendationFeedback = ResponseOf<'createRecommendationFeedback'>;
/** POST 로 보낼 수 있는 피드백 값. cleared 는 이전 피드백 취소(정정)이며 조회 응답에서는 null 로 바뀝니다. */
export type RecommendationFeedbackChoice = RecommendationFeedbackInput['feedback'];

export const RECOMMENDATION_LIMIT_DEFAULT = 20;
export const RECOMMENDATION_LIMIT_MAX = 50;

const RUNS_PATH = '/v1/recommendation-runs';

export const recommendationsApi = (http: HttpClient) => {
  /** GET /api/v1/recommendation-runs/latest — 다시 계산하지 않고 가장 최근 추천을 조회합니다. */
  const latest = (signal?: AbortSignal) => http.request<RecommendationRun>(`${RUNS_PATH}/latest`, { signal });
  return {
    latest,
    /**
     * 최근 추천이 없으면(404) null 을 돌려줍니다. 화면은 null 일 때 "추천 받기" 버튼을 보여줍니다.
     * 401·5xx·네트워크 오류는 그대로 던집니다.
     */
    findLatest: async (signal?: AbortSignal): Promise<RecommendationRun | null> => {
      try {
        return await latest(signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    /**
     * POST /api/v1/recommendation-runs — 새 추천을 계산합니다(201, Location 헤더는 쓰지 않음).
     * T45: 보유 기술이 없거나 기술을 비교할 공고가 없으면 status=fallback + 최신 공개 공고(score=null),
     * 공개 공고가 없으면 fallback + 빈 items. 관심 없음(최신 피드백) 공고는 제외됩니다. DB 오류는 503.
     */
    create: (body: RecommendationRunRequest = { limit: RECOMMENDATION_LIMIT_DEFAULT }) =>
      http.request<RecommendationRun>(RUNS_PATH, { method: 'POST', body }),
    /**
     * GET /api/v1/recommendation-runs/{recommendation_run_id} — 저장된 결과 읽기 전용. 다른 사용자 run 은 404.
     * T45: 이후 비공개·삭제된 공고 항목은 빠질 수 있어 rank 가 1부터 연속이 아닐 수 있습니다.
     */
    get: (recommendationRunId: string, signal?: AbortSignal) =>
      http.request<RecommendationRun>(`${RUNS_PATH}/${encodeURIComponent(recommendationRunId)}`, { signal }),
    /**
     * POST /api/v1/recommendation-feedback — 추천 공고 피드백을 이력으로 추가합니다(201, T47).
     * 피드백은 내 다음 추천을 개선하는 데에만 쓰입니다.
     */
    sendFeedback: (body: RecommendationFeedbackInput) =>
      http.request<RecommendationFeedback>('/v1/recommendation-feedback', { method: 'POST', body }),
  };
};

/**
 * 공고 상세 화면 경로(UI-012). 공고 상세 화면은 T24 범위이며,
 * API 경로 GET /api/v1/job-postings/{job_posting_id} 와 같은 이름으로 맞춥니다.
 */
export const jobPostingDetailPath = (jobPostingId: string) => `/job-postings/${encodeURIComponent(jobPostingId)}`;


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
