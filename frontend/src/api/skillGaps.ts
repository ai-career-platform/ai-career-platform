/**
 * Skill Gap API (T43, FR-ANL-002). 경로와 타입은 이 파일에만 둡니다.
 * 화면은 useApi().skillGaps 로 씁니다. 로그인 토큰과 401 처리는 AuthProvider 의 클라이언트가 맡습니다.
 */
import type { HttpClient } from './http';
import type { QueryOf, ResponseOf, Schemas } from './schema';

export type SkillGapItem = Schemas['SkillGapItem'];
export type SkillGap = ResponseOf<'getSkillGap'>;
export type SkillGapSummary = Schemas['SkillGapSummary'];
export type SkillGapSummaryPage = ResponseOf<'listMySkillGaps'>;
export type SkillGapHistoryQuery = QueryOf<'listMySkillGaps'>;

export const skillGapsApi = (http: HttpClient) => ({
  /** 목표 직무 기준으로 새로 계산해 저장합니다. 본문에는 job_role_id 만 보냅니다. */
  create: (job_role_id: string) =>
    http.request<SkillGap>('/v1/skill-gaps', { method: 'POST', body: { job_role_id } }),
  get: (assessmentId: string, signal?: AbortSignal) =>
    http.request<SkillGap>(`/v1/skill-gaps/${encodeURIComponent(assessmentId)}`, { signal }),
  /** 본인 이력(최신순). limit·cursor 를 주지 않으면 서버 기본값을 따릅니다. */
  list: (query: SkillGapHistoryQuery = {}, signal?: AbortSignal) =>
    http.request<SkillGapSummaryPage>('/v1/skill-gaps', { query, signal }),
});
