import { afterEach, describe, expect, it } from 'vitest';
import {
  formatBytes, formatDate, formatDateOnly, formatDateTime, formatNumber, formatPercent, formatRelative,
  kstDateKey, kstDayRangeUtc, parseInstant,
} from './format';
import { MESSAGES, t } from './messages';

/** ICU 버전에 따라 en-US 시각 앞 공백이 U+202F 일 수 있어 일반 공백으로 맞춘다. */
const plain = (text: string) => text.replace(/[  ]/g, ' ');
const HOST_ZONES = ['UTC', 'America/Los_Angeles', 'Asia/Seoul', 'Pacific/Kiritimati', 'Pacific/Pago_Pago', 'Europe/London'];
const originalTz = process.env.TZ;
afterEach(() => { process.env.TZ = originalTz; });

// 2026-11-10 15:30 UTC = 2026-11-11 00:30 KST (한국 날짜가 바뀌는 경계)
const BOUNDARY = '2026-11-10T15:30:00Z';

describe('timezone is explicit: same output on every host timezone', () => {
  it('host timezone really changes local Date getters (the test is meaningful)', () => {
    const date = new Date(BOUNDARY);
    process.env.TZ = 'Pacific/Pago_Pago';   // UTC-11
    const west = date.getDate();
    process.env.TZ = 'Pacific/Kiritimati';  // UTC+14
    const east = date.getDate();
    expect(west).not.toBe(east);
  });

  it.each(HOST_ZONES)('host TZ=%s → KST date/time unchanged', (zone) => {
    process.env.TZ = zone;
    expect(formatDate(BOUNDARY)).toBe('2026. 11. 11.');
    expect(plain(formatDateTime(BOUNDARY))).toBe('2026. 11. 11. 오전 12:30');
    expect(kstDateKey(BOUNDARY)).toBe('2026-11-11');
    expect(formatDateOnly('2026-11-10')).toBe('2026. 11. 10.');
  });

  it('UTC display is labelled so it is not mistaken for KST', () => {
    expect(formatDate(BOUNDARY, { zone: 'utc' })).toBe('2026. 11. 10.');
    expect(plain(formatDateTime(BOUNDARY, { zone: 'utc' }))).toBe('2026. 11. 10. 오후 3:30 UTC');
  });

  it('KST has no daylight saving: offset is +9 in January and July', () => {
    expect(kstDateKey('2026-01-15T15:00:00Z')).toBe('2026-01-16');
    expect(kstDateKey('2026-07-15T15:00:00Z')).toBe('2026-07-16');
    expect(kstDateKey('2026-07-15T14:59:59Z')).toBe('2026-07-15');
  });

  it('KST day → UTC range for server queries', () => {
    expect(kstDayRangeUtc('2026-11-11')).toEqual({ from: '2026-11-10T15:00:00.000Z', to: '2026-11-11T15:00:00.000Z' });
    expect(kstDayRangeUtc('2026-02-30')).toBeNull();
    expect(kstDayRangeUtc('11/11/2026')).toBeNull();
  });
});

describe('English locale', () => {
  it('formats date, time, numbers in en-US', () => {
    expect(formatDate(BOUNDARY, { locale: 'en' })).toBe('Nov 11, 2026');
    expect(plain(formatDateTime(BOUNDARY, { locale: 'en' }))).toBe('Nov 11, 2026, 12:30 AM');
    expect(formatNumber(1234567, { locale: 'en' })).toBe('1,234,567');
    expect(formatPercent(0.1234, { locale: 'en' })).toBe('12.3%');
    expect(formatDateOnly('2026-03-01', { locale: 'en' })).toBe('Mar 1, 2026');
  });
});

describe('invalid and missing values never invent data', () => {
  it.each([null, undefined, '', 'not-a-date', '2026-13-45T00:00:00Z'])('%s → fallback', (value) => {
    expect(formatDate(value)).toBe('—');
    expect(formatDateTime(value, { fallback: '없음' })).toBe('없음');
    expect(parseInstant(value)).toBeNull();
  });
  it('date-only rejects impossible dates and timestamps', () => {
    expect(formatDateOnly('2026-02-29')).toBe('—');
    expect(formatDateOnly('2028-02-29')).toBe('2028. 2. 29.');
    expect(formatDateOnly('2026-11-10T00:00:00Z')).toBe('—');
  });
  it('numbers: NaN/Infinity/negative bytes → fallback', () => {
    expect(formatNumber(Number.NaN)).toBe('—');
    expect(formatPercent(Number.POSITIVE_INFINITY)).toBe('—');
    expect(formatBytes(-1)).toBe('—');
  });
});

describe('numbers, bytes and relative time', () => {
  it('Korean grouping and percent', () => {
    expect(formatNumber(12345)).toBe('12,345');
    expect(formatNumber(1.256, { maximumFractionDigits: 2 })).toBe('1.26');
    expect(formatPercent(0.5)).toBe('50%');
  });
  it('bytes use 1024 steps', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1023)).toBe('1,023 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(10 * 1024 * 1024)).toBe('10 MB');
  });
  it('relative time is deterministic with an injected clock', () => {
    const now = new Date('2026-11-11T00:00:00Z');
    expect(formatRelative('2026-11-10T21:00:00Z', now)).toBe('3시간 전');
    expect(formatRelative('2026-11-12T00:00:00Z', now)).toBe('내일');
    expect(formatRelative('2026-11-13T00:00:00Z', now, { locale: 'en' })).toBe('in 2 days');
    expect(formatRelative('2026-11-11T00:00:20Z', now, { locale: 'en' })).toBe('in 20 seconds');
    expect(formatRelative('bad', now)).toBe('—');
  });
});

describe('message catalogue', () => {
  it('ko and en have the same keys and no empty text', () => {
    expect(Object.keys(MESSAGES.en).sort()).toEqual(Object.keys(MESSAGES.ko).sort());
    for (const table of Object.values(MESSAGES)) for (const text of Object.values(table)) expect(text.trim()).not.toBe('');
  });
  it('placeholders match between languages', () => {
    const names = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(MESSAGES.ko) as (keyof typeof MESSAGES.ko)[]) {
      expect({ key, names: names(MESSAGES.en[key]) }).toEqual({ key, names: names(MESSAGES.ko[key]) });
    }
  });
  it('t() substitutes params and keeps unknown placeholders visible', () => {
    expect(t('form.tooLong', { name: '이름', max: 40 })).toBe('이름은(는) 40자 이하로 입력해 주세요.');
    expect(t('form.required', {}, 'en')).toBe('Enter {name}.');
    expect(t('action.retry', {}, 'en')).toBe('Try again');
  });
  it('the skip link copy in the layout matches the standard', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const layout = readFileSync(resolve(process.cwd(), 'src/layouts/AppLayout.tsx'), 'utf8');
    expect(layout).toContain(MESSAGES.ko['nav.skip']);
  });
});
