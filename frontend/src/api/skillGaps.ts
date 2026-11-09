import type { AuthContextValue } from '../auth/useAuth';

// T06 SkillGap schema. Runtime wiring waits for the T43 provider.
export interface SkillGapItem {
  skill: { skill_id: string; code: string; name: string };
  required_level: number;
  observed_level: number;
  gap: number;
}

export interface SkillGap {
  assessment_id: string;
  job_role: { job_role_id: string; code: string; name: string };
  model_version: { model_code: string; version: string; kind: 'rule' };
  is_stale: boolean;
  evaluated_at: string;
  items: SkillGapItem[];
}

export interface SkillGapSummary {
  assessment_id: string;
  job_role: SkillGap['job_role'];
  missing_skill_count: number;
  total_gap: number;
  is_stale: boolean;
  evaluated_at: string;
}

export interface SkillGapSummaryPage {
  items: SkillGapSummary[];
  next_cursor: string | null;
}

export interface SkillGapHistoryQuery {
  job_role_id?: string;
  limit?: number;
  cursor?: string;
}

// Reuse T21's authenticated request, including its 401/session handling.
// The application must inject useAuth().request; no separate token storage.
export function createSkillGapApi(request: AuthContextValue['request']) {
  return {
    create: (job_role_id: string) => request<SkillGap>('/v1/skill-gaps', {
      method: 'POST', body: { job_role_id },
    }),
    get: (assessment_id: string) => request<SkillGap>(`/v1/skill-gaps/${encodeURIComponent(assessment_id)}`),
    list: (query: SkillGapHistoryQuery = {}) => {
      const params = new URLSearchParams();
      if (query.job_role_id !== undefined) params.set('job_role_id', query.job_role_id);
      if (query.limit !== undefined) params.set('limit', String(query.limit));
      if (query.cursor !== undefined) params.set('cursor', query.cursor);
      const search = params.toString();
      return request<SkillGapSummaryPage>(`/v1/skill-gaps${search ? `?${search}` : ''}`);
    },
  };
}
