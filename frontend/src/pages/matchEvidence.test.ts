import { describe, expect, it } from 'vitest';
import { buildEvidence } from './matchEvidence';
import type { EvidenceRequirement, EvidenceUserSkill } from './matchEvidence';

/** 고정 fixture: 필수 3개(충족·부족·미보유), 우대 2개(미입력·요구 수준 미등록). */
const requirements: EvidenceRequirement[] = [
  { skill: { skill_id: 's-py', name: 'Python' }, required_level: 3, is_required: true },
  { skill: { skill_id: 's-sql', name: 'SQL' }, required_level: 4, is_required: true },
  { skill: { skill_id: 's-k8s', name: 'Kubernetes' }, required_level: 2, is_required: true },
  { skill: { skill_id: 's-git', name: 'Git' }, required_level: 2, is_required: false },
  { skill: { skill_id: 's-docker', name: 'Docker' }, required_level: null, is_required: false },
];
const mine: EvidenceUserSkill[] = [
  { skill: { skill_id: 's-py' }, proficiency: 5 },
  { skill: { skill_id: 's-sql' }, proficiency: 2 },
  { skill: { skill_id: 's-git' }, proficiency: null },
  { skill: { skill_id: 's-docker' }, proficiency: 3 },
  { skill: { skill_id: 's-react' }, proficiency: 4 }, // 요구 기술이 아니면 표에 나오지 않음
];

describe('적합도 근거 표 (고정 fixture)', () => {
  it('요구 기술마다 상태를 매기고 필수 → 확인 필요 → 이름 순으로 정렬한다', () => {
    expect(buildEvidence(requirements, mine).map((r) => [r.name, r.required, r.status, r.myLevel, r.gap])).toEqual([
      ['Kubernetes', true, 'missing', null, null],
      ['SQL', true, 'short', 2, 2],
      ['Python', true, 'met', 5, null],
      ['Git', false, 'unrated', null, null],
      ['Docker', false, 'level_unknown', 3, null],
    ]);
  });

  it('입력 순서가 바뀌어도 같은 결과를 낸다', () => {
    const expected = buildEvidence(requirements, mine);
    expect(buildEvidence([...requirements].reverse(), [...mine].reverse())).toEqual(expected);
  });

  it('직무 요구 기술처럼 필수 구분이 없으면 모두 필수로 본다', () => {
    const rows = buildEvidence([{ skill: { skill_id: 'a', name: 'A' }, required_level: 1 }], []);
    expect(rows[0]).toMatchObject({ required: true, status: 'missing' });
  });
});
