/**
 * T146 날짜·숫자 표시 표준. 화면에서 날짜·숫자를 글자로 바꿀 때는 이 함수들을 씁니다.
 *
 * 규칙 (docs/frontend/I18N_A11Y_STANDARD.md)
 * - 시간대는 항상 명시합니다. 기본은 한국 시간(Asia/Seoul, UTC+9, 1988년 이후 서머타임 없음)입니다.
 *   `toLocaleString('ko-KR')`처럼 시간대를 빼면 사용자 PC 시간대에 따라 다른 날짜가 보입니다.
 * - API의 날짜 전용 값(`YYYY-MM-DD`, 예: 지원일)은 시각이 아닙니다. 한국 날짜 그대로 보여 주고 시간대를 옮기지 않습니다.
 * - 값이 없거나 잘못되면 지어내지 않고 fallback을 보여 줍니다.
 * - 외부 라이브러리 없이 브라우저 내장 Intl만 씁니다.
 */

export type Locale = 'ko' | 'en';
export type Zone = 'kst' | 'utc';

export const DEFAULT_LOCALE: Locale = 'ko';
const LOCALE_TAG: Record<Locale, string> = { ko: 'ko-KR', en: 'en-US' };
const ZONE_ID: Record<Zone, string> = { kst: 'Asia/Seoul', utc: 'UTC' };
const KST_OFFSET_MS = 9 * 3_600_000;
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export interface FormatOptions {
  locale?: Locale;
  zone?: Zone;
  fallback?: string;
}

const cache = new Map<string, Intl.DateTimeFormat>();
function dateFormatter(locale: Locale, zone: Zone, kind: 'date' | 'dateTime'): Intl.DateTimeFormat {
  const key = `${locale}|${zone}|${kind}`;
  let formatter = cache.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(LOCALE_TAG[locale], kind === 'date'
      ? { dateStyle: 'medium', timeZone: ZONE_ID[zone] }
      : { dateStyle: 'medium', timeStyle: 'short', timeZone: ZONE_ID[zone] });
    cache.set(key, formatter);
  }
  return formatter;
}

/** ISO 시각 문자열·Date를 Date로. 잘못된 값은 null. */
export function parseInstant(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 날짜+시각. 예: ko `2026. 11. 2. 오전 9:00`, en `Nov 2, 2026, 9:00 AM`. */
export function formatDateTime(value: string | Date | null | undefined, options: FormatOptions = {}): string {
  const date = parseInstant(value);
  if (!date) return options.fallback ?? '—';
  const text = dateFormatter(options.locale ?? DEFAULT_LOCALE, options.zone ?? 'kst', 'dateTime').format(date);
  return options.zone === 'utc' ? `${text} UTC` : text;
}

/** 시각의 날짜 부분만(시간대 기준). 예: 2026-11-10T15:30:00Z → KST `2026. 11. 11.` */
export function formatDate(value: string | Date | null | undefined, options: FormatOptions = {}): string {
  const date = parseInstant(value);
  if (!date) return options.fallback ?? '—';
  return dateFormatter(options.locale ?? DEFAULT_LOCALE, options.zone ?? 'kst', 'date').format(date);
}

/** API 날짜 전용 값 `YYYY-MM-DD`를 그 날짜 그대로 표시. 시간대 변환 없음. */
export function formatDateOnly(value: string | null | undefined, options: Omit<FormatOptions, 'zone'> = {}): string {
  const match = value ? DATE_ONLY.exec(value) : null;
  if (!match) return options.fallback ?? '—';
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  const date = new Date(Date.UTC(y, m - 1, d));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return options.fallback ?? '—';
  return dateFormatter(options.locale ?? DEFAULT_LOCALE, 'utc', 'date').format(date);
}

/** 한국 날짜 키 `YYYY-MM-DD` (날짜 입력·집계 경계용). */
export function kstDateKey(value: string | Date): string | null {
  const date = parseInstant(value);
  return date ? new Date(date.getTime() + KST_OFFSET_MS).toISOString().slice(0, 10) : null;
}

/** 한국 날짜 하루의 UTC 범위 [시작, 다음 날 시작). 검색 조건을 서버에 보낼 때 사용. */
export function kstDayRangeUtc(dateKey: string): { from: string; to: string } | null {
  if (!DATE_ONLY.test(dateKey) || formatDateOnly(dateKey, { fallback: '' }) === '') return null;
  const start = Date.parse(`${dateKey}T00:00:00+09:00`);
  return { from: new Date(start).toISOString(), to: new Date(start + 86_400_000).toISOString() };
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60], ['minute', 60], ['hour', 24], ['day', 7], ['week', 4.348], ['month', 12], ['year', Number.POSITIVE_INFINITY],
];

/** 상대 시각. 예: ko `3시간 전`, `내일`, en `in 2 days`. 기준 시각(now)을 받아 테스트가 결정적입니다. */
export function formatRelative(value: string | Date | null | undefined, now: Date, options: Omit<FormatOptions, 'zone'> = {}): string {
  const date = parseInstant(value);
  if (!date || Number.isNaN(now.getTime())) return options.fallback ?? '—';
  let amount = (date.getTime() - now.getTime()) / 1000;
  const formatter = new Intl.RelativeTimeFormat(LOCALE_TAG[options.locale ?? DEFAULT_LOCALE], { numeric: 'auto' });
  for (const [unit, size] of RELATIVE_STEPS) {
    if (Math.abs(amount) < size) return formatter.format(Math.round(amount), unit);
    amount /= size;
  }
  return formatter.format(Math.round(amount), 'year');
}

/** 정수·소수 숫자. 예: ko `12,345`. */
export function formatNumber(value: number | null | undefined, options: FormatOptions & { maximumFractionDigits?: number } = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return options.fallback ?? '—';
  return new Intl.NumberFormat(LOCALE_TAG[options.locale ?? DEFAULT_LOCALE], { maximumFractionDigits: options.maximumFractionDigits ?? 0 }).format(value);
}

/** 비율(0~1)을 백분율로. 예: 0.1234 → `12.3%`. */
export function formatPercent(ratio: number | null | undefined, options: FormatOptions & { maximumFractionDigits?: number } = {}): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return options.fallback ?? '—';
  return new Intl.NumberFormat(LOCALE_TAG[options.locale ?? DEFAULT_LOCALE], { style: 'percent', maximumFractionDigits: options.maximumFractionDigits ?? 1 }).format(ratio);
}

/** 파일 크기. 1024 단위, 예: `1.5 MB`. 단위 표기는 언어와 무관하게 B/KB/MB/GB. */
export function formatBytes(bytes: number | null | undefined, options: FormatOptions = {}): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return options.fallback ?? '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${formatNumber(value, { locale: options.locale, maximumFractionDigits: unit === 0 ? 0 : 1 })} ${units[unit]}`;
}
