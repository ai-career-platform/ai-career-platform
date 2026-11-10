import { FEATURE_LABELS, type AuditEvent, type UsageGroupBy } from '../../api/adminAudit';

const KST_MS = 9 * 3_600_000;

const dateTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const integer = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 });

/** 서버 시각(UTC ISO) → KST 표시 */
export const formatKstDateTime = (iso: string) => `${dateTime.format(new Date(iso))} KST`;
export const formatInteger = (value: number) => integer.format(value);
/** 서버가 준 추정값을 그대로 표시합니다(재계산·반올림 변경 없음, 최대 소수 6자리). */
export const formatUsd = (value: number) => usd.format(value);

/**
 * 화면 표시용 UUID 줄임(앞 8 + 끝 4). **보호 장치가 아닙니다** — 확정 API 응답에는 원래 UUID 가 그대로 오고
 * 브라우저 메모리·네트워크에는 남습니다. 화면·캡처 노출만 줄입니다(서버 마스킹 D3 은 미승인).
 */
export function shortenId(id: string | null): string | null {
  if (!id) return null;
  const hex = id.replace(/-/g, '');
  return `${hex.slice(0, 8)}…${hex.slice(-4)}`;
}

export function actorLabel(event: AuditEvent): string {
  const short = shortenId(event.actor_user_id);
  return short ? `사용자 ${short}` : '시스템 또는 탈퇴 익명화';
}

export function resourceLabel(event: AuditEvent): string {
  if (!event.resource_id) return event.resource_type;
  return `${event.resource_type} ${event.resource_type === 'user' ? shortenId(event.resource_id) : event.resource_id}`;
}

/** Date → datetime-local 입력값 (KST, 분 단위) */
export function toKstInput(date: Date): string {
  return new Date(date.getTime() + KST_MS).toISOString().slice(0, 16);
}

/** datetime-local 입력값(KST) → 오프셋이 있는 ISO. 형식이 틀리면 null */
export function kstInputToIso(value: string): string | null {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) ? `${value}:00+09:00` : null;
}

/** Date → KST 날짜 (YYYY-MM-DD) */
export function kstDate(date: Date): string {
  return new Date(date.getTime() + KST_MS).toISOString().slice(0, 10);
}

export function usageKeyLabel(groupBy: UsageGroupBy, key: string): string {
  if (groupBy === 'day') return `${key} (KST)`;
  if (groupBy === 'feature_code') return FEATURE_LABELS[key] ? `${FEATURE_LABELS[key]} (${key})` : key;
  return key;
}
