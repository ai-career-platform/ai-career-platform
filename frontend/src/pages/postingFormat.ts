/** T18 `/job-postings` 응답을 화면 문구로 바꾸는 순수 함수들. API가 주지 않은 값은 만들어 내지 않습니다. */

export type EmploymentType = 'full_time' | 'contract' | 'intern' | 'part_time';

const EMPLOYMENT_LABELS: Record<EmploymentType, string> = {
  full_time: '정규직', contract: '계약직', intern: '인턴', part_time: '파트타임',
};

export function employmentLabel(value: string | null): string {
  if (!value) return '고용형태 미등록';
  return EMPLOYMENT_LABELS[value as EmploymentType] ?? value;
}

/** ISO 시각을 한국 날짜로. 값이 없거나 잘못되면 fallback(모르면 모른다고 표시). */
export function formatDate(value: string | null, fallback = '미등록'): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * 외부로 나가는 링크는 http(s) 만 허용하고 계정 정보가 들어 있는 주소는 막습니다.
 * 반환값은 정규화된 href 와 화면에 보여 줄 호스트 이름입니다.
 */
export function safeExternalUrl(value: string | null | undefined): { href: string; host: string } | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return { href: url.href, host: url.host };
  } catch {
    return null;
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** URL 에서 읽은 ID 가 UUID 모양이 아니면 버려서 엉뚱한 요청이 나가지 않게 합니다. */
export function uuidOrEmpty(value: string | null): string {
  return value && UUID.test(value) ? value : '';
}
