/**
 * 내 보유 기술 API (T33) · 기술 검색 API (T17). 타입은 docs/api/openapi.yaml 과 같습니다.
 * - GET /v1/me/skills          → UserSkill[] (이름순)
 * - PUT /v1/me/skills          → UserSkill[] (전체 교체, 빈 목록이면 모두 삭제)
 * - GET /v1/skills?q=&limit=   → { items: Skill[] } (활성 기술만, 2글자 이상)
 */
import type { ApiRequestOptions } from './client';

export interface Skill {
  skill_id: string;
  code: string;
  name: string;
}

/** 자기평가 숙련도 1~5. null = 미입력 (AI 분석 수치가 아님) */
export type Proficiency = 1 | 2 | 3 | 4 | 5;

export interface UserSkill {
  skill: Skill;
  proficiency: Proficiency | null;
}

export interface UserSkillsReplace {
  items: { skill_id: string; proficiency: Proficiency | null }[];
}

export const MAX_SKILLS = 100;
export const SEARCH_MIN_LENGTH = 2;
export const SEARCH_MAX_LENGTH = 60;

/** 숙련도 단계 설명 (FR-PRF-001 수용 기준 2, openapi.yaml Level) */
export const proficiencyLabels: Record<Proficiency, string> = {
  1: '입문',
  2: '기초',
  3: '실무 가능',
  4: '능숙',
  5: '전문가',
};

type Request = <T>(path: string, options?: ApiRequestOptions) => Promise<T>;

export const listMySkills = (request: Request) => request<UserSkill[]>('/v1/me/skills');

export const replaceMySkills = (request: Request, body: UserSkillsReplace) =>
  request<UserSkill[]>('/v1/me/skills', { method: 'PUT', body });

export const searchSkills = (request: Request, q: string, limit = 10) =>
  request<{ items: Skill[] }>(`/v1/skills?q=${encodeURIComponent(q)}&limit=${limit}`);
