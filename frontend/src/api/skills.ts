/**
 * 내 보유 기술 화면(T34)의 규칙 상수와 숙련도 설명.
 * 호출은 createApi(http).me.skills (T33 GET/PUT /v1/me/skills), .skills.search (T17 GET /v1/skills),
 * .skills.suggest (T139 GET /v1/skills/suggest — PROPOSED, 서버 SKILL_AUTOCOMPLETE_API·화면 VITE_SKILL_AUTOCOMPLETE 모두 기본 꺼짐).
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

/** T139 일치 종류. alias·ambiguous 는 동의어(표준 이름과 다른 표기)로 찾은 경우입니다. */
export type SkillMatchType = 'code' | 'alias' | 'ambiguous' | 'prefix' | 'partial';

/** T139 자동완성 한 건. skill_id 가 null 이면 분류에는 있으나 아직 등록할 수 없는 기술입니다. */
export interface SkillSuggestion {
  code: string;
  name: string;
  match_type: SkillMatchType;
  matched: string;
  skill_id: string | null;
}

export interface SkillSuggestPage {
  items: SkillSuggestion[];
  next_cursor: string | null;
  /** 'none' 이면 서버에 동의어 표가 없어 이름·코드로만 찾은 결과입니다(T137 별칭 표 미적용). */
  alias_source: 'taxonomy' | 'none';
}

/** T137 정규화 규칙(T139 서버와 같음): 공백 제거 → NFKC → 소문자 → 공백·. - _ / 괄호 제거. + 와 # 은 남김. */
export function normalizeSkillTerm(value: string): string {
  return value.trim().normalize('NFKC').toLowerCase().replace(/[\s._/()[\]-]+/g, '');
}
