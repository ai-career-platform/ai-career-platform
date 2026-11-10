/**
 * T68 채용시장 추세 화면의 날짜·구간·수치 표시 규칙. 그래프와 표가 모두 이 함수만 써서
 * 같은 API 값을 같은 문구로 보여줍니다. 값 자체(API 원본)는 바꾸지 않고 표시 문자열만 만듭니다.
 * 구간 규칙은 T65 계약 §3.2·§8 과 T67 서비스(bucket_count, MAX_POINTS)를 따릅니다.
 */
import { ApiError } from '../api/errors';
import type { MarketMetricCode, MarketPeriod, MarketPoint, MarketUnit } from '../api/marketTrends';

/** 화면에 항상 표시하는 대표성 한계 문구 */
export const MARKET_DISCLAIMER = '본 통계는 수집된 채용공고를 기준으로 하며 전체 채용시장을 대표하지 않습니다.';

/** API 오류를 화면 문구로 바꿉니다. 응답 원문·내부 정보는 보여주지 않습니다. */
export function marketTrendErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return '로그인이 필요합니다. 다시 로그인해 주세요.';
    if (error.status === 404) return '선택한 직무·기술·출처를 찾을 수 없습니다. 조건을 다시 선택해 주세요.';
    if (error.status === 422) {
      return '조회 조건을 확인해 주세요. 기간이 너무 길거나, 관측값의 출처가 여러 개라 출처를 정해야 할 수 있습니다.';
    }
    if (error.status === 0) return '네트워크 연결을 확인한 뒤 다시 시도해 주세요.';
  }
  return '채용시장 추세를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
}

export const METRIC_UNITS: Record<MarketMetricCode, MarketUnit> = {
  posting_count: 'count',
  skill_demand_share: 'ratio',
};

export const METRIC_LABELS: Record<MarketMetricCode, string> = {
  posting_count: '신규 게시 공고 수',
  skill_demand_share: '기술 요구 비율',
};

/** T65 계약 §1·§3 지표 정의를 화면 문구로 옮긴 것 */
export const METRIC_DEFINITIONS: Record<MarketMetricCode, string> = {
  posting_count:
    '구간 안에 새로 게시된 공고 수(건)입니다. 게시 시각(KST) 기준으로 구간에 넣고, 마감된 공고도 게시된 구간에 포함합니다. 작성 중 공고는 제외합니다.',
  skill_demand_share:
    '구간 안 신규 공고 중 선택한 기술을 요구한 공고의 비율입니다. 서버 값은 0~1 비율(소수 넷째 자리 반올림)이고 화면에는 퍼센트로 표시합니다. 같은 범위의 공고가 5건 미만인 구간은 계산하지 않습니다.',
};

export const PERIOD_LABELS: Record<MarketPeriod, string> = { day: '일', week: '주', month: '월' };

/** T67 MAX_POINTS: 한 번에 조회할 수 있는 구간 수 상한 */
export const MAX_BUCKETS: Record<MarketPeriod, number> = { day: 366, week: 157, month: 60 };

