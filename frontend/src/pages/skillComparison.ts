/**
 * 직무 요구 기술(T17)과 내 보유 기술(T33 `GET /me/skills`)의 단순 비교.
 * AI/ML 분석(T26·T27)이 아니라 숫자 대 숫자의 직접 비교이며, 점수·순위를 만들지 않습니다.
 * 숙련도 미입력(null)은 0으로 바꾸지 않고 따로 표시합니다(0 처리는 T04 제안이며 PM 승인 전).
 */
export type RequiredSkillItem = { skill: { skill_id: string; name: string }; required_level: number };
export type UserSkillItem = { skill: { skill_id: string; name: string }; proficiency: number | null };

export type ComparisonStatus = 'met' | 'short' | 'unrated' | 'missing';
export type ComparisonRow = {
  skillId: string;
  name: string;
  requiredLevel: number;
  myLevel: number | null;
  status: ComparisonStatus;
  /** 부족할 때만 요구 수준 - 내 수준 (1 이상). */
  gap: number | null;
};

/** openapi.yaml `Level` 설명과 같은 표기. */
export const LEVEL_LABELS: Record<number, string> = {
  1: '입문', 2: '기초', 3: '실무 가능', 4: '능숙', 5: '전문가',
};

export function levelText(level: number): string {
  const label = LEVEL_LABELS[level];
  return label ? `${level} / 5 · ${label}` : `${level} / 5`;
}

export function compareSkills(
  required: readonly RequiredSkillItem[],
  mine: readonly UserSkillItem[],
): { rows: ComparisonRow[]; metCount: number } {
  const owned = new Map(mine.map((item) => [item.skill.skill_id, item.proficiency] as const));
  const rows = required.map((item): ComparisonRow => {
    const base = { skillId: item.skill.skill_id, name: item.skill.name, requiredLevel: item.required_level };
    if (!owned.has(item.skill.skill_id)) return { ...base, myLevel: null, status: 'missing', gap: null };
    const level = owned.get(item.skill.skill_id) ?? null;
    if (level === null) return { ...base, myLevel: null, status: 'unrated', gap: null };
    return level >= item.required_level
      ? { ...base, myLevel: level, status: 'met', gap: null }
      : { ...base, myLevel: level, status: 'short', gap: item.required_level - level };
  });
  return { rows, metCount: rows.filter((row) => row.status === 'met').length };
}
