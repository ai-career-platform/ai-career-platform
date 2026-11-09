import { describe, expect, it } from 'vitest';
import { employmentLabel, formatDate, safeExternalUrl, uuidOrEmpty } from './postingFormat';

describe('postingFormat', () => {
  it('labels known employment types, passes unknown ones through, and admits missing ones', () => {
    expect(employmentLabel('full_time')).toBe('정규직');
    expect(employmentLabel('intern')).toBe('인턴');
    expect(employmentLabel('freelance')).toBe('freelance');
    expect(employmentLabel(null)).toBe('고용형태 미등록');
  });

  it('formats dates in Korea time and never invents a missing or invalid date', () => {
    expect(formatDate('2026-12-31T00:00:00Z')).toBe('2026년 12월 31일');
    expect(formatDate('2026-12-31T20:00:00Z')).toBe('2027년 1월 1일');
    expect(formatDate(null)).toBe('미등록');
    expect(formatDate(null, '미정')).toBe('미정');
    expect(formatDate('not-a-date')).toBe('미등록');
  });

  it('allows only plain http(s) external links', () => {
    expect(safeExternalUrl('https://example.com/a?b=1')).toEqual({ href: 'https://example.com/a?b=1', host: 'example.com' });
    expect(safeExternalUrl('http://example.com')?.host).toBe('example.com');
    for (const bad of ['javascript:alert(1)', 'data:text/html,hi', 'ftp://example.com', 'https://user:pw@example.com', '//example.com', '', null, undefined]) {
      expect(safeExternalUrl(bad)).toBeNull();
    }
  });

  it('keeps only UUID-shaped ids from the URL', () => {
    expect(uuidOrEmpty('11111111-1111-4111-8111-111111111111')).toBe('11111111-1111-4111-8111-111111111111');
    expect(uuidOrEmpty('1; drop')).toBe('');
    expect(uuidOrEmpty(null)).toBe('');
  });
});
