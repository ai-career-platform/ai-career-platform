/**
 * 내 보유 기술 화면(T34)의 규칙 상수와 숙련도 설명.
 * 호출은 createApi(http).me.skills (T33 GET/PUT /v1/me/skills), .skills.search (T17 GET /v1/skills).
 */
import type { Proficiency } from './me';

export type { Skill } from './catalog';
export type { Proficiency, UserSkill, UserSkillsReplace } from './me';

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
