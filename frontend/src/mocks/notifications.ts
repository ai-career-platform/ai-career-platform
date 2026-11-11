/**
 * T97 알림함·수신 설정 Mock Adapter — **합성 데이터만**, 네트워크 요청 없음, 실제 메일·알림 발송 없음.
 * 사용자 ID 별로 저장소를 나눠 서버의 본인 격리를 흉내 냅니다(다른 사용자 알림 ID 로 읽음 처리 → 404).
 * 수신 설정 규칙은 T95 매트릭스: 필수는 끌 수 없음(422), 선택 알림 기본값(점검 켬, 추천·마케팅 끔).
 */
import { ApiError } from '../api/errors';
import {
  INBOX_PATH, NOTIFICATION_TYPES, PREFERENCES_PATH,
  type InboxItem, type InboxPage, type NotificationPreference, type NotificationPreferences,
  type NotificationPreferencesUpdate, type NotificationService, type NotificationType,
} from '../api/notifications';

const OPTIONAL: Partial<Record<NotificationType, { consent: string; defaultOn: boolean }>> = {
  'service.maintenance': { consent: 'service_updates', defaultOn: true },
  'recommendation.new_results': { consent: 'recommendation_alerts', defaultOn: false },
  'marketing.newsletter': { consent: 'marketing_notification', defaultOn: false },
};

function defaultPreferences(): NotificationPreference[] {
  return NOTIFICATION_TYPES.map((type) => {
    const optional = OPTIONAL[type];
    return { type, required: !optional, enabled: optional ? optional.defaultOn : true,
      consent_policy_code: optional?.consent ?? null, channels: ['email'] };
  });
}

const HOUR = 3_600_000;
const SEED: Array<Pick<InboxItem, 'type' | 'title' | 'summary'> & { hoursAgo: number; read: boolean }> = [
  { type: 'security.new_login', title: '새 기기 로그인', summary: '새 기기에서 로그인했습니다. 본인이 아니면 비밀번호를 바꿔 주세요.', hoursAgo: 2, read: false },
  { type: 'recommendation.new_results', title: '새 맞춤 추천 3건', summary: '목표 직무에 맞는 새 추천이 준비됐습니다.', hoursAgo: 20, read: false },
  { type: 'service.maintenance', title: '서비스 점검 예정', summary: '11월 20일 02:00~04:00 점검이 있습니다.', hoursAgo: 50, read: true },
  { type: 'service.policy_change', title: '개인정보 처리방침 변경', summary: '12월 1일부터 변경된 처리방침이 적용됩니다.', hoursAgo: 120, read: true },
];

export type MockNotificationOptions = {
  latencyMs?: number;
  now?: () => Date;
  /** 사용자별 알림 시드. 없으면 기본 4건 (빈 상태 시험은 []) */
  seed?: (userId: string) => typeof SEED;
};

type Store = { inbox: InboxItem[]; preferences: NotificationPreference[] };

/** 사용자 하나에 묶인 서비스. 같은 options 로 만든 store 맵을 공유해 사용자 간 격리를 시험합니다. */
export function createMockNotificationBackend(options: MockNotificationOptions = {}) {
  const stores = new Map<string, Store>();
  const now = options.now ?? (() => new Date());
  let failures: Array<'inbox' | 'read' | 'preferences' | 'update'> = [];

  function store(userId: string): Store {
    let s = stores.get(userId);
    if (!s) {
      const base = now().getTime();
      const seed = options.seed ? options.seed(userId) : SEED;
      s = {
        inbox: seed.map((item, i) => ({
          // 사용자 ID·이메일을 ID 에 넣지 않음(경로에 남지 않도록). 사용자마다 다른 접두어
          notification_id: `00000000-0000-4000-8${String(stores.size + 1).padStart(3, '0')}-${String(i + 1).padStart(12, '0')}`,
          type: item.type, title: item.title, summary: item.summary,
          created_at: new Date(base - item.hoursAgo * HOUR).toISOString(),
          read_at: item.read ? new Date(base - (item.hoursAgo - 1) * HOUR).toISOString() : null,
        })),
        preferences: defaultPreferences(),
      };
      stores.set(userId, s);
    }
    return s;
  }

  const wait = (signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, options.latencyMs ?? 0);
    signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
  });
  function maybeFail(kind: (typeof failures)[number], path: string) {
    if (failures[0] !== kind) return;
    failures = failures.slice(1);
    throw new ApiError(0, path);
  }
  const page = (s: Store): InboxPage => ({
    items: [...s.inbox].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((x) => ({ ...x })),
    unread_count: s.inbox.filter((x) => !x.read_at).length,
  });

  return {
    /** 다음 호출(들)을 네트워크 오류로 실패시킵니다(시험용). */
    failNext(...kinds: typeof failures) { failures = [...failures, ...kinds]; },
    snapshot(userId: string) { return structuredClone(store(userId)); },
    serviceFor(userId: string): NotificationService {
      return {
        async listInbox(signal) {
          await wait(signal); maybeFail('inbox', INBOX_PATH);
          return page(store(userId));
        },
        async markRead(id) {
          await wait(); maybeFail('read', INBOX_PATH);
          const item = store(userId).inbox.find((x) => x.notification_id === id);
          if (!item) throw new ApiError(404, `${INBOX_PATH}/${id}/read`, undefined, 'NOT_FOUND');
          item.read_at ??= now().toISOString();
          return { ...item };
        },
        async markAllRead() {
          await wait(); maybeFail('read', INBOX_PATH);
          const unread = store(userId).inbox.filter((x) => !x.read_at);
          for (const item of unread) item.read_at = now().toISOString();
          return { updated: unread.length };
        },
        async getPreferences(signal) {
          await wait(signal); maybeFail('preferences', PREFERENCES_PATH);
          return { items: store(userId).preferences.map((p) => ({ ...p })) };
        },
        async updatePreferences(update: NotificationPreferencesUpdate): Promise<NotificationPreferences> {
          await wait(); maybeFail('update', PREFERENCES_PATH);
          const s = store(userId);
          if (update.items.length < 1 || update.items.length > 20) throw new ApiError(422, PREFERENCES_PATH, undefined, 'VALIDATION_FAILED');
          for (const change of update.items) {
            const current = s.preferences.find((p) => p.type === change.type);
            if (!current || (current.required && !change.enabled)) {
              throw new ApiError(422, PREFERENCES_PATH, undefined, 'VALIDATION_FAILED');
            }
          }
          for (const change of update.items) s.preferences.find((p) => p.type === change.type)!.enabled = change.enabled;
          return { items: s.preferences.map((p) => ({ ...p })) };
        },
      };
    },
  };
}

export type MockNotificationBackend = ReturnType<typeof createMockNotificationBackend>;
