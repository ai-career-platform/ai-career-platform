import { describe, expect, it } from 'vitest';
import { compareSkills, levelText } from './skillComparison';

const req = (id: string, level: number) => ({ skill: { skill_id: id, name: `S-${id}` }, required_level: level });
const own = (id: string, proficiency: number | null) => ({ skill: { skill_id: id, name: `S-${id}` }, proficiency });

describe('compareSkills', () => {
  it('classifies met, short, unrated and missing without turning unrated into 0', () => {
    const { rows, metCount } = compareSkills(
      [req('a', 3), req('b', 4), req('c', 2), req('d', 1)],
      [own('a', 3), own('b', 2), own('c', null)],
    );
    expect(rows.map((row) => row.status)).toEqual(['met', 'short', 'unrated', 'missing']);
    expect(rows[1]).toMatchObject({ myLevel: 2, gap: 2 });
    expect(rows[2]).toMatchObject({ myLevel: null, gap: null });
    expect(rows[3]).toMatchObject({ myLevel: null, gap: null });
    expect(rows.every((row) => row.myLevel !== 0)).toBe(true);
    expect(metCount).toBe(1);
  });

  it('treats a higher level as met and ignores skills the role does not ask for', () => {
    const { rows } = compareSkills([req('a', 2)], [own('a', 5), own('zzz', 1)]);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.status).toBe('met');
  });

  it('handles empty inputs', () => {
    expect(compareSkills([], [own('a', 1)])).toEqual({ rows: [], metCount: 0 });
    expect(compareSkills([req('a', 1)], []).rows[0]?.status).toBe('missing');
  });
});

describe('levelText', () => {
  it('uses the API contract level names and falls back for unknown levels', () => {
    expect(levelText(3)).toBe('3 / 5 · 실무 가능');
    expect(levelText(9)).toBe('9 / 5');
  });
});
