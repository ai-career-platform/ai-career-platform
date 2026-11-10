import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/errors';
import {
  bucketCount, bucketStart, bucketsBetween, chartSegments, defaultRange, formatAxisValue, formatMetricValue,
  marketTrendErrorMessage, nextBucket, niceMax, parseDate, periodLabel, todayKst, validateRange,
} from './marketTrendFormat';

describe('value formatting (display only, API value unchanged)', () => {
  it.each([
    [0, '0건'], [7, '7건'], [1580, '1,580건'],
  ])('count %d -> %s', (value, text) => expect(formatMetricValue(value, 'count')).toBe(text));

  it.each([
    // T65 §6 hand-computed values (round 4) -> percent with at most 2 decimals, no float noise
    [0.7143, '71.43%'], [0.2857, '28.57%'], [0.1429, '14.29%'], [0.8, '80%'], [0.4, '40%'], [0, '0%'], [1, '100%'],
    [0.0005, '0.05%'], [0.0001, '0.01%'],
  ])('ratio %f -> %s', (value, text) => expect(formatMetricValue(value, 'ratio')).toBe(text));

  it('axis labels keep the unit', () => {
    expect(formatAxisValue(0.25, 'ratio')).toBe('25%');
    expect(formatAxisValue(2500, 'count')).toBe('2,500');
  });
});

describe('KST buckets (T65 §3.2, T67 bucket_count)', () => {
  it('bucket start: week = Monday, month = 1st', () => {
    expect(bucketStart('2026-10-11', 'week')).toBe('2026-10-05'); // Sunday -> Monday before
    expect(bucketStart('2026-10-12', 'week')).toBe('2026-10-12'); // Monday
    expect(bucketStart('2026-10-31', 'month')).toBe('2026-10-01');
    expect(bucketStart('2026-10-31', 'day')).toBe('2026-10-31');
  });

  it('next bucket crosses month and year ends', () => {
    expect(nextBucket('2026-12-28', 'week')).toBe('2027-01-04');
    expect(nextBucket('2026-12-15', 'month')).toBe('2027-01-01');
    expect(nextBucket('2028-02-28', 'day')).toBe('2028-02-29');
  });

  it('bucket count matches the T67 limits', () => {
    expect(bucketCount('2026-01-01', '2026-12-31', 'day')).toBe(365);
    expect(bucketCount('2026-10-07', '2026-10-12', 'week')).toBe(2);
    expect(bucketCount('2022-01-31', '2026-12-01', 'month')).toBe(60);
    expect(bucketsBetween('2026-10-07', '2026-10-20', 'week')).toEqual(['2026-10-05', '2026-10-12', '2026-10-19']);
    expect(bucketsBetween('2026-01-01', '2026-01-01', 'month')).toEqual(['2026-01-01']);
  });

  it('rejects malformed and impossible dates', () => {
    expect(parseDate('2026-02-30')).toBeNull();
    expect(parseDate('2026-1-01')).toBeNull();
    expect(parseDate('2026-02-28')?.toISOString()).toBe('2026-02-28T00:00:00.000Z');
  });
});

describe('query validation', () => {
  it('requires both dates and from <= to', () => {
    expect(validateRange('', '2026-10-01', 'week')).toMatch(/모두 입력/);
    expect(validateRange('2026-10-02', '2026-10-01', 'week')).toMatch(/늦을 수 없습니다/);
    expect(validateRange('2026-10-01', '2026-10-01', 'day')).toBeNull();
  });

  it.each([
    ['day', '2026-01-01', '2027-01-01', '2026-01-01', '2027-01-02'],
    ['week', '2024-01-01', '2026-12-28', '2024-01-01', '2027-01-04'],
    ['month', '2022-01-01', '2026-12-31', '2021-12-01', '2026-12-31'],
  ] as const)('%s: exact limit passes, one more bucket fails', (period, okFrom, okTo, badFrom, badTo) => {
    expect(validateRange(okFrom, okTo, period)).toBeNull();
    expect(validateRange(badFrom, badTo, period)).toMatch(/최대/);
  });
});

describe('default range and labels', () => {
  it('uses the KST date, not UTC', () => {
    expect(todayKst(new Date('2026-11-09T15:30:00Z'))).toBe('2026-11-10'); // 00:30 KST
    expect(defaultRange(new Date('2026-11-10T03:00:00Z'))).toEqual({ from: '2026-08-19', to: '2026-11-10' });
  });

  it('labels periods', () => {
    expect(periodLabel('2026-10-05', 'week')).toBe('2026-10-05 주');
    expect(periodLabel('2026-10-01', 'month')).toBe('2026년 10월');
    expect(periodLabel('2026-10-05', 'day')).toBe('2026-10-05');
  });
});

describe('chart segments: gaps stay gaps', () => {
  const buckets = bucketsBetween('2026-10-05', '2026-11-08', 'week'); // 5 weeks

  it('breaks the line where a bucket has no observation and never inserts zeros', () => {
    const segments = chartSegments([
      { date: '2026-10-05', value: 3 }, { date: '2026-10-12', value: 0 }, { date: '2026-10-26', value: 5 },
    ], buckets, 'week');
    expect(segments).toEqual([
      [{ date: '2026-10-05', value: 3, index: 0 }, { date: '2026-10-12', value: 0, index: 1 }],
      [{ date: '2026-10-26', value: 5, index: 3 }],
    ]);
    expect(segments.flat()).toHaveLength(3);
  });

  it('drops values outside the bucket list (caller reports the mismatch)', () => {
    expect(chartSegments([{ date: '2027-01-04', value: 1 }], buckets, 'week')).toEqual([]);
  });

  it('nice y max', () => {
    expect(niceMax(0, 'count')).toBe(4);
    expect(niceMax(37, 'count')).toBe(40);
    expect(niceMax(0.7143, 'ratio')).toBe(0.8);
    expect(niceMax(1, 'ratio')).toBe(1);
  });
});

describe('error messages never echo server text', () => {
  it.each([
    [401, '로그인'], [404, '찾을 수 없습니다'], [422, '조회 조건'], [0, '네트워크'], [503, '잠시 후'],
  ])('%i', (status, text) => {
    expect(marketTrendErrorMessage(new ApiError(status, '/v1/market-trends', 'internal detail'))).toContain(text);
    expect(marketTrendErrorMessage(new ApiError(status, '/v1/market-trends', 'internal detail'))).not.toContain('internal');
  });
});
