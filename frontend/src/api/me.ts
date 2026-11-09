/**
 * 로그인한 사용자 본인 API (/v1/me/*) 와 약관 정책.
 * 경로와 타입은 이 파일에만 둡니다. 화면은 createApi(http).me 로 씁니다.
 */
import type { HttpClient } from './http';
import type { BodyOf, ResponseOf, Schemas } from './schema';

export type Me = ResponseOf<'getMe'>;
export type Permissions = ResponseOf<'getMyPermissions'>;
/** 자기평가 숙련도 1~5 (계약의 Level: integer 1~5). null = 미입력 */
export type Proficiency = 1 | 2 | 3 | 4 | 5;
export type UserSkill = Omit<Schemas['UserSkill'], 'proficiency'> & { proficiency: Proficiency | null };
export type UserSkillsReplace = { items: { skill_id: string; proficiency: Proficiency | null }[] };
export type TargetRole = Schemas['TargetRole'];
export type Experience = Schemas['Experience'];
export type Project = Schemas['Project'];
export type ConsentPolicy = Schemas['ConsentPolicy'];
export type Consent = Schemas['Consent'];
export type DeletionRequest = Schemas['DeletionRequest'];

const id = (value: string) => encodeURIComponent(value);

export const meApi = (http: HttpClient) => ({
  profile: {
    get: (signal?: AbortSignal) => http.request<Me>('/v1/me', { signal }),
    update: (body: BodyOf<'updateMe'>) => http.request<Me>('/v1/me', { method: 'PATCH', body }),
    permissions: (signal?: AbortSignal) => http.request<Permissions>('/v1/me/permissions', { signal }),
  },
  skills: {
    list: (signal?: AbortSignal) => http.request<UserSkill[]>('/v1/me/skills', { signal }),
    replace: (body: UserSkillsReplace) =>
      http.request<UserSkill[]>('/v1/me/skills', { method: 'PUT', body }),
  },
  targetRoles: {
    list: (signal?: AbortSignal) => http.request<TargetRole[]>('/v1/me/target-roles', { signal }),
    replace: (body: BodyOf<'replaceMyTargetRoles'>) =>
      http.request<TargetRole[]>('/v1/me/target-roles', { method: 'PUT', body }),
  },
  experiences: {
    list: (signal?: AbortSignal) => http.request<Experience[]>('/v1/me/experiences', { signal }),
    create: (body: BodyOf<'createMyExperience'>) =>
      http.request<Experience>('/v1/me/experiences', { method: 'POST', body }),
    remove: (experienceId: string) =>
      http.request<undefined>(`/v1/me/experiences/${id(experienceId)}`, { method: 'DELETE' }),
  },
  projects: {
    list: (signal?: AbortSignal) => http.request<Project[]>('/v1/me/projects', { signal }),
    create: (body: BodyOf<'createMyProject'>) =>
      http.request<Project>('/v1/me/projects', { method: 'POST', body }),
    remove: (projectId: string) =>
      http.request<undefined>(`/v1/me/projects/${id(projectId)}`, { method: 'DELETE' }),
  },
  bookmarks: {
    list: (signal?: AbortSignal) => http.request<ResponseOf<'listMyBookmarks'>>('/v1/me/bookmarks', { signal }),
    add: (jobPostingId: string) =>
      http.request<undefined>(`/v1/me/bookmarks/${id(jobPostingId)}`, { method: 'PUT' }),
    remove: (jobPostingId: string) =>
      http.request<undefined>(`/v1/me/bookmarks/${id(jobPostingId)}`, { method: 'DELETE' }),
  },
  consents: {
    policies: (signal?: AbortSignal) => http.request<ConsentPolicy[]>('/v1/consent-policies', { signal }),
    list: (signal?: AbortSignal) => http.request<Consent[]>('/v1/me/consents', { signal }),
    record: (body: BodyOf<'recordMyConsent'>) =>
      http.request<Consent>('/v1/me/consents', { method: 'POST', body }),
  },
  deletion: {
    get: (signal?: AbortSignal) => http.request<DeletionRequest>('/v1/me/deletion-request', { signal }),
    request: (body: BodyOf<'requestMyDeletion'>) =>
      http.request<DeletionRequest>('/v1/me/deletion-request', { method: 'POST', body }),
    cancel: () => http.request<undefined>('/v1/me/deletion-request', { method: 'DELETE' }),
  },
});
