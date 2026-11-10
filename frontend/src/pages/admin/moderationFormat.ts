import { OPEN_STATUSES, type ModerationStatus } from '../../api/moderation';

const dateFormat = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
});

export function formatDateTime(iso: string | null): string {
  return iso ? dateFormat.format(new Date(iso)) : '—';
}

/** 열린 건이 기한을 넘겼는지 (경고 표시만, 자동 처리 없음) */
export function isOverdue(dueAt: string, status: ModerationStatus, now: Date = new Date()): boolean {
  return OPEN_STATUSES.includes(status) && new Date(dueAt) < now;
}

export function assigneeLabel(assigneeId: string | null, viewerId: string | undefined): string {
  if (!assigneeId) return '미배정';
  return assigneeId === viewerId ? `나 (${assigneeId})` : assigneeId;
}
