/**
 * 적합도 결과(T41) 화면의 "근거" 표. 대상의 요구 기술과 **지금** 내 보유 기술을 한 줄씩 견줍니다.
 * 점수는 서버가 계산한 값만 보여 주고, 여기서는 점수를 다시 만들지 않습니다.
 * T41은 계산 입력값을 저장하지 않으므로, 계산 뒤에 보유 기술을 바꾸면 이 표와 점수가 다를 수 있습니다.
 */
import { LEVEL_LABELS } from './skillComparison';

export type EvidenceRequirement = {
  skill: { skill_id: string; name: string };
  /** 공고는 수준이 비어 있을 수 있음(null). 직무 요구 기술은 항상 숫자. */
  required_level: number | null;
  /** 공고만 필수/우대 구분이 있음. 직무 요구 기술은 T41에서 모두 필수로 계산. */
  is_required?: boolean;
};
export type EvidenceUserSkill = { skill: { skill_id: string }; proficiency: number | null };

export type EvidenceStatus = 'met' | 'short' | 'unrated' | 'missing' | 'level_unknown';
export type EvidenceRow = {
  skillId: string;
  name: string;
  required: boolean;
  requiredLevel: number | null;
  myLevel: number | null;
  status: EvidenceStatus;
  /** 부족할 때만 요구 수준 - 내 수준 (1 이상). */
  gap: number | null;
};

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  met: '충족', short: '부족', unrated: '숙련도 미입력', missing: '보유 기술에 없음', level_unknown: '요구 수준 미등록',
};

/** 정렬: 필수 먼저, 그다음 부족·미보유·미입력 등 확인이 필요한 줄, 이름순. 입력 순서와 무관하게 같은 결과. */
const STATUS_ORDER: Record<EvidenceStatus, number> = { missing: 0, short: 1, unrated: 2, level_unknown: 3, met: 4 };

export function buildEvidence(
  requirements: readonly EvidenceRequirement[],
  mine: readonly EvidenceUserSkill[],
): EvidenceRow[] {
  const owned = new Map(mine.map((item) => [item.skill.skill_id, item.proficiency] as const));
  return requirements.map((item): EvidenceRow => {
    const base = {
      skillId: item.skill.skill_id, name: item.skill.name,
      required: item.is_required ?? true, requiredLevel: item.required_level,
    };
    if (!owned.has(item.skill.skill_id)) return { ...base, myLevel: null, status: 'missing', gap: null };
    const level = owned.get(item.skill.skill_id) ?? null;
    if (level === null) return { ...base, myLevel: null, status: 'unrated', gap: null };
    if (item.required_level === null) return { ...base, myLevel: level, status: 'level_unknown', gap: null };
    return level >= item.required_level
      ? { ...base, myLevel: level, status: 'met', gap: null }
      : { ...base, myLevel: level, status: 'short', gap: item.required_level - level };
  }).sort((a, b) => Number(b.required) - Number(a.required)
    || STATUS_ORDER[a.status] - STATUS_ORDER[b.status]
    || a.name.localeCompare(b.name, 'ko') || a.skillId.localeCompare(b.skillId));
}

export function shortLevel(level: number | null): string {
  if (level === null) return '—';
  const label = LEVEL_LABELS[level];
  return label ? `${level} · ${label}` : String(level);
}
