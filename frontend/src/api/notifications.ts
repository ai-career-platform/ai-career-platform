/**
 * 알림함·수신 설정 화면의 데이터 계약 (T97).
 *
 * - 수신 설정 DTO: T95 제안 OpenAPI(docs/notifications/t95_openapi_proposal.yaml) 그대로 — **PROPOSED, docs/api/openapi.yaml 에 없음**.
 * - 알림함 DTO: 계약 문서가 없어 이 화면이 필요로 하는 최소 형태를 **제안**합니다(docs/testing/T97_NOTIFICATION_UI_VALIDATION.md §3).
 * - 서버(T96 발송 모듈 PR)는 알림함·수신 설정 API 를 제공하지 않습니다 → 지금은 Mock Adapter 만 연결합니다.
 */
import { ApiError } from './errors';

export const NOTIFICATION_TYPES = [
  'security.password_reset', 'security.password_changed', 'security.new_login', 'account.email_verification',
  'account.recovery_notice', 'account.deletion_receipt', 'service.policy_change', 'service.maintenance',
  'recommendation.new_results', 'marketing.newsletter',
] as const;
export type NotificationType = (typeof NOTIFICATION_TYPES)[number];

export type NotificationPreference = {
  type: NotificationType;
  /** true 면 끌 수 없음(보안·인증·복구·법적 고지) */
  required: boolean;
  enabled: boolean;
  consent_policy_code: string | null;
  channels: Array<'email' | 'in_app'>;
};
export type NotificationPreferences = { items: NotificationPreference[] };
export type NotificationPreferencesUpdate = { items: Array<{ type: NotificationType; enabled: boolean }> };

/** 알림함 한 건 (제안). 본문 전체·링크·토큰은 담지 않고 짧은 요약만 둡니다. */
export type InboxItem = {
  notification_id: string;
  type: NotificationType;
  title: string;
  summary: string;
  created_at: string;
  read_at: string | null;
};
export type InboxPage = { items: InboxItem[]; unread_count: number };

export interface NotificationService {
  listInbox(signal?: AbortSignal): Promise<InboxPage>;
  markRead(notificationId: string): Promise<InboxItem>;
  markAllRead(): Promise<{ updated: number }>;
  getPreferences(signal?: AbortSignal): Promise<NotificationPreferences>;
  updatePreferences(update: NotificationPreferencesUpdate): Promise<NotificationPreferences>;
}

export const INBOX_PATH = '/v1/me/notifications';
export const PREFERENCES_PATH = '/v1/me/notification-preferences';

export const TYPE_LABELS: Record<NotificationType, { label: string; group: string; description: string }> = {
  'security.password_reset': { label: '비밀번호 재설정', group: '계정 보안', description: '재설정 링크 안내' },
  'security.password_changed': { label: '비밀번호 변경', group: '계정 보안', description: '비밀번호가 바뀌었을 때' },
  'security.new_login': { label: '새 로그인', group: '계정 보안', description: '새 기기에서 로그인했을 때' },
  'account.email_verification': { label: '이메일 확인', group: '계정', description: '이메일 주소 확인 링크' },
  'account.recovery_notice': { label: '계정 복구', group: '계정', description: '계정 복구 요청 안내' },
  'account.deletion_receipt': { label: '탈퇴 처리 안내', group: '계정', description: '탈퇴 요청 접수·처리 안내' },
  'service.policy_change': { label: '약관·정책 변경', group: '서비스 안내', description: '법적 고지' },
  'service.maintenance': { label: '서비스 점검', group: '서비스 안내', description: '점검 일정 안내' },
  'recommendation.new_results': { label: '새 맞춤 추천', group: '추천', description: '새 추천 결과가 준비됐을 때' },
  'marketing.newsletter': { label: '소식·혜택(광고)', group: '마케팅', description: '광고성 정보. 밤 9시~아침 8시에는 보내지 않습니다' },
};

export function notificationErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.';
    if (error.status === 422) return '필수 알림은 끌 수 없습니다.';
    if (error.status === 404) return '이미 삭제되었거나 볼 수 없는 알림입니다.';
    if (error.userMessage) return error.userMessage;
  }
  return fallback;
}
