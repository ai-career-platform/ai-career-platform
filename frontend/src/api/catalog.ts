/**
 * 로그인 없이 볼 수 있는 카탈로그 API — 직무·기술(T17), 기업·공고(T18).
 * 경로와 타입은 이 파일에만 둡니다. 화면은 createApi(http).catalog 로 씁니다.
 */
import type { HttpClient } from './http';
import type { QueryOf, ResponseOf, Schemas } from './schema';
import type { SkillSuggestPage } from './skills';

export type JobRoleRef = Schemas['JobRoleRef'];
export type JobRolePage = ResponseOf<'listJobRoles'>;
export type JobRoleDetail = ResponseOf<'getJobRole'>;
export type Skill = Schemas['Skill'];
export type CompanyRef = Schemas['CompanyRef'];
export type CompanyPage = ResponseOf<'listCompanies'>;
export type CompanyDetail = ResponseOf<'getCompany'>;
export type JobPostingSummary = Schemas['JobPostingSummary'];
export type JobPostingPage = ResponseOf<'listJobPostings'>;

/**
 * 계약과 구현이 다른 부분 (backend/app/schemas/job_postings.py):
 * 공고 요구 기술의 required_level 은 실제로 null 일 수 있고(직무 기본값도 없을 때), is_required 는 항상 옵니다.
 * 계약(openapi.yaml)이 고쳐지면 이 보정을 지우세요.
 */
export type PostingRequiredSkill = Omit<Schemas['RequiredSkill'], 'required_level' | 'is_required'> & {
  required_level: number | null;
  is_required: boolean;
};
export type JobPostingDetail = Omit<ResponseOf<'getJobPosting'>, 'required_skills'> & {
  required_skills: PostingRequiredSkill[];
};

const id = (value: string) => encodeURIComponent(value);

export const catalogApi = (http: HttpClient) => ({
  jobRoles: {
    list: (query: QueryOf<'listJobRoles'>, signal?: AbortSignal) =>
      http.request<JobRolePage>('/v1/job-roles', { query, signal }),
    get: (jobRoleId: string, signal?: AbortSignal) =>
      http.request<JobRoleDetail>(`/v1/job-roles/${id(jobRoleId)}`, { signal }),
  },
  skills: {
    search: (query: QueryOf<'searchSkills'>, signal?: AbortSignal) =>
      http.request<ResponseOf<'searchSkills'>>('/v1/skills', { query, signal }),
    /** T139 자동완성(PROPOSED). openapi.yaml 에 아직 없어서 타입을 직접 둡니다(api/skills.ts). */
    suggest: (query: { q: string; limit?: number; cursor?: string }, signal?: AbortSignal) =>
      http.request<SkillSuggestPage>('/v1/skills/suggest', { query, signal }),
  },
  companies: {
    list: (query: QueryOf<'listCompanies'>, signal?: AbortSignal) =>
      http.request<CompanyPage>('/v1/companies', { query, signal }),
    get: (companyId: string, signal?: AbortSignal) =>
      http.request<CompanyDetail>(`/v1/companies/${id(companyId)}`, { signal }),
  },
  jobPostings: {
    list: (query: QueryOf<'listJobPostings'>, signal?: AbortSignal) =>
      http.request<JobPostingPage>('/v1/job-postings', { query, signal }),
    get: (jobPostingId: string, signal?: AbortSignal) =>
      http.request<JobPostingDetail>(`/v1/job-postings/${id(jobPostingId)}`, { signal }),
  },
});