const DAY_MS = 86_400_000;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** YYYY-MM-DD → UTC 자정 Date (달력 날짜 계산용, 시간대 영향 없음). 형식이 틀리면 null */
export function parseDate(text: string): Date | null {
  if (!ISO_DATE.test(text)) return null;
  const date = new Date(`${text}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== text ? null : date;
}

const iso = (date: Date) => date.toISOString().slice(0, 10);

/** 날짜가 속한 구간 시작일 (주=월요일, 월=1일) */
export function bucketStart(text: string, period: MarketPeriod): string {
  const date = parseDate(text);
  if (!date) return text;
  if (period === 'day') return text;
  if (period === 'week') return iso(new Date(date.getTime() - ((date.getUTCDay() + 6) % 7) * DAY_MS));
  return `${text.slice(0, 7)}-01`;
}

/** 다음 구간 시작일 */
export function nextBucket(text: string, period: MarketPeriod): string {
  const date = parseDate(bucketStart(text, period))!;
  if (period === 'day') return iso(new Date(date.getTime() + DAY_MS));
  if (period === 'week') return iso(new Date(date.getTime() + 7 * DAY_MS));
  return iso(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)));
}

/** [from, to] 가 걸치는 구간 수 (T67 bucket_count 와 같은 규칙) */
export function bucketCount(from: string, to: string, period: MarketPeriod): number {
  const a = parseDate(bucketStart(from, period));
  const b = parseDate(bucketStart(to, period));
  if (!a || !b) return 0;
  if (period === 'month') {
    return (b.getUTCFullYear() * 12 + b.getUTCMonth()) - (a.getUTCFullYear() * 12 + a.getUTCMonth()) + 1;
  }
  return Math.round((b.getTime() - a.getTime()) / (period === 'week' ? 7 * DAY_MS : DAY_MS)) + 1;
}

/** [from, to] 가 걸치는 구간 시작일 목록. 그래프 X축 위치에만 쓰고 값을 만들지 않습니다. */
export function bucketsBetween(from: string, to: string, period: MarketPeriod): string[] {
  const count = bucketCount(from, to, period);
  if (count <= 0 || count > MAX_BUCKETS[period]) return [];
  const result: string[] = [];
  for (let current = bucketStart(from, period); result.length < count; current = nextBucket(current, period)) {
    result.push(current);
  }
  return result;
}

/** 조회 조건 검사. 서버(T67)도 같은 조건을 422 로 막지만, 잘못된 요청은 보내지 않습니다. */
export function validateRange(from: string, to: string, period: MarketPeriod): string | null {
  if (!parseDate(from) || !parseDate(to)) return '시작일과 종료일을 모두 입력해 주세요.';
  if (from > to) return '시작일은 종료일보다 늦을 수 없습니다.';
  if (bucketCount(from, to, period) > MAX_BUCKETS[period]) {
    const limits = { day: '366일', week: '157주', month: '60개월' };
    return `${PERIOD_LABELS[period]} 단위는 최대 ${limits[period]}까지 조회할 수 있습니다. 기간을 줄여 주세요.`;
  }
  return null;
}

/** 오늘 날짜 (KST) */
export function todayKst(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(now);
}

/** 기본 조회 기간: 오늘(KST)까지 최근 12주 */
export function defaultRange(now: Date = new Date()): { from: string; to: string } {
  const to = todayKst(now);
  return { from: iso(new Date(parseDate(to)!.getTime() - 83 * DAY_MS)), to };
}

/** 구간 이름: 일 2026-10-05 / 주 2026-10-05 주(월~일) / 월 2026년 10월 */
export function periodLabel(date: string, period: MarketPeriod): string {
  if (period === 'week') return `${date} 주`;
  if (period === 'month') return `${date.slice(0, 4)}년 ${Number(date.slice(5, 7))}월`;
  return date;
}

const countFormat = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const percentFormat = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

/**
 * 표시용 수치. count → "1,234건", ratio(0~1) → "71.43%".
 * ratio 는 서버가 소수 넷째 자리로 반올림한 값이므로 ×100 하면 소수 둘째 자리까지 정확히 나옵니다.
 */
export function formatMetricValue(value: number, unit: MarketUnit): string {
  if (unit === 'ratio') return `${percentFormat.format(Math.round(value * 10_000) / 100)}%`;
  return `${countFormat.format(value)}건`;
}

/** 축 눈금 문구 (단위 표기 포함) */
export function formatAxisValue(value: number, unit: MarketUnit): string {
  return unit === 'ratio' ? `${percentFormat.format(Math.round(value * 1000) / 10)}%` : countFormat.format(value);
}

export type PlacedPoint = MarketPoint & { index: number };

/**
 * 관측값을 X 위치(구간 순번)에 놓고, 구간이 이어지지 않는 곳에서 선을 끊습니다.
 * 관측이 없는 구간은 0으로 채우지도, 선으로 잇지도 않습니다(T65 §3.4).
 * 조회 구간 목록에 놓을 수 없는 값은 그래프에 넣지 않습니다. 화면은 그 수를 세어 표와 다르다고 알립니다.
 */
export function chartSegments(observations: MarketPoint[], buckets: string[], period: MarketPeriod): PlacedPoint[][] {
  const position = new Map(buckets.map((bucket, index) => [bucket, index]));
  const segments: PlacedPoint[][] = [];
  let previous: number | null = null;
  for (const point of observations) {
    const index = position.get(bucketStart(point.date, period));
    if (index === undefined) continue;
    if (previous === null || index !== previous + 1) segments.push([]);
    segments[segments.length - 1]!.push({ ...point, index });
    previous = index;
  }
  return segments;
}

/** Y축 상한: 데이터 최댓값보다 크거나 같은 보기 좋은 값 (ratio 는 1 을 넘지 않음) */
export function niceMax(max: number, unit: MarketUnit): number {
  if (unit === 'ratio') {
    if (max <= 0) return 1;
    return Math.min(1, Math.ceil(max * 10) / 10);
  }
  if (max <= 0) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * magnitude >= max / 4)! * magnitude;
  return Math.ceil(max / step) * step;
}
